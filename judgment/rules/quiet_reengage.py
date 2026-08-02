"""A live conversation gone quiet past QUIET_DAYS — ping today."""

from datetime import date

from derivation.rules import INBOUND_TYPES
from judgment.protocol import Hit, Recipient


class _Rule:
    name = "quiet_reengage"
    priority = 4
    # S-7 flip (Stage C1): inactivity is inferred from ABSENCE of spine evidence,
    # and for a partner-owned contact absence is not proof of neglect — this
    # routes to Young, never the partner.
    recipient = Recipient.YOUNG
    nudge = "The thread's gone quiet — ping today"

    def evaluate(self, cur, params, as_of: date) -> list[Hit]:
        cur.execute(
            "select c.id from contacts c "
            "where c.is_seed = false "  # seeds never enter the judgment machinery (FR-7)
            "and c.stage_snapshot = 'in_conversation' "
            "and coalesce((select max(e.occurred_at) from events e "
            "  where e.contact_id = c.id and e.type = any(%s)), 'epoch') "
            "< %s::date - make_interval(days => %s)",
            (list(INBOUND_TYPES), as_of, params.quiet_days),
        )
        return [Hit(contact_id=r[0], wave_id=None) for r in cur.fetchall()]


RULE = _Rule()
