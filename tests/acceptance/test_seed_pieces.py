"""Seed pieces (PRD FR-4/FR-7): a founder-address contact flagged is_seed rides every
wave as one extra piece (the physical print-quality check), but is excluded from every
response metric — a seed never responds, so counting it would deflate the rate — and
never enters the pipeline or judgment machinery."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import psycopg

from config.params import DEFAULT_PARAMS
from judgment.rules.returned_mail import RULE as returned_mail
from seams.fakes import FakePrintApi
from service.execution import execute_wave
from service.queries import get_pipeline, get_wave_dashboard
from service.waves import approve_wave, create_variant, draft_wave, preview_audience


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


def _make_seed_contact(conn, name, stage="prospect") -> UUID:
    cid = uuid4()
    key = "seed-" + name.lower().replace(" ", "-")
    with conn.cursor() as cur:
        cur.execute(
            "insert into contacts (id, list_key, business_name, is_seed, segment, "
            "stage_snapshot, addr_line1, addr_city, addr_state, addr_zip) values "
            "(%s, %s, %s, true, 'seed', %s, '200 N Spring St', 'Los Angeles', 'CA', '90012')",
            (cid, key, name, stage),
        )
    conn.commit()
    return cid


def _draft(conn, rule) -> UUID:
    variant_id = create_variant(f"v-{uuid4()}", "h", {"copy": "A"})
    return draft_wave(f"w-{uuid4()}", 1, rule, {str(variant_id): 1.0}, _future())


def _approved(conn, rule) -> UUID:
    wave_id = _draft(conn, rule)
    approve_wave(wave_id, "young")
    return wave_id


def _event(conn, contact_id, etype):
    with conn.cursor() as cur:
        cur.execute(
            "insert into events (contact_id, source, type, occurred_at, payload) "
            "values (%s, 'nmc', %s, now(), '{}')",
            (contact_id, etype),
        )
    conn.commit()


def _scalar(url, query, params=()):
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            assert row is not None
            return row[0]


def test_seed_is_appended_to_every_audience(clean_db, owner_conn):
    _seed_prospects(owner_conn, 3)
    _make_seed_contact(owner_conn, "Young HQ")
    preview = preview_audience(_draft(owner_conn, {"trade": ["plumber"]}))
    assert preview.count == 4  # 3 plumbers + 1 seed fire
    assert preview.seed_count == 1  # ...rendered distinctly


def test_preview_reports_seed_count_and_total_includes_seeds(clean_db, owner_conn):
    _seed_prospects(owner_conn, 5)
    _make_seed_contact(owner_conn, "Young HQ")
    _make_seed_contact(owner_conn, "Partner HQ")
    preview = preview_audience(_draft(owner_conn, {"trade": ["plumber"]}))
    assert preview.count == 7
    assert preview.seed_count == 2


def test_seed_piece_is_created_and_submitted_in_a_drop(clean_db, owner_conn, readonly_url):
    _seed_prospects(owner_conn, 2)
    seed_id = _make_seed_contact(owner_conn, "Young HQ")
    wave_id = _approved(owner_conn, {"trade": ["plumber"]})

    execute_wave(wave_id, FakePrintApi())

    assert _scalar(readonly_url, "select count(*) from pieces where contact_id = %s", (seed_id,)) == 1
    assert _scalar(readonly_url, "select count(*) from pieces where wave_id = %s", (wave_id,)) == 3


def test_seed_excluded_from_wave_dashboard_response_rate(clean_db, owner_conn, readonly_url):
    # THE invariant: a seed piece must not deflate the response rate.
    plumbers = _seed_prospects(owner_conn, 2)
    _make_seed_contact(owner_conn, "Young HQ")
    wave_id = _approved(owner_conn, {"trade": ["plumber"]})
    execute_wave(wave_id, FakePrintApi())
    _event(owner_conn, plumbers[0], "sms.inbound")  # 1 of 2 plumbers responds

    dash = get_wave_dashboard(wave_id)

    assert dash.responses == 1
    assert sum(v.pieces for v in dash.by_variant) == 2  # seed piece NOT in the denominator


def test_seed_excluded_from_pipeline(clean_db, owner_conn):
    seed_id = _make_seed_contact(owner_conn, "Young HQ", stage="responded")
    assert seed_id not in [c.id for c in get_pipeline()]


def test_returned_mail_ignores_seed_pieces(clean_db, owner_conn, readonly_url):
    seed_id = _make_seed_contact(owner_conn, "Young HQ")
    _event(owner_conn, seed_id, "piece.returned")  # a seed's mail bounced (twice)
    _event(owner_conn, seed_id, "piece.returned")

    with psycopg.connect(readonly_url) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            hits = returned_mail.evaluate(cur, DEFAULT_PARAMS, date.today())

    assert all(str(seed_id) not in h.facts.get("contacts", []) for h in hits)
