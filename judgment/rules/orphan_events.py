"""Unattributed events above ORPHAN_MAX — a roll-up of the attribution leaks to
review (weekly cadence in spirit; the per-rule cooldown keeps it from repeating daily)."""

from datetime import date

from judgment.protocol import Hit, Recipient


class _Rule:
    name = "orphan_events"
    priority = 10
    recipient = Recipient.YOUNG
    nudge = "Attribution leaks to review"

    def evaluate(self, cur, params, as_of: date) -> list[Hit]:
        cur.execute("select count(*) from events where contact_id is null")
        row = cur.fetchone()
        count = row[0] if row else 0
        if count <= params.orphan_max:
            return []
        return [Hit(contact_id=None, wave_id=None, facts={"count": count})]


RULE = _Rule()
