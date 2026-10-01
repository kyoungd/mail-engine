"""Part 5b gate: the rule (docs/contact-engine/05b-the-rule.md §4, §7).

Each contact's state is one row written by the act that changes it, under the
contact's lock; the list is read from that row, the rep's current settings, part 2's
block and the contact's zones. Dates are whole days and never come early in any zone.
"""

import threading
import time
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest

import service.calls as calls
import service.rule as rule
from config.params import HOUSE_PARTNER_ID
from domain.errors import ValidationError
from service import dnc, zones
from service.assignment import reclaim
from service.custody import set_owner
from tests.factories import new_contact

NOON = timedelta(hours=20)  # noon in Los Angeles, winter (UTC-8)
AT = datetime(2026, 1, 15, tzinfo=UTC) + NOON
EVENING = datetime(2026, 1, 16, 4, 0, tzinfo=UTC)  # 8 PM in Los Angeles


def noon(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC) + NOON


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
        cur.execute("delete from rep_settings where rep_id = any(%s)", (made,))
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


def _hold(owner_conn, contact: UUID, rep: UUID) -> None:
    with owner_conn.cursor() as cur:
        set_owner(cur, contact, rep, event_type="contact.assigned", reason="test", actor="t")
    owner_conn.commit()


_n = [0]


def _contact(owner_conn, rep: UUID, *, phone: str | None = None, state: str | None = "CA",
             checked: datetime | None = None) -> UUID:
    """A contact `rep` holds: an 818 number in a subscribed code, checked a day before AT."""
    _n[0] += 1
    phone = phone or f"+1818555{_n[0]:04d}"
    _sql(owner_conn, "insert into dnc_subscriptions (area_code, subscribed_at) "
                     "values (%s, now()) on conflict do nothing", (phone[2:5],))
    with owner_conn.cursor() as cur:
        contact = new_contact(cur, phone_e164=phone, intake=False, addr_state=state,
                              dnc_checked_at=checked or AT - timedelta(days=1))
    owner_conn.commit()
    _hold(owner_conn, contact, rep)
    return contact


def _fresh(owner_conn, contact: UUID, at: datetime) -> None:
    _sql(owner_conn, "update contacts set dnc_checked_at = %s where id = %s",
         (at - timedelta(hours=1), contact))


def _call(owner_conn, rep: UUID, contact: UUID, at: datetime, outcome: str,
          confirm: bool = False) -> UUID:
    _fresh(owner_conn, contact, at)
    opened = calls.open_call(rep, contact, at, confirm_outside_hours=confirm)
    calls.record_outcome(rep, contact, outcome, at + timedelta(minutes=1),
                         call_id=opened.call_id)
    return opened.call_id


def _state(rep, contact, at):
    return rule.contact_state(rep, contact, at)


def _is(st, lst, reason=None, **fields):
    assert st.list == lst, st
    if reason is not None:
        assert st.reason == reason, st
    for key, value in fields.items():
        assert getattr(st, key) == value, (key, st)


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


def _calls_on_due_days(owner_conn, rep, contact, outcomes, start=AT, days=3):
    """One call per outcome, each on the day the last one made due; returns the last
    call's time."""
    at = start
    for i, outcome in enumerate(outcomes):
        if i:
            at = at + timedelta(days=days if outcomes[i - 1] != "busy" else 1)
        _call(owner_conn, rep, contact, at, outcome)
    return at


# --- settings -------------------------------------------------------------------


def test_settings(reps):
    rep = reps()
    s = rule.get_settings(rep)
    assert (s.voicemails, s.calls, s.days_between, s.rest_months) == (2, 5, 3, 3)
    rule.save_settings(rep, 3, 8, 7, 6, AT)
    s = rule.get_settings(rep)
    assert (s.voicemails, s.calls, s.days_between, s.rest_months) == (3, 8, 7, 6)
    for bad in ((0, 5, 3, 3), (2, 4, 3, 3), (2, 5, 4, 3), (2, 5, 3, 2)):
        _refused("bad_setting",
                 lambda b=bad: rule.save_settings(rep, b[0], b[1], b[2], b[3], AT))
    rule.restore_defaults(rep, AT)
    s = rule.get_settings(rep)
    assert (s.voicemails, s.calls, s.days_between, s.rest_months) == (2, 5, 3, 3)


