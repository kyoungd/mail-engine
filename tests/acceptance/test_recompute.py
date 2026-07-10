"""Phase 1 gate: recompute_state derives stage snapshots from the event stream,
is deterministic over unchanged events, preserves human-authored data, and scales
to a realistic history in bounded time (the last is a nightly test)."""

import time
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import psycopg
import pytest

from service.execution import recompute_state
from service.ingestion import ingest_event

AT1 = datetime(2026, 1, 1, 12, tzinfo=UTC)
AT2 = datetime(2026, 1, 3, 12, tzinfo=UTC)
AT3 = datetime(2026, 1, 4, 12, tzinfo=UTC)


def _seed_contact(conn, **cols) -> UUID:
    contact_id = uuid4()
    columns = ["id", "trade", *cols.keys()]
    values = [contact_id, "plumber", *cols.values()]
    placeholders = ", ".join(["%s"] * len(values))
    with conn.cursor() as cur:
        cur.execute(
            f"insert into contacts ({', '.join(columns)}) values ({placeholders})",
            values,
        )
    conn.commit()
    return contact_id


def _stage(readonly_url: str, contact_id: UUID) -> str:
    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select stage_snapshot from contacts where id = %s", (contact_id,)
            )
            row = cur.fetchone()
            assert row is not None
            return row[0]


def test_recompute_derives_stage_from_events(clean_db, owner_conn, readonly_url):
    contact_id = _seed_contact(owner_conn)
    ingest_event("lob", "piece.submitted", AT1, {}, contact_id=contact_id)
    ingest_event("nmc", "sms.inbound", AT2, {}, contact_id=contact_id)

    report = recompute_state()

    assert report.contacts_updated == 1
    assert _stage(readonly_url, contact_id) == "responded"


def test_recompute_is_deterministic(clean_db, owner_conn, readonly_url):
    contact_id = _seed_contact(owner_conn)
    ingest_event("lob", "piece.submitted", AT1, {}, contact_id=contact_id)
    ingest_event("nmc", "sms.inbound", AT2, {}, contact_id=contact_id)
    ingest_event("nmc", "sms.outbound", AT3, {}, contact_id=contact_id)

    recompute_state()
    first = _stage(readonly_url, contact_id)
    recompute_state()
    second = _stage(readonly_url, contact_id)

    assert first == second == "in_conversation"


def test_do_not_mail_survives_and_drives_suppression(clean_db, owner_conn, readonly_url):
    contact_id = _seed_contact(owner_conn, do_not_mail=True)
    ingest_event("lob", "piece.submitted", AT1, {}, contact_id=contact_id)

    recompute_state()

    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select do_not_mail, stage_snapshot from contacts where id = %s",
                (contact_id,),
            )
            row = cur.fetchone()
            assert row is not None
            do_not_mail, stage = row
    assert do_not_mail is True
    assert stage == "suppressed"


def test_human_set_next_action_survives_recompute(clean_db, owner_conn, readonly_url):
    contact_id = _seed_contact(owner_conn)
    with owner_conn.cursor() as cur:
        cur.execute(
            "update contacts set next_action_at = %s, next_action_note = %s where id = %s",
            (date(2026, 2, 1), "call them", contact_id),
        )
    owner_conn.commit()

    recompute_state()

    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select next_action_at, next_action_note from contacts where id = %s",
                (contact_id,),
            )
            row = cur.fetchone()
            assert row is not None
            next_action_at, note = row
    assert next_action_at == date(2026, 2, 1)
    assert note == "call them"


@pytest.mark.nightly
def test_recompute_scales_and_is_deterministic(clean_db, owner_conn, readonly_url):
    contacts, events = 5000, 50000  # 10 events per contact
    with owner_conn.cursor() as cur:
        cur.execute(
            "insert into contacts (trade) select 'plumber' from generate_series(1, %s)",
            (contacts,),
        )
        cur.execute("select id from contacts")
        ids = [r[0] for r in cur.fetchall()]
        with cur.copy(
            "copy events (contact_id, source, type, occurred_at, payload) from stdin"
        ) as copy:
            for contact_id in ids:
                copy.write_row((contact_id, "lob", "piece.submitted", AT1, "{}"))
                for _ in range(9):
                    copy.write_row((contact_id, "nmc", "sms.inbound", AT2, "{}"))
    owner_conn.commit()

    started = time.monotonic()
    report = recompute_state()
    elapsed = time.monotonic() - started
    assert report.contacts_updated == contacts

    def snapshot() -> dict:
        with psycopg.connect(readonly_url) as conn:
            with conn.cursor() as cur:
                cur.execute("select id, stage_snapshot from contacts")
                return dict(cur.fetchall())

    first = snapshot()
    recompute_state()
    second = snapshot()

    assert first == second
    assert all(stage == "responded" for stage in first.values())
    assert len(first) == contacts
    assert elapsed < 30, f"recompute of {events} events took {elapsed:.1f}s"
