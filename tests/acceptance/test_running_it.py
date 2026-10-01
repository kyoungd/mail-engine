"""Part 6b gate: running it (docs/contact-engine/06b-running-it.md §4, §7).

The nightly records each run it completes; the scrub also rechecks a contact whose
list is over 21 days old when tonight's list is newer; one status read names what
holds now — a missing daily run, contacts about to stop being callable, a call left
open — for the website to send; and a health check says the service answers.
"""

import threading
import time
import zipfile
from datetime import UTC, date, datetime, time as dtime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

import db.session as session
import web.api as web_api
from config.params import HOUSE_PARTNER_ID
from jobs import nightly_cli
from jobs.dnc_pull import pull_snapshots
from jobs.dnc_refresh import _due, dnc_refresh_all
from seams.fakes import FakeSnapshotInbox
from service import calls, dnc, runs
from tests.factories import new_contact

DK, WK = "dialer-key-for-tests", "website-key-for-tests"
AT = datetime.now(UTC).replace(microsecond=0)


def _utc_today() -> date:
    return datetime.now(UTC).date()


# --- fixtures and helpers ---------------------------------------------------------


@pytest.fixture()
def fresh(clean_db, owner_conn):
    """clean_db, plus the tables it does not truncate; partners made here go after."""
    def wipe():
        owner_conn.rollback()
        with owner_conn.cursor() as cur:
            cur.execute("truncate daily_runs")
            cur.execute("select id from partners where id <> %s and name <> 'John'",
                        (HOUSE_PARTNER_ID,))
            made = [r[0] for r in cur.fetchall()]
            cur.execute("delete from calls where rep_id = any(%s)", (made,))
            cur.execute("delete from intake_rep where rep_id = any(%s)", (made,))
            cur.execute("update contacts set owner_id = %s, assignment_batch_id = null "
                        "where owner_id = any(%s)", (HOUSE_PARTNER_ID, made))
            cur.execute("delete from assignment_batches where partner_id = any(%s)",
                        (made,))
            cur.execute("delete from dnc_subscriptions where san_holder_id = any(%s)",
                        (made,))
            cur.execute("delete from dnc_snapshots where san_holder_id = any(%s)", (made,))
            cur.execute("delete from partners where id = any(%s)", (made,))
        owner_conn.commit()

    wipe()
    yield owner_conn
    wipe()


def _sql(conn, query: str, params=()):
    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall() if cur.description else []
    conn.commit()
    return rows


def _partner(conn, *, sales_rep_id: int | None = None) -> UUID:
    return _sql(conn, "insert into partners (name, sales_rep_id) values (%s, %s) returning id",
                (f"Run-{uuid4().hex[:8]}", sales_rep_id))[0][0]


def _subscribe(conn, area_code: str = "818", *, ago: timedelta = timedelta(hours=60),
               holder: UUID = HOUSE_PARTNER_ID) -> None:
    _sql(conn, "insert into dnc_subscriptions (area_code, san_holder_id, subscribed_at) "
               "values (%s, %s, %s)", (area_code, holder, AT - ago))


def _snapshot(conn, area_code: str, list_date: date, *, status: str = "accepted",
              holder: UUID = HOUSE_PARTNER_ID) -> UUID:
    """A ledger row with no file behind it."""
    return _sql(
        conn,
        "insert into dnc_snapshots (area_code, san_holder_id, version_date, file_guid, "
        "sha256, object_key, uploaded_at, status, reject_reason) "
        "values (%s, %s, %s, %s, %s, %s, now(), %s, %s) returning id",
        (area_code, holder, list_date, uuid4().hex, uuid4().hex, f"dnc/test/{uuid4().hex}",
         status, None if status == "accepted" else "short_file"),
    )[0][0]


def _zip_bytes(name: str, lines: list[str], tmp_path: Path) -> bytes:
    path = tmp_path / f"staging-{name}"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(name.removesuffix(".zip"), "".join(f"{line}\n" for line in lines))
    data = path.read_bytes()
    path.unlink()
    return data


