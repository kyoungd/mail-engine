"""Part 4 gate: assignment — holding and getting numbers
(docs/contact-engine/04-assignment.md §4, §7).

A rep gets more numbers by region, drawn at random through the same gate as every
batch, skipping contacts locked elsewhere; a rep's own is never in another rep's batch;
NMC's contact held without a batch goes back after 90 days from its latest assignment,
and the same rep cannot take it back for 90 days more.
"""

import csv
import hashlib
import json
import random
import re
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

import service.assignment as asg
from config.params import ASK_AGAIN_AT, HOUSE_PARTNER_ID, REGIONS, REP_BATCH_SIZE
from domain.errors import ValidationError
from domain.types import RepRow
from jobs import console
from service import rep_intake
from service.assignment import assign_batch, get_more_numbers, reclaim, run_expiry_step
from service.custody import set_owner
from service.ingestion import ingest_event
from tests.factories import new_contact

NPA_FILE = Path(__file__).resolve().parents[2] / "domain" / "data" / "npa_report.csv"
CONFIRMATION = "These are businesses I found through my own prospecting."
LA, SD, NORTH = "LA area", "San Diego", "Northern CA"


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


def _subscribe(owner_conn, *codes: str) -> None:
    for code in codes:
        _sql(owner_conn,
             "insert into dnc_subscriptions (area_code, subscribed_at) values (%s, now()) "
             "on conflict do nothing", (code,))


def _pool(owner_conn, phone: str, **fields) -> UUID:
    """NMC's contact the house holds, freshly checked."""
    fields.setdefault("dnc_checked_at", _now())
    with owner_conn.cursor() as cur:
        contact = new_contact(cur, phone_e164=phone, intake=False, **fields)
    owner_conn.commit()
    return contact


def _pools(owner_conn, code: str, n: int, start: int = 0) -> list[UUID]:
    ids = []
    with owner_conn.cursor() as cur:
        for i in range(start, start + n):
            ids.append(new_contact(cur, phone_e164=f"+1{code}555{i:04d}", intake=False,
                                   dnc_checked_at=_now()))
    owner_conn.commit()
    return ids


def _add(rep: UUID, phone: str, at: datetime | None = None) -> str:
    """Door B, one number; returns its result."""
    results = rep_intake.add_numbers(rep, [RepRow(phone=phone)], "referral", CONFIRMATION,
                                     at or _now())
    return results[0].result


def _contact_for(owner_conn, phone: str) -> UUID:
    return _sql(owner_conn, "select id from contacts where phone_e164 = %s", (phone,))[0][0]


def _owner(owner_conn, contact: UUID) -> UUID:
    return _sql(owner_conn, "select owner_id from contacts where id = %s", (contact,))[0][0]


def _backdate(owner_conn, contact: UUID, event_type: str, days: float) -> None:
    _sql(owner_conn,
         "update events set occurred_at = now() - make_interval(secs => %s) "
         "where contact_id = %s and type = %s",
         (days * 86400, contact, event_type))


def _expire_batches(owner_conn, partner: UUID) -> None:
    _sql(owner_conn,
         "update assignment_batches set expires_at = now() - interval '1 day' "
         "where partner_id = %s", (partner,))


def _batches(owner_conn) -> int:
    return _sql(owner_conn, "select count(*) from assignment_batches")[0][0]


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


# --- the settings -----------------------------------------------------------------


def test_the_settings():
    assert set(REGIONS) == {LA, SD, NORTH}
    assert set(REGIONS[LA]) == set(
        "213 323 738 310 424 818 747 626 562 661 714 657 949 909 840 951 805 820".split())
    assert set(REGIONS[SD]) == set("619 858 760 442".split())
    assert set(REGIONS[NORTH]) == set(
        "415 628 510 341 650 408 669 925 707 369 916 279 530 837 209 350 831".split())
    assert REP_BATCH_SIZE == 250
    assert ASK_AGAIN_AT == 50

    with open(NPA_FILE, newline="") as f:
        f.readline()
        rows = [r for r in csv.DictReader(f)
                if r["COUNTRY"] == "US" and r["USE"] == "G" and r["IN_SERVICE"] == "Y"]
    ca = {r["NPA_ID"] for r in rows if r["LOCATION"] == "CA"}
    codes = [c for region in REGIONS.values() for c in region]
    assert len(codes) == len(set(codes))
    assert set(codes) | {"559", "357"} == ca
    region_of = {c: name for name, region in REGIONS.items() for c in region}
    for r in rows:
        if r["NPA_ID"] in region_of:
            group = {r["NPA_ID"]} | {m for m in re.findall(r"\d{3}", r["OVERLAY_COMPLEX"])
                                     if m in region_of}
            assert len({region_of[m] for m in group}) == 1, group


