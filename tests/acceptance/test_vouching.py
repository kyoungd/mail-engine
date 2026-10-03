"""Part 7 gate: vouching, and callable-only lists (docs/contact-engine/07-vouching.md §4,
§7).

A rep vouches for a contact they hold — met in person, or they contacted me. A vouch
that counts lets a call open past a DNC status that is not clear, never past a "don't
call me again", no phone, or a seed; everything else about the call is unchanged, and
the call records the vouch. A vouch counts only for its rep, while they hold the
contact, since they last got it, until withdrawn. The scrub leaves a vouched contact
with its rep. The lists hold only what the rep may call; search holds everything.
"""

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from itertools import count
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import jobs.dnc_refresh as scrub
import service.calls as calls
import service.reads as reads
import web.api as web_api
from config.params import HOUSE_PARTNER_ID
from domain.errors import ValidationError
from domain.types import RepRow
from seams.fakes import FakeDncRegistry
from service import dnc, rep_intake, rule, vouch
from service.assignment import assign_batch, reclaim, run_expiry_step
from service.custody import set_owner
from tests.factories import new_contact

AT = datetime(2026, 1, 15, 20, 0, tzinfo=UTC)  # noon in Los Angeles
EVENING = datetime(2026, 1, 16, 4, 0, tzinfo=UTC)  # 8 PM in Los Angeles
BEFORE = AT - timedelta(hours=1)
LA_ZONE = "America/Los_Angeles"
MET = "I met someone from this business in person, and they agreed to hear from me."
DK, WK = "dialer-key-for-tests", "website-key-for-tests"
CONFIRMATION = "These are businesses I found through my own prospecting."
NO_CONTACT = {"code": "no_contact", "message": "no such contact", "detail": {}}
PASSABLE = ("not_checked", "not_covered", "on_dnc_file", "check_too_old")
CUSTODY = ("contact.assigned", "contact.assignment_expired", "contact.reclaimed")
LIST_FIELDS = {"id", "business", "contact_name", "phone", "list", "reason", "due",
               "rest_until", "pause_until", "whose", "vouched"}
SEARCH_FIELDS = {"id", "phone", "business", "contact_name", "dnc_status", "vouched"}


# --- fixtures and helpers ---------------------------------------------------------


@dataclass(frozen=True)
class Rep:
    id: UUID
    sid: int


_sids = count(int(time.time()) % 1_000_000 * 1000 + 500)
_n = count(1)


def _sql(owner_conn, query: str, params=()):
    with owner_conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall() if cur.description else []
    owner_conn.commit()
    return rows


def _forget_partners(owner_conn) -> None:
    owner_conn.rollback()
    with owner_conn.cursor() as cur:
        cur.execute(
            "select id from partners where id <> %s and name <> 'John'", (HOUSE_PARTNER_ID,)
        )
        made = [r[0] for r in cur.fetchall()]
        cur.execute("truncate api_requests")
        cur.execute("delete from rep_settings where rep_id = any(%s)", (made,))
        cur.execute("delete from memos where rep_id = any(%s)", (made,))
        cur.execute("delete from calls_received where rep_id = any(%s)", (made,))
        cur.execute("delete from calls where rep_id = any(%s)", (made,))
        cur.execute("delete from vouch_withdrawals")
        cur.execute("delete from vouches")
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


@pytest.fixture()
def reps(clean_db, owner_conn):
    _forget_partners(owner_conn)

    def make(status: str = "active") -> Rep:
        sid = next(_sids)
        rows = _sql(owner_conn,
                    "insert into partners (name, status, sales_rep_id) values (%s, %s, %s) "
                    "returning id", (f"Rep-{uuid4().hex[:8]}", status, sid))
        return Rep(id=rows[0][0], sid=sid)

    yield make
    _forget_partners(owner_conn)


def _subscribe(owner_conn, code: str = "818") -> None:
    _sql(owner_conn, "insert into dnc_subscriptions (area_code, subscribed_at) "
                     "values (%s, now()) on conflict do nothing", (code,))


