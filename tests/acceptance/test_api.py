"""Part 6a gate: the API (docs/contact-engine/06a-the-api.md §4, §5, §7).

The only way in from outside: two keys, a rep or an admin per request, every action
remembered with its answer in the act's own transaction, every refusal in one shape,
and a contact the rep never held indistinguishable from one that does not exist.
"""

import json
import threading
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from itertools import count
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import psycopg
import pytest
from fastapi.testclient import TestClient

import service.calls as calls
import service.reads as reads
import service.roster as roster
import web.api as web_api
from config.params import ASSIGNMENT_EXPIRY_DAYS, HOUSE_PARTNER_ID
from db.session import transaction
from domain.types import RepRow
from jobs import partners_cli
from service import rep_intake, rule, zones
from service.assignment import assign_batch, run_expiry_step
from service.custody import set_owner
from tests.factories import new_contact

DK, WK = "dialer-key-for-tests", "website-key-for-tests"
CONFIRMATION = "These are businesses I found through my own prospecting."
LA = "LA area"
LA_ZONE = "America/Los_Angeles"
NO_CONTACT = {"code": "no_contact", "message": "no such contact", "detail": {}}


def _now() -> datetime:
    return datetime.now(UTC)


def _inside_at() -> datetime:
    """A moment at least an hour ahead that is noon in Los Angeles — inside the calling
    window, and after every `dnc_checked_at` the helpers write."""
    t = (_now() + timedelta(hours=1)).astimezone(ZoneInfo(LA_ZONE))
    noon = t.replace(hour=12, minute=0, second=0, microsecond=0)
    if noon < t:
        noon += timedelta(days=1)
    return noon.astimezone(UTC)


# --- fixtures and helpers ---------------------------------------------------------


@dataclass(frozen=True)
class Rep:
    id: UUID
    sid: int
    name: str


_sids = count(int(time.time()) % 1_000_000 * 1000)


def _sql(owner_conn, query: str, params=()):
    with owner_conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall() if cur.description else []
    owner_conn.commit()
    return rows


def _forget_partners(owner_conn) -> None:
    """Every partner but the seeded two goes, with what refers to it; the seeded two
    are left unlinked."""
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
        cur.execute(
            "update partners set sales_rep_id = null, status = 'active' "
            "where id = %s or name = 'John'",
            (HOUSE_PARTNER_ID,),
        )
    owner_conn.commit()


@pytest.fixture()
def reps(clean_db, owner_conn):
    _forget_partners(owner_conn)

    def make(status: str = "active") -> Rep:
        sid = next(_sids)
        name = f"Rep-{uuid4().hex[:8]}"
        rows = _sql(owner_conn,
                    "insert into partners (name, status, sales_rep_id) values (%s, %s, %s) "
                    "returning id", (name, status, sid))
        return Rep(id=rows[0][0], sid=sid, name=name)

    yield make
    _forget_partners(owner_conn)


@pytest.fixture()
def api(monkeypatch, reps):
    monkeypatch.setenv("CE_DIALER_KEY", DK)
    monkeypatch.setenv("CE_WEBSITE_KEY", WK)
    return TestClient(web_api.create_app(), raise_server_exceptions=False)


def _client(api: TestClient) -> TestClient:
    """A second client on the same app, for a request made from another thread."""
    return TestClient(api.app, raise_server_exceptions=False)


def _headers(rep=None, key=DK, idem=None, admin=None) -> dict[str, str]:
    h = {"X-API-Key": key}
    if rep is not None:
        h["X-Rep"] = str(rep.sid if isinstance(rep, Rep) else rep)
    if admin is not None:
        h["X-Admin"] = admin
    if idem is not None:
        h["Idempotency-Key"] = idem
    return h


def _act(api, path, body=None, *, rep=None, key=DK, idem: str | None = "new", admin=None, method="POST"):
    if idem == "new":
        idem = uuid4().hex
    return api.request(method, "/v1" + path, json=body,
                       headers=_headers(rep, key, idem, admin))


def _get(api, path, *, rep=None, key=DK, admin=None, params=None):
    return api.get("/v1" + path, headers=_headers(rep, key, None, admin), params=params)


def _ok(response) -> dict:
    assert response.status_code == 200, (response.status_code, response.text)
    return response.json()


def _refused(response, status: int, code: str) -> dict:
    assert response.status_code == status, (response.status_code, response.text)
    body = response.json()
    assert body["code"] == code, body
    assert set(body) == {"code", "message", "detail"}
    return body


_n = count(1)


def _contact(owner_conn, *, business: str | None = None, name: str | None = None,
             phone: str | None = None, **fields) -> UUID:
    """NMC's contact the house holds: an 818 number, subscribed, freshly checked, CA,
    with a CSLB intake row for a plumber."""
    _sql(owner_conn, "insert into dnc_subscriptions (area_code, subscribed_at) "
                     "values ('818', now()) on conflict do nothing")
    n = next(_n)
    with owner_conn.cursor() as cur:
        contact = new_contact(
            cur, phone_e164=phone or f"+1818555{n:04d}",
            business_name=business or f"Business {n}", contact_name=name or f"Owner {n}",
            addr_city="Reseda", addr_state="CA",
            dnc_checked_at=_now() - timedelta(hours=1), **fields,
        )
    owner_conn.commit()
    return contact


def _phone(owner_conn, contact: UUID) -> str:
    return _sql(owner_conn, "select phone_e164 from contacts where id = %s", (contact,))[0][0]


def _owner(owner_conn, contact: UUID) -> UUID:
    return _sql(owner_conn, "select owner_id from contacts where id = %s", (contact,))[0][0]


