"""The nightly judgment run: evaluate every rule, apply discipline (human-action
respect, cooldown, budget), compose briefs, record nudges. Silence is a valid output —
a zero-hit night records and returns nothing. Actual delivery (one morning digest per
founder via NMC's sending path) wires in at Phase 5; here we assemble it and log the
nudge.sent facts.
"""

from collections import defaultdict
from datetime import date, timedelta

from config.params import DEFAULT_PARAMS, Params
from db.readonly import readonly_connection
from derivation.rules import INBOUND_TYPES
from judgment.composer import compose_brief, template_brief
from judgment.protocol import ComposedNudge, Hit, JudgmentResult, Recipient, Rule
from judgment.rules import all_rules
from service.nudges import expire_stale_actions, record_nudge
from service.queries import get_contact_timeline


def _scalar(cur):
    row = cur.fetchone()
    assert row is not None
    return row[0]


def _has_future_action(cur, contact_id, as_of: date) -> bool:
    cur.execute("select next_action_at from contacts where id = %s", (contact_id,))
    value = _scalar(cur)
    return value is not None and value > as_of


def _in_cooldown(cur, rule: Rule, hit: Hit, params: Params, as_of: date) -> bool:
    cutoff = as_of - timedelta(days=params.cooldown_days)
    if hit.contact_id is not None:
        cur.execute(
            "select max(occurred_at) from events "
            "where contact_id = %s and type = 'nudge.sent'",
            (hit.contact_id,),
        )
        last = _scalar(cur)
        if last is None or last.date() <= cutoff:
            return False
        cur.execute(
            "select exists(select 1 from events where contact_id = %s "
            "and type = any(%s) and occurred_at > %s)",
            (hit.contact_id, list(INBOUND_TYPES), last),
        )
        return not _scalar(cur)  # quiet through cooldown unless a new inbound arrived
    if hit.wave_id is not None:
        cur.execute(
            "select max(occurred_at) from events where type = 'nudge.sent' "
            "and payload->>'rule' = %s and payload->>'wave_id' = %s",
            (rule.name, str(hit.wave_id)),
        )
    else:
        cur.execute(
            "select max(occurred_at) from events where type = 'nudge.sent' "
            "and payload->>'rule' = %s and payload->>'wave_id' is null",
            (rule.name,),
        )
    last = _scalar(cur)
    return last is not None and last.date() > cutoff


def _resolve_recipient(cur, rule: Rule, hit: Hit) -> str:
    if rule.recipient == Recipient.YOUNG or hit.contact_id is None:
        return "young"
    cur.execute("select owner from contacts where id = %s", (hit.contact_id,))
    owner = _scalar(cur)
    return owner or "young"


def _format_digest(nudges: list[ComposedNudge]) -> str:
    lines = "\n".join(f"{i}. {n.brief}" for i, n in enumerate(nudges, start=1))
    return f"Today's nudges ({len(nudges)}):\n{lines}"


def run(as_of: date, params: Params = DEFAULT_PARAMS, ai_client=None, sender=None) -> JudgmentResult:
    expire_stale_actions(as_of, params.expire_days)

    prepared: list[tuple[Rule, Hit, str, list]] = []
    with readonly_connection() as conn:
        with conn.cursor() as cur:
            for rule in all_rules():
                for hit in rule.evaluate(cur, params, as_of):
                    if hit.contact_id is not None and _has_future_action(cur, hit.contact_id, as_of):
                        continue  # respect a human-set, unexpired next_action
                    if _in_cooldown(cur, rule, hit, params, as_of):
                        continue
                    founder = _resolve_recipient(cur, rule, hit)
                    timeline = get_contact_timeline(hit.contact_id) if hit.contact_id else []
                    prepared.append((rule, hit, founder, timeline))

    prepared.sort(key=lambda item: item[0].priority)
    sent: dict[str, list[ComposedNudge]] = defaultdict(list)
    deferred: list[ComposedNudge] = []
    counts: dict[str, int] = defaultdict(int)

    for rule, hit, founder, timeline in prepared:
        if counts[founder] < params.nudge_budget:
            brief = compose_brief(hit, timeline, rule, ai_client)
            record_nudge(hit.contact_id, hit.wave_id, rule.name, brief, as_of, founder)
            sent[founder].append(
                ComposedNudge(rule=rule.name, recipient=founder, contact_id=hit.contact_id,
                              wave_id=hit.wave_id, brief=brief, priority=rule.priority)
            )
            counts[founder] += 1
        else:
            deferred.append(
                ComposedNudge(rule=rule.name, recipient=founder, contact_id=hit.contact_id,
                              wave_id=hit.wave_id, brief=template_brief(hit, rule),
                              priority=rule.priority)
            )

    result = JudgmentResult(sent=dict(sent), deferred=deferred)
    if sender is not None:
        for founder, nudges in result.sent.items():
            sender.send(founder, _format_digest(nudges))
    return result
