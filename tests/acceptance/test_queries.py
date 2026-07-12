"""Phase 2 gate: the query verbs the UI panels are built on. Each must return in
exactly one round trip (no N+1) and read correct data. Round trips are counted with a
Cursor subclass installed via cursor_factory."""

from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Cursor
from psycopg.types.json import Json

import service.queries as queries

AT = datetime(2026, 1, 5, 12, tzinfo=UTC)


class _CountingCursor(Cursor):
    executes = 0

    def execute(self, query, params=None, **kwargs):
        type(self).executes += 1
        return super().execute(query, params, **kwargs)


@contextmanager
def _counting_readonly(url):
    with psycopg.connect(url, cursor_factory=_CountingCursor) as conn:
        conn.read_only = True
        yield conn


@pytest.fixture()
def one_round_trip(monkeypatch, readonly_url):
    """Route the query verbs through a counting read-only connection; return a checker
    that asserts exactly one execute happened for the wrapped call."""
    monkeypatch.setattr(queries, "readonly_connection", lambda: _counting_readonly(readonly_url))

    def run(fn, *args, **kwargs):
        _CountingCursor.executes = 0
        result = fn(*args, **kwargs)
        assert _CountingCursor.executes == 1, f"{fn.__name__} did {_CountingCursor.executes} queries"
        return result

    return run


def _seed_contact(conn, stage="prospect", **cols) -> UUID:
    contact_id = uuid4()
    columns = ["id", "trade", "stage_snapshot", *cols.keys()]
    values = [contact_id, "plumber", stage, *cols.values()]
    placeholders = ", ".join(["%s"] * len(values))
    with conn.cursor() as cur:
        cur.execute(
            f"insert into contacts ({', '.join(columns)}) values ({placeholders})", values
        )
    conn.commit()
    return contact_id


def _seed_variant_wave_piece(conn, contact_id, status="delivered", cost=73):
    variant_id, wave_id = uuid4(), uuid4()
    with conn.cursor() as cur:
        cur.execute(
            "insert into variants (id, name, hypothesis, creative) values (%s, 'v', 'h', %s)",
            (variant_id, Json({})),
        )
        cur.execute(
            "insert into waves (id, name, drop_number, audience_rule, variant_split) "
            "values (%s, 'w', 1, %s, %s)",
            (wave_id, Json({}), Json({})),
        )
        cur.execute(
            "insert into pieces (contact_id, wave_id, variant_id, mailer_code, status, cost_cents) "
            "values (%s, %s, %s, 'MC1', %s, %s)",
            (contact_id, wave_id, variant_id, status, cost),
        )
    conn.commit()
    return wave_id, variant_id


def test_get_contact_timeline_one_query_and_ordered(clean_db, owner_conn, one_round_trip):
    from service.ingestion import ingest_event

    contact_id = _seed_contact(owner_conn)
    ingest_event("lob", "piece.submitted", AT, {}, contact_id=contact_id)
    ingest_event("nmc", "sms.inbound", AT + timedelta(days=1), {}, contact_id=contact_id)

    timeline = one_round_trip(queries.get_contact_timeline, contact_id)
    assert [e.type for e in timeline] == ["piece.submitted", "sms.inbound"]


def test_get_pipeline_one_query_and_computes_days_quiet(clean_db, owner_conn, one_round_trip):
    from service.ingestion import ingest_event

    contact_id = _seed_contact(owner_conn, stage="responded")
    ingest_event("nmc", "sms.inbound", AT, {}, contact_id=contact_id)

    cards = one_round_trip(queries.get_pipeline)
    assert len(cards) == 1
    assert cards[0].id == contact_id
    assert cards[0].days_quiet is not None


def test_get_pipeline_excludes_non_pipeline_stages(clean_db, owner_conn, one_round_trip):
    _seed_contact(owner_conn, stage="prospect")
    _seed_contact(owner_conn, stage="won")
    assert one_round_trip(queries.get_pipeline) == []


def test_get_wave_dashboard_one_query_and_folds_stats(clean_db, owner_conn, one_round_trip):
    from service.ingestion import ingest_event

    contact_id = _seed_contact(owner_conn)
    wave_id, variant_id = _seed_variant_wave_piece(owner_conn, contact_id)
    ingest_event("nmc", "sms.inbound", AT, {}, contact_id=contact_id)

    dashboard = one_round_trip(queries.get_wave_dashboard, wave_id)
    assert dashboard.pieces_by_status == {"delivered": 1}
    assert dashboard.responses == 1
    assert dashboard.cost_cents == 73
    assert dashboard.cost_per_response_cents == 73
    assert len(dashboard.by_variant) == 1
    assert dashboard.by_variant[0].variant_id == variant_id
    assert dashboard.by_variant[0].responses == 1


