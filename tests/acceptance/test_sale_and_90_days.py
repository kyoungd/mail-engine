"""Part 5c gate: the sale and the 90 days (docs/contact-engine/05c-sale-and-90-days.md
§4, §7).

A sold contact stays with its seller — the rep who signed, else the holder recorded when
the website's sale first reached the nightly — and is never returned, given out, or
taken by a second sale; a take-back from a rep is never undone by that rep's late
Signed up. NMC's contacts in Got a callback or Follow up do not go back at 90 days;
closed and resting contacts are not given out.
"""

import threading
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest

import service.calls as calls
import service.rule as rule
from config.params import HOUSE_PARTNER_ID
from domain.errors import ValidationError
from domain.types import RepRow
from jobs.nightly import run_nightly
from service import dnc, rep_intake
from service.assignment import (
    assign_batch,
    get_more_numbers,
    reclaim,
    run_expiry_step,
    run_won_termination_step,
)
from service.contacts import suppress
from service.ingestion import ingest_event
from service.state import recompute_state
from tests.factories import new_contact

CONFIRMATION = "These are businesses I found through my own prospecting."
LA = "LA area"


def _now() -> datetime:
    return datetime.now(UTC)


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
        cur.execute("delete from intake_rep where rep_id = any(%s)", (made,))
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


_n = [0]


def _contact(owner_conn) -> UUID:
    """NMC's contact the house holds: an 818 number, subscribed, freshly checked, CA."""
    _n[0] += 1
    _sql(owner_conn, "insert into dnc_subscriptions (area_code, subscribed_at) "
                     "values ('818', now()) on conflict do nothing")
    with owner_conn.cursor() as cur:
        contact = new_contact(cur, phone_e164=f"+1818555{_n[0]:04d}", intake=False,
                              addr_state="CA", dnc_checked_at=_now() - timedelta(hours=1))
    owner_conn.commit()
    return contact


def _phone(owner_conn, contact: UUID) -> str:
    return _sql(owner_conn, "select phone_e164 from contacts where id = %s", (contact,))[0][0]


def _owner(owner_conn, contact: UUID) -> UUID:
    return _sql(owner_conn, "select owner_id from contacts where id = %s", (contact,))[0][0]


def _pointer(owner_conn, contact: UUID):
    return _sql(owner_conn, "select assignment_batch_id from contacts where id = %s",
                (contact,))[0][0]


def _web_seller(owner_conn, contact: UUID):
    rows = _sql(owner_conn, "select web_seller from contact_state where contact_id = %s",
                (contact,))
    return rows[0][0] if rows else None


def _batch(partner: UUID, *contacts: UUID):
    return assign_batch(partner, f"k-{uuid4().hex[:10]}", "young", contact_ids=list(contacts))


def _expire_batches(owner_conn, partner: UUID) -> None:
    _sql(owner_conn, "update assignment_batches set expires_at = now() - interval '1 day' "
                     "where partner_id = %s", (partner,))


def _add(owner_conn, rep: UUID, contact: UUID) -> str:
    results = rep_intake.add_numbers(rep, [RepRow(phone=_phone(owner_conn, contact))],
                                     "referral", CONFIRMATION, _now())
    return results[0].result


def _open(owner_conn, rep: UUID, contact: UUID) -> UUID:
    _sql(owner_conn, "update contacts set dnc_checked_at = %s where id = %s",
         (_now() - timedelta(hours=1), contact))
    return calls.open_call(rep, contact, _now(), confirm_outside_hours=True).call_id


def _sign(rep: UUID, contact: UUID, call_id: UUID | None = None):
    return calls.record_outcome(rep, contact, "signed_up", _now(), call_id=call_id)


def _backdate_assigned(owner_conn, contact: UUID, days: int) -> None:
    _sql(owner_conn, "update events set occurred_at = now() - make_interval(days => %s) "
                     "where contact_id = %s and type = 'contact.assigned'", (days, contact))


def _expired_to_house(owner_conn, rep: UUID, contact: UUID) -> None:
    """The contact goes back from `rep` by expiry."""
    _expire_batches(owner_conn, rep)
    run_expiry_step()
    assert _owner(owner_conn, contact) == HOUSE_PARTNER_ID


def _website_sale(contact: UUID) -> None:
    ingest_event("posthog", "signup.completed", _now(), {}, contact_id=contact)
    recompute_state()


