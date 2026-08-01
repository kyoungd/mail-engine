"""Custody derivation (partner-lead-assignment.md S-8, Phase 1's half).

`current_owner` is the event-confirmed derivation: it follows the last ownership
event's `new_owner_id` and closes custody only on end events — it is what the
`contacts.owner_id` column must always equal (the single-writer invariant). The
stamped-expiry-bounded `owner_at` is Phase 5's function and deliberately disagrees
with the column in the late-expiry window; do not fold the two together (S-8's
two-derivations rule)."""

from collections.abc import Iterable
from uuid import UUID

from domain.types import Event

# Pinned event-type mapping (§7): contact.assigned opens a custody interval;
# contact.assignment_expired (the nightly expiry step, alone) and contact.reclaimed
# (every other return to the house, reason in the payload) close one.
OWNERSHIP_EVENT_TYPES: frozenset[str] = frozenset(
    {"contact.assigned", "contact.assignment_expired", "contact.reclaimed"}
)


def current_owner(events: Iterable[Event], house_id: UUID) -> UUID:
    """The contact's owner per the event stream, in the caller's (occurred_at, id)
    order. Genesis rule: no ownership event => the house account — this clause is
    what makes the derivation total over 100,444 event-less contacts."""
    owner = house_id
    for event in events:
        if event.type in OWNERSHIP_EVENT_TYPES:
            owner = UUID(event.payload["new_owner_id"])
    return owner