# --- the sequence ---------------------------------------------------------------


def test_never_called(reps, owner_conn):
    rep = reps()
    contact = _contact(owner_conn, rep)
    _is(_state(rep, contact, AT), "never_called", calls=0, voicemails=0)


@pytest.mark.parametrize("outcome", ["no_answer", "owner_unavailable", "left_voicemail"])
def test_a_call_makes_the_contact_due_after_the_days_between(reps, owner_conn, outcome):
    rep = reps()
    contact = _contact(owner_conn, rep)
    _call(owner_conn, rep, contact, AT, outcome)
    due = date(2026, 1, 18)
    _is(_state(rep, contact, noon(date(2026, 1, 17))), "waiting", "due_later", due=due,
        calls=1, voicemails=1 if outcome == "left_voicemail" else 0)
    _is(_state(rep, contact, noon(due)), "all_due_retries")


def test_busy_is_due_the_next_day_and_call_not_placed_changes_nothing(reps, owner_conn):
    rep = reps()
    busy, placed = _contact(owner_conn, rep), _contact(owner_conn, rep)
    _call(owner_conn, rep, busy, AT, "busy")
    _is(_state(rep, busy, AT + timedelta(hours=2)), "waiting", "due_later",
        due=date(2026, 1, 16))
    _is(_state(rep, busy, noon(date(2026, 1, 16))), "all_due_retries")
    _call(owner_conn, rep, placed, AT, "call_not_placed")
    _is(_state(rep, placed, AT), "never_called", calls=0)


def test_the_voicemail_limit_and_the_rest(reps, owner_conn):
    rep = reps()
    contact = _contact(owner_conn, rep)
    last = _calls_on_due_days(owner_conn, rep, contact, ["left_voicemail", "left_voicemail"])
    rest_until = date(2026, 4, 18)  # last call Jan 18 + 3 months
    _is(_state(rep, contact, last + timedelta(hours=1)), "limit_reached", "resting",
        rest_until=rest_until, voicemails=2)
    _is(_state(rep, contact, noon(date(2026, 4, 17))), "limit_reached", "resting")
    _is(_state(rep, contact, noon(rest_until)), "limit_reached", "rest_over")


def test_the_call_limit(reps, owner_conn):
    rep = reps()
    rule.save_settings(rep, 3, 3, 3, 1, AT)
    contact = _contact(owner_conn, rep)
    last = _calls_on_due_days(owner_conn, rep, contact, ["no_answer"] * 3)
    _is(_state(rep, contact, last + timedelta(hours=1)), "limit_reached", "resting",
        calls=3, rest_until=date(2026, 2, 21))


def test_settings_take_effect_at_once(reps, owner_conn):
    rep = reps()
    rule.save_settings(rep, 3, 8, 3, 3, AT)
    six = _contact(owner_conn, rep)
    last = _calls_on_due_days(owner_conn, rep, six, ["no_answer"] * 6)
    _is(_state(rep, six, last + timedelta(hours=1)), "waiting", calls=6)
    rule.save_settings(rep, 3, 5, 3, 3, last + timedelta(hours=2))
    _is(_state(rep, six, last + timedelta(hours=3)), "limit_reached", "resting",
        rest_until=date(2026, 4, 30))  # last call Jan 30 + 3 months

    one = _contact(owner_conn, rep)
    _call(owner_conn, rep, one, AT, "no_answer")
    _is(_state(rep, one, AT + timedelta(hours=1)), "waiting", due=date(2026, 1, 18))
    rule.save_settings(rep, 3, 5, 7, 3, AT + timedelta(hours=2))
    _is(_state(rep, one, AT + timedelta(hours=3)), "waiting", due=date(2026, 1, 22))

    rule.save_settings(rep, 1, 5, 3, 6, AT)
    resting = _contact(owner_conn, rep)
    _call(owner_conn, rep, resting, AT, "left_voicemail")
    _is(_state(rep, resting, noon(date(2026, 3, 1))), "limit_reached", "resting",
        rest_until=date(2026, 7, 15))
    rule.save_settings(rep, 1, 5, 3, 1, noon(date(2026, 3, 1)))
    _is(_state(rep, resting, noon(date(2026, 3, 1))), "limit_reached", "rest_over")


