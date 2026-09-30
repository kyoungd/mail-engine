"""DNC filtering (docs/contact-engine/02-dnc-filtering.md §4).

One record of "don't call me again", keyed by phone: `dnc_numbers` says whether a phone
is blocked, `dnc_log` holds every block and lift. The verbs here are the only Python
writers; the database trigger and door A write the rest (migration 0015). Every place
that decides reads BLOCKED_SQL, so the status, the gate, the export, and door B agree.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from psycopg import sql

from config.params import DNC_FRESHNESS_DAYS, HOUSE_PARTNER_ID
from db.session import transaction
from domain.errors import ValidationError
from domain.phone import to_e164

# A phone is blocked by a live row, the flag, or a voice tombstone on it (§4.1 row 1).
# Written over the alias `c` of a contacts row.
LIVE_ROW_SQL = sql.SQL(
    "exists (select 1 from dnc_numbers n where n.phone_e164 = c.phone_e164 and n.blocked)"
)
BLOCKED_SQL = sql.SQL(
    "({live} or c.do_not_call or exists (select 1 from suppression_tombstones t "
    "where t.phone_e164 = c.phone_e164 and t.channel = 'voice'))"
).format(live=LIVE_ROW_SQL)

# A link counts only to an accepted snapshot of the phone's own area code with a date,
# no more than `%s` days old on the UTC date of now() (§4.1 rows 4 and 6).
LINK_FRESH_SQL = sql.SQL(
    "(c.dnc_snapshot_id is null or exists (select 1 from dnc_snapshots s "
    "where s.id = c.dnc_snapshot_id and s.status = 'accepted' "
    "and s.area_code is not distinct from substring(c.phone_e164 from 3 for 3) "
    "and s.version_date is not null "
    "and s.version_date >= (now() at time zone 'UTC')::date - %s))"
)

_DEFAULT_REASON = "asked not to be called"
_UNLIFTABLE_KINDS = ("event", "intake", "backfill")


@dataclass(frozen=True)
class DncLogEntry:
    seq: int
    phone: str
    kind: str
    actor: str
    rep_id: UUID | None
    contact_id: UUID | None
    reason: str | None
    at: datetime


def _after_lock(cur) -> None:
    """Called once per verb, after its locks and before its first write."""


def _aware(at: datetime) -> None:
    if at.tzinfo is None:
        raise ValidationError("bad_time", "at must carry a time zone")


def _phone(raw) -> str:
    e164 = to_e164(raw)
    if e164 is None or not re.fullmatch(r"\+1[0-9]{10}", e164):
        raise ValidationError("invalid_phone", f"not a phone: {raw!r}")
    return e164


def _block(cur, phone: str, *, kind: str, actor: str, rep: UUID | None,
           contact: UUID | None, reason: str, at: datetime) -> None:
    """The block helper (§4.5): the caller has locked the contact, if any. Lock the
    phone's row, then turn it on and log it. No flag, no tombstone, no event."""
    cur.execute(
        "insert into dnc_numbers (phone_e164, blocked, updated_at) values (%s, false, %s) "
        "on conflict (phone_e164) do nothing",
        (phone, at),
    )
    cur.execute("select 1 from dnc_numbers where phone_e164 = %s for update", (phone,))
    _after_lock(cur)
    cur.execute(
        "update dnc_numbers set blocked = true, updated_at = %s where phone_e164 = %s",
        (at, phone),
    )
    cur.execute(
        "insert into dnc_log (phone_e164, kind, actor, rep_id, contact_id, reason, at) "
        "values (%s, %s, %s, %s, %s, %s, %s)",
        (phone, kind, actor, rep, contact, reason, at),
    )


def dnc_status(contact_id: UUID, at: datetime) -> str:
    """The first of §4.1's rows that applies to the contact at `at`."""
    _aware(at)
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "select c.is_seed, c.phone_e164, c.dnc_registry, c.dnc_checked_at, "
                    "{blocked}, "
                    "exists (select 1 from dnc_subscriptions s "
                    "  where s.area_code = substring(c.phone_e164 from 3 for 3)), "
                    "greatest(c.created_at, (select max(i.added_at) from intake_rep i "
                    "  where i.contact_id = c.id)), "
                    "(select max(r.started_at) from dnc_runs r "
                    "  where not r.limited and r.started_at <= %s), "
                    "c.dnc_snapshot_id is not null, "
                    "(select s.version_date from dnc_snapshots s where s.id = c.dnc_snapshot_id "
                    "  and s.status = 'accepted' and s.version_date is not null "
                    "  and s.area_code is not distinct from substring(c.phone_e164 from 3 for 3)) "
                    "from contacts c where c.id = %s"
                ).format(blocked=BLOCKED_SQL),
                (at, contact_id),
            )
            row = cur.fetchone()
    if row is None:
        raise ValidationError("no_contact", f"no contact {contact_id}")
    (is_seed, phone, listed, checked_at, blocked, subscribed, came_in, last_run,
     linked, list_date) = row

    if is_seed:
        return "seed"
    if blocked:
        return "do_not_call"
    if phone is None:
        return "no_phone"
    if not subscribed:
        if last_run is not None and came_in < last_run:
            return "not_covered"
        return "not_checked"
    if checked_at is None or checked_at > at or (linked and list_date is None):
        return "not_checked"
    if listed:
        return "on_dnc_file"
    if checked_at < at - timedelta(days=DNC_FRESHNESS_DAYS):
        return "check_too_old"
    if list_date is not None and list_date < (
        at.astimezone(UTC).date() - timedelta(days=DNC_FRESHNESS_DAYS)
    ):
        return "check_too_old"
    return "clear"