# --- a rep's own ------------------------------------------------------------------


def test_a_rep_s_own_is_never_in_another_rep_s_batch(reps, owner_conn):
    _subscribe(owner_conn, "818")
    a, b = reps(), reps()
    assert _add(a, "+18185557001") == "added"
    own = _contact_for(owner_conn, "+18185557001")
    _sql(owner_conn, "update contacts set dnc_checked_at = now() where id = %s", (own,))
    reclaim(a, "back", "young")
    nmc = _pool(owner_conn, "+18185557002")

    report = assign_batch(b, "k-1", "young", contact_ids=[own, nmc])
    assert report.assigned == [nmc]
    assert report.shortfall == {"rep_own": [own]}
    reclaim(b, "back", "young")

    report = assign_batch(b, "k-2", "young", audience_rule={"area_code": ["818"]}, count=10)
    assert report.shortfall.get("rep_own") == [own]
    reclaim(b, "back", "young")

    report = get_more_numbers(b, LA, "k-3", _now())
    assert own not in report.assigned
    assert report.shortfall.get("rep_own") == [own]
    reclaim(b, "back", "young")

    assert assign_batch(a, "k-4", "young", contact_ids=[own]).shortfall == {"rep_own": [own]}
    assert assign_batch(HOUSE_PARTNER_ID, "k-5", "young", contact_ids=[own]).assigned == [own]


# --- the draw ---------------------------------------------------------------------


def test_the_draw_comes_from_the_region(reps, owner_conn):
    _subscribe(owner_conn, "818", "916")
    rep = reps()
    la = _pools(owner_conn, "818", 3)
    _pools(owner_conn, "916", 3)
    unsubscribed = _pool(owner_conn, "+16195550001")

    report = get_more_numbers(rep, SD, "k-sd", _now())
    assert report.assigned == []
    assert report.shortfall == {"dnc_unsubscribed": [unsubscribed]}

    report = get_more_numbers(rep, LA, "k-la", _now())
    assert set(report.assigned) == set(la)


def test_the_draw_is_random_and_in_proportion(reps, owner_conn, monkeypatch):
    _subscribe(owner_conn, "818", "714")
    rep = reps()
    big = _pools(owner_conn, "818", 300)
    small = _pools(owner_conn, "714", 100)
    monkeypatch.setattr(asg, "_rng", random.Random(7))
    report = assign_batch(rep, "k-rand", "young", audience_rule={"area_code": ["818", "714"]},
                          count=200, random_draw=True)
    drawn = set(report.assigned)
    assert len(drawn) == 200
    assert drawn != set(sorted(big + small, key=str)[:200])
    from_big = len(drawn & set(big))
    assert drawn & set(small)
    assert 130 <= from_big <= 170


def test_the_count(reps, owner_conn):
    _subscribe(owner_conn, "818")
    rep, other = reps(), reps()
    _pools(owner_conn, "818", 260)
    assert len(get_more_numbers(rep, LA, "k-many", _now()).assigned) == 250
    assert len(get_more_numbers(other, LA, "k-few", _now()).assigned) == 10


# --- ask again --------------------------------------------------------------------


