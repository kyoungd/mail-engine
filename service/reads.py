"""What a rep or an admin reads through the API (docs/contact-engine/06a-the-api.md
§4.5–§4.8): the card, history, lists, known callers, search, open calls, and the rule
that hides a contact the rep never held. Inside a request every read runs in one
REPEATABLE READ, READ ONLY transaction, and none takes a lock."""

import re
from datetime import datetime, timedelta
from typing import Any, LiteralString
from uuid import UUID

from psycopg import sql

from config.params import ASSIGNMENT_EXPIRY_DAYS, HOUSE_PARTNER_ID
from db.session import transaction
from domain.errors import ValidationError
from service import calls, dnc, rule, vouch, zones
from service.assignment import _EXEMPT_SQL
from service.sale import SOLD_SQL

SEARCH_LIMIT = 50

_OWN_SQL = (
    "exists (select 1 from intake_rep i where i.contact_id = c.id and i.is_primary)"
)


def _after_first_read() -> None:
    """Called once per card, right after its first query."""


def hide(rep: UUID, contact_id: UUID | None, error: ValidationError) -> bool:
    """§4.5: a refusal on a contact the rep never held answers as no such contact."""
    if error.code == "not_yours":
        return True
    if contact_id is None:
        return False
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select 1 from contacts c where c.id = %(id)s and " + calls.KNOWN_SQL,
                {"id": contact_id, "rep": rep, "rep_text": str(rep)},
            )
            return cur.fetchone() is None