def _land(conn, tmp_path, lists_root, list_date: date, area_code: str = "818") -> UUID:
    """One snapshot through the real pull, with its file on disk."""
    name = (f"{list_date.year}-{list_date.month}-{list_date.day}"
            f"_{area_code}_{uuid4().hex}.txt.zip")
    key = f"dnc/{HOUSE_PARTNER_ID}/{name}"
    uploaded_at = datetime.combine(list_date, dtime(15), tzinfo=UTC)
    inbox = FakeSnapshotInbox()
    inbox.add(key=key, partner_id=HOUSE_PARTNER_ID,
              body=_zip_bytes(name, [f"{area_code},5550100"], tmp_path),
              uploaded_at=uploaded_at, claimed_fetched_at=uploaded_at)
    pull_snapshots(inbox, lists_root=lists_root)
    rows = _sql(conn, "select id, status from dnc_snapshots where object_key = %s", (key,))
    assert rows and rows[0][1] == "accepted"
    return rows[0][0]


_n = [0]


def _contact(conn, area_code: str = "818", **fields) -> UUID:
    _n[0] += 1
    fields.setdefault("phone_e164", f"+1{area_code}555{_n[0]:04d}")
    with conn.cursor() as cur:
        contact = new_contact(cur, intake=False, **fields)
    conn.commit()
    return contact


def _linked(conn, list_age_days: int, *, checked: timedelta = timedelta(days=5),
            **fields) -> UUID:
    snapshot = _snapshot(conn, "818", _utc_today() - timedelta(days=list_age_days))
    return _contact(conn, dnc_checked_at=AT - checked, dnc_snapshot_id=snapshot, **fields)


def _link_of(conn, contact: UUID):
    return _sql(conn, "select dnc_snapshot_id, dnc_checked_at from contacts where id = %s",
                (contact,))[0]


def _expiring(at: datetime = AT) -> dict:
    return runs.status(at)["dnc_checks_expiring"]


def _codes(status: dict) -> list[str]:
    return [a["code"] for a in status["alerts"]]


# --- the record (§4.1) --------------------------------------------------------------


def _runs(conn) -> list[datetime]:
    return [r[0] for r in _sql(conn, "select finished_at from daily_runs order by id")]


def test_the_nightly_records_each_run_it_completes(fresh, monkeypatch):
    monkeypatch.setattr(nightly_cli, "run_nightly", lambda **_: None)
    monkeypatch.delenv("MEDUSA_READONLY_URL", raising=False)
    before = datetime.now(UTC)
    assert nightly_cli.main([]) == 0
    [finished] = _runs(fresh)
    assert before <= finished <= datetime.now(UTC)

    assert nightly_cli.main(["--dry-run"]) == 0
    assert len(_runs(fresh)) == 1

    def broken(**_):
        raise RuntimeError("the nightly broke")

    monkeypatch.setattr(nightly_cli, "run_nightly", broken)
    with pytest.raises(RuntimeError):
        nightly_cli.main([])
    assert len(_runs(fresh)) == 1


def test_record_daily_run_stamps_its_moment(fresh):
    runs.record_daily_run(AT - timedelta(hours=3))
    assert _runs(fresh) == [AT - timedelta(hours=3)]


# --- daily_run_missing (§4.3) -------------------------------------------------------


def test_daily_run_missing(fresh):
    status = runs.status(AT)
    assert status["daily_run"] == {"last_finished_at": None}
    assert "daily_run_missing" in _codes(status)

    runs.record_daily_run(AT - timedelta(hours=40))
    runs.record_daily_run(AT - timedelta(hours=26))
    status = runs.status(AT)
    assert status["daily_run"] == {"last_finished_at": AT - timedelta(hours=26)}
    assert "daily_run_missing" not in _codes(status)

    later = AT + timedelta(minutes=1)
    assert "daily_run_missing" in _codes(runs.status(later))


def test_the_scrub_is_a_fact(fresh):
    _sql(fresh, "insert into dnc_runs (started_at, limited) values (%s, false), (%s, true)",
         (AT - timedelta(hours=5), AT - timedelta(hours=1)))
    assert runs.status(AT)["scrub"] == {"last_started_at": AT - timedelta(hours=5)}


# --- the recheck by the list's age (§4.2) ------------------------------------------


@pytest.mark.parametrize("pgtz", ["UTC", "Pacific/Kiritimati", "Pacific/Pago_Pago"])
@pytest.mark.parametrize(("age", "rechecked"), [(22, True), (21, False), (20, False)])
def test_a_contact_on_an_old_list_is_rechecked_when_a_newer_one_exists(
    fresh, tmp_path, monkeypatch, pgtz, age, rechecked
):
    monkeypatch.setenv("PGTZ", pgtz)
    lists_root = tmp_path / "lists"
    _subscribe(fresh)
    tonight = _land(fresh, tmp_path, lists_root, _utc_today())
    contact = _linked(fresh, age)
    before = _link_of(fresh, contact)

    dnc_refresh_all(lists_root=lists_root)

    after = _link_of(fresh, contact)
    if rechecked:
        assert after[0] == tonight and after[1] > before[1]
    else:
        assert after == before


