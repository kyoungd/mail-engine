"""E2E journey — a sales partner's full lifecycle on the local stack.

Wipe → intake (intake_cli) → partner registration (partners_cli) → area-code
subscription → fake-registry DNC scrub → assign → export → nightly #1 (close
correlated, won terminated) → idempotent replays (retry receipt, nightly #2
changes nothing) → reclaim. Everything runs through the real front doors — the
operator CLIs and run_nightly — with fakes only at the seams that CANNOT be real
locally: the FTC registry (no SAN exists) and the Medusa close feed (no test run
may hold a writable Medusa credential — tests/guard.py).

Needs no network. Marked `e2e`: the default suite deselects it; run with
`make e2e` or `uv run pytest -m e2e tests/e2e/test_partner_journey.py`.
"""

import csv
import io
from datetime import UTC, datetime

import psycopg
import pytest

from config.params import HOUSE_PARTNER_ID  # noqa: E402
from jobs import (  # noqa: E402
    assignment_cli,
    dnc_refresh,
    intake_cli,
    partners_cli,
    subscribe_area_codes,
)
from jobs.nightly import run_nightly  # noqa: E402
from seams.fakes import FakeCloseFeed  # noqa: E402
from seams.nmc_closes import Close  # noqa: E402

pytestmark = pytest.mark.e2e

from pathlib import Path  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "cslb-partner-journey.csv"

PARTNER = "Journey Partner"
PARTNER_EMAIL = "partner@e2e.test"
PARTNER_CODE = "JP-01"
SALES_REP_ID = 77
DNC_LISTED = "8185550103"  # Burbank Pipe & Supply — the registry-hit contact
CLOSE_PHONE = "+18185550101"  # Reseda Rooter — the contact that becomes a customer


def _wipe(owner_url: str) -> None:
    with psycopg.connect(owner_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "truncate activation, events, pieces, waves, variants, contacts, "
                "intake_cslb_ca, intake_fbn_ca, contact_merge_map, "
                "assignment_batches, feed_watermarks, "
                "suppression_tombstones, dnc_subscriptions, "
                "dnc_numbers, dnc_log, dnc_runs, contact_zones, memos, calls_received, calls, contact_state, rep_settings "
                "restart identity cascade"
            )
            # partners is not truncatable (the house row is load-bearing) — drop
            # only this journey's row so registration below starts from nothing.
            cur.execute("delete from partners where name = %s", (PARTNER,))
        conn.commit()


def _scalar(url: str, query, params=()):
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            assert row is not None
            return row[0]