def test_add_months_clamps_the_day():
    assert rule.add_months(date(2027, 1, 31), 1) == date(2027, 2, 28)
    assert rule.add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert rule.add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)
    assert rule.add_months(date(2026, 1, 15), 6) == date(2026, 7, 15)


# --- leaving the sequence -------------------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "lst", "reason"),
    [
        ("spoke", "follow_up", None),
        ("follow_up", "follow_up", None),
        ("not_interested", "closed", "not_interested"),
        ("wrong_number", "closed", "wrong_number"),
        ("signed_up", "closed", "customer"),
    ],
)
def test_leaving_the_sequence(reps, owner_conn, outcome, lst, reason):
    rep = reps()
    contact = _contact(owner_conn, rep)
    _call(owner_conn, rep, contact, AT, outcome)
    _is(_state(rep, contact, AT + timedelta(hours=1)), lst, reason, calls=1)


def test_calls_on_follow_up_and_got_a_callback_count_nothing(reps, owner_conn):
    rep = reps()
    follow, callback = _contact(owner_conn, rep), _contact(owner_conn, rep)
    _call(owner_conn, rep, follow, AT, "spoke")
    _call(owner_conn, rep, follow, AT + timedelta(hours=1), "no_answer")
    _is(_state(rep, follow, AT + timedelta(hours=2)), "follow_up", calls=1)
    rule.move(rep, callback, "got_callback", AT)
    _call(owner_conn, rep, callback, AT + timedelta(hours=1), "left_voicemail")
    _call(owner_conn, rep, callback, AT + timedelta(hours=2), "left_voicemail")
    _is(_state(rep, callback, AT + timedelta(hours=3)), "got_callback", calls=0,
        voicemails=0)


def test_an_undo_changes_the_list_never_the_count(reps, owner_conn):
    rep = reps()
    contact = _contact(owner_conn, rep)
    last = _calls_on_due_days(owner_conn, rep, contact, ["no_answer"] * 4 + ["wrong_number"])
    _is(_state(rep, contact, last + timedelta(hours=1)), "closed", "wrong_number", calls=5)
    wrong = _sql(owner_conn, "select id from calls where contact_id = %s "
                             "and outcome = 'wrong_number'", (contact,))[0][0]
    calls.undo_outcome(rep, wrong, "it was right", last + timedelta(hours=2))
    _is(_state(rep, contact, last + timedelta(hours=3)), "limit_reached", calls=5)

    card = _contact(owner_conn, rep)
    signed = calls.record_outcome(rep, card, "signed_up", AT)
    _is(_state(rep, card, AT), "closed", "customer")
    calls.undo_outcome(rep, signed, "mistake", AT + timedelta(minutes=5))
    _is(_state(rep, card, AT + timedelta(minutes=6)), "never_called", calls=0)


def test_an_undo_keeps_the_other_closings(reps, owner_conn):
    rep = reps()
    a, b, c = (_contact(owner_conn, rep) for _ in range(3))
    calls.record_outcome(rep, a, "not_interested", AT)
    wrong = calls.record_outcome(rep, a, "wrong_number", AT)
    calls.undo_outcome(rep, wrong, "no", AT + timedelta(minutes=1))
    _is(_state(rep, a, AT + timedelta(minutes=2)), "closed", "not_interested")

    rule.move(rep, b, "closed", AT)
    signed = calls.record_outcome(rep, b, "signed_up", AT)
    calls.undo_outcome(rep, signed, "no", AT + timedelta(minutes=1))
    _is(_state(rep, b, AT + timedelta(minutes=2)), "closed", "closed")

    first = calls.record_outcome(rep, c, "wrong_number", AT)
    calls.record_outcome(rep, c, "wrong_number", AT)
    calls.undo_outcome(rep, first, "no", AT + timedelta(minutes=1))
    _is(_state(rep, c, AT + timedelta(minutes=2)), "closed", "wrong_number")


