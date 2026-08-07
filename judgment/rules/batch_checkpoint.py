"""A LIVE batch past the day-30 checkpoint with no spine-observable activity —
check in with the partner (partner-lead-assignment.md §5 amendment 2026-08-05).
Visibility, never auto-reclaim: the S-7 principle says absence of spine evidence
is not proof of partner neglect, so this routes to Young as a judgment prompt.
The expired batch is the expiry job's, not this rule's."""

from datetime import date

from config.params import HOUSE_PARTNER_ID
from derivation.rules import INBOUND_TYPES
from judgment.protocol import Hit, Recipient

# What counts as activity on an assigned contact. Shared with the `partners
# status` view (jobs/partners_cli) — one definition, so the checkpoint and the
# status display can never disagree.
ACTIVITY_TYPES = frozenset(INBOUND_TYPES) | {
    "signup.completed",
    "note.demo_call",
    "note.partner",
    "note.general",
}


class _Rule:
    name = "batch_checkpoint"
    priority = 11
    recipient = Recipient.YOUNG
    nudge = "Batch past day 30 with no observable activity — check in with the partner"

    def evaluate(self, cur, params, as_of: date) -> list[Hit]:
        cur.execute(
            "select b.idempotency_key, p.name, b.delivered_count, "
            "(%s::date - b.created_at::date) "
            "from assignment_batches b join partners p on p.id = b.partner_id "
            "where p.status = 'active' and b.partner_id <> %s "
            "and b.created_at <= %s::date - make_interval(days => %s) "
            "and b.expires_at > now() "
            "and not exists (select 1 from events e "
            "  join contacts c on c.id = e.contact_id "
            "  where c.assignment_batch_id = b.id and e.type = any(%s) "
            "  and e.occurred_at >= b.created_at)",
            (as_of, HOUSE_PARTNER_ID, as_of, params.batch_checkpoint_days,
             list(ACTIVITY_TYPES)),
        )
        return [
            Hit(
                contact_id=None,
                wave_id=None,
                facts={
                    "batch_key": key,
                    "partner": partner,
                    "delivered": delivered,
                    "days_in": days_in,
                },
            )
            for key, partner, delivered, days_in in cur.fetchall()
        ]


RULE = _Rule()