def _refused(code: str, call):
    with pytest.raises(ValidationError) as err:
        call()
    assert err.value.code == code, (err.value.code, str(err.value))
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


def _while_waiting(monkeypatch, owner_url, module, waiter, act):
    """`act` runs; its first `module._after_lock` starts `waiter` in a thread and waits
    until it blocks on the lock `act` holds. Returns the waiter's outcome."""
    holder: dict = {}

    def hook(cur):
        if "worker" in holder:
            return
        holder["worker"], holder["out"] = _run(waiter)
        _wait_until_blocked(owner_url)

    monkeypatch.setattr(module, "_after_lock", hook)
    act()
    monkeypatch.undo()
    holder["worker"].join(timeout=10)
    assert not holder["worker"].is_alive()
    return holder["out"]


# --- the sale holds -------------------------------------------------------------


def test_a_signed_up_holds(reps, owner_conn):
    r, p, other = reps(), reps(), reps()
    x = _contact(owner_conn)
    _batch(r, x)
    _sign(r, x, _open(owner_conn, r, x))
    assert (_owner(owner_conn, x), _pointer(owner_conn, x)) == (r, None)
    _backdate_assigned(owner_conn, x, 91)
    run_expiry_step()
    assert _owner(owner_conn, x) == r
    assert _batch(p, x).shortfall == {"already_assigned": [x]}
    assert _add(owner_conn, other, x) == "held"
    reclaim(r, "back", "young")
    assert _batch(p, x).shortfall == {"won": [x]}


def test_the_rep_who_signed_takes_it(reps, owner_conn):
    a, b = reps(), reps()
    x = _contact(owner_conn)
    _batch(a, x)
    call = _open(owner_conn, a, x)
    _expired_to_house(owner_conn, a, x)
    assert _add(owner_conn, b, x) == "claimed"
    _sign(a, x, call)
    assert (_owner(owner_conn, x), _pointer(owner_conn, x)) == (a, None)


def test_a_take_back_before_the_call_does_not_block(reps, owner_conn):
    a = reps()
    x = _contact(owner_conn)
    _batch(a, x)
    reclaim(a, "back", "young")
    _batch(a, x)
    call = _open(owner_conn, a, x)
    _expired_to_house(owner_conn, a, x)
    _sign(a, x, call)
    assert _owner(owner_conn, x) == a


# --- the first sale stands ------------------------------------------------------


def test_a_second_signed_up_is_refused(reps, owner_conn):
    a, b = reps(), reps()
    x = _contact(owner_conn)
    _batch(a, x)
    call = _open(owner_conn, a, x)
    _expired_to_house(owner_conn, a, x)
    assert _add(owner_conn, b, x) == "claimed"
    _sign(b, x)
    _refused("sold", lambda: _sign(a, x, call))
    assert _owner(owner_conn, x) == b


def test_a_website_sale_records_its_seller(reps, owner_conn):
    a, b = reps(), reps()
    x = _contact(owner_conn)
    _batch(a, x)
    call = _open(owner_conn, a, x)
    _expired_to_house(owner_conn, a, x)
    assert _add(owner_conn, b, x) == "claimed"
    _website_sale(x)
    run_won_termination_step()
    assert _web_seller(owner_conn, x) == b
    reclaim(b, "back", "young")
    _refused("sold", lambda: _sign(a, x, call))


def test_the_recorded_seller_s_late_signed_up_after_a_reclaim(reps, owner_conn):
    b = reps()
    x = _contact(owner_conn)
    assert _add(owner_conn, b, x) == "claimed"
    b_call = _open(owner_conn, b, x)
    _website_sale(x)
    run_won_termination_step()
    assert _web_seller(owner_conn, x) == b
    reclaim(b, "back", "young")
    _sign(b, x, b_call)
    assert _owner(owner_conn, x) == HOUSE_PARTNER_ID
    assert _sql(owner_conn, "select outcome from calls where id = %s",
                (b_call,))[0][0] == "signed_up"


def test_an_undo_does_not_free_a_website_sale(reps, owner_conn):
    a, b = reps(), reps()
    x = _contact(owner_conn)
    _batch(b, x)
    b_call = _open(owner_conn, b, x)
    _expired_to_house(owner_conn, b, x)
    assert _add(owner_conn, a, x) == "claimed"
    signed = _sign(a, x)
    _website_sale(x)
    run_won_termination_step()
    assert _web_seller(owner_conn, x) == a
    calls.undo_outcome(a, signed, "mistake", _now())
    _refused("sold", lambda: _sign(b, x, b_call))
    assert _owner(owner_conn, x) == a