def report_do_not_call(rep: UUID, contact_id: UUID, reason: str | None, at: datetime) -> str:
    """A rep's "don't call me again" (§4.5): recorded whoever holds the contact now."""
    _aware(at)
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select owner_id, phone_e164 from contacts where id = %s for update",
                (contact_id,),
            )
            contact = cur.fetchone()
            if contact is None:
                raise ValidationError("no_contact", f"no contact {contact_id}")
            owner_id, phone = contact
            if phone is None:
                raise ValidationError("no_phone", f"contact {contact_id} has no phone")
            cur.execute("select 1 from partners where id = %s", (rep,))
            if rep == HOUSE_PARTNER_ID or cur.fetchone() is None:
                raise ValidationError("bad_rep", f"no rep {rep}")
            if owner_id != rep:
                cur.execute(
                    "select 1 from events where contact_id = %s "
                    "and payload->>'new_owner_id' = %s "
                    "union all select 1 from intake_rep where contact_id = %s and rep_id = %s",
                    (contact_id, str(rep), contact_id, rep),
                )
                if cur.fetchone() is None:
                    raise ValidationError("not_yours", "the rep never held this contact")
            _block(cur, phone, kind="rep", actor=str(rep), rep=rep, contact=contact_id,
                   reason=(reason or "").strip() or _DEFAULT_REASON, at=at)
    return "blocked"


def record_do_not_call_request(phone: str, actor: str, reason: str, at: datetime) -> str:
    """An admin's "don't call me again" (§4.6), with or without a contact."""
    _aware(at)
    if not (reason or "").strip():
        raise ValidationError("no_reason", "a request carries its reason")
    e164 = _phone(phone)
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id from contacts where phone_e164 = %s and is_seed = false for update",
                (e164,),
            )
            found = cur.fetchone()
            _block(cur, e164, kind="admin", actor=actor, rep=None,
                   contact=found[0] if found else None, reason=reason.strip(), at=at)
    return "blocked"


def dnc_history(phone: str) -> list[DncLogEntry]:
    e164 = to_e164(phone) or phone
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select seq, phone_e164, kind, actor, rep_id, contact_id, reason, at "
                "from dnc_log where phone_e164 = %s order by seq",
                (e164,),
            )
            return [DncLogEntry(*row) for row in cur.fetchall()]


def lift_do_not_call(phone: str, seen_seq: int, actor: str, reason: str, at: datetime) -> str:
    """An admin's lift (§4.7): only blocks the verbs recorded, all seen."""
    _aware(at)
    if not (reason or "").strip():
        raise ValidationError("no_reason", "a lift carries its reason")
    e164 = _phone(phone)
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id from contacts where phone_e164 = %s and is_seed = false for update",
                (e164,),
            )
            cur.execute(
                "select blocked from dnc_numbers where phone_e164 = %s for update", (e164,)
            )
            row = cur.fetchone()
            _after_lock(cur)
            if row is None or not row[0]:
                raise ValidationError("nothing_to_lift", f"{e164} is not blocked")
            cur.execute("select max(seq) from dnc_log where phone_e164 = %s", (e164,))
            latest = cur.fetchone()
            if latest is None or latest[0] != seen_seq:
                raise ValidationError("changed", "the history changed; read it again")
            cur.execute(
                "select exists (select 1 from dnc_log where phone_e164 = %s "
                "  and kind = any(%s)) "
                "or exists (select 1 from suppression_tombstones where phone_e164 = %s "
                "  and channel = 'voice') "
                "or exists (select 1 from contacts where phone_e164 = %s and do_not_call)",
                (e164, list(_UNLIFTABLE_KINDS), e164, e164),
            )
            other = cur.fetchone()
            if other is not None and other[0]:
                raise ValidationError(
                    "not_liftable", "blocked some way other than part 2's verbs"
                )
            cur.execute(
                "update dnc_numbers set blocked = false, updated_at = %s "
                "where phone_e164 = %s",
                (at, e164),
            )
            cur.execute(
                "insert into dnc_log (phone_e164, kind, actor, reason, at) "
                "values (%s, 'lift', %s, %s, %s)",
                (e164, actor, reason.strip(), at),
            )
    return "lifted"


def record_scrub_run(started_at: datetime, limited: bool) -> None:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into dnc_runs (started_at, limited) values (%s, %s)",
                (started_at, limited),
            )
