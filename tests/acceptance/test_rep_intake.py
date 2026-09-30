"""Part 1 gate: a rep adds numbers (docs/contact-engine/01-intake.md §4, §7).

`add_numbers(rep, rows, how_obtained, confirmation, at)` refuses a whole call for the
first whole-call reason that applies, or returns one result per row: the first row
result that applies, in the order of §4.2. A refused row writes nothing.
"""

import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

from config.params import HOUSE_PARTNER_ID
from domain.errors import ValidationError
from domain.types import RepRow
from service import rep_intake
from service.assignment import assign_batch, reclaim
from service.contacts import load_list
from service.custody import set_owner
from service.ingestion import ingest_event
from tests.factories import add_intake_row, new_contact

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
AT = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
CONFIRMATION = "These are businesses I found through my own prospecting."
FIXTURE = Path(__file__).parents[1] / "e2e" / "fixtures" / "cslb-partner-journey.csv"


# --- fixtures and helpers ---------------------------------------------------------


@pytest.fixture()
def reps(clean_db, owner_conn):
    """Creates reps; at teardown deletes their intake_rep rows, releases what they hold,
    and deletes them (clean_db never truncates partners)."""
    made: list[UUID] = []

    def make(status: str = "active") -> UUID:
        with owner_conn.cursor() as cur:
            cur.execute(
                "insert into partners (name, status) values (%s, %s) returning id",
                (f"Rep-{uuid4().hex[:8]}", status),
            )
            row = cur.fetchone()
            assert row is not None
        owner_conn.commit()
        made.append(row[0])
        return row[0]

    yield make
    owner_conn.rollback()
    with owner_conn.cursor() as cur:
        cur.execute("delete from intake_rep where rep_id = any(%s)", (made,))
        cur.execute(
            "update contacts set owner_id = %s, assignment_batch_id = null "
            "where owner_id = any(%s)",
            (HOUSE_PARTNER_ID, made),
        )
        cur.execute("delete from assignment_batches where partner_id = any(%s)", (made,))
        cur.execute("delete from partners where id = any(%s)", (made,))
    owner_conn.commit()


def _add(rep, *rows, how: str | None = "referral", confirmation=CONFIRMATION, at=NOW):
    rows = [RepRow(phone=r) if isinstance(r, str) else r for r in rows]
    return rep_intake.add_numbers(rep, rows, how, confirmation, at)


def _results(results) -> list[str]:
    return [r.result for r in results]


def _one(rep, row, **kw) -> str:
    return _results(_add(rep, row, **kw))[0]


def _counts(owner_conn) -> tuple[int, int, int]:
    with owner_conn.cursor() as cur:
        cur.execute(
            "select (select count(*) from contacts), (select count(*) from intake_rep), "
            "(select count(*) from events)"
        )
        row = cur.fetchone()
    owner_conn.commit()
    assert row is not None
    return row


def _house(owner_conn, phone: str, **fields) -> UUID:
    """An NMC contact (a CSLB primary intake row), held by the house, no batch."""
    with owner_conn.cursor() as cur:
        contact = new_contact(cur, phone_e164=phone, **fields)
    owner_conn.commit()
    return contact


def _hold(owner_conn, contact: UUID, rep: UUID) -> None:
    with owner_conn.cursor() as cur:
        set_owner(cur, contact, rep, event_type="contact.assigned",
                  reason="test", actor="young")
    owner_conn.commit()


def _on_nmc_sheet(owner_conn, contact: UUID) -> None:
    """Put the contact in a house batch — the operator's own sheet."""
    with owner_conn.cursor() as cur:
        cur.execute(
            "update contacts set dnc_checked_at = now() where id = %s", (contact,)
        )
        cur.execute(
            "insert into dnc_subscriptions (area_code, subscribed_at) "
            "values ('818', now()) on conflict do nothing"
        )
    owner_conn.commit()
    report = assign_batch(HOUSE_PARTNER_ID, f"sheet-{uuid4().hex[:8]}", "young",
                          contact_ids=[contact])
    assert report.assigned == [contact]


