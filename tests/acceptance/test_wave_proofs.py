"""Phase 3/5 gate: the proof — a Lob test-mode render of each variant, shown at the
approval screen, plus the drift guard that now covers the creative (editing a variant's
creative after you previewed/proofed it makes approval fail stale_preview)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest

from domain.errors import ValidationError
from seams.fakes import FakePrintApi
from service.waves import (
    approve_wave,
    create_variant,
    draft_wave,
    preview_audience,
    update_variant,
    wave_proofs,
)


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


def _status(readonly_url, wave_id) -> str:
    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute("select status from waves where id = %s", (wave_id,))
            row = cur.fetchone()
            assert row is not None
            return row[0]


def test_wave_proofs_returns_one_proof_per_variant(clean_db, owner_conn):
    _seed_prospects(owner_conn, 2)
    v1 = create_variant(f"A-{uuid4()}", "hA", {"front": "fa", "back": "ba"})
    v2 = create_variant(f"B-{uuid4()}", "hB", {"front": "fb", "back": "bb"})
    wave_id = draft_wave(
        f"w-{uuid4()}", 1, {"trade": ["plumber"]}, {str(v1): 0.5, str(v2): 0.5}, _future()
    )

    proofs = wave_proofs(wave_id, FakePrintApi())

    assert {p.variant_id for p in proofs} == {v1, v2}
    assert all(p.pdf_url for p in proofs)


def test_approve_rejects_creative_edited_after_preview(clean_db, owner_conn, readonly_url):
    _seed_prospects(owner_conn, 2)
    v1 = create_variant(f"A-{uuid4()}", "hA", {"front": "v1", "back": "b"})
    wave_id = draft_wave(f"w-{uuid4()}", 1, {"trade": ["plumber"]}, {str(v1): 1.0}, _future())
    stale = preview_audience(wave_id).state_hash

    update_variant(v1, f"A-{uuid4()}", "hA", {"front": "EDITED", "back": "b"})  # creative changed

    with pytest.raises(ValidationError) as exc:
        approve_wave(wave_id, "young", stale)
    assert exc.value.code == "stale_preview"

    fresh = preview_audience(wave_id).state_hash  # re-preview captures the new creative
    approve_wave(wave_id, "young", fresh)
    assert _status(readonly_url, wave_id) == "approved"
