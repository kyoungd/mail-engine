"""Time zone (docs/contact-engine/03-time-zone.md §4.2-§4.5).

The zones a contact could be in are its area code's zones and its state's zones, both
from `domain.zones`; a zone the holding rep or an admin set replaces them. A moment is
inside calling hours only when it is inside the window in every zone.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from config.params import CALLING_WINDOW_END, CALLING_WINDOW_START, HOUSE_PARTNER_ID
from db.session import transaction
from domain.errors import ValidationError
from domain.zones import TABLE, ZONES


@dataclass(frozen=True)
class SetBy:
    actor: str
    rep: UUID | None
    at: datetime


@dataclass(frozen=True)
class CallingHours:
    zones: frozenset[str]
    set_by: SetBy | None
    local: dict[str, datetime]
    inside: bool | None


def _aware(at: datetime) -> None:
    if at.tzinfo is None:
        raise ValidationError("bad_time", "at must carry a time zone")


def _evidence(phone: str | None, state: str | None) -> frozenset[str]:
    area = TABLE.area(phone[2:5]) if phone and phone.startswith("+1") else frozenset()
    return area | TABLE.state((state or "").strip().upper())


def calling_hours(contact_id: UUID, at: datetime) -> CallingHours:
    _aware(at)
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select phone_e164, addr_state from contacts where id = %s", (contact_id,)
            )
            contact = cur.fetchone()
            if contact is None:
                raise ValidationError("no_contact", f"no contact {contact_id}")
            cur.execute(
                "select zone, actor, rep_id, at from contact_zones where contact_id = %s "
                "order by seq desc limit 1",
                (contact_id,),
            )
            latest = cur.fetchone()

    if latest is not None:
        zone, actor, rep, set_at = latest
        zones = frozenset({zone})
        set_by = SetBy(actor=actor, rep=rep, at=set_at)
    else:
        zones = _evidence(*contact)
        set_by = None

    local = {z: at.astimezone(ZoneInfo(z)) for z in zones}
    inside = (
        all(CALLING_WINDOW_START <= t.time() < CALLING_WINDOW_END for t in local.values())
        if zones else None
    )
    return CallingHours(zones=zones, set_by=set_by, local=local, inside=inside)


def set_zone(
    contact_id: UUID,
    zone: str,
    at: datetime,
    *,
    rep: UUID | None = None,
    actor: str | None = None,
) -> str:
    """The holding rep's or an admin's zone for a contact (§4.5, answer 3)."""
    _aware(at)
    if (rep is None) == (actor is None) or (actor is not None and not actor.strip()):
        raise ValidationError("bad_actor", "give a rep, or an admin's actor, not both")
    if zone not in ZONES:
        raise ValidationError("bad_zone", f"unknown zone {zone!r}")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select owner_id from contacts where id = %s for update", (contact_id,)
            )
            contact = cur.fetchone()
            if contact is None:
                raise ValidationError("no_contact", f"no contact {contact_id}")
            if rep is not None:
                cur.execute("select 1 from partners where id = %s", (rep,))
                if rep == HOUSE_PARTNER_ID or cur.fetchone() is None:
                    raise ValidationError("bad_rep", f"no rep {rep}")
                if contact[0] != rep:
                    raise ValidationError("not_yours", "the rep does not hold this contact")
            cur.execute(
                "insert into contact_zones (contact_id, zone, actor, rep_id, at) "
                "values (%s, %s, %s, %s, %s)",
                (contact_id, zone, str(rep) if actor is None else actor.strip(), rep, at),
            )
    return "set"
