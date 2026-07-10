"""Phase 5 gate: digest delivery. When a sender is injected, the judgment run
delivers one assembled digest per founder; with no sender (or a zero-hit night) it
sends nothing. The real NMC sender is deferred; a fake stands in."""

from datetime import UTC, datetime
from uuid import uuid4

from judgment import digest
from seams.fakes import FakeSender

AS_OF = datetime.now(UTC).date()


def _stalled(conn):
    contact_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            "insert into contacts (id, trade, stage_snapshot) values (%s, 'plumber', 'won')",
            (contact_id,),
        )
        cur.execute(
            "insert into activation (contact_id, signed_up_at) values (%s, %s)",
            (contact_id, datetime(2026, 1, 1, tzinfo=UTC)),
        )
    conn.commit()


def test_digest_sends_one_message_per_founder(clean_db, owner_conn):
    _stalled(owner_conn)
    _stalled(owner_conn)
    sender = FakeSender()

    result = digest.run(AS_OF, sender=sender)

    assert len(sender.sent) == 1  # both nudges route to 'young' -> one digest
    founder, message = sender.sent[0]
    assert founder == "young"
    assert "Today's nudges (2)" in message
    assert len(result.sent["young"]) == 2


def test_no_sender_delivers_nothing(clean_db, owner_conn):
    _stalled(owner_conn)
    result = digest.run(AS_OF)  # no sender injected
    assert len(result.sent["young"]) == 1  # still computed and recorded, just not sent


def test_a_zero_hit_night_sends_no_message(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        cur.execute("insert into contacts (trade) values ('plumber')")
    owner_conn.commit()
    sender = FakeSender()

    digest.run(AS_OF, sender=sender)

    assert sender.sent == []
