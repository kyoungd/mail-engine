"""`partners_cli status` — where each partner is in the assignment cycle
(operator decision 2026-08-05: CLI-first, pulled ahead of the rehearsal)."""

from datetime import UTC, datetime

import pytest

from jobs.partners_cli import main
from service.ingestion import ingest_event
from tests.acceptance.partner_cycle_helpers import aged_quiet_batch, remove_partners


@pytest.fixture(autouse=True)
def _cleanup(owner_conn):
    yield
    remove_partners(owner_conn, "Stat")


def test_status_shows_holdings_batch_age_and_quiet_marker(clean_db, owner_conn, capsys):
    aged_quiet_batch(owner_conn, "StatA", days=31, key="stat-a")
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "StatA" in out
    assert "holdings: 2" in out
    assert "stat-a" in out
    assert "day 31 of 90" in out
    assert "QUIET past day 30" in out
    assert "Young" not in out  # the house is the pool, not a partner cycle


def test_status_shows_activity_count_instead_of_quiet(clean_db, owner_conn, capsys):
    _, contacts = aged_quiet_batch(owner_conn, "StatB", days=31, key="stat-b")
    ingest_event(
        "nmc", "call.inbound", datetime.now(UTC), {},
        external_id="stat-b-call", contact_id=contacts[0],
    )
    main(["status"])
    out = capsys.readouterr().out
    assert "activity: 1" in out
    assert "QUIET" not in out


def test_status_filters_by_name(clean_db, owner_conn, capsys):
    aged_quiet_batch(owner_conn, "StatC", days=10, key="stat-c")
    aged_quiet_batch(
        owner_conn, "StatD", days=10, key="stat-d",
        phones=("+18185551003", "+18185551004"),
    )
    main(["status", "StatC"])
    out = capsys.readouterr().out
    assert "StatC" in out and "StatD" not in out


def test_status_hides_inactive_partners_unless_named(clean_db, owner_conn, capsys):
    aged_quiet_batch(owner_conn, "StatE", days=10, key="stat-e")
    with owner_conn.cursor() as cur:
        cur.execute("update partners set status = 'inactive' where name = 'StatE'")
    owner_conn.commit()
    main(["status"])
    assert "StatE" not in capsys.readouterr().out
    main(["status", "StatE"])
    assert "StatE" in capsys.readouterr().out
