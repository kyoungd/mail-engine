"""The personal-list rule (partner-sourced-leads.md rev 5, operator 2026-08-06):

    a number is on the partner's sheet if it is in their personal list
    (<= 90 days from permission_at), or if it came off the main list and clears DNC.

The personal window waives the FTC-REGISTRY checks only. It never waives our own
do_not_call or a suppression tombstone — the entity-specific list has no
exemption in law.
"""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest

from config.params import HOUSE_PARTNER_ID
from service.assignment import (
    export_batch,
    reclaim,
    run_won_termination_step,
)
from tests.factories import new_contact

FRESH = datetime.now(UTC)


def _mk_partner(cur, name: str) -> UUID:
    cur.execute(
        "insert into partners (name, status, weekly_hours) values (%s, 'active', 10) "
        "returning id",
        (name,),
    )
    row = cur.fetchone()
    assert row is not None
    return row[0]


def _cleanup(owner_conn, prefix: str) -> None:
    with owner_conn.cursor() as cur:
        cur.execute("select id from partners where name like %s", (prefix + "%",))
        for (pid,) in cur.fetchall():
            cur.execute(
                "update contacts set owner_id = %s, assignment_batch_id = null, "
                "sourced_by_partner_id = null where owner_id = %s or "
                "sourced_by_partner_id = %s",
                (HOUSE_PARTNER_ID, pid, pid),
            )
            cur.execute("delete from assignment_batches where partner_id = %s", (pid,))
            cur.execute("delete from partners where id = %s", (pid,))
    owner_conn.commit()


@pytest.fixture(autouse=True)
def _teardown(owner_conn):
    yield
    _cleanup(owner_conn, "PL-")


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------


def test_personal_row_is_on_the_sheet_without_any_registry_check(clean_db, owner_conn):
    """310 is not a subscribed code, the number is registry-listed, and it has
    never been scrubbed — the personal window carries it onto the sheet anyway."""
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, "PL-A")
        new_contact(
            cur, phone_e164="+13105551001", dnc_registry=True, dnc_checked_at=None,
            owner_id=partner, sourced_by_partner_id=partner,
            permission_at=date.today() - timedelta(days=10),
        )
    owner_conn.commit()
    assert "+13105551001" in export_batch(partner).csv


def test_our_own_do_not_call_is_never_waived_by_permission(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, "PL-B")
        new_contact(
            cur, phone_e164="+18185551002", do_not_call=True, dnc_checked_at=FRESH,
            owner_id=partner, sourced_by_partner_id=partner,
            permission_at=date.today(),
        )
    owner_conn.commit()
    assert "+18185551002" not in export_batch(partner).csv


def test_a_tombstoned_phone_is_never_waived_by_permission(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, "PL-B2")
        new_contact(
            cur, phone_e164="+18185551012", dnc_checked_at=FRESH,
            owner_id=partner, sourced_by_partner_id=partner,
            permission_at=date.today(),
        )
        cur.execute(
            "insert into suppression_tombstones (phone_e164, channel, reason) "
            "values ('+18185551012', 'voice', 'asked us not to call')"
        )
    owner_conn.commit()
    assert "+18185551012" not in export_batch(partner).csv


def test_past_ninety_days_ordinary_rules_resume(clean_db, owner_conn):
    """Window closed: the registry-listed number drops off, the clean one stays."""
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, "PL-C")
        old = date.today() - timedelta(days=91)
        new_contact(
            cur, phone_e164="+18185551003", dnc_registry=True, dnc_checked_at=FRESH,
            owner_id=partner, sourced_by_partner_id=partner, permission_at=old,
        )
        new_contact(
            cur, phone_e164="+18185551004", dnc_checked_at=FRESH,
            owner_id=partner, sourced_by_partner_id=partner, permission_at=old,
        )
    owner_conn.commit()
    csv = export_batch(partner).csv
    assert "+18185551003" not in csv
    assert "+18185551004" in csv


def test_issued_rows_keep_todays_gates(clean_db, owner_conn):
    """No attribution ⇒ nothing changes: a registry-listed issued row stays off."""
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, "PL-D")
        cur.execute(
            "insert into assignment_batches (partner_id, idempotency_key, "
            "delivered_count, expires_at, actor) values (%s, 'pl-d', 1, "
            "now() + interval '90 days', 'test') returning id",
            (partner,),
        )
        row = cur.fetchone()
        assert row is not None
        batch = row[0]
        new_contact(
            cur, phone_e164="+18185551005", dnc_registry=True, dnc_checked_at=FRESH,
            owner_id=partner, assignment_batch_id=batch,
        )
    owner_conn.commit()
    assert "+18185551005" not in export_batch(partner).csv


def test_the_sheet_marks_which_is_which(clean_db, owner_conn):
    """origin column: sourced rows say so and carry no expiry date."""
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, "PL-E")
        cur.execute(
            "insert into assignment_batches (partner_id, idempotency_key, "
            "delivered_count, expires_at, actor) values (%s, 'pl-e', 1, "
            "now() + interval '90 days', 'test') returning id",
            (partner,),
        )
        row = cur.fetchone()
        assert row is not None
        batch = row[0]
        new_contact(
            cur, phone_e164="+18185551006", dnc_checked_at=FRESH,
            owner_id=partner, assignment_batch_id=batch,
        )
        new_contact(
            cur, phone_e164="+18185551007", dnc_checked_at=FRESH, owner_id=partner,
            sourced_by_partner_id=partner, permission_at=date.today(),
        )
    owner_conn.commit()
    csv = export_batch(partner).csv
    header, *lines = [line for line in csv.splitlines() if line.strip()]
    assert "origin" in header
    issued = next(line for line in lines if "+18185551006" in line)
    sourced = next(line for line in lines if "+18185551007" in line)
    assert "issued" in issued
    assert "sourced" in sourced
    assert sourced.count(",,") >= 1  # blank expires_at


