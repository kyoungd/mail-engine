"""Shared fixtures for the day-30 checkpoint rule and `partners status` (§5
amendment 2026-08-05). Not a test module — no `test_` prefix, so pytest never
collects it; both test files import from here so the two suites age batches the
same way."""

from datetime import UTC, datetime
from uuid import UUID

from config.params import HOUSE_PARTNER_ID
from service.assignment import assign_batch
from tests.factories import new_contact

FRESH = datetime.now(UTC)


def mk_partner(cur, name: str) -> UUID:
    cur.execute(
        "insert into partners (name, status, weekly_hours) values (%s, 'active', 10) "
        "returning id",
        (name,),
    )
    row = cur.fetchone()
    assert row is not None
    return row[0]


def aged_quiet_batch(
    owner_conn,
    partner_name: str,
    *,
    days: int,
    key: str,
    phones: tuple[str, ...] = ("+18185551001", "+18185551002"),
):
    """Assign real contacts through the real verb, then rewind the batch clock
    so it sits `days` into its 90-day custody window."""
    with owner_conn.cursor() as cur:
        cur.execute(
            "insert into dnc_subscriptions (area_code, subscribed_at) "
            "values ('818', now()) on conflict do nothing"
        )
        partner_id = mk_partner(cur, partner_name)
        contact_ids = [
            new_contact(cur, phone_e164=p, dnc_checked_at=FRESH) for p in phones
        ]
    owner_conn.commit()
    assign_batch(partner_id, key, "test", contact_ids=contact_ids)
    with owner_conn.cursor() as cur:
        cur.execute(
            "update assignment_batches set "
            "created_at = now() - make_interval(days => %s), "
            "expires_at = now() + make_interval(days => %s) "
            "where idempotency_key = %s",
            (days, 90 - days, key),
        )
    owner_conn.commit()
    return partner_id, contact_ids


def remove_partners(owner_conn, *prefixes: str) -> None:
    """Partners are deliberately not truncated by clean_db — tests that create
    extra partners delete them (the 0009 seed comment's rule)."""
    with owner_conn.cursor() as cur:
        for prefix in prefixes:
            cur.execute("select id from partners where name like %s", (prefix + "%",))
            for (partner_id,) in cur.fetchall():
                cur.execute(
                    "update contacts set owner_id = %s, assignment_batch_id = null "
                    "where owner_id = %s",
                    (HOUSE_PARTNER_ID, partner_id),
                )
                cur.execute(
                    "delete from assignment_batches where partner_id = %s",
                    (partner_id,),
                )
                cur.execute("delete from partners where id = %s", (partner_id,))
    owner_conn.commit()