def _hold(owner_conn, contact: UUID, rep: Rep) -> None:
    with owner_conn.cursor() as cur:
        set_owner(cur, contact, rep.id, event_type="contact.assigned", reason="test",
                  actor="t")
    owner_conn.commit()


def _phone() -> str:
    return f"+1818555{next(_n):04d}"


def _contact(owner_conn, rep: Rep | None = None, phone: str | None = None,
             **fields) -> UUID:
    """A contact on a subscribed code, checked a day before AT, in CA — clear unless
    `fields` say otherwise — held by `rep` through `set_owner`, or by the house."""
    phone = phone or _phone()
    _subscribe(owner_conn, phone[2:5])
    fields.setdefault("dnc_checked_at", AT - timedelta(days=1))
    fields.setdefault("addr_state", "CA")
    fields.setdefault("business_name", f"Business {next(_n)}")
    with owner_conn.cursor() as cur:
        contact = new_contact(cur, phone_e164=phone, intake=False, **fields)
    owner_conn.commit()
    if rep is not None:
        _hold(owner_conn, contact, rep)
    return contact


def _not_covered(owner_conn, rep: Rep) -> UUID:
    with owner_conn.cursor() as cur:
        contact = new_contact(cur, phone_e164=f"+1213555{next(_n):04d}", intake=False,
                              addr_state="CA", created_at=AT - timedelta(days=3))
    owner_conn.commit()
    _hold(owner_conn, contact, rep)
    _sql(owner_conn, "insert into dnc_runs (started_at, limited) values (%s, false)",
         (AT - timedelta(days=1),))
    return contact


def _with_status(owner_conn, rep: Rep, status: str) -> UUID:
    if status == "not_covered":
        return _not_covered(owner_conn, rep)
    fields = {
        "not_checked": {"dnc_checked_at": None},
        "on_dnc_file": {"dnc_registry": True},
        "check_too_old": {"dnc_checked_at": AT - timedelta(days=40)},
    }[status]
    return _contact(owner_conn, rep, **fields)


def _refused(code: str, call, **detail) -> ValidationError:
    with pytest.raises(ValidationError) as err:
        call()
    assert err.value.code == code, (err.value.code, str(err.value))
    for key, value in detail.items():
        assert err.value.detail.get(key) == value, err.value.detail
    return err.value


def _mark(owner_conn, contact: UUID) -> int:
    return _sql(owner_conn, "select max(id) from events where contact_id = %s "
                            "and type = any(%s)", (contact, list(CUSTODY)))[0][0]


def _vouches(owner_conn, contact: UUID) -> list[tuple]:
    return _sql(owner_conn,
                "select id, rep_id, phone_e164, reason, confirmation, source, "
                "custody_mark, at from vouches where contact_id = %s order by seq",
                (contact,))


def _call_row(owner_conn, call_id: UUID) -> tuple:
    return _sql(owner_conn, "select vouch_id, vouched_status, dnc_checked_at from calls "
                            "where id = %s", (call_id,))[0]


def _status(contact: UUID) -> str:
    return dnc.dnc_status(contact, AT)


def _listed(rep: Rep, at: datetime = AT) -> dict[UUID, dict]:
    return {c["id"]: c for c in reads.lists(rep.id, at)["contacts"]}


# --- a vouch ----------------------------------------------------------------------


@pytest.mark.parametrize("reason", ["met_in_person", "they_contacted_me"])
def test_a_vouch_is_recorded(reps, owner_conn, reason):
    r = reps()
    phone = _phone()
    x = _contact(owner_conn, r, phone=phone, dnc_registry=True)
    assert vouch.vouch(r.id, x, reason, f"  {MET}  ", BEFORE) == "vouched"
    [(_, rep_id, stored_phone, stored_reason, confirmation, source, mark, at)] = (
        _vouches(owner_conn, x))
    assert (rep_id, stored_phone, stored_reason, confirmation, source, at) == (
        r.id, phone, reason, MET, "rep", BEFORE)
    assert mark == _mark(owner_conn, x)

    assert vouch.vouch(r.id, x, reason, MET, AT) == "vouched"
    assert len(_vouches(owner_conn, x)) == 2


