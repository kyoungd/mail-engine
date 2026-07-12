"""Phase 3 gate: the jobs. sync ingests a feed idempotently; nightly runs
sync -> resolve -> recompute in order and halts before recompute on a sync failure;
run_drops fires only approved waves that are due."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest

from domain.enums import EventSource
from domain.types import Event
from jobs.drop import run_drops
from jobs.nightly import run_nightly
from jobs.sync import sync
from seams.fakes import FakePrintApi, FakeResponseFeed
from service.ingestion import ingest_event
from service.waves import approve_wave, create_variant, draft_wave

AT = datetime(2026, 1, 5, 12, tzinfo=UTC)
SINCE = datetime(2026, 1, 1, tzinfo=UTC)


def _seed_contact(conn) -> UUID:
    contact_id = uuid4()
    with conn.cursor() as cur:
        cur.execute("insert into contacts (id, trade) values (%s, 'plumber')", (contact_id,))
    conn.commit()
    return contact_id


def _event(source, etype, at, contact_id=None, ext=None) -> Event:
    return Event(
        id=0, source=EventSource(source), type=etype, occurred_at=at, ingested_at=at,
        contact_id=contact_id, external_id=ext, payload={},
    )


def _stage(readonly_url, contact_id) -> str:
    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute("select stage_snapshot from contacts where id = %s", (contact_id,))
            row = cur.fetchone()
            assert row is not None
            return row[0]


def _count(readonly_url, query, params=()) -> int:
    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            assert row is not None
            return row[0]


def test_sync_ingests_feed_events_idempotently(clean_db, owner_conn, readonly_url):
    contact_id = _seed_contact(owner_conn)
    feed = FakeResponseFeed(
        source="posthog", events=[_event("posthog", "page.visit", AT, contact_id, "pv1")]
    )

    first = sync(feed, SINCE)
    second = sync(feed, SINCE)

    assert first == 1
    assert second == 1
    assert _count(readonly_url, "select count(*) from events where external_id = 'pv1'") == 1


def test_nightly_syncs_then_recomputes(clean_db, owner_conn, readonly_url):
    contact_id = _seed_contact(owner_conn)
    feed = FakeResponseFeed(
        source="nmc",
        events=[
            _event("nmc", "piece.submitted", AT, contact_id, "ps1"),
            _event("nmc", "sms.inbound", AT + timedelta(days=1), contact_id, "si1"),
        ],
    )

    run_nightly([feed], SINCE)

    assert _stage(readonly_url, contact_id) == "responded"


def test_nightly_halts_before_recompute_on_sync_failure(clean_db, owner_conn, readonly_url):
    contact_id = _seed_contact(owner_conn)
    # events that WOULD make the contact responded once recompute runs
    ingest_event("lob", "piece.submitted", AT, {}, contact_id=contact_id)
    ingest_event("nmc", "sms.inbound", AT + timedelta(days=1), {}, contact_id=contact_id)
    assert _stage(readonly_url, contact_id) == "prospect"  # not yet recomputed

    with pytest.raises(RuntimeError):
        run_nightly([FakeResponseFeed(source="posthog", fail=True)], SINCE)

    assert _stage(readonly_url, contact_id) == "prospect"  # recompute never ran


def test_run_drops_fires_only_due_approved_waves(clean_db, owner_conn, readonly_url):
    with owner_conn.cursor() as cur:
        for _ in range(2):
            cur.execute("insert into contacts (trade) values ('plumber')")
    owner_conn.commit()
    variant_id = create_variant("v", "h", {})
    scheduled = datetime.now(UTC).date() + timedelta(days=2)
    wave_id = draft_wave("w", 1, {"trade": ["plumber"]}, {str(variant_id): 1}, scheduled)
    approve_wave(wave_id, "young")

    assert run_drops(FakePrintApi(), datetime.now(UTC).date()) == []  # not due yet

    reports = run_drops(FakePrintApi(), scheduled)
    assert len(reports) == 1
    assert reports[0].pieces_created == 2
    assert _count(readonly_url, "select count(*) from pieces where wave_id = %s", (wave_id,)) == 2


def test_run_drops_resumes_a_crashed_executing_wave(clean_db, owner_conn, readonly_url):
    with owner_conn.cursor() as cur:
        for _ in range(5):
            cur.execute("insert into contacts (trade) values ('plumber')")
    owner_conn.commit()
    variant_id = create_variant("v", "h", {})
    scheduled = datetime.now(UTC).date() + timedelta(days=1)
    wave_id = draft_wave("w", 1, {"trade": ["plumber"]}, {str(variant_id): 1}, scheduled)
    approve_wave(wave_id, "young")

    with pytest.raises(RuntimeError):
        run_drops(FakePrintApi(fail_after=2), scheduled)  # crashes -> wave left 'executing'
    assert _count(readonly_url, "select count(*) from pieces where wave_id = %s", (wave_id,)) == 2

    reports = run_drops(FakePrintApi(), scheduled)  # the job resumes the executing wave
    assert len(reports) == 1
    assert _count(readonly_url, "select count(*) from pieces where wave_id = %s", (wave_id,)) == 5
