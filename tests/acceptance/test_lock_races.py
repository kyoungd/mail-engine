"""The stale-owner races (contact-engine part 1, answers 9 and 11): a writer that
decides a reclaim from an owner it read without a lock can leave a voice-blocked or
registry-listed contact with a rep. After the fix each decides on the row as it is
under lock."""

import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from config.params import HOUSE_PARTNER_ID
from jobs import dnc_refresh as scrub
from seams.fakes import FakeDncRegistry
from service import contacts
from service.assignment import assign_batch, reclaim
from tests.factories import new_contact


def _mk_partner(cur):
    cur.execute(
        "insert into partners (name, status) values (%s, 'active') returning id",
        (f"Race-{uuid4().hex[:8]}",),
    )
    row = cur.fetchone()
    assert row is not None
    return row[0]


def _subscribe(cur, code):
    cur.execute(
        "insert into dnc_subscriptions (area_code, subscribed_at) "
        "values (%s, now()) on conflict do nothing", (code,),
    )


def _row(cur, contact_id):
    cur.execute(
        "select owner_id, do_not_call, dnc_registry from contacts where id = %s",
        (contact_id,),
    )
    row = cur.fetchone()
    assert row is not None
    return row


def _reclaims(cur, contact_id):
    cur.execute(
        "select count(*) from events where contact_id = %s "
        "and type = 'contact.reclaimed'", (contact_id,),
    )
    row = cur.fetchone()
    assert row is not None
    return row[0]


def _cleanup(owner_conn, partner):
    with owner_conn.cursor() as cur:
        cur.execute(
            "update contacts set owner_id = %s, assignment_batch_id = null "
            "where owner_id = %s", (HOUSE_PARTNER_ID, partner),
        )
        cur.execute("delete from assignment_batches where partner_id = %s", (partner,))
        cur.execute("delete from partners where id = %s", (partner,))
    owner_conn.commit()


def test_an_assignment_racing_a_voice_suppression_never_leaves_it_with_a_rep(
    clean_db, owner_conn, monkeypatch
):
    """Race A. The assignment is started after suppress() has read the owner and
    before it writes. Unfixed, it commits in that gap and suppress skips the reclaim.
    Fixed, it waits on suppress's row lock and then refuses the contact."""
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur)
        _subscribe(cur, "818")
        contact = new_contact(cur, phone_e164="+18185557001",
                              dnc_checked_at=datetime.now(UTC))
    owner_conn.commit()

    result = {}
    worker = threading.Thread(target=lambda: result.update(
        report=assign_batch(partner, "race-a", "young", contact_ids=[contact])))
    original = contacts._primary_list_key

    def in_the_gap(cur, contact_id):
        worker.start()
        worker.join(timeout=2)  # unfixed: finishes; fixed: blocked on the row lock
        return original(cur, contact_id)

    monkeypatch.setattr(contacts, "_primary_list_key", in_the_gap)
    contacts.suppress(contact, "voice", "asked to stop calling")
    worker.join(timeout=10)
    assert not worker.is_alive()

    with owner_conn.cursor() as cur:
        owner, do_not_call, _ = _row(cur, contact)
    assert do_not_call is True
    assert owner == HOUSE_PARTNER_ID
    _cleanup(owner_conn, partner)


def test_a_scrub_hit_on_a_contact_assigned_after_the_due_read_takes_it_back(
    clean_db, owner_conn, monkeypatch
):
    """Race B, first way. The contact is due (checked 25 days ago: past the 21-day
    recheck, inside the 31-day wall, so still assignable) and is assigned after the
    scrub read it as NMC's. Unfixed, the hit is stamped and the rep keeps it."""
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur)
        _subscribe(cur, "818")
        contact = new_contact(cur, phone_e164="+18185557002",
                              dnc_checked_at=datetime.now(UTC) - timedelta(days=25))
    owner_conn.commit()

    original = scrub._due

    def then_assigned(subscribed, limit):
        due = original(subscribed, limit)
        assign_batch(partner, "race-b1", "young", contact_ids=[contact])
        return due

    monkeypatch.setattr(scrub, "_due", then_assigned)
    scrub.dnc_refresh(FakeDncRegistry(version="v1", numbers={"818": {"8185557002"}}))

    with owner_conn.cursor() as cur:
        owner, _, dnc_registry = _row(cur, contact)
    assert dnc_registry is True
    assert owner == HOUSE_PARTNER_ID
    _cleanup(owner_conn, partner)


def test_a_scrub_hit_on_a_contact_reclaimed_after_the_due_read_writes_no_second_reclaim(
    clean_db, owner_conn, monkeypatch
):
    """Race B, second way. The contact was held when the scrub read it and is
    reclaimed before the scrub acts. Unfixed, the scrub 'reclaims' it again, from the
    house to the house: a second contact.reclaimed event."""
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur)
        _subscribe(cur, "818")
        contact = new_contact(cur, phone_e164="+18185557003",
                              dnc_checked_at=datetime.now(UTC) - timedelta(days=25))
    owner_conn.commit()
    assign_batch(partner, "race-b2", "young", contact_ids=[contact])

    original = scrub._due

    def then_reclaimed(subscribed, limit):
        due = original(subscribed, limit)
        reclaim(partner, "operator took them back", "young")
        return due

    monkeypatch.setattr(scrub, "_due", then_reclaimed)
    scrub.dnc_refresh(FakeDncRegistry(version="v1", numbers={"818": {"8185557003"}}))

    with owner_conn.cursor() as cur:
        owner, _, dnc_registry = _row(cur, contact)
        assert dnc_registry is True
        assert owner == HOUSE_PARTNER_ID
        assert _reclaims(cur, contact) == 1
    _cleanup(owner_conn, partner)
