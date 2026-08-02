"""Stage C gate (frozen 2026-08-01, operator nod): C1 the real Sender + S-7 flip,
C2 the partner report composer — the ratified R2 tests 1-10 plus the Section 2
(closes) and Section 3 (demo line) additions from the 2026-07-31 design revision.

Operator decision at the gate: the sender-None recording guard is KEPT (plan
amended) — Batch C's guard tests remain binding unchanged."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from config.params import HOUSE_PARTNER_ID
from judgment.partner_report import run_partner_reports
from seams.fakes import FakeDemosClient, FakeSender
from service.assignment import assign_batch
from service.contacts import suppress
from service.ingestion import ingest_event
from tests.factories import new_contact

NOW = datetime.now(UTC)
FRESH = NOW


def _mk_partner(
    cur, name: str, *, code: str | None = None, rep: int | None = None,
    last_report_at: datetime | None = None, channel: str | None = "email",
    address: str | None = "p@example.com",
) -> UUID:
    cur.execute(
        "insert into partners (name, status, weekly_hours, channel, channel_address, "
        "partner_code, sales_rep_id, last_report_at) "
        "values (%s, 'active', 10, %s, %s, %s, %s, %s) returning id",
        (name, channel, address, code, rep, last_report_at),
    )
    row = cur.fetchone()
    assert row is not None
    return row[0]


def _rm_partner(owner_conn, partner_id: UUID) -> None:
    with owner_conn.cursor() as cur:
        cur.execute(
            "update contacts set owner_id = %s, assignment_batch_id = null "
            "where owner_id = %s",
            (HOUSE_PARTNER_ID, partner_id),
        )
        cur.execute("delete from assignment_batches where partner_id = %s", (partner_id,))
        cur.execute("delete from partners where id = %s", (partner_id,))
    owner_conn.commit()


def _pool_contact(cur, phone: str, **fields) -> UUID:
    fields.setdefault("dnc_checked_at", FRESH)
    return new_contact(cur, phone_e164=phone, **fields)


def _subscribe(cur, *codes: str) -> None:
    for code in codes:
        cur.execute(
            "insert into dnc_subscriptions (area_code, subscribed_at) "
            "values (%s, now()) on conflict do nothing",
            (code,),
        )


def _one_report(sender: FakeSender, partner_id: UUID) -> str:
    mine = [m for f, m in sender.sent if f == str(partner_id)]
    assert len(mine) == 1, f"expected exactly one report, got {len(mine)}"
    return mine[0]


def _last_report_at(cur, partner_id) -> datetime | None:
    cur.execute("select last_report_at from partners where id = %s", (partner_id,))
    row = cur.fetchone()
    assert row is not None
    return row[0]


# ----------------------------------------------------------------------------------
# R2 tests 1/1b — heartbeat and the empty partner
# ----------------------------------------------------------------------------------


def test_heartbeat_sends_at_seven_days_not_before(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        _subscribe(cur, "818")
        due = _mk_partner(cur, f"P-{uuid4().hex[:8]}",
                          last_report_at=NOW - timedelta(days=8))
        recent = _mk_partner(cur, f"P-{uuid4().hex[:8]}",
                             last_report_at=NOW - timedelta(days=2))
        never = _mk_partner(cur, f"P-{uuid4().hex[:8]}", last_report_at=None)
        c1 = _pool_contact(cur, "+18185570001")
        c2 = _pool_contact(cur, "+18185570002")
        c3 = _pool_contact(cur, "+18185570003")
    owner_conn.commit()
    assign_batch(due, "rpt-1", "young", contact_ids=[c1])
    assign_batch(recent, "rpt-2", "young", contact_ids=[c2])
    assign_batch(never, "rpt-3", "young", contact_ids=[c3])
    # `recent` must model "reported 2 days ago, nothing since": its batch was
    # assigned BEFORE that report, so backdate the batch behind the watermark
    with owner_conn.cursor() as cur:
        cur.execute(
            "update assignment_batches set created_at = %s where partner_id = %s",
            (NOW - timedelta(days=3), recent),
        )
    owner_conn.commit()

    sender = FakeSender()
    run_partner_reports(sender=sender, now=NOW)

    recipients = {f for f, _ in sender.sent}
    assert str(due) in recipients
    assert str(never) in recipients
    assert str(recent) not in recipients
    for pid in (due, recent, never):
        _rm_partner(owner_conn, pid)


def test_empty_partner_gets_no_email_and_no_stamp(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        empty = _mk_partner(cur, f"P-{uuid4().hex[:8]}", last_report_at=None)
    owner_conn.commit()

    sender = FakeSender()
    run_partner_reports(sender=sender, now=NOW)

    assert all(f != str(empty) for f, _ in sender.sent)
    with owner_conn.cursor() as cur:
        assert _last_report_at(cur, empty) is None  # nothing sent, nothing stamped
    _rm_partner(owner_conn, empty)


# ----------------------------------------------------------------------------------
# R2 tests 2/3 — triggers, the re-pull line
# ----------------------------------------------------------------------------------


def test_new_batch_triggers_early_and_names_the_batch(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        _subscribe(cur, "818")
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}",
                              last_report_at=NOW - timedelta(days=3))
        contact = _pool_contact(cur, "+18185570100")
    owner_conn.commit()
    assign_batch(partner, "rpt-4", "young", contact_ids=[contact])

    sender = FakeSender()
    run_partner_reports(sender=sender, now=NOW)

    report = _one_report(sender, partner)
    assert "assigned 1 contact" in report
    assert "expires" in report
    _rm_partner(owner_conn, partner)


def test_a_removal_triggers_the_repull_line_with_the_count(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        _subscribe(cur, "818")
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}",
                              last_report_at=NOW - timedelta(days=1))
        keep = _pool_contact(cur, "+18185570200")
        gone = _pool_contact(cur, "+18185570201")
    owner_conn.commit()
    assign_batch(partner, "rpt-5", "young", contact_ids=[keep, gone])
    with owner_conn.cursor() as cur:  # age the assignment trigger out of the story
        cur.execute("update partners set last_report_at = %s where id = %s",
                    (NOW - timedelta(days=1), partner))
    owner_conn.commit()
    suppress(gone, "voice", "asked to stop")  # the S-6 removal

    sender = FakeSender()
    run_partner_reports(sender=sender, now=NOW)

    report = _one_report(sender, partner)
    assert "Re-pull your sheet before your next calling session." in report
    assert "1 opted out" in report
    _rm_partner(owner_conn, partner)


# ----------------------------------------------------------------------------------
# R2 test 4 — golden content, no effort language
# ----------------------------------------------------------------------------------


def test_holdings_content_and_the_effort_language_absence(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        _subscribe(cur, "818")
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}", last_report_at=None)
        a = _pool_contact(cur, "+18185570300")
        b = _pool_contact(cur, "+18185570301")
    owner_conn.commit()
    assign_batch(partner, "rpt-6", "young", contact_ids=[a, b])
    from service.assignment import export_batch

    export_batch(partner)  # stamps last_export_at → the export line renders

    sender = FakeSender()
    run_partner_reports(sender=sender, now=NOW)

    report = _one_report(sender, partner)
    assert "days left" in report            # the expiry headline
    assert "Contacts currently yours: 2" in report
    assert "Your last export was generated" in report
    # §1 "Deliberately absent" — the smoke word-list (named weak in the plan)
    for word in ("dial", "attempt", "worked"):
        assert word not in report.lower()
    _rm_partner(owner_conn, partner)


# ----------------------------------------------------------------------------------
# R2 test 5 — isolation
# ----------------------------------------------------------------------------------


def test_reports_never_name_another_partners_contacts(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        _subscribe(cur, "818")
        p1 = _mk_partner(cur, f"P-{uuid4().hex[:8]}", last_report_at=None)
        p2 = _mk_partner(cur, f"P-{uuid4().hex[:8]}", last_report_at=None)
        c1 = _pool_contact(cur, "+18185570400", business_name="Alpha Plumbing")
        c2 = _pool_contact(cur, "+18185570401", business_name="Beta Rooter")
    owner_conn.commit()
    assign_batch(p1, "rpt-7", "young", contact_ids=[c1])
    assign_batch(p2, "rpt-8", "young", contact_ids=[c2])
    suppress(c2, "voice", "asked")

    sender = FakeSender()
    run_partner_reports(sender=sender, now=NOW)

    r1 = _one_report(sender, p1)
    r2 = _one_report(sender, p2)
    assert "opted out" in r2 and "opted out" not in r1
    assert "Beta Rooter" not in r1 and "Alpha Plumbing" not in r2
    for pid in (p1, p2):
        _rm_partner(owner_conn, pid)


# ----------------------------------------------------------------------------------
# R2 tests 6/7/8/9 — state discipline, failure isolation, loud channel, house
# ----------------------------------------------------------------------------------


def test_a_send_writes_no_nudges_and_no_next_actions(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        _subscribe(cur, "818")
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}", last_report_at=None)
        contact = _pool_contact(cur, "+18185570500")
    owner_conn.commit()
    assign_batch(partner, "rpt-9", "young", contact_ids=[contact])

    run_partner_reports(sender=FakeSender(), now=NOW)

    with owner_conn.cursor() as cur:
        cur.execute("select count(*) from events where type = 'nudge.sent'")
        assert cur.fetchone()[0] == 0
        cur.execute(
            "select count(*) from contacts where next_action_at is not null"
        )
        assert cur.fetchone()[0] == 0
    _rm_partner(owner_conn, partner)


class _FailsFor:
    """A sender that raises for one recipient and records the rest."""

    def __init__(self, bad: str) -> None:
        self.bad = bad
        self.sent: list[tuple[str, str]] = []

    def send(self, founder: str, message: str) -> None:
        if founder == self.bad:
            raise RuntimeError("smtp down for this one")
        self.sent.append((founder, message))


def test_one_partners_failure_does_not_block_anothers_send(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        _subscribe(cur, "818")
        pa = _mk_partner(cur, f"P-{uuid4().hex[:8]}", last_report_at=None)
        pb = _mk_partner(cur, f"P-{uuid4().hex[:8]}", last_report_at=None)
        ca = _pool_contact(cur, "+18185570600")
        cb = _pool_contact(cur, "+18185570601")
    owner_conn.commit()
    assign_batch(pa, "rpt-10", "young", contact_ids=[ca])
    assign_batch(pb, "rpt-11", "young", contact_ids=[cb])

    sender = _FailsFor(str(pa))
    with pytest.raises(RuntimeError):  # the run fails loud at the end
        run_partner_reports(sender=sender, now=NOW)

    with owner_conn.cursor() as cur:
        assert _last_report_at(cur, pa) is None      # unstamped → next run retries
        assert _last_report_at(cur, pb) is not None  # B sent and stamped
    assert any(f == str(pb) for f, _ in sender.sent)
    for pid in (pa, pb):
        _rm_partner(owner_conn, pid)


def test_null_channel_fails_loud_never_a_silent_skip(clean_db, owner_conn):
    from seams.email_sender import EmailSender

    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}", last_report_at=None,
                              channel=None, address=None)
        _subscribe(cur, "818")
        contact = _pool_contact(cur, "+18185570700")
    owner_conn.commit()
    assign_batch(partner, "rpt-12", "young", contact_ids=[contact])

    sender = EmailSender(
        host="smtp.example.com", port=587, user="u", password="p",
        transport=lambda *a, **k: pytest.fail("must fail before any SMTP attempt"),
    )
    with pytest.raises(Exception):
        run_partner_reports(sender=sender, now=NOW)
    with owner_conn.cursor() as cur:
        assert _last_report_at(cur, partner) is None
    _rm_partner(owner_conn, partner)


def test_house_account_is_never_reported(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        _subscribe(cur, "818")
        contact = _pool_contact(cur, "+18185570800")
        cur.execute(
            "update contacts set owner_id = %s where id = %s",
            (HOUSE_PARTNER_ID, contact),
        )
    owner_conn.commit()

    sender = FakeSender()
    run_partner_reports(sender=sender, now=NOW)

    assert all(f != str(HOUSE_PARTNER_ID) for f, _ in sender.sent)
    with owner_conn.cursor() as cur:
        assert _last_report_at(cur, HOUSE_PARTNER_ID) is None


# ----------------------------------------------------------------------------------
# R2 test 10 — ordering: expiry runs before the report, in the real nightly
# ----------------------------------------------------------------------------------


def test_nightly_expires_before_reporting(clean_db, owner_conn):
    from jobs.nightly import run_nightly

    with owner_conn.cursor() as cur:
        _subscribe(cur, "818")
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}", last_report_at=None)
        contact = _pool_contact(cur, "+18185570900")
    owner_conn.commit()
    assign_batch(partner, "rpt-13", "young", contact_ids=[contact])
    with owner_conn.cursor() as cur:
        cur.execute(
            "update assignment_batches set expires_at = now() - interval '1 day' "
            "where partner_id = %s",
            (partner,),
        )
    owner_conn.commit()

    sender = FakeSender()
    run_nightly([], NOW - timedelta(days=1), sender=sender)

    report = _one_report(sender, partner)
    assert "1 expired" in report
    assert "Contacts currently yours: 0" in report  # never counted as still held
    _rm_partner(owner_conn, partner)


# ----------------------------------------------------------------------------------
# Section 2 — closes
# ----------------------------------------------------------------------------------


def test_closes_credited_by_code_or_sold_by_with_pending_details(
    clean_db, owner_conn
):
    with owner_conn.cursor() as cur:
        _subscribe(cur, "818")
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}", code="JK-01", rep=7,
                              last_report_at=None)
        held = _pool_contact(cur, "+18185571000")
        closed = _pool_contact(cur, "+18185571001", business_name="Gamma Drains")
    owner_conn.commit()
    assign_batch(partner, "rpt-14", "young", contact_ids=[held])

    # a correlated close credited by partner_code
    ingest_event("nmc", "signup.completed", NOW - timedelta(hours=4),
                 {"partner_code": "JK-01"}, external_id="cl-1", contact_id=closed)
    # an orphaned-but-credited close (sold_by matches; no contact yet)
    ingest_event("nmc", "signup.completed", NOW - timedelta(hours=3),
                 {"sold_by": 7}, external_id="cl-2", contact_id=None)
    # someone else's close — never this partner's
    ingest_event("nmc", "signup.completed", NOW - timedelta(hours=2),
                 {"partner_code": "XX-99"}, external_id="cl-3", contact_id=None)

    sender = FakeSender()
    run_partner_reports(sender=sender, now=NOW)

    report = _one_report(sender, partner)
    assert "Closes credited since your last report: 2" in report
    assert "Gamma Drains" in report
    assert "new close — details pending" in report
    assert "Total closes to date: 2" in report
    # no money language, ever (the smoke word-list, named weak)
    for word in ("vest", "paid", "bonus", "balance", "$"):
        assert word not in report.lower()
    _rm_partner(owner_conn, partner)


def test_no_closes_means_no_closes_section(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        _subscribe(cur, "818")
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}", code="JK-02",
                              last_report_at=None)
        held = _pool_contact(cur, "+18185571100")
    owner_conn.commit()
    assign_batch(partner, "rpt-15", "young", contact_ids=[held])

    sender = FakeSender()
    run_partner_reports(sender=sender, now=NOW)
    assert "Closes credited" not in _one_report(sender, partner)
    _rm_partner(owner_conn, partner)


# ----------------------------------------------------------------------------------
# Section 3 — the demo line, via the B2 client
# ----------------------------------------------------------------------------------


def test_demo_line_renders_from_the_feed_and_omits_when_unreachable(
    clean_db, owner_conn
):
    with owner_conn.cursor() as cur:
        _subscribe(cur, "818")
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}", rep=7, last_report_at=None)
        held = _pool_contact(cur, "+18185571200")
    owner_conn.commit()
    assign_batch(partner, "rpt-16", "young", contact_ids=[held])

    demos = FakeDemosClient(partners=[{
        "partnerNumber": "+18184180546", "salesRepId": "7",
        "calls": "5", "uniqueProspects": "3", "blockedCalls": "1",
        "textsForwarded": "2",
    }])
    sender = FakeSender()
    run_partner_reports(sender=sender, now=NOW, demos=demos)
    report = _one_report(sender, partner)
    assert ("On your demo line since your last report: 5 calls "
            "(3 unique prospects, 1 from blocked numbers), "
            "2 texts forwarded to you") in report

    # unreachable feed → the section is omitted, no placeholder, still sends
    with owner_conn.cursor() as cur:
        cur.execute("update partners set last_report_at = null where id = %s",
                    (partner,))
    owner_conn.commit()
    sender2 = FakeSender()
    run_partner_reports(sender=sender2, now=NOW, demos=FakeDemosClient(fail=True))
    assert "demo line" not in _one_report(sender2, partner)
    _rm_partner(owner_conn, partner)


# ----------------------------------------------------------------------------------
# C1 — the S-7 flip
# ----------------------------------------------------------------------------------


def test_s7_flip_inactivity_rules_route_to_young_event_rules_to_owner():
    from judgment.protocol import Recipient
    from judgment.rules.demo_no_show import RULE as demo_no_show
    from judgment.rules.hot_response import RULE as hot_response
    from judgment.rules.lost_aging import RULE as lost_aging
    from judgment.rules.quiet_reengage import RULE as quiet_reengage

    assert quiet_reengage.recipient is Recipient.YOUNG  # inference from absence
    assert lost_aging.recipient is Recipient.YOUNG
    assert hot_response.recipient is Recipient.DEAL_OWNER  # observed events
    assert demo_no_show.recipient is Recipient.DEAL_OWNER
