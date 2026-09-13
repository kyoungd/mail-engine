"""A subscribed area code's registry check is aging toward the 31-day safe-harbor
wall (§6, Phase 2). Fires at dnc_version_alert_days (default 24 — a week of margin):
the scrub is dead, the SAN expired, or the download broke. High priority — an expired
version stops dialing in that code, exactly like a drained pool (S-9's
drain-not-stale failure mode).

PER CODE, not global (Architecture B, Phase 4). The rule used to read one
`max(occurred_at)` over every check event, which under hybrid coverage is dominated
by whichever code is scrubbed most often: NMC's own daily codes would mask a
partner's dead one indefinitely. A code's age is the OLDER of two: its newest
`contacts.dnc_checked_at` (a dead scrub) and its newest accepted snapshot's
`version_date` (dead uploads — the scrub keeps stamping fresh checks against an old
list, so check age alone never sees it; 16 CFR 310.4(b)(3)(iv) counts the list's age).

One hit carrying every stale code, not one hit per code: this is a single operator
action ("the scrub is broken"), and one nudge per area code would eat the budget.
"""

from datetime import date

from judgment.protocol import Hit, Recipient


class _Rule:
    name = "dnc_version_alert"
    priority = 0  # above hot_response: a stale registry stops all dialing
    recipient = Recipient.YOUNG
    nudge = "DNC registry version is aging toward the 31-day wall — check the scrub"

    def evaluate(self, cur, params, as_of: date) -> list[Hit]:
        cur.execute("select distinct area_code from dnc_subscriptions")
        subscribed = [row[0] for row in cur.fetchall()]
        if not subscribed:
            return []  # nothing subscribed — nobody is dialing against the registry

        cur.execute(
            "select substring(phone_e164 from 3 for 3) as area_code, "
            "max(dnc_checked_at) from contacts "
            "where phone_e164 is not null and is_seed = false "
            "and substring(phone_e164 from 3 for 3) = any(%s) "
            "group by 1",
            (subscribed,),
        )
        newest = dict(cur.fetchall())

        cur.execute(
            "select distinct on (area_code) area_code, version_date from dnc_snapshots "
            "where status = 'accepted' and area_code = any(%s) "
            "order by area_code, version_date desc",
            (subscribed,),
        )
        newest_list = dict(cur.fetchall())

        stale = []
        for area_code in sorted(subscribed):
            checked = newest.get(area_code)
            listed = newest_list.get(area_code)
            age = None if checked is None else (as_of - checked.date()).days
            if age is not None and listed is not None:
                age = max(age, (as_of - listed).days)
            if age is None or age > params.dnc_version_alert_days:
                stale.append({"area_code": area_code, "age_days": age})

        if not stale:
            return []
        return [Hit(contact_id=None, wave_id=None, facts={"stale": stale})]


RULE = _Rule()