def test_a_clear_contact_can_be_vouched(reps, owner_conn):
    r = reps()
    x = _contact(owner_conn, r)
    assert _status(x) == "clear"
    assert vouch.vouch(r.id, x, "met_in_person", MET, BEFORE) == "vouched"


def test_vouch_refusals_write_nothing(reps, owner_conn):
    r, other = reps(), reps()
    x = _contact(owner_conn, r, dnc_registry=True)
    theirs = _contact(owner_conn, other, dnc_registry=True)
    house = _contact(owner_conn, None, dnc_registry=True)
    _refused("bad_time", lambda: vouch.vouch(r.id, x, "met_in_person", MET,
                                             datetime(2026, 1, 15, 12)))
    _refused("bad_rep", lambda: vouch.vouch(HOUSE_PARTNER_ID, x, "met_in_person", MET, AT))
    _refused("bad_rep", lambda: vouch.vouch(uuid4(), x, "met_in_person", MET, AT))
    _refused("no_contact", lambda: vouch.vouch(r.id, uuid4(), "met_in_person", MET, AT))
    _refused("not_yours", lambda: vouch.vouch(r.id, theirs, "met_in_person", MET, AT))
    _refused("not_yours", lambda: vouch.vouch(r.id, house, "met_in_person", MET, AT))
    for reason in ("referral", "public_or_research", None, ""):
        _refused("bad_reason", lambda reason=reason: vouch.vouch(r.id, x, reason, MET, AT))
    for blank in (None, "", "   "):
        _refused("no_confirmation",
                 lambda blank=blank: vouch.vouch(r.id, x, "met_in_person", blank, AT))
    assert _sql(owner_conn, "select count(*) from vouches")[0][0] == 0


def test_blocked_no_phone_and_seed_are_not_vouchable(reps, owner_conn):
    r = reps()
    blocked = _contact(owner_conn, r)
    dnc.report_do_not_call(r.id, blocked, "asked", BEFORE)
    no_phone = _contact(owner_conn, r)
    _sql(owner_conn, "update contacts set phone_e164 = null where id = %s", (no_phone,))
    seed = _contact(owner_conn, r, is_seed=True, seed_key=f"seed-{uuid4().hex[:6]}")
    for contact, status in ((blocked, "do_not_call"), (no_phone, "no_phone"),
                            (seed, "seed")):
        _refused("not_vouchable",
                 lambda c=contact: vouch.vouch(r.id, c, "met_in_person", MET, AT),
                 status=status)
    assert _sql(owner_conn, "select count(*) from vouches")[0][0] == 0


# --- what a vouch passes ----------------------------------------------------------


@pytest.mark.parametrize("status", PASSABLE)
def test_a_vouched_contact_with_a_passable_status_is_callable(reps, owner_conn, status):
    r = reps()
    x = _with_status(owner_conn, r, status)
    assert _status(x) == status
    _refused("not_callable", lambda: calls.open_call(r.id, x, AT), status=status)

    vouch.vouch(r.id, x, "they_contacted_me", MET, BEFORE)
    [(vouch_id, *_)] = _vouches(owner_conn, x)
    assert rule.may_call(r.id, x, AT)
    card = reads.card(r.id, x, AT)
    assert card["may_call"] == {"yes": True}
    assert card["dnc_status"] == status
    assert card["vouched"] == {"reason": "they_contacted_me", "at": BEFORE}

    opened = calls.open_call(r.id, x, AT)
    checked_at = _sql(owner_conn, "select dnc_checked_at from contacts where id = %s",
                      (x,))[0][0]
    assert _call_row(owner_conn, opened.call_id) == (vouch_id, status, checked_at)
    if status == "not_checked":
        assert checked_at is None


def test_a_clear_call_records_no_vouch(reps, owner_conn):
    r = reps()
    x = _contact(owner_conn, r)
    vouch.vouch(r.id, x, "met_in_person", MET, BEFORE)
    opened = calls.open_call(r.id, x, AT)
    assert _call_row(owner_conn, opened.call_id)[:2] == (None, None)


