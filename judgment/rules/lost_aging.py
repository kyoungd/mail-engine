"""A responder gone silent past AGE_OUT_DAYS despite prior nudges — propose marking
lost, or one last postcard-style text."""

from datetime import date

from derivation.rules import INBOUND_TYPES
from judgment.protocol import Hit, Recipient


class _Rule:
    name = "lost_aging"
    priority = 9
    recipient = Recipient.DEAL_OWNER
    nudge = "Propose marking lost — or one last text"

    def evaluate(self, cur, params, as_of: date) -> list[Hit]:
        cur.execute(
            "select c.id from contacts c "
            "where c.is_seed = false "  # seeds never enter the judgment machinery (FR-7)
            "and c.stage_snapshot in ('responded', 'in_conversation') "
            "and coalesce((select max(e.occurred_at) from events e "
            "  where e.contact_id = c.id and e.type = any(%s)), 'epoch') "
            "< %s::date - make_interval(days => %s) "
            "and exists (select 1 from events e2 "
            "  where e2.contact_id = c.id and e2.type = 'nudge.sent')",
            (list(INBOUND_TYPES), as_of, params.age_out_days),
        )
        return [Hit(contact_id=r[0], wave_id=None) for r in cur.fetchall()]


RULE = _Rule()