def _held(cur, rep: UUID, contact_id: UUID) -> tuple:
    cur.execute(
        "select c.owner_id, c.business_name, c.contact_name, c.phone_e164, c.addr_city, "
        "c.addr_state, " + _OWN_SQL + " from contacts c where c.id = %s",
        (contact_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise ValidationError("no_contact", f"no contact {contact_id}")
    if row[0] != rep:
        raise ValidationError("not_yours", "the rep does not hold this contact")
    return row


def _mine_only(own: bool, rep: UUID) -> tuple[LiteralString, list]:
    """History's filter (6.4): a rep's own contact shows only this rep's entries."""
    return (" and rep_id = %s", [rep]) if own else ("", [])


def _trade(cur, contact_id: UUID) -> str | None:
    cur.execute(
        "select trade from intake_rep where contact_id = %(id)s and is_primary "
        "union all select trade from intake_cslb_ca where contact_id = %(id)s "
        "and is_primary "
        "union all select trade from intake_fbn_ca where contact_id = %(id)s "
        "and is_primary limit 1",
        {"id": contact_id},
    )
    row = cur.fetchone()
    return row[0] if row else None


def _goes_back_on(cur, contact_id: UUID) -> datetime | None:
    cur.execute(
        sql.SQL(
            "select b.expires_at, (select max(e.occurred_at) from events e "
            "  where e.contact_id = c.id and e.type = 'contact.assigned') "
            "from contacts c left join assignment_batches b "
            "on b.id = c.assignment_batch_id "
            "where c.id = %(id)s and not {sold} and not {exempt}"
        ).format(sold=SOLD_SQL, exempt=_EXEMPT_SQL),
        {"id": contact_id, "house": HOUSE_PARTNER_ID},
    )
    row = cur.fetchone()
    if row is None:
        return None
    expires_at, assigned_at = row
    if expires_at is not None:
        return expires_at
    if assigned_at is None:
        return None
    return assigned_at + timedelta(days=ASSIGNMENT_EXPIRY_DAYS)


def card(rep: UUID, contact_id: UUID, at: datetime) -> dict[str, Any]:
    with transaction() as conn:
        with conn.cursor() as cur:
            _, business, contact_name, phone, city, state, own = _held(cur, rep, contact_id)
            _after_first_read()
            settings = rule._settings(cur, rep)  # noqa: SLF001
            st = rule._states(cur, rep, [contact_id], at)[contact_id]  # noqa: SLF001
            try:
                calls._check_open(cur, rep, contact_id, at, False, lock=False)  # noqa: SLF001
                may_call: dict[str, Any] = {"yes": True}
            except ValidationError as refusal:
                may_call = {"yes": False, "code": refusal.code, "detail": refusal.detail}
            hours = zones.calling_hours(contact_id, at)
            status = dnc.dnc_status(contact_id, at)
            mine, mine_params = _mine_only(own, rep)
            cur.execute(
                "select text, at from memos where contact_id = %s" + mine
                + " order by at desc, id desc limit 1",
                [contact_id, *mine_params],
            )
            memo = cur.fetchone()
            cur.execute(
                "select outcome_at, outcome from calls where contact_id = %s "
                "and outcome is not null and undone_at is null" + mine
                + " order by outcome_at desc, id desc limit 1",
                [contact_id, *mine_params],
            )
            last = cur.fetchone()
            cur.execute(
                "select id from calls where contact_id = %s and rep_id = %s "
                "and outcome = any(%s) and undone_at is null and outcome_at <= %s "
                "and outcome_at >= %s order by outcome_at, id",
                (contact_id, rep, sorted(calls.UNDOABLE), at, at - calls.UNDO_WINDOW),
            )
            undoable = [r[0] for r in cur.fetchall()]
            trade = _trade(cur, contact_id)
            goes_back_on = None if own else _goes_back_on(cur, contact_id)
            vouched = vouch.counting(cur, rep, [contact_id]).get(contact_id)
    return {
        "id": contact_id, "business": business, "contact_name": contact_name,
        "phone": phone, "city": city, "state": state, "trade": trade,
        "whose": "own" if own else "nmc",
        "list": st.list, "reason": st.reason, "calls": st.calls,
        "voicemails": st.voicemails,
        "limits": {"voicemails": settings.voicemails, "calls": settings.calls},
        "due": st.due, "rest_until": st.rest_until, "pause_until": st.pause_until,
        "may_call": may_call,
        "zones": sorted(hours.zones), "local_times": hours.local, "inside": hours.inside,
        "dnc_status": status, "goes_back_on": goes_back_on,
        "latest_memo": {"text": memo[0], "at": memo[1]} if memo else None,
        "last_call": {"at": last[0], "outcome": last[1]} if last else None,
        "undoable": undoable,
        "vouched": {"reason": vouched.reason, "at": vouched.at} if vouched else None,
    }


def history(rep: UUID, contact_id: UUID) -> dict[str, Any]:
    with transaction() as conn:
        with conn.cursor() as cur:
            own = _held(cur, rep, contact_id)[6]
            mine, mine_params = _mine_only(own, rep)
            cur.execute(
                "select coalesce(outcome_at, opened_at), outcome, rep_id, id from calls "
                "where contact_id = %s" + mine,
                [contact_id, *mine_params],
            )
            entries = [
                {"kind": "call", "at": a, "outcome": o, "by_you": r == rep, "_id": i}
                for a, o, r, i in cur.fetchall()
            ]
            cur.execute(
                "select at, text, rep_id, id from memos where contact_id = %s" + mine,
                [contact_id, *mine_params],
            )
            entries += [
                {"kind": "memo", "at": a, "text": t, "by_you": r == rep, "_id": i}
                for a, t, r, i in cur.fetchall()
            ]
    entries.sort(key=lambda e: (e["at"], e["kind"] == "call", str(e["_id"])), reverse=True)
    for e in entries:
        del e["_id"]
    return {"entries": entries}


def lists(rep: UUID, at: datetime) -> dict[str, Any]:
    """Part 7 §4.6: only the contacts whose DNC status the rep may call past."""
    held = rule.rep_lists(rep, at)
    with transaction() as conn:
        with conn.cursor() as cur:
            vouched = vouch.counting(cur, rep, list(held.by_contact))
            cur.execute(
                "select c.id, c.business_name, c.contact_name, c.phone_e164, "
                + _OWN_SQL + " from contacts c where c.id = any(%s) "
                "order by c.business_name, c.id",
                (list(held.by_contact),),
            )
            contacts = [
                {"id": cid, "business": b, "contact_name": n, "phone": p,
                 "list": held.by_contact[cid].list, "reason": held.by_contact[cid].reason,
                 "due": held.by_contact[cid].due,
                 "rest_until": held.by_contact[cid].rest_until,
                 "pause_until": held.by_contact[cid].pause_until,
                 "whose": "own" if own else "nmc", "vouched": cid in vouched}
                for cid, b, n, p, own in cur.fetchall()
                if vouch.passes(dnc.dnc_status(cid, at), cid in vouched)
            ]
            cur.execute(
                "select r.id, r.contact_id, c.business_name, r.phone_e164, r.received_at "
                "from calls_received r join contacts c on c.id = r.contact_id "
                "where r.id = any(%s) order by r.received_at, r.id",
                (held.calls_received,),
            )
            received = [
                {"id": i, "contact_id": c, "business": b, "phone": p, "received_at": a}
                for i, c, b, p, a in cur.fetchall()
            ]
    return {"contacts": contacts, "calls_received": received}


def _identities(cur) -> list[dict[str, Any]]:
    return [
        {"id": i, "phone": p, "business": b, "contact_name": n}
        for i, p, b, n in cur.fetchall()
    ]


def known_callers(rep: UUID) -> dict[str, Any]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select c.id, c.phone_e164, c.business_name, c.contact_name "
                "from contacts c where " + calls.KNOWN_SQL
                + " order by c.business_name, c.id",
                {"rep": rep, "rep_text": str(rep)},
            )
            return {"contacts": _identities(cur)}


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search(rep: UUID, q: str, at: datetime) -> dict[str, Any]:
    q = q.strip()
    if len(q) < 2:
        raise ValidationError("bad_request", "search for at least 2 characters")
    digits = re.sub(r"[^0-9]", "", q)
    phone = " or c.phone_e164 like %(digits)s" if len(digits) >= 4 else ""
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select c.id, c.phone_e164, c.business_name, c.contact_name "
                "from contacts c where c.owner_id = %(rep)s and ("
                "c.business_name ilike %(q)s or c.contact_name ilike %(q)s" + phone
                + ") order by c.business_name, c.id limit %(limit)s",
                {"rep": rep, "q": _like(q), "digits": f"%{digits}%",
                 "limit": SEARCH_LIMIT},
            )
            found = _identities(cur)
            vouched = vouch.counting(cur, rep, [c["id"] for c in found])
    return {"contacts": [
        {**c, "dnc_status": dnc.dnc_status(c["id"], at), "vouched": c["id"] in vouched}
        for c in found
    ]}


def open_calls() -> list[dict[str, Any]]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select c.id, c.opened_at, c.phone_e164, p.name from calls c "
                "join partners p on p.id = c.rep_id "
                "where c.opened_at is not null and c.outcome is null "
                "and c.cleared_at is null order by c.opened_at, c.id"
            )
            return [
                {"id": i, "opened_at": a, "phone": p, "rep": n}
                for i, a, p, n in cur.fetchall()
            ]