def _contact_for(owner_conn, phone: str) -> UUID:
    with owner_conn.cursor() as cur:
        cur.execute("select id from contacts where phone_e164 = %s", (phone,))
        row = cur.fetchone()
    owner_conn.commit()
    assert row is not None
    return row[0]


def _owner(owner_conn, contact: UUID) -> UUID:
    with owner_conn.cursor() as cur:
        cur.execute("select owner_id from contacts where id = %s", (contact,))
        row = cur.fetchone()
    owner_conn.commit()
    assert row is not None
    return row[0]


def _whose(owner_conn, contact: UUID):
    """The rep whose own the contact is, or None for NMC's: its primary intake row."""
    with owner_conn.cursor() as cur:
        cur.execute(
            "select rep_id from intake_rep where contact_id = %s and is_primary",
            (contact,),
        )
        row = cur.fetchone()
    owner_conn.commit()
    return row[0] if row else None


def _primaries(owner_conn, contact: UUID) -> int:
    with owner_conn.cursor() as cur:
        cur.execute(
            "select (select count(*) from intake_cslb_ca where contact_id = %s and is_primary)"
            " + (select count(*) from intake_fbn_ca where contact_id = %s and is_primary)"
            " + (select count(*) from intake_rep where contact_id = %s and is_primary)",
            (contact, contact, contact),
        )
        row = cur.fetchone()
    owner_conn.commit()
    assert row is not None
    return row[0]


def _fields_but_owner(owner_conn, contact: UUID) -> dict:
    """Every column of the contact except owner_id, the one a claim changes."""
    with owner_conn.cursor() as cur:
        cur.execute(
            "select to_jsonb(c) - 'owner_id' from contacts c where id = %s", (contact,)
        )
        row = cur.fetchone()
    owner_conn.commit()
    assert row is not None
    return row[0]


def _tombstone(owner_conn, phone: str, channel: str) -> None:
    with owner_conn.cursor() as cur:
        cur.execute(
            "insert into suppression_tombstones (phone_e164, channel, reason) "
            "values (%s, %s, 'asked')",
            (phone, channel),
        )
    owner_conn.commit()


# --- the whole call ---------------------------------------------------------------


def test_an_unknown_rep_is_refused_whole(reps, owner_conn):
    reps()
    before = _counts(owner_conn)
    with pytest.raises(ValidationError) as err:
        _add(uuid4(), "+18185556001")
    assert err.value.code == "bad_rep"
    assert _counts(owner_conn) == before


def test_an_inactive_rep_is_refused_whole(reps, owner_conn):
    rep = reps(status="inactive")
    before = _counts(owner_conn)
    with pytest.raises(ValidationError) as err:
        _add(rep, "+18185556002")
    assert err.value.code == "bad_rep"
    assert _counts(owner_conn) == before


def test_the_house_is_refused_as_a_rep(reps, owner_conn):
    before = _counts(owner_conn)
    with pytest.raises(ValidationError) as err:
        _add(HOUSE_PARTNER_ID, "+18185556003")
    assert err.value.code == "bad_rep"
    assert _counts(owner_conn) == before


@pytest.mark.parametrize("confirmation", [None, "", "   \n\t "])
def test_a_missing_or_blank_confirmation_is_refused_whole(reps, owner_conn, confirmation):
    rep = reps()
    before = _counts(owner_conn)
    with pytest.raises(ValidationError) as err:
        _add(rep, "+18185556004", confirmation=confirmation)
    assert err.value.code == "no_confirmation"
    assert _counts(owner_conn) == before


def test_how_obtained_missing_from_row_and_call_is_refused_whole(reps, owner_conn):
    rep = reps()
    before = _counts(owner_conn)
    with pytest.raises(ValidationError) as err:
        _add(rep, "+18185556005", how=None)
    assert err.value.code == "bad_how_obtained"
    assert _counts(owner_conn) == before


