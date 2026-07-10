"""A draft wave whose scheduled date is within LEAD_DAYS — approve it or it slips."""

from datetime import date

from judgment.protocol import Hit, Recipient


class _Rule:
    name = "approval_pending"
    priority = 8
    recipient = Recipient.YOUNG
    nudge = "Wave needs your approval or it slips"

    def evaluate(self, cur, params, as_of: date) -> list[Hit]:
        cur.execute(
            "select w.id from waves w "
            "where w.status = 'draft' and w.scheduled_for is not null "
            "and w.scheduled_for <= %s::date + make_interval(days => %s)",
            (as_of, params.lead_days),
        )
        return [Hit(contact_id=None, wave_id=r[0]) for r in cur.fetchall()]


RULE = _Rule()
