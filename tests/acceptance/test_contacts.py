"""Phase 2 gate: list intake and the contact verbs — load_list counts/normalizes,
suppress is one-way, record_outcome declares lost, set_next_action writes the slot."""

import csv
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import psycopg
import pytest

import service.contacts as contacts
from domain.errors import ValidationError
from service.contacts import load_list, record_outcome, set_next_action, suppress
from service.execution import recompute_state
from service.ingestion import ingest_event

FIELDS = [
    "list_key", "business_name", "trade", "phone", "addr_state",
    "do_not_mail", "segment",
]


def _write_csv(path, rows) -> str:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in FIELDS})
    return str(path)


def _seed_contact(conn) -> UUID:
    contact_id = uuid4()
    with conn.cursor() as cur:
        cur.execute("insert into contacts (id, trade) values (%s, 'plumber')", (contact_id,))
    conn.commit()
    return contact_id


def _stage(readonly_url, contact_id) -> str:
    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute("select stage_snapshot from contacts where id = %s", (contact_id,))
            row = cur.fetchone()
            assert row is not None
            return row[0]


def test_load_list_counts_normalizes_and_segments(clean_db, tmp_path, readonly_url):
    path = _write_csv(
        tmp_path / "list.csv",
        [
            {"list_key": "cslb-L1", "business_name": "A Plumbing", "trade": "plumber",
             "phone": "(818) 679-3565", "addr_state": "ca"},
            {"list_key": "cslb-L2", "business_name": "B Electric", "trade": "electrician",
             "phone": "bad", "addr_state": "CA", "do_not_mail": "true"},
            {"list_key": "cslb-L1", "trade": "plumber"},  # duplicate key
            {"list_key": "cslb-L3", "trade": ""},         # invalid: no trade AND no segment
        ],
    )
    report = load_list(path)
    assert (report.loaded, report.deduped, report.invalid, report.suppressed) == (2, 1, 1, 1)

    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute("select phone_e164, segment from contacts where list_key = 'cslb-L1'")
            row = cur.fetchone()
            assert row is not None
            phone, segment = row
    assert phone == "+18186793565"
    assert segment == "plumber-CA"


def test_load_list_trade_less_row_with_segment_is_valid(clean_db, tmp_path, readonly_url):
    """The FBN shape: no trade, targetable via segment."""
    path = _write_csv(
        tmp_path / "fbn.csv",
        [{"list_key": "fbn-ca-2026000001", "business_name": "New Biz",
          "trade": "", "segment": "fbn-ca-2026"}],
    )
    report = load_list(path, source="fbn-ca-2026")
    assert (report.loaded, report.invalid) == (1, 0)

    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select trade, segment, source from contacts where list_key = 'fbn-ca-2026000001'"
            )
            assert cur.fetchone() == (None, "fbn-ca-2026", "fbn-ca-2026")


def test_load_list_dedupes_against_existing_rows(clean_db, tmp_path, owner_conn):
    with owner_conn.cursor() as cur:
        cur.execute("insert into contacts (list_key, trade) values ('cslb-L9', 'plumber')")
    owner_conn.commit()
    path = _write_csv(tmp_path / "l.csv", [{"list_key": "cslb-L9", "trade": "plumber"}])
    report = load_list(path)
    assert report.loaded == 0
    assert report.deduped == 1


def test_suppress_sets_flag_appends_event_and_derives_suppressed(
    clean_db, owner_conn, readonly_url
):
    contact_id = _seed_contact(owner_conn)
    suppress(contact_id, "do_not_mail")
    recompute_state()

    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute("select do_not_mail from contacts where id = %s", (contact_id,))
            row = cur.fetchone()
            assert row is not None and row[0] is True
            cur.execute(
                "select count(*) from events where contact_id = %s and type = 'contact.opt_out'",
                (contact_id,),
            )
            row = cur.fetchone()
            assert row is not None and row[0] == 1
    assert _stage(readonly_url, contact_id) == "suppressed"


def test_suppress_is_one_way_no_unsuppress_verb():
    assert not hasattr(contacts, "unsuppress")


def test_opt_out_halts_mail_immediately_without_a_recompute(clean_db, owner_conn, readonly_url):
    from service.waves import resolve_audience

    contact_id = _seed_contact(owner_conn)  # plumber, do_not_mail = false
    suppress(contact_id, "opt_out")
    # No recompute has run — the audience resolver must already exclude them.
    with owner_conn.cursor() as cur:
        remaining = resolve_audience(cur, {"trade": ["plumber"]})
    assert contact_id not in remaining

    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select do_not_mail, do_not_text from contacts where id = %s", (contact_id,)
            )
            row = cur.fetchone()
            assert row is not None
            assert row == (True, True)


def test_suppress_rejects_bad_reason(clean_db, owner_conn):
    contact_id = _seed_contact(owner_conn)
    with pytest.raises(ValidationError):
        suppress(contact_id, "whatever")


def test_record_outcome_lost_derives_lost_stage(clean_db, owner_conn, readonly_url):
    contact_id = _seed_contact(owner_conn)
    ingest_event("lob", "piece.submitted", datetime(2026, 1, 1, tzinfo=UTC), {}, contact_id=contact_id)
    ingest_event("nmc", "sms.inbound", datetime(2026, 1, 3, tzinfo=UTC), {}, contact_id=contact_id)

    record_outcome(contact_id, "lost", "went with a competitor")
    recompute_state()

    assert _stage(readonly_url, contact_id) == "lost"


def test_record_outcome_rejects_non_lost(clean_db, owner_conn):
    contact_id = _seed_contact(owner_conn)
    with pytest.raises(ValidationError):
        record_outcome(contact_id, "won", "x")


def test_set_next_action_writes_the_slot(clean_db, owner_conn, readonly_url):
    contact_id = _seed_contact(owner_conn)
    set_next_action(contact_id, date(2026, 3, 1), "call them")

    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select next_action_at, next_action_note from contacts where id = %s",
                (contact_id,),
            )
            row = cur.fetchone()
            assert row is not None
            next_at, note = row
    assert next_at == date(2026, 3, 1)
    assert note == "call them"
