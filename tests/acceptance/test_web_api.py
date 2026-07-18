"""Phase 5 gate: the thin FastAPI window. Every view maps to one query verb, the
approval flow carries the preview hash, and the execution verbs are unreachable over
HTTP — except the one decided exception, the DROP_PASSWORD-gated /drops/run trigger
for the run_drops job (2026-07-12). Driven in-process via FastAPI's TestClient."""

import warnings
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from seams.fakes import FakePrintApi
from service.waves import create_variant, draft_wave

warnings.simplefilter("ignore")  # starlette testclient httpx deprecation noise

from web.api import _proof_client, app  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fake_proof_client():
    """The approve screen renders Lob proofs; a real render would hit the network.
    Default every web test to a fake proof client so none makes a vendor call."""
    app.dependency_overrides[_proof_client] = lambda: FakePrintApi()
    yield
    app.dependency_overrides.clear()


def _future():
    return datetime.now(UTC).date() + timedelta(days=5)


def _seed_prospects(conn, n) -> list[UUID]:
    ids = []
    with conn.cursor() as cur:
        for _ in range(n):
            cur.execute("insert into contacts (trade) values ('plumber') returning id")
            row = cur.fetchone()
            assert row is not None
            ids.append(row[0])
    conn.commit()
    return ids


def _draft(conn, n) -> UUID:
    _seed_prospects(conn, n)
    variant_id = create_variant("v", "h", {})
    return draft_wave("w", 1, {"trade": ["plumber"]}, {str(variant_id): 1}, _future())


# --- one view, one verb --------------------------------------------------------