def test_get_approval_queue_one_query(clean_db, owner_conn, one_round_trip):
    with owner_conn.cursor() as cur:
        cur.execute(
            "insert into waves (name, drop_number, audience_rule, variant_split) "
            "values ('draft-wave', 1, %s, %s)",
            (Json({}), Json({})),
        )
        cur.execute(
            "insert into waves (name, drop_number, audience_rule, variant_split, status) "
            "values ('sent-wave', 1, %s, %s, 'sent')",
            (Json({}), Json({})),
        )
    owner_conn.commit()

    queue = one_round_trip(queries.get_approval_queue)
    assert [w.name for w in queue] == ["draft-wave"]


def test_get_activation_board_one_query_and_flags_stalled(clean_db, owner_conn, one_round_trip):
    contact_id = _seed_contact(owner_conn, stage="won")
    old_signup = datetime.now(UTC) - timedelta(days=30)
    with owner_conn.cursor() as cur:
        cur.execute(
            "insert into activation (contact_id, signed_up_at) values (%s, %s)",
            (contact_id, old_signup),
        )
    owner_conn.commit()

    board = one_round_trip(queries.get_activation_board)
    assert len(board) == 1
    assert board[0].stalled is True


def test_list_due_nudges_one_query(clean_db, owner_conn, one_round_trip):
    due = _seed_contact(owner_conn, next_action_at=date(2026, 1, 1))
    _seed_contact(owner_conn, next_action_at=date(2099, 1, 1))  # not yet due

    nudges = one_round_trip(queries.list_due_nudges, date(2026, 6, 1))
    assert [n.contact_id for n in nudges] == [due]


def test_list_waves_one_query_all_statuses_newest_drop_first(clean_db, owner_conn, one_round_trip):
    with owner_conn.cursor() as cur:
        cur.execute(
            "insert into waves (name, drop_number, audience_rule, variant_split) "
            "values ('first-drop', 1, %s, %s)",
            (Json({}), Json({})),
        )
        cur.execute(
            "insert into waves (name, drop_number, audience_rule, variant_split, status) "
            "values ('second-drop', 2, %s, %s, 'sent')",
            (Json({}), Json({})),
        )
    owner_conn.commit()

    waves = one_round_trip(queries.list_waves)
    assert [w.name for w in waves] == ["second-drop", "first-drop"]


def test_list_variants_one_query_with_hypothesis(clean_db, owner_conn, one_round_trip):
    with owner_conn.cursor() as cur:
        cur.execute(
            "insert into variants (name, hypothesis, creative) values ('v1', 'h1', %s)",
            (Json({"headline": "x"}),),
        )
    owner_conn.commit()

    variants = one_round_trip(queries.list_variants)
    assert len(variants) == 1
    assert variants[0].name == "v1"
    assert variants[0].hypothesis == "h1"
    assert variants[0].creative == {"headline": "x"}


def test_search_contacts_one_query_matches_fields(clean_db, owner_conn, one_round_trip):
    hit = _seed_contact(owner_conn, business_name="Acme Plumbing", phone_e164="+13105551212")
    _seed_contact(owner_conn, business_name="Other Corp")

    by_name = one_round_trip(queries.search_contacts, "acme")
    assert [c.id for c in by_name] == [hit]

    by_phone = one_round_trip(queries.search_contacts, "3105551212")
    assert [c.id for c in by_phone] == [hit]

    assert one_round_trip(queries.search_contacts, "zzz-no-match") == []


def test_search_contacts_empty_query_browses_all(clean_db, owner_conn, one_round_trip):
    _seed_contact(owner_conn, business_name="A")
    _seed_contact(owner_conn, business_name="B")

    assert len(one_round_trip(queries.search_contacts, "")) == 2


def test_list_orphans_one_query_unattributed_newest_first(clean_db, owner_conn, one_round_trip):
    from service.ingestion import ingest_event

    attributed_to = _seed_contact(owner_conn)
    ingest_event("nmc", "call.inbound", AT, {}, contact_id=attributed_to)
    older = ingest_event("nmc", "sms.inbound", AT + timedelta(days=1), {"phone": "x"})
    newer = ingest_event("posthog", "page.visit", AT + timedelta(days=2), {})

    orphans = one_round_trip(queries.list_orphans)
    assert [e.id for e in orphans] == [newer, older]