def test_a_vouch_never_passes_a_do_not_call(reps, owner_conn):
    r = reps()
    x = _contact(owner_conn, r, dnc_registry=True)
    vouch.vouch(r.id, x, "met_in_person", MET, BEFORE)
    dnc.report_do_not_call(r.id, x, "asked", BEFORE)
    _refused("not_callable", lambda: calls.open_call(r.id, x, AT), status="do_not_call")
    assert reads.card(r.id, x, AT)["may_call"]["code"] == "not_callable"


def test_a_vouch_never_passes_a_seed_or_no_phone(reps, owner_conn):
    """Neither can be vouched through the verb (above); a row put there by hand still
    passes nothing."""
    r = reps()
    seed = _contact(owner_conn, r, is_seed=True, seed_key=f"seed-{uuid4().hex[:6]}")
    _sql(owner_conn,
         "insert into vouches (contact_id, rep_id, phone_e164, reason, confirmation, "
         "source, custody_mark, at) select id, %s, phone_e164, 'met_in_person', %s, 'rep', "
         "%s, %s from contacts where id = %s",
         (r.id, MET, _mark(owner_conn, seed), BEFORE, seed))
    _refused("not_callable", lambda: calls.open_call(r.id, seed, AT), status="seed")

    no_phone = _contact(owner_conn, r, dnc_registry=True)
    vouch.vouch(r.id, no_phone, "met_in_person", MET, BEFORE)
    _sql(owner_conn, "update contacts set phone_e164 = null where id = %s", (no_phone,))
    _refused("not_callable", lambda: calls.open_call(r.id, no_phone, AT), status="no_phone")


def test_everything_else_about_a_call_stands(reps, owner_conn):
    r = reps()

    def vouched(**fields) -> UUID:
        x = _contact(owner_conn, r, dnc_registry=True, **fields)
        vouch.vouch(r.id, x, "met_in_person", MET, AT - timedelta(days=20))
        return x

    late = vouched()
    _refused("outside_hours", lambda: calls.open_call(r.id, late, EVENING))
    assert calls.open_call(r.id, late, EVENING, confirm_outside_hours=True).call_id

    again = vouched()
    first = calls.open_call(r.id, again, BEFORE)
    calls.record_outcome(r.id, again, "no_answer", BEFORE + timedelta(minutes=2),
                         call_id=first.call_id)
    _refused("not_due", lambda: calls.open_call(r.id, again, AT))

    paused = vouched()
    rule.pause(r.id, paused, date(2026, 2, 1), BEFORE)
    _refused("paused", lambda: calls.open_call(r.id, paused, AT))

    closed = vouched()
    rule.move(r.id, closed, "closed", BEFORE)
    _refused("closed", lambda: calls.open_call(r.id, closed, AT))

    ended = vouched()
    for days in (10, 6):
        made = calls.open_call(r.id, ended, AT - timedelta(days=days))
        calls.record_outcome(r.id, ended, "left_voicemail",
                             AT - timedelta(days=days) + timedelta(minutes=2),
                             call_id=made.call_id)
    _refused("limit_reached", lambda: calls.open_call(r.id, ended, AT))

    _subscribe(owner_conn, "800")
    nowhere = _contact(owner_conn, r, phone=f"+1800555{next(_n):04d}", addr_state=None,
                       dnc_registry=True)
    vouch.vouch(r.id, nowhere, "met_in_person", MET, BEFORE)
    _refused("no_zone", lambda: calls.open_call(r.id, nowhere, AT))


# --- whose vouch counts -----------------------------------------------------------


def test_a_vouch_does_not_follow_the_contact_to_another_rep(reps, owner_conn):
    a, b = reps(), reps()
    x = _contact(owner_conn, dnc_checked_at=datetime.now(UTC) - timedelta(hours=1))
    assign_batch(a.id, f"k-{uuid4().hex[:10]}", "young", contact_ids=[x])
    _sql(owner_conn, "update contacts set dnc_registry = true, dnc_checked_at = %s "
                     "where id = %s", (AT - timedelta(days=1), x))
    vouch.vouch(a.id, x, "met_in_person", MET, BEFORE)
    _sql(owner_conn, "update assignment_batches set expires_at = now() - interval '1 day' "
                     "where partner_id = %s", (a.id,))
    run_expiry_step()
    [result] = rep_intake.add_numbers(b.id, [RepRow(phone=_sql(
        owner_conn, "select phone_e164 from contacts where id = %s", (x,))[0][0])],
        "referral", CONFIRMATION, BEFORE)
    assert result.result == "claimed"
    _refused("not_callable", lambda: calls.open_call(b.id, x, AT), status="on_dnc_file")
    assert reads.card(b.id, x, AT)["vouched"] is None
    vouch.vouch(b.id, x, "they_contacted_me", MET, BEFORE)
    assert calls.open_call(b.id, x, AT).call_id