def _batch(rep: Rep, *contacts: UUID):
    return assign_batch(rep.id, f"k-{uuid4().hex[:10]}", "young", contact_ids=list(contacts))


def _expire_to_house(owner_conn, rep: Rep, contact: UUID) -> None:
    _sql(owner_conn, "update assignment_batches set expires_at = now() - interval '1 day' "
                     "where partner_id = %s", (rep.id,))
    run_expiry_step()
    assert _owner(owner_conn, contact) == HOUSE_PARTNER_ID


def _claim(owner_conn, rep: Rep, contact: UUID) -> None:
    results = rep_intake.add_numbers(rep.id, [RepRow(phone=_phone(owner_conn, contact))],
                                     "referral", CONFIRMATION, _now())
    assert results[0].result == "claimed", results


def _own(rep: Rep, phone: str, **fields) -> UUID:
    results = rep_intake.add_numbers(rep.id, [RepRow(phone=phone, **fields)],
                                     "referral", CONFIRMATION, _now())
    assert results[0].result == "added", results
    contact = results[0].contact_id
    assert contact is not None
    return contact


def _went_back_and_taken(owner_conn, a: Rep, b: Rep) -> UUID:
    """A contact `a` held, which went back by expiry and `b` now holds."""
    x = _contact(owner_conn)
    _batch(a, x)
    _expire_to_house(owner_conn, a, x)
    _claim(owner_conn, b, x)
    return x


def _count(owner_conn, query: str, params=()) -> int:
    return _sql(owner_conn, query, params)[0][0]


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


# --- keys -------------------------------------------------------------------------


def test_keys(api, reps):
    r = reps()
    _refused(api.get("/v1/me/settings", headers={"X-Rep": str(r.sid)}), 401, "bad_key")
    _refused(_get(api, "/me/settings", rep=r, key="wrong"), 401, "bad_key")
    _ok(_get(api, "/me/settings", rep=r, key=DK))
    _ok(_get(api, "/me/settings", rep=r, key=WK))

    settings = {"voicemails": 3, "calls": 8, "days_between": 7, "rest_months": 6}
    _refused(_act(api, "/me/settings", settings, rep=r, method="PUT"), 403, "wrong_key")
    _refused(_act(api, "/me/settings/restore", rep=r), 403, "wrong_key")
    _refused(_get(api, "/admin/calls/open", admin="young"), 403, "wrong_key")
    _refused(_act(api, "/admin/do-not-call", {"phone": "8185550000", "reason": "asked"},
                  admin="young"), 403, "wrong_key")
    _refused(_act(api, f"/reps/{next(_sids)}", {"name": "Someone"}, key=WK, method="PUT"),
             403, "wrong_key")
    _refused(_act(api, f"/reps/{r.sid}/deactivate", key=WK), 403, "wrong_key")

    _ok(_act(api, "/me/settings", settings, rep=r, key=WK, method="PUT"))
    _ok(_get(api, "/admin/calls/open", key=WK, admin="young"))


@pytest.mark.parametrize("dialer, website", [
    (None, WK), (DK, None), ("", WK), (DK, ""), (DK, DK),
])
def test_the_app_refuses_to_start_without_two_keys(monkeypatch, dialer, website):
    for name, value in (("CE_DIALER_KEY", dialer), ("CE_WEBSITE_KEY", website)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError):
        web_api.create_app()


# --- the rep ----------------------------------------------------------------------


def test_the_rep(api, reps, owner_conn):
    r, gone = reps(), reps(status="inactive")
    _refused(api.get("/v1/me/settings", headers={"X-API-Key": DK}), 403, "unknown_rep")
    for bad in ("abc", "1.5", "", "99999999999999999999", str(next(_sids))):
        _refused(_get(api, "/me/settings", rep=bad), 403, "unknown_rep")
    house_sid = next(_sids)
    _sql(owner_conn, "update partners set sales_rep_id = %s where id = %s",
         (house_sid, HOUSE_PARTNER_ID))
    _refused(_get(api, "/me/settings", rep=house_sid), 403, "unknown_rep")
    _refused(_get(api, "/me/settings", rep=gone), 403, "rep_inactive")
    _refused(_act(api, "/me/more-numbers", {"region": LA}, rep=gone), 403, "rep_inactive")
    _ok(_get(api, "/me/settings", rep=r))


def test_an_inactive_rep_s_do_not_call_is_recorded(api, reps, owner_conn):
    r = reps()
    x = _contact(owner_conn)
    _batch(r, x)
    _sql(owner_conn, "update partners set status = 'inactive' where id = %s", (r.id,))
    assert _ok(_act(api, f"/contacts/{x}/do-not-call", {"reason": "asked"}, rep=r)) == {
        "result": "blocked"}
    assert _count(owner_conn, "select count(*) from dnc_log where rep_id = %s and "
                              "contact_id = %s", (r.id, x)) == 1


# --- the roster -------------------------------------------------------------------


def _partner(owner_conn, sid: int):
    rows = _sql(owner_conn, "select id, name, status from partners where sales_rep_id = %s",
                (sid,))
    return rows[0] if rows else None


