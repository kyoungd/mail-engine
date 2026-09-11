"""Registry removals in the partner report (operator decision, 2026-09-10).

A number the scrub finds on the national Do Not Call registry leaves the partner's
list, but a sheet the partner exported earlier still carries it. So the report
names each one — company and number — as an exclusion list, and says which sheets
still carry them. A registry listing is not an opt-out and is never counted as one.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from config.params import HOUSE_PARTNER_ID
from jobs.dnc_refresh import dnc_refresh
from judgment.partner_report import run_partner_reports
from seams.fakes import FakeDncRegistry, FakeSender
from service.assignment import assign_batch
from service.contacts import suppress
from tests.factories import new_contact

NOW = datetime.now(UTC)
DUE = NOW - timedelta(days=22)  # past the 21-day recheck, still assignable (31)


# helpers _mk_partner, _rm_partner, _pool_contact, _subscribe, _one_report:
# copied from test_partner_report.py (frozen; not imported from a test module)


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
    fields.setdefault("dnc_checked_at", NOW)
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


def _listed(*numbers: str) -> FakeDncRegistry:
    return FakeDncRegistry(version="2026-09-10", numbers={"818": set(numbers)})


def _after_assignment(owner_conn, partner: UUID) -> None:
    with owner_conn.cursor() as cur:
        cur.execute("update partners set last_report_at = %s where id = %s",
                    (NOW - timedelta(days=1), partner))
    owner_conn.commit()


def _reclaim_day(owner_conn, contact_id: UUID) -> str:
    with owner_conn.cursor() as cur:
        cur.execute("select occurred_at from events where type = 'contact.reclaimed' "
                    "and contact_id = %s", (contact_id,))
        row = cur.fetchone()
    assert row is not None
    return row[0].astimezone(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")


def test_a_registry_removal_names_the_company_and_number_to_exclude(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        _subscribe(cur, "818")
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        keep = _pool_contact(cur, "+18185570500", business_name="Keep Plumbing")
        listed = _pool_contact(cur, "+18185570501", business_name="Whole Earth Inc",
                               dnc_checked_at=DUE)
    owner_conn.commit()
    assign_batch(partner, "reg-1", "young", contact_ids=[keep, listed])
    _after_assignment(owner_conn, partner)
    dnc_refresh(_listed("8185570501"))

    sender = FakeSender()
    run_partner_reports(sender=sender, now=NOW)
    report = _one_report(sender, partner)

    assert ("Now on the national Do Not Call registry — removed from your list, "
            "do not call:") in report
    assert "- Whole Earth Inc, (818) 557-0501" in report
    assert ("These numbers are still on any sheet you exported before "
            f"{_reclaim_day(owner_conn, listed)}.") in report
    assert "Re-pull your sheet before your next calling session." in report
    assert "Keep Plumbing" not in report
    assert "opted out" not in report
    _rm_partner(owner_conn, partner)


def test_the_registry_is_never_counted_as_an_opt_out(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        _subscribe(cur, "818")
        partner = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        asked = _pool_contact(cur, "+18185570601", business_name="Asked Rooter")
        listed = _pool_contact(cur, "+18185570602", business_name="Listed Electric",
                               dnc_checked_at=DUE)
    owner_conn.commit()
    assign_batch(partner, "reg-2", "young", contact_ids=[asked, listed])
    _after_assignment(owner_conn, partner)
    suppress(asked, "voice", "asked to stop")
    dnc_refresh(_listed("8185570602"))

    sender = FakeSender()
    run_partner_reports(sender=sender, now=NOW)
    report = _one_report(sender, partner)

    assert "Removed since your last report: 1 opted out, 0 reclaimed, 0 expired" in report
    assert "- Listed Electric, (818) 557-0602" in report
    assert "Asked Rooter" not in report  # an opt-out is counted, never named
    _rm_partner(owner_conn, partner)


def test_a_partner_never_sees_another_partners_registry_numbers(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        _subscribe(cur, "818")
        p1 = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        p2 = _mk_partner(cur, f"P-{uuid4().hex[:8]}")
        c1 = _pool_contact(cur, "+18185570701", business_name="Alpha Plumbing")
        c2 = _pool_contact(cur, "+18185570702", business_name="Beta Rooter",
                           dnc_checked_at=DUE)
    owner_conn.commit()
    assign_batch(p1, "reg-3", "young", contact_ids=[c1])
    assign_batch(p2, "reg-4", "young", contact_ids=[c2])
    dnc_refresh(_listed("8185570702"))

    sender = FakeSender()
    run_partner_reports(sender=sender, now=NOW)
    r1, r2 = _one_report(sender, p1), _one_report(sender, p2)

    assert "- Beta Rooter, (818) 557-0702" in r2
    assert "Beta Rooter" not in r1 and "557-0702" not in r1
    for pid in (p1, p2):
        _rm_partner(owner_conn, pid)