@pytest.mark.parametrize("where", ["call", "row"])
def test_an_invalid_how_obtained_is_refused_whole(reps, owner_conn, where):
    rep = reps()
    before = _counts(owner_conn)
    row = RepRow(phone="+18185556006", how_obtained="bought_a_list" if where == "row" else None)
    with pytest.raises(ValidationError) as err:
        _add(rep, row, how="bought_a_list" if where == "call" else "referral")
    assert err.value.code == "bad_how_obtained"
    assert _counts(owner_conn) == before


def test_no_rows_is_refused_whole(reps, owner_conn):
    rep = reps()
    with pytest.raises(ValidationError) as err:
        rep_intake.add_numbers(rep, [], "referral", CONFIRMATION, NOW)
    assert err.value.code == "no_rows"


def test_the_whole_call_refusals_apply_in_order(reps, owner_conn):
    with pytest.raises(ValidationError) as err:
        rep_intake.add_numbers(uuid4(), [], None, "", NOW)
    assert err.value.code == "bad_rep"


def test_a_naive_time_is_refused_and_nothing_written(reps, owner_conn):
    rep = reps()
    before = _counts(owner_conn)
    with pytest.raises(ValidationError):
        _add(rep, "+18185556007", at=datetime(2026, 9, 30, 12, 0))
    assert _counts(owner_conn) == before


# --- each row result, in §4.2 order ----------------------------------------------


@pytest.mark.parametrize("phone", [
    "12345",            # to_e164 gives nothing
    "0185556008",       # area code starts with 0
    "+1 118 555 6008",  # area code starts with 1
    "8180556008",       # exchange starts with 0
    "8181556008",       # exchange starts with 1
    "2115556008",       # N11 area code
    "8184115556",       # N11 exchange
])
def test_row_1_an_invalid_number(reps, owner_conn, phone):
    rep = reps()
    before = _counts(owner_conn)
    assert _one(rep, phone) == "invalid_phone"
    assert _counts(owner_conn) == before


def test_row_2_a_number_repeated_in_the_call_after_normalizing(reps, owner_conn):
    rep = reps()
    assert _results(_add(rep, "(818) 555-6010", "18185556010")) == [
        "added", "duplicate_in_request"
    ]


def test_row_3_the_do_not_call_flag(reps, owner_conn):
    rep = reps()
    _house(owner_conn, "+18185556011", do_not_call=True)
    before = _counts(owner_conn)
    assert _one(rep, "+18185556011") == "do_not_call"
    assert _counts(owner_conn) == before


def test_row_3_a_voice_tombstone_creates_no_contact(reps, owner_conn):
    rep = reps()
    _tombstone(owner_conn, "+18185556012", "voice")
    before = _counts(owner_conn)
    assert _one(rep, "+18185556012") == "do_not_call"
    assert _counts(owner_conn) == before


@pytest.mark.parametrize("payload", [{"reason": "phone"}, {}])
def test_row_3_an_old_opt_out_event_with_no_flag(reps, owner_conn, payload):
    """Before 0010 an opt-out set no do_not_call and wrote no tombstone; the stage is
    not recomputed here. A missing reason counts as an opt-out."""
    rep = reps()
    contact = _house(owner_conn, "+18185556013")
    ingest_event("human", "contact.opt_out", AT, payload, contact_id=contact)
    before = _counts(owner_conn)
    assert _one(rep, "+18185556013") == "do_not_call"
    assert _counts(owner_conn) == before


def test_row_3_a_mail_only_opt_out_event_does_not_refuse(reps, owner_conn):
    rep = reps()
    contact = _house(owner_conn, "+18185556014")
    ingest_event("human", "contact.opt_out", AT, {"reason": "do_not_mail"},
                 contact_id=contact)
    assert _one(rep, "+18185556014") == "claimed"


