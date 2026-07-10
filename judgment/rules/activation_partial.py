"""A signup stuck at forwarding or calendar setup past PARTIAL_DAYS (but not yet
stalled) — offer to walk them through the step."""

from datetime import date

from judgment.protocol import Hit, Recipient


class _Rule:
    name = "activation_partial"
    priority = 5
    recipient = Recipient.YOUNG
    nudge = "Stuck at setup — offer to walk them through"

    def evaluate(self, cur, params, as_of: date) -> list[Hit]:
        cur.execute(
            "select a.contact_id from activation a "
            "where a.first_lead_at is null "
            "and (a.forwarding_at is null or a.calendar_at is null) "
            "and a.signed_up_at < %s::date - make_interval(days => %s) "
            "and a.signed_up_at >= %s::date - make_interval(days => %s)",
            (as_of, params.partial_days, as_of, params.stall_days),
        )
        return [Hit(contact_id=r[0], wave_id=None) for r in cur.fetchall()]


RULE = _Rule()