def test_api_pipeline_returns_the_pipeline_verb(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        cur.execute(
            "insert into contacts (trade, stage_snapshot) values ('plumber', 'responded') returning id"
        )
        contact_id = cur.fetchone()[0]
    owner_conn.commit()

    response = client.get("/api/pipeline")
    assert response.status_code == 200
    body = response.json()
    assert [c["id"] for c in body] == [str(contact_id)]


def test_ui_pipeline_renders_html(clean_db, owner_conn):
    response = client.get("/pipeline")
    assert response.status_code == 200
    assert "Pipeline" in response.text


def test_home_redirects_to_waves(clean_db):
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (307, 308)
    assert response.headers["location"] == "/waves"


# --- execution verbs are not routed --------------------------------------------


def test_execution_verbs_have_no_http_route(clean_db):
    assert client.post(f"/api/waves/{uuid4()}/execute").status_code == 404
    assert client.post("/api/recompute").status_code == 404
    assert client.get("/api/waves/drop").status_code == 404


# --- run-drops button: the password-gated exception to job-only execution -------


def test_run_drops_fails_closed_without_password_env(clean_db, monkeypatch):
    monkeypatch.delenv("DROP_PASSWORD", raising=False)
    page = client.get("/drops")
    assert page.status_code == 200
    assert "Disabled" in page.text

    response = client.post("/drops/run", data={"password": "x", "as_of": str(_future())})
    assert response.status_code == 503


def test_run_drops_rejects_wrong_password(clean_db, monkeypatch):
    monkeypatch.setenv("DROP_PASSWORD", "sekret")
    response = client.post(
        "/drops/run", data={"password": "wrong", "as_of": str(_future())}
    )
    assert response.status_code == 401


def test_run_drops_runs_the_job_with_correct_password(clean_db, monkeypatch):
    monkeypatch.setenv("DROP_PASSWORD", "sekret")
    seen = {}

    def fake_run_drops(api, as_of):
        seen["as_of"] = as_of
        return []

    monkeypatch.setattr("web.api.run_drops", fake_run_drops)
    response = client.post(
        "/drops/run", data={"password": "sekret", "as_of": str(_future())}
    )
    assert response.status_code == 200
    assert seen["as_of"] == _future()
    assert "No approved waves due" in response.text


# --- approval flow: preview hash carried into approve --------------------------


def test_preview_then_approve_with_hash(clean_db, owner_conn):
    wave_id = _draft(owner_conn, 3)

    preview = client.get(f"/api/waves/{wave_id}/preview")
    assert preview.status_code == 200
    assert preview.json()["count"] == 3
    state_hash = preview.json()["state_hash"]

    approve = client.post(f"/api/waves/{wave_id}/approve", params={"state_hash": state_hash})
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"


def test_approve_route_rejects_a_stale_hash(clean_db, owner_conn):
    wave_id = _draft(owner_conn, 3)
    state_hash = client.get(f"/api/waves/{wave_id}/preview").json()["state_hash"]
    _seed_prospects(owner_conn, 2)  # drift after preview

    approve = client.post(f"/api/waves/{wave_id}/approve", params={"state_hash": state_hash})
    assert approve.status_code == 409
    assert approve.json()["code"] == "stale_preview"


def test_ui_approve_screen_renders_preview_and_hash(clean_db, owner_conn):
    wave_id = _draft(owner_conn, 3)
    response = client.get(f"/waves/{wave_id}/approve")
    assert response.status_code == 200
    assert "Approve this wave" in response.text
    assert "state_hash=" in response.text  # the form carries the hash back


def test_approve_screen_embeds_a_proof_per_variant(clean_db, owner_conn):
    _seed_prospects(owner_conn, 2)
    v1 = create_variant("A", "hA", {"front": "fa", "back": "ba"})
    wave_id = draft_wave("w2", 1, {"trade": ["plumber"]}, {str(v1): 1.0}, _future())
    r = client.get(f"/waves/{wave_id}/approve")
    assert r.status_code == 200
    assert "lob.test/proof" in r.text  # the fake proof url is embedded (autouse fake client)


# --- v1 window: wave composition -----------------------------------------------


def test_ui_waves_lists_every_status(clean_db, owner_conn):
    _draft(owner_conn, 1)
    response = client.get("/waves")
    assert response.status_code == 200
    assert "draft" in response.text


def test_ui_waves_shows_dropped_label_and_executed_at(clean_db, owner_conn):
    wave_id = _draft(owner_conn, 1)
    with owner_conn.cursor() as cur:
        cur.execute(
            "update waves set status = 'sent', "
            "executed_at = '2026-07-12T11:38:00-07:00' where id = %s",
            (wave_id,),
        )
    owner_conn.commit()

    response = client.get("/waves")
    assert response.status_code == 200
    assert "dropped" in response.text  # 'sent' rendered as the operator's word
    assert "2026-07-12 11:38" in response.text


def test_ui_new_wave_form_drafts_and_redirects_to_preview(clean_db, owner_conn):
    _seed_prospects(owner_conn, 2)
    variant_id = create_variant("v", "h", {})

    response = client.post(
        "/waves/new",
        data={
            "name": "form-wave",
            "drop_number": "1",
            "scheduled_for": str(_future()),
            "audience_rule": '{"trade": ["plumber"]}',
            "variant_split": f'{{"{variant_id}": 1}}',
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith("/approve")

    approve_page = client.get(response.headers["location"])
    assert approve_page.status_code == 200
    assert "Approve this wave" in approve_page.text


def test_ui_new_wave_rejects_bad_json(clean_db):
    response = client.post(
        "/waves/new",
        data={"name": "w", "drop_number": "1", "audience_rule": "not json"},
        follow_redirects=False,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "bad_json"


def test_ui_edit_form_prefills_and_updates_a_draft(clean_db, owner_conn):
    wave_id = _draft(owner_conn, 2)

    form = client.get(f"/waves/{wave_id}/edit")
    assert form.status_code == 200
    assert 'value="w"' in form.text  # prefilled from the stored draft
    assert '"plumber"' in form.text

    response = client.post(
        f"/waves/{wave_id}/edit",
        data={
            "name": "w edited",
            "drop_number": "2",
            "scheduled_for": str(_future()),
            "audience_rule": '{"trade": ["plumber"], "limit": 1}',
            "variant_split": "{}",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith("/approve")

    with owner_conn.cursor() as cur:
        cur.execute("select name, drop_number from waves where id = %s", (wave_id,))
        assert cur.fetchone() == ("w edited", 2)


def test_api_update_rejects_non_draft(clean_db, owner_conn):
    wave_id = _draft(owner_conn, 2)
    state_hash = client.get(f"/api/waves/{wave_id}/preview").json()["state_hash"]
    client.post(f"/api/waves/{wave_id}/approve", params={"state_hash": state_hash})

    response = client.post(
        f"/api/waves/{wave_id}/update",
        json={"name": "w2", "drop_number": 1},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "not_draft"


def test_cancel_wave_route_and_too_late_guard(clean_db, owner_conn):
    wave_id = _draft(owner_conn, 1)
    response = client.post(f"/waves/{wave_id}/cancel", follow_redirects=False)
    assert response.status_code == 303

    with owner_conn.cursor() as cur:
        cur.execute("update waves set status = 'sent' where id = %s", (wave_id,))
    owner_conn.commit()
    assert client.post(f"/api/waves/{wave_id}/cancel").status_code == 409


# --- v1 window: variants ---------------------------------------------------------


def test_ui_variants_create_and_list(clean_db):
    response = client.post(
        "/variants",
        data={"name": "big-headline", "hypothesis": "bold beats subtle", "creative": "{}"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    page = client.get("/variants")
    assert page.status_code == 200
    assert "bold beats subtle" in page.text


def test_creatives_gallery_renders_every_variant(clean_db):
    a = create_variant("gal-a", "h1", {"front": "<html>A</html>", "back": "", "size": "6x9"})
    b = create_variant("gal-b", "h2", {"front": "<html>B</html>", "back": ""})

    page = client.get("/creatives")
    assert page.status_code == 200
    assert "gal-a" in page.text and "gal-b" in page.text
    assert f"/variants/{a}/creative/front" in page.text
    assert f"/variants/{b}/preview" in page.text
    assert "sandbox" in page.text


def test_variant_preview_page_isolates_creative_in_sandboxed_iframes(clean_db):
    variant_id = create_variant(
        "v6x9", "big cards draw", {
            "front": "<html><body><h1>FRONT</h1></body></html>",
            "back": "<html><body>getnevermisscall.com/?r={{mailer_code}}</body></html>",
            "size": "6x9",
        },
    )

    preview = client.get(f"/variants/{variant_id}/preview")
    assert preview.status_code == 200
    assert "sandbox" in preview.text
    assert f"/variants/{variant_id}/creative/front" in preview.text
    assert f"/variants/{variant_id}/creative/back" in preview.text

    raw = client.get(f"/variants/{variant_id}/creative/back")
    assert raw.status_code == 200
    assert "?r=SAMPLE7X29Q" in raw.text  # sample code, never a live piece's
    assert "{{mailer_code}}" not in raw.text

    assert client.get(f"/variants/{variant_id}/creative/left").status_code == 409
    assert client.get(f"/variants/{uuid4()}/preview").status_code == 409


def test_api_variant_requires_hypothesis(clean_db):
    response = client.post(
        "/api/variants", json={"name": "v", "hypothesis": "  ", "creative": {}}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "empty_hypothesis"


# --- v1 window: contact search + actions ----------------------------------------


def test_ui_contacts_search(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        cur.execute(
            "insert into contacts (trade, business_name) values ('plumber', 'Acme Plumbing')"
        )
        cur.execute(
            "insert into contacts (trade, business_name) values ('plumber', 'Other Corp')"
        )
    owner_conn.commit()

    page = client.get("/contacts", params={"q": "acme"})
    assert page.status_code == 200
    assert "Acme Plumbing" in page.text
    assert "Other Corp" not in page.text


def test_contact_note_and_next_action_and_lost_routes(clean_db, owner_conn):
    (contact_id,) = _seed_prospects(owner_conn, 1)

    note = client.post(
        f"/contacts/{contact_id}/note",
        data={"note_type": "note.general", "text": "spoke at the counter"},
        follow_redirects=False,
    )
    assert note.status_code == 303

    action = client.post(
        f"/contacts/{contact_id}/next-action",
        data={"action_date": "2026-08-01", "note": "call back"},
        follow_redirects=False,
    )
    assert action.status_code == 303

    lost = client.post(
        f"/contacts/{contact_id}/lost", data={"reason": "went dark"}, follow_redirects=False
    )
    assert lost.status_code == 303

    timeline = client.get(f"/api/contacts/{contact_id}/timeline").json()
    assert [e["type"] for e in timeline] == ["note.general", "contact.lost"]

    with owner_conn.cursor() as cur:
        cur.execute(
            "select next_action_at, next_action_note from contacts where id = %s",
            (contact_id,),
        )
        row = cur.fetchone()
    assert str(row[0]) == "2026-08-01" and row[1] == "call back"


def test_contact_suppress_route_sets_flags(clean_db, owner_conn):
    (contact_id,) = _seed_prospects(owner_conn, 1)

    response = client.post(
        f"/contacts/{contact_id}/suppress", data={"reason": "opt_out"}, follow_redirects=False
    )
    assert response.status_code == 303

    with owner_conn.cursor() as cur:
        cur.execute(
            "select do_not_mail, do_not_text from contacts where id = %s", (contact_id,)
        )
        assert cur.fetchone() == (True, True)


# --- v1 window: intake, orphans, nudges ------------------------------------------


def test_intake_upload_loads_list_and_renders_report(clean_db):
    csv_bytes = (
        b"trade,business_name,phone,list_key\n"
        b"plumber,Acme Plumbing,3105551212,cslb-L100\n"
        b",No Trade Co,3105550000,cslb-L200\n"
    )
    response = client.post(
        "/intake",
        files={"file": ("list.csv", csv_bytes, "text/csv")},
        data={"source": "cslb"},
    )
    assert response.status_code == 200
    assert "loaded 1" in response.text
    assert "invalid 1" in response.text

    found = client.get("/api/contacts", params={"q": "acme"}).json()
    assert len(found) == 1
    assert found[0]["phone_e164"] == "+13105551212"


def test_orphans_page_and_resolve_route(clean_db, owner_conn):
    from service.ingestion import ingest_event

    (contact_id,) = _seed_prospects(owner_conn, 1)
    variant_id = create_variant("v", "h", {})
    wave_id = draft_wave("w", 1, {}, {str(variant_id): 1}, _future())
    with owner_conn.cursor() as cur:
        cur.execute(
            "insert into pieces (contact_id, wave_id, variant_id, mailer_code) "
            "values (%s, %s, %s, 'k7m2xq3vhp')",
            (contact_id, wave_id, variant_id),
        )
    owner_conn.commit()
    ingest_event(
        "posthog", "page.visit", datetime.now(UTC), {"mailer_code": "k7m2xq3vhp"}
    )

    page = client.get("/orphans")
    assert page.status_code == 200
    assert "k7m2xq3vhp" in page.text

    resolve = client.post("/orphans/resolve", follow_redirects=False)
    assert resolve.status_code == 303
    assert client.get("/api/orphans").json() == []


def test_nudges_page_renders_due_nudges(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        cur.execute(
            "insert into contacts (trade, next_action_at, next_action_note) "
            "values ('plumber', '2026-01-01', 'call him')"
        )
    owner_conn.commit()

    page = client.get("/nudges")
    assert page.status_code == 200
    assert "call him" in page.text


def test_lob_webhook_fail_closed_and_ingests_signed_events(clean_db, monkeypatch):
    import hashlib as _hashlib
    import hmac as _hmac
    import json as _json

    monkeypatch.delenv("LOB_WEBHOOK_SECRET", raising=False)
    body = {
        "id": "evt_hook_1",
        "date_created": "2026-07-11T18:00:00Z",
        "event_type": {"id": "postcard.processed_for_delivery"},
        "body": {"metadata": {"mailer_code": "k7m2xq3vhp"}},
    }
    raw = _json.dumps(body).encode()

    # no secret configured -> 503, never ingested
    assert client.post("/webhooks/lob", content=raw).status_code == 503

    monkeypatch.setenv("LOB_WEBHOOK_SECRET", "whsec_test")
    # bad signature -> 401
    assert client.post(
        "/webhooks/lob", content=raw,
        headers={"Lob-Signature": "bad", "Lob-Signature-Timestamp": "1"},
    ).status_code == 401

    ts = str(int(datetime.now(UTC).timestamp() * 1000))
    sig = _hmac.new(b"whsec_test", f"{ts}.".encode() + raw, _hashlib.sha256).hexdigest()
    ok = client.post(
        "/webhooks/lob", content=raw,
        headers={"Lob-Signature": sig, "Lob-Signature-Timestamp": ts},
    )
    assert ok.status_code == 200 and ok.json()["status"] == "ok"

    # idempotent on (source, external_id): replay ingests nothing new
    replay = client.post(
        "/webhooks/lob", content=raw,
        headers={"Lob-Signature": sig, "Lob-Signature-Timestamp": ts},
    )
    assert replay.status_code == 200
    orphans = client.get("/api/orphans").json()
    assert [e["external_id"] for e in orphans] == ["evt_hook_1"]