# --- no pull-back -----------------------------------------------------------------


def _house_after(owner_conn, reps, how: str):
    """A's open call on X, then X taken back to the house in the way named."""
    a = reps()
    x = _contact(owner_conn)
    _batch(a, x)
    call = _open(owner_conn, a, x)
    if how == "reclaim_ended":
        _sql(owner_conn, "update partners set status = 'inactive' where id = %s", (a,))
        reclaim(a, "partnership ended", "young")
    elif how == "reclaim_active":
        reclaim(a, "back", "young")
    elif how == "suppression":
        suppress(x, "voice", "asked")
    elif how == "dnc_hit":
        with owner_conn.cursor() as cur:
            cur.execute("update contacts set dnc_registry = true where id = %s", (x,))
        owner_conn.commit()
        reclaim(a, "dnc", "system")
    assert _owner(owner_conn, x) == HOUSE_PARTNER_ID
    return a, x, call


@pytest.mark.parametrize("how", ["reclaim_ended", "reclaim_active", "suppression",
                                 "dnc_hit"])
def test_a_late_signed_up_never_undoes_a_take_back(reps, owner_conn, how):
    a, x, call = _house_after(owner_conn, reps, how)
    _sign(a, x, call)
    assert _owner(owner_conn, x) == HOUSE_PARTNER_ID
    assert _sql(owner_conn, "select outcome from calls where id = %s",
                (call,))[0][0] == "signed_up"


def test_a_take_back_then_nmc_s_sheet_stays(reps, owner_conn):
    a, x, call = _house_after(owner_conn, reps, "reclaim_active")
    _batch(HOUSE_PARTNER_ID, x)
    _sign(a, x, call)
    assert _owner(owner_conn, x) == HOUSE_PARTNER_ID
    assert _pointer(owner_conn, x) is not None


def test_an_inactive_signer_does_not_take_it(reps, owner_conn):
    a, b = reps(), reps()
    x, y = _contact(owner_conn), _contact(owner_conn)
    _batch(a, x, y)
    cx, cy = _open(owner_conn, a, x), _open(owner_conn, a, y)
    _expired_to_house(owner_conn, a, x)
    assert _add(owner_conn, b, y) == "claimed"
    _sql(owner_conn, "update partners set status = 'inactive' where id = %s", (a,))
    _sign(a, x, cx)
    assert _owner(owner_conn, x) == HOUSE_PARTNER_ID
    _sign(a, y, cy)
    assert _owner(owner_conn, y) == HOUSE_PARTNER_ID


def test_a_dnc_file_hit_after_expiry_stops_the_move(reps, owner_conn):
    a = reps()
    x = _contact(owner_conn)
    _batch(a, x)
    call = _open(owner_conn, a, x)
    _expired_to_house(owner_conn, a, x)
    _sql(owner_conn, "update contacts set dnc_registry = true where id = %s", (x,))
    _sign(a, x, call)
    assert _owner(owner_conn, x) == HOUSE_PARTNER_ID


def test_a_blocked_number_held_by_another_rep_goes_to_the_house(reps, owner_conn):
    a, b = reps(), reps()
    x = _contact(owner_conn)
    _batch(a, x)
    call = _open(owner_conn, a, x)
    _expired_to_house(owner_conn, a, x)
    assert _add(owner_conn, b, x) == "claimed"
    dnc.report_do_not_call(b, x, "asked", _now())
    assert _owner(owner_conn, x) == b
    _sign(a, x, call)
    assert _owner(owner_conn, x) == HOUSE_PARTNER_ID


def test_the_signed_up_takes_the_partner_lock_first(reps, owner_conn, owner_url):
    a = reps()
    x = _contact(owner_conn)
    _batch(a, x)
    call = _open(owner_conn, a, x)
    with psycopg.connect(owner_url) as blocker:
        blocker.execute("select 1 from partners where id = %s for update", (a,))
        worker, out = _run(lambda: _sign(a, x, call))
        _wait_until_blocked(owner_url)
        with psycopg.connect(owner_url) as probe:
            probe.execute("select 1 from contacts where id = %s for update nowait", (x,))
            probe.rollback()
        blocker.rollback()
    worker.join(timeout=10)
    assert "error" not in out, out


