"""Phase 2 gate: the wave lifecycle draft -> preview -> approve -> cancel, the
audience resolver (shared by preview and execution), and every documented approval
precondition."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Json

from domain.errors import ValidationError
from service.queries import get_variant
from service.waves import (
    approve_wave,
    cancel_wave,
    create_variant,
    draft_wave,
    preview_audience,
    resolve_audience,
    update_variant,
    update_wave,
)


def _future():
    return datetime.now(UTC).date() + timedelta(days=5)


def _seed_prospects(conn, n, trade="plumber", segment="plumber-CA", do_not_mail=False):
    ids = []
    with conn.cursor() as cur:
        for _ in range(n):
            cur.execute(
                "insert into contacts (trade, segment, do_not_mail) values (%s, %s, %s) "
                "returning id",
                (trade, segment, do_not_mail),
            )
            ids.append(cur.fetchone()[0])
    conn.commit()
    return ids


def _wave_status(readonly_url, wave_id) -> str:
    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute("select status from waves where id = %s", (wave_id,))
            row = cur.fetchone()
            assert row is not None
            return row[0]


# --- create_variant ------------------------------------------------------------


def test_create_variant_requires_nonempty_hypothesis(clean_db):
    with pytest.raises(ValidationError):
        create_variant("v", "   ", {"copy": "x"})


def test_create_variant_returns_id(clean_db):
    assert create_variant("v1", "tests headline A vs B", {"copy": "A"}) is not None


# --- freeze at approval --------------------------------------------------------


def _approved_wave(owner_conn, variant_id, name="freeze-wave"):
    _seed_prospects(owner_conn, 3)
    wave_id = draft_wave(name, 1, {"trade": ["plumber"]}, {str(variant_id): 1.0}, _future())
    approve_wave(wave_id, "young", preview_audience(wave_id).state_hash)
    return wave_id


def test_update_variant_edits_an_unapproved_variant(clean_db):
    v = create_variant("v1", "hypothesis", {"front": "A"})
    update_variant(v, "v1 revised", "sharper hypothesis", {"front": "B"})
    got = get_variant(v)
    assert got.name == "v1 revised"
    assert got.hypothesis == "sharper hypothesis"
    assert got.creative["front"] == "B"


def test_update_variant_rejects_once_approved(clean_db, owner_conn):
    v = create_variant("v1", "hypothesis", {"front": "A"})
    _approved_wave(owner_conn, v)
    with pytest.raises(ValidationError):
        update_variant(v, "v1", "hypothesis", {"front": "B"})


def test_variant_stays_frozen_after_the_wave_is_sent(clean_db, owner_conn):
    # status walks approved -> executing -> sent. Keying the freeze on
    # status == 'approved' would thaw a variant the moment it mailed; the freeze
    # keys on approved_at, which never clears.
    v = create_variant("v1", "hypothesis", {"front": "A"})
    wave_id = _approved_wave(owner_conn, v)
    with owner_conn.cursor() as cur:
        cur.execute(
            "update waves set status = 'sent', executed_at = now() where id = %s",
            (wave_id,),
        )
    owner_conn.commit()

    with pytest.raises(ValidationError):
        update_variant(v, "v1", "hypothesis", {"front": "B"})


def test_variant_in_a_draft_wave_is_still_editable(clean_db, owner_conn):
    _seed_prospects(owner_conn, 3)
    v = create_variant("v1", "hypothesis", {"front": "A"})
    draft_wave("draft-wave", 1, {"trade": ["plumber"]}, {str(v): 1.0}, _future())

    update_variant(v, "v1", "hypothesis", {"front": "B"})
    assert get_variant(v).creative["front"] == "B"


def test_variant_stays_frozen_after_an_approved_wave_is_cancelled(clean_db, owner_conn):
    # approval is a promise that was made; cancelling the wave does not unmake it
    v = create_variant("v1", "hypothesis", {"front": "A"})
    wave_id = _approved_wave(owner_conn, v)
    cancel_wave(wave_id)

    with pytest.raises(ValidationError):
        update_variant(v, "v1", "hypothesis", {"front": "B"})


def test_update_variant_still_requires_a_hypothesis(clean_db):
    v = create_variant("v1", "hypothesis", {})
    with pytest.raises(ValidationError):
        update_variant(v, "v1", "   ", {})


# --- lifecycle -----------------------------------------------------------------


def test_draft_preview_approve(clean_db, owner_conn, readonly_url):
    _seed_prospects(owner_conn, 3)
    variant_id = create_variant("v1", "hypothesis", {})
    wave_id = draft_wave("wave-1", 1, {"trade": ["plumber"]}, {str(variant_id): 1.0}, _future())

    preview = preview_audience(wave_id)
    assert preview.count == 3
    assert preview.by_stage.get("prospect") == 3
    assert preview.by_segment.get("plumber-CA") == 3
    assert len(preview.sample) == 3
    assert preview.estimated_cost_cents == 3 * 73

    approve_wave(wave_id, "young")
    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status, approved_by, approved_at from waves where id = %s", (wave_id,)
            )
            row = cur.fetchone()
            assert row is not None
            status, who, approved_at = row
    assert status == "approved"
    assert who == "young"
    assert approved_at is not None


def test_preview_matches_resolution_and_is_deterministic(clean_db, owner_conn):
    _seed_prospects(owner_conn, 4)
    wave_id = draft_wave("w", 1, {"trade": ["plumber"]}, {}, _future())

    first = preview_audience(wave_id)
    second = preview_audience(wave_id)
    assert first.count == second.count == 4

    with owner_conn.cursor() as cur:
        resolved = resolve_audience(cur, {"trade": ["plumber"]})
    assert len(resolved) == 4


def test_audience_always_excludes_do_not_mail(clean_db, owner_conn):
    _seed_prospects(owner_conn, 2)
    _seed_prospects(owner_conn, 1, do_not_mail=True)
    wave_id = draft_wave("w", 1, {"trade": ["plumber"]}, {}, _future())
    assert preview_audience(wave_id).count == 2


def test_audience_rule_filters_by_source(clean_db, owner_conn):
    """FBN-style targeting: a trade-less list is addressed by its source."""
    _seed_prospects(owner_conn, 2)  # source defaults to 'cslb'
    with owner_conn.cursor() as cur:
        cur.execute("insert into contacts (segment, source) values ('fbn-ca-2026', 'fbn-ca-2026')")
    owner_conn.commit()

    wave_id = draft_wave("fbn-wave", 1, {"source": ["fbn-ca-2026"]}, {}, _future())
    assert preview_audience(wave_id).count == 1


def test_audience_rule_filters_by_city_case_insensitive_and_zip_prefix(clean_db, owner_conn):
    """Region targeting: SFV = a bag of cities or a ZIP band, not a county."""
    with owner_conn.cursor() as cur:
        cur.execute(
            "insert into contacts (trade, addr_city, addr_zip) values "
            "('hvac', 'VAN NUYS', '91406'), "
            "('hvac', 'Northridge', '91324'), "
            "('hvac', 'Long Beach', '90802')"
        )
    owner_conn.commit()

    wave_id = draft_wave("sfv-city", 1, {"city": ["Van Nuys", "northridge"]}, {}, _future())
    assert preview_audience(wave_id).count == 2

    zip_wave = draft_wave("sfv-zip", 1, {"zip_prefix": ["913", "914"]}, {}, _future())
    assert preview_audience(zip_wave).count == 2

    combo = draft_wave("sfv-combo", 1, {"trade": ["hvac"], "zip_prefix": ["908"]}, {}, _future())
    assert preview_audience(combo).count == 1


def test_limit_takes_deterministic_unbiased_sample(clean_db, owner_conn):
    _seed_prospects(owner_conn, 20)
    wave_id = draft_wave("w", 1, {"trade": ["plumber"], "limit": 5}, {}, _future())

    first = preview_audience(wave_id)
    second = preview_audience(wave_id)
    assert first.count == 5
    assert first.state_hash == second.state_hash  # same sample every resolve

    with owner_conn.cursor() as cur:
        sampled = resolve_audience(cur, {"trade": ["plumber"], "limit": 5})
        full = resolve_audience(cur, {"trade": ["plumber"]})
    # exact expectation: md5-of-uuid order (the unbiased deterministic sample)
    import hashlib

    expected = sorted(full, key=lambda u: hashlib.md5(str(u).encode()).hexdigest())[:5]
    assert sampled == expected


def test_limit_must_be_positive_integer(clean_db):
    for bad in (0, -3, "500", True, 2.5):
        with pytest.raises(ValidationError):
            draft_wave("w-bad", 1, {"limit": bad}, {}, _future())


def test_not_responded_to_wave_targets_only_non_responders(clean_db, owner_conn):
    non_responder, responder = _seed_prospects(owner_conn, 2)
    variant_id = create_variant("v", "h", {})
    with owner_conn.cursor() as cur:
        cur.execute(
            "insert into waves (name, drop_number, audience_rule, variant_split) "
            "values ('drop1', 1, %s, %s) returning id",
            (Json({}), Json({})),
        )
        wave1 = cur.fetchone()[0]
        for contact_id in (non_responder, responder):
            cur.execute(
                "insert into pieces (contact_id, wave_id, variant_id, mailer_code) "
                "values (%s, %s, %s, %s)",
                (contact_id, wave1, variant_id, f"MC-{contact_id}"),
            )
        # the responder has advanced past in_sequence
        cur.execute("update contacts set stage_snapshot = 'responded' where id = %s", (responder,))
    owner_conn.commit()

    with owner_conn.cursor() as cur:
        resolved = resolve_audience(cur, {"not_responded_to_wave": str(wave1)})
    assert resolved == [non_responder]


# --- approval preconditions ----------------------------------------------------


def test_approve_rejects_past_schedule(clean_db, owner_conn):
    _seed_prospects(owner_conn, 1)
    variant_id = create_variant("v", "h", {})
    wave_id = draft_wave(
        "w", 1, {"trade": ["plumber"]}, {str(variant_id): 1}, datetime.now(UTC).date()
    )
    with pytest.raises(ValidationError):
        approve_wave(wave_id, "young")


def test_approve_rejects_empty_audience(clean_db, owner_conn):
    variant_id = create_variant("v", "h", {})
    wave_id = draft_wave("w", 1, {"trade": ["nobody"]}, {str(variant_id): 1}, _future())
    with pytest.raises(ValidationError):
        approve_wave(wave_id, "young")


def test_approve_rejects_unknown_variant(clean_db, owner_conn):
    _seed_prospects(owner_conn, 1)
    wave_id = draft_wave("w", 1, {"trade": ["plumber"]}, {str(uuid4()): 1}, _future())
    with pytest.raises(ValidationError):
        approve_wave(wave_id, "young")


def test_approve_only_from_draft(clean_db, owner_conn):
    _seed_prospects(owner_conn, 1)
    variant_id = create_variant("v", "h", {})
    wave_id = draft_wave("w", 1, {"trade": ["plumber"]}, {str(variant_id): 1}, _future())
    approve_wave(wave_id, "young")
    with pytest.raises(ValidationError):
        approve_wave(wave_id, "young")


def test_draft_rejects_unknown_audience_key(clean_db):
    with pytest.raises(ValidationError):
        draft_wave("w", 1, {"bogus": ["x"]}, {}, _future())


# --- update (draft-only edit) ----------------------------------------------------


def test_update_wave_edits_a_draft_in_place(clean_db, owner_conn, readonly_url):
    _seed_prospects(owner_conn, 2)
    v1 = create_variant("v1", "h", {})
    v2 = create_variant("v2", "h", {})
    wave_id = draft_wave("w", 1, {"trade": ["plumber"]}, {str(v1): 1}, _future())

    later = _future() + timedelta(days=1)
    update_wave(wave_id, "w renamed", 2, {"trade": ["plumber"], "limit": 1}, {str(v2): 1}, later)

    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select name, drop_number, audience_rule, variant_split, scheduled_for "
                "from waves where id = %s",
                (wave_id,),
            )
            row = cur.fetchone()
    assert row == ("w renamed", 2, {"trade": ["plumber"], "limit": 1}, {str(v2): 1}, later)


def test_update_wave_rejected_once_approved(clean_db, owner_conn):
    _seed_prospects(owner_conn, 1)
    variant_id = create_variant("v", "h", {})
    wave_id = draft_wave("w", 1, {"trade": ["plumber"]}, {str(variant_id): 1}, _future())
    approve_wave(wave_id, "young")
    with pytest.raises(ValidationError) as exc:
        update_wave(wave_id, "w2", 1, {"trade": ["plumber"]}, {str(variant_id): 1}, _future())
    assert exc.value.code == "not_draft"


def test_update_wave_validates_audience_rule(clean_db, owner_conn):
    wave_id = draft_wave("w", 1, {"trade": ["plumber"]}, {}, _future())
    with pytest.raises(ValidationError):
        update_wave(wave_id, "w", 1, {"bogus": ["x"]}, {}, _future())


def test_edit_after_preview_invalidates_the_hash(clean_db, owner_conn):
    _seed_prospects(owner_conn, 2)
    variant_id = create_variant("v", "h", {})
    wave_id = draft_wave("w", 1, {"trade": ["plumber"]}, {str(variant_id): 1}, _future())
    stale = preview_audience(wave_id).state_hash

    update_wave(
        wave_id, "w", 1, {"trade": ["plumber"], "limit": 1}, {str(variant_id): 1}, _future()
    )
    with pytest.raises(ValidationError) as exc:
        approve_wave(wave_id, "young", stale)
    assert exc.value.code == "stale_preview"

    fresh = preview_audience(wave_id).state_hash
    approve_wave(wave_id, "young", fresh)


# --- name uniqueness scoped to non-cancelled waves --------------------------------


def test_cancelled_wave_frees_its_name(clean_db, owner_conn):
    first = draft_wave("w", 1, {"trade": ["plumber"]}, {}, _future())
    cancel_wave(first)
    assert draft_wave("w", 1, {"trade": ["plumber"]}, {}, _future()) != first


def test_active_wave_name_still_unique(clean_db, owner_conn):
    draft_wave("w", 1, {"trade": ["plumber"]}, {}, _future())
    with pytest.raises(psycopg.errors.UniqueViolation):
        draft_wave("w", 1, {"trade": ["plumber"]}, {}, _future())


# --- cancel --------------------------------------------------------------------


def test_cancel_valid_from_draft_and_approved(clean_db, owner_conn, readonly_url):
    _seed_prospects(owner_conn, 1)
    variant_id = create_variant("v", "h", {})

    draft = draft_wave("w", 1, {"trade": ["plumber"]}, {str(variant_id): 1}, _future())
    cancel_wave(draft)
    assert _wave_status(readonly_url, draft) == "cancelled"

    approved = draft_wave("w2", 1, {"trade": ["plumber"]}, {str(variant_id): 1}, _future())
    approve_wave(approved, "young")
    cancel_wave(approved)
    assert _wave_status(readonly_url, approved) == "cancelled"


def test_cancel_rejected_once_executing(clean_db, owner_conn):
    wave_id = draft_wave("w", 1, {"trade": ["plumber"]}, {}, _future())
    with owner_conn.cursor() as cur:
        cur.execute("update waves set status = 'executing' where id = %s", (wave_id,))
    owner_conn.commit()
    with pytest.raises(ValidationError):
        cancel_wave(wave_id)
