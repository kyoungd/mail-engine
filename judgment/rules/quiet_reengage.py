"""A live conversation gone quiet past QUIET_DAYS — ping today."""

from datetime import date

from derivation.rules import INBOUND_TYPES
from judgment.protocol import Hit, Recipient


class _Rule:
    name = "quiet_reengage"
    priority = 4
    recipient = Recipient.DEAL_OWNER
    nudge = "The thread's gone quiet — ping today"

    def evaluate(self, cur, params, as_of: date) -> list[Hit]:
        cur.execute(
            "select c.id from contacts c "
            "where c.stage_snapshot = 'in_conversation' "
            "and coalesce((select max(e.occurred_at) from events e "
            "  where e.contact_id = c.id and e.type = any(%s)), 'epoch') "
            "< %s::date - make_interval(days => %s)",
            (list(INBOUND_TYPES), as_of, params.quiet_days),
        )
        return [Hit(contact_id=r[0], wave_id=None) for r in cur.fetchall()]


RULE = _Rule()