# --- undo -------------------------------------------------------------------------


def test_an_undone_signed_up_stays_then_goes_back_at_90_days(reps, owner_conn):
    a = reps()
    x = _contact(owner_conn)
    assert _add(owner_conn, a, x) == "claimed"
    signed = _sign(a, x)
    calls.undo_outcome(a, signed, "mistake", _now())
    assert _owner(owner_conn, x) == a
    _backdate_assigned(owner_conn, x, 91)
    assert run_expiry_step() == 1
    assert _owner(owner_conn, x) == HOUSE_PARTNER_ID


# --- the website's sale -----------------------------------------------------------


def test_the_won_step_keeps_a_rep_s_sale(reps, owner_conn):
    r = reps()
    held, sheet = _contact(owner_conn), _contact(owner_conn)
    _batch(r, held)
    _batch(HOUSE_PARTNER_ID, sheet)
    _website_sale(held)
    _website_sale(sheet)
    assert run_won_termination_step() == 2
    assert (_owner(owner_conn, held), _pointer(owner_conn, held)) == (r, None)
    assert (_owner(owner_conn, sheet), _pointer(owner_conn, sheet)) == (HOUSE_PARTNER_ID,
                                                                       None)
    assert _web_seller(owner_conn, held) == r
    assert _web_seller(owner_conn, sheet) == HOUSE_PARTNER_ID


def test_a_sale_whose_batch_expired_the_same_night_stays(reps, owner_conn):
    r = reps()
    x = _contact(owner_conn)
    _batch(r, x)
    _expire_batches(owner_conn, r)
    ingest_event("posthog", "signup.completed", _now(), {}, contact_id=x)
    run_nightly()
    assert (_owner(owner_conn, x), _pointer(owner_conn, x)) == (r, None)


def test_an_unmatched_sale_with_an_expired_batch(reps, owner_conn):
    r = reps()
    x = _contact(owner_conn)
    _batch(r, x)
    _expire_batches(owner_conn, r)
    ingest_event("posthog", "signup.completed", _now(), {"phone_e164": _phone(owner_conn, x)})
    run_expiry_step()
    run_won_termination_step()
    assert (_owner(owner_conn, x), _pointer(owner_conn, x)) == (r, None)


def test_a_website_sale_is_closed_in_the_rule(reps, owner_conn):
    r = reps()
    x = _contact(owner_conn)
    _batch(r, x)
    _website_sale(x)
    run_won_termination_step()
    st = rule.contact_state(r, x, _now())
    assert (st.list, st.reason) == ("closed", "customer")
    _refused("closed", lambda: _open(owner_conn, r, x))


# --- re-read after the lock -------------------------------------------------------


def test_the_gate_sees_a_sale_landing_while_it_waits(reps, owner_conn, owner_url,
                                                     monkeypatch):
    a, p = reps(), reps()
    a2, x, call = _house_after(owner_conn, lambda: a, "reclaim_active")
    out = _while_waiting(monkeypatch, owner_url, calls, lambda: _batch(p, x),
                         lambda: _sign(a2, x, call))
    assert out["value"].shortfall == {"won": [x]}


def test_the_gate_sees_a_closing_landing_while_it_waits(reps, owner_conn, owner_url,
                                                        monkeypatch):
    a, p = reps(), reps()
    a2, x, call = _house_after(owner_conn, lambda: a, "reclaim_active")
    out = _while_waiting(
        monkeypatch, owner_url, calls, lambda: _batch(p, x),
        lambda: calls.record_outcome(a2, x, "wrong_number", _now(), call_id=call))
    assert out["value"].shortfall == {"closed": [x]}


def test_the_batch_rule_sees_a_sale_landing_while_it_waits(reps, owner_conn, owner_url,
                                                           monkeypatch):
    r = reps()
    x = _contact(owner_conn)
    _batch(r, x)
    _expire_batches(owner_conn, r)
    _sql(owner_conn, "update partners set status = 'inactive' where id = %s", (r,))
    out = _while_waiting(monkeypatch, owner_url, calls, run_expiry_step,
                         lambda: _sign(r, x))
    assert out["value"] == 0
    assert _owner(owner_conn, x) == r


