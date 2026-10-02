"""Smoke — one rep's journey through the running API, over HTTP.

Make a rep known → regions, settings → hold numbers (Get more numbers when the rep
holds none callable) → card, may-call → open a call (with the rep's confirmation when
outside 9 AM–7 PM) → outcome, resent with the same key → memo → history → card again
→ "don't call me again" on another contact → refused → the admin's history of it →
known callers, search, a contact never held → status.

Talks to whatever API `CONTACT_ENGINE_URL` names (default http://127.0.0.1:8002, the
`make api` port) — so it writes to THAT database: a test rep (`SMOKE_REP_ID`, default
900001), its batch, one call and its memos, one blocked number per run. Meant for
`mailengine_dev`, which is test-only. Never point it at production.

Skips, with the reason, when the API does not answer or the keys are not set; fails
when the API answers in a shape the contract (06a, 06b) does not allow. Marked
`smoke`: deselected by default; run with `make smoke` while `make api` runs.
"""

import os
import uuid
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.smoke

BASE = os.environ.get("CONTACT_ENGINE_URL", "http://127.0.0.1:8002")
DIALER = os.environ.get("CE_DIALER_KEY", "")
WEBSITE = os.environ.get("CE_WEBSITE_KEY", "")
REP = os.environ.get("SMOKE_REP_ID", "900001")
REGION = "LA area"
CARD_LOOKS = 25
NO_CONTACT = {"code": "no_contact", "message": "no such contact", "detail": {}}


@pytest.fixture(scope="module")
def api() -> httpx.Client:
    if not DIALER or not WEBSITE:
        pytest.skip("CE_DIALER_KEY / CE_WEBSITE_KEY not set — see .env")
    client = httpx.Client(base_url=BASE, timeout=60)
    try:
        health = client.get("/health")
    except httpx.TransportError as err:
        pytest.skip(f"contact-engine not reachable at {BASE} ({err!r}) — start it with make api")
    assert health.status_code == 200 and health.json() == {"ok": True}, health.text
    return client


def _call(api: httpx.Client, method: str, path: str, body: Any = None, *,
          key: str = DIALER, rep: str | None = REP, admin: str | None = None,
          idem: str | None = None) -> httpx.Response:
    headers = {"X-API-Key": key}
    if rep is not None:
        headers["X-Rep"] = rep
    if admin is not None:
        headers["X-Admin"] = admin
    if method in ("POST", "PUT"):
        headers["Idempotency-Key"] = idem or str(uuid.uuid4())
    return api.request(method, path, json=body, headers=headers)


def _callable_now(card: dict[str, Any]) -> bool:
    may = card["may_call"]
    return may["yes"] or may["code"] == "outside_hours"


def _pick(api: httpx.Client) -> tuple[dict[str, Any], dict[str, Any]]:
    """A held contact that may be called now (outside hours counts), and another
    never-called one to block."""
    for attempt in range(2):
        held = _call(api, "GET", "/v1/me/lists").json()["contacts"]
        fresh = [c for c in held if c["list"] == "never_called"]
        target = None
        for c in fresh[:CARD_LOOKS]:
            card = _call(api, "GET", f"/v1/contacts/{c['id']}").json()
            if _callable_now(card):
                target = card
                break
        other = next((c for c in fresh if target and c["id"] != target["id"]), None)
        if target and other:
            return target, other
        assert attempt == 0, f"no callable contact after Get more numbers: {len(fresh)} fresh"
        got = _call(api, "POST", "/v1/me/more-numbers", {"region": REGION})
        assert got.status_code == 200, got.text
        assert got.json()["result"]["assigned"] > 0, got.text
    raise AssertionError("unreachable")


