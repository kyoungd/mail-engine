"""Phase 1 gate: resolve_orphans runs the precedence chain over unattributed
events — mailer code (attributing the piece too), thread continuity, exact phone —
never fuzzy-matches, and is idempotent on re-run."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Json

from service.ingestion import ingest_event, resolve_orphans

AT = datetime(2026, 1, 5, 12, tzinfo=UTC)


def _seed_contact(conn, phone: str | None = None) -> UUID:
    contact_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            "insert into contacts (id, trade, phone_e164) values (%s, 'plumber', %s)",
            (contact_id, phone),
        )
    conn.commit()
    return contact_id


def _seed_piece(conn, contact_id: UUID, mailer_code: str) -> UUID:
    variant_id, wave_id, piece_id = uuid4(), uuid4(), uuid4()
    with conn.cursor() as cur:
        cur.execute(
            "insert into variants (id, name, hypothesis, creative) "
            "values (%s, %s, 'tests copy A', %s)",
            (variant_id, f"v-{variant_id}", Json({})),
        )
        cur.execute(
            "insert into waves (id, name, drop_number, audience_rule, variant_split) "
            "values (%s, %s, 1, %s, %s)",
            (wave_id, f"w-{wave_id}", Json({}), Json({})),
        )
        cur.execute(
            "insert into pieces (id, contact_id, wave_id, variant_id, mailer_code) "
            "values (%s, %s, %s, %s, %s)",
            (piece_id, contact_id, wave_id, variant_id, mailer_code),
        )
    conn.commit()
    return piece_id


def _attribution(readonly_url: str, event_id: int) -> tuple:
    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select contact_id, piece_id from events where id = %s", (event_id,)
            )
            row = cur.fetchone()
            assert row is not None
            return row


def test_mailer_code_attributes_event_and_piece(clean_db, owner_conn, readonly_url):
    contact_id = _seed_contact(owner_conn)
    piece_id = _seed_piece(owner_conn, contact_id, "MC-100")
    event_id = ingest_event("posthog", "page.visit", AT, {"mailer_code": "MC-100"})

    report = resolve_orphans()

    assert (event_id, contact_id) in report.matched
    assert _attribution(readonly_url, event_id) == (contact_id, piece_id)


def test_phone_attributes_when_no_code(clean_db, owner_conn, readonly_url):
    contact_id = _seed_contact(owner_conn, phone="+18186793565")
    event_id = ingest_event("nmc", "call.inbound", AT, {"phone": "(818) 679-3565"})

    resolve_orphans()

    contact, piece = _attribution(readonly_url, event_id)
    assert contact == contact_id
    assert piece is None


def test_thread_continuity_attributes(clean_db, owner_conn, readonly_url):
    contact_id = _seed_contact(owner_conn)
    ingest_event("nmc", "call.inbound", AT, {"thread_id": "T-9"}, contact_id=contact_id)
    event_id = ingest_event("nmc", "sms.inbound", AT, {"thread_id": "T-9"})

    resolve_orphans()

    contact, _ = _attribution(readonly_url, event_id)
    assert contact == contact_id


def test_name_only_stays_orphan(clean_db, owner_conn, readonly_url):
    _seed_contact(owner_conn, phone="+18186793565")
    event_id = ingest_event("nmc", "call.inbound", AT, {"name": "Bob Plumber"})

    report = resolve_orphans()

    assert event_id in report.orphaned
    assert _attribution(readonly_url, event_id) == (None, None)


def test_resolve_is_idempotent(clean_db, owner_conn, readonly_url):
    _seed_contact(owner_conn, phone="+18186793565")
    ingest_event("nmc", "call.inbound", AT, {"phone": "+18186793565"})

    first = resolve_orphans()
    second = resolve_orphans()

    assert len(first.matched) == 1
    assert second.matched == []
