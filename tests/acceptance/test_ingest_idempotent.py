"""Phase 1 gate: ingest_event is idempotent on (source, external_id), rejects
unknown types and sources loudly, and does not dedupe events that carry no key."""

from datetime import UTC, datetime

import psycopg
import pytest

from domain.taxonomy import UnknownEventType
from service.ingestion import ingest_event

AT = datetime(2026, 1, 5, 12, tzinfo=UTC)


def _event_count(readonly_url: str) -> int:
    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from events")
            row = cur.fetchone()
            assert row is not None
            return row[0]


def test_same_source_and_external_id_is_one_row(clean_db, readonly_url):
    first = ingest_event("lob", "piece.delivered", AT, {"x": 1}, external_id="E1")
    second = ingest_event("lob", "piece.delivered", AT, {"x": 1}, external_id="E1")
    assert first == second
    assert _event_count(readonly_url) == 1


def test_unknown_type_is_rejected_loudly(clean_db):
    with pytest.raises(UnknownEventType):
        ingest_event("lob", "piece.exploded", AT, {})


def test_unknown_source_is_rejected(clean_db):
    with pytest.raises(ValueError):
        ingest_event("lobster", "piece.delivered", AT, {})


def test_events_without_external_id_are_not_deduped(clean_db, readonly_url):
    ingest_event("human", "note.general", AT, {"text": "a"})
    ingest_event("human", "note.general", AT, {"text": "a"})
    assert _event_count(readonly_url) == 2
