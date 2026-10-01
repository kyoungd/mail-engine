"""The call record (docs/contact-engine/05a-call-record.md §4).

A rep opens a call on a contact they hold whose DNC status is clear and whose zone is
known, inside hours or with a recorded confirmation; the call keeps the check it relied
on. An outcome is set once, under a lock; `calls.happened` is computed by the database.
Memos, calls received, an admin's clear and a 24-hour undo complete the record. Nothing
here writes or removes a "don't call me again" — that is part 2's report.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from config.params import HOUSE_PARTNER_ID
from db.session import transaction
from domain.errors import ValidationError
from domain.phone import to_e164
from service import dnc, rule, zones

CALL_OUTCOMES = frozenset(
    {"no_answer", "left_voicemail", "owner_unavailable", "busy", "call_not_placed"}
)
CARD_OUTCOMES = frozenset(
    {"spoke", "follow_up", "not_interested", "wrong_number", "signed_up"}
)
UNDOABLE = frozenset({"signed_up", "wrong_number"})
RESOLUTIONS = frozenset({"spoke", "call_back", "dismiss"})
UNDO_WINDOW = timedelta(hours=24)

_OPEN = "opened_at is not null and outcome is null and cleared_at is null"


@dataclass(frozen=True)
class OpenedCall:
    call_id: UUID
    phone: str


@dataclass(frozen=True)
class _Checked:
    phone: str
    checked_at: datetime
    snapshot_id: UUID | None
    hours: zones.CallingHours


def _after_lock(cur) -> None:
    """Called once per verb, right after its lock."""


def _aware(at: datetime) -> None:
    if at.tzinfo is None:
        raise ValidationError("bad_time", "at must carry a time zone")


def _check_rep(cur, rep: UUID) -> None:
    cur.execute("select 1 from partners where id = %s", (rep,))
    if rep == HOUSE_PARTNER_ID or cur.fetchone() is None:
        raise ValidationError("bad_rep", f"no rep {rep}")


def _own_open_call(cur, rep: UUID, contact_id: UUID) -> UUID | None:
    cur.execute(
        f"select id from calls where contact_id = %s and rep_id = %s and {_OPEN}",  # noqa: S608
        (contact_id, rep),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _check_open(
    cur, rep: UUID, contact_id: UUID, at: datetime, confirm_outside_hours: bool
) -> _Checked:
    """`open_call`'s refusals, in order, on the caller's cursor; the contact is left
    locked. `rule.may_call` gives the same answer through it."""
    _check_rep(cur, rep)
    cur.execute(
        "select owner_id, phone_e164, dnc_checked_at, dnc_snapshot_id "
        "from contacts where id = %s for update",
        (contact_id,),
    )
    contact = cur.fetchone()
    if contact is None:
        raise ValidationError("no_contact", f"no contact {contact_id}")
    _after_lock(cur)
    owner_id, phone, checked_at, snapshot_id = contact

    own = _own_open_call(cur, rep, contact_id)
    if own is not None:
        raise ValidationError(
            "call_open", "this contact has your open call", {"call_id": own}
        )
    if owner_id != rep:
        raise ValidationError("not_yours", "the rep does not hold this contact")
    cur.execute(
        f"select 1 from calls where contact_id = %s and {_OPEN}",  # noqa: S608
        (contact_id,),
    )
    if cur.fetchone() is not None:
        raise ValidationError("call_open", "this contact has an open call")

    # Part 2's status and part 3's hours, read after the lock (§4.2).
    status = dnc.dnc_status(contact_id, at)
    if status != "clear":
        raise ValidationError(
            "not_callable", f"DNC status is {status}", {"status": status}
        )
    hours = zones.calling_hours(contact_id, at)
    if hours.inside is None:
        raise ValidationError("no_zone", "no time zone is known for this contact")
    # The rule (part 5b §4.6), after the zone and before the hours.
    rule.refuse_call(cur, rep, contact_id, at)
    if hours.inside is False and not confirm_outside_hours:
        raise ValidationError(
            "outside_hours", "outside calling hours there",
            {"local": {z: t.isoformat() for z, t in hours.local.items()}},
        )
    return _Checked(phone=phone, checked_at=checked_at, snapshot_id=snapshot_id,
                    hours=hours)


def open_call(
    rep: UUID, contact_id: UUID, at: datetime, confirm_outside_hours: bool = False
) -> OpenedCall:
    _aware(at)
    with transaction() as conn:
        with conn.cursor() as cur:
            checked = _check_open(cur, rep, contact_id, at, confirm_outside_hours)
            hours = checked.hours
            cur.execute(
                "insert into calls (contact_id, rep_id, phone_e164, opened_at, "
                "dnc_checked_at, dnc_snapshot_id, zones, inside, outside_confirmed) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
                (contact_id, rep, checked.phone, at, checked.checked_at,
                 checked.snapshot_id, sorted(hours.zones), hours.inside,
                 hours.inside is False),
            )
            made = cur.fetchone()
            assert made is not None
    return OpenedCall(call_id=made[0], phone=checked.phone)


def record_outcome(
    rep: UUID,
    contact_id: UUID,
    outcome: str,
    at: datetime,
    *,
    call_id: UUID | None = None,
    memo: str | None = None,
) -> UUID:
    _aware(at)
    with transaction() as conn:
        with conn.cursor() as cur:
            _check_rep(cur, rep)
            if outcome not in CALL_OUTCOMES | CARD_OUTCOMES or (
                call_id is None and outcome in CALL_OUTCOMES
            ):
                raise ValidationError("bad_outcome", f"not an outcome here: {outcome!r}")
            if memo is not None and not memo.strip():
                raise ValidationError("no_text", "a memo carries its text")

            if call_id is not None:
                # The contact first, then the call row (part 5b §4.3).
                cur.execute(
                    "select 1 from contacts where id = %s for update", (contact_id,)
                )
                if cur.fetchone() is None:
                    raise ValidationError("no_contact", f"no contact {contact_id}")
                cur.execute(
                    "select contact_id, rep_id, opened_at, outcome, cleared_at "
                    "from calls where id = %s for update",
                    (call_id,),
                )
                row = cur.fetchone()
                _after_lock(cur)
                if (
                    row is None or row[0] != contact_id or row[1] != rep
                    or row[2] is None or row[3] is not None or row[4] is not None
                    or row[2] > at
                ):
                    raise ValidationError("no_call", "not your open call on this contact")
                cur.execute(
                    "update calls set outcome = %s, outcome_at = %s "
                    "where id = %s and outcome is null and cleared_at is null",
                    (outcome, at, call_id),
                )
                if cur.rowcount != 1:
                    raise ValidationError("no_call", "the call is no longer open")
                outcome_id = call_id
                rule.apply_outcome(cur, contact_id, outcome, outcome != "call_not_placed",
                                   row[2], at)
            else:
                cur.execute(
                    "select owner_id from contacts where id = %s for update", (contact_id,)
                )
                contact = cur.fetchone()
                if contact is None:
                    raise ValidationError("no_contact", f"no contact {contact_id}")
                _after_lock(cur)
                own = _own_open_call(cur, rep, contact_id)
                if own is not None:
                    raise ValidationError(
                        "call_open", "record the outcome on your open call",
                        {"call_id": own},
                    )
                if contact[0] != rep:
                    raise ValidationError("not_yours", "the rep does not hold this contact")
                cur.execute(
                    "insert into calls (contact_id, rep_id, outcome, outcome_at) "
                    "values (%s,%s,%s,%s) returning id",
                    (contact_id, rep, outcome, at),
                )
                made = cur.fetchone()
                assert made is not None
                outcome_id = made[0]
                rule.apply_outcome(cur, contact_id, outcome, False, None, at)

            if memo is not None:
                cur.execute(
                    "insert into memos (contact_id, rep_id, call_id, text, at) "
                    "values (%s,%s,%s,%s,%s)",
                    (contact_id, rep, outcome_id, memo.strip(), at),
                )
    return outcome_id


def add_memo(rep: UUID, contact_id: UUID, text: str, at: datetime) -> UUID:
    _aware(at)
    with transaction() as conn:
        with conn.cursor() as cur:
            _check_rep(cur, rep)
            cur.execute(
                "select owner_id from contacts where id = %s for update", (contact_id,)
            )
            contact = cur.fetchone()
            if contact is None:
                raise ValidationError("no_contact", f"no contact {contact_id}")
            _after_lock(cur)
            if contact[0] != rep:
                raise ValidationError("not_yours", "the rep does not hold this contact")
            if not (text or "").strip():
                raise ValidationError("no_text", "a memo carries its text")
            cur.execute(
                "insert into memos (contact_id, rep_id, text, at) values (%s,%s,%s,%s) "
                "returning id",
                (contact_id, rep, text.strip(), at),
            )
            made = cur.fetchone()
            assert made is not None
    return made[0]


def receive_call(rep: UUID, phone: str, at: datetime) -> UUID:
    """A call to the rep's phone from a contact they hold now or held before (§4.5)."""
    _aware(at)
    e164 = to_e164(phone)
    with transaction() as conn:
        with conn.cursor() as cur:
            _check_rep(cur, rep)
            if e164 is None or not re.fullmatch(r"\+1[0-9]{10}", e164):
                raise ValidationError("invalid_phone", f"not a phone: {phone!r}")
            cur.execute(
                "select c.id from contacts c where c.phone_e164 = %s and not c.is_seed "
                "and (c.owner_id = %s "
                "  or exists (select 1 from events e where e.contact_id = c.id "
                "             and e.payload->>'new_owner_id' = %s) "
                "  or exists (select 1 from intake_rep i where i.contact_id = c.id "
                "             and i.rep_id = %s))",
                (e164, rep, str(rep), rep),
            )
            found = cur.fetchone()
            if found is None:
                raise ValidationError("not_yours", "not a contact this rep knows")
            cur.execute(
                "insert into calls_received (contact_id, rep_id, phone_e164, received_at) "
                "values (%s,%s,%s,%s) returning id",
                (found[0], rep, e164, at),
            )
            made = cur.fetchone()
            assert made is not None
    return made[0]


