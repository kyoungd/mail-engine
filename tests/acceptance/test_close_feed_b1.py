"""Stage B1 reconciliation (project plan B1, approved 2026-08-01): the three
deltas between Batch C's correlation and the B1 spec — mailer-code
classification against our own pieces, the 45-day lookback floor, and same-run
orphan re-resolution after a phone backfill."""

from datetime import UTC, datetime, timedelta

from jobs.close_correlation import correlate_closes
from seams.fakes import FakeCloseFeed
from seams.nmc_closes import Close
from tests.factories import new_contact

NOW = datetime.now(UTC)


def _close(id: str, phone: str | None, recorded_at: datetime, mailer_code=None):
    return Close(
        id=id, recorded_at=recorded_at, occurred_at=recorded_at,
        kind="signup_completed", phone_e164=phone, partner_code=None,
        mailer_code=mailer_code, sold_by=None, signed_up_via=None,
        subscription_status=None,
    )


def _payload(cur, external_id: str) -> dict:
    cur.execute(
        "select payload from events where source = 'nmc' and external_id = %s",
        (external_id,),
    )
    row = cur.fetchone()
    assert row is not None
    return row[0]


def test_a_real_piece_code_classifies_and_noise_nulls_out(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185560001")
        cur.execute(
            "insert into variants (name, hypothesis, creative) "
            "values ('v', 'h', '{}') returning id"
        )
        variant_id = cur.fetchone()[0]
        cur.execute(
            "insert into waves (name, drop_number, audience_rule, variant_split) "
            "values ('w', 1, '{}', '{}') returning id"
        )
        wave_id = cur.fetchone()[0]
        cur.execute(
            "insert into pieces (contact_id, wave_id, variant_id, mailer_code) "
            "values (%s, %s, %s, 'abc123xyz0') ",
            (contact_id, wave_id, variant_id),
        )
    owner_conn.commit()

    correlate_closes(
        FakeCloseFeed(
            [
                _close("cus_M1", "+18185560001", NOW, mailer_code="abc123xyz0"),
                _close("cus_M2", "+18185560002", NOW, mailer_code="SMS_SALES"),
            ]
        )
    )

    with owner_conn.cursor() as cur:
        assert _payload(cur, "cus_M1")["mailer_code"] == "abc123xyz0"
        assert _payload(cur, "cus_M2")["mailer_code"] is None  # page-default noise


def test_lookback_never_starts_later_than_45_days_ago(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        cur.execute(
            "insert into feed_watermarks (feed_name, watermark) values "
            "('nmc_closes', %s)",
            (NOW - timedelta(days=1),),  # a fresh watermark must NOT shrink the window
        )
    owner_conn.commit()

    feed = FakeCloseFeed([])
    correlate_closes(feed, now=NOW)

    assert len(feed.pulls) == 1
    assert feed.pulls[0] <= NOW - timedelta(days=45)


def test_phone_backfill_resolves_the_orphan_in_the_same_run(clean_db, owner_conn):
    # first pass: the close arrives phone-less (checkout collects none) -> orphan
    correlate_closes(FakeCloseFeed([_close("cus_B1", None, NOW - timedelta(days=2))]))

    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185560100")
    owner_conn.commit()

    # second pass: the wizard has saved the phone; the re-covered 45-day window
    # re-serves the close, the payload gains the phone, and orphan resolution
    # runs in the SAME nightly, not tomorrow's
    correlate_closes(
        FakeCloseFeed([_close("cus_B1", "+18185560100", NOW - timedelta(days=2))])
    )

    with owner_conn.cursor() as cur:
        cur.execute(
            "select contact_id, payload->>'phone' from events "
            "where source = 'nmc' and external_id = 'cus_B1'"
        )
        row = cur.fetchone()
        assert row is not None
        assert row[1] == "+18185560100"  # payload backfilled
        assert row[0] == contact_id  # attributed same run