def test_do_not_call_closes(reps, owner_conn):
    rep = reps()
    contact = _contact(owner_conn, rep)
    dnc.report_do_not_call(rep, contact, "asked", AT)
    _is(_state(rep, contact, AT), "closed", "asked_not_to_be_called")


# --- calls received -------------------------------------------------------------


def test_the_holder_s_resolutions_move_the_contact(reps, owner_conn):
    rep, other = reps(), reps()
    spoke, back, dismissed, gone = (_contact(owner_conn, rep) for _ in range(4))
    phones = {c: _sql(owner_conn, "select phone_e164 from contacts where id = %s", (c,))[0][0]
              for c in (spoke, back, dismissed, gone)}
    received = {c: calls.receive_call(rep, phones[c], AT) for c in phones}
    calls.resolve_received(rep, received[spoke], "spoke", AT)
    calls.resolve_received(rep, received[back], "call_back", AT)
    calls.resolve_received(rep, received[dismissed], "dismiss", AT)
    _is(_state(rep, spoke, AT), "follow_up")
    _is(_state(rep, back, AT), "got_callback")
    _is(_state(rep, dismissed, AT), "never_called")

    reclaim(rep, "back", "young")
    _hold(owner_conn, gone, other)
    calls.resolve_received(rep, received[gone], "call_back", AT + timedelta(minutes=1))
    _is(_state(other, gone, AT + timedelta(minutes=2)), "never_called")


def test_unresolved_calls_received_are_listed(reps, owner_conn):
    rep = reps()
    contact = _contact(owner_conn, rep)
    phone = _sql(owner_conn, "select phone_e164 from contacts where id = %s", (contact,))[0][0]
    received = calls.receive_call(rep, phone, AT)
    assert rule.rep_lists(rep, AT).calls_received == [received]
    calls.resolve_received(rep, received, "dismiss", AT)
    assert rule.rep_lists(rep, AT).calls_received == []


def test_a_former_holder_s_outcome_moves_the_contact(reps, owner_conn):
    a, b = reps(), reps()
    contact = _contact(owner_conn, a)
    opened = calls.open_call(a, contact, AT)
    reclaim(a, "back", "young")
    _hold(owner_conn, contact, b)
    calls.record_outcome(a, contact, "spoke", AT + timedelta(minutes=1),
                         call_id=opened.call_id)
    _is(_state(b, contact, AT + timedelta(minutes=2)), "follow_up")


def test_leaving_limit_reached_during_the_rest(reps, owner_conn):
    rep = reps()
    rule.save_settings(rep, 1, 5, 3, 3, AT)
    via_received, via_move, via_card = (_contact(owner_conn, rep) for _ in range(3))
    for c in (via_received, via_move, via_card):
        _call(owner_conn, rep, c, AT, "left_voicemail")
        _is(_state(rep, c, AT + timedelta(hours=1)), "limit_reached")
    later = AT + timedelta(days=5)
    phone = _sql(owner_conn, "select phone_e164 from contacts where id = %s",
                 (via_received,))[0][0]
    received = calls.receive_call(rep, phone, later)
    calls.resolve_received(rep, received, "call_back", later)
    rule.move(rep, via_move, "got_callback", later)
    calls.record_outcome(rep, via_card, "spoke", later)
    _is(_state(rep, via_received, later), "got_callback")
    _is(_state(rep, via_move, later), "got_callback")
    _is(_state(rep, via_card, later), "follow_up")


# --- moves, pause, restart ------------------------------------------------------


def test_moves(reps, owner_conn):
    rep = reps()
    a, b, c = (_contact(owner_conn, rep) for _ in range(3))
    rule.move(rep, a, "got_callback", AT)
    _is(_state(rep, a, AT), "got_callback")
    rule.move(rep, b, "closed", AT)
    _is(_state(rep, b, AT), "closed", "closed")
    _refused("bad_list", lambda: rule.move(rep, a, "follow_up", AT))
    _refused("closed_already", lambda: rule.move(rep, b, "got_callback", AT))
    opened = calls.open_call(rep, c, AT)
    _refused("call_open", lambda: rule.move(rep, c, "closed", AT), call_id=opened.call_id)
    _refused("call_open", lambda: rule.pause(rep, c, date(2026, 2, 1), AT),
             call_id=opened.call_id)
    _refused("call_open", lambda: rule.restart(rep, c, AT))


