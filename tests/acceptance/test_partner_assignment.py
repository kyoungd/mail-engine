"""Partner Phase 4 gate (partner-lead-assignment-implementation.md, Batch C, frozen
2026-08-01, operator nod): the assignment verbs and jobs — the feature proper.

Consumes the contracts Batches A and B fixed; pins nothing new. Covers: assign_batch
(derived/explicit/id-list counts, idempotent retry, key-mismatch rejection, every S-1
gate as a named shortfall cause, deterministic order, the suppress-vs-assign race,
double-assignment unconstructibility), export_batch (CSV shape, fallback name,
stale-DNC shortfall, last_export_at), the nightly expiry + won-termination steps and
their ordering, the sender-None recording guard, and the Q10 close correlation in
consumer terms (both orderings + the no-mailer-code close ending an assignment)."""

import csv
import io
import threading
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest

from config.params import HOUSE_PARTNER_ID, derived_batch_size
from domain.errors import ValidationError
from service.assignment import (
    assign_batch,
    export_batch,
    reclaim,
    run_expiry_step,
    run_won_termination_step,
)
from service.contacts import suppress
from service.custody import set_owner
from service.ingestion import ingest_event
from tests.factories import new_contact

AT = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
FRESH = datetime.now(UTC)


def _mk_partner(cur, name: str, *, hours: int | None = None) -> UUID:
    cur.execute(
        "insert into partners (name, status, weekly_hours) values (%s, 'active', %s) "
        "returning id",
        (name, hours),
    )
    row = cur.fetchone()
    assert row is not None
    return row[0]


def _rm_partner(owner_conn, partner_id: UUID) -> None:
    """In-test cleanup (partners is deliberately not truncated by clean_db):
    release FK references, then the row. Raw resets are fine — this is fixture
    teardown, not a production path."""
    with owner_conn.cursor() as cur:
        cur.execute(
            "update contacts set owner_id = %s, assignment_batch_id = null "
            "where owner_id = %s",
            (HOUSE_PARTNER_ID, partner_id),
        )
        cur.execute(
            "delete from assignment_batches where partner_id = %s", (partner_id,)
        )
        cur.execute("delete from partners where id = %s", (partner_id,))
    owner_conn.commit()


def _pool_contact(cur, phone: str, **fields) -> UUID:
    """An assignable contact: phone in a subscribed area code, fresh DNC check."""
    fields.setdefault("dnc_checked_at", FRESH)
    return new_contact(cur, phone_e164=phone, **fields)


def _subscribe(cur, *codes: str) -> None:
    for code in codes:
        cur.execute(
            "insert into dnc_subscriptions (area_code, subscribed_at) "
            "values (%s, now()) on conflict do nothing",
            (code,),
        )


def _owner(cur, contact_id) -> UUID:
    cur.execute("select owner_id from contacts where id = %s", (contact_id,))
    row = cur.fetchone()
    assert row is not None
    return row[0]


def _batch_pointer(cur, contact_id):
    cur.execute("select assignment_batch_id from contacts where id = %s", (contact_id,))
    row = cur.fetchone()
    assert row is not None
    return row[0]


# ----------------------------------------------------------------------------------
# 1. The §5 formula
# ----------------------------------------------------------------------------------


def test_derived_batch_size_follows_the_design_table():
    assert derived_batch_size(10) == 100
    assert derived_batch_size(20) == 250
    assert derived_batch_size(30) == 350
    assert derived_batch_size(40) == 500
    assert derived_batch_size(1) == 100   # floor
    assert derived_batch_size(80) == 500  # cap


# ----------------------------------------------------------------------------------
# 2-3. Idempotent retry and key mismatch
# ----------------------------------------------------------------------------------


