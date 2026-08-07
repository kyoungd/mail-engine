"""The referral import (partner-sourced-leads.md rev 5 §3): a partner's own
collected numbers, with the permission provenance that justifies calling them.

Fails closed on provenance — no who/when/where, no number — because the recorded
permission is what puts the number on their sheet without an FTC-registry check
(§4). Resolution is by phone against the phone-unique contacts spine, and the
four cases differ: a new number becomes an attributed contact; an existing
UNOWNED one has custody moved to the partner (operator decision 2026-08-06 —
"he worked for it"); one already theirs records the permission and leaves custody
alone; one held by ANOTHER partner is a conflict where nothing moves and the
report carries the evidence for the operator to adjudicate.

Not a bulk-list path: `load_list` cannot be reused (it rejects rows without a
trade or segment, dedupes on a `list_key` a referral has no notion of, and
inserts a fixed intake tuple). There is no referral intake table — the
`contact.permission_recorded` event is the record and the CSV file is the archive.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from config.params import HOUSE_PARTNER_ID, PERSONAL_WINDOW_DAYS
from db.session import transaction
from domain.phone import to_e164
from judgment.rules.batch_checkpoint import ACTIVITY_TYPES
from service.custody import set_owner
from service.ingestion import append_event

REQUIRED = ("phone", "permission_by", "permission_at", "permission_where", "sourced_by")
SOURCE = "referral"


@dataclass(frozen=True)
class Rejected:
    row: int
    reason: str


@dataclass(frozen=True)
class Conflict:
    row: int
    contact_id: UUID
    phone: str
    held_by: str
    held_since: datetime | None
    activity: int
    demo_calls: dict[str, int]


@dataclass(frozen=True)
class Cliff:
    """A row on the sheet now that will need DNC clearance when its window ends —
    registry-listed, or in an area code we do not subscribe to. The operator sees
    the date at import instead of noticing an absence three months later."""

    phone: str
    expires_on: date
    why: str


@dataclass(frozen=True)
class ImportReport:
    created: int = 0
    took_custody: int = 0
    already_theirs: int = 0
    rejected: list[Rejected] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    cliffs: list[Cliff] = field(default_factory=list)


def _validate(row: dict, index: int) -> tuple[dict | None, Rejected | None]:
    missing = [f for f in REQUIRED if not str(row.get(f) or "").strip()]
    if missing:
        return None, Rejected(index, f"missing required field(s): {', '.join(missing)}")
    phone = to_e164(str(row["phone"]))
    if phone is None:
        return None, Rejected(index, f"phone {row['phone']!r} is not a US number")
    try:
        permission_at = date.fromisoformat(str(row["permission_at"]).strip())
    except ValueError:
        return None, Rejected(
            index, f"permission_at {row['permission_at']!r} is not YYYY-MM-DD"
        )
    return (
        {**row, "phone_e164": phone, "permission_at_date": permission_at},
        None,
    )


def _partner(cur, name: str) -> tuple[UUID | None, str | None]:
    cur.execute("select id, status from partners where name = %s", (name,))
    found = cur.fetchone()
    if found is None:
        return None, f"no partner named {name!r}"
    if found[1] != "active":
        return None, f"partner {name!r} is inactive"
    return found[0], None


def _activity(cur, contact_id: UUID) -> int:
    cur.execute(
        "select count(*) from events where contact_id = %s and type = any(%s)",
        (contact_id, list(ACTIVITY_TYPES)),
    )
    row = cur.fetchone()
    return row[0] if row else 0


def _cliff(cur, contact_id: UUID, phone: str, permission_at: date) -> Cliff | None:
    cur.execute(
        "select dnc_registry, "
        "(substring(phone_e164 from 3 for 3) in "
        "  (select area_code from dnc_subscriptions)) as subscribed "
        "from contacts where id = %s",
        (contact_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    listed, subscribed = row
    why = (
        "on the DNC registry" if listed
        else ("area code not subscribed" if not subscribed else None)
    )
    if why is None:
        return None
    return Cliff(
        phone=phone,
        expires_on=permission_at + timedelta(days=PERSONAL_WINDOW_DAYS),
        why=why,
    )


def import_collected(rows: list[dict], *, actor: str) -> ImportReport:
    """Import one partner-collected CSV, already parsed into dicts. Each row
    commits in its own transaction, so one bad row cannot roll back the rows
    already imported."""
    created = took = theirs = 0
    rejected: list[Rejected] = []
    conflicts: list[Conflict] = []
    cliffs: list[Cliff] = []

    for index, raw in enumerate(rows, start=1):
        clean, bad = _validate(raw, index)
        if bad is not None:
            rejected.append(bad)
            continue
        assert clean is not None
        phone = clean["phone_e164"]
        permission_at: date = clean["permission_at_date"]

        with transaction() as conn:
            with conn.cursor() as cur:
                partner_id, why = _partner(cur, str(clean["sourced_by"]).strip())
                if partner_id is None:
                    rejected.append(Rejected(index, why or "unknown partner"))
                    continue

                cur.execute(
                    "select id, owner_id from contacts where phone_e164 = %s "
                    "for update",
                    (phone,),
                )
                found = cur.fetchone()

                if found is None:
                    contact_id = _create(cur, clean, phone, partner_id, permission_at)
                    created += 1
                elif found[1] == partner_id:
                    contact_id = found[0]
                    _attribute(cur, contact_id, partner_id, permission_at)
                    theirs += 1
                elif found[1] == HOUSE_PARTNER_ID:
                    contact_id = found[0]
                    _attribute(cur, contact_id, partner_id, permission_at)
                    set_owner(
                        cur, contact_id, partner_id,
                        event_type="contact.assigned",
                        reason="partner-collected", actor=actor,
                    )
                    took += 1
                else:
                    conflicts.append(
                        _conflict(cur, index, phone, found[0], found[1])
                    )
                    continue

                _record_permission(cur, contact_id, clean, actor)
                cliff = _cliff(cur, contact_id, phone, permission_at)
                if cliff is not None:
                    cliffs.append(cliff)

    return ImportReport(
        created=created, took_custody=took, already_theirs=theirs,
        rejected=rejected, conflicts=conflicts, cliffs=cliffs,
    )


def _create(
    cur, row: dict, phone: str, partner_id: UUID, permission_at: date
) -> UUID:
    cur.execute(
        "insert into contacts (source, business_name, contact_name, phone_e164, "
        "addr_line1, addr_city, addr_state, addr_zip, owner_id, "
        "sourced_by_partner_id, permission_at) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
        (
            SOURCE,
            (row.get("business_name") or "").strip() or None,
            (row.get("contact_name") or "").strip() or None,
            phone,
            (row.get("addr_line1") or "").strip() or None,
            (row.get("city") or "").strip() or None,
            (row.get("state") or "").strip() or None,
            (row.get("zip") or "").strip() or None,
            partner_id,
            partner_id,
            permission_at,
        ),
    )
    found = cur.fetchone()
    assert found is not None
    contact_id = found[0]
    # Tombstone consult (S-6), as load_list does: a suppression survives FR-8's
    # hard-delete, so a re-imported phone re-acquires it instead of returning as a
    # fresh callable contact. This is the one consult that keeps "the personal
    # window never waives our own list" true across a delete.
    cur.execute(
        "select distinct channel from suppression_tombstones where phone_e164 = %s",
        (phone,),
    )
    for (channel,) in cur.fetchall():
        column = {"voice": "do_not_call", "sms": "do_not_text", "mail": "do_not_mail"}[
            channel
        ]
        cur.execute(
            f"update contacts set {column} = true where id = %s",  # noqa: S608
            (contact_id,),
        )
    return contact_id


def _attribute(cur, contact_id: UUID, partner_id: UUID, permission_at: date) -> None:
    cur.execute(
        "update contacts set sourced_by_partner_id = %s, permission_at = %s "
        "where id = %s",
        (partner_id, permission_at, contact_id),
    )


def _record_permission(cur, contact_id: UUID, row: dict, actor: str) -> None:
    payload: dict[str, Any] = {
        "permission_by": str(row["permission_by"]).strip(),
        "permission_at": str(row["permission_at"]).strip(),
        "permission_where": str(row["permission_where"]).strip(),
        "sourced_by": str(row["sourced_by"]).strip(),
        "actor": actor,
    }
    append_event(
        cur, "human", "contact.permission_recorded", datetime.now(UTC), payload,
        external_id=f"permission:{contact_id}:{payload['permission_at']}",
        contact_id=contact_id,
    )


def _conflict(cur, index: int, phone: str, contact_id: UUID, holder_id: UUID) -> Conflict:
    cur.execute("select name from partners where id = %s", (holder_id,))
    found = cur.fetchone()
    holder = found[0] if found else str(holder_id)
    cur.execute(
        "select occurred_at from events where contact_id = %s "
        "and type = 'contact.assigned' order by occurred_at desc limit 1",
        (contact_id,),
    )
    since = cur.fetchone()
    return Conflict(
        row=index,
        contact_id=contact_id,
        phone=phone,
        held_by=holder,
        held_since=since[0] if since else None,
        activity=_activity(cur, contact_id),
        demo_calls={},
    )