def test_the_roster(api, reps, owner_conn):
    s1, s2, s3, s4 = next(_sids), next(_sids), next(_sids), next(_sids)
    alpha = f"Alpha-{uuid4().hex[:6]}"
    assert _ok(_act(api, f"/reps/{s1}", {"name": alpha}, method="PUT")) == {"result": "known"}
    first = _partner(owner_conn, s1)
    assert first is not None
    assert (first[1], first[2]) == (alpha, "active")

    beta = f"Beta-{uuid4().hex[:6]}"
    _ok(_act(api, f"/reps/{s1}", {"name": beta}, method="PUT"))
    assert _partner(owner_conn, s1) == (first[0], beta, "active")

    # an unlinked partner's name: the operator links it first, then it is found
    _refused(_act(api, f"/reps/{s2}", {"name": "John"}, method="PUT"), 409, "link_first")
    assert partners_cli.main(["set", "John", "--sales-rep-id", str(s2)]) == 0
    _ok(_act(api, f"/reps/{s2}", {"name": "John"}, method="PUT"))
    john = _sql(owner_conn, "select id from partners where name = 'John'")
    assert len(john) == 1
    assert _partner(owner_conn, s2) == (john[0][0], "John", "active")

    unlinked = f"Unlinked-{uuid4().hex[:6]}"
    _sql(owner_conn, "insert into partners (name) values (%s)", (unlinked,))
    _refused(_act(api, f"/reps/{s1}", {"name": unlinked}, method="PUT"), 409, "name_taken")
    _refused(_act(api, f"/reps/{s3}", {"name": "Young"}, method="PUT"), 409, "name_taken")
    _refused(_act(api, f"/reps/{s4}", {"name": beta}, method="PUT"), 409, "name_taken")
    _refused(_act(api, f"/reps/{s3}", {"name": "   "}, method="PUT"), 400, "bad_request")
    _refused(_act(api, "/reps/abc", {"name": "Gamma"}, method="PUT"), 400, "bad_request")
    assert _partner(owner_conn, s3) is None and _partner(owner_conn, s4) is None

    assert _ok(_act(api, f"/reps/{s1}/deactivate")) == {"result": "inactive"}
    assert _partner(owner_conn, s1) == (first[0], beta, "inactive")
    _ok(_act(api, f"/reps/{s1}/deactivate"))
    _refused(_act(api, f"/reps/{next(_sids)}/deactivate"), 404, "unknown_rep")
    _refused(_act(api, f"/reps/{s1}", {"name": beta}, method="PUT"), 409, "rep_inactive")
    _refused(_act(api, f"/reps/{s1}", {"name": "Young"}, method="PUT"), 409, "name_taken")


def test_two_reps_racing_for_one_name(api, reps, owner_conn, monkeypatch):
    s1, s2 = next(_sids), next(_sids)
    name = f"Racer-{uuid4().hex[:6]}"
    holder: dict = {}

    def hook(cur):
        if holder:
            return
        holder["started"] = True
        holder["worker"], holder["out"] = _run(
            lambda: _act(_client(api), f"/reps/{s2}", {"name": name}, method="PUT"))
        holder["worker"].join(timeout=10)

    monkeypatch.setattr(roster, "_after_name_check", hook)
    first = _act(api, f"/reps/{s1}", {"name": name}, method="PUT")
    assert not holder["worker"].is_alive()
    _ok(holder["out"]["value"])
    _refused(first, 409, "name_taken")
    assert _sql(owner_conn, "select sales_rep_id from partners where name = %s",
                (name,)) == [(s2,)]


# --- request memory ---------------------------------------------------------------


def _memos(owner_conn, contact: UUID) -> int:
    return _count(owner_conn, "select count(*) from memos where contact_id = %s", (contact,))


def test_a_success_is_answered_again(api, reps, owner_conn):
    r = reps()
    x = _contact(owner_conn)
    _batch(r, x)
    first = _act(api, f"/contacts/{x}/memos", {"text": "hello"}, rep=r, idem="k1")
    again = _act(api, f"/contacts/{x}/memos", {"text": "hello"}, rep=r, idem="k1")
    assert _ok(first) == _ok(again)
    assert "Idempotent-Replay" not in first.headers
    assert again.headers["Idempotent-Replay"] == "true"
    assert again.content == first.content
    assert _memos(owner_conn, x) == 1


def test_the_body_is_compared_canonically(api, reps):
    r, other = reps(), reps()
    body = {"voicemails": 3, "calls": 8, "days_between": 7, "rest_months": 6}
    _ok(_act(api, "/me/settings", body, rep=r, key=WK, idem="k2", method="PUT"))
    turned = api.put("/v1/me/settings", content=json.dumps(dict(reversed(body.items()))),
                     headers={**_headers(r, WK, "k2"), "Content-Type": "application/json"})
    _ok(turned)
    assert turned.headers["Idempotent-Replay"] == "true"
    _refused(_act(api, "/me/settings", {**body, "calls": 5}, rep=r, key=WK, idem="k2",
                  method="PUT"), 409, "key_mismatch")
    _refused(_act(api, "/me/settings/restore", rep=r, key=WK, idem="k2"), 409, "key_mismatch")
    separate = _act(api, "/me/settings", {**body, "calls": 5}, rep=other, key=WK, idem="k2",
                    method="PUT")
    _ok(separate)
    assert "Idempotent-Replay" not in separate.headers
    assert rule.get_settings(other.id).calls == 5


def test_an_action_carries_a_good_key(api, reps, owner_conn):
    r = reps()
    x = _contact(owner_conn)
    _batch(r, x)
    for idem in (None, "", "   ", "k" * 201):
        _refused(_act(api, f"/contacts/{x}/memos", {"text": "hi"}, rep=r, idem=idem),
                 400, "no_key")
    _ok(_act(api, f"/contacts/{x}/memos", {"text": "hi"}, rep=r, idem="k" * 200))
    assert _memos(owner_conn, x) == 1


