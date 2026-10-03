"""Vouching (docs/contact-engine/07-vouching.md §4).

A rep vouches for a contact they hold: met in person, or they contacted me. The verbs
here and door B are the only writers of `vouches` and `vouch_withdrawals`, and only
insert. `dnc_basis` is the one place that decides the DNC part of a call: `clear`, or a
passable status under a vouch that counts (§4.3) — never `do_not_call`, `no_phone` or
`seed`.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from config.params import HOUSE_PARTNER_ID
from db.session import transaction
from domain.errors import ValidationError
from service import dnc

REASONS = frozenset({"met_in_person", "they_contacted_me"})
PASSABLE = frozenset({"not_checked", "not_covered", "on_dnc_file", "check_too_old"})
NOT_VOUCHABLE = frozenset({"do_not_call", "no_phone", "seed"})
CUSTODY_TYPES = ["contact.assigned", "contact.assignment_expired", "contact.reclaimed"]

# §4.3: a vouch of `rep` that counts on its contact `c`, over the alias `v`. Its
# parameters: `rep` (uuid), `rep_text`, `types`.
_COUNTS_SQL = (
    "v.rep_id = %(rep)s and c.owner_id = %(rep)s and c.phone_e164 = v.phone_e164 "
    "and not exists (select 1 from vouch_withdrawals w where w.vouch_id = v.id) "
    "and not exists (select 1 from events e where e.contact_id = v.contact_id "
    "  and e.type = any(%(types)s) and e.id > v.custody_mark "
    "  and e.payload->>'previous_owner_id' = %(rep_text)s "
    "  and e.payload->>'new_owner_id' is distinct from %(rep_text)s)"
)


@dataclass(frozen=True)
class Vouch:
    id: UUID
    reason: str
    at: datetime


def _after_lock(cur) -> None:
    """Called once per verb, right after its lock."""


def _aware(at: datetime) -> None:
    if at.tzinfo is None:
        raise ValidationError("bad_time", "at must carry a time zone")


def _check_rep(cur, rep: UUID) -> None:
    cur.execute("select 1 from partners where id = %s", (rep,))
    if rep == HOUSE_PARTNER_ID or cur.fetchone() is None:
        raise ValidationError("bad_rep", f"no rep {rep}")


def _params(rep: UUID, **more) -> dict:
    return {"rep": rep, "rep_text": str(rep), "types": CUSTODY_TYPES, **more}


def counting(cur, rep: UUID, contact_ids: list[UUID]) -> dict[UUID, Vouch]:
    """The vouch that counts for `rep` on each contact: the latest by `seq` (§4.3)."""
    if not contact_ids:
        return {}
    cur.execute(
        "select distinct on (v.contact_id) v.contact_id, v.id, v.reason, v.at "
        "from vouches v join contacts c on c.id = v.contact_id "
        "where v.contact_id = any(%(ids)s) and " + _COUNTS_SQL
        + " order by v.contact_id, v.seq desc",
        _params(rep, ids=contact_ids),
    )
    return {cid: Vouch(id=i, reason=r, at=a) for cid, i, r, a in cur.fetchall()}


def passes(status: str, vouched: bool) -> bool:
    return status == "clear" or (status in PASSABLE and vouched)


def dnc_basis(cur, rep: UUID, contact_id: UUID, status: str) -> Vouch | None:
    """§4.2: None for a clear contact, the vouch for one passed under it; otherwise
    refused `not_callable`."""
    found = counting(cur, rep, [contact_id]).get(contact_id) if status in PASSABLE else None
    if not passes(status, found is not None):
        raise ValidationError("not_callable", f"DNC status is {status}", {"status": status})
    return None if status == "clear" else found


def record(cur, rep: UUID, contact_id: UUID, phone: str, reason: str, confirmation: str,
           source: str, at: datetime) -> UUID:
    """Append one vouch, with the contact's latest custody event as its mark; the
    caller holds the contact's lock."""
    cur.execute(
        "select max(id) from events where contact_id = %s and type = any(%s)",
        (contact_id, CUSTODY_TYPES),
    )
    mark = cur.fetchone()
    assert mark is not None
    cur.execute(
        "insert into vouches (contact_id, rep_id, phone_e164, reason, confirmation, "
        "source, custody_mark, at) values (%s,%s,%s,%s,%s,%s,%s,%s) returning id",
        (contact_id, rep, phone, reason, confirmation, source, mark[0], at),
    )
    made = cur.fetchone()
    assert made is not None
    return made[0]


def _held(cur, rep: UUID, contact_id: UUID) -> str | None:
    cur.execute(
        "select owner_id, phone_e164 from contacts where id = %s for update", (contact_id,)
    )
    row = cur.fetchone()
    if row is None:
        raise ValidationError("no_contact", f"no contact {contact_id}")
    _after_lock(cur)
    if row[0] != rep:
        raise ValidationError("not_yours", "the rep does not hold this contact")
    return row[1]


def vouch(rep: UUID, contact_id: UUID, reason: str | None, confirmation: str | None,
          at: datetime) -> str:
    _aware(at)
    with transaction() as conn:
        with conn.cursor() as cur:
            _check_rep(cur, rep)
            phone = _held(cur, rep, contact_id)
            if reason not in REASONS:
                raise ValidationError("bad_reason", f"not a reason to vouch: {reason!r}")
            if confirmation is None or not confirmation.strip():
                raise ValidationError("no_confirmation", "a vouch carries its confirmation")
            status = dnc.dnc_status(contact_id, at)
            if status in NOT_VOUCHABLE:
                raise ValidationError("not_vouchable", f"DNC status is {status}",
                                      {"status": status})
            assert phone is not None
            record(cur, rep, contact_id, phone, reason, confirmation.strip(), "rep", at)
    return "vouched"


def withdraw(rep: UUID, contact_id: UUID, reason: str | None, at: datetime) -> str:
    """§4.4a: every vouch of the rep's that counts on the contact stops counting."""
    _aware(at)
    with transaction() as conn:
        with conn.cursor() as cur:
            _check_rep(cur, rep)
            _held(cur, rep, contact_id)
            if not (reason or "").strip():
                raise ValidationError("no_reason", "a withdrawal carries its reason")
            assert reason is not None
            cur.execute(
                "select v.id from vouches v join contacts c on c.id = v.contact_id "
                "where v.contact_id = %(id)s and " + _COUNTS_SQL + " order by v.seq",
                _params(rep, id=contact_id),
            )
            ids = [r[0] for r in cur.fetchall()]
            if not ids:
                raise ValidationError("not_vouched", "no vouch of yours counts here")
            for vouch_id in ids:
                cur.execute(
                    "insert into vouch_withdrawals (vouch_id, reason, at) "
                    "values (%s, %s, %s)",
                    (vouch_id, reason.strip(), at),
                )
    return "withdrawn"