@pytest.mark.parametrize("payload", [
    {"phone_e164": "+18185556015"}, {"phone": "(818) 555-6015"},
])
def test_row_3_an_unmatched_opt_out_carrying_the_phone(reps, owner_conn, payload):
    rep = reps()
    ingest_event("human", "contact.opt_out", AT, {"reason": "phone", **payload})
    before = _counts(owner_conn)
    assert _one(rep, "+18185556015") == "do_not_call"
    assert _counts(owner_conn) == before


def test_row_4_a_sold_contact(reps, owner_conn):
    rep = reps()
    _house(owner_conn, "+18185556016", stage_snapshot="won")
    before = _counts(owner_conn)
    assert _one(rep, "+18185556016") == "held"
    assert _counts(owner_conn) == before


def test_row_4_a_matched_sale_before_the_recompute(reps, owner_conn):
    rep = reps()
    contact = _house(owner_conn, "+18185556017")
    ingest_event("nmc", "signup.completed", AT, {"phone": "+18185556017"},
                 contact_id=contact)
    before = _counts(owner_conn)
    assert _one(rep, "+18185556017") == "held"
    assert _counts(owner_conn) == before


@pytest.mark.parametrize("payload", [
    {"phone_e164": "+18185556018"}, {"phone": "(818) 555-6018"},
])
def test_row_4_an_unmatched_sale_carrying_the_phone(reps, owner_conn, payload):
    rep = reps()
    ingest_event("nmc", "signup.completed", AT, payload)
    before = _counts(owner_conn)
    assert _one(rep, "+18185556018") == "held"
    assert _counts(owner_conn) == before


def test_row_4_an_unmatched_sale_for_a_phone_that_already_has_a_contact(reps, owner_conn):
    """The sale arrived before the contact existed; resolve_orphans has not attached it."""
    rep = reps()
    _house(owner_conn, "+18185556064")
    ingest_event("nmc", "signup.completed", AT, {"phone": "+18185556064"})
    before = _counts(owner_conn)
    assert _one(rep, "+18185556064") == "held"
    assert _counts(owner_conn) == before


def test_row_5_held_by_another_rep(reps, owner_conn):
    rep, other = reps(), reps()
    contact = _house(owner_conn, "+18185556019")
    _hold(owner_conn, contact, other)
    before = _counts(owner_conn)
    assert _one(rep, "+18185556019") == "held"
    assert _counts(owner_conn) == before
    assert _owner(owner_conn, contact) == other


def test_row_5a_on_nmcs_own_sheet(reps, owner_conn):
    rep = reps()
    contact = _house(owner_conn, "+18185556020")
    _on_nmc_sheet(owner_conn, contact)
    before = _counts(owner_conn)
    assert _one(rep, "+18185556020") == "held"
    assert _counts(owner_conn) == before
    assert _owner(owner_conn, contact) == HOUSE_PARTNER_ID


def test_row_6_another_reps_own_back_at_the_house(reps, owner_conn):
    rep, other = reps(), reps()
    assert _one(other, "+18185556021") == "added"
    reclaim(other, "operator took them back", "young")
    before = _counts(owner_conn)
    assert _one(rep, "+18185556021") == "held"
    assert _counts(owner_conn) == before


def test_row_7_already_held_by_this_rep(reps, owner_conn):
    rep = reps()
    contact = _house(owner_conn, "+18185556022")
    _hold(owner_conn, contact, rep)
    before = _counts(owner_conn)
    assert _one(rep, "+18185556022") == "already_yours"
    assert _counts(owner_conn) == before


def test_row_8_this_reps_own_back_at_the_house_is_taken_back(reps, owner_conn):
    rep = reps()
    assert _one(rep, "+18185556023") == "added"
    contact = _contact_for(owner_conn, "+18185556023")
    reclaim(rep, "operator took them back", "young")
    assert _one(rep, "+18185556023") == "claimed"
    assert _owner(owner_conn, contact) == rep
    assert _whose(owner_conn, contact) == rep  # its primary row is still the first
    assert _primaries(owner_conn, contact) == 1


