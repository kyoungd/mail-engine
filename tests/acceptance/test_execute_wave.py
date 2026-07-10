"""Phase 3 gate: execute_wave — creates and submits pieces, emits piece.submitted,
is resumable without duplicates after a mid-drop crash, and halts on audience drift
beyond tolerance."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest

from domain.errors import ValidationError
from seams.fakes import FakePrintApi
from service.execution import execute_wave
from service.waves import approve_wave, create_variant, draft_wave


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


def _approved_wave(conn, contact_count) -> UUID:
    _seed_prospects(conn, contact_count)
    variant_id = create_variant(f"v-{uuid4()}", "hypothesis", {"copy": "A"})
    wave_id = draft_wave(f"w-{uuid4()}", 1, {"trade": ["plumber"]}, {str(variant_id): 1.0}, _future())
    approve_wave(wave_id, "young")
    return wave_id


def _one(readonly_url, query, params):
    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            assert row is not None
            return row


def test_execute_creates_submits_and_emits_events(clean_db, owner_conn, readonly_url):
    wave_id = _approved_wave(owner_conn, 3)
    fake = FakePrintApi()

    report = execute_wave(wave_id, fake)

    assert report.halted is False
    assert report.pieces_created == 3
    assert report.pieces_submitted == 3
    assert fake.submit_calls == 3

    total, distinct_codes = _one(
        readonly_url,
        "select count(*), count(distinct mailer_code) from pieces where wave_id = %s",
        (wave_id,),
    )
    assert total == 3
    assert distinct_codes == 3
    assert _one(readonly_url, "select status from waves where id = %s", (wave_id,))[0] == "sent"
    submitted = _one(
        readonly_url,
        "select count(*) from pieces where wave_id = %s and status = 'submitted' "
        "and lob_id is not null",
        (wave_id,),
    )[0]
    assert submitted == 3
    events = _one(
        readonly_url,
        "select count(*) from events where type = 'piece.submitted' and source = 'system'",
        (),
    )[0]
    assert events == 3


def test_execute_is_resumable_without_duplicates(clean_db, owner_conn, readonly_url):
    wave_id = _approved_wave(owner_conn, 5)
    fake = FakePrintApi(fail_after=2)

    with pytest.raises(RuntimeError):
        execute_wave(wave_id, fake)

    partial = _one(
        readonly_url,
        "select count(*) from pieces where wave_id = %s and status = 'submitted'",
        (wave_id,),
    )[0]
    assert partial == 2
    assert _one(readonly_url, "select status from waves where id = %s", (wave_id,))[0] == "executing"

    fake.fail_after = None
    report = execute_wave(wave_id, fake)

    assert report.halted is False
    total, distinct_codes = _one(
        readonly_url,
        "select count(*), count(distinct mailer_code) from pieces where wave_id = %s",
        (wave_id,),
    )
    assert total == 5
    assert distinct_codes == 5
    assert fake.submit_calls == 5  # each piece printed exactly once across both runs
    events = _one(
        readonly_url, "select count(*) from events where type = 'piece.submitted'", ()
    )[0]
    assert events == 5  # piece.submitted stayed idempotent on the resume
    assert _one(readonly_url, "select status from waves where id = %s", (wave_id,))[0] == "sent"


def test_execute_halts_on_audience_drift(clean_db, owner_conn, readonly_url):
    wave_id = _approved_wave(owner_conn, 10)
    _seed_prospects(owner_conn, 3)  # +30% after approval
    fake = FakePrintApi()

    report = execute_wave(wave_id, fake)

    assert report.halted is True
    assert report.approved_count == 10
    assert report.resolved_count == 13
    assert report.pieces_created == 0
    assert fake.submit_calls == 0
    assert _one(readonly_url, "select count(*) from pieces where wave_id = %s", (wave_id,))[0] == 0
    assert _one(readonly_url, "select status from waves where id = %s", (wave_id,))[0] == "approved"


def test_execute_within_tolerance_proceeds(clean_db, owner_conn):
    wave_id = _approved_wave(owner_conn, 10)
    with owner_conn.cursor() as cur:
        cur.execute("update contacts set do_not_mail = true where id in "
                    "(select id from contacts where trade = 'plumber' order by id limit 1)")
    owner_conn.commit()  # -10%, exactly at tolerance, not beyond

    report = execute_wave(wave_id, FakePrintApi())

    assert report.halted is False
    assert report.resolved_count == 9
    assert report.pieces_created == 9


def test_execute_rejects_a_draft_wave(clean_db, owner_conn):
    _seed_prospects(owner_conn, 1)
    variant_id = create_variant("v", "h", {})
    wave_id = draft_wave("w", 1, {"trade": ["plumber"]}, {str(variant_id): 1}, _future())
    with pytest.raises(ValidationError):
        execute_wave(wave_id, FakePrintApi())


def test_execute_rejects_an_already_sent_wave(clean_db, owner_conn):
    wave_id = _approved_wave(owner_conn, 2)
    execute_wave(wave_id, FakePrintApi())
    with pytest.raises(ValidationError):
        execute_wave(wave_id, FakePrintApi())
