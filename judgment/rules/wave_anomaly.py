"""An executing/sent wave whose piece failure rate exceeds FAIL_PCT — investigate
before the next drop fires."""

from datetime import date

from judgment.protocol import Hit, Recipient


class _Rule:
    name = "wave_anomaly"
    priority = 7
    recipient = Recipient.YOUNG
    nudge = "Wave looks broken — investigate before the next drop"

    def evaluate(self, cur, params, as_of: date) -> list[Hit]:
        cur.execute(
            "select w.id, "
            "  count(*) filter (where p.status in ('returned', 'failed')) as bad, "
            "  count(*) as total "
            "from waves w join pieces p on p.wave_id = w.id "
            "where w.status in ('executing', 'sent') "
            "group by w.id "
            "having count(*) > 0 and "
            "  count(*) filter (where p.status in ('returned', 'failed'))::float "
            "  / count(*) > %s",
            (params.fail_pct,),
        )
        return [
            Hit(contact_id=None, wave_id=r[0], facts={"failed": r[1], "total": r[2]})
            for r in cur.fetchall()
        ]


RULE = _Rule()
