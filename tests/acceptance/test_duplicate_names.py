"""Duplicate-name handling: the DB's unique constraints (waves_name_active_key,
variants_name_key) must surface as structured ValidationErrors the UI can render —
never as a raw psycopg.UniqueViolation 500 (service contract §4: validation failures
return structured reasons)."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from domain.errors import ValidationError
from service.waves import cancel_wave, create_variant, draft_wave, update_wave


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


def _rule():
    return {"trade": ["plumber"]}


def test_drafting_a_duplicate_wave_name_is_a_validation_error(clean_db, owner_conn):
    _seed_prospects(owner_conn, 1)
    v = create_variant(f"v-{uuid4()}", "h", {})
    draft_wave("test drop", 1, _rule(), {str(v): 1.0}, _future())

    with pytest.raises(ValidationError) as exc:
        draft_wave("test drop", 2, _rule(), {str(v): 1.0}, _future())
    assert exc.value.code == "duplicate_name"


def test_cancelled_wave_frees_its_name(clean_db, owner_conn):
    _seed_prospects(owner_conn, 1)
    v = create_variant(f"v-{uuid4()}", "h", {})
    first = draft_wave("test drop", 1, _rule(), {str(v): 1.0}, _future())
    cancel_wave(first)

    draft_wave("test drop", 1, _rule(), {str(v): 1.0}, _future())  # no raise


def test_renaming_a_wave_onto_a_taken_name_is_a_validation_error(clean_db, owner_conn):
    _seed_prospects(owner_conn, 1)
    v = create_variant(f"v-{uuid4()}", "h", {})
    draft_wave("taken", 1, _rule(), {str(v): 1.0}, _future())
    second = draft_wave("second", 1, _rule(), {str(v): 1.0}, _future())

    with pytest.raises(ValidationError) as exc:
        update_wave(second, "taken", 1, _rule(), {str(v): 1.0}, _future())
    assert exc.value.code == "duplicate_name"


def test_duplicate_variant_name_is_a_validation_error(clean_db):
    create_variant("dup", "h", {})

    with pytest.raises(ValidationError) as exc:
        create_variant("dup", "h2", {})
    assert exc.value.code == "duplicate_name"
