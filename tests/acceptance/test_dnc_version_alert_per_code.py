"""Phase 4 gate: the registry-age alert is PER COVERED CODE.

The rule used to read one global `max(occurred_at)` over every check event. Under
hybrid coverage that number is dominated by whichever code is scrubbed most often,
so NMC's own daily-scrubbed codes would mask a partner's dead one indefinitely —
the alert stays quiet while that partner's numbers age past the 31-day wall.
"""

from datetime import date, timedelta
from uuid import UUID

import psycopg

from config.params import DEFAULT_PARAMS, HOUSE_PARTNER_ID
from judgment.rules.dnc_version_alert import RULE as dnc_version_alert
from tests.factories import new_contact

AS_OF = date(2026, 9, 9)


def _evaluate(readonly_url, params=DEFAULT_PARAMS):
    with psycopg.connect(readonly_url) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            return dnc_version_alert.evaluate(cur, params, AS_OF)


def _subscribe(conn, area_code: str, holder: UUID = HOUSE_PARTNER_ID) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "insert into dnc_subscriptions (area_code, san_holder_id, subscribed_at) "
            "values (%s, %s, now()) on conflict do nothing",
            (area_code, holder),
        )
    conn.commit()


def _checked(conn, phone: str, days_ago: int) -> None:
    with conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164=phone)
        cur.execute(
            "update contacts set dnc_checked_at = %s where id = %s",
            (AS_OF - timedelta(days=days_ago), contact_id),
        )
    conn.commit()


def test_alert_fires_when_one_code_is_stale_though_another_is_fresh(
    clean_db, owner_conn, readonly_url
):
    _subscribe(owner_conn, "818")
    _subscribe(owner_conn, "714")
    _checked(owner_conn, "+18185550009", days_ago=1)    # NMC's daily code
    _checked(owner_conn, "+17145550009", days_ago=30)   # a partner's dead one

    hits = _evaluate(readonly_url)

    assert len(hits) == 1
    stale = hits[0].facts["stale"]
    assert [row["area_code"] for row in stale] == ["714"]
    assert stale[0]["age_days"] == 30


def test_a_subscribed_code_never_scrubbed_at_all_fires(clean_db, owner_conn, readonly_url):
    _subscribe(owner_conn, "805")

    hits = _evaluate(readonly_url)

    assert len(hits) == 1
    assert hits[0].facts["stale"][0] == {"area_code": "805", "age_days": None}


def test_no_alert_when_every_covered_code_is_fresh(clean_db, owner_conn, readonly_url):
    _subscribe(owner_conn, "818")
    _subscribe(owner_conn, "714")
    _checked(owner_conn, "+18185550009", days_ago=1)
    _checked(owner_conn, "+17145550009", days_ago=2)

    assert _evaluate(readonly_url) == []


def test_no_alert_when_nothing_is_subscribed(clean_db, readonly_url):
    assert _evaluate(readonly_url) == []