def test_ask_again_counts_nmc_s_contacts_however_held(reps, owner_conn):
    _subscribe(owner_conn, "818")
    over, at_limit, with_own = reps(), reps(), reps()
    pool = _pools(owner_conn, "818", 149)
    _pool(owner_conn, "+18185559990")
    _pool(owner_conn, "+18185559991")
    assign_batch(over, "k-o", "young", contact_ids=pool[:50])
    assert _add(over, "+18185559990") == "claimed"
    assign_batch(at_limit, "k-a", "young", contact_ids=pool[50:99])
    assert _add(at_limit, "+18185559991") == "claimed"
    assign_batch(with_own, "k-w", "young", contact_ids=pool[99:149])
    assert _add(with_own, "+18185559992") == "added"

    batches = _batches(owner_conn)
    with pytest.raises(ValidationError) as err:
        get_more_numbers(over, LA, "k-o2", _now())
    assert err.value.code == "not_yet"
    assert _batches(owner_conn) == batches

    get_more_numbers(at_limit, LA, "k-a2", _now())
    get_more_numbers(with_own, LA, "k-w2", _now())
    assert _batches(owner_conn) == batches + 2


def _paused_first_ask(monkeypatch, owner_url, second) -> dict:
    """The first ask's `_after_lock` starts `second` in a thread and waits until it is
    blocked on a lock; the second's own hook call does nothing."""
    holder: dict = {}

    def hook(cur):
        if "worker" in holder:
            return
        holder["worker"], holder["out"] = _run(second)
        _wait_until_blocked(owner_url)

    monkeypatch.setattr(asg, "_after_lock", hook)
    return holder


def test_two_asks_at_once_are_one_after_the_other(reps, owner_conn, owner_url, monkeypatch):
    _subscribe(owner_conn, "818")
    rep = reps()
    _pools(owner_conn, "818", 60)
    holder = _paused_first_ask(monkeypatch, owner_url,
                               lambda: get_more_numbers(rep, LA, "k-second", _now()))
    first = get_more_numbers(rep, LA, "k-first", _now())
    holder["worker"].join(timeout=10)
    assert len(first.assigned) == 60
    error = holder["out"].get("error")
    assert isinstance(error, ValidationError) and error.code == "not_yet"


def test_the_same_key_at_once_returns_the_first_receipt(reps, owner_conn, owner_url,
                                                        monkeypatch):
    _subscribe(owner_conn, "818")
    rep = reps()
    _pools(owner_conn, "818", 60)
    holder = _paused_first_ask(monkeypatch, owner_url,
                               lambda: get_more_numbers(rep, LA, "k-same", _now()))
    first = get_more_numbers(rep, LA, "k-same", _now())
    holder["worker"].join(timeout=10)
    second = holder["out"].get("value")
    assert second is not None, holder["out"]
    assert second.retry is True
    assert set(second.assigned) == set(first.assigned)


def test_a_retry_with_a_later_at_returns_the_first_receipt(reps, owner_conn):
    _subscribe(owner_conn, "818")
    rep = reps()
    _pools(owner_conn, "818", 60)
    first = get_more_numbers(rep, LA, "k-retry", _now())
    again = get_more_numbers(rep, LA, "k-retry", _now() + timedelta(hours=1))
    assert again.retry is True
    assert set(again.assigned) == set(first.assigned)


def test_refusals_write_nothing(reps, owner_conn):
    _subscribe(owner_conn, "818")
    rep, inactive = reps(), reps("inactive")
    _pools(owner_conn, "818", 3)
    cases = [
        ("bad_region", lambda: get_more_numbers(rep, "Fresno", "k-r1", _now())),
        ("bad_rep", lambda: get_more_numbers(HOUSE_PARTNER_ID, LA, "k-r2", _now())),
        ("bad_time", lambda: get_more_numbers(rep, LA, "k-r3", datetime(2026, 9, 30, 12))),
        ("no_partner", lambda: get_more_numbers(uuid4(), LA, "k-r4", _now())),
        ("inactive_partner", lambda: get_more_numbers(inactive, LA, "k-r5", _now())),
    ]
    for code, call in cases:
        with pytest.raises(ValidationError) as err:
            call()
        assert err.value.code == code
    assert _batches(owner_conn) == 0