def test_a_vouch_does_not_come_back_with_the_contact(reps, owner_conn):
    a = reps()
    x = _contact(owner_conn, a, dnc_registry=True)
    vouch.vouch(a.id, x, "met_in_person", MET, BEFORE)
    reclaim(a.id, "back", "young")
    phone = _sql(owner_conn, "select phone_e164 from contacts where id = %s", (x,))[0][0]
    [result] = rep_intake.add_numbers(a.id, [RepRow(phone=phone)], "referral",
                                      CONFIRMATION, BEFORE)
    assert result.result == "claimed"
    _refused("not_callable", lambda: calls.open_call(a.id, x, AT), status="on_dnc_file")
    vouch.vouch(a.id, x, "met_in_person", MET, BEFORE)
    assert calls.open_call(a.id, x, AT).call_id


def test_a_sale_moving_the_contact_to_its_holder_keeps_the_vouch(reps, owner_conn):
    a = reps()
    x = _contact(owner_conn, dnc_checked_at=datetime.now(UTC) - timedelta(hours=1))
    assign_batch(a.id, f"k-{uuid4().hex[:10]}", "young", contact_ids=[x])
    vouch.vouch(a.id, x, "met_in_person", MET, BEFORE)
    before = _mark(owner_conn, x)
    calls.record_outcome(a.id, x, "signed_up", BEFORE + timedelta(minutes=1))
    moved = _sql(owner_conn, "select payload->>'previous_owner_id', "
                             "payload->>'new_owner_id' from events where contact_id = %s "
                             "and type = 'contact.assigned' and id > %s", (x, before))
    assert moved == [(str(a.id), str(a.id))]
    _sql(owner_conn, "update contacts set dnc_checked_at = null where id = %s", (x,))
    assert reads.card(a.id, x, AT)["vouched"] == {"reason": "met_in_person", "at": BEFORE}


def test_a_vouch_on_an_old_phone_does_not_count(reps, owner_conn):
    a = reps()
    x = _contact(owner_conn, a, dnc_registry=True)
    vouch.vouch(a.id, x, "met_in_person", MET, BEFORE)
    _sql(owner_conn, "update contacts set phone_e164 = %s where id = %s", (_phone(), x))
    _refused("not_callable", lambda: calls.open_call(a.id, x, AT), status="on_dnc_file")
    assert reads.card(a.id, x, AT)["vouched"] is None


def test_the_counting_vouch_is_the_latest_by_seq(reps, owner_conn):
    a = reps()
    x = _contact(owner_conn, a, dnc_registry=True)
    vouch.vouch(a.id, x, "met_in_person", MET, BEFORE)
    vouch.vouch(a.id, x, "they_contacted_me", MET, BEFORE)
    later = _vouches(owner_conn, x)[1][0]
    assert reads.card(a.id, x, AT)["vouched"] == {"reason": "they_contacted_me",
                                                  "at": BEFORE}
    opened = calls.open_call(a.id, x, AT)
    assert _call_row(owner_conn, opened.call_id)[0] == later


# --- withdrawing ------------------------------------------------------------------


