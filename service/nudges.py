"""The judgment job's write path (service contract §5: nudges are events too).
record_nudge appends the nudge.sent fact and fills the contact's next_action slot;
expire_stale_actions clears the slot once a nudge has aged past expiry, so the morning
list stays current-state truth rather than a guilt-stack of stale reminders."""

from datetime import UTC, date, datetime
from uuid import UUID

from db.session import transaction
from service.ingestion import append_event


def record_nudge(
    contact_id: UUID | None,
    wave_id: UUID | None,
    rule_name: str,
    brief: str,
    as_of: date,
    recipient: str,
) -> int:
    """Emit the nudge.sent event (rule + facts in payload) and, for a contact-level
    nudge, write next_action_at/next_action_note — atomically."""
    payload = {"rule": rule_name, "brief": brief, "recipient": recipient}
    if wave_id is not None:
        payload["wave_id"] = str(wave_id)
    with transaction() as conn:
        with conn.cursor() as cur:
            event_id = append_event(
                cur, "system", "nudge.sent", datetime.now(UTC), payload,
                contact_id=contact_id,
            )
            if contact_id is not None:
                cur.execute(
                    "update contacts set next_action_at = %s, next_action_note = %s "
                    "where id = %s",
                    (as_of, brief, contact_id),
                )
    return event_id


def expire_stale_actions(as_of: date, expire_days: int) -> int:
    """Clear next_action slots that have aged past expiry (a human's future action,
    dated ahead, is untouched — only passed, stale slots clear)."""
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update contacts set next_action_at = null, next_action_note = null "
                "where next_action_at is not null "
                "and next_action_at < %s::date - make_interval(days => %s)",
                (as_of, expire_days),
            )
            return cur.rowcount