# ---------------------------------------------------------------------------
# Safety: won-termination must reach batchless custody
# ---------------------------------------------------------------------------


def test_a_sourced_contact_who_becomes_a_customer_leaves_the_sheet(clean_db, owner_conn):
    """S-10's worst case — a partner cold-calling our own paying subscriber."""
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, "PL-F")
        cid = new_contact(
            cur, phone_e164="+18185551008", dnc_checked_at=FRESH, owner_id=partner,
            sourced_by_partner_id=partner, permission_at=date.today(),
            stage_snapshot="won",
        )
    owner_conn.commit()
    assert run_won_termination_step() == 1
    with owner_conn.cursor() as cur:
        cur.execute("select owner_id from contacts where id = %s", (cid,))
        row = cur.fetchone()
        assert row is not None
        assert row[0] == HOUSE_PARTNER_ID
    assert "+18185551008" not in export_batch(partner).csv


def test_won_termination_does_not_re_select_house_contacts_forever(clean_db, owner_conn):
    """The predicate is owner <> house, NOT a dropped batch filter: otherwise the
    nightly emits a house->house event per won pool contact per night, forever."""
    with owner_conn.cursor() as cur:
        new_contact(
            cur, phone_e164="+18185551009", dnc_checked_at=FRESH,
            stage_snapshot="won",
        )
    owner_conn.commit()
    assert run_won_termination_step() == 0
    with owner_conn.cursor() as cur:
        cur.execute("select count(*) from events where type = 'contact.reclaimed'")
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 0


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def test_reclaim_takes_issued_and_leaves_sourced(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, "PL-G")
        cur.execute(
            "insert into assignment_batches (partner_id, idempotency_key, "
            "delivered_count, expires_at, actor) values (%s, 'pl-g', 1, "
            "now() + interval '90 days', 'test') returning id",
            (partner,),
        )
        row = cur.fetchone()
        assert row is not None
        batch = row[0]
        issued = new_contact(
            cur, phone_e164="+18185551010", dnc_checked_at=FRESH,
            owner_id=partner, assignment_batch_id=batch,
        )
        sourced = new_contact(
            cur, phone_e164="+18185551011", dnc_checked_at=FRESH, owner_id=partner,
            sourced_by_partner_id=partner, permission_at=date.today(),
        )
    owner_conn.commit()
    assert reclaim(partner, "partnership paused", "test") == 1
    with owner_conn.cursor() as cur:
        cur.execute("select owner_id from contacts where id = %s", (issued,))
        row = cur.fetchone()
        assert row is not None and row[0] == HOUSE_PARTNER_ID
        cur.execute("select owner_id from contacts where id = %s", (sourced,))
        row = cur.fetchone()
        assert row is not None and row[0] == partner


def test_reclaim_include_sourced_takes_both(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, "PL-H")
        new_contact(
            cur, phone_e164="+18185551013", dnc_checked_at=FRESH, owner_id=partner,
            sourced_by_partner_id=partner, permission_at=date.today(),
        )
    owner_conn.commit()
    assert reclaim(partner, "partnership ended", "test", include_sourced=True) == 1


def test_audience_excludes_contacts_attributed_to_another_partner(clean_db, owner_conn):
    """Requirement 2: never reassigned to someone else — even back in the pool."""
    from service.assignment import assign_batch

    with owner_conn.cursor() as cur:
        cur.execute(
            "insert into dnc_subscriptions (area_code, subscribed_at) "
            "values ('818', now()) on conflict do nothing"
        )
        owner = _mk_partner(cur, "PL-I-owner")
        other = _mk_partner(cur, "PL-I-other")
        theirs = new_contact(
            cur, phone_e164="+18185551014", dnc_checked_at=FRESH,
            sourced_by_partner_id=other,  # in the pool, but attributed elsewhere
        )
        free = new_contact(cur, phone_e164="+18185551015", dnc_checked_at=FRESH)
    owner_conn.commit()
    report = assign_batch(owner, "pl-i", "test",
                          audience_rule={"area_code": ["818"]}, count=10)
    assert free in report.assigned
    assert theirs not in report.assigned
    assert theirs in report.shortfall.get("sourced_elsewhere", [])


def test_an_attributed_contact_returns_to_its_own_sourcer(clean_db, owner_conn):
    from service.assignment import assign_batch

    with owner_conn.cursor() as cur:
        cur.execute(
            "insert into dnc_subscriptions (area_code, subscribed_at) "
            "values ('818', now()) on conflict do nothing"
        )
        partner = _mk_partner(cur, "PL-J")
        cid = new_contact(
            cur, phone_e164="+18185551016", dnc_checked_at=FRESH,
            sourced_by_partner_id=partner,  # released to the pool, still theirs
        )
    owner_conn.commit()
    report = assign_batch(partner, "pl-j", "test",
                          audience_rule={"area_code": ["818"]}, count=10)
    assert cid in report.assigned
