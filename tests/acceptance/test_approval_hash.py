"""Phase 5 gate: the approval-hash guard — preview returns a fingerprint of exactly
what it showed, and approve rejects it once the audience has drifted, so you approve
what you saw."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import psycopg
import pytest

from domain.errors import ValidationError
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


def _draft(conn, n) -> UUID:
    _seed_prospects(conn, n)
    variant_id = create_variant("v", "h", {})
    return draft_wave("w", 1, {"trade": ["plumber"]}, {str(variant_id): 1}, _future())


def _status(readonly_url, wave_id) -> str:
    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute("select status from waves where id = %s", (wave_id,))
            row = cur.fetchone()
            assert row is not None
            return row[0]


def test_preview_returns_a_state_hash(clean_db, owner_conn):
    wave_id = _draft(owner_conn, 2)
    preview = preview_audience(wave_id)
    assert isinstance(preview.state_hash, str)
    assert preview.state_hash


def test_approve_with_matching_hash_succeeds(clean_db, owner_conn, readonly_url):
    wave_id = _draft(owner_conn, 2)
    preview = preview_audience(wave_id)
    approve_wave(wave_id, "young", preview.state_hash)
    assert _status(readonly_url, wave_id) == "approved"


def test_approve_with_stale_hash_is_rejected(clean_db, owner_conn, readonly_url):
    wave_id = _draft(owner_conn, 2)
    preview = preview_audience(wave_id)
    _seed_prospects(owner_conn, 3)  # audience drifts after preview

    with pytest.raises(ValidationError) as exc:
        approve_wave(wave_id, "young", preview.state_hash)
    assert exc.value.code == "stale_preview"
    assert _status(readonly_url, wave_id) == "draft"  # not approved


def test_approve_without_a_hash_still_works(clean_db, owner_conn, readonly_url):
    # Backward-compatible: a trusted programmatic caller may omit the hash.
    wave_id = _draft(owner_conn, 2)
    approve_wave(wave_id, "young")
    assert _status(readonly_url, wave_id) == "approved"
