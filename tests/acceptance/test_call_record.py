"""Part 5a gate: the call record (docs/contact-engine/05a-call-record.md §4, §7).

A rep opens a call on a contact they hold, whose DNC status is clear and whose zone is
known, inside hours or with a recorded confirmation; the call keeps the check it relied
on. An outcome is set once; whether a call happened is computed by the database. Memos,
calls received, an admin's clear and a 24-hour undo complete the record.
"""

import threading
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest

import service.calls as calls
from config.params import HOUSE_PARTNER_ID
from domain.errors import ValidationError
from service import dnc, zones
from service.assignment import reclaim
from service.custody import set_owner
from tests.factories import new_contact

AT = datetime(2026, 1, 15, 20, 0, tzinfo=UTC)  # noon in Los Angeles
EVENING = datetime(2026, 1, 16, 4, 0, tzinfo=UTC)  # 8 PM in Los Angeles
CALL_OUTCOMES = ("no_answer", "left_voicemail", "owner_unavailable", "busy", "call_not_placed")
CARD_OUTCOMES = ("spoke", "follow_up", "not_interested", "wrong_number", "signed_up")


# --- fixtures and helpers ---------------------------------------------------------


@pytest.fixture()
def reps(clean_db, owner_conn):
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
        cur.execute("delete from memos where rep_id = any(%s)", (made,))
        cur.execute("delete from calls_received where rep_id = any(%s)", (made,))
        cur.execute("delete from calls where rep_id = any(%s)", (made,))
        cur.execute("delete from dnc_log where rep_id = any(%s)", (made,))
        cur.execute("delete from contact_zones where rep_id = any(%s)", (made,))
        cur.execute(
            "update contacts set owner_id = %s, assignment_batch_id = null "
            "where owner_id = any(%s)",
            (HOUSE_PARTNER_ID, made),
        )
        cur.execute("delete from assignment_batches where partner_id = any(%s)", (made,))
        cur.execute("delete from partners where id = any(%s)", (made,))
    owner_conn.commit()


def _sql(owner_conn, query: str, params=()):
    with owner_conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall() if cur.description else []
    owner_conn.commit()
    return rows


def _subscribe(owner_conn, code: str = "818") -> None:
    _sql(owner_conn, "insert into dnc_subscriptions (area_code, subscribed_at) "
                     "values (%s, now()) on conflict do nothing", (code,))


def _snapshot(owner_conn, code: str) -> UUID:
    return _sql(
        owner_conn,
        "insert into dnc_snapshots (area_code, san_holder_id, version_date, file_guid, "
        "sha256, object_key, uploaded_at, status) "
        "values (%s, %s, %s, %s, %s, %s, now(), 'accepted') returning id",
        (code, HOUSE_PARTNER_ID, (AT - timedelta(days=1)).date(), uuid4().hex, uuid4().hex,
         f"dnc/t/{uuid4().hex}"),
    )[0][0]


def _hold(owner_conn, contact: UUID, rep: UUID) -> None:
    with owner_conn.cursor() as cur:
        set_owner(cur, contact, rep, event_type="contact.assigned", reason="test", actor="t")
    owner_conn.commit()


def _callable(owner_conn, rep: UUID, phone: str, **fields) -> UUID:
    """A contact `rep` holds: subscribed code, checked a day before AT, state CA."""
    _subscribe(owner_conn, phone[2:5])
    fields.setdefault("dnc_checked_at", AT - timedelta(days=1))
    fields.setdefault("addr_state", "CA")
    with owner_conn.cursor() as cur:
        contact = new_contact(cur, phone_e164=phone, intake=False, **fields)
    owner_conn.commit()
    _hold(owner_conn, contact, rep)
    return contact


def _calls(owner_conn) -> list:
    return _sql(owner_conn, "select id, outcome, happened, cleared_at from calls order by id")


def _refused(code: str, call, **detail):
    with pytest.raises(ValidationError) as err:
        call()
    assert err.value.code == code, (err.value.code, str(err.value))
    for key, value in detail.items():
        assert err.value.detail.get(key) == value, err.value.detail
    return err.value