def test_an_inactive_rep_s_retry_is_refused_but_do_not_call_s_is_served(api, reps,
                                                                      owner_conn):
    r = reps()
    x, y = _contact(owner_conn), _contact(owner_conn)
    _batch(r, x, y)
    memo = _act(api, f"/contacts/{x}/memos", {"text": "hi"}, rep=r, idem="k3")
    block = _act(api, f"/contacts/{y}/do-not-call", {"reason": "asked"}, rep=r, idem="k4")
    _ok(memo)
    _ok(block)
    _sql(owner_conn, "update partners set status = 'inactive' where id = %s", (r.id,))
    _refused(_act(api, f"/contacts/{x}/memos", {"text": "hi"}, rep=r, idem="k3"),
             403, "rep_inactive")
    again = _act(api, f"/contacts/{y}/do-not-call", {"reason": "asked"}, rep=r, idem="k4")
    assert again.content == block.content
    assert again.headers["Idempotent-Replay"] == "true"


def test_a_refusal_is_asked_again(api, reps, owner_conn):
    r = reps()
    x = _contact(owner_conn)
    refused = _act(api, f"/contacts/{x}/memos", {"text": "hi"}, rep=r, idem="k5")
    assert refused.status_code == 404
    _batch(r, x)
    _ok(_act(api, f"/contacts/{x}/memos", {"text": "hi"}, rep=r, idem="k5"))
    assert _memos(owner_conn, x) == 1


def test_two_at_once_are_one_act(api, reps, owner_conn, owner_url, monkeypatch):
    r = reps()
    x = _contact(owner_conn)
    _batch(r, x)
    holder: dict = {}

    def hook(cur):
        if holder:
            return
        holder["started"] = True
        holder["worker"], holder["out"] = _run(
            lambda: _act(_client(api), f"/contacts/{x}/memos", {"text": "hi"}, rep=r,
                         idem="k6"))
        _wait_until_blocked(owner_url)

    monkeypatch.setattr(calls, "_after_lock", hook)
    first = _act(api, f"/contacts/{x}/memos", {"text": "hi"}, rep=r, idem="k6")
    holder["worker"].join(timeout=10)
    assert not holder["worker"].is_alive()
    second = holder["out"]["value"]
    _ok(first)
    assert second.content == first.content
    assert second.headers["Idempotent-Replay"] == "true"
    assert _memos(owner_conn, x) == 1


def test_a_key_stored_over_90_days_ago_is_asked_again(api, reps, owner_conn):
    r = reps()
    x = _contact(owner_conn)
    _batch(r, x)
    _ok(_act(api, f"/contacts/{x}/memos", {"text": "hi"}, rep=r, idem="k7"))
    _sql(owner_conn, "update api_requests set at = at - interval '91 days'")
    again = _act(api, f"/contacts/{x}/memos", {"text": "hi"}, rep=r, idem="k7")
    _ok(again)
    assert "Idempotent-Replay" not in again.headers
    assert _memos(owner_conn, x) == 2
    assert _count(owner_conn, "select count(*) from api_requests "
                              "where at > now() - interval '1 day'") == 1


def test_the_act_and_its_memory_commit_together(api, reps, owner_conn, monkeypatch):
    r = reps()
    x = _contact(owner_conn)
    _batch(r, x)

    def fail() -> None:
        raise RuntimeError("injected between the act and its memory")

    monkeypatch.setattr(web_api, "_before_memory", fail)
    failed = _act(api, f"/contacts/{x}/memos", {"text": "hi"}, rep=r, idem="k8")
    assert failed.status_code == 500
    assert _memos(owner_conn, x) == 0
    assert _count(owner_conn, "select count(*) from api_requests") == 0
    monkeypatch.undo()
    _ok(_act(api, f"/contacts/{x}/memos", {"text": "hi"}, rep=r, idem="k8"))
    assert _memos(owner_conn, x) == 1


# --- Get more numbers -------------------------------------------------------------


def test_get_more_numbers_keys_are_the_rep_s_and_the_day_s(api, reps, owner_conn,
                                                           monkeypatch):
    a, b, c = reps(), reps(), reps()
    for _ in range(4):
        _contact(owner_conn)
    first_a = _ok(_act(api, "/me/more-numbers", {"region": LA}, rep=a, idem="same"))["result"]
    first_b = _ok(_act(api, "/me/more-numbers", {"region": LA}, rep=b, idem="same"))["result"]
    assert first_a["batch_id"] != first_b["batch_id"]
    assert not first_a["retry"] and not first_b["retry"]
    assert first_a["assigned"] == 4

    early = _ok(_act(api, "/me/more-numbers", {"region": LA}, rep=c, idem="later"))["result"]
    _contact(owner_conn)
    _contact(owner_conn)
    later = _now() + timedelta(days=91)
    monkeypatch.setattr(web_api, "_now", lambda: later)
    again = _act(api, "/me/more-numbers", {"region": LA}, rep=c, idem="later")
    result = _ok(again)["result"]
    assert "Idempotent-Replay" not in again.headers
    assert result["batch_id"] != early["batch_id"]
    assert not result["retry"]
    assert result["assigned"] == 2


def test_get_more_numbers_answers_counts(api, reps, owner_conn):
    a, b = reps(), reps()
    held = _contact(owner_conn)
    _batch(b, held)
    listed = _contact(owner_conn, dnc_registry=True)
    _contact(owner_conn)
    response = _act(api, "/me/more-numbers", {"region": LA}, rep=a)
    result = _ok(response)["result"]
    assert set(result) == {"batch_id", "assigned", "shortfall", "retry"}
    assert result["assigned"] == 1
    assert result["shortfall"]["dnc_registry"] == 1
    assert all(isinstance(v, int) for v in result["shortfall"].values())
    assert str(held) not in response.text and str(listed) not in response.text


# --- errors -----------------------------------------------------------------------


