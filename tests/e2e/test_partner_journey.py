"""E2E journey — a sales partner's full lifecycle on the local stack.

Wipe → intake (web window) → partner registration (partners_cli) → area-code
subscription → fake-registry DNC scrub → assign → export → nightly #1 (close
correlated, won terminated, report emailed) → idempotent replays (retry receipt,
nightly #2 sends nothing new) → reclaim. Everything runs through the real front
doors — the web /intake route, the operator CLIs, run_nightly, the real
EmailSender with the DB recipient resolver — with fakes only at the seams that
CANNOT be real locally: the FTC registry (no SAN exists), the Medusa close feed
(no test run may hold a writable Medusa credential — tests/guard.py), the demos
summary (booking-system is another repo), and the SMTP socket (a transport
capture inside the real Sender, so composition and recipient resolution stay
real).

This is the partner-spine counterpart of test_journey.py's mail funnel, and the
local rehearsal of the C3 ceremony's verification: holdings, close crediting,
and the demo line, end to end. Unlike the mail journey it needs no Lob key and
no network. Marked `e2e`: the default suite deselects it; run with `make e2e`
or `uv run pytest -m e2e tests/e2e/test_partner_journey.py`.
"""

import csv
import io
import warnings
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

warnings.simplefilter("ignore")  # starlette testclient httpx deprecation noise

from config.params import HOUSE_PARTNER_ID  # noqa: E402
from jobs import assignment_cli, dnc_refresh, partners_cli, subscribe_area_codes  # noqa: E402
from jobs.nightly import run_nightly  # noqa: E402
from seams.email_sender import EmailSender  # noqa: E402
from seams.fakes import FakeCloseFeed, FakeDemosClient, FakeResponseFeed  # noqa: E402
from seams.nmc_closes import Close  # noqa: E402
from web.api import app  # noqa: E402

pytestmark = pytest.mark.e2e

from fastapi.testclient import TestClient  # noqa: E402
from pathlib import Path  # noqa: E402

client = TestClient(app)

FIXTURE = Path(__file__).parent / "fixtures" / "cslb-partner-journey.csv"

PARTNER = "Journey Partner"
PARTNER_EMAIL = "partner@e2e.test"
PARTNER_CODE = "JP-01"
SALES_REP_ID = 77
DNC_LISTED = "8185550103"  # Burbank Pipe & Supply — the registry-hit contact
CLOSE_PHONE = "+18185550101"  # Reseda Rooter — the contact that becomes a customer


class _CaptureSMTP:
    """Duck-typed smtplib.SMTP stand-in: the real EmailSender composes and
    resolves; only the socket is captured. Class-level outbox — EmailSender
    constructs a fresh transport per send."""

    outbox: list = []

    def __init__(self, host, port):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        _CaptureSMTP.outbox.append(msg)


def _wipe(owner_url: str) -> None:
    with psycopg.connect(owner_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "truncate activation, events, pieces, waves, variants, contacts, "
                "intake_cslb_ca, intake_fbn_ca, contact_merge_map, "
                "assignment_batches, feed_watermarks, "
                "suppression_tombstones, dnc_subscriptions "
                "restart identity cascade"
            )
            # partners is not truncatable (the house row is load-bearing) — drop
            # only this journey's row so registration below starts from nothing.
            cur.execute("delete from partners where name = %s", (PARTNER,))
        conn.commit()
    _CaptureSMTP.outbox.clear()


def _scalar(url: str, query, params=()):
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            assert row is not None
            return row[0]


def _sender() -> EmailSender:
    return EmailSender(
        host="capture.local", port=2525, user="e2e", password="unused",
        transport=_CaptureSMTP,
    )


def _partner_mail() -> list:
    return [m for m in _CaptureSMTP.outbox if m["To"] == PARTNER_EMAIL]


def test_partner_journey(owner_url, readonly_url, applied_migrations, capsys):
    # 1. wipe --------------------------------------------------------------------
    _wipe(owner_url)
    assert _scalar(readonly_url, "select count(*) from contacts") == 0

    # 2. intake through the web window -------------------------------------------
    with open(FIXTURE, "rb") as handle:
        r = client.post(
            "/intake",
            files={"file": ("cslb-partner-journey.csv", handle, "text/csv")},
            data={"source": "cslb"},
        )
    assert r.status_code == 200
    assert "loaded 6" in " ".join(r.text.split())
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

    # 8. nightly #1 — the close arrives; the report goes out ---------------------
    now = datetime.now(UTC)
    close_feed = FakeCloseFeed([Close(
        id="cust-journey-1", recorded_at=now, occurred_at=now,
        kind="signup_completed", phone_e164=CLOSE_PHONE,
        partner_code=PARTNER_CODE, mailer_code=None, sold_by=SALES_REP_ID,
        signed_up_via="wizard", subscription_status="active",
    )])
    demos = FakeDemosClient(partners=[{
        "salesRepId": str(SALES_REP_ID), "calls": "5", "uniqueProspects": "4",
        "blockedCalls": "1", "textsForwarded": "2",
    }])
    run_nightly(
        [FakeResponseFeed(source="e2e-fake")], now - timedelta(days=1),
        sender=_sender(), close_feed=close_feed, demos_client=demos,
    )

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

    # the report: one email, all three sections rendered from real data
    mail = _partner_mail()
    assert len(mail) == 1
    report = mail[0]
    assert report["Subject"].startswith("Your NeverMissCall partner report —")
    body = report.get_content()
    assert "Your list" in body
    assert "assigned 2 contacts" in body
    assert "Contacts currently yours: 1" in body
    assert "0 opted out, 1 reclaimed, 0 expired" in body
    assert "Your last export was generated" in body
    assert "Re-pull your sheet before your next calling session." in body
    assert "Closes credited since your last report: 1" in body
    assert "- Reseda Rooter (" in body
    assert "Total closes to date: 1" in body
    assert (
        "On your demo line since your last report: 5 calls "
        "(4 unique prospects, 1 from blocked numbers), 2 texts forwarded"
    ) in body
    assert _scalar(
        readonly_url,
        "select last_report_at is not null from partners where id = %s",
        (partner_id,),
    ) is True

    # 9. same-key retry is a receipt, not a re-run -------------------------------
    assert assignment_cli.main([
        "assign", PARTNER, "--key", "journey-b1",
        "--rule", '{"trade": ["plumber"]}',
    ]) == 0
    out = capsys.readouterr().out
    assert "1 RETRY (receipt)" in out
    assert "released since assignment: 1" in out  # Reseda, released by won

    # 10. nightly #2 — full replay changes nothing, mails nothing ---------------
    run_nightly(
        [FakeResponseFeed(source="e2e-fake")], now - timedelta(days=1),
        sender=_sender(), close_feed=close_feed, demos_client=demos,
    )
    assert _scalar(
        readonly_url,
        "select count(*) from events where type = 'signup.completed'",
    ) == 1
    assert len(_partner_mail()) == 1  # heartbeat not due, no trigger — silence

    # 11. reclaim — end of the road ----------------------------------------------
    assert assignment_cli.main([
        "reclaim", PARTNER, "--reason", "journey over",
    ]) == 0
    assert "reclaimed 1 contact(s)" in capsys.readouterr().out
    assert _scalar(
        readonly_url,
        "select count(*) from contacts where owner_id = %s", (partner_id,),
    ) == 0