def test_no_recheck_when_tonight_s_list_is_the_one_it_has(fresh, tmp_path):
    lists_root = tmp_path / "lists"
    _subscribe(fresh)
    old = _land(fresh, tmp_path, lists_root, _utc_today() - timedelta(days=22))
    contact = _contact(fresh, dnc_checked_at=AT - timedelta(days=5), dnc_snapshot_id=old)
    before = _link_of(fresh, contact)

    report = dnc_refresh_all(lists_root=lists_root)

    assert report.checked == 0
    assert _link_of(fresh, contact) == before


def test_a_same_date_list_from_another_holder_is_not_newer(fresh, tmp_path):
    lists_root = tmp_path / "lists"
    other = _partner(fresh)
    _subscribe(fresh)
    _subscribe(fresh, holder=other)
    day = _utc_today() - timedelta(days=22)
    mine = _snapshot(fresh, "818", day)
    _snapshot(fresh, "818", day, holder=other)
    contact = _contact(fresh, dnc_checked_at=AT - timedelta(days=5), dnc_snapshot_id=mine)
    before = _link_of(fresh, contact)

    report = dnc_refresh_all(lists_root=lists_root)

    assert report.checked == 0
    assert _link_of(fresh, contact) == before


def test_under_a_limit_rep_held_contacts_come_first(fresh, tmp_path):
    lists_root = tmp_path / "lists"
    rep = _partner(fresh)
    _subscribe(fresh)
    tonight = _land(fresh, tmp_path, lists_root, _utc_today())
    pool = _linked(fresh, 25)
    held = _linked(fresh, 25)
    _sql(fresh, "update contacts set owner_id = %s where id = %s", (rep, held))

    dnc_refresh_all(lists_root=lists_root, limit=1)

    assert _link_of(fresh, held)[0] == tonight
    assert _link_of(fresh, pool)[0] != tonight


def test_a_newer_list_with_no_working_copy_rechecks_nothing_and_the_alert_counts(
    fresh, tmp_path
):
    lists_root = tmp_path / "lists"
    _subscribe(fresh)
    _snapshot(fresh, "818", _utc_today())
    contact = _linked(fresh, 25)
    before = _link_of(fresh, contact)

    report = dnc_refresh_all(lists_root=lists_root)

    assert ("818", "working_copy_missing") in report.skips
    assert _link_of(fresh, contact) == before
    assert _expiring()["pool"] == 1


def test_the_single_registry_due_set_is_by_the_check_s_age_alone(fresh):
    _subscribe(fresh)
    _snapshot(fresh, "818", _utc_today())
    on_old_list = _linked(fresh, 25)
    old_check = _contact(fresh, dnc_checked_at=AT - timedelta(days=22))
    due = {row[0] for row in _due(["818"], None)}
    assert old_check in due
    assert on_old_list not in due


# --- dnc_checks_expiring (§4.3) -----------------------------------------------------

_DAY = timedelta(days=1)

# (case, how the contact is made, counted under (a))
_CASES = [
    ("list 25 days old", lambda c: _linked(c, 25, checked=timedelta(hours=1)), True),
    ("list 24 days old", lambda c: _linked(c, 24, checked=timedelta(hours=1)), False),
    ("list 23 days old", lambda c: _linked(c, 23, checked=timedelta(hours=1)), False),
    ("list 40 days old", lambda c: _linked(c, 40, checked=timedelta(hours=1)), True),
    ("check just over 24 days, no list",
     lambda c: _contact(c, dnc_checked_at=AT - 24 * _DAY - timedelta(seconds=1)), True),
    ("check exactly 24 days, no list",
     lambda c: _contact(c, dnc_checked_at=AT - 24 * _DAY), False),
    ("check 25 days, no list", lambda c: _contact(c, dnc_checked_at=AT - 25 * _DAY), True),
    ("check 23 days, no list", lambda c: _contact(c, dnc_checked_at=AT - 23 * _DAY), False),
    ("on the DNC file",
     lambda c: _linked(c, 25, checked=timedelta(hours=1), dnc_registry=True), False),
    ("a seed", lambda c: _linked(c, 25, checked=timedelta(hours=1), is_seed=True), False),
    ("an unsubscribed code",
     lambda c: _contact(c, "714", dnc_checked_at=AT - 25 * _DAY), False),
    ("linked to a rejected list",
     lambda c: _contact(c, dnc_checked_at=AT - timedelta(hours=1),
                        dnc_snapshot_id=_snapshot(c, "818", _utc_today() - 25 * _DAY,
                                                  status="rejected")), False),
    ("linked to another code's list",
     lambda c: _contact(c, dnc_checked_at=AT - timedelta(hours=1),
                        dnc_snapshot_id=_snapshot(c, "714", _utc_today() - 25 * _DAY)),
     False),
]