def test_pause(reps, owner_conn):
    rep = reps()
    contact, early, closed = (_contact(owner_conn, rep) for _ in range(3))
    _call(owner_conn, rep, contact, AT, "no_answer")
    until = date(2026, 1, 25)
    rule.pause(rep, contact, until, AT + timedelta(hours=1))
    _is(_state(rep, contact, noon(date(2026, 1, 20))), "waiting", "paused", pause_until=until)
    _is(_state(rep, contact, noon(until)), "all_due_retries", calls=1, due=date(2026, 1, 18))

    rule.pause(rep, early, date(2026, 2, 1), AT)
    rule.pause(rep, early, date(2026, 1, 20), AT + timedelta(minutes=1))
    _is(_state(rep, early, AT), "waiting", "paused", pause_until=date(2026, 1, 20))
    rule.unpause(rep, early, AT + timedelta(minutes=2))
    _is(_state(rep, early, AT + timedelta(minutes=3)), "never_called")
    _refused("not_paused", lambda: rule.unpause(rep, early, AT + timedelta(minutes=4)))
    rule.pause(rep, early, date(2026, 1, 16), AT + timedelta(minutes=5))
    _refused("not_paused", lambda: rule.unpause(rep, early, noon(date(2026, 1, 16))))
    _refused("bad_date", lambda: rule.pause(rep, early, date(2026, 1, 15), AT))

    rule.move(rep, closed, "closed", AT)
    _refused("closed_already", lambda: rule.pause(rep, closed, date(2026, 2, 1), AT))


def test_not_pausable_and_a_restart_clears_a_pause(reps, owner_conn):
    rep = reps()
    contact = _contact(owner_conn, rep)
    _call(owner_conn, rep, contact, AT, "left_voicemail")
    rule.pause(rep, contact, date(2026, 12, 31), AT + timedelta(hours=1))
    rule.save_settings(rep, 1, 5, 3, 3, AT + timedelta(hours=2))
    _is(_state(rep, contact, AT + timedelta(hours=3)), "limit_reached")
    _refused("not_pausable", lambda: rule.pause(rep, contact, date(2026, 12, 31),
                                                AT + timedelta(hours=3)))
    rule.restart(rep, contact, noon(date(2026, 4, 15)))
    _is(_state(rep, contact, noon(date(2026, 4, 16))), "never_called", calls=0)


def test_restart(reps, owner_conn):
    rep = reps()
    rule.save_settings(rep, 1, 5, 3, 3, AT)
    contact, fresh = _contact(owner_conn, rep), _contact(owner_conn, rep)
    _refused("not_limit_reached", lambda: rule.restart(rep, fresh, AT))
    _call(owner_conn, rep, contact, AT, "left_voicemail")
    _refused("still_resting", lambda: rule.restart(rep, contact, noon(date(2026, 4, 14))))
    rule.restart(rep, contact, noon(date(2026, 4, 15)))
    _is(_state(rep, contact, noon(date(2026, 4, 15))), "never_called", calls=0, voicemails=0)


def test_restart_with_a_former_holder_s_call_open(reps, owner_conn):
    a, b = reps(), reps()
    contact = _contact(owner_conn, a)
    calls.open_call(a, contact, AT)
    reclaim(a, "back", "young")
    _hold(owner_conn, contact, b)
    _refused("call_open", lambda: rule.restart(b, contact, AT))


# --- days in several zones ------------------------------------------------------


