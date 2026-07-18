"""A contact that just responded and hasn't been nudged yet — reply while warm."""

from datetime import date

from judgment.protocol import Hit, Recipient


class _Rule:
    name = "hot_response"
    priority = 1
    recipient = Recipient.DEAL_OWNER
    nudge = "New responder — reply while warm"

    def evaluate(self, cur, params, as_of: date) -> list[Hit]:
        cur.execute(
            "select c.id from contacts c "
            "where c.is_seed = false "  # seeds never enter the judgment machinery (FR-7)
            "and c.stage_snapshot = 'responded' "
            "and not exists (select 1 from events e "
            "  where e.contact_id = c.id and e.type = 'nudge.sent')"
        )
        return [Hit(contact_id=r[0], wave_id=None) for r in cur.fetchall()]


RULE = _Rule()