def test_row_9_nmcs_contact_held_by_nobody_is_claimed(reps, owner_conn):
    rep = reps()
    contact = _house(owner_conn, "+18185556024", business_name="Reseda Rooter",
                     addr_city="Reseda")
    fields_before = _fields_but_owner(owner_conn, contact)

    results = _add(rep, RepRow(phone="+18185556024", business_name="Something Else"))
    assert _results(results) == ["claimed"]
    assert results[0].contact_id == contact

    assert _fields_but_owner(owner_conn, contact) == fields_before
    with owner_conn.cursor() as cur:
        cur.execute(
            "select is_primary from intake_rep where contact_id = %s", (contact,)
        )
        rep_rows = cur.fetchall()
    owner_conn.commit()
    assert rep_rows == [(False,)]
    assert _owner(owner_conn, contact) == rep
    assert _whose(owner_conn, contact) is None  # still NMC's
    assert _primaries(owner_conn, contact) == 1


def test_row_10_a_new_number_is_added_as_the_reps_own(reps, owner_conn):
    rep = reps()
    results = _add(rep, RepRow(
        phone="(818) 555-6025", business_name="Valley Locksmith", contact_name="Pat",
        contact_role="owner", trade="locksmith", addr_city="Van Nuys", addr_state="CA",
    ), how="met_in_person")
    assert _results(results) == ["added"]
    contact = results[0].contact_id
    assert contact is not None

    with owner_conn.cursor() as cur:
        cur.execute(
            "select phone_e164, business_name, contact_name, addr_city, addr_state, "
            "source, segment, owner_id, assignment_batch_id from contacts where id = %s",
            (contact,),
        )
        assert cur.fetchone() == (
            "+18185556025", "Valley Locksmith", "Pat", "Van Nuys", "CA",
            "rep", None, rep, None,
        )
        cur.execute(
            "select is_primary, rep_id, phone_e164, contact_role, trade, how_obtained, "
            "confirmation, added_at from intake_rep where contact_id = %s",
            (contact,),
        )
        assert cur.fetchall() == [(
            True, rep, "+18185556025", "owner", "locksmith", "met_in_person",
            CONFIRMATION, NOW,
        )]
        cur.execute(
            "select type, payload->>'reason', payload->>'new_owner_id' from events "
            "where contact_id = %s",
            (contact,),
        )
        assert cur.fetchall() == [("contact.assigned", "added_by_rep", str(rep))]
    owner_conn.commit()
    assert _whose(owner_conn, contact) == rep


# --- what else a row carries -------------------------------------------------------


def test_a_rows_own_how_obtained_overrides_the_calls_and_is_stored(reps, owner_conn):
    rep = reps()
    results = _add(rep, RepRow(phone="+18185556026", how_obtained="they_contacted_me"),
                   RepRow(phone="+18185556027"), how="referral")
    with owner_conn.cursor() as cur:
        cur.execute(
            "select phone_e164, how_obtained from intake_rep order by phone_e164"
        )
        assert cur.fetchall() == [
            ("+18185556026", "they_contacted_me"), ("+18185556027", "referral"),
        ]
    owner_conn.commit()
    assert _results(results) == ["added", "added"]


def test_the_stored_confirmation_is_the_input_stripped(reps, owner_conn):
    rep = reps()
    _add(rep, "+18185556028", confirmation=f"  {CONFIRMATION}\n")
    with owner_conn.cursor() as cur:
        cur.execute("select confirmation from intake_rep")
        assert cur.fetchall() == [(CONFIRMATION,)]
    owner_conn.commit()


