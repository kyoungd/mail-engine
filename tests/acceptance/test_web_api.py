"""Phase 5 gate: the thin FastAPI window. Every view maps to one query verb, the
approval flow carries the preview hash, and the execution verbs are unreachable over
HTTP. Driven in-process via FastAPI's TestClient."""

import warnings
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from service.waves import create_variant, draft_wave

warnings.simplefilter("ignore")  # starlette testclient httpx deprecation noise

from web.api import app  # noqa: E402

client = TestClient(app)


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


def test_home_redirects_to_pipeline(clean_db):
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (307, 308)
    assert response.headers["location"] == "/pipeline"


# --- execution verbs are not routed --------------------------------------------


def test_execution_verbs_have_no_http_route(clean_db):
    assert client.post(f"/api/waves/{uuid4()}/execute").status_code == 404
    assert client.post("/api/recompute").status_code == 404
    assert client.get("/api/waves/drop").status_code == 404


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