def _contact_routes(contact: str, call_id: UUID) -> list[tuple[str, str, dict | None]]:
    future = (date.today() + timedelta(days=30)).isoformat()
    return [
        ("GET", f"/contacts/{contact}", None),
        ("GET", f"/contacts/{contact}/history", None),
        ("GET", f"/contacts/{contact}/may-call", None),
        ("POST", f"/contacts/{contact}/calls", {"confirm_outside_hours": True}),
        ("POST", f"/contacts/{contact}/outcomes", {"outcome": "spoke"}),
        ("POST", f"/contacts/{contact}/outcomes",
         {"outcome": "no_answer", "call_id": str(call_id)}),
        ("POST", f"/contacts/{contact}/memos", {"text": "hi"}),
        ("POST", f"/contacts/{contact}/zone", {"zone": LA_ZONE}),
        ("POST", f"/contacts/{contact}/move", {"to": "closed"}),
        ("POST", f"/contacts/{contact}/pause", {"until": future}),
        ("POST", f"/contacts/{contact}/unpause", None),
        ("POST", f"/contacts/{contact}/restart", None),
        ("POST", f"/contacts/{contact}/do-not-call", {"reason": "asked"}),
    ]


def _call(api, rep, method, path, body):
    if method == "GET":
        return _get(api, path, rep=rep)
    return _act(api, path, body, rep=rep)


def test_a_contact_never_held_does_not_exist(api, reps, owner_conn):
    a, b = reps(), reps()
    x = _contact(owner_conn)
    _batch(b, x)
    b_call = calls.open_call(b.id, x, _now(), confirm_outside_hours=True).call_id
    for target in (str(x), str(uuid4()), "not-a-uuid"):
        for method, path, body in _contact_routes(target, b_call):
            response = _call(api, a, method, path, body)
            assert response.status_code == 404, (method, path, response.text)
            assert response.json() == NO_CONTACT, (method, path)
    assert _count(owner_conn, "select count(*) from api_requests") == 0


def test_a_refusal_has_one_shape(api, reps, owner_conn):
    r = reps()
    x = _contact(owner_conn)
    _batch(r, x)
    until = (date.today() + timedelta(days=30)).isoformat()
    _ok(_act(api, f"/contacts/{x}/pause", {"until": until}, rep=r))
    body = _refused(_act(api, f"/contacts/{x}/calls", {"confirm_outside_hours": True}, rep=r),
                    409, "paused")
    assert body["detail"] == {"until": until}

    bad_json = api.post(f"/v1/contacts/{x}/memos", content="{not json",
                        headers={**_headers(r, DK, uuid4().hex),
                                 "Content-Type": "application/json"})
    _refused(bad_json, 400, "bad_request")
    _refused(_act(api, f"/contacts/{x}/memos", {}, rep=r), 400, "bad_request")
    _refused(_act(api, f"/contacts/{x}/pause", {"until": "soon"}, rep=r), 400, "bad_request")


def test_a_former_holder_s_open_call_takes_its_outcome(api, reps, owner_conn):
    a, b = reps(), reps()
    x = _contact(owner_conn)
    _batch(a, x)
    call = calls.open_call(a.id, x, _now(), confirm_outside_hours=True).call_id
    _expire_to_house(owner_conn, a, x)
    _claim(owner_conn, b, x)
    _ok(_act(api, f"/contacts/{x}/outcomes", {"outcome": "spoke", "call_id": str(call)},
             rep=a))
    assert _sql(owner_conn, "select outcome from calls where id = %s", (call,)) == [("spoke",)]


def test_a_former_holder_sees_nothing(api, reps, owner_conn):
    a, b = reps(), reps()
    x = _went_back_and_taken(owner_conn, a, b)
    future = (date.today() + timedelta(days=30)).isoformat()
    for method, path, body in [
        ("POST", f"/contacts/{x}/memos", {"text": "hi"}),
        ("POST", f"/contacts/{x}/calls", {"confirm_outside_hours": True}),
        ("POST", f"/contacts/{x}/move", {"to": "got_callback"}),
        ("POST", f"/contacts/{x}/pause", {"until": future}),
        ("POST", f"/contacts/{x}/unpause", None),
        ("POST", f"/contacts/{x}/restart", None),
        ("POST", f"/contacts/{x}/zone", {"zone": LA_ZONE}),
        ("GET", f"/contacts/{x}/may-call", None),
        ("POST", f"/contacts/{x}/outcomes", {"outcome": "spoke"}),
        ("GET", f"/contacts/{x}", None),
        ("GET", f"/contacts/{x}/history", None),
    ]:
        response = _call(api, a, method, path, body)
        assert response.status_code == 404, (method, path, response.text)
        assert response.json() == NO_CONTACT, (method, path)


def test_a_former_holder_s_do_not_call_is_recorded(api, reps, owner_conn):
    a, b = reps(), reps()
    x, y = _contact(owner_conn), _contact(owner_conn)
    _batch(a, x, y)
    _expire_to_house(owner_conn, a, x)
    _claim(owner_conn, b, y)
    assert _ok(_act(api, f"/contacts/{x}/do-not-call", None, rep=a)) == {"result": "blocked"}
    _sql(owner_conn, "update partners set status = 'inactive' where id = %s", (a.id,))
    assert _ok(_act(api, f"/contacts/{y}/do-not-call", None, rep=a)) == {"result": "blocked"}
    assert _count(owner_conn, "select count(*) from dnc_log where rep_id = %s", (a.id,)) == 2


def test_the_edges(api, reps, owner_conn):
    r = reps()
    _refused(_get(api, "/admin/calls/open", key=WK), 403, "no_admin")
    _refused(_get(api, "/admin/calls/open", key=WK, admin="  "), 403, "no_admin")
    _refused(_get(api, "/nowhere", rep=r), 404, "no_route")
    x = _contact(owner_conn)
    _batch(r, x)
    _refused(_get(api, f"/contacts/{x}/memos", rep=r), 405, "no_route")
    _refused(_act(api, "/outcomes/not-a-uuid/undo", {"reason": "oops"}, rep=r),
             400, "bad_request")
    _refused(_act(api, "/admin/calls/not-a-uuid/clear", {"reason": "crashed"}, key=WK,
                  admin="young"), 400, "bad_request")


