"""The referral import (partner-sourced-leads.md rev 5 §3): a partner's own
collected numbers, with the permission provenance that justifies calling them.

Fails closed on provenance — no who/when/where, no number. Resolution is by
phone, and the four cases differ: new, existing-unowned (custody moves — the
operator decision, "he worked for it"), already-theirs, and held-by-another
(conflict; nothing moves).
"""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest

from config.params import HOUSE_PARTNER_ID
from service.referrals import import_collected
from tests.factories import new_contact

FRESH = datetime.now(UTC)


def _row(**over) -> dict:
    row = {
        "business_name": "Smith Plumbing",
        "contact_name": "Bob Smith",
        "phone": "8185552001",
        "addr_line1": "123 Main St",
        "city": "Van Nuys",
        "state": "CA",
        "zip": "91401",
        "permission_by": "Bob Smith (owner)",
        "permission_at": "2026-08-05",
        "permission_where": "in person at Ferguson supply counter",
        "sourced_by": "RI-A",
    }
    row.update(over)
    return row


def _mk_partner(cur, name: str, *, status: str = "active") -> UUID:
    cur.execute(
        "insert into partners (name, status, weekly_hours) values (%s, %s, 10) "
        "returning id",
        (name, status),
    )
    r = cur.fetchone()
    assert r is not None
    return r[0]


@pytest.fixture(autouse=True)
def _teardown(owner_conn):
    yield
    with owner_conn.cursor() as cur:
        cur.execute("select id from partners where name like 'RI-%'")
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


# ---------------------------------------------------------------------------
# Provenance fails closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "missing", ["phone", "permission_by", "permission_at", "permission_where",
                "sourced_by"]
)
def test_a_row_missing_any_required_field_is_rejected_and_named(
    clean_db, owner_conn, missing
):
    with owner_conn.cursor() as cur:
        _mk_partner(cur, "RI-A")
    owner_conn.commit()
    report = import_collected([_row(**{missing: ""})], actor="test")
    assert report.created == 0
    assert len(report.rejected) == 1
    assert missing in report.rejected[0].reason


def test_an_unknown_partner_rejects_the_row(clean_db, owner_conn):
    report = import_collected([_row(sourced_by="RI-nobody")], actor="test")
    assert len(report.rejected) == 1
    assert "RI-nobody" in report.rejected[0].reason