@pytest.mark.parametrize("channel,column", [("mail", "do_not_mail"), ("sms", "do_not_text")])
def test_a_mail_or_sms_tombstone_is_carried_onto_the_new_contact(
    reps, owner_conn, channel, column
):
    rep = reps()
    _tombstone(owner_conn, "+18185556029", channel)
    results = _add(rep, "+18185556029")
    assert _results(results) == ["added"]
    with owner_conn.cursor() as cur:
        cur.execute(
            "select do_not_mail, do_not_text, do_not_call from contacts where id = %s",
            (results[0].contact_id,),
        )
        row = cur.fetchone()
    owner_conn.commit()
    assert row is not None
    assert dict(zip(["do_not_mail", "do_not_text", "do_not_call"], row)) == {
        "do_not_mail": column == "do_not_mail",
        "do_not_text": column == "do_not_text",
        "do_not_call": False,
    }


@pytest.mark.parametrize("fields", [{"dnc_registry": True}, {"stage_snapshot": "in_conversation"}])
def test_a_registry_listed_or_mid_conversation_house_contact_is_claimed(
    reps, owner_conn, fields
):
    rep = reps()
    _house(owner_conn, "+18185556030", **fields)
    assert _one(rep, "+18185556030") == "claimed"


def test_the_same_call_twice(reps, owner_conn):
    rep = reps()
    _house(owner_conn, "+18185556031")
    rows = ["+18185556031", "+18185556032"]
    assert _results(_add(rep, *rows)) == ["claimed", "added"]
    before = _counts(owner_conn)
    assert _results(_add(rep, *rows)) == ["already_yours", "already_yours"]
    assert _counts(owner_conn) == before


def test_whose_it_is_survives_going_back_to_the_house(reps, owner_conn):
    rep = reps()
    nmc = _house(owner_conn, "+18185556033")
    results = _add(rep, "+18185556033", "+18185556034")
    own = results[1].contact_id
    assert own is not None
    assert (_whose(owner_conn, nmc), _whose(owner_conn, own)) == (None, rep)
    reclaim(rep, "operator took them back", "young")
    assert (_whose(owner_conn, nmc), _whose(owner_conn, own)) == (None, rep)


def test_door_a_after_door_b_attaches_and_keeps_it_the_reps_own(reps, owner_conn):
    rep = reps()
    results = _add(rep, "+18185550101")  # Reseda Rooter's number in the CSLB fixture
    contact = results[0].contact_id
    assert contact is not None
    load_list(str(FIXTURE), source="cslb")
    assert _contact_for(owner_conn, "+18185550101") == contact
    assert _owner(owner_conn, contact) == rep
    assert _whose(owner_conn, contact) == rep
    assert _primaries(owner_conn, contact) == 1


def test_a_phone_only_on_an_intake_row_is_added_as_a_new_contact(reps, owner_conn):
    """§4.2: the phone is looked up on contacts only — this pins the assumption."""
    rep = reps()
    with owner_conn.cursor() as cur:
        phoneless = new_contact(cur, phone_e164=None)
        add_intake_row(cur, phoneless, phone_e164="+18185556035")
    owner_conn.commit()
    results = _add(rep, "+18185556035")
    assert _results(results) == ["added"]
    assert results[0].contact_id != phoneless


def test_the_time_written_is_at(reps, owner_conn):
    rep = reps()
    _add(rep, "+18185556036", at=NOW)
    with owner_conn.cursor() as cur:
        cur.execute("select added_at from intake_rep")
        assert cur.fetchall() == [(NOW,)]
    owner_conn.commit()


def test_load_list_does_not_know_the_rep_source(clean_db):
    with pytest.raises(ValidationError) as err:
        load_list(str(FIXTURE), source="rep")
    assert err.value.code == "unknown_source"


def test_the_read_only_role_can_read_intake_rep(clean_db, readonly_url):
    with psycopg.connect(readonly_url) as conn:
        conn.execute("select count(*) from intake_rep").fetchone()


# --- the order: pairs that can meet -----------------------------------------------