def _wait_until_blocked(owner_url: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    with psycopg.connect(owner_url, autocommit=True) as probe:
        while time.monotonic() < deadline:
            row = probe.execute("select count(*) from pg_locks where not granted").fetchone()
            if row is not None and row[0] > 0:
                return
            time.sleep(0.02)
    raise AssertionError("nothing waited on a lock")


def _run(target) -> tuple[threading.Thread, dict]:
    out: dict = {}

    def body():
        try:
            out["value"] = target()
        except Exception as exc:  # noqa: BLE001
            out["error"] = exc

    worker = threading.Thread(target=body)
    worker.start()
    return worker, out


# --- opening ----------------------------------------------------------------------


def test_opening_records_the_check_it_relied_on(reps, owner_conn):
    rep = reps()
    snapshot = _snapshot(owner_conn, "818")
    contact = _callable(owner_conn, rep, "+18185550101", dnc_snapshot_id=snapshot)
    opened = calls.open_call(rep, contact, AT)
    assert opened.phone == "+18185550101"
    row = _sql(owner_conn,
               "select rep_id, contact_id, phone_e164, opened_at, dnc_checked_at, "
               "dnc_snapshot_id, zones, inside, outside_confirmed, happened "
               "from calls where id = %s", (opened.call_id,))[0]
    assert row == (rep, contact, "+18185550101", AT, AT - timedelta(days=1), snapshot,
                   ["America/Los_Angeles"], True, False, False)


def test_opening_refusals_in_order_write_nothing(reps, owner_conn):
    rep, other = reps(), reps()
    mine = _callable(owner_conn, rep, "+18185550102")
    theirs = _callable(owner_conn, other, "+18185550103", dnc_registry=True)
    _refused("bad_time", lambda: calls.open_call(rep, mine, datetime(2026, 1, 15, 12)))
    _refused("bad_rep", lambda: calls.open_call(HOUSE_PARTNER_ID, uuid4(), AT))
    _refused("bad_rep", lambda: calls.open_call(uuid4(), mine, AT))
    _refused("no_contact", lambda: calls.open_call(rep, uuid4(), AT))
    _refused("not_yours", lambda: calls.open_call(rep, theirs, AT))
    assert _calls(owner_conn) == []


@pytest.mark.parametrize(
    ("status", "fields"),
    [
        ("do_not_call", {"do_not_call": True}),
        ("on_dnc_file", {"dnc_registry": True}),
        ("not_checked", {"dnc_checked_at": None}),
        ("check_too_old", {"dnc_checked_at": AT - timedelta(days=40)}),
    ],
)
def test_a_non_clear_status_is_not_callable(reps, owner_conn, status, fields):
    rep = reps()
    contact = _callable(owner_conn, rep, "+18185550104", **fields)
    _refused("not_callable", lambda: calls.open_call(rep, contact, AT), status=status)
    assert _calls(owner_conn) == []


def test_no_phone_seed_and_not_covered_are_not_callable(reps, owner_conn):
    rep = reps()
    no_phone = _callable(owner_conn, rep, "+18185550105")
    _sql(owner_conn, "update contacts set phone_e164 = null where id = %s", (no_phone,))
    _refused("not_callable", lambda: calls.open_call(rep, no_phone, AT), status="no_phone")

    seed = _callable(owner_conn, rep, "+18185550106", is_seed=True,
                     seed_key=f"seed-{uuid4().hex[:6]}")
    _refused("not_callable", lambda: calls.open_call(rep, seed, AT), status="seed")

    with owner_conn.cursor() as cur:
        uncovered = new_contact(cur, phone_e164="+12135550107", intake=False,
                                addr_state="CA", created_at=AT - timedelta(days=3))
    owner_conn.commit()
    _hold(owner_conn, uncovered, rep)
    _sql(owner_conn, "insert into dnc_runs (started_at, limited) values (%s, false)",
         (AT - timedelta(days=1),))
    _refused("not_callable", lambda: calls.open_call(rep, uncovered, AT), status="not_covered")
    assert _calls(owner_conn) == []


def test_no_zone_then_the_rep_sets_it(reps, owner_conn):
    rep = reps()
    _subscribe(owner_conn, "800")
    contact = _callable(owner_conn, rep, "+18005550108", addr_state=None)
    _refused("no_zone", lambda: calls.open_call(rep, contact, AT))
    zones.set_zone(contact, "America/Los_Angeles", AT, rep=rep)
    assert calls.open_call(rep, contact, AT).call_id


def test_outside_hours_needs_a_recorded_confirmation(reps, owner_conn):
    rep = reps()
    contact = _callable(owner_conn, rep, "+18185550109")
    err = _refused("outside_hours", lambda: calls.open_call(rep, contact, EVENING))
    assert set(err.detail["local"]) == {"America/Los_Angeles"}
    assert _calls(owner_conn) == []
    opened = calls.open_call(rep, contact, EVENING, confirm_outside_hours=True)
    row = _sql(owner_conn, "select inside, outside_confirmed from calls where id = %s",
               (opened.call_id,))[0]
    assert row == (False, True)


def test_a_confirmation_sent_inside_hours_is_not_recorded(reps, owner_conn):
    rep = reps()
    contact = _callable(owner_conn, rep, "+18185550110")
    opened = calls.open_call(rep, contact, AT, confirm_outside_hours=True)
    row = _sql(owner_conn, "select inside, outside_confirmed from calls where id = %s",
               (opened.call_id,))[0]
    assert row == (True, False)


def test_one_open_call_per_contact(reps, owner_conn):
    rep, other, stranger = reps(), reps(), reps()
    contact = _callable(owner_conn, rep, "+18185550111")
    another = _callable(owner_conn, rep, "+18185550112")
    first = calls.open_call(rep, contact, AT)
    _refused("call_open", lambda: calls.open_call(rep, contact, AT), call_id=first.call_id)
    assert calls.open_call(rep, another, AT).call_id

    reclaim(rep, "back", "young")
    _hold(owner_conn, contact, other)
    _refused("call_open", lambda: calls.open_call(rep, contact, AT), call_id=first.call_id)
    err = _refused("call_open", lambda: calls.open_call(other, contact, AT))
    assert "call_id" not in err.detail
    _refused("not_yours", lambda: calls.open_call(stranger, contact, AT))

    calls.record_outcome(rep, contact, "no_answer", AT + timedelta(minutes=2),
                         call_id=first.call_id)
    assert _sql(owner_conn, "select outcome from calls where id = %s",
                (first.call_id,))[0][0] == "no_answer"


def test_a_block_landing_while_opening_is_seen(reps, owner_conn, owner_url, monkeypatch):
    rep = reps()
    contact = _callable(owner_conn, rep, "+18185550113")
    worker, out = None, {}

    def hook(cur):
        nonlocal worker, out
        if worker is not None:
            return
        worker, out = _run(lambda: calls.open_call(rep, contact, AT))
        _wait_until_blocked(owner_url)

    monkeypatch.setattr(dnc, "_after_lock", hook)
    dnc.report_do_not_call(rep, contact, "asked", AT)
    assert worker is not None
    worker.join(timeout=10)
    error = out.get("error")
    assert isinstance(error, ValidationError) and error.code == "not_callable", out
    assert _calls(owner_conn) == []


# --- outcomes ---------------------------------------------------------------------


@pytest.mark.parametrize("outcome", CALL_OUTCOMES + CARD_OUTCOMES)
def test_outcomes_on_a_call(reps, owner_conn, outcome):
    rep = reps()
    contact = _callable(owner_conn, rep, "+18185550120")
    opened = calls.open_call(rep, contact, AT)
    calls.record_outcome(rep, contact, outcome, AT + timedelta(minutes=3),
                         call_id=opened.call_id)
    happened = _sql(owner_conn, "select happened from calls where id = %s",
                    (opened.call_id,))[0][0]
    assert happened is (outcome != "call_not_placed")


def test_outcome_on_a_call_refusals(reps, owner_conn):
    rep, other = reps(), reps()
    contact = _callable(owner_conn, rep, "+18185550121")
    elsewhere = _callable(owner_conn, rep, "+18185550122")
    theirs = _callable(owner_conn, other, "+18185550123")
    mine = calls.open_call(rep, contact, AT)
    their_call = calls.open_call(other, theirs, AT)
    on_other = calls.open_call(rep, elsewhere, AT)
    later = AT + timedelta(minutes=1)
    _refused("no_call", lambda: calls.record_outcome(rep, theirs, "busy", later,
                                                     call_id=their_call.call_id))
    _refused("no_call", lambda: calls.record_outcome(rep, contact, "busy", later,
                                                     call_id=on_other.call_id))
    _refused("no_call", lambda: calls.record_outcome(rep, contact, "busy",
                                                     AT - timedelta(minutes=1),
                                                     call_id=mine.call_id))
    _refused("bad_outcome", lambda: calls.record_outcome(rep, contact, "maybe", later,
                                                         call_id=mine.call_id))
    _refused("bad_outcome", lambda: calls.record_outcome(rep, contact, "do_not_call", later,
                                                         call_id=mine.call_id))
    _refused("bad_rep", lambda: calls.record_outcome(HOUSE_PARTNER_ID, contact, "busy", later,
                                                     call_id=mine.call_id))
    _refused("bad_rep", lambda: calls.record_outcome(uuid4(), contact, "busy", later,
                                                     call_id=mine.call_id))
    calls.record_outcome(rep, contact, "busy", later, call_id=mine.call_id)
    _refused("no_call", lambda: calls.record_outcome(rep, contact, "spoke", later,
                                                     call_id=mine.call_id))
    assert _sql(owner_conn, "select outcome from calls where id = %s",
                (mine.call_id,))[0][0] == "busy"

    fresh = _callable(owner_conn, rep, "+18185550129")
    cleared = calls.open_call(rep, fresh, later)
    calls.clear_call(cleared.call_id, "young", "stuck", later)
    _refused("no_call", lambda: calls.record_outcome(rep, fresh, "busy", later,
                                                     call_id=cleared.call_id))


def test_two_outcomes_at_once(reps, owner_conn, owner_url, monkeypatch):
    rep = reps()
    contact = _callable(owner_conn, rep, "+18185550124")
    opened = calls.open_call(rep, contact, AT)
    later = AT + timedelta(minutes=2)
    holder: dict = {}

    def hook(cur):
        if "worker" in holder:
            return
        holder["worker"], holder["out"] = _run(
            lambda: calls.record_outcome(rep, contact, "spoke", later, call_id=opened.call_id))
        _wait_until_blocked(owner_url)

    monkeypatch.setattr(calls, "_after_lock", hook)
    calls.record_outcome(rep, contact, "no_answer", later, call_id=opened.call_id)
    holder["worker"].join(timeout=10)
    error = holder["out"].get("error")
    assert isinstance(error, ValidationError) and error.code == "no_call", holder["out"]
    assert _sql(owner_conn, "select outcome from calls where id = %s",
                (opened.call_id,))[0][0] == "no_answer"


@pytest.mark.parametrize("outcome", CARD_OUTCOMES)
def test_outcomes_from_the_card_are_not_calls(reps, owner_conn, outcome):
    rep = reps()
    contact = _callable(owner_conn, rep, "+18185550125")
    calls.record_outcome(rep, contact, outcome, AT)
    assert _sql(owner_conn, "select outcome, opened_at, happened from calls") == [
        (outcome, None, False)]


def test_card_outcome_refusals(reps, owner_conn):
    rep, other = reps(), reps()
    contact = _callable(owner_conn, rep, "+18185550126")
    theirs = _callable(owner_conn, other, "+18185550127")
    _refused("bad_outcome", lambda: calls.record_outcome(rep, contact, "no_answer", AT))
    _refused("not_yours", lambda: calls.record_outcome(rep, theirs, "spoke", AT))
    opened = calls.open_call(rep, contact, AT)
    _refused("call_open", lambda: calls.record_outcome(rep, contact, "spoke", AT),
             call_id=opened.call_id)
    assert len(_calls(owner_conn)) == 1


# --- memos ------------------------------------------------------------------------


def test_memos(reps, owner_conn):
    rep, other = reps(), reps()
    contact = _callable(owner_conn, rep, "+18185550130")
    theirs = _callable(owner_conn, other, "+18185550131")
    calls.add_memo(rep, contact, "owner back Monday", AT)
    outcome_id = calls.record_outcome(rep, contact, "spoke", AT, memo="wants a demo")
    rows = _sql(owner_conn, "select text, call_id from memos order by at, text")
    assert set(rows) == {("owner back Monday", None), ("wants a demo", outcome_id)}
    _refused("no_text", lambda: calls.add_memo(rep, contact, "   ", AT))
    _refused("no_text", lambda: calls.record_outcome(rep, contact, "spoke", AT, memo=" "))
    _refused("not_yours", lambda: calls.add_memo(rep, theirs, "hello", AT))
    _refused("bad_rep", lambda: calls.add_memo(HOUSE_PARTNER_ID, contact, "x", AT))
    assert len(_sql(owner_conn, "select 1 from memos")) == 2


# --- calls received ---------------------------------------------------------------


def test_calls_received(reps, owner_conn):
    rep, other = reps(), reps()
    _callable(owner_conn, rep, "+18185550140")
    _callable(owner_conn, other, "+18185550141")
    once = _callable(owner_conn, rep, "+18185550142")
    reclaim(rep, "back", "young")
    _hold(owner_conn, once, other)
    _hold(owner_conn, _sql(owner_conn, "select id from contacts where phone_e164 = "
                                       "'+18185550140'")[0][0], rep)

    held = calls.receive_call(rep, "+18185550140", AT)
    returned = calls.receive_call(rep, "(818) 555-0142", AT)
    _refused("not_yours", lambda: calls.receive_call(rep, "+18185550141", AT))
    _refused("not_yours", lambda: calls.receive_call(rep, "+18185559999", AT))
    _refused("invalid_phone", lambda: calls.receive_call(rep, "hello", AT))
    _refused("bad_rep", lambda: calls.receive_call(HOUSE_PARTNER_ID, "+18185550140", AT))

    _refused("bad_resolution", lambda: calls.resolve_received(rep, held, "maybe", AT))
    _refused("bad_time", lambda: calls.resolve_received(rep, held, "spoke",
                                                        AT - timedelta(minutes=1)))
    _refused("no_received", lambda: calls.resolve_received(other, held, "spoke", AT))
    _refused("no_received", lambda: calls.resolve_received(rep, uuid4(), "spoke", AT))
    _refused("bad_rep", lambda: calls.resolve_received(uuid4(), held, "spoke", AT))
    calls.resolve_received(rep, held, "spoke", AT)
    calls.resolve_received(rep, returned, "call_back", AT)
    _refused("already_resolved", lambda: calls.resolve_received(rep, held, "dismiss", AT))
    assert set(_sql(owner_conn, "select phone_e164, resolution from calls_received")) == {
        ("+18185550140", "spoke"), ("+18185550142", "call_back")}


# --- clear ------------------------------------------------------------------------


def test_an_admin_clears_an_open_call(reps, owner_conn):
    rep = reps()
    contact = _callable(owner_conn, rep, "+18185550150")
    opened = calls.open_call(rep, contact, AT)
    later = AT + timedelta(hours=1)
    _refused("bad_actor", lambda: calls.clear_call(opened.call_id, " ", "stuck", later))
    _refused("no_reason", lambda: calls.clear_call(opened.call_id, "young", " ", later))
    _refused("no_call", lambda: calls.clear_call(uuid4(), "young", "stuck", later))
    _refused("bad_time", lambda: calls.clear_call(opened.call_id, "young", "stuck",
                                                  AT - timedelta(minutes=1)))
    calls.clear_call(opened.call_id, "young", "stuck", later)
    assert _sql(owner_conn, "select cleared_by, cleared_reason, happened, outcome "
                            "from calls where id = %s", (opened.call_id,))[0] == (
        "young", "stuck", False, None)
    _refused("not_open", lambda: calls.clear_call(opened.call_id, "young", "again", later))

    again = calls.open_call(rep, contact, later)
    calls.record_outcome(rep, contact, "busy", later, call_id=again.call_id)
    _refused("not_open", lambda: calls.clear_call(again.call_id, "young", "stuck", later))


# --- undo -------------------------------------------------------------------------


def test_undo_signed_up_and_wrong_number_within_24_hours(reps, owner_conn):
    rep, other = reps(), reps()
    contact = _callable(owner_conn, rep, "+18185550160")
    signed = calls.record_outcome(rep, contact, "signed_up", AT)
    wrong = calls.record_outcome(rep, contact, "wrong_number", AT)
    late = calls.record_outcome(rep, contact, "wrong_number", AT)
    plain = calls.record_outcome(rep, contact, "spoke", AT)
    day = AT + timedelta(hours=24)

    _refused("no_reason", lambda: calls.undo_outcome(rep, signed, " ", day))
    _refused("no_outcome", lambda: calls.undo_outcome(other, signed, "mistake", day))
    _refused("no_outcome", lambda: calls.undo_outcome(rep, uuid4(), "mistake", day))
    _refused("not_undoable", lambda: calls.undo_outcome(rep, plain, "mistake", day))
    _refused("bad_time", lambda: calls.undo_outcome(rep, signed, "mistake",
                                                    AT - timedelta(minutes=1)))
    _refused("too_late", lambda: calls.undo_outcome(rep, late, "mistake",
                                                    day + timedelta(seconds=1)))
    _refused("bad_rep", lambda: calls.undo_outcome(HOUSE_PARTNER_ID, signed, "x", day))
    calls.undo_outcome(rep, signed, "tapped by mistake", day)
    calls.undo_outcome(rep, wrong, "it was right", day)
    _refused("already_undone", lambda: calls.undo_outcome(rep, signed, "again", day))
    rows = _sql(owner_conn, "select outcome, undone_reason from calls "
                            "where undone_at is not null order by outcome")
    assert rows == [("signed_up", "tapped by mistake"), ("wrong_number", "it was right")]


# --- the table's checks -----------------------------------------------------------


def _insert(owner_conn, rep: UUID, contact: UUID, **cols) -> None:
    names = ", ".join(["contact_id", "rep_id", *cols])
    marks = ", ".join(["%s"] * (2 + len(cols)))
    with owner_conn.cursor() as cur:
        cur.execute(f"insert into calls ({names}) values ({marks})",  # noqa: S608
                    [contact, rep, *cols.values()])


OPENED = {"phone_e164": "+18185550170", "opened_at": AT, "dnc_checked_at": AT,
          "zones": ["America/Los_Angeles"], "inside": True}


@pytest.mark.parametrize(
    "cols",
    [
        {**OPENED, "undone_at": AT, "undone_reason": "x"},
        {**OPENED, "outcome": "no_answer", "outcome_at": AT, "undone_at": AT,
         "undone_reason": "x"},
        {**OPENED, "outcome": "signed_up", "outcome_at": AT,
         "undone_at": AT - timedelta(minutes=1), "undone_reason": "x"},
        {"outcome": "busy", "outcome_at": AT},
        {"outcome": "spoke", "outcome_at": AT, "phone_e164": "+18185550170"},
        {"outcome": "spoke", "outcome_at": AT, "zones": ["America/Los_Angeles"]},
        {"outcome": "spoke", "outcome_at": AT, "inside": True},
        {"outcome": "spoke", "outcome_at": AT, "dnc_checked_at": AT},
        {"outcome": "spoke", "outcome_at": AT, "outside_confirmed": True},
        {},
        {**OPENED, "dnc_checked_at": None},
        {**OPENED, "zones": []},
        {**OPENED, "inside": False},
        {**OPENED, "outside_confirmed": True},
        {"outcome": "spoke", "outcome_at": AT, "cleared_at": AT, "cleared_by": "young",
         "cleared_reason": "x"},
        {**OPENED, "cleared_at": AT, "cleared_by": "young"},
        {**OPENED, "outcome": "busy", "outcome_at": AT, "cleared_at": AT,
         "cleared_by": "young", "cleared_reason": "x"},
        {**OPENED, "outcome": "busy", "outcome_at": AT - timedelta(minutes=1)},
    ],
    ids=["undone-without-outcome", "undone-no-answer", "undone-before-outcome",
         "card-call-outcome", "card-phone", "card-zones", "card-inside", "card-checked",
         "card-confirmed", "neither-opened-nor-outcome", "opened-unchecked",
         "opened-no-zones", "opened-outside-unconfirmed", "confirmed-inside",
         "cleared-card", "cleared-no-reason", "cleared-with-outcome", "outcome-before-call"],
)
def test_the_table_refuses_illegal_rows(reps, owner_conn, cols):
    rep = reps()
    contact = _callable(owner_conn, rep, "+18185550170")
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert(owner_conn, rep, contact, **cols)
    owner_conn.rollback()


def test_a_received_call_cannot_be_resolved_before_it_came(reps, owner_conn):
    rep = reps()
    contact = _callable(owner_conn, rep, "+18185550171")
    with pytest.raises(psycopg.errors.CheckViolation):
        with owner_conn.cursor() as cur:
            cur.execute(
                "insert into calls_received (contact_id, rep_id, phone_e164, received_at, "
                "resolution, resolved_at) values (%s, %s, '+18185550171', %s, 'spoke', %s)",
                (contact, rep, AT, AT - timedelta(minutes=1)))
    owner_conn.rollback()


# --- the clock and existing refusals ----------------------------------------------


def test_every_verb_refuses_a_naive_time(reps, owner_conn):
    rep = reps()
    contact = _callable(owner_conn, rep, "+18185550180")
    naive = datetime(2026, 1, 15, 12)
    for call in (
        lambda: calls.open_call(rep, contact, naive),
        lambda: calls.record_outcome(rep, contact, "spoke", naive),
        lambda: calls.add_memo(rep, contact, "x", naive),
        lambda: calls.receive_call(rep, "+18185550180", naive),
        lambda: calls.resolve_received(rep, uuid4(), "spoke", naive),
        lambda: calls.clear_call(uuid4(), "young", "x", naive),
        lambda: calls.undo_outcome(rep, uuid4(), "x", naive),
    ):
        _refused("bad_time", call)


def test_existing_refusals_carry_no_detail():
    err = ValidationError("bad_rep", "no rep")
    assert err.code == "bad_rep"
    assert err.detail == {}
