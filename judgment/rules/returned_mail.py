"""Contacts with two returned pieces (auto-suppressed by derivation) — a single FYI
roll-up, not a per-contact nag."""

from datetime import date

from derivation.rules import RETURNED_SUPPRESSION_COUNT
from judgment.protocol import Hit, Recipient


class _Rule:
    name = "returned_mail"
    priority = 6
    recipient = Recipient.YOUNG
    nudge = "Returned mail — auto-suppressed, FYI"

    def evaluate(self, cur, params, as_of: date) -> list[Hit]:
        cur.execute(
            "select c.id from contacts c where "
            "c.is_seed = false and "  # seeds never enter the judgment machinery (FR-7)
            "(select count(*) from events e "
            "  where e.contact_id = c.id and e.type = 'piece.returned') >= %s",
            (RETURNED_SUPPRESSION_COUNT,),
        )
        contacts = [str(r[0]) for r in cur.fetchall()]
        if not contacts:
            return []
        return [Hit(contact_id=None, wave_id=None,
                    facts={"count": len(contacts), "contacts": contacts})]


RULE = _Rule()