def test_the_order_of_the_row_results(reps, owner_conn):
    rep, other = reps(), reps()

    # invalid + duplicate -> invalid_phone
    assert _results(_add(rep, "2115556040", "2115556040")) == [
        "invalid_phone", "invalid_phone"
    ]

    # duplicate + do_not_call -> duplicate_in_request
    _house(owner_conn, "+18185556041", do_not_call=True)
    assert _results(_add(rep, "+18185556041", "8185556041")) == [
        "do_not_call", "duplicate_in_request"
    ]

    # do_not_call + this rep's own at the house -> do_not_call
    assert _one(rep, "+18185556042") == "added"
    own = _contact_for(owner_conn, "+18185556042")
    reclaim(rep, "back", "young")
    with owner_conn.cursor() as cur:
        cur.execute("update contacts set do_not_call = true where id = %s", (own,))
    owner_conn.commit()
    assert _one(rep, "+18185556042") == "do_not_call"

    # do_not_call + held by this rep -> do_not_call
    c = _house(owner_conn, "+18185556043", do_not_call=True)
    _hold(owner_conn, c, rep)
    assert _one(rep, "+18185556043") == "do_not_call"

    # do_not_call + held by another rep -> do_not_call
    c = _house(owner_conn, "+18185556044", do_not_call=True)
    _hold(owner_conn, c, other)
    assert _one(rep, "+18185556044") == "do_not_call"

    # do_not_call + sold -> do_not_call
    _house(owner_conn, "+18185556045", do_not_call=True, stage_snapshot="won")
    assert _one(rep, "+18185556045") == "do_not_call"

    # do_not_call + on NMC's sheet -> do_not_call
    c = _house(owner_conn, "+18185556046")
    _on_nmc_sheet(owner_conn, c)
    with owner_conn.cursor() as cur:
        cur.execute("update contacts set do_not_call = true where id = %s", (c,))
    owner_conn.commit()
    assert _one(rep, "+18185556046") == "do_not_call"

    # do_not_call + another rep's own at the house -> do_not_call
    assert _one(other, "+18185556047") == "added"
    theirs = _contact_for(owner_conn, "+18185556047")
    reclaim(other, "back", "young")
    with owner_conn.cursor() as cur:
        cur.execute("update contacts set do_not_call = true where id = %s", (theirs,))
    owner_conn.commit()
    assert _one(rep, "+18185556047") == "do_not_call"

    # sold + held by this rep -> already_yours
    c = _house(owner_conn, "+18185556048", stage_snapshot="won")
    _hold(owner_conn, c, rep)
    assert _one(rep, "+18185556048") == "already_yours"

    # sold + NMC's at the house -> held
    _house(owner_conn, "+18185556049", stage_snapshot="won")
    assert _one(rep, "+18185556049") == "held"

    # sold + this rep's own at the house -> held
    assert _one(rep, "+18185556050") == "added"
    mine = _contact_for(owner_conn, "+18185556050")
    reclaim(rep, "back", "young")
    with owner_conn.cursor() as cur:
        cur.execute("update contacts set stage_snapshot = 'won' where id = %s", (mine,))
    owner_conn.commit()
    assert _one(rep, "+18185556050") == "held"

    # on NMC's sheet + this rep's own -> held
    assert _one(rep, "+18185556051") == "added"
    mine = _contact_for(owner_conn, "+18185556051")
    reclaim(rep, "back", "young")
    _on_nmc_sheet(owner_conn, mine)
    assert _one(rep, "+18185556051") == "held"


# --- locking ---------------------------------------------------------------------


def _wait_until_blocked(owner_url: str, timeout: float = 5.0) -> None:
    """Until some session waits on a lock that is not granted."""
    deadline = time.monotonic() + timeout
    with psycopg.connect(owner_url, autocommit=True) as probe:
        while time.monotonic() < deadline:
            row = probe.execute("select count(*) from pg_locks where not granted").fetchone()
            if row is not None and row[0] > 0:
                return
            time.sleep(0.02)
    raise AssertionError("add_numbers never waited on the lock")