def test_partner_journey(owner_url, readonly_url, applied_migrations, capsys):
    # 1. wipe --------------------------------------------------------------------
    _wipe(owner_url)
    assert _scalar(readonly_url, "select count(*) from contacts") == 0

    # 2. intake through the command ---------------------------------------------
    assert intake_cli.main([str(FIXTURE), "--source", "cslb"]) == 0
    assert "loaded=6" in capsys.readouterr().out
    assert _scalar(readonly_url, "select count(*) from contacts") == 6

    # 3. partner registration — the runbook's CLI step ---------------------------
    assert partners_cli.main([
        "set", PARTNER, "--channel", "email", "--channel-address", PARTNER_EMAIL,
        "--hours", "10", "--radius", "20",
        "--sales-rep-id", str(SALES_REP_ID), "--partner-code", PARTNER_CODE,
    ]) == 0
    partner_id = _scalar(
        readonly_url, "select id from partners where name = %s", (PARTNER,)
    )

    # 4. DNC subscription: 818 only (Harbor's 310 stays uncovered) ---------------
    assert subscribe_area_codes.main(["add", "818"]) == 0

    # 5. the scrub — fake registry (no SAN), Burbank listed ----------------------
    assert dnc_refresh.main(["--fake", "v1", "--listed", DNC_LISTED]) == 0
    # all four 818 contacts checked (incl. the hvac row), exactly one hit
    assert "checked=4 hits=1 cleared=0" in capsys.readouterr().err
    assert _scalar(
        readonly_url,
        "select dnc_registry from contacts where phone_e164 = %s",
        (f"+1{DNC_LISTED}",),
    ) is True

    # 6. assign — derived batch, every gate visible as a named shortfall ---------
    assert assignment_cli.main([
        "assign", PARTNER, "--key", "journey-b1",
        "--rule", '{"trade": ["plumber"]}',
    ]) == 0
    out = capsys.readouterr().out
    # 5 plumbers matched the rule; the hvac row was never a candidate. Two clear
    # the gates; the other three each name their cause.
    assert "2 assigned" in out
    assert "shortfall dnc_registry: 1" in out
    assert "shortfall dnc_unsubscribed: 1" in out
    assert "shortfall no_phone: 1" in out
    assert _scalar(
        readonly_url,
        "select count(*) from contacts where owner_id = %s "
        "and assignment_batch_id is not null",
        (partner_id,),
    ) == 2

    # 7. export — the partner's working file -------------------------------------
    assert assignment_cli.main(["export", PARTNER]) == 0
    sheet = list(csv.reader(io.StringIO(capsys.readouterr().out)))
    header, rows = sheet[0], sheet[1:]
    assert header[:3] == ["business_name", "contact_name", "phone"]
    assert {row[0] for row in rows} == {"Reseda Rooter", "Van Nuys Drainworks"}
    assert all(row[header.index("expires_at")] for row in rows)
    assert _scalar(
        readonly_url,
        "select last_export_at is not null from partners where id = %s",
        (partner_id,),
    ) is True

    # 8. nightly #1 — the close arrives -----------------------------------------
    now = datetime.now(UTC)
    close_feed = FakeCloseFeed([Close(
        id="cust-journey-1", recorded_at=now, occurred_at=now,
        kind="signup_completed", phone_e164=CLOSE_PHONE,
        partner_code=PARTNER_CODE, mailer_code=None, sold_by=SALES_REP_ID,
        signed_up_via="wizard", subscription_status="active",
    )])
    run_nightly(close_feed=close_feed)

    # the close correlated by phone, derived won, and left its assignment
    reseda = _scalar(
        readonly_url, "select id from contacts where phone_e164 = %s", (CLOSE_PHONE,)
    )
    assert _scalar(
        readonly_url,
        "select count(*) from events where type = 'signup.completed' "
        "and contact_id = %s and payload->>'partner_code' = %s",
        (reseda, PARTNER_CODE),
    ) == 1
    assert _scalar(
        readonly_url,
        "select stage_snapshot::text from contacts where id = %s", (reseda,),
    ) == "won"
    assert _scalar(
        readonly_url, "select owner_id from contacts where id = %s", (reseda,)
    ) == HOUSE_PARTNER_ID
    # the other assigned contact is untouched
    assert _scalar(
        readonly_url,
        "select count(*) from contacts where owner_id = %s "
        "and assignment_batch_id is not null",
        (partner_id,),
    ) == 1

    # 9. same-key retry is a receipt, not a re-run -------------------------------
    assert assignment_cli.main([
        "assign", PARTNER, "--key", "journey-b1",
        "--rule", '{"trade": ["plumber"]}',
    ]) == 0
    out = capsys.readouterr().out
    assert "1 RETRY (receipt)" in out
    assert "released since assignment: 1" in out  # Reseda, released by won

    # 10. nightly #2 — full replay changes nothing ------------------------------
    run_nightly(close_feed=close_feed)
    assert _scalar(
        readonly_url,
        "select count(*) from events where type = 'signup.completed'",
    ) == 1

    # 11. reclaim — end of the road ----------------------------------------------
    assert assignment_cli.main([
        "reclaim", PARTNER, "--reason", "journey over",
    ]) == 0
    assert "reclaimed 1 contact(s)" in capsys.readouterr().out
    assert _scalar(
        readonly_url,
        "select count(*) from contacts where owner_id = %s", (partner_id,),
    ) == 0