@pytest.mark.parametrize("act", ["got_callback", "signed_up", "follow_up"])
def test_the_expiry_re_reads_after_the_lock(reps, owner_conn, owner_url, monkeypatch, act):
    r = reps()
    x = _contact(owner_conn)
    if act == "got_callback":
        _batch(r, x)
        _expire_batches(owner_conn, r)
        module, do = rule, (lambda: rule.move(r, x, "got_callback", _now()))
    else:
        assert _add(owner_conn, r, x) == "claimed"
        _backdate_assigned(owner_conn, x, 91)
        module, do = calls, (lambda: calls.record_outcome(r, x, act, _now()))
    out = _while_waiting(monkeypatch, owner_url, module, run_expiry_step, do)
    assert out["value"] == 0
    assert _owner(owner_conn, x) == r


# --- Got a callback / Follow up ---------------------------------------------------


def _into(rep, x, lst):
    if lst == "got_callback":
        rule.move(rep, x, "got_callback", _now())
    else:
        calls.record_outcome(rep, x, "follow_up", _now())


@pytest.mark.parametrize("lst", ["got_callback", "follow_up"])
@pytest.mark.parametrize("by", ["batch", "claim"])
def test_callbacks_and_follow_ups_do_not_go_back(reps, owner_conn, lst, by):
    r = reps()
    x = _contact(owner_conn)
    if by == "batch":
        _batch(r, x)
    else:
        assert _add(owner_conn, r, x) == "claimed"
    _into(r, x, lst)
    if by == "batch":
        _expire_batches(owner_conn, r)
    else:
        _backdate_assigned(owner_conn, x, 91)
    assert run_expiry_step() == 0
    assert _owner(owner_conn, x) == r


def test_a_paused_follow_up_does_not_go_back(reps, owner_conn):
    r = reps()
    x = _contact(owner_conn)
    assert _add(owner_conn, r, x) == "claimed"
    _into(r, x, "follow_up")
    rule.pause(r, x, (_now() + timedelta(days=30)).date(), _now())
    _backdate_assigned(owner_conn, x, 91)
    assert run_expiry_step() == 0


@pytest.mark.parametrize("then", ["closed", "blocked"])
def test_a_follow_up_closed_or_blocked_goes_back(reps, owner_conn, then):
    r = reps()
    x = _contact(owner_conn)
    assert _add(owner_conn, r, x) == "claimed"
    _into(r, x, "follow_up")
    if then == "closed":
        rule.move(r, x, "closed", _now())
    else:
        dnc.report_do_not_call(r, x, "asked", _now())
    _backdate_assigned(owner_conn, x, 91)
    assert run_expiry_step() == 1
    assert _owner(owner_conn, x) == HOUSE_PARTNER_ID


def test_nmc_s_own_sheet_is_not_exempt(reps, owner_conn):
    x = _contact(owner_conn)
    _batch(HOUSE_PARTNER_ID, x)
    _sql(owner_conn, "insert into contact_state (contact_id, list, updated_at) "
                     "values (%s, 'follow_up', now())", (x,))
    _expire_batches(owner_conn, HOUSE_PARTNER_ID)
    assert run_expiry_step() == 1
    assert _pointer(owner_conn, x) is None


# --- resting goes back; batches ---------------------------------------------------


def _resting_call(owner_conn, rep, x, at=None):
    """A Left voicemail by `rep` on X, which `rep` holds; with voicemails 1 it rests."""
    at = at or _now()
    _sql(owner_conn, "update contacts set dnc_checked_at = %s where id = %s",
         (at - timedelta(hours=1), x))
    call = calls.open_call(rep, x, at, confirm_outside_hours=True).call_id
    calls.record_outcome(rep, x, "left_voicemail", at + timedelta(minutes=1), call_id=call)


def test_a_resting_contact_goes_back_with_its_state(reps, owner_conn):
    a, c = reps(), reps()
    rule.save_settings(a, 1, 5, 3, 3, _now())
    rule.save_settings(c, 1, 5, 3, 3, _now())
    x = _contact(owner_conn)
    assert _add(owner_conn, a, x) == "claimed"
    _resting_call(owner_conn, a, x)
    _backdate_assigned(owner_conn, x, 91)
    assert run_expiry_step() == 1
    _sql(owner_conn, "update contacts set dnc_checked_at = now() where id = %s", (x,))
    assert _add(owner_conn, c, x) == "claimed"
    st = rule.contact_state(c, x, _now())
    assert (st.list, st.reason) == ("limit_reached", "resting")