def test_same_key_retry_returns_the_original_membership(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        _subscribe(cur, "818")
        ids = [_pool_contact(cur, f"+1818555{i:04d}") for i in range(3)]
    owner_conn.commit()

    first = assign_batch(partner, "key-1", "young", contact_ids=ids)
    assert set(first.assigned) == set(ids) and first.retry is False

    with owner_conn.cursor() as cur:
        cur.execute("select count(*) from events where type = 'contact.assigned'")
        events_before = cur.fetchone()[0]
    owner_conn.commit()

    # release one row (reclaim path) then retry the same key
    with owner_conn.cursor() as cur:
        set_owner(cur, ids[0], HOUSE_PARTNER_ID, event_type="contact.reclaimed",
                  reason="test", actor="young")
    owner_conn.commit()

    retry = assign_batch(partner, "key-1", "young", contact_ids=ids)
    assert retry.retry is True
    assert set(retry.assigned) | set(retry.released) == set(ids)
    assert ids[0] in retry.released  # reported as such, not silently re-assigned

    with owner_conn.cursor() as cur:
        cur.execute("select count(*) from events where type = 'contact.assigned'")
        assert cur.fetchone()[0] == events_before  # a receipt, not a re-run
    _rm_partner(owner_conn, partner)


def test_reused_key_with_different_parameters_is_rejected(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        other = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        _subscribe(cur, "818")
        ids = [_pool_contact(cur, "+18185551100")]
    owner_conn.commit()

    assign_batch(partner, "key-2", "young", contact_ids=ids)
    with pytest.raises(ValidationError):
        assign_batch(other, "key-2", "young", contact_ids=ids)  # different partner
    with pytest.raises(ValidationError):
        assign_batch(partner, "key-2", "young", count=5)  # different request
    _rm_partner(owner_conn, partner)
    _rm_partner(owner_conn, other)


# ----------------------------------------------------------------------------------
# 4. Every S-1 gate, as a named shortfall cause
# ----------------------------------------------------------------------------------


def test_every_pool_gate_excludes_with_its_cause(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        taken_by = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        _subscribe(cur, "818")

        ok = _pool_contact(cur, "+18185552000")
        no_phone = new_contact(cur, phone_e164=None, dnc_checked_at=FRESH)
        mid_funnel = _pool_contact(cur, "+18185552001")
        won = _pool_contact(cur, "+18185552002")
        voice = _pool_contact(cur, "+18185552003", do_not_call=True)
        listed = _pool_contact(cur, "+18185552004", dnc_registry=True)
        stale = _pool_contact(
            cur, "+18185552005", dnc_checked_at=FRESH - timedelta(days=45)
        )
        unsub = _pool_contact(cur, "+13105552006")  # 310 not subscribed
        seed = new_contact(cur, phone_e164="+18185552007", is_seed=True,
                           intake=False, dnc_checked_at=FRESH)
        taken = _pool_contact(cur, "+18185552008")
    owner_conn.commit()

    # stages constructed through REAL events + recompute (a bare column write would
    # be erased by the very recompute the fixture needs)
    ingest_event("lob", "piece.submitted", AT, {}, contact_id=mid_funnel)
    ingest_event("nmc", "call.inbound", AT + timedelta(days=1), {}, contact_id=mid_funnel)
    ingest_event("nmc", "sms.outbound", AT + timedelta(days=2), {}, contact_id=mid_funnel)
    ingest_event("posthog", "signup.completed", AT, {}, contact_id=won)
    from service.execution import recompute_state

    recompute_state()

    with owner_conn.cursor() as cur:
        set_owner(cur, taken, taken_by, event_type="contact.assigned", reason="test",
                  actor="young", batch_id=None)
        cur.execute(
            "update contacts set assignment_batch_id = null where id = %s", (taken,)
        )
    owner_conn.commit()
    # 'taken' is owned (owner != house) though pointer is null — assign to the other
    # partner via a real batch to make the pointer real:
    assign_batch(taken_by, "key-gate-taken", "young", contact_ids=[taken])

    report = assign_batch(
        partner, "key-3", "young",
        contact_ids=[ok, no_phone, mid_funnel, won, voice, listed, stale, unsub,
                     seed, taken],
    )
    assert report.assigned == [ok]
    assert report.shortfall["no_phone"] == [no_phone]
    assert report.shortfall["mid_funnel"] == [mid_funnel]
    assert report.shortfall["won"] == [won]
    assert report.shortfall["voice_suppressed"] == [voice]
    assert report.shortfall["dnc_registry"] == [listed]
    assert report.shortfall["dnc_stale"] == [stale]
    assert report.shortfall["dnc_unsubscribed"] == [unsub]
    assert report.shortfall["seed"] == [seed]
    assert report.shortfall["already_assigned"] == [taken]
    _rm_partner(owner_conn, partner)


def test_deletion_tombstone_blocks_assignment_by_phone(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        _subscribe(cur, "818")
        cur.execute(
            "insert into suppression_tombstones (phone_e164, channel, reason) "
            "values ('+18185552100', 'voice', 'FR-8 deleted')"
        )
        contact = _pool_contact(cur, "+18185552100")  # re-ingested after delete,
        # columns not yet re-applied (the belt the gate provides)
    owner_conn.commit()

    report = assign_batch(partner, "key-4", "young", contact_ids=[contact])
    assert report.assigned == []
    assert report.shortfall["tombstoned"] == [contact]
    _rm_partner(owner_conn, partner)


# ----------------------------------------------------------------------------------
# 5-7. Selection order, partner validation, counts
# ----------------------------------------------------------------------------------


def test_rule_selection_is_deterministic_order_by_id(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        _subscribe(cur, "818")
        ids = sorted(
            [_pool_contact(cur, f"+1818555{i:04d}", trade="plumber") for i in range(5)],
            key=str,
        )
    owner_conn.commit()

    report = assign_batch(
        partner, "key-5", "young", audience_rule={"trade": ["plumber"]}, count=3
    )
    assert report.assigned == ids[:3]  # order by id, first three
    _rm_partner(owner_conn, partner)


def test_rule_rejects_stage_limit_and_unknown_keys(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}", hours=10)
    owner_conn.commit()
    for bad in ({"stage": ["prospect"]}, {"limit": 5}, {"not_responded_to_wave": "x"},
                {"nope": 1}):
        with pytest.raises(ValidationError):
            assign_batch(partner, f"key-bad-{list(bad)[0]}", "young", audience_rule=bad)
    _rm_partner(owner_conn, partner)


def test_inactive_partner_and_null_hours_are_rejected(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        inactive = _mk_partner(cur, f"P-{uuid4().hex[:8]}", hours=10)
        cur.execute("update partners set status = 'inactive' where id = %s", (inactive,))
        no_hours = _mk_partner(cur, f"P-{uuid4().hex[:8]}")  # weekly_hours null
    owner_conn.commit()

    with pytest.raises(ValidationError):
        assign_batch(inactive, "key-6", "young", count=1)
    with pytest.raises(ValidationError):
        assign_batch(no_hours, "key-7", "young")  # no count, no hours
    _rm_partner(owner_conn, inactive)
    _rm_partner(owner_conn, no_hours)


def test_derived_count_and_explicit_override(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}", hours=10)  # derived 100
        _subscribe(cur, "818")
        for i in range(120):
            _pool_contact(cur, f"+1818555{i:04d}", trade="plumber")
    owner_conn.commit()

    derived = assign_batch(
        partner, "key-8", "young", audience_rule={"trade": ["plumber"]}
    )
    assert len(derived.assigned) == 100  # §5: 10h -> 120 -> round/floor -> 100

    with owner_conn.cursor() as cur:
        trial_partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}", hours=10)
    owner_conn.commit()
    trial = assign_batch(
        trial_partner, "key-9", "young",
        audience_rule={"trade": ["plumber"]}, count=15,
    )
    assert len(trial.assigned) == 15  # explicit count bypasses the floor
    _rm_partner(owner_conn, partner)
    _rm_partner(owner_conn, trial_partner)


# ----------------------------------------------------------------------------------
# 8-9. Concurrency: double-assignment and the suppress-vs-assign race
# ----------------------------------------------------------------------------------


def test_double_assignment_is_unconstructible(clean_db, owner_conn, owner_url):
    with owner_conn.cursor() as cur:
        p1 = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        p2 = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        _subscribe(cur, "818")
        contact = _pool_contact(cur, "+18185553000")
    owner_conn.commit()

    results = {}

    def _try(partner_id, key):
        results[key] = assign_batch(partner_id, key, "young", contact_ids=[contact])

    t1 = threading.Thread(target=_try, args=(p1, "key-r1"))
    t2 = threading.Thread(target=_try, args=(p2, "key-r2"))
    t1.start()
    t2.start()
    t1.join(10)
    t2.join(10)

    won = [k for k, r in results.items() if r.assigned == [contact]]
    lost = [k for k, r in results.items()
            if r.shortfall.get("already_assigned") == [contact]]
    assert len(won) == 1 and len(lost) == 1  # exactly one batch holds it

    with owner_conn.cursor() as cur:
        assert _batch_pointer(cur, contact) is not None
    _rm_partner(owner_conn, p1)
    _rm_partner(owner_conn, p2)


def test_suppress_landing_mid_assign_never_yields_a_suppressed_assignment(
    clean_db, owner_conn, owner_url
):
    """The race fixture: a do_not_call in flight (uncommitted row lock) while
    assign_batch runs. The storage layer — not timing — must decide: after the
    suppress commits, the contact is voice-suppressed and NOT assigned."""
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        _subscribe(cur, "818")
        contact = _pool_contact(cur, "+18185553100")
    owner_conn.commit()

    blocker = psycopg.connect(owner_url)
    with blocker.cursor() as cur:
        # the in-flight suppress: row locked, flag written, not yet committed
        cur.execute(
            "update contacts set do_not_call = true where id = %s", (contact,)
        )

    result = {}

    def _assign():
        result["report"] = assign_batch(
            partner, "key-race", "young", contact_ids=[contact]
        )

    t = threading.Thread(target=_assign)
    t.start()
    t.join(1)
    assert t.is_alive()  # blocked on the row lock — serialization is real
    blocker.commit()
    blocker.close()
    t.join(10)

    assert result["report"].assigned == []
    assert result["report"].shortfall["voice_suppressed"] == [contact]
    with owner_conn.cursor() as cur:
        assert _owner(cur, contact) == HOUSE_PARTNER_ID
    _rm_partner(owner_conn, partner)


# ----------------------------------------------------------------------------------
# 11. export_batch
# ----------------------------------------------------------------------------------


def test_export_batch_shape_fallback_stale_shortfall_and_stamp(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        _subscribe(cur, "818")
        named = _pool_contact(cur, "+18185554000", business_name="Named Co")
        nameless = _pool_contact(
            cur, "+18185554001", business_name=None, contact_name=None
        )
        stale = _pool_contact(cur, "+18185554002")
    owner_conn.commit()

    assign_batch(partner, "key-10", "young", contact_ids=[named, nameless, stale])
    with owner_conn.cursor() as cur:
        cur.execute(
            "update contacts set dnc_checked_at = now() - interval '45 days' "
            "where id = %s",
            (stale,),
        )
    owner_conn.commit()

    result = export_batch(partner)
    rows = list(csv.DictReader(io.StringIO(result.csv)))
    assert {"expires_at", "generated_at"} <= set(rows[0].keys())
    names = {r["business_name"] for r in rows}
    assert "Named Co" in names and "Business Owner" in names
    assert len(rows) == 2  # the stale row is NOT in the file
    assert result.shortfall["dnc_stale"] == [stale]

    with owner_conn.cursor() as cur:
        cur.execute("select last_export_at from partners where id = %s", (partner,))
        row = cur.fetchone()
        assert row is not None and row[0] is not None
    _rm_partner(owner_conn, partner)


# ----------------------------------------------------------------------------------
# 12-14. The nightly steps: expiry, won-termination, ordering
# ----------------------------------------------------------------------------------


def test_expiry_returns_contacts_and_reassignability_is_immediate(
    clean_db, owner_conn
):
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        _subscribe(cur, "818")
        contact = _pool_contact(cur, "+18185555000")
    owner_conn.commit()

    assign_batch(partner, "key-11", "young", contact_ids=[contact])
    with owner_conn.cursor() as cur:
        cur.execute(
            "update assignment_batches set expires_at = now() - interval '1 day' "
            "where partner_id = %s",
            (partner,),
        )
    owner_conn.commit()

    expired = run_expiry_step()
    assert expired == 1
    with owner_conn.cursor() as cur:
        assert _owner(cur, contact) == HOUSE_PARTNER_ID
        assert _batch_pointer(cur, contact) is None
        cur.execute(
            "select count(*) from events where contact_id = %s "
            "and type = 'contact.assignment_expired'",
            (contact,),
        )
        assert cur.fetchone()[0] == 1
    owner_conn.commit()

    again = assign_batch(partner, "key-12", "young", contact_ids=[contact])
    assert again.assigned == [contact]  # immediately re-assignable
    _rm_partner(owner_conn, partner)


def test_a_won_contact_never_reenters_the_pool(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        _subscribe(cur, "818")
        contact = _pool_contact(cur, "+18185555100")
    owner_conn.commit()

    assign_batch(partner, "key-13", "young", contact_ids=[contact])
    ingest_event("posthog", "signup.completed", FRESH, {}, contact_id=contact)
    from service.execution import recompute_state

    recompute_state()
    terminated = run_won_termination_step()
    assert terminated == 1
    with owner_conn.cursor() as cur:
        assert _owner(cur, contact) == HOUSE_PARTNER_ID
    owner_conn.commit()

    # even after its batch would have expired, the pool gate keeps it out
    report = assign_batch(partner, "key-14", "young", contact_ids=[contact])
    assert report.assigned == [] and report.shortfall["won"] == [contact]
    _rm_partner(owner_conn, partner)


def test_nightly_runs_steps_after_recompute_and_digest_routes_post_return(
    clean_db, owner_conn
):
    """A close ingested before the nightly: recompute derives won, the termination
    step returns the contact, and the digest routes any hit for it to the house —
    the documented order sync → orphans → recompute → steps → digest, observed
    through its effects in ONE run_nightly call."""
    from jobs.nightly import run_nightly
    from seams.fakes import FakeSender

    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        _subscribe(cur, "818")
        contact = _pool_contact(cur, "+18185555200")
    owner_conn.commit()

    assign_batch(partner, "key-15", "young", contact_ids=[contact])
    ingest_event("posthog", "signup.completed", FRESH, {}, contact_id=contact)

    sender = FakeSender()
    run_nightly([], FRESH - timedelta(days=1), sender=sender)

    with owner_conn.cursor() as cur:
        assert _owner(cur, contact) == HOUSE_PARTNER_ID  # won -> terminated same night
        cur.execute("select stage_snapshot from contacts where id = %s", (contact,))
        assert cur.fetchone()[0] == "won"  # so the step ran AFTER recompute
    for founder, _message in sender.sent:
        assert founder != str(partner)  # nudges routed on post-return ownership
    _rm_partner(owner_conn, partner)


# ----------------------------------------------------------------------------------
# 15. The sender-None recording guard
# ----------------------------------------------------------------------------------


def test_sender_none_skips_partner_hits_entirely(clean_db, owner_conn):
    from judgment import digest

    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        _subscribe(cur, "818")
        partner_owned = _pool_contact(cur, "+18185556000")
        house_owned = _pool_contact(cur, "+18185556001")
    owner_conn.commit()

    assign_batch(partner, "key-16", "young", contact_ids=[partner_owned])
    # hot responses on both (piece out, inbound back, no engagement yet)
    for cid in (partner_owned, house_owned):
        ingest_event("lob", "piece.submitted", AT, {}, contact_id=cid)
        ingest_event("nmc", "call.inbound", FRESH - timedelta(hours=2), {},
                     contact_id=cid)
    from service.execution import recompute_state

    recompute_state()

    result = digest.run(FRESH.date(), sender=None)

    with owner_conn.cursor() as cur:
        cur.execute(
            "select count(*) from events where contact_id = %s and type = 'nudge.sent'",
            (partner_owned,),
        )
        assert cur.fetchone()[0] == 0  # skipped BEFORE recording
        cur.execute(
            "select next_action_at from contacts where id = %s", (partner_owned,)
        )
        assert cur.fetchone()[0] is None
        cur.execute(
            "select count(*) from events where contact_id = %s and type = 'nudge.sent'",
            (house_owned,),
        )
        assert cur.fetchone()[0] == 1  # the house burn, unchanged (TD-10 known cost)
    assert str(partner) not in result.sent
    _rm_partner(owner_conn, partner)


def test_with_a_sender_partner_hits_record_and_deliver(clean_db, owner_conn):
    from judgment import digest
    from seams.fakes import FakeSender

    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        _subscribe(cur, "818")
        partner_owned = _pool_contact(cur, "+18185556100")
    owner_conn.commit()

    assign_batch(partner, "key-17", "young", contact_ids=[partner_owned])
    ingest_event("lob", "piece.submitted", AT, {}, contact_id=partner_owned)
    ingest_event("nmc", "call.inbound", FRESH - timedelta(hours=2), {},
                 contact_id=partner_owned)
    from service.execution import recompute_state

    recompute_state()

    sender = FakeSender()
    digest.run(FRESH.date(), sender=sender)

    with owner_conn.cursor() as cur:
        cur.execute(
            "select count(*) from events where contact_id = %s and type = 'nudge.sent'",
            (partner_owned,),
        )
        assert cur.fetchone()[0] == 1  # byte-identical to the pre-guard path
    assert any(founder == str(partner) for founder, _ in sender.sent)
    _rm_partner(owner_conn, partner)


# ----------------------------------------------------------------------------------
# 16-18. Q10 close correlation, in consumer terms
# ----------------------------------------------------------------------------------


def _close(id: str, phone: str | None, recorded_at: datetime, **extra):
    from seams.nmc_closes import Close

    return Close(
        id=id, recorded_at=recorded_at, occurred_at=recorded_at,
        kind="signup_completed", phone_e164=phone,
        partner_code=extra.get("partner_code"),
        mailer_code=extra.get("mailer_code"),
        sold_by=extra.get("sold_by"),
        signed_up_via=extra.get("signed_up_via"),
        subscription_status=extra.get("subscription_status"),
    )


def _signup_events(cur, contact_id) -> list[tuple]:
    cur.execute(
        "select source from events where contact_id = %s "
        "and type = 'signup.completed' order by id",
        (contact_id,),
    )
    return cur.fetchall()


def test_funnel_close_first_then_correlation_ingests_exactly_one(
    clean_db, owner_conn
):
    from jobs.close_correlation import correlate_closes
    from seams.fakes import FakeCloseFeed

    with owner_conn.cursor() as cur:
        _subscribe(cur, "818")
        contact = _pool_contact(cur, "+18185557000")
    owner_conn.commit()

    # the PostHog funnel close, already attributed (post-resolve_orphans state)
    ingest_event("posthog", "signup.completed", FRESH - timedelta(hours=3), {},
                 external_id="ph-1", contact_id=contact)

    feed = FakeCloseFeed([_close("cus_A", "+18185557000", FRESH)])
    correlate_closes(feed)

    with owner_conn.cursor() as cur:
        assert _signup_events(cur, contact) == [("posthog",)]  # guard skipped ours


def test_correlation_first_then_replayed_funnel_close_is_two_events_and_correct(
    clean_db, owner_conn
):
    from jobs.close_correlation import correlate_closes
    from seams.fakes import FakeCloseFeed

    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        _subscribe(cur, "818")
        contact = _pool_contact(cur, "+18185557100")
    owner_conn.commit()
    assign_batch(partner, "key-18", "young", contact_ids=[contact])

    correlate_closes(FakeCloseFeed([_close("cus_B", "+18185557100", FRESH)]))
    # the PostHog replay lands afterwards (reverse ordering)
    ingest_event("posthog", "signup.completed", FRESH, {"mailer_code": "abc"},
                 external_id="ph-2", contact_id=contact)

    from service.execution import recompute_state

    recompute_state()
    terminated = run_won_termination_step()

    with owner_conn.cursor() as cur:
        sources = {s for (s,) in _signup_events(cur, contact)}
        assert sources == {"nmc", "posthog"}  # two events exist — and that is correct
        cur.execute("select stage_snapshot from contacts where id = %s", (contact,))
        assert cur.fetchone()[0] == "won"  # won derived once
    assert terminated == 1  # termination fired once
    assert run_won_termination_step() == 0  # and only once
    _rm_partner(owner_conn, partner)


def test_a_codeless_close_ends_the_assignment_before_expiry(clean_db, owner_conn):
    """The Q10 acceptance: a contractor signs up with no mailer code (typed partner
    code, organic, demo line) — the correlation alone must end the assignment,
    long before the 90-day expiry would have."""
    from jobs.close_correlation import correlate_closes
    from seams.fakes import FakeCloseFeed

    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        _subscribe(cur, "818")
        contact = _pool_contact(cur, "+18185557200")
    owner_conn.commit()
    assign_batch(partner, "key-19", "young", contact_ids=[contact])

    correlate_closes(
        FakeCloseFeed([_close("cus_C", "+18185557200", FRESH, mailer_code=None)])
    )
    from service.execution import recompute_state

    recompute_state()
    run_won_termination_step()

    with owner_conn.cursor() as cur:
        assert _owner(cur, contact) == HOUSE_PARTNER_ID
        assert _batch_pointer(cur, contact) is None
    _rm_partner(owner_conn, partner)


# ----------------------------------------------------------------------------------
# 19. reclaim, and the Phase 1 single-writer regression
# ----------------------------------------------------------------------------------


def test_reclaim_returns_all_holdings_with_events(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        _subscribe(cur, "818")
        ids = [_pool_contact(cur, f"+1818555{i + 8000:04d}") for i in range(2)]
    owner_conn.commit()

    assign_batch(partner, "key-20", "young", contact_ids=ids)
    returned = reclaim(partner, "partnership ended", "young")
    assert returned == 2
    with owner_conn.cursor() as cur:
        for cid in ids:
            assert _owner(cur, cid) == HOUSE_PARTNER_ID
            cur.execute(
                "select payload->>'reason' from events where contact_id = %s "
                "and type = 'contact.reclaimed'",
                (cid,),
            )
            assert cur.fetchone()[0] == "partnership ended"
    _rm_partner(owner_conn, partner)


def test_column_still_equals_derivation_across_all_new_paths(clean_db, owner_conn):
    """Phase 1's single-writer invariant, re-asserted with every Phase 4 path
    exercised: assign, expire, won-terminate, reclaim, suppress-reclaim."""
    from derivation.custody import OWNERSHIP_EVENT_TYPES, current_owner
    from service.ingestion import event_from_row

    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        _subscribe(cur, "818")
        a = _pool_contact(cur, "+18185559000")
        b = _pool_contact(cur, "+18185559001")
        c = _pool_contact(cur, "+18185559002")
        d = _pool_contact(cur, "+18185559003")
    owner_conn.commit()

    assign_batch(partner, "key-21", "young", contact_ids=[a, b, c, d])
    with owner_conn.cursor() as cur:
        cur.execute(
            "update assignment_batches set expires_at = now() - interval '1 day' "
            "where idempotency_key = 'key-21'"
        )
    owner_conn.commit()
    run_expiry_step()  # a,b,c,d all expire

    assign_batch(partner, "key-22", "young", contact_ids=[b, c, d])
    ingest_event("posthog", "signup.completed", FRESH, {}, contact_id=b)
    from service.execution import recompute_state

    recompute_state()
    run_won_termination_step()  # b
    suppress(c, "voice", "asked")  # c reclaimed via suppress
    reclaim(partner, "test end", "young")  # d

    with owner_conn.cursor() as cur:
        for cid in (a, b, c, d):
            cur.execute(
                "select id, contact_id, piece_id, source, type, occurred_at, "
                "ingested_at, external_id, payload from events "
                "where contact_id = %s and type = any(%s) order by occurred_at, id",
                (cid, list(OWNERSHIP_EVENT_TYPES)),
            )
            events = [event_from_row(r) for r in cur.fetchall()]
            assert current_owner(events, HOUSE_PARTNER_ID) == _owner(cur, cid)
    _rm_partner(owner_conn, partner)
