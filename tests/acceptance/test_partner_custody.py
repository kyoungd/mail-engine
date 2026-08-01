"""Partner Phase 1 gate (partner-lead-assignment-implementation.md, Batch A, frozen
2026-08-01): the custody foundation. Migration 0009's shape (partners incl. the R1
report/feed columns, assignment_batches, feed_watermarks, owner_id, the exclusivity
index), the single emitting writer `set_owner`, the event-confirmed `current_owner`
derivation with the genesis rule, recipient resolution by partner id, and the
partners CLI upsert."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from config.params import HOUSE_PARTNER_ID
from derivation.custody import OWNERSHIP_EVENT_TYPES, current_owner
from jobs.partners_cli import main as partners_cli
from judgment import digest
from seams.fakes import FakeSender
from service.custody import set_owner
from service.ingestion import event_from_row
from tests.factories import new_contact

AS_OF = datetime.now(UTC).date()


def _john_id(cur) -> UUID:
    cur.execute("select id from partners where name = 'John'")
    row = cur.fetchone()
    assert row is not None, "migration 0009 seeds the John row"
    return row[0]


def _ownership_events(cur, contact_id):
    cur.execute(
        "select id, contact_id, piece_id, source, type, occurred_at, ingested_at, "
        "external_id, payload from events where contact_id = %s and type = any(%s) "
        "order by occurred_at, id",
        (contact_id, list(OWNERSHIP_EVENT_TYPES)),
    )
    return [event_from_row(r) for r in cur.fetchall()]


def _column_owner(cur, contact_id) -> UUID:
    cur.execute("select owner_id from contacts where id = %s", (contact_id,))
    row = cur.fetchone()
    assert row is not None
    return row[0]


# ----------------------------------------------------------------------------------
# 1. Migration shape (idempotence itself is test_migrations_idempotent's generic)
# ----------------------------------------------------------------------------------


def test_partners_table_shape_including_r1_columns(owner_conn):
    with owner_conn.cursor() as cur:
        cur.execute(
            "select column_name from information_schema.columns "
            "where table_schema = 'public' and table_name = 'partners'"
        )
        columns = {r[0] for r in cur.fetchall()}
    assert {
        "id", "name", "status", "channel", "channel_address",
        "radius_miles", "weekly_hours", "created_at",
        # R1 report/feed columns (partner-report-implementation.md R1, ride 0009)
        "sales_rep_id", "partner_code", "last_report_at", "last_export_at",
    } <= columns


def test_house_row_is_seeded_with_pinned_id_and_email_channel(owner_conn):
    with owner_conn.cursor() as cur:
        cur.execute(
            "select name, status, channel, channel_address from partners where id = %s",
            (HOUSE_PARTNER_ID,),
        )
        row = cur.fetchone()
    assert row is not None, "the house row's identity is pinned, not discovered"
    name, status, channel, channel_address = row
    assert name == "Young"
    assert status == "active"
    assert channel == "email"
    assert channel_address == "young@nevermisscall.com"


def test_john_row_is_seeded(owner_conn):
    with owner_conn.cursor() as cur:
        _john_id(cur)


def test_contacts_owner_text_column_is_gone_owner_id_defaults_to_house(owner_conn):
    with owner_conn.cursor() as cur:
        cur.execute(
            "select column_name, column_default, is_nullable "
            "from information_schema.columns "
            "where table_schema = 'public' and table_name = 'contacts' "
            "and column_name in ('owner', 'owner_id')"
        )
        cols = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
    assert "owner" not in cols, "the text column dies with the FK (revision 7)"
    assert "owner_id" in cols
    default, nullable = cols["owner_id"]
    assert nullable == "NO"
    assert str(HOUSE_PARTNER_ID) in (default or "")


def test_assignment_batches_and_feed_watermarks_exist(owner_conn):
    with owner_conn.cursor() as cur:
        cur.execute(
            "select column_name from information_schema.columns "
            "where table_schema = 'public' and table_name = 'assignment_batches'"
        )
        batch_cols = {r[0] for r in cur.fetchall()}
        cur.execute(
            "select column_name from information_schema.columns "
            "where table_schema = 'public' and table_name = 'feed_watermarks'"
        )
        watermark_cols = {r[0] for r in cur.fetchall()}
    assert {
        "id", "partner_id", "idempotency_key", "requested_count", "delivered_count",
        "expires_at", "actor", "created_at", "request", "request_hash",
    } <= batch_cols
    assert {"feed_name", "watermark", "updated_at"} <= watermark_cols


def test_exclusivity_index_one_assigned_row_per_phone(owner_conn):
    with owner_conn.cursor() as cur:
        cur.execute(
            "select indexdef from pg_indexes where tablename = 'contacts' "
            "and indexname = 'contacts_assigned_phone_unique'"
        )
        row = cur.fetchone()
    assert row is not None
    indexdef = row[0]
    assert "UNIQUE" in indexdef
    assert "assignment_batch_id IS NOT NULL" in indexdef


def test_intake_shaped_insert_lands_on_the_house_row(clean_db, owner_conn):
    """load_list / ensure_seed_contacts INSERT without any owner column — the
    migration default is load-bearing (revision 5)."""
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur)
        assert _column_owner(cur, contact_id) == HOUSE_PARTNER_ID
    owner_conn.rollback()


# ----------------------------------------------------------------------------------
# 2. set_owner — the single emitting writer
# ----------------------------------------------------------------------------------


def test_set_owner_assign_writes_column_pointer_and_event_atomically(clean_db, owner_conn):
    expires = datetime.now(UTC) + timedelta(days=90)
    with owner_conn.cursor() as cur:
        john = _john_id(cur)
        contact_id = new_contact(cur)
        cur.execute(
            "insert into assignment_batches (partner_id, idempotency_key, actor) "
            "values (%s, 'k-1', 'young') returning id",
            (john,),
        )
        batch_id = cur.fetchone()[0]
        set_owner(
            cur, contact_id, john,
            event_type="contact.assigned", reason="assignment", actor="young",
            batch_id=batch_id, expires_at=expires,
        )
        assert _column_owner(cur, contact_id) == john
        cur.execute("select assignment_batch_id from contacts where id = %s", (contact_id,))
        assert cur.fetchone()[0] == batch_id
        events = _ownership_events(cur, contact_id)
        assert [e.type for e in events] == ["contact.assigned"]
        payload = events[0].payload
        assert payload["new_owner_id"] == str(john)
        assert payload["previous_owner_id"] == str(HOUSE_PARTNER_ID)
        assert payload["actor"] == "young"
        assert payload["batch_id"] == str(batch_id)
        assert payload["expires_at"] == expires.isoformat()
    owner_conn.rollback()


def test_set_owner_event_type_mapping_expire_and_reclaim(clean_db, owner_conn):
    """Expiry alone emits contact.assignment_expired; every other return to the house
    emits contact.reclaimed with the reason in the payload."""
    with owner_conn.cursor() as cur:
        john = _john_id(cur)
        expired = new_contact(cur)
        reclaimed = new_contact(cur)
        for contact in (expired, reclaimed):
            set_owner(cur, contact, john,
                      event_type="contact.assigned", reason="assignment", actor="young")
        set_owner(cur, expired, HOUSE_PARTNER_ID,
                  event_type="contact.assignment_expired", reason="expiry", actor="system")
        set_owner(cur, reclaimed, HOUSE_PARTNER_ID,
                  event_type="contact.reclaimed", reason="voice_suppressed", actor="system")
        assert _column_owner(cur, expired) == HOUSE_PARTNER_ID
        assert _column_owner(cur, reclaimed) == HOUSE_PARTNER_ID
        cur.execute(
            "select assignment_batch_id from contacts where id = any(%s)",
            ([expired, reclaimed],),
        )
        assert all(r[0] is None for r in cur.fetchall())
        assert _ownership_events(cur, expired)[-1].type == "contact.assignment_expired"
        last = _ownership_events(cur, reclaimed)[-1]
        assert last.type == "contact.reclaimed"
        assert last.payload["reason"] == "voice_suppressed"
    owner_conn.rollback()


def test_set_owner_rejects_a_non_ownership_event_type(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur)
        with pytest.raises(ValueError):
            set_owner(cur, contact_id, HOUSE_PARTNER_ID,
                      event_type="contact.opt_out", reason="wrong", actor="young")
        assert _ownership_events(cur, contact_id) == []
    owner_conn.rollback()


def test_set_owner_composes_on_the_callers_transaction(clean_db, owner_conn, owner_url):
    """Rollback after set_owner leaves NEITHER the column write nor the event —
    one caller-owned transaction, not two (the Phase 2 composition contract)."""
    import psycopg

    with owner_conn.cursor() as cur:
        john = _john_id(cur)
        contact_id = new_contact(cur)
    owner_conn.commit()

    with owner_conn.cursor() as cur:
        set_owner(cur, contact_id, john,
                  event_type="contact.assigned", reason="assignment", actor="young")
    owner_conn.rollback()

    with psycopg.connect(owner_url) as check:
        with check.cursor() as cur:
            assert _column_owner(cur, contact_id) == HOUSE_PARTNER_ID
            assert _ownership_events(cur, contact_id) == []


# ----------------------------------------------------------------------------------
# 3. The single-writer invariant, proven by deriving (not by grepping)
# ----------------------------------------------------------------------------------


def test_column_equals_event_confirmed_derivation_with_genesis(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        john = _john_id(cur)
        assigned = new_contact(cur)
        expired = new_contact(cur)
        reclaimed = new_contact(cur)
        untouched = new_contact(cur)  # genesis: no event => house
        set_owner(cur, assigned, john,
                  event_type="contact.assigned", reason="assignment", actor="young")
        set_owner(cur, expired, john,
                  event_type="contact.assigned", reason="assignment", actor="young")
        set_owner(cur, expired, HOUSE_PARTNER_ID,
                  event_type="contact.assignment_expired", reason="expiry", actor="system")
        set_owner(cur, reclaimed, john,
                  event_type="contact.assigned", reason="assignment", actor="young")
        set_owner(cur, reclaimed, HOUSE_PARTNER_ID,
                  event_type="contact.reclaimed", reason="won", actor="system")
        for contact_id in (assigned, expired, reclaimed, untouched):
            derived = current_owner(_ownership_events(cur, contact_id), HOUSE_PARTNER_ID)
            assert _column_owner(cur, contact_id) == derived, (
                "owner_id must equal the event-confirmed derivation for every "
                "ownership-changing path exercised in the suite"
            )
    owner_conn.rollback()


def test_current_owner_genesis_rule_is_total():
    assert current_owner([], HOUSE_PARTNER_ID) == HOUSE_PARTNER_ID


# ----------------------------------------------------------------------------------
# 4. Recipient resolution by partner id (digest + record_nudge payload)
# ----------------------------------------------------------------------------------


def _stalled(conn):
    contact_id = uuid4()
    with conn.cursor() as cur:
        new_contact(cur, id=contact_id, stage_snapshot="won")
        cur.execute(
            "insert into activation (contact_id, signed_up_at) values (%s, %s)",
            (contact_id, datetime(2026, 1, 1, tzinfo=UTC)),
        )
    conn.commit()


def test_young_recipient_resolves_to_the_house_partner_id(clean_db, owner_conn):
    _stalled(owner_conn)
    sender = FakeSender()

    result = digest.run(AS_OF, sender=sender)

    house = str(HOUSE_PARTNER_ID)
    assert [f for f, _ in sender.sent] == [house]
    assert len(result.sent[house]) == 1
    with owner_conn.cursor() as cur:
        cur.execute("select payload from events where type = 'nudge.sent'")
        payloads = [r[0] for r in cur.fetchall()]
    assert payloads and all(
        p["recipient"] == house and p["recipient_name"] == "Young" for p in payloads
    )


def test_deal_owner_recipient_resolves_to_the_owning_partner_id(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        john = _john_id(cur)
        contact_id = new_contact(cur, stage_snapshot="responded")
        set_owner(cur, contact_id, john,
                  event_type="contact.assigned", reason="assignment", actor="young")
    owner_conn.commit()
    sender = FakeSender()

    result = digest.run(AS_OF, sender=sender)

    assert str(john) in result.sent
    with owner_conn.cursor() as cur:
        cur.execute("select payload from events where type = 'nudge.sent'")
        payloads = [r[0] for r in cur.fetchall()]
    assert any(
        p["recipient"] == str(john) and p["recipient_name"] == "John" for p in payloads
    )


# ----------------------------------------------------------------------------------
# 5. The partners CLI — upsert by name (a mutate-only CLI cannot create partner #2)
# ----------------------------------------------------------------------------------


def test_cli_set_creates_a_new_partner_with_r1_columns(clean_db, owner_conn):
    code = partners_cli([
        "set", "Jane",
        "--channel", "email", "--channel-address", "jane@example.com",
        "--hours", "10", "--radius", "20",
        "--sales-rep-id", "7", "--partner-code", "JA-01",
    ])
    assert code == 0
    with owner_conn.cursor() as cur:
        cur.execute(
            "select channel, channel_address, weekly_hours, radius_miles, "
            "sales_rep_id, partner_code, status from partners where name = 'Jane'"
        )
        row = cur.fetchone()
        assert row == ("email", "jane@example.com", 10, 20, 7, "JA-01", "active")
        cur.execute("delete from partners where name = 'Jane'")
    owner_conn.commit()


def test_cli_set_updates_in_place_second_call_same_name(clean_db, owner_conn):
    assert partners_cli(["set", "Jane", "--hours", "10"]) == 0
    assert partners_cli(["set", "Jane", "--hours", "15", "--status", "inactive"]) == 0
    with owner_conn.cursor() as cur:
        cur.execute(
            "select count(*), max(weekly_hours), max(status) from partners "
            "where name = 'Jane'"
        )
        count, hours, status = cur.fetchone()
        assert (count, hours, status) == (1, 15, "inactive")
        cur.execute("delete from partners where name = 'Jane'")
    owner_conn.commit()


def test_cli_help_exits_zero():
    with pytest.raises(SystemExit) as excinfo:
        partners_cli(["--help"])
    assert excinfo.value.code == 0