def test_the_gate_still_applies(reps, owner_conn):
    _subscribe(owner_conn, "818")
    rep = reps()
    clean = _pool(owner_conn, "+18185558000")
    _pool(owner_conn, "+18185558001", do_not_call=True)
    _pool(owner_conn, "+18185558002", dnc_registry=True)
    _pool(owner_conn, "+18185558003", dnc_checked_at=None)
    _pool(owner_conn, "+18185558004", stage_snapshot="won")
    _pool(owner_conn, "+18185558005")
    _sql(owner_conn, "insert into suppression_tombstones (phone_e164, channel, reason) "
                     "values ('+18185558005', 'voice', 'asked')")
    _pool(owner_conn, "+18185558006")
    _sql(owner_conn, "select dnc_block('+18185558006', 'admin', 'young', null, null, "
                     "'asked', now())")
    assert get_more_numbers(rep, LA, "k-gate", _now()).assigned == [clean]


# --- skip, never wait -------------------------------------------------------------


def test_an_ask_skips_locked_contacts(reps, owner_conn, owner_url):
    _subscribe(owner_conn, "818")
    rep, other = reps(), reps()
    held, free = _pool(owner_conn, "+18185558100"), _pool(owner_conn, "+18185558101")
    with psycopg.connect(owner_url) as blocker:
        blocker.execute("select 1 from contacts where id = %s for update", (held,))
        worker, out = _run(lambda: get_more_numbers(rep, LA, "k-skip", _now()))
        worker.join(timeout=5)
        assert not worker.is_alive(), "the ask waited on a locked contact"
        report = out["value"]
        assert report.assigned == [free]
        assert report.shortfall == {"locked": [held]}
        blocker.rollback()

        reclaim(rep, "back", "young")
        blocker.execute("select 1 from contacts where id = any(%s) for update", ([held, free],))
        worker, out = _run(lambda: get_more_numbers(other, LA, "k-skip2", _now()))
        worker.join(timeout=5)
        assert not worker.is_alive(), "the ask waited on a locked contact"
        report = out["value"]
        assert report.assigned == []
        assert set(report.shortfall["locked"]) == {held, free}
        blocker.rollback()


# --- the 90 days, per contact -----------------------------------------------------


def test_a_door_b_claim_of_nmc_s_goes_back_after_90_days(reps, owner_conn):
    rep = reps()
    x = _pool(owner_conn, "+18185558200")
    y = _pool(owner_conn, "+18185558201")
    assert _add(rep, "+18185558200") == "claimed"
    assert _add(rep, "+18185558201") == "claimed"
    _backdate(owner_conn, x, "contact.assigned", 91)
    _backdate(owner_conn, y, "contact.assigned", 89)
    assert run_expiry_step() == 1
    assert _owner(owner_conn, x) == HOUSE_PARTNER_ID
    assert _owner(owner_conn, y) == rep
    latest = _sql(owner_conn, "select type from events where contact_id = %s "
                              "order by id desc limit 1", (x,))[0][0]
    assert latest == "contact.assignment_expired"


def test_the_90_days_run_from_the_latest_assignment(reps, owner_conn):
    _subscribe(owner_conn, "818")
    first, second = reps(), reps()
    y = _pool(owner_conn, "+18185558210")
    assign_batch(first, "k-old", "young", contact_ids=[y])
    _expire_batches(owner_conn, first)
    assert run_expiry_step() == 1
    _backdate(owner_conn, y, "contact.assigned", 200)
    _backdate(owner_conn, y, "contact.assignment_expired", 110)
    assert _add(second, "+18185558210") == "claimed"
    _sql(owner_conn,
         "update events set occurred_at = now() - interval '10 days' where id = "
         "(select max(id) from events where contact_id = %s and type = 'contact.assigned')",
         (y,))
    assert run_expiry_step() == 0
    assert _owner(owner_conn, y) == second


def test_a_rep_s_own_and_a_sold_contact_stay(reps, owner_conn):
    rep = reps()
    assert _add(rep, "+18185558220") == "added"
    own = _contact_for(owner_conn, "+18185558220")
    won = _pool(owner_conn, "+18185558221")
    signed = _pool(owner_conn, "+18185558222")
    unmatched = _pool(owner_conn, "+18185558223")
    for phone in ("+18185558221", "+18185558222", "+18185558223"):
        assert _add(rep, phone) == "claimed"
    _sql(owner_conn, "update contacts set stage_snapshot = 'won' where id = %s", (won,))
    ingest_event("posthog", "signup.completed", _now(), {}, contact_id=signed)
    ingest_event("posthog", "signup.completed", _now(), {"phone_e164": "+18185558223"})
    for contact in (own, won, signed, unmatched):
        _backdate(owner_conn, contact, "contact.assigned", 91)
    assert run_expiry_step() == 0
    for contact in (own, won, signed, unmatched):
        assert _owner(owner_conn, contact) == rep


