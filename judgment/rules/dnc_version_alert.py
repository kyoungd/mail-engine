"""The registry version is aging toward the 31-day safe-harbor wall (§6, Phase 2).
Fires at dnc_version_alert_days (default 24 — a week of margin): the scrub is dead,
the SAN expired, or the download broke. High priority — an expired version stops
John dialing, exactly like a drained pool (S-9's drain-not-stale failure mode)."""

from datetime import date

from judgment.protocol import Hit, Recipient


class _Rule:
    name = "dnc_version_alert"
    priority = 0  # above hot_response: a stale registry stops all dialing
    recipient = Recipient.YOUNG
    nudge = "DNC registry version is aging toward the 31-day wall — check the scrub"

    def evaluate(self, cur, params, as_of: date) -> list[Hit]:
        cur.execute("select count(*) from dnc_subscriptions")
        row = cur.fetchone()
        if row is None or row[0] == 0:
            return []  # nothing subscribed — nobody is dialing against the registry

        cur.execute(
            "select max(occurred_at) from events where type = 'contact.dnc_checked'"
        )
        row = cur.fetchone()
        newest = row[0] if row else None
        if newest is None:
            return [Hit(contact_id=None, wave_id=None,
                        facts={"newest_check": None, "age_days": None})]
        age = (as_of - newest.date()).days
        if age <= params.dnc_version_alert_days:
            return []
        return [Hit(contact_id=None, wave_id=None,
                    facts={"newest_check": newest.isoformat(), "age_days": age})]


RULE = _Rule()