@pytest.mark.parametrize(("case", "make", "counted"), _CASES, ids=[c[0] for c in _CASES])
def test_dnc_checks_expiring_agrees_with_dnc_status(fresh, case, make, counted):
    _subscribe(fresh)
    contact = make(fresh)
    expiring = _expiring()
    assert (expiring["pool"] == 1) is counted, case
    assert expiring["held"] == 0 and expiring["never_checked"] == 0
    assert counted == (dnc.dnc_status(contact, AT + 7 * _DAY) == "check_too_old"), case


def test_a_blocked_contact_and_one_with_no_phone_are_not_counted(fresh):
    _subscribe(fresh)
    blocked = _linked(fresh, 25, checked=timedelta(hours=1))
    phone = _sql(fresh, "select phone_e164 from contacts where id = %s", (blocked,))[0][0]
    dnc.record_do_not_call_request(phone, "young", "asked", AT)
    _contact(fresh, phone_e164=None, dnc_checked_at=AT - 25 * _DAY)
    assert _expiring() == {"held": 0, "pool": 0, "never_checked": 0,
                           "by_area_code": {"818": {"held": 0, "pool": 0,
                                                    "never_checked": 0}}}


def test_held_and_pool_are_counted_apart_and_by_area_code(fresh):
    _subscribe(fresh)
    _subscribe(fresh, "714")
    rep = _partner(fresh, sales_rep_id=int(time.time()))
    export_partner = _partner(fresh)
    for owner in (rep, export_partner):
        c = _linked(fresh, 25, checked=timedelta(hours=1))
        _sql(fresh, "update contacts set owner_id = %s where id = %s", (owner, c))
    _linked(fresh, 25, checked=timedelta(hours=1))
    _contact(fresh, "714", dnc_checked_at=AT - 25 * _DAY)
    status = runs.status(AT)
    assert status["dnc_checks_expiring"] == {
        "held": 2, "pool": 2, "never_checked": 0,
        "by_area_code": {"818": {"held": 2, "pool": 1, "never_checked": 0},
                         "714": {"held": 0, "pool": 1, "never_checked": 0}},
    }
    [alert] = [a for a in status["alerts"] if a["code"] == "dnc_checks_expiring"]
    assert alert["detail"]["held"] == 2 and alert["detail"]["pool"] == 2


def test_none_expiring_raises_no_alert(fresh):
    _subscribe(fresh)
    _linked(fresh, 1, checked=timedelta(hours=1))
    assert "dnc_checks_expiring" not in _codes(runs.status(AT))


def test_never_checked(fresh):
    _subscribe(fresh)
    rep = _partner(fresh)
    _contact(fresh, created_at=AT - timedelta(hours=49))
    _contact(fresh, created_at=AT - timedelta(hours=47))
    late = _contact(fresh, created_at=AT - timedelta(hours=60))
    _sql(fresh,
         "insert into intake_rep (contact_id, rep_id, phone_e164, how_obtained, "
         "confirmation, added_at) select id, %s, phone_e164, 'referral', 'mine', %s "
         "from contacts where id = %s",
         (rep, AT - timedelta(hours=10), late))
    assert _expiring()["never_checked"] == 1
    assert "dnc_checks_expiring" in _codes(runs.status(AT))


def test_never_checked_counts_from_the_code_s_earliest_subscription(fresh):
    other = _partner(fresh)
    _subscribe(fresh, ago=timedelta(hours=60))
    _subscribe(fresh, ago=timedelta(hours=10), holder=other)
    _contact(fresh, created_at=AT - timedelta(hours=90))
    assert _expiring()["never_checked"] == 1

    _subscribe(fresh, "714", ago=timedelta(hours=10))
    _contact(fresh, "714", created_at=AT - timedelta(hours=90))
    expiring = _expiring()
    assert expiring["never_checked"] == 1
    assert expiring["by_area_code"]["714"]["never_checked"] == 0


# --- call_left_open (§4.3) ----------------------------------------------------------