def _rule_1_and_rule_2(reps, owner_conn) -> tuple[UUID, UUID, UUID, UUID]:
    """Two contacts: one whose batch expired (rule 1), one door B claim 91 days old
    (rule 2). Returns (low id, high id, the rule-1 contact, the rule-2 contact) after
    giving the lower id whichever role the caller then reads off."""
    _subscribe(owner_conn, "818")
    batch_rep, claim_rep = reps(), reps()
    a = _pool(owner_conn, "+18185558230")
    b = _pool(owner_conn, "+18185558231")
    low, high = sorted([a, b], key=str)
    return low, high, batch_rep, claim_rep


def _set_up(owner_conn, rule_1: UUID, rule_2: UUID, batch_rep: UUID, claim_rep: UUID):
    assign_batch(batch_rep, f"k-{uuid4().hex[:6]}", "young", contact_ids=[rule_1])
    _expire_batches(owner_conn, batch_rep)
    phone = _sql(owner_conn, "select phone_e164 from contacts where id = %s", (rule_2,))[0][0]
    assert _add(claim_rep, phone) == "claimed"
    _backdate(owner_conn, rule_2, "contact.assigned", 91)


def test_both_rules_at_once(reps, owner_conn):
    low, high, batch_rep, claim_rep = _rule_1_and_rule_2(reps, owner_conn)
    _set_up(owner_conn, low, high, batch_rep, claim_rep)
    assert run_expiry_step() == 2


@pytest.mark.parametrize("rule_2_is_low", [True, False])
def test_the_step_locks_in_one_pass(reps, owner_conn, owner_url, rule_2_is_low):
    low, high, batch_rep, claim_rep = _rule_1_and_rule_2(reps, owner_conn)
    if rule_2_is_low:
        _set_up(owner_conn, high, low, batch_rep, claim_rep)
    else:
        _set_up(owner_conn, low, high, batch_rep, claim_rep)
    with psycopg.connect(owner_url) as blocker:
        blocker.execute("select 1 from contacts where id = %s for update", (low,))
        worker, out = _run(run_expiry_step)
        _wait_until_blocked(owner_url)
        with psycopg.connect(owner_url) as probe:
            probe.execute("select 1 from contacts where id = %s for update nowait", (high,))
            probe.rollback()
        blocker.rollback()
    worker.join(timeout=10)
    assert out.get("value") == 2, out


def test_the_latest_assignment_is_read_after_the_lock(reps, owner_conn, owner_url):
    rep = reps()
    x = _pool(owner_conn, "+18185558240")
    assert _add(rep, "+18185558240") == "claimed"
    _backdate(owner_conn, x, "contact.assigned", 91)
    with psycopg.connect(owner_url) as blocker:
        with blocker.cursor() as cur:
            cur.execute("select 1 from contacts where id = %s for update", (x,))
            worker, out = _run(run_expiry_step)
            _wait_until_blocked(owner_url)
            set_owner(cur, x, HOUSE_PARTNER_ID, event_type="contact.reclaimed",
                      reason="test", actor="t")
            set_owner(cur, x, rep, event_type="contact.assigned", reason="test", actor="t")
        blocker.commit()
    worker.join(timeout=10)
    assert out.get("value") == 0, out
    assert _owner(owner_conn, x) == rep


# --- not the same rep for 90 days -------------------------------------------------


def _expired_from(owner_conn, rep: UUID, phone: str) -> UUID:
    contact = _pool(owner_conn, phone)
    assert _add(rep, phone) == "claimed"
    _backdate(owner_conn, contact, "contact.assigned", 91)
    assert run_expiry_step() == 1
    return contact


