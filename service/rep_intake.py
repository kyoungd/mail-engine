"""Door B: a rep adds numbers (docs/contact-engine/01-intake.md §4).

`add_numbers` is the only writer of `intake_rep`. One transaction: the whole call is
refused for the first whole-call reason that applies, or every row gets the first
row result of §4.2 that applies. A refused row writes nothing. Rows are judged on the
contact rows as they are under lock (§4.3); new contacts are inserted in phone order.
"""

from datetime import datetime
from uuid import UUID

from psycopg import sql

from config.params import HOUSE_PARTNER_ID
from db.session import transaction
from derivation.rules import is_suppressed
from domain.errors import ValidationError
from domain.phone import to_e164
from domain.types import ContactFlags, RepRow, RowResult
from service.custody import set_owner
from service.ingestion import EVENT_COLS, event_from_row

HOW_OBTAINED = frozenset(
    {"met_in_person", "they_contacted_me", "referral", "public_or_research"}
)


def _before_insert(cur) -> None:
    """Called once per call, after every row is judged and before the first write."""


def valid_phone(raw: str | None) -> str | None:
    """E.164 for a callable US number, else None: the area code and the exchange must
    not start with 0 or 1, and neither may be an N11 code."""
    e164 = to_e164(raw)
    if e164 is None:
        return None
    area, exchange = e164[2:5], e164[5:8]
    if area[0] in "01" or exchange[0] in "01":
        return None
    if area[1:] == "11" or exchange[1:] == "11":
        return None
    return e164


def _event_phone(payload) -> str | None:
    """The matcher's rule (resolution/matcher.py:63); a non-object carries no phone."""
    if not isinstance(payload, dict):
        return None
    return payload.get("phone_e164") or to_e164(payload.get("phone"))


def _refuse_call(cur, rep: UUID, rows, how_obtained, confirmation) -> str:
    if rep == HOUSE_PARTNER_ID:
        raise ValidationError("bad_rep", "the house is not a rep")
    cur.execute("select status from partners where id = %s for share", (rep,))
    found = cur.fetchone()
    if found is None or found[0] != "active":
        raise ValidationError("bad_rep", f"no active rep {rep}")
    if confirmation is None or not confirmation.strip():
        raise ValidationError("no_confirmation", "a rep's numbers carry their confirmation")
    if how_obtained is not None and how_obtained not in HOW_OBTAINED:
        raise ValidationError("bad_how_obtained", f"unknown how_obtained {how_obtained!r}")
    for row in rows:
        how = row.how_obtained or how_obtained
        if how is None or how not in HOW_OBTAINED:
            raise ValidationError(
                "bad_how_obtained", f"row {row.phone!r}: how_obtained {how!r}"
            )
    if not rows:
        raise ValidationError("no_rows", "no numbers to add")
    return confirmation.strip()


def _unmatched_phones(cur, event_type: str) -> set[str]:
    cur.execute(
        "select payload from events where contact_id is null and type = %s",
        (event_type,),
    )
    return {p for (payload,) in cur.fetchall() if (p := _event_phone(payload or {}))}


def _judge(cur, rep: UUID, phone: str, unmatched_opt_outs, unmatched_sales):
    """(result, contact_id, owner-relation) for one valid, first-seen phone."""
    cur.execute(
        "select id, owner_id, assignment_batch_id, do_not_call, stage_snapshot::text "
        "from contacts where phone_e164 = %s and is_seed = false",
        (phone,),
    )
    contact = cur.fetchone()
    cur.execute(
        "select exists (select 1 from suppression_tombstones "
        "  where phone_e164 = %s and channel = 'voice') "
        "or exists (select 1 from dnc_numbers where phone_e164 = %s and blocked)",
        (phone, phone),
    )
    found = cur.fetchone()
    voice_tombstone = found is not None and found[0]

    if contact is None:
        if voice_tombstone or phone in unmatched_opt_outs:
            return "do_not_call", None
        if phone in unmatched_sales:
            return "held", None
        return "added", None

    contact_id, owner_id, batch_id, do_not_call, stage = contact
    cur.execute(
        sql.SQL(
            "select {cols} from events where contact_id = %s "
            "and type in ('contact.opt_out', 'signup.completed')"
        ).format(cols=EVENT_COLS),
        (contact_id,),
    )
    events = [event_from_row(r) for r in cur.fetchall()]

    if (
        do_not_call
        or voice_tombstone
        or phone in unmatched_opt_outs
        or is_suppressed(events, ContactFlags(do_not_mail=False, do_not_text=False))
    ):
        return "do_not_call", None
    sold = (
        stage == "won"
        or any(e.type == "signup.completed" for e in events)
        or phone in unmatched_sales
    )
    if sold and owner_id != rep:
        return "held", None
    if owner_id != rep and owner_id != HOUSE_PARTNER_ID:
        return "held", None
    if owner_id == HOUSE_PARTNER_ID and batch_id is not None:
        return "held", None
    if owner_id == rep:
        return "already_yours", contact_id

    cur.execute(
        "select rep_id from intake_rep where contact_id = %s and is_primary", (contact_id,)
    )
    primary = cur.fetchone()
    if primary is not None and primary[0] != rep:
        return "held", None
    return "claimed", contact_id


