"""The standing export-compliance invariant (testing.md § Standing invariants).

test_partner_assignment.py pins each gate one at a time. This file pins the
PROPERTY the whole red tier exists for:

    No export ever contains a number the program may not dial.

One adversarial pool holds every violating condition at once; the real
assign → flip → export sequence runs over it; then the violating set is
RE-DERIVED with SQL independent of the WHERE clauses under test and intersected
with the phones actually in the CSV. A mutant that drops a single predicate from
`assign_batch` or `export_batch` must turn this file red even while every
per-gate test still passes.

The post-assignment flips are the paths the per-gate tests cannot reach:
`dnc_registry` flipping on an already-assigned contact is exactly what the
21-day scrub cycle produces, and the raw `do_not_call` flip (bypassing
`suppress`, which would also release custody) is the adversarial construction
that proves export's own predicate — not custody release — keeps the row off
the sheet.
"""

import csv
import io
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from config.params import DNC_FRESHNESS_DAYS, HOUSE_PARTNER_ID
from service.assignment import assign_batch, export_batch
from tests.factories import new_contact

FRESH = datetime.now(UTC)
STALE = FRESH - timedelta(days=DNC_FRESHNESS_DAYS + 5)


def _mk_partner(cur, name: str) -> UUID:
    # partners survives clean_db, and a failing run never reaches _rm_partner —
    # a unique name keeps a leftover row from aborting the next run's insert
    cur.execute(
        "insert into partners (name, status, weekly_hours) values (%s, 'active', 5) "
        "returning id",
        (f"{name}-{uuid4().hex[:8]}",),
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


def _adversarial_pool(cur) -> dict[str, UUID]:
    """Every violating condition at once, plus clean rows destined for the flips."""
    cur.execute(
        "insert into dnc_subscriptions (area_code, subscribed_at) values ('818', now()) "
        "on conflict do nothing"
    )
    pool = {
        "clean": new_contact(cur, phone_e164="+18185550001", dnc_checked_at=FRESH),
        "flip_listed": new_contact(cur, phone_e164="+18185550002", dnc_checked_at=FRESH),
        "flip_optout": new_contact(cur, phone_e164="+18185550003", dnc_checked_at=FRESH),
        "flip_stale": new_contact(cur, phone_e164="+18185550004", dnc_checked_at=FRESH),
        "listed": new_contact(
            cur, phone_e164="+18185550010", dnc_checked_at=FRESH, dnc_registry=True
        ),
        "voice_suppressed": new_contact(
            cur, phone_e164="+18185550011", dnc_checked_at=FRESH, do_not_call=True
        ),
        "tombstoned": new_contact(cur, phone_e164="+18185550012", dnc_checked_at=FRESH),
        "unsubscribed_area": new_contact(
            cur, phone_e164="+13105550013", dnc_checked_at=FRESH
        ),
        "stale": new_contact(cur, phone_e164="+18185550014", dnc_checked_at=STALE),
        "unchecked": new_contact(cur, phone_e164="+18185550015"),
        "no_phone": new_contact(cur),
        "won": new_contact(
            cur, phone_e164="+18185550016", dnc_checked_at=FRESH, stage_snapshot="won"
        ),
        "seed": new_contact(
            cur, phone_e164="+18185550017", dnc_checked_at=FRESH, is_seed=True,
            seed_key="inv-seed", intake=False,
        ),
    }
    cur.execute(
        "insert into suppression_tombstones (phone_e164, channel, reason) "
        "values ('+18185550012', 'voice', 'ccpa_delete')"
    )
    return pool


def _forbidden_phones(cur) -> set[str]:
    """The violating set, re-derived independently of the code under test."""
    cur.execute(
        "select c.phone_e164 from contacts c where c.phone_e164 is not null and ("
        "  c.do_not_call or c.dnc_registry or c.is_seed"
        "  or c.stage_snapshot::text not in ('prospect', 'in_sequence', 'lost')"
        "  or c.dnc_checked_at is null"
        "  or c.dnc_checked_at < now() - make_interval(days => %s)"
        "  or substring(c.phone_e164 from 3 for 3) not in"
        "     (select area_code from dnc_subscriptions)"
        "  or exists (select 1 from suppression_tombstones t"
        "             where t.phone_e164 = c.phone_e164 and t.channel = 'voice')"
        ")",
        (DNC_FRESHNESS_DAYS,),
    )
    return {r[0] for r in cur.fetchall()}


def _exported_phones(result) -> set[str]:
    rows = list(csv.DictReader(io.StringIO(result.csv)))
    return {row["phone"] for row in rows}


def test_no_export_ever_contains_a_forbidden_number(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        pool = _adversarial_pool(cur)
        partner_id = _mk_partner(cur, "Invariant-partner")
    owner_conn.commit()

    report = assign_batch(partner_id, "inv-key-1", actor="test", count=50)

    clean_ids = {pool[k] for k in ("clean", "flip_listed", "flip_optout", "flip_stale")}
    assert set(report.assigned) == clean_ids
    # the rule path filters seeds in the WHERE (`c.is_seed = false`), so a seed
    # never reaches _gate — it must appear NOWHERE, not under a "seed" cause
    # (the id-list path's "seed" cause is pinned in test_partner_assignment.py)
    assert set(report.shortfall) == {
        "dnc_registry", "voice_suppressed", "tombstoned", "dnc_unsubscribed",
        "dnc_stale", "no_phone", "won",
    }
    all_shortfall_ids = {c for ids in report.shortfall.values() for c in ids}
    assert pool["seed"] not in all_shortfall_ids | set(report.assigned)
    assert report.shortfall["dnc_stale"] == sorted(
        [pool["stale"], pool["unchecked"]], key=str
    )

    with owner_conn.cursor() as cur:
        cur.execute(
            "update contacts set dnc_registry = true where id = %s",
            (pool["flip_listed"],),
        )
        cur.execute(
            "update contacts set do_not_call = true where id = %s",
            (pool["flip_optout"],),
        )
        cur.execute(
            "update contacts set dnc_checked_at = %s where id = %s",
            (STALE, pool["flip_stale"]),
        )
    owner_conn.commit()

    result = export_batch(partner_id)
    exported = _exported_phones(result)

    assert exported == {"+18185550001"}
    assert result.shortfall == {"dnc_stale": [pool["flip_stale"]]}

    with owner_conn.cursor() as cur:
        forbidden = _forbidden_phones(cur)
    assert exported & forbidden == set()
    assert "+18185550002" in forbidden and "+18185550003" in forbidden

    _rm_partner(owner_conn, partner_id)


def test_a_second_pull_regates_from_scratch(clean_db, owner_conn):
    """The stale-sheet mitigation is the partner re-pulling: the SAME batch,
    exported twice, shrinks when a number becomes forbidden in between — the
    exclusion is per-pull, not per-assignment."""
    with owner_conn.cursor() as cur:
        pool = _adversarial_pool(cur)
        partner_id = _mk_partner(cur, "Invariant-repull")
    owner_conn.commit()

    assign_batch(partner_id, "inv-key-2", actor="test", count=50)
    first = _exported_phones(export_batch(partner_id))
    assert first == {
        "+18185550001", "+18185550002", "+18185550003", "+18185550004"
    }

    with owner_conn.cursor() as cur:
        cur.execute(
            "update contacts set dnc_registry = true where id = %s",
            (pool["flip_listed"],),
        )
    owner_conn.commit()

    second = _exported_phones(export_batch(partner_id))
    assert second == first - {"+18185550002"}

    _rm_partner(owner_conn, partner_id)