def test_the_same_rep_waits_90_days(reps, owner_conn):
    _subscribe(owner_conn, "818")
    r, other = reps(), reps()
    x = _expired_from(owner_conn, r, "+18185558250")

    assert _add(r, "+18185558250") == "held"
    report = get_more_numbers(r, LA, "k-r", _now())
    assert x not in report.assigned
    assert report.shortfall.get("returned_recently") == [x]

    assert x in get_more_numbers(other, LA, "k-o", _now()).assigned
    reclaim(other, "back", "young")
    assert assign_batch(r, "k-op", "young", contact_ids=[x]).assigned == [x]
    reclaim(r, "back", "young")

    later = _now() + timedelta(days=91)
    assert x in get_more_numbers(r, LA, "k-later", later).assigned
    reclaim(r, "back", "young")
    assert _add(r, "+18185558250", at=later) == "claimed"


def test_another_rep_s_door_b_claims_it(reps, owner_conn):
    r, other = reps(), reps()
    _expired_from(owner_conn, r, "+18185558260")
    assert _add(other, "+18185558260") == "claimed"


def test_a_reclaim_starts_no_wait(reps, owner_conn):
    r = reps()
    _pool(owner_conn, "+18185558270")
    assert _add(r, "+18185558270") == "claimed"
    reclaim(r, "back", "young")
    assert _add(r, "+18185558270") == "claimed"


def test_the_90_day_edge(reps, owner_conn):
    r = reps()
    x = _expired_from(owner_conn, r, "+18185558280")
    expired_at = _sql(owner_conn, "select occurred_at from events where contact_id = %s "
                                  "and type = 'contact.assignment_expired'", (x,))[0][0]
    assert _add(r, "+18185558280", at=expired_at + timedelta(days=90)) == "held"
    assert _add(r, "+18185558280", at=expired_at + timedelta(days=90, seconds=1)) == "claimed"


def test_an_expiry_landing_while_door_b_waits_is_seen(reps, owner_conn, owner_url):
    _subscribe(owner_conn, "818")
    r = reps()
    x = _pool(owner_conn, "+18185558290")
    assert _add(r, "+18185558290") == "claimed"
    reclaim(r, "back", "young")
    assign_batch(r, "k-x", "young", contact_ids=[x])
    with psycopg.connect(owner_url) as blocker:
        with blocker.cursor() as cur:
            cur.execute("select 1 from contacts where id = %s for update", (x,))
            set_owner(cur, x, HOUSE_PARTNER_ID, event_type="contact.assignment_expired",
                      reason="expired", actor="system")
            worker, out = _run(lambda: _add(r, "+18185558290"))
            _wait_until_blocked(owner_url)
        blocker.commit()
    worker.join(timeout=10)
    assert out.get("value") == "held", out


# --- the console ------------------------------------------------------------------


def test_the_console_counts_only_nmc_s_contacts_the_house_holds(reps, owner_conn):
    _subscribe(owner_conn, "818")
    rep = reps()
    _pool(owner_conn, "+18185558300")
    _pool(owner_conn, "+18185558301")
    assert _add(rep, "+18185558301") == "claimed"
    assert _add(rep, "+18185558302") == "added"
    own = _contact_for(owner_conn, "+18185558302")
    _sql(owner_conn, "update contacts set dnc_checked_at = now() where id = %s", (own,))
    reclaim(rep, "back", "young")
    assert _add(rep, "+18185558301") == "claimed"

    inventory = {row[0]: row for row in console._owned_inventory()}
    assert inventory["818"][3] == 1
    view = {row[0]: row for row in console._subscription_view()}
    assert view["818"][4] == 1


# --- existing callers -------------------------------------------------------------


def test_existing_callers_are_unchanged(reps, owner_conn):
    _subscribe(owner_conn, "818")
    rep = reps()
    ids = _pools(owner_conn, "818", 5)
    report = assign_batch(rep, "k-plain", "young", audience_rule={"area_code": ["818"]},
                          count=2)
    assert report.assigned == sorted(ids, key=str)[:2]
    canonical = json.dumps({"partner_id": str(rep), "rule": {}, "count": 5,
                            "contact_ids": None}, sort_keys=True)
    assert asg._request_hash(rep, {}, 5, None) == hashlib.sha256(canonical.encode()).hexdigest()
