"""Running it (docs/contact-engine/06b-running-it.md §4.1, §4.3): the record of each
nightly that completes, and the status the website reads — the facts, and the alerts
that hold now. contact-engine names an alert; the website sends it (1.7).
"""

from datetime import datetime, timedelta
from typing import Any

from psycopg import sql

from config.params import (
    CALL_OPEN_ALERT_HOURS,
    DAILY_RUN_ALERT_HOURS,
    DNC_EXPIRY_ALERT_DAYS,
    DNC_FRESHNESS_DAYS,
    HOUSE_PARTNER_ID,
    NEVER_CHECKED_ALERT_HOURS,
)
from db.session import transaction
from service.dnc import BLOCKED_SQL


def record_daily_run(at: datetime) -> None:
    with transaction() as conn:
        conn.execute("insert into daily_runs (finished_at) values (%s)", (at,))


# §4.3 (a) and (b), over the alias `c`: `dnc_status`'s rule, read at %(t)s = at + 7 days.
# A contact's list counts only as `dnc_status` reads it; one linked otherwise is
# `not_checked` and in neither.
_EXPIRING_SQL = sql.SQL(
    "with codes as ("
    "  select area_code, min(subscribed_at) as subscribed_at "
    "  from dnc_subscriptions group by area_code), "
    "people as ("
    "  select substring(c.phone_e164 from 3 for 3) as code, c.owner_id, "
    "  c.dnc_checked_at, c.dnc_snapshot_id, c.created_at, c.id, "
    "  (select s.version_date from dnc_snapshots s where s.id = c.dnc_snapshot_id "
    "   and s.status = 'accepted' and s.version_date is not null "
    "   and s.area_code is not distinct from substring(c.phone_e164 from 3 for 3)) "
    "   as list_date "
    "  from contacts c "
    "  where c.phone_e164 is not null and not c.is_seed and not c.dnc_registry "
    "  and not {blocked} "
    "  and substring(c.phone_e164 from 3 for 3) in (select area_code from codes)) "
    "select p.code, "
    "  count(*) filter (where p.expiring and p.owner_id <> %(house)s), "
    "  count(*) filter (where p.expiring and p.owner_id = %(house)s), "
    "  count(*) filter (where p.never_checked) "
    "from ("
    "  select p.code, p.owner_id, "
    "  (p.dnc_checked_at is not null and p.dnc_checked_at <= %(at)s "
    "   and not (p.dnc_snapshot_id is not null and p.list_date is null) "
    "   and (p.dnc_checked_at < %(t)s - make_interval(days => %(fresh)s) "
    "        or p.list_date < (%(t)s at time zone 'UTC')::date - %(fresh)s)) as expiring, "
    "  (p.dnc_checked_at is null and greatest(p.created_at, "
    "     (select max(i.added_at) from intake_rep i where i.contact_id = p.id), "
    "     k.subscribed_at) < %(at)s - make_interval(hours => %(never)s)) "
    "   as never_checked "
    "  from people p join codes k on k.area_code = p.code) p "
    "group by p.code"
).format(blocked=BLOCKED_SQL)


def _expiring(cur, at: datetime) -> dict[str, Any]:
    cur.execute("select distinct area_code from dnc_subscriptions order by area_code")
    by_code = {code: {"held": 0, "pool": 0, "never_checked": 0}
               for (code,) in cur.fetchall()}
    cur.execute(_EXPIRING_SQL, {
        "at": at, "t": at + timedelta(days=DNC_EXPIRY_ALERT_DAYS),
        "fresh": DNC_FRESHNESS_DAYS, "never": NEVER_CHECKED_ALERT_HOURS,
        "house": HOUSE_PARTNER_ID,
    })
    for code, held, pool, never in cur.fetchall():
        by_code[code] = {"held": held, "pool": pool, "never_checked": never}
    return {
        "held": sum(c["held"] for c in by_code.values()),
        "pool": sum(c["pool"] for c in by_code.values()),
        "never_checked": sum(c["never_checked"] for c in by_code.values()),
        "by_area_code": by_code,
    }


def status(at: datetime) -> dict[str, Any]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("select max(finished_at) from daily_runs")
            last_run = cur.fetchone()[0]  # pyright: ignore[reportOptionalSubscript]
            cur.execute("select max(started_at) from dnc_runs where not limited")
            last_scrub = cur.fetchone()[0]  # pyright: ignore[reportOptionalSubscript]
            expiring = _expiring(cur, at)
            cur.execute(
                "select count(*) from calls where opened_at is not null "
                "and outcome is null and cleared_at is null and opened_at < %s",
                (at - timedelta(hours=CALL_OPEN_ALERT_HOURS),),
            )
            open_calls = cur.fetchone()[0]  # pyright: ignore[reportOptionalSubscript]

    alerts: list[dict[str, Any]] = []
    if last_run is None or last_run < at - timedelta(hours=DAILY_RUN_ALERT_HOURS):
        alerts.append({"code": "daily_run_missing",
                       "detail": {"last_finished_at": last_run}})
    if expiring["held"] or expiring["pool"] or expiring["never_checked"]:
        alerts.append({"code": "dnc_checks_expiring", "detail": {
            "held": expiring["held"], "pool": expiring["pool"],
            "never_checked": expiring["never_checked"],
            "by_area_code": {code: counts for code, counts in
                             expiring["by_area_code"].items() if any(counts.values())},
        }})
    if open_calls:
        alerts.append({"code": "call_left_open", "detail": {"count": open_calls}})
    return {
        "daily_run": {"last_finished_at": last_run},
        "scrub": {"last_started_at": last_scrub},
        "dnc_checks_expiring": expiring,
        "calls_open_over_24h": open_calls,
        "alerts": alerts,
    }