def test_a_withdrawal(reps, owner_conn):
    r, other = reps(), reps()
    x = _contact(owner_conn, r, dnc_registry=True)
    vouch.vouch(r.id, x, "met_in_person", MET, BEFORE - timedelta(minutes=5))
    vouch.vouch(r.id, x, "they_contacted_me", MET, BEFORE)
    assert x in _listed(r)

    _refused("no_reason", lambda: vouch.withdraw(r.id, x, "  ", AT))
    theirs = _contact(owner_conn, other, dnc_registry=True)
    _refused("not_yours", lambda: vouch.withdraw(r.id, theirs, "mistake", AT))
    assert vouch.withdraw(r.id, x, "  wrong business  ", BEFORE) == "withdrawn"
    rows = _sql(owner_conn, "select w.reason, w.at from vouch_withdrawals w "
                            "join vouches v on v.id = w.vouch_id where v.contact_id = %s",
                (x,))
    assert rows == [("wrong business", BEFORE)] * 2

    _refused("not_callable", lambda: calls.open_call(r.id, x, AT), status="on_dnc_file")
    assert x not in _listed(r)
    assert reads.card(r.id, x, AT)["vouched"] is None
    _refused("not_vouched", lambda: vouch.withdraw(r.id, x, "again", AT))

    vouch.vouch(r.id, x, "met_in_person", MET, BEFORE)
    assert calls.open_call(r.id, x, AT).call_id


def test_a_withdrawal_leaves_an_open_call_to_its_outcome(reps, owner_conn):
    r = reps()
    x = _contact(owner_conn, r, dnc_registry=True)
    vouch.vouch(r.id, x, "met_in_person", MET, BEFORE)
    opened = calls.open_call(r.id, x, AT)
    vouch.withdraw(r.id, x, "mistake", AT + timedelta(minutes=1))
    calls.record_outcome(r.id, x, "no_answer", AT + timedelta(minutes=2),
                         call_id=opened.call_id)
    assert _sql(owner_conn, "select outcome from calls where id = %s",
                (opened.call_id,))[0][0] == "no_answer"


# --- door B -----------------------------------------------------------------------


def test_adding_a_number_with_either_reason_vouches_for_it(reps, owner_conn):
    r, other = reps(), reps()
    mine = _phone()
    rep_intake.add_numbers(r.id, [RepRow(phone=mine)], "referral", CONFIRMATION, BEFORE)
    house = _phone()
    _contact(owner_conn, None, phone=house, dnc_registry=True)
    new_met, new_contacted, new_referral, new_public = (_phone() for _ in range(4))
    held = _phone()
    _contact(owner_conn, other, phone=held)
    blocked = _phone()
    _contact(owner_conn, None, phone=blocked, do_not_call=True)

    results = rep_intake.add_numbers(r.id, [
        RepRow(phone=new_met),
        RepRow(phone=new_contacted, how_obtained="they_contacted_me"),
        RepRow(phone=new_referral, how_obtained="referral"),
        RepRow(phone=new_public, how_obtained="public_or_research"),
        RepRow(phone=house, how_obtained="they_contacted_me"),
        RepRow(phone=mine),
        RepRow(phone=held),
        RepRow(phone=blocked),
        RepRow(phone="123"),
    ], "met_in_person", f"  {CONFIRMATION}  ", AT)
    by_phone = {row.phone: row for row in results}
    assert {p: by_phone[p].result for p in (new_met, house, mine, held, blocked)} == {
        new_met: "added", house: "claimed", mine: "already_yours", held: "held",
        blocked: "do_not_call"}

    rows = _sql(owner_conn, "select phone_e164, rep_id, reason, confirmation, source, at, "
                            "custody_mark, contact_id from vouches order by phone_e164")
    assert {(p, reason) for p, _, reason, *_ in rows} == {
        (new_met, "met_in_person"), (new_contacted, "they_contacted_me"),
        (house, "they_contacted_me"), (mine, "met_in_person")}
    for _, rep_id, _, confirmation, source, at, mark, contact in rows:
        assert (rep_id, confirmation, source, at) == (r.id, CONFIRMATION, "intake", AT)
        assert mark == _mark(owner_conn, contact)

    claimed = by_phone[house].contact_id
    assert claimed is not None
    assert calls.open_call(r.id, claimed, AT).call_id


# --- the scrub (answer 1) ---------------------------------------------------------


