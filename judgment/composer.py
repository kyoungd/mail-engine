"""Tier 2: the AI briefing officer, with a template fallback. Delivery never depends
on the model — if no client is supplied, or the call fails or returns empty, the
deterministic template is used and the digest still sends."""

from domain.types import Event
from judgment.protocol import Hit, Rule


def template_brief(hit: Hit, rule: Rule) -> str:
    if hit.contact_id is not None:
        target = f"contact {hit.contact_id}"
    elif hit.wave_id is not None:
        target = f"wave {hit.wave_id}"
    else:
        target = "roll-up"
    return f"[{rule.name}] {rule.nudge} — {target}"


def _prompt(hit: Hit, timeline: list[Event], rule: Rule) -> str:
    events = "\n".join(f"{e.occurred_at:%Y-%m-%d} {e.type}" for e in timeline)
    return (
        f"Rule {rule.name} fired. Write a two-sentence action brief a founder can act on "
        f"in thirty seconds — who, what happened, what they said last, suggested move.\n"
        f"Facts: {hit.facts}\nTimeline:\n{events}"
    )


def compose_brief(hit: Hit, timeline: list[Event], rule: Rule, ai_client) -> str:
    if ai_client is None:
        return template_brief(hit, rule)
    try:
        text = ai_client.complete(_prompt(hit, timeline, rule))
    except Exception:
        return template_brief(hit, rule)
    return text if text and text.strip() else template_brief(hit, rule)