# --- reads ------------------------------------------------------------------------


def test_reads_take_no_lock(api, reps, owner_conn, owner_url):
    r = reps()
    x = _contact(owner_conn)
    _batch(r, x)
    with psycopg.connect(owner_url) as blocker:
        blocker.execute("select 1 from contacts where id = %s for update", (x,))
        for path in (f"/contacts/{x}", f"/contacts/{x}/may-call"):
            worker, out = _run(lambda path=path: _get(_client(api), path, rep=r))
            worker.join(timeout=5)
            alive = worker.is_alive()
            if alive:
                blocker.rollback()
                worker.join(timeout=10)
            assert not alive, f"{path} waited on the contact's lock"
            assert out["value"].status_code in (200, 409), out["value"].text
        blocker.rollback()


def test_the_card_is_one_moment(api, reps, owner_conn, owner_url, monkeypatch):
    r = reps()
    x = _contact(owner_conn)
    _batch(r, x)

    def commit_meanwhile() -> None:
        with psycopg.connect(owner_url) as other:
            other.execute("insert into memos (contact_id, rep_id, text, at) "
                          "values (%s, %s, 'meanwhile', now())", (x, r.id))
            other.execute("insert into calls (contact_id, rep_id, outcome, outcome_at) "
                          "values (%s, %s, 'spoke', now())", (x, r.id))

    monkeypatch.setattr(reads, "_after_first_read", commit_meanwhile)
    card = _ok(_get(api, f"/contacts/{x}", rep=r))
    assert card["latest_memo"] is None
    assert card["last_call"] is None
    monkeypatch.undo()
    card = _ok(_get(api, f"/contacts/{x}", rep=r))
    assert card["latest_memo"]["text"] == "meanwhile"
    assert card["last_call"]["outcome"] == "spoke"


CARD_FIELDS = {
    "id", "business", "contact_name", "phone", "city", "state", "trade", "whose", "list",
    "reason", "calls", "voicemails", "limits", "due", "rest_until", "pause_until",
    "may_call", "zones", "local_times", "inside", "dnc_status", "goes_back_on",
    "latest_memo", "last_call", "undoable", "vouched",
}