def test_a_day_never_comes_early_in_any_zone(reps, owner_conn):
    rep = reps()
    contact = _contact(owner_conn, rep, state="AZ")
    assert zones.calling_hours(contact, AT).zones == {
        "America/Los_Angeles", "America/Phoenix", "America/Denver"}
    late = datetime(2026, 1, 16, 7, 30, tzinfo=UTC)  # 23:30 Pacific, Jan 15
    _call(owner_conn, rep, contact, late, "no_answer", confirm=True)
    before = datetime(2026, 1, 19, 7, 30, tzinfo=UTC)  # 23:30 Pacific, Jan 18
    _is(_state(rep, contact, before), "waiting", "due_later", due=date(2026, 1, 19))
    _is(_state(rep, contact, noon(date(2026, 1, 19))), "all_due_retries")


# --- a new holder and the lists -------------------------------------------------


def test_a_new_holder_inherits_the_state(reps, owner_conn):
    a, b = reps(), reps()
    rule.save_settings(a, 1, 5, 3, 3, AT)
    rule.save_settings(b, 1, 5, 3, 3, AT)
    limited, closed, paused = (_contact(owner_conn, a) for _ in range(3))
    _call(owner_conn, a, limited, AT, "left_voicemail")
    rule.move(a, closed, "closed", AT)
    rule.pause(a, paused, date(2026, 2, 1), AT)
    reclaim(a, "back", "young")
    for c in (limited, closed, paused):
        _hold(owner_conn, c, b)
    later = AT + timedelta(hours=1)
    _is(_state(b, limited, later), "limit_reached")
    _is(_state(b, closed, later), "closed", "closed")
    _is(_state(b, paused, later), "waiting", "paused")


def test_the_lists_agree_with_contact_state(reps, owner_conn):
    rep, other = reps(), reps()
    rule.save_settings(rep, 1, 5, 3, 3, AT)
    made = {}
    made["never"] = _contact(owner_conn, rep)
    made["due"] = _contact(owner_conn, rep)
    _call(owner_conn, rep, made["due"], AT - timedelta(days=4), "no_answer")
    made["waiting"] = _contact(owner_conn, rep)
    _call(owner_conn, rep, made["waiting"], AT - timedelta(days=1), "no_answer")
    made["resting"] = _contact(owner_conn, rep)
    _call(owner_conn, rep, made["resting"], AT - timedelta(days=2), "left_voicemail")
    made["rest_over"] = _contact(owner_conn, rep)
    _call(owner_conn, rep, made["rest_over"], AT - timedelta(days=100), "left_voicemail")
    made["paused"] = _contact(owner_conn, rep)
    rule.pause(rep, made["paused"], date(2026, 2, 1), AT - timedelta(hours=1))
    made["callback"] = _contact(owner_conn, rep)
    rule.move(rep, made["callback"], "got_callback", AT - timedelta(hours=1))
    made["follow"] = _contact(owner_conn, rep)
    calls.record_outcome(rep, made["follow"], "follow_up", AT - timedelta(hours=1))
    for reason, outcome in (("customer", "signed_up"), ("wrong", "wrong_number"),
                            ("notint", "not_interested")):
        made[reason] = _contact(owner_conn, rep)
        calls.record_outcome(rep, made[reason], outcome, AT - timedelta(hours=1))
    made["closed"] = _contact(owner_conn, rep)
    rule.move(rep, made["closed"], "closed", AT - timedelta(hours=1))
    made["dnc"] = _contact(owner_conn, rep)
    dnc.report_do_not_call(rep, made["dnc"], "asked", AT - timedelta(hours=1))
    made["zones"] = _contact(owner_conn, rep, state="AZ")
    _call(owner_conn, rep, made["zones"], datetime(2026, 1, 13, 7, 30, tzinfo=UTC),
          "no_answer", confirm=True)
    theirs = _contact(owner_conn, other)

    lists = rule.rep_lists(rep, AT)
    assert set(lists.by_contact) == set(made.values())
    assert theirs not in lists.by_contact
    for name, contact in made.items():
        assert lists.by_contact[contact] == rule.contact_state(rep, contact, AT), name
    seen = {lists.by_contact[c].list for c in made.values()}
    assert seen == {"never_called", "all_due_retries", "waiting", "limit_reached",
                    "got_callback", "follow_up", "closed"}


# --- order and transactions -----------------------------------------------------