def resolve_received(rep: UUID, received_id: UUID, resolution: str, at: datetime) -> str:
    _aware(at)
    with transaction() as conn:
        with conn.cursor() as cur:
            _check_rep(cur, rep)
            if resolution not in RESOLUTIONS:
                raise ValidationError("bad_resolution", f"not a resolution: {resolution!r}")
            # The contact first, then the row (part 5b §4.3); its contact never changes.
            cur.execute(
                "select contact_id from calls_received where id = %s", (received_id,)
            )
            found = cur.fetchone()
            if found is None:
                raise ValidationError("no_received", "no such call received")
            cur.execute("select 1 from contacts where id = %s for update", (found[0],))
            cur.execute(
                "select rep_id, received_at, resolution from calls_received "
                "where id = %s for update",
                (received_id,),
            )
            row = cur.fetchone()
            _after_lock(cur)
            if row is None or row[0] != rep:
                raise ValidationError("no_received", "no such call received")
            if row[2] is not None:
                raise ValidationError("already_resolved", "already resolved")
            if at < row[1]:
                raise ValidationError("bad_time", "resolved before it was received")
            cur.execute(
                "update calls_received set resolution = %s, resolved_at = %s where id = %s",
                (resolution, at, received_id),
            )
            rule.apply_resolution(cur, found[0], rep, resolution, at)
    return "resolved"