def _insert_rep_row(cur, contact_id, is_primary, rep, phone, row, how, confirmation, at):
    cur.execute(
        "insert into intake_rep (contact_id, is_primary, rep_id, phone_e164, "
        "business_name, contact_name, contact_role, trade, addr_city, addr_state, "
        "how_obtained, confirmation, added_at) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            contact_id, is_primary, rep, phone, row.business_name, row.contact_name,
            row.contact_role, row.trade, row.addr_city, row.addr_state, how,
            confirmation, at,
        ),
    )


def _hold(cur, contact_id: UUID, rep: UUID) -> None:
    set_owner(
        cur, contact_id, rep,
        event_type="contact.assigned", reason="added_by_rep", actor=str(rep),
    )


def add_numbers(
    rep: UUID,
    rows: list[RepRow],
    how_obtained: str | None,
    confirmation: str | None,
    at: datetime,
) -> list[RowResult]:
    if at.tzinfo is None:
        raise ValidationError("bad_time", "at must carry a time zone")

    with transaction() as conn:
        with conn.cursor() as cur:
            stripped = _refuse_call(cur, rep, rows, how_obtained, confirmation)

            phones = [valid_phone(row.phone) for row in rows]
            cur.execute(
                "select id from contacts where phone_e164 = any(%s) and is_seed = false "
                "order by id for update",
                (sorted({p for p in phones if p}),),
            )
            unmatched_opt_outs = _unmatched_phones(cur, "contact.opt_out")
            unmatched_sales = _unmatched_phones(cur, "signup.completed")

            judged: list[tuple[str, str, UUID | None]] = []
            seen: set[str] = set()
            for row, phone in zip(rows, phones, strict=True):
                if phone is None:
                    judged.append((row.phone, "invalid_phone", None))
                elif phone in seen:
                    judged.append((phone, "duplicate_in_request", None))
                else:
                    seen.add(phone)
                    result, contact_id = _judge(
                        cur, rep, phone, unmatched_opt_outs, unmatched_sales
                    )
                    judged.append((phone, result, contact_id))

            _before_insert(cur)

            created: dict[str, UUID] = {}
            new_rows = sorted(
                (phone, row)
                for row, (phone, result, _) in zip(rows, judged, strict=True)
                if result == "added"
            )
            for phone, row in new_rows:
                cur.execute(
                    "select channel from suppression_tombstones where phone_e164 = %s",
                    (phone,),
                )
                channels = {c for (c,) in cur.fetchall()}
                cur.execute(
                    "insert into contacts (business_name, contact_name, phone_e164, "
                    "addr_city, addr_state, source, segment, do_not_mail, do_not_text) "
                    "values (%s,%s,%s,%s,%s,'rep',null,%s,%s) returning id",
                    (
                        row.business_name, row.contact_name, phone, row.addr_city,
                        row.addr_state, "mail" in channels, "sms" in channels,
                    ),
                )
                made = cur.fetchone()
                assert made is not None
                created[phone] = made[0]
                _insert_rep_row(
                    cur, made[0], True, rep, phone, row,
                    row.how_obtained or how_obtained, stripped, at,
                )
                _hold(cur, made[0], rep)

            for row, (phone, result, contact_id) in zip(rows, judged, strict=True):
                if result == "claimed":
                    assert contact_id is not None
                    _insert_rep_row(
                        cur, contact_id, False, rep, phone, row,
                        row.how_obtained or how_obtained, stripped, at,
                    )
                    _hold(cur, contact_id, rep)

    return [
        RowResult(
            phone=phone,
            result=result,
            contact_id=created.get(phone) if result == "added" else contact_id,
        )
        for phone, result, contact_id in judged
    ]
