"""E2E journey — the full funnel against the REAL Lob test environment.

Wipe → intake → creative → wave → proof → approve → drop → verify-against-Lob →
idempotent replay. No fakes anywhere: the proof and the drop hit real Lob (test key,
so nothing prints and no money moves). This is the software half of the Phase-6 ghost
wave, and the one command that answers "did my change break the funnel?".

Marked `e2e`: the default suite deselects it (network, ~30-60s). Run with `make e2e`.
tests/guard.py still fences the session — it cannot run against mailengine_prod or a
live Lob key, so the step-1 wipe is safe by construction.
"""

import base64
import html as html_mod
import json
import os
import re
import time
import urllib.request
import warnings
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

warnings.simplefilter("ignore")  # starlette testclient httpx deprecation noise

from service.contacts import ensure_seed_contacts  # noqa: E402
from service.queries import get_wave_dashboard  # noqa: E402
from web.api import app  # noqa: E402

pytestmark = pytest.mark.e2e

SEED = [{"name": "E2E Seed HQ", "line1": "1200 Getty Center Dr", "city": "Los Angeles",
         "state": "CA", "zip": "90049"}]

REPO = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).parent / "fixtures" / "cslb-journey.csv"
CREATIVE_DIR = REPO / "creative" / "w1-6x9-loss-math"

from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(app)


def _future_iso() -> str:
    return (datetime.now(UTC).date() + timedelta(days=5)).isoformat()


def _wipe(owner_url: str) -> None:
    with psycopg.connect(owner_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "truncate activation, events, pieces, waves, variants, contacts "
                "restart identity cascade"
            )
        conn.commit()


def _scalar(url: str, query, params=()):
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            assert row is not None
            return row[0]


def _column(url: str, query, params=()) -> list:
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return [r[0] for r in cur.fetchall()]


def _fetch_pdf_with_retry(url: str, attempts: int = 8, delay: float = 4.0) -> None:
    """Lob renders the proof PDF asynchronously — the URL is returned immediately but
    500s for a few seconds until the render lands. Poll until it serves a real PDF."""
    last = None
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                head = resp.read(5)
                if head.startswith(b"%PDF"):
                    return
                last = head
        except Exception as exc:  # noqa: BLE001 — surface whatever Lob returned
            last = exc
        time.sleep(delay)
    raise AssertionError(f"proof PDF never rendered at {url} (last: {last!r})")


def _assert_postcard_in_lob(lob_id: str) -> None:
    key = os.environ["LOB_API_KEY"]  # dev == the Lob test key
    auth = base64.b64encode(f"{key}:".encode()).decode()
    req = urllib.request.Request(
        f"https://api.lob.com/v1/postcards/{lob_id}",
        headers={"Authorization": f"Basic {auth}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    assert data["id"] == lob_id, f"Lob returned {data.get('id')!r} for {lob_id!r}"


def test_full_funnel_journey(owner_url, readonly_url, applied_migrations):
    # 1. wipe --------------------------------------------------------------------
    _wipe(owner_url)
    assert _scalar(readonly_url, "select count(*) from contacts") == 0

    # 2. intake ------------------------------------------------------------------
    with open(FIXTURE, "rb") as handle:
        r = client.post(
            "/intake",
            files={"file": ("cslb-journey.csv", handle, "text/csv")},
            data={"source": "cslb"},
        )
    assert r.status_code == 200
    # 6 load; 1 dup deduped; 1 no-trade invalid; 1 do_not_mail suppressed.
    # (fragments, not one string — the template wraps the report across lines.)
    body = " ".join(r.text.split())
    assert "loaded 6" in body
    assert "deduped 1" in body
    assert "invalid 1" in body
    assert "suppressed 1" in body
    assert _scalar(readonly_url, "select count(*) from contacts") == 6

    # 2b. seed — one founder address rides the wave (FR-4) -----------------------
    ensure_seed_contacts(SEED)
    assert _scalar(readonly_url, "select count(*) from contacts where is_seed") == 1

    # 3. creative — a real one ---------------------------------------------------
    creative = {
        "front": (CREATIVE_DIR / "front.html").read_text(),
        "back": (CREATIVE_DIR / "back.html").read_text(),
        "size": "6x9",
        "mail_type": "usps_first_class",
    }
    r = client.post(
        "/variants",
        data={"name": "e2e-loss-math", "hypothesis": "journey", "creative": json.dumps(creative)},
        follow_redirects=False,
    )
    assert r.status_code == 303
    variant_id = _scalar(readonly_url, "select id::text from variants where name = 'e2e-loss-math'")

    # 4. wave --------------------------------------------------------------------
    r = client.post(
        "/waves/new",
        data={
            "name": "e2e journey wave",
            "drop_number": "1",
            "scheduled_for": _future_iso(),
            "audience_rule": '{"trade": ["plumber"]}',
            "variant_split": json.dumps({variant_id: 1}),
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    approve_path = r.headers["location"]
    wave_id = approve_path.split("/")[2]

    # 5. preview + proof (REAL Lob test render) ----------------------------------
    r = client.get(approve_path)
    assert r.status_code == 200
    # Audience is the 4 mailable plumbers + 1 seed — not the do_not_mail one, not hvac.
    assert "<strong>5</strong>" in r.text
    assert "seed" in r.text.lower()
    proof_match = re.search(r'src="(https://lob-assets[^"]+)"', r.text)
    assert proof_match, "no Lob proof embedded on the approval screen"
    _fetch_pdf_with_retry(html_mod.unescape(proof_match.group(1)))
    hash_match = re.search(r"state_hash=([0-9a-f]+)", r.text)
    assert hash_match, "no state_hash in the approval form"
    state_hash = hash_match.group(1)

    # 6. approve -----------------------------------------------------------------
    r = client.post(
        f"/waves/{wave_id}/approve",
        params={"state_hash": state_hash},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert _scalar(readonly_url, "select status from waves where id = %s", (wave_id,)) == "approved"

    # 7. drop — REAL Lob test-mode postcards -------------------------------------
    r = client.post(
        "/drops/run",
        data={"password": os.environ["DROP_PASSWORD"], "as_of": _future_iso()},
    )
    assert r.status_code == 200
    # 5 pieces fire (4 plumbers + 1 seed); all submit to real Lob test mode.
    assert _scalar(readonly_url, "select count(*) from pieces where wave_id = %s", (wave_id,)) == 5
    assert (
        _scalar(
            readonly_url,
            "select count(*) from pieces where wave_id = %s and status = 'submitted' "
            "and lob_id is not null",
            (wave_id,),
        )
        == 5
    )
    assert _scalar(readonly_url, "select status from waves where id = %s", (wave_id,)) == "sent"

    # 7b. the seed fired but stays out of the metrics (FR-7) ---------------------
    dash = get_wave_dashboard(wave_id)
    assert sum(v.pieces for v in dash.by_variant) == 4  # seed piece excluded from the denominator

    # 8. verify against Lob itself -----------------------------------------------
    lob_ids = _column(readonly_url, "select lob_id from pieces where wave_id = %s", (wave_id,))
    assert len(lob_ids) == 5 and len(set(lob_ids)) == 5
    for lob_id in lob_ids:
        _assert_postcard_in_lob(lob_id)

    # 9. idempotent replay — clicking Run drops again re-mails nothing -----------
    r = client.post(
        "/drops/run",
        data={"password": os.environ["DROP_PASSWORD"], "as_of": _future_iso()},
    )
    assert r.status_code == 200
    after = _column(readonly_url, "select lob_id from pieces where wave_id = %s", (wave_id,))
    assert sorted(after) == sorted(lob_ids)  # same pieces, no new postcards
