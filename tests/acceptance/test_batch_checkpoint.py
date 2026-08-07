"""The day-30 batch checkpoint (partner-lead-assignment.md §5 amendment 2026-08-05):
a LIVE batch past batch_checkpoint_days whose contacts show no spine-observable
activity surfaces to the operator. Visibility, never auto-reclaim — and the expired
batch belongs to the expiry job, not this rule."""

from datetime import UTC, date, datetime

import pytest

from config.params import Params
from judgment.rules.batch_checkpoint import RULE
from service.ingestion import ingest_event
from tests.acceptance.partner_cycle_helpers import aged_quiet_batch, remove_partners


@pytest.fixture(autouse=True)
def _cleanup(owner_conn):
    yield
    remove_partners(owner_conn, "Ckpt")


def test_fires_for_a_quiet_live_batch_past_day_30(clean_db, owner_conn):
    aged_quiet_batch(owner_conn, "CkptA", days=31, key="ckpt-a")
    hits = RULE.evaluate(owner_conn.cursor(), Params(), date.today())
    assert len(hits) == 1
    assert hits[0].contact_id is None  # batch-level, like the roll-up rules
    assert hits[0].facts["batch_key"] == "ckpt-a"
    assert hits[0].facts["partner"] == "CkptA"
    assert hits[0].facts["days_in"] >= 31


def test_near_miss_younger_than_the_checkpoint(clean_db, owner_conn):
    aged_quiet_batch(owner_conn, "CkptB", days=29, key="ckpt-b")
    assert RULE.evaluate(owner_conn.cursor(), Params(), date.today()) == []


def test_near_miss_inbound_activity_silences(clean_db, owner_conn):
    _, contacts = aged_quiet_batch(owner_conn, "CkptC", days=31, key="ckpt-c")
    ingest_event(
        "nmc", "call.inbound", datetime.now(UTC), {},
        external_id="ckpt-c-call", contact_id=contacts[0],
    )
    assert RULE.evaluate(owner_conn.cursor(), Params(), date.today()) == []


def test_near_miss_notes_and_closes_count_as_activity(clean_db, owner_conn):
    _, c1 = aged_quiet_batch(owner_conn, "CkptD", days=31, key="ckpt-d")
    _, c2 = aged_quiet_batch(
        owner_conn, "CkptE", days=31, key="ckpt-e",
        phones=("+18185551003", "+18185551004"),
    )
    ingest_event(
        "human", "note.general", datetime.now(UTC), {"text": "spoke, callback"},
        external_id="ckpt-d-note", contact_id=c1[0],
    )
    ingest_event(
        "nmc", "signup.completed", datetime.now(UTC), {},
        external_id="ckpt-e-close", contact_id=c2[0],
    )
    assert RULE.evaluate(owner_conn.cursor(), Params(), date.today()) == []


def test_near_miss_expired_batch_belongs_to_the_expiry_job(clean_db, owner_conn):
    aged_quiet_batch(owner_conn, "CkptF", days=31, key="ckpt-f")
    with owner_conn.cursor() as cur:
        cur.execute(
            "update assignment_batches set created_at = now() - interval '91 days', "
            "expires_at = now() - interval '1 day' where idempotency_key = 'ckpt-f'"
        )
    owner_conn.commit()
    assert RULE.evaluate(owner_conn.cursor(), Params(), date.today()) == []
