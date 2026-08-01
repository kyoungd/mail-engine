"""Custody writes (partner-lead-assignment.md §7, S-11, Phase 1).

`set_owner` is the SINGLE emitting writer for `contacts.owner_id` — six stories
change ownership and all of them route through here; nothing else may touch the
column. It composes on a caller-owned cursor (column + batch pointer + event in the
caller's one transaction), which is what lets Phase 2's rewritten `suppress()` fold
a custody removal into its own transaction and Phase 4's `assign_batch` move a
whole batch atomically. No public verb exists yet; the assignment verbs arrive in
Phase 4."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from derivation.custody import OWNERSHIP_EVENT_TYPES
from service.ingestion import append_event


def set_owner(
    cur,
    contact_id: UUID,
    new_owner_id: UUID,
    *,
    event_type: str,
    reason: str,
    actor: str,
    batch_id: UUID | None = None,
    expires_at: datetime | None = None,
) -> int:
    """Write the owner column, set/clear the batch pointer, append the ownership
    event — one caller-owned transaction. Returns the event id.

    The event-type mapping is the caller's contract (§7, pinned): assignment passes
    `contact.assigned` (with `batch_id` and the stamped `expires_at`); the nightly
    expiry step alone passes `contact.assignment_expired`; every other return to the
    house passes `contact.reclaimed` with the reason in the payload."""
    if event_type not in OWNERSHIP_EVENT_TYPES:
        raise ValueError(
            f"set_owner emits only {sorted(OWNERSHIP_EVENT_TYPES)}, got {event_type!r}"
        )

    cur.execute("select owner_id from contacts where id = %s", (contact_id,))
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"unknown contact {contact_id}")
    previous_owner_id = row[0]

    cur.execute(
        "update contacts set owner_id = %s, assignment_batch_id = %s where id = %s",
        (new_owner_id, batch_id, contact_id),
    )

    payload: dict[str, Any] = {
        "reason": reason,
        "actor": actor,
        "previous_owner_id": str(previous_owner_id),
        "new_owner_id": str(new_owner_id),
    }
    if batch_id is not None:
        payload["batch_id"] = str(batch_id)
    if expires_at is not None:
        payload["expires_at"] = expires_at.isoformat()

    return append_event(
        cur, "system", event_type, datetime.now(UTC), payload, contact_id=contact_id
    )