def clear_call(call_id: UUID, actor: str, reason: str, at: datetime) -> str:
    """An admin closes a call left without an outcome (7.9)."""
    _aware(at)
    if not (actor or "").strip():
        raise ValidationError("bad_actor", "an admin clears a call")
    if not (reason or "").strip():
        raise ValidationError("no_reason", "a clear carries its reason")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select opened_at, outcome, cleared_at from calls where id = %s for update",
                (call_id,),
            )
            row = cur.fetchone()
            _after_lock(cur)
            if row is None or row[0] is None:
                raise ValidationError("no_call", f"no call {call_id}")
            if row[1] is not None or row[2] is not None:
                raise ValidationError("not_open", "the call has an outcome or was cleared")
            if at < row[0]:
                raise ValidationError("bad_time", "cleared before it was opened")
            cur.execute(
                "update calls set cleared_by = %s, cleared_reason = %s, cleared_at = %s "
                "where id = %s",
                (actor.strip(), reason.strip(), at, call_id),
            )
    return "cleared"


def undo_outcome(rep: UUID, outcome_id: UUID, reason: str, at: datetime) -> str:
    """A rep's own Signed up or Wrong number, within 24 hours (7.10)."""
    _aware(at)
    with transaction() as conn:
        with conn.cursor() as cur:
            _check_rep(cur, rep)
            if not (reason or "").strip():
                raise ValidationError("no_reason", "an undo carries its reason")
            cur.execute(
                "select rep_id, outcome, outcome_at, undone_at from calls "
                "where id = %s for update",
                (outcome_id,),
            )
            row = cur.fetchone()
            _after_lock(cur)
            if row is None or row[0] != rep:
                raise ValidationError("no_outcome", "no such outcome")
            if row[1] not in UNDOABLE:
                raise ValidationError("not_undoable", "only Signed up or Wrong number")
            if row[3] is not None:
                raise ValidationError("already_undone", "already undone")
            if at < row[2]:
                raise ValidationError("bad_time", "undone before it was recorded")
            if at - row[2] > UNDO_WINDOW:
                raise ValidationError("too_late", "more than 24 hours ago")
            cur.execute(
                "update calls set undone_reason = %s, undone_at = %s where id = %s",
                (reason.strip(), at, outcome_id),
            )
    return "undone"