def test_an_outcome_waiting_on_a_move_is_judged_after_it(reps, owner_conn, owner_url,
                                                         monkeypatch):
    a, b = reps(), reps()
    contact = _contact(owner_conn, a)
    opened = calls.open_call(a, contact, AT)
    reclaim(a, "back", "young")
    _hold(owner_conn, contact, b)
    holder: dict = {}

    def hook(cur):
        if "worker" in holder:
            return
        holder["worker"], holder["out"] = _run(lambda: calls.record_outcome(
            a, contact, "no_answer", AT + timedelta(minutes=2), call_id=opened.call_id))
        _wait_until_blocked(owner_url)

    monkeypatch.setattr(rule, "_after_lock", hook)
    rule.move(b, contact, "got_callback", AT + timedelta(minutes=1))
    holder["worker"].join(timeout=10)
    assert "error" not in holder["out"], holder["out"]
    _is(_state(b, contact, AT + timedelta(minutes=3)), "got_callback", calls=0)


def test_a_resolution_waiting_on_a_change_of_holder_writes_nothing(reps, owner_conn,
                                                                   owner_url):
    a, b = reps(), reps()
    contact = _contact(owner_conn, a)
    phone = _sql(owner_conn, "select phone_e164 from contacts where id = %s", (contact,))[0][0]
    received = calls.receive_call(a, phone, AT)
    with psycopg.connect(owner_url) as blocker:
        with blocker.cursor() as cur:
            cur.execute("select 1 from contacts where id = %s for update", (contact,))
            set_owner(cur, contact, b, event_type="contact.assigned", reason="t", actor="t")
            worker, out = _run(lambda: calls.resolve_received(a, received, "call_back",
                                                              AT + timedelta(minutes=1)))
            _wait_until_blocked(owner_url)
        blocker.commit()
    worker.join(timeout=10)
    assert "error" not in out, out
    _is(_state(b, contact, AT + timedelta(minutes=2)), "never_called")


def _with_timeout(call, seconds: float = 10.0):
    worker, out = _run(call)
    worker.join(timeout=seconds)
    assert not worker.is_alive(), "the act hung"
    return out


def test_a_failed_state_write_rolls_the_outcome_back(reps, owner_conn, monkeypatch):
    rep = reps()
    contact = _contact(owner_conn, rep)
    opened = calls.open_call(rep, contact, AT)

    def boom(cur, contact_id, change):
        raise RuntimeError("state write failed")

    monkeypatch.setattr(rule, "_write_state", boom)
    out = _with_timeout(lambda: calls.record_outcome(
        rep, contact, "no_answer", AT + timedelta(minutes=1), call_id=opened.call_id))
    assert isinstance(out.get("error"), RuntimeError)
    assert _sql(owner_conn, "select outcome from calls where id = %s",
                (opened.call_id,))[0][0] is None


def test_a_failure_after_the_state_write_rolls_it_back(reps, owner_conn, monkeypatch):
    rep = reps()
    contact = _contact(owner_conn, rep)
    opened = calls.open_call(rep, contact, AT)
    real = rule._write_state

    def then_boom(cur, contact_id, change):
        real(cur, contact_id, change)
        raise RuntimeError("after the state write")

    monkeypatch.setattr(rule, "_write_state", then_boom)
    out = _with_timeout(lambda: calls.record_outcome(
        rep, contact, "no_answer", AT + timedelta(minutes=1), call_id=opened.call_id))
    assert isinstance(out.get("error"), RuntimeError)
    monkeypatch.undo()
    _is(_state(rep, contact, AT + timedelta(minutes=2)), "never_called", calls=0)


# --- may I call ------------------------------------------------------------------


def test_part_2_s_refusal_keeps_the_list(reps, owner_conn):
    rep = reps()
    contact = _contact(owner_conn, rep, checked=AT - timedelta(days=40))
    _is(_state(rep, contact, AT), "never_called")
    _refused("not_callable", lambda: calls.open_call(rep, contact, AT))