def _at(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def test_the_card(api, reps, owner_conn, monkeypatch):
    at = _inside_at()
    monkeypatch.setattr(web_api, "_now", lambda: at)
    r = reps()
    x = _contact(owner_conn, business="Reseda Rooter", name="Ann Lee")
    batch = _batch(r, x)
    memo_at = at - timedelta(minutes=5)
    calls.add_memo(r.id, x, "call after lunch", memo_at)

    card = _ok(_get(api, f"/contacts/{x}", rep=r))
    assert set(card) == CARD_FIELDS
    assert card["id"] == str(x)
    assert (card["business"], card["contact_name"], card["phone"]) == (
        "Reseda Rooter", "Ann Lee", _phone(owner_conn, x))
    assert (card["city"], card["state"], card["trade"]) == ("Reseda", "CA", "plumber")
    assert card["whose"] == "nmc"
    assert (card["list"], card["reason"], card["calls"], card["voicemails"]) == (
        "never_called", None, 0, 0)
    assert card["limits"] == {"voicemails": 2, "calls": 5}
    assert (card["due"], card["rest_until"], card["pause_until"]) == (None, None, None)
    assert card["may_call"] == {"yes": True}
    hours = zones.calling_hours(x, at)
    assert card["zones"] == sorted(hours.zones) == [LA_ZONE]
    assert {z: _at(t) for z, t in card["local_times"].items()} == hours.local
    assert card["inside"] is True
    assert card["dnc_status"] == "clear"
    expires = _sql(owner_conn, "select expires_at from assignment_batches where id = %s",
                   (batch.batch_id,))[0][0]
    assert _at(card["goes_back_on"]) == expires
    assert card["latest_memo"]["text"] == "call after lunch"
    assert _at(card["latest_memo"]["at"]) == memo_at
    assert (card["last_call"], card["undoable"]) == (None, [])

    _ok(_act(api, f"/contacts/{x}/pause",
             {"until": (at.date() + timedelta(days=10)).isoformat()}, rep=r))
    card = _ok(_get(api, f"/contacts/{x}", rep=r))
    assert card["may_call"]["yes"] is False
    assert card["may_call"]["code"] == "paused"

    own = _own(r, "+18185559901", business_name="Own Plumbing", trade="hvac")
    card = _ok(_get(api, f"/contacts/{own}", rep=r))
    assert (card["whose"], card["business"], card["trade"]) == ("own", "Own Plumbing", "hvac")
    assert card["goes_back_on"] is None


def _goes_back_on(api, rep, contact) -> datetime | None:
    return _at(_ok(_get(api, f"/contacts/{contact}", rep=rep))["goes_back_on"])


def test_the_card_s_goes_back_on_is_the_expiry_s(api, reps, owner_conn):
    r = reps()
    claimed = _contact(owner_conn)
    _claim(owner_conn, r, claimed)
    assigned_at = _sql(owner_conn, "select max(occurred_at) from events where contact_id = %s "
                                   "and type = 'contact.assigned'", (claimed,))[0][0]
    assert _goes_back_on(api, r, claimed) == assigned_at + timedelta(
        days=ASSIGNMENT_EXPIRY_DAYS)

    sold, callback, follow_up, blocked, rep_closed = (_contact(owner_conn) for _ in range(5))
    _batch(r, sold, callback, follow_up, blocked, rep_closed)
    outcome = _ok(_act(api, f"/contacts/{sold}/outcomes", {"outcome": "signed_up"},
                       rep=r))["result"]
    for c in (callback, blocked, rep_closed):
        _ok(_act(api, f"/contacts/{c}/move", {"to": "got_callback"}, rep=r))
    _ok(_act(api, f"/contacts/{follow_up}/outcomes", {"outcome": "follow_up"}, rep=r))
    _ok(_act(api, f"/contacts/{blocked}/do-not-call", None, rep=r))
    _ok(_act(api, f"/contacts/{rep_closed}/move", {"to": "closed"}, rep=r))

    assert _goes_back_on(api, r, sold) is None
    assert _goes_back_on(api, r, callback) is None
    assert _goes_back_on(api, r, follow_up) is None
    assert _goes_back_on(api, r, blocked) is not None
    assert _goes_back_on(api, r, rep_closed) is not None
    card = _ok(_get(api, f"/contacts/{sold}", rep=r))
    assert card["undoable"] == [outcome]
    assert card["last_call"]["outcome"] == "signed_up"

    _sql(owner_conn, "update assignment_batches set expires_at = now() - interval '1 day' "
                     "where partner_id = %s", (r.id,))
    run_expiry_step()
    kept = {c for c in (sold, callback, follow_up, blocked, rep_closed)
            if _owner(owner_conn, c) == r.id}
    assert kept == {sold, callback, follow_up}


def test_history(api, reps, owner_conn):
    a, b = reps(), reps()
    x = _contact(owner_conn)
    _batch(a, x)
    calls.add_memo(a.id, x, "a's memo", _now())
    call = calls.open_call(a.id, x, _now(), confirm_outside_hours=True).call_id
    calls.record_outcome(a.id, x, "no_answer", _now(), call_id=call)
    _expire_to_house(owner_conn, a, x)
    _claim(owner_conn, b, x)
    calls.add_memo(b.id, x, "b's memo", _now())

    response = _get(api, f"/contacts/{x}/history", rep=b)
    entries = _ok(response)["entries"]
    assert [(e["kind"], e["by_you"]) for e in entries] == [
        ("memo", True), ("call", False), ("memo", False)]
    assert entries[1]["outcome"] == "no_answer" and entries[2]["text"] == "a's memo"
    assert str(a.id) not in response.text and a.name not in response.text
    assert str(a.sid) not in response.text

    own = _own(a, "+18185559902")
    calls.add_memo(a.id, own, "a's own memo", _now())
    with transaction() as conn, conn.cursor() as cur:
        set_owner(cur, own, b.id, event_type="contact.reclaimed", reason="test",
                  actor="young")
    calls.add_memo(b.id, own, "b's memo on a's own", _now())
    entries = _ok(_get(api, f"/contacts/{own}/history", rep=b))["entries"]
    assert [(e["text"], e["by_you"]) for e in entries] == [("b's memo on a's own", True)]
    assert _ok(_get(api, f"/contacts/{own}", rep=b))["latest_memo"]["text"] == (
        "b's memo on a's own")


def test_lists(api, reps, owner_conn):
    r = reps()
    x = _contact(owner_conn, business="Reseda Rooter", name="Ann Lee")
    _batch(r, x)
    received = _ok(_act(api, "/calls-received", {"phone": _phone(owner_conn, x)},
                        rep=r))["result"]
    lists = _ok(_get(api, "/me/lists", rep=r))
    assert set(lists) == {"contacts", "calls_received"}
    [entry] = lists["contacts"]
    assert entry == {
        "id": str(x), "business": "Reseda Rooter", "contact_name": "Ann Lee",
        "phone": _phone(owner_conn, x), "list": "never_called", "reason": None,
        "due": None, "rest_until": None, "pause_until": None,
        "whose": "nmc", "vouched": False,
    }
    [call] = lists["calls_received"]
    assert set(call) == {"id", "contact_id", "business", "phone", "received_at"}
    assert (call["id"], call["contact_id"], call["business"], call["phone"]) == (
        received, str(x), "Reseda Rooter", _phone(owner_conn, x))


def test_known_callers(api, reps, owner_conn):
    a, b = reps(), reps()
    once = _went_back_and_taken(owner_conn, a, b)
    now = _contact(owner_conn)
    _batch(a, now)
    never = _contact(owner_conn)
    _batch(b, never)
    known = _ok(_get(api, "/me/known-callers", rep=a))["contacts"]
    assert {c["id"] for c in known} == {str(once), str(now)}
    assert all(set(c) == {"id", "phone", "business", "contact_name"} for c in known)


def test_search(api, reps, owner_conn):
    a, b = reps(), reps()
    rooter = _contact(owner_conn, business="Reseda ROOTER", phone="+18185551234")
    drain = _contact(owner_conn, business="Van Nuys Drain", phone="+18185559876")
    theirs = _contact(owner_conn, business="Rooter Bros", phone="+18185551235")
    _batch(a, rooter, drain)
    _batch(b, theirs)

    def found(q: str) -> set[str]:
        return {c["id"] for c in _ok(_get(api, "/me/search", rep=a, params={"q": q}))[
            "contacts"]}

    assert found("rooter") == {str(rooter)}
    assert found("9876") == {str(drain)}
    assert found("1235") == set()
    assert found("%%") == set()
    assert found("__") == set()
    _refused(_get(api, "/me/search", rep=a, params={"q": "r"}), 400, "bad_request")

    many = [_contact(owner_conn, business=f"Bulk Plumbing {i}") for i in range(55)]
    _batch(a, *many)
    assert len(found("bulk")) == 50


# --- every route ------------------------------------------------------------------


def test_every_route(api, reps, owner_conn, monkeypatch):
    at = _inside_at()
    monkeypatch.setattr(web_api, "_now", lambda: at)
    r = reps()
    x, y, z, w, v = (_contact(owner_conn) for _ in range(5))
    _batch(r, x, y, z, w, v)
    admin = {"key": WK, "admin": "young"}

    assert set(_ok(_get(api, "/regions", rep=r))["regions"]) == {
        LA, "San Diego", "Northern CA"}
    assert _ok(_get(api, "/me/settings", rep=r)) == {
        "voicemails": 2, "calls": 5, "days_between": 3, "rest_months": 3}
    _ok(_act(api, "/me/settings", {"voicemails": 3, "calls": 8, "days_between": 7,
                                   "rest_months": 6}, rep=r, key=WK, method="PUT"))
    assert rule.get_settings(r.id).calls == 8
    assert _ok(_act(api, "/me/settings/restore", rep=r, key=WK)) == {"result": "restored"}
    assert rule.get_settings(r.id).calls == 5

    added = _ok(_act(api, "/contacts", {
        "rows": [{"phone": "8185559903", "business_name": "Fresh Pipes"}],
        "how_obtained": "referral", "confirmation": CONFIRMATION}, rep=r))["result"]
    assert [(row["phone"], row["result"]) for row in added] == [("+18185559903", "added")]

    assert _ok(_get(api, f"/contacts/{x}/may-call", rep=r)) == {"yes": True}
    opened = _ok(_act(api, f"/contacts/{x}/calls", {"confirm_outside_hours": False},
                      rep=r))["result"]
    assert opened["phone"] == _phone(owner_conn, x)
    _ok(_act(api, f"/contacts/{x}/outcomes",
             {"outcome": "left_voicemail", "call_id": opened["call_id"], "memo": "vm"}, rep=r))
    assert _sql(owner_conn, "select outcome from calls where id = %s",
                (opened["call_id"],)) == [("left_voicemail",)]

    wrong = _ok(_act(api, f"/contacts/{y}/outcomes", {"outcome": "wrong_number"},
                     rep=r))["result"]
    assert _ok(_act(api, f"/outcomes/{wrong}/undo", {"reason": "misdial"}, rep=r)) == {
        "result": "undone"}
    _ok(_act(api, f"/contacts/{x}/memos", {"text": "nice"}, rep=r))
    assert _ok(_act(api, f"/contacts/{x}/zone", {"zone": "America/Denver"}, rep=r)) == {
        "result": "set"}
    assert _ok(_act(api, f"/contacts/{z}/move", {"to": "got_callback"}, rep=r)) == {
        "result": "moved"}
    until = (at.date() + timedelta(days=10)).isoformat()
    assert _ok(_act(api, f"/contacts/{w}/pause", {"until": until}, rep=r)) == {
        "result": "paused"}
    assert _ok(_act(api, f"/contacts/{w}/unpause", None, rep=r)) == {"result": "unpaused"}
    _sql(owner_conn, "insert into contact_state (contact_id, calls, last_call_at, updated_at) "
                     "values (%s, 5, now() - interval '200 days', now())", (v,))
    assert _ok(_act(api, f"/contacts/{v}/restart", None, rep=r)) == {"result": "restarted"}

    received = _ok(_act(api, "/calls-received", {"phone": _phone(owner_conn, z)},
                        rep=r))["result"]
    assert _ok(_act(api, f"/calls-received/{received}/resolve", {"resolution": "dismiss"},
                    rep=r)) == {"result": "resolved"}

    left = _ok(_act(api, f"/contacts/{w}/calls", {"confirm_outside_hours": True},
                    rep=r))["result"]
    open_calls = _ok(_get(api, "/admin/calls/open", **admin))["calls"]
    assert [(c["id"], c["phone"], c["rep"]) for c in open_calls] == [
        (left["call_id"], _phone(owner_conn, w), r.name)]
    assert _ok(_act(api, f"/admin/calls/{left['call_id']}/clear", {"reason": "crashed"},
                    **admin)) == {"result": "cleared"}

    assert _ok(_act(api, "/admin/do-not-call", {"phone": "8185550999", "reason": "asked"},
                    **admin)) == {"result": "blocked"}
    entries = _ok(_get(api, "/admin/do-not-call/8185550999", **admin))["entries"]
    assert [e["kind"] for e in entries] == ["admin"]
    assert _ok(_act(api, "/admin/do-not-call/8185550999/lift",
                    {"seen": entries[-1]["seq"], "reason": "entered by mistake"},
                    **admin)) == {"result": "lifted"}
    assert _ok(_act(api, f"/admin/contacts/{y}/zone", {"zone": LA_ZONE}, **admin)) == {
        "result": "set"}
    assert _ok(_act(api, f"/contacts/{y}/do-not-call", {"reason": "asked"}, rep=r)) == {
        "result": "blocked"}

    _ok(_get(api, "/me/lists", rep=r))
    _ok(_get(api, "/me/known-callers", rep=r))
    _ok(_get(api, "/me/search", rep=r, params={"q": "business"}))
    _ok(_get(api, f"/contacts/{x}", rep=r))
    _ok(_get(api, f"/contacts/{x}/history", rep=r))
    _ok(_act(api, "/me/more-numbers", {"region": "San Diego"}, rep=r))

    held = _count(owner_conn, "select count(*) from contacts where owner_id = %s", (r.id,))
    assert _ok(_act(api, f"/admin/reps/{r.sid}/reclaim", {"reason": "done"}, **admin)) == {
        "result": held}
    _refused(_act(api, f"/admin/reps/{next(_sids)}/reclaim", {"reason": "done"}, **admin),
             404, "unknown_rep")