@pytest.mark.parametrize("change,expected", [
    ("do_not_call", "do_not_call"),
    ("another_rep", "held"),
    ("voice_tombstone", "do_not_call"),
    ("opt_out_event", "do_not_call"),
    ("sale_event", "held"),
])
def test_add_numbers_judges_the_row_as_it_is_under_lock(
    reps, owner_conn, owner_url, change, expected
):
    """Another connection locks the contact row, changes something, and commits only
    after add_numbers has started waiting. A judgment from any read taken before the
    lock gives `claimed` and fails."""
    rep, other = reps(), reps()
    contact = _house(owner_conn, "+18185556060")

    blocker = psycopg.connect(owner_url)
    try:
        with blocker.cursor() as cur:
            cur.execute("select id from contacts where id = %s for update", (contact,))
            if change == "do_not_call":
                cur.execute("update contacts set do_not_call = true where id = %s", (contact,))
            elif change == "another_rep":
                cur.execute("update contacts set owner_id = %s where id = %s", (other, contact))
            elif change == "voice_tombstone":
                cur.execute(
                    "insert into suppression_tombstones (phone_e164, channel, reason) "
                    "values ('+18185556060', 'voice', 'asked')"
                )
            elif change == "opt_out_event":
                cur.execute(
                    "insert into events (source, type, occurred_at, payload, contact_id) "
                    "values ('human', 'contact.opt_out', now(), '{\"reason\": \"phone\"}', %s)",
                    (contact,),
                )
            elif change == "sale_event":
                cur.execute(
                    "insert into events (source, type, occurred_at, payload, contact_id) "
                    "values ('nmc', 'signup.completed', now(), '{}', %s)",
                    (contact,),
                )

        result: dict = {}
        worker = threading.Thread(
            target=lambda: result.update(out=_one(rep, "+18185556060"))
        )
        worker.start()
        _wait_until_blocked(owner_url)
        blocker.commit()
        worker.join(timeout=10)
        assert not worker.is_alive()
    finally:
        blocker.close()

    assert result["out"] == expected


def test_a_unique_index_collision_raises_and_writes_nothing(
    reps, owner_conn, owner_url, monkeypatch
):
    rep = reps()

    def another_call_got_there_first(cur):
        with psycopg.connect(owner_url, autocommit=True) as conn:
            conn.execute(
                "insert into contacts (phone_e164, source) values ('+18185556061', 'rep')"
            )

    monkeypatch.setattr(rep_intake, "_before_insert", another_call_got_there_first)
    before = _counts(owner_conn)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _add(rep, "+18185556061")
    after = _counts(owner_conn)
    assert (after[1], after[2]) == (before[1], before[2])  # no intake_rep row, no event
    assert after[0] == before[0] + 1  # only the other call's contact


def test_a_deactivation_waits_for_the_call_and_a_later_call_is_refused(
    reps, owner_conn, owner_url, monkeypatch
):
    rep = reps()
    deactivation = threading.Thread(target=lambda: _deactivate(owner_url, rep))
    original = rep_intake._before_insert

    def deactivate_meanwhile(cur):
        deactivation.start()
        deactivation.join(timeout=1)
        assert deactivation.is_alive()  # waiting on add_numbers' for share lock
        original(cur)

    monkeypatch.setattr(rep_intake, "_before_insert", deactivate_meanwhile)
    assert _one(rep, "+18185556062") == "added"
    deactivation.join(timeout=10)
    assert not deactivation.is_alive()

    monkeypatch.setattr(rep_intake, "_before_insert", original)
    with pytest.raises(ValidationError) as err:
        _add(rep, "+18185556063")
    assert err.value.code == "bad_rep"


def _deactivate(owner_url: str, rep: UUID) -> None:
    with psycopg.connect(owner_url, autocommit=True) as conn:
        conn.execute("update partners set status = 'inactive' where id = %s", (rep,))
