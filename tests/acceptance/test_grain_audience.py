"""Phase 2 frozen acceptance tests — audience trims and resume idempotency
(design §10 tests 6 and 8).

The two trims are ordered, and the order is the point: undeliverable exclusion runs
BEFORE delivery-point dedupe, so an undeliverable contact can never win a keeper pick and
take a deliverable duplicate down with it.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg

from seams.fakes import FakePrintApi
from service.execution import execute_wave
from service.waves import approve_wave, create_variant, draft_wave, preview_audience, resolve_audience
from tests.factories import add_intake_row, new_contact

DELIVERABLE = "deliverable"
UNDELIVERABLE = "undeliverable"


def _future():
    return datetime.now(UTC).date() + timedelta(days=3)


def _contact(
    cur,
    *,
    delivery_point: str | None = None,
    deliverability: str | None = DELIVERABLE,
    verified: bool = True,
    phone: str | None = None,
    **contact_fields,
) -> UUID:
    """A contact whose PRIMARY intake row carries a verification snapshot."""
    contact_id = new_contact(
        cur, intake=False, segment="plumber-CA", phone_e164=phone, **contact_fields
    )
    add_intake_row(
        cur,
        contact_id,
        is_primary=True,
        delivery_point=delivery_point,
        deliverability=deliverability if verified else None,
        std_verified_at=datetime.now(UTC) if verified else None,
    )
    return contact_id


def _resolve(conn, rule=None):
    with conn.cursor() as cur:
        return resolve_audience(cur, rule if rule is not None else {"trade": ["plumber"]})


def _run_wave(conn, rule=None):
    variant_id = create_variant(f"v-{uuid4()}", "hypothesis", {"copy": "A"})
    wave_id = draft_wave(
        f"w-{uuid4()}", 1, rule if rule is not None else {"trade": ["plumber"]},
        {str(variant_id): 1.0}, _future(),
    )
    preview = preview_audience(wave_id)
    approve_wave(wave_id, "young", preview.state_hash)
    report = execute_wave(wave_id, FakePrintApi())
    return preview, report, wave_id


# --- §10 test 6: delivery-point dedupe -----------------------------------------


def test_two_contacts_sharing_a_delivery_point_yield_one_piece(clean_db, owner_conn, readonly_url):
    with owner_conn.cursor() as cur:
        _contact(cur, delivery_point="DP-1", phone="+18180000001")
        _contact(cur, delivery_point="DP-1")
    owner_conn.commit()

    resolved = _resolve(owner_conn)
    assert len(resolved.ids) == 1
    assert resolved.deduped_delivery_point == 1

    preview, report, wave_id = _run_wave(owner_conn)
    assert preview.count == report.pieces_created == 1
    assert preview.deduped_delivery_point == 1  # reported, never a silent cap


def test_the_keeper_is_the_phone_bearing_contact_then_the_lowest_id(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        no_phone = _contact(cur, delivery_point="DP-1")
        with_phone = _contact(cur, delivery_point="DP-1", phone="+18180000002")
    owner_conn.commit()

    ids = _resolve(owner_conn).ids
    assert ids == [with_phone]
    assert no_phone not in ids


def test_an_unverified_primary_row_does_not_dedupe(clean_db, owner_conn):
    """No verdict yet is not a delivery point. There is no homegrown normalization
    fallback — a wrong merge here silently drops real mail."""
    with owner_conn.cursor() as cur:
        _contact(cur, delivery_point=None, verified=False)
        _contact(cur, delivery_point=None, verified=False)
    owner_conn.commit()

    resolved = _resolve(owner_conn)
    assert len(resolved.ids) == 2
    assert resolved.deduped_delivery_point == 0


def test_a_non_primary_row_sharing_a_delivery_point_dedupes_nothing(clean_db, owner_conn):
    """A contact's delivery point is its PRIMARY row's — the address actually mailed.
    Other licence records for the same business are not other mailings."""
    with owner_conn.cursor() as cur:
        first = _contact(cur, delivery_point="DP-1")
        second = _contact(cur, delivery_point="DP-2")
        add_intake_row(cur, second, is_primary=False, delivery_point="DP-1")
    owner_conn.commit()

    resolved = _resolve(owner_conn)
    assert set(resolved.ids) == {first, second}
    assert resolved.deduped_delivery_point == 0


def test_seeds_are_exempt_from_the_dedupe(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        _contact(cur, delivery_point="DP-1")
        _contact(cur, delivery_point="DP-1")
        new_contact(
            cur, intake=False, is_seed=True, seed_key="seed-a", segment="seed",
            addr_line1="200 N Spring St",
        )
    owner_conn.commit()

    resolved = _resolve(owner_conn)
    assert len(resolved.ids) == 2  # one survivor + the seed, which never deduped
    assert resolved.deduped_delivery_point == 1


# --- §10 test 6: undeliverable exclusion ---------------------------------------


def test_an_undeliverable_primary_row_is_excluded_and_counted(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        good = _contact(cur, delivery_point="DP-1", deliverability=DELIVERABLE)
        _contact(cur, delivery_point="DP-2", deliverability=UNDELIVERABLE)
    owner_conn.commit()

    resolved = _resolve(owner_conn)
    assert resolved.ids == [good]
    assert resolved.excluded_undeliverable == 1


def test_an_unverified_row_is_not_excluded(clean_db, owner_conn):
    """No verdict yet is not the same fact as undeliverable."""
    with owner_conn.cursor() as cur:
        pending = _contact(cur, verified=False)
    owner_conn.commit()

    resolved = _resolve(owner_conn)
    assert resolved.ids == [pending]
    assert resolved.excluded_undeliverable == 0


def test_a_no_delivery_point_verdict_is_not_excluded(clean_db, owner_conn):
    """It stays mailable at the raw picked address, which the inherit never overwrote."""
    with owner_conn.cursor() as cur:
        no_dp = _contact(cur, delivery_point=None, deliverability=DELIVERABLE)
    owner_conn.commit()

    resolved = _resolve(owner_conn)
    assert resolved.ids == [no_dp]
    assert resolved.excluded_undeliverable == 0


def test_exclusion_runs_before_dedupe_so_the_deliverable_twin_survives(clean_db, owner_conn):
    """THE ORDERING TEST. The undeliverable contact would win the keeper pick on phone,
    so if dedupe ran first the deliverable twin would be dropped and the surviving
    contact then excluded — mailing nobody. Exclusion first means the deliverable one
    is mailed."""
    with owner_conn.cursor() as cur:
        _contact(
            cur, delivery_point="DP-1", deliverability=UNDELIVERABLE, phone="+18180000003"
        )
        deliverable = _contact(cur, delivery_point="DP-1", deliverability=DELIVERABLE)
    owner_conn.commit()

    resolved = _resolve(owner_conn)
    assert resolved.ids == [deliverable]
    assert resolved.excluded_undeliverable == 1
    assert resolved.deduped_delivery_point == 0  # only one candidate was left to keep


# --- §10 test 8: resume idempotency on mailer_code ------------------------------


def test_a_killed_drop_re_runs_clean(clean_db, owner_conn, readonly_url):
    with owner_conn.cursor() as cur:
        for _ in range(3):
            _contact(cur, delivery_point=None, verified=False)
    owner_conn.commit()

    variant_id = create_variant("v", "hypothesis", {"copy": "A"})
    wave_id = draft_wave("resume", 1, {"trade": ["plumber"]}, {str(variant_id): 1.0}, _future())
    approve_wave(wave_id, "young", preview_audience(wave_id).state_hash)

    execute_wave(wave_id, FakePrintApi())
    with owner_conn.cursor() as cur:
        cur.execute("update waves set status = 'executing' where id = %s", (wave_id,))
    owner_conn.commit()
    second = execute_wave(wave_id, FakePrintApi())

    assert second.pieces_created == 0  # every mailer_code already present
    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from pieces where wave_id = %s", (wave_id,))
            assert cur.fetchone() == (3,)
            cur.execute(
                "select count(*) from events e join pieces p on p.id = e.piece_id "
                "where p.wave_id = %s and e.type = 'piece.submitted'",
                (wave_id,),
            )
            assert cur.fetchone() == (3,)


def test_the_per_piece_lookup_resolves_by_mailer_code_on_ambiguous_merged_history(
    clean_db, owner_conn, readonly_url
):
    """Merged history makes (contact_id, wave_id) genuinely ambiguous — two wave-1 pieces
    can legitimately sit on one merged contact now the unique constraint is gone. The
    lookup must key on the mailer code, which stays one-per-piece."""
    with owner_conn.cursor() as cur:
        contact_id = _contact(cur, delivery_point=None, verified=False)
    owner_conn.commit()

    variant_id = create_variant("v", "hypothesis", {"copy": "A"})
    wave_id = draft_wave("ambig", 1, {"trade": ["plumber"]}, {str(variant_id): 1.0}, _future())
    approve_wave(wave_id, "young", preview_audience(wave_id).state_hash)

    # A second piece on the SAME (contact, wave) — the pre-swap constraint forbade this.
    with owner_conn.cursor() as cur:
        cur.execute(
            "insert into pieces (contact_id, wave_id, variant_id, mailer_code) "
            "values (%s, %s, %s, 'historic01')",
            (contact_id, wave_id, variant_id),
        )
    owner_conn.commit()

    report = execute_wave(wave_id, FakePrintApi())

    assert report.pieces_created == 1  # its own code, alongside the historic row
    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from pieces where wave_id = %s", (wave_id,))
            assert cur.fetchone() == (2,)
            # The drop submitted ITS piece, not the pre-existing one.
            cur.execute(
                "select status from pieces where wave_id = %s and mailer_code = 'historic01'",
                (wave_id,),
            )
            assert cur.fetchone() == ("created",)