def test_the_scrub_leaves_a_vouched_contact_with_its_rep(reps, owner_conn):
    r = reps()
    now = datetime.now(UTC)
    due = now - timedelta(days=25)
    kept, taken, withdrawn = (_phone() for _ in range(3))
    x = _contact(owner_conn, r, phone=kept, dnc_checked_at=due)
    y = _contact(owner_conn, r, phone=taken, dnc_checked_at=due)
    z = _contact(owner_conn, r, phone=withdrawn, dnc_checked_at=due)
    vouch.vouch(r.id, x, "met_in_person", MET, now)
    vouch.vouch(r.id, z, "met_in_person", MET, now)
    vouch.withdraw(r.id, z, "mistake", now)

    scrub.dnc_refresh(FakeDncRegistry(version="v1", numbers={
        "818": {p[2:] for p in (kept, taken, withdrawn)}}))

    owners = dict(_sql(owner_conn, "select id, owner_id from contacts where id = any(%s)",
                       ([x, y, z],)))
    assert owners == {x: r.id, y: HOUSE_PARTNER_ID, z: HOUSE_PARTNER_ID}
    assert _sql(owner_conn, "select dnc_registry from contacts where id = %s", (x,)) == [
        (True,)]
    assert _sql(owner_conn, "select count(*) from events where contact_id = %s "
                            "and type = 'contact.dnc_checked'", (x,))[0][0] == 1
    assert _sql(owner_conn, "select count(*) from events where contact_id = %s "
                            "and type = 'contact.reclaimed'", (x,))[0][0] == 0


# --- the lists, the card, search --------------------------------------------------


def test_the_lists_hold_only_what_the_rep_may_call(reps, owner_conn):
    r = reps()
    clear = _contact(owner_conn, r, business_name="Clear Plumbing")
    listed = _contact(owner_conn, r, business_name="Listed Plumbing", dnc_registry=True)
    blocked = _contact(owner_conn, r, business_name="Blocked Plumbing")
    dnc.report_do_not_call(r.id, blocked, "asked", BEFORE)
    own = rep_intake.add_numbers(r.id, [RepRow(phone=_phone(), business_name="Own Plumbing")],
                                 "referral", CONFIRMATION, BEFORE)[0].contact_id
    assert own is not None and _status(own) == "not_checked"

    lists = _listed(r)
    assert set(lists) == {clear}
    assert lists[clear]["whose"] == "nmc" and lists[clear]["vouched"] is False
    assert all(set(entry) == LIST_FIELDS for entry in lists.values())

    vouch.vouch(r.id, listed, "met_in_person", MET, BEFORE)
    vouch.vouch(r.id, own, "they_contacted_me", MET, BEFORE)
    lists = _listed(r)
    assert set(lists) == {clear, listed, own}
    assert (lists[listed]["vouched"], lists[listed]["whose"]) == (True, "nmc")
    assert (lists[own]["vouched"], lists[own]["whose"]) == (True, "own")
    assert lists[listed]["list"] == "never_called"

    found = {c["id"]: c for c in reads.search(r.id, "plumbing", AT)["contacts"]}
    assert set(found) == {clear, listed, blocked, own}
    assert all(set(c) == SEARCH_FIELDS for c in found.values())
    assert {cid: (c["dnc_status"], c["vouched"]) for cid, c in found.items()} == {
        clear: ("clear", False), listed: ("on_dnc_file", True),
        blocked: ("do_not_call", False), own: ("not_checked", True)}


# --- the API ----------------------------------------------------------------------


def _inside_at() -> datetime:
    t = (datetime.now(UTC) + timedelta(hours=1)).astimezone(ZoneInfo(LA_ZONE))
    noon = t.replace(hour=12, minute=0, second=0, microsecond=0)
    if noon < t:
        noon += timedelta(days=1)
    return noon.astimezone(UTC)


@pytest.fixture()
def api(monkeypatch, reps):
    monkeypatch.setenv("CE_DIALER_KEY", DK)
    monkeypatch.setenv("CE_WEBSITE_KEY", WK)
    return TestClient(web_api.create_app(), raise_server_exceptions=False)


def _headers(rep: Rep, idem: str | None = None, key: str = DK) -> dict[str, str]:
    h = {"X-API-Key": key, "X-Rep": str(rep.sid)}
    if idem is not None:
        h["Idempotency-Key"] = idem
    return h