def _open_call(conn, opened_ago: timedelta) -> UUID:
    rep = _partner(conn)
    opened = AT - opened_ago
    contact = _contact(conn, dnc_checked_at=opened - timedelta(hours=1), addr_state="CA")
    _sql(conn, "update contacts set owner_id = %s where id = %s", (rep, contact))
    return calls.open_call(rep, contact, opened, confirm_outside_hours=True).call_id


@pytest.mark.parametrize(("hours", "alerts"), [(25, True), (24, False), (23, False)])
def test_call_left_open(fresh, hours, alerts):
    _subscribe(fresh)
    _open_call(fresh, timedelta(hours=hours))
    status = runs.status(AT)
    assert status["calls_open_over_24h"] == (1 if alerts else 0)
    found = [a for a in status["alerts"] if a["code"] == "call_left_open"]
    assert found == ([{"code": "call_left_open", "detail": {"count": 1}}] if alerts else [])


def test_a_cleared_call_or_one_with_an_outcome_is_not_open(fresh):
    _subscribe(fresh)
    cleared = _open_call(fresh, timedelta(hours=30))
    calls.clear_call(cleared, "young", "crashed", AT)
    done = _open_call(fresh, timedelta(hours=30))
    _sql(fresh, "update calls set outcome = 'no_answer', outcome_at = %s where id = %s",
         (AT - timedelta(hours=29), done))
    status = runs.status(AT)
    assert status["calls_open_over_24h"] == 0
    assert "call_left_open" not in _codes(status)


# --- the routes (§4.3, §4.4) --------------------------------------------------------


@pytest.fixture()
def api(monkeypatch, fresh):
    monkeypatch.setenv("CE_DIALER_KEY", DK)
    monkeypatch.setenv("CE_WEBSITE_KEY", WK)
    return TestClient(web_api.create_app(), raise_server_exceptions=False)


def test_the_status_route(api, monkeypatch):
    monkeypatch.setattr(web_api, "_now", lambda: AT)
    for headers in ({"X-API-Key": WK}, {"X-API-Key": WK, "X-Admin": "young"}):
        response = api.get("/v1/status", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body) == {"daily_run", "scrub", "dnc_checks_expiring",
                             "calls_open_over_24h", "alerts"}
        assert [a["code"] for a in body["alerts"]] == ["daily_run_missing"]
        assert all(set(a) == {"code", "detail"} for a in body["alerts"])
    assert api.get("/v1/status", headers={"X-API-Key": DK}).json()["code"] == "wrong_key"
    assert api.get("/v1/status").status_code == 401


def test_the_status_takes_no_lock(api, fresh, owner_url):
    _subscribe(fresh)
    call = _open_call(fresh, timedelta(hours=30))
    with psycopg.connect(owner_url) as blocker:
        blocker.execute("select 1 from calls where id = %s for update", (call,))
        blocker.execute("select 1 from contacts for update")
        blocker.execute("lock table daily_runs in row exclusive mode")
        out: dict = {}
        worker = threading.Thread(
            target=lambda: out.setdefault("r", api.get("/v1/status",
                                                       headers={"X-API-Key": WK})))
        worker.start()
        worker.join(timeout=5)
        alive = worker.is_alive()
        blocker.rollback()
        worker.join(timeout=10)
    assert not alive, "the status waited on a lock"
    assert out["r"].status_code == 200


def test_health(api, monkeypatch):
    response = api.get("/health")
    assert (response.status_code, response.json()) == (200, {"ok": True})

    seen: dict = {}
    real_connect = psycopg.connect

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(session.psycopg, "connect", spy)
    assert api.get("/health").status_code == 200
    assert seen.get("connect_timeout") == 3
    assert "statement_timeout=2000" in seen.get("options", "")
    monkeypatch.undo()

    monkeypatch.setattr(session, "_owner_url",
                        lambda: "postgresql://nobody@127.0.0.1:1/nothing")
    response = api.get("/health")
    assert (response.status_code, response.json()) == (503, {"ok": False})


def test_a_code_with_two_holders_counts_each_contact_once(fresh):
    other = _partner(fresh)
    _subscribe(fresh, ago=timedelta(hours=60))
    _subscribe(fresh, ago=timedelta(hours=50), holder=other)
    _contact(fresh, created_at=AT - timedelta(hours=90))
    _linked(fresh, 25, checked=timedelta(hours=1))
    expiring = _expiring()
    assert (expiring["never_checked"], expiring["pool"]) == (1, 1)
    assert expiring["by_area_code"] == {"818": {"held": 0, "pool": 1, "never_checked": 1}}
