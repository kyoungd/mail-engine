"""A wave that looks broken: piece failure rate above FAIL_PCT, OR a wave that has
been out longer than RESP_CHECK_DAYS with zero response — investigate before the next
drop fires. A dead wave (delivered fine, nobody responded) is the more important half."""

from datetime import date

from derivation.rules import INBOUND_TYPES
from judgment.protocol import Hit, Recipient


class _Rule:
    name = "wave_anomaly"
    priority = 7
    recipient = Recipient.YOUNG
    nudge = "Wave looks broken or dead — investigate before the next drop"

    def evaluate(self, cur, params, as_of: date) -> list[Hit]:
        cur.execute(
            "with wave_stats as ("
            "  select w.id, w.executed_at, "
            "    count(p.id) as total, "
            "    count(*) filter (where p.status in ('returned', 'failed')) as bad, "
            "    (select count(*) from events e join pieces p2 on p2.contact_id = e.contact_id "
            "       where p2.wave_id = w.id and e.type = any(%(inbound)s)) as responses "
            "  from waves w join pieces p on p.wave_id = w.id "
            "  where w.status in ('executing', 'sent') "
            "  group by w.id, w.executed_at"
            ") "
            "select id, bad, total, responses from wave_stats "
            "where total > 0 and ("
            "  bad::float / total > %(fail_pct)s "
            "  or (executed_at is not null "
            "      and executed_at < %(as_of)s::date - make_interval(days => %(resp_days)s) "
            "      and responses = 0)"
            ")",
            {
                "inbound": list(INBOUND_TYPES),
                "fail_pct": params.fail_pct,
                "as_of": as_of,
                "resp_days": params.resp_check_days,
            },
        )
        return [
            Hit(
                contact_id=None,
                wave_id=r[0],
                facts={"failed": r[1], "total": r[2], "responses": r[3]},
            )
            for r in cur.fetchall()
        ]


RULE = _Rule()