def test_rep_journey(api: httpx.Client) -> None:
    known = _call(api, "PUT", f"/v1/reps/{REP}", {"name": f"Smoke Test Rep {REP}"}, rep=None)
    assert known.status_code == 200 and known.json() == {"result": "known"}, known.text

    regions = _call(api, "GET", "/v1/regions")
    assert regions.status_code == 200 and REGION in regions.json()["regions"], regions.text

    settings = _call(api, "GET", "/v1/me/settings")
    assert settings.status_code == 200, settings.text
    assert set(settings.json()) == {"voicemails", "calls", "days_between", "rest_months"}

    card, other = _pick(api)
    cid = card["id"]
    assert card["dnc_status"] == "clear", card
    assert card["whose"] == "nmc" and card["list"] == "never_called", card
    assert card["phone"].startswith("+1"), card

    inside = card["inside"]
    may = _call(api, "GET", f"/v1/contacts/{cid}/may-call")
    if inside:
        assert may.status_code == 200 and may.json() == {"yes": True}, may.text
    else:
        assert may.status_code == 409 and may.json()["code"] == "outside_hours", may.text
        refused = _call(api, "POST", f"/v1/contacts/{cid}/calls", {"confirm_outside_hours": False})
        assert refused.status_code == 409 and refused.json()["code"] == "outside_hours", refused.text

    opened = _call(api, "POST", f"/v1/contacts/{cid}/calls", {"confirm_outside_hours": not inside})
    assert opened.status_code == 200, opened.text
    call_id = opened.json()["result"]["call_id"]
    assert opened.json()["result"]["phone"] == card["phone"]

    busy = _call(api, "GET", f"/v1/contacts/{cid}/may-call")
    assert busy.status_code == 409 and busy.json()["code"] == "call_open", busy.text
    assert busy.json()["detail"]["call_id"] == call_id

    key = str(uuid.uuid4())
    outcome = {"outcome": "no_answer", "call_id": call_id, "memo": "smoke: rang out"}
    first = _call(api, "POST", f"/v1/contacts/{cid}/outcomes", outcome, idem=key)
    assert first.status_code == 200 and first.json() == {"result": call_id}, first.text
    again = _call(api, "POST", f"/v1/contacts/{cid}/outcomes", outcome, idem=key)
    assert again.status_code == 200 and again.content == first.content, again.text
    assert again.headers.get("Idempotent-Replay") == "true", dict(again.headers)

    memo = _call(api, "POST", f"/v1/contacts/{cid}/memos", {"text": "smoke: try again later"})
    assert memo.status_code == 200, memo.text

    history = _call(api, "GET", f"/v1/contacts/{cid}/history").json()["entries"]
    calls = [e for e in history if e["kind"] == "call"]
    memos = [e for e in history if e["kind"] == "memo"]
    assert [(c["outcome"], c["by_you"]) for c in calls] == [("no_answer", True)], history
    assert {m["text"] for m in memos} == {"smoke: rang out", "smoke: try again later"}, history

    after = _call(api, "GET", f"/v1/contacts/{cid}").json()
    assert after["calls"] == 1 and after["list"] == "waiting", after
    assert after["last_call"]["outcome"] == "no_answer", after
    assert after["may_call"] == {"yes": False, "code": "not_due", "detail": {"due": after["due"]}}

    oid = other["id"]
    blocked = _call(api, "POST", f"/v1/contacts/{oid}/do-not-call", {"reason": "smoke: asked"})
    assert blocked.status_code == 200 and blocked.json() == {"result": "blocked"}, blocked.text
    for method, path in (("GET", f"/v1/contacts/{oid}/may-call"), ("POST", f"/v1/contacts/{oid}/calls")):
        refused = _call(api, method, path)
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "not_callable", refused.text
        assert refused.json()["detail"]["status"] == "do_not_call", refused.text

    log = _call(api, "GET", f"/v1/admin/do-not-call/{other['phone']}",
                key=WEBSITE, rep=None, admin="smoke-admin")
    assert log.status_code == 200, log.text
    assert any(e["reason"] == "smoke: asked" for e in log.json()["entries"]), log.text

    callers = _call(api, "GET", "/v1/me/known-callers").json()["contacts"]
    assert {cid, oid} <= {c["id"] for c in callers}

    search = _call(api, "GET", f"/v1/me/search?q={card['phone'][-4:]}")
    assert search.status_code == 200, search.text
    assert cid in {c["id"] for c in search.json()["contacts"]}, search.text

    stranger = _call(api, "GET", f"/v1/contacts/{uuid.uuid4()}")
    assert stranger.status_code == 404 and stranger.json() == NO_CONTACT, stranger.text

    status = _call(api, "GET", "/v1/status", key=WEBSITE, rep=None)
    assert status.status_code == 200, status.text
    assert {"daily_run", "scrub", "dnc_checks_expiring", "calls_open_over_24h", "alerts"} <= set(status.json())
    wrong = _call(api, "GET", "/v1/status", key=DIALER, rep=None)
    assert wrong.status_code == 403 and wrong.json()["code"] == "wrong_key", wrong.text