def test_batches_skip_closed_and_resting(reps, owner_conn):
    a, p = reps(), reps()
    rule.save_settings(a, 1, 5, 3, 3, _now())
    rule.save_settings(p, 1, 5, 3, 3, _now())
    made = {k: _contact(owner_conn) for k in (
        "wrong", "notint", "closed", "customer", "resting", "over", "blocked")}
    for x in made.values():
        assert _add(owner_conn, a, x) == "claimed"
    calls.record_outcome(a, made["wrong"], "wrong_number", _now())
    calls.record_outcome(a, made["notint"], "not_interested", _now())
    rule.move(a, made["closed"], "closed", _now())
    _sign(a, made["customer"])
    _resting_call(owner_conn, a, made["resting"])
    _resting_call(owner_conn, a, made["over"], _now() - timedelta(days=120))
    calls.record_outcome(a, made["blocked"], "follow_up", _now())
    dnc.report_do_not_call(a, made["blocked"], "asked", _now())
    reclaim(a, "back", "young")
    for x in made.values():
        _sql(owner_conn, "update contacts set dnc_checked_at = now() where id = %s", (x,))
    report = _batch(p, *made.values())
    by = {c: cause for cause, ids in report.shortfall.items() for c in ids}
    assert by[made["wrong"]] == "closed"
    assert by[made["notint"]] == "closed"
    assert by[made["closed"]] == "closed"
    assert by[made["customer"]] == "won"
    assert by[made["resting"]] == "resting"
    assert by[made["blocked"]] == "voice_suppressed"
    assert made["over"] in report.assigned


def test_batches_read_the_partner_s_settings(reps, owner_conn):
    a, p, q = reps(), reps(), reps()
    rule.save_settings(a, 1, 5, 3, 3, _now())
    rule.save_settings(p, 1, 5, 3, 1, _now())
    rule.save_settings(q, 1, 5, 3, 3, _now())
    x, y = _contact(owner_conn), _contact(owner_conn)
    for c in (x, y):
        assert _add(owner_conn, a, c) == "claimed"
        _resting_call(owner_conn, a, c, _now() - timedelta(days=40))
    reclaim(a, "back", "young")
    for c in (x, y):
        _sql(owner_conn, "update contacts set dnc_checked_at = now() where id = %s", (c,))
    assert _batch(p, x).assigned == [x]
    assert _batch(q, y).shortfall == {"resting": [y]}


def test_get_more_numbers_reads_its_own_moment(reps, owner_conn):
    a, p = reps(), reps()
    rule.save_settings(a, 1, 5, 3, 3, _now())
    rule.save_settings(p, 1, 5, 3, 3, _now())
    x = _contact(owner_conn)
    assert _add(owner_conn, a, x) == "claimed"
    _resting_call(owner_conn, a, x)
    reclaim(a, "back", "young")
    _sql(owner_conn, "update contacts set dnc_checked_at = now() where id = %s", (x,))
    later = _now() + timedelta(days=95)
    report = get_more_numbers(p, LA, f"k-{uuid4().hex[:8]}", later)
    assert x in report.assigned


# --- ask again --------------------------------------------------------------------


def test_sold_callbacks_and_follow_ups_do_not_count(reps, owner_conn):
    r = reps()
    plain = [_contact(owner_conn) for _ in range(50)]
    sold, back, follow = _contact(owner_conn), _contact(owner_conn), _contact(owner_conn)
    _batch(r, *plain, sold, back, follow)
    _sign(r, sold)
    rule.move(r, back, "got_callback", _now())
    calls.record_outcome(r, follow, "follow_up", _now())
    report = get_more_numbers(r, LA, f"k-{uuid4().hex[:8]}", _now())
    assert report.batch_id is not None


# --- a wrong number ---------------------------------------------------------------


def test_the_right_number_is_added_through_door_b(reps, owner_conn):
    r = reps()
    x = _contact(owner_conn)
    assert _add(owner_conn, r, x) == "claimed"
    calls.record_outcome(r, x, "wrong_number", _now())
    results = rep_intake.add_numbers(r, [RepRow(phone="+18185559876")], "referral",
                                     CONFIRMATION, _now())
    assert results[0].result == "added"