def test_open_call_and_may_call_refuse_what_the_rule_does_not_allow(reps, owner_conn):
    rep = reps()
    rule.save_settings(rep, 1, 5, 3, 3, AT)
    closed, limited, paused, waiting, ok = (_contact(owner_conn, rep) for _ in range(5))
    rule.move(rep, closed, "closed", AT - timedelta(days=2))
    _call(owner_conn, rep, limited, AT - timedelta(days=2), "left_voicemail")
    rule.pause(rep, paused, date(2026, 2, 1), AT - timedelta(days=2))
    _call(owner_conn, rep, waiting, AT - timedelta(days=1), "no_answer")
    for c in (closed, limited, paused, waiting, ok):
        _fresh(owner_conn, c, AT)
    cases = [
        (closed, "closed", {"reason": "closed"}),
        (limited, "limit_reached", {"rest_until": date(2026, 4, 13)}),
        (paused, "paused", {"until": date(2026, 2, 1)}),
        (waiting, "not_due", {"due": date(2026, 1, 17)}),
    ]
    for contact, code, detail in cases:
        _refused(code, lambda c=contact: calls.open_call(rep, c, AT), **detail)
        _refused(code, lambda c=contact: rule.may_call(rep, c, AT), **detail)
    assert rule.may_call(rep, ok, AT) == _sql(
        owner_conn, "select phone_e164 from contacts where id = %s", (ok,))[0][0]
    err = _refused("outside_hours", lambda: rule.may_call(rep, ok, EVENING))
    assert set(err.detail["local"]) == {"America/Los_Angeles"}
    assert calls.open_call(rep, ok, AT).call_id


def test_the_four_callable_lists_open(reps, owner_conn):
    rep = reps()
    never, due, callback, follow = (_contact(owner_conn, rep) for _ in range(4))
    _call(owner_conn, rep, due, AT - timedelta(days=4), "no_answer")
    rule.move(rep, callback, "got_callback", AT - timedelta(hours=2))
    calls.record_outcome(rep, follow, "follow_up", AT - timedelta(hours=2))
    for c in (never, due, callback, follow):
        _fresh(owner_conn, c, AT)
        assert calls.open_call(rep, c, AT).call_id


def test_no_zone_comes_before_the_rule(reps, owner_conn):
    rep = reps()
    contact = _contact(owner_conn, rep, phone="+18005550199", state=None)
    _sql(owner_conn,
         "insert into contact_state (contact_id, calls, last_call_at, updated_at) "
         "values (%s, 1, %s, %s)", (contact, AT - timedelta(hours=1), AT))
    _refused("no_zone", lambda: calls.open_call(rep, contact, AT))


# --- refusals -------------------------------------------------------------------


def test_refusals(reps, owner_conn):
    rep, other = reps(), reps()
    mine, theirs = _contact(owner_conn, rep), _contact(owner_conn, other)
    naive = datetime(2026, 1, 15, 12)
    on_contact = [
        lambda r, c, t: rule.contact_state(r, c, t),
        lambda r, c, t: rule.may_call(r, c, t),
        lambda r, c, t: rule.move(r, c, "got_callback", t),
        lambda r, c, t: rule.pause(r, c, date(2026, 2, 1), t),
        lambda r, c, t: rule.unpause(r, c, t),
        lambda r, c, t: rule.restart(r, c, t),
    ]
    for verb in on_contact:
        _refused("bad_time", lambda v=verb: v(rep, mine, naive))
        _refused("bad_rep", lambda v=verb: v(HOUSE_PARTNER_ID, mine, AT))
        _refused("bad_rep", lambda v=verb: v(uuid4(), mine, AT))
        _refused("no_contact", lambda v=verb: v(rep, uuid4(), AT))
        _refused("not_yours", lambda v=verb: v(rep, theirs, AT))
    _refused("bad_time", lambda: rule.save_settings(rep, 2, 5, 3, 3, naive))
    _refused("bad_rep", lambda: rule.save_settings(HOUSE_PARTNER_ID, 2, 5, 3, 3, AT))
    _refused("bad_time", lambda: rule.restore_defaults(rep, naive))
    _refused("bad_rep", lambda: rule.get_settings(uuid4()))
    _refused("bad_time", lambda: rule.rep_lists(rep, naive))
    _refused("bad_rep", lambda: rule.rep_lists(HOUSE_PARTNER_ID, AT))
