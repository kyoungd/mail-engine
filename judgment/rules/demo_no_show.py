"""A recorded demo no-show with no later rebook — one graceful rebook text."""

from datetime import date

from judgment.protocol import Hit, Recipient


class _Rule:
    name = "demo_no_show"
    priority = 3
    recipient = Recipient.DEAL_OWNER
    nudge = "No-show — one graceful rebook text"

    def evaluate(self, cur, params, as_of: date) -> list[Hit]:
        cur.execute(
            "select distinct c.id from contacts c "
            "join events e on e.contact_id = c.id and e.type = 'demo.no_show' "
            "where c.is_seed = false "  # seeds never enter the judgment machinery (FR-7)
            "and not exists (select 1 from events e2 "
            "  where e2.contact_id = c.id and e2.type = 'demo.booked' "
            "  and e2.occurred_at > e.occurred_at)"
        )
        return [Hit(contact_id=r[0], wave_id=None) for r in cur.fetchall()]


RULE = _Rule()