def test_an_inactive_partner_rejects_the_row(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        _mk_partner(cur, "RI-A", status="inactive")
    owner_conn.commit()
    report = import_collected([_row()], actor="test")
    assert len(report.rejected) == 1
    assert "inactive" in report.rejected[0].reason


# ---------------------------------------------------------------------------
# The four resolution cases
# ---------------------------------------------------------------------------


def test_a_new_number_becomes_an_attributed_contact(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, "RI-A")
    owner_conn.commit()
    report = import_collected([_row()], actor="test")
    assert report.created == 1
    with owner_conn.cursor() as cur:
        cur.execute(
            "select owner_id, sourced_by_partner_id, permission_at, source "
            "from contacts where phone_e164 = '+18185552001'"
        )
        row = cur.fetchone()
        assert row is not None
        owner_id, sourced_by, permission_at, source = row
        assert owner_id == partner
        assert sourced_by == partner
        assert permission_at == date(2026, 8, 5)
        assert source != "cslb"  # must not inherit the column default


def test_an_existing_unowned_number_moves_custody_to_the_partner(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, "RI-A")
        cid = new_contact(cur, phone_e164="+18185552001", dnc_checked_at=FRESH)
    owner_conn.commit()
    report = import_collected([_row()], actor="test")
    assert report.took_custody == 1
    assert report.created == 0
    with owner_conn.cursor() as cur:
        cur.execute(
            "select owner_id, sourced_by_partner_id from contacts where id = %s", (cid,)
        )
        row = cur.fetchone()
        assert row is not None and row == (partner, partner)


def test_a_number_already_theirs_records_permission_without_moving_custody(
    clean_db, owner_conn
):
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, "RI-A")
        cur.execute(
            "insert into assignment_batches (partner_id, idempotency_key, "
            "delivered_count, expires_at, actor) values (%s, 'ri-a', 1, "
            "now() + interval '90 days', 'test') returning id",
            (partner,),
        )
        r = cur.fetchone()
        assert r is not None
        batch = r[0]
        cid = new_contact(
            cur, phone_e164="+18185552001", dnc_checked_at=FRESH,
            owner_id=partner, assignment_batch_id=batch,
        )
    owner_conn.commit()
    report = import_collected([_row()], actor="test")
    assert report.already_theirs == 1
    with owner_conn.cursor() as cur:
        cur.execute(
            "select assignment_batch_id, sourced_by_partner_id, permission_at "
            "from contacts where id = %s", (cid,)
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == batch  # custody untouched
        assert row[1] == partner
        assert row[2] == date(2026, 8, 5)


def test_a_number_held_by_another_partner_is_a_conflict_and_nothing_moves(
    clean_db, owner_conn
):
    with owner_conn.cursor() as cur:
        _mk_partner(cur, "RI-A")
        holder = _mk_partner(cur, "RI-holder")
        cid = new_contact(
            cur, phone_e164="+18185552001", dnc_checked_at=FRESH, owner_id=holder,
        )
    owner_conn.commit()
    report = import_collected([_row()], actor="test")
    assert len(report.conflicts) == 1
    conflict = report.conflicts[0]
    assert conflict.held_by == "RI-holder"
    assert conflict.activity == 0
    with owner_conn.cursor() as cur:
        cur.execute(
            "select owner_id, sourced_by_partner_id from contacts where id = %s", (cid,)
        )
        row = cur.fetchone()
        assert row is not None and row == (holder, None)


# ---------------------------------------------------------------------------
# The consults
# ---------------------------------------------------------------------------


def test_a_tombstoned_phone_re_acquires_its_suppression(clean_db, owner_conn):
    """FR-8's hard-delete must not be undone by a re-import: a person who told us
    not to call comes back suppressed, not as a fresh mailable contact."""
    with owner_conn.cursor() as cur:
        _mk_partner(cur, "RI-A")
        cur.execute(
            "insert into suppression_tombstones (phone_e164, channel, reason) "
            "values ('+18185552001', 'voice', 'opt_out')"
        )
    owner_conn.commit()
    import_collected([_row()], actor="test")
    with owner_conn.cursor() as cur:
        cur.execute(
            "select do_not_call from contacts where phone_e164 = '+18185552001'"
        )
        row = cur.fetchone()
        assert row is not None and row[0] is True


def test_every_accepted_row_records_a_permission_event(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        _mk_partner(cur, "RI-A")
    owner_conn.commit()
    import_collected([_row()], actor="test")
    with owner_conn.cursor() as cur:
        cur.execute(
            "select payload from events where type = 'contact.permission_recorded'"
        )
        rows = cur.fetchall()
        assert len(rows) == 1
        payload = rows[0][0]
        assert payload["permission_by"] == "Bob Smith (owner)"
        assert payload["permission_where"].startswith("in person")
        assert payload["sourced_by"] == "RI-A"


def test_the_report_flags_the_cliff_for_a_row_that_will_need_dnc_later(
    clean_db, owner_conn
):
    """A 310 number (unsubscribed) is on the sheet now, dead after the window —
    the operator learns the date at import, not by noticing an absence."""
    with owner_conn.cursor() as cur:
        _mk_partner(cur, "RI-A")
    owner_conn.commit()
    report = import_collected([_row(phone="3105552002")], actor="test")
    assert report.created == 1
    assert len(report.cliffs) == 1
    assert report.cliffs[0].expires_on == date(2026, 8, 5) + timedelta(days=90)