def _post(api, path: str, body, rep: Rep, idem: str | None = None, key: str = DK):
    return api.post("/v1" + path, json=body, headers=_headers(rep, idem or uuid4().hex, key))


def _get(api, path: str, rep: Rep, params=None):
    return api.get("/v1" + path, headers=_headers(rep), params=params)


def _api_refused(response, status: int, code: str) -> dict:
    assert response.status_code == status, (response.status_code, response.text)
    body = response.json()
    assert body["code"] == code, body
    return body


def test_the_routes(api, reps, owner_conn, monkeypatch):
    at = _inside_at()
    monkeypatch.setattr(web_api, "_now", lambda: at)
    r, other = reps(), reps()
    checked = at - timedelta(hours=1)
    x = _contact(owner_conn, r, dnc_registry=True, dnc_checked_at=checked)
    theirs = _contact(owner_conn, other, dnc_registry=True, dnc_checked_at=checked)
    blocked = _contact(owner_conn, r, dnc_checked_at=checked)
    dnc.report_do_not_call(r.id, blocked, "asked", at - timedelta(minutes=5))

    _api_refused(_post(api, f"/contacts/{x}/vouch", {}, r), 409, "bad_reason")
    _api_refused(_post(api, f"/contacts/{x}/vouch", {"reason": "referral",
                                                      "confirmation": MET}, r),
                 409, "bad_reason")
    _api_refused(_post(api, f"/contacts/{x}/vouch", {"reason": "met_in_person"}, r),
                 409, "no_confirmation")
    refused = _api_refused(_post(api, f"/contacts/{blocked}/vouch",
                                 {"reason": "met_in_person", "confirmation": MET}, r),
                           409, "not_vouchable")
    assert refused["detail"] == {"status": "do_not_call"}
    for contact in (theirs, uuid4()):
        response = _post(api, f"/contacts/{contact}/vouch",
                         {"reason": "met_in_person", "confirmation": MET}, r)
        assert (response.status_code, response.json()) == (404, NO_CONTACT)

    card = _get(api, f"/contacts/{x}", r).json()
    assert (card["vouched"], card["may_call"]["code"]) == (None, "not_callable")

    key = uuid4().hex
    body = {"reason": "met_in_person", "confirmation": MET}
    first = _post(api, f"/contacts/{x}/vouch", body, r, idem=key, key=WK)
    assert (first.status_code, first.json()) == (200, {"result": "vouched"})
    replay = _post(api, f"/contacts/{x}/vouch", body, r, idem=key, key=WK)
    assert replay.headers.get("Idempotent-Replay") == "true"
    assert len(_vouches(owner_conn, x)) == 1

    card = _get(api, f"/contacts/{x}", r).json()
    assert card["vouched"]["reason"] == "met_in_person"
    assert datetime.fromisoformat(card["vouched"]["at"]) == at
    assert card["dnc_status"] == "on_dnc_file"
    assert card["may_call"] == {"yes": True}
    assert _get(api, f"/contacts/{x}/may-call", r).json() == {"yes": True}

    [entry] = _get(api, "/me/lists", r).json()["contacts"]
    assert entry["id"] == str(x) and set(entry) == LIST_FIELDS
    assert (entry["whose"], entry["vouched"]) == ("nmc", True)
    found = _get(api, "/me/search", r, {"q": "business"}).json()["contacts"]
    assert {c["id"] for c in found} == {str(x), str(blocked)}
    assert all(set(c) == SEARCH_FIELDS for c in found)

    _api_refused(_post(api, f"/contacts/{x}/vouch/withdraw", {}, r), 409, "no_reason")
    response = _post(api, f"/contacts/{theirs}/vouch/withdraw", {"reason": "x"}, r)
    assert (response.status_code, response.json()) == (404, NO_CONTACT)
    done = _post(api, f"/contacts/{x}/vouch/withdraw", {"reason": "mistake"}, r)
    assert (done.status_code, done.json()) == (200, {"result": "withdrawn"})
    assert _get(api, "/me/lists", r).json()["contacts"] == []
    assert _get(api, f"/contacts/{x}", r).json()["vouched"] is None
