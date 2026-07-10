"""Derivation — pure `events -> judgment`, no I/O. The single source of truth for
what contact state *means* (data document §3). `recompute_state` in the service
layer does the database work and calls these; keeping them pure is what makes
full-history recomputation trivial and the definitions unit-testable with fixtures.

RULESET_VERSION is stamped on snapshots so a recompute under a changed definition
is distinguishable from one under the old.
"""

from datetime import date, datetime

from domain.enums import ContactStage
from domain.types import ContactFlags, Event

RULESET_VERSION = "2"  # v2: contact.lost -> LOST stage (revivable)

# The caller-initiated signals that constitute a response (data document §3).
INBOUND_TYPES = frozenset({"page.visit", "call.inbound", "sms.inbound"})
# Our engagement back on a live thread — the difference between "responded" and
# "in conversation".
ENGAGE_TYPES = frozenset({"sms.outbound", "call.answered"})
# Returned pieces at or above this count auto-suppress the contact (data document §3).
RETURNED_SUPPRESSION_COUNT = 2


def _first_submitted_at(events: list[Event]) -> datetime | None:
    times = [e.occurred_at for e in events if e.type == "piece.submitted"]
    return min(times) if times else None


def _last_occurrence(events: list[Event], etype: str) -> datetime | None:
    times = [e.occurred_at for e in events if e.type == etype]
    return max(times) if times else None


def _first_response_at(events: list[Event]) -> datetime | None:
    """occurred_at of the earliest inbound that lands *after* the first piece —
    the moment the contact became a responder. None if never a responder."""
    submitted = _first_submitted_at(events)
    if submitted is None:
        return None
    responses = [
        e.occurred_at
        for e in events
        if e.type in INBOUND_TYPES and e.occurred_at > submitted
    ]
    return min(responses) if responses else None


def is_responded(events: list[Event]) -> bool:
    """Any inbound signal attributed to the contact after the first piece went out."""
    return _first_response_at(events) is not None


def quiet_days(events: list[Event], as_of: date) -> int | None:
    """Whole days since the last inbound signal; None if the contact never responded.
    Order-independent: keyed on occurred_at, not list position."""
    inbound = [e.occurred_at for e in events if e.type in INBOUND_TYPES]
    if not inbound:
        return None
    return (as_of - max(inbound).date()).days


def is_suppressed(events: list[Event], flags: ContactFlags) -> bool:
    """Suppression is an absorbing state: a do-not-mail request, an opt-out, or two
    returned pieces. All three are monotonic — once true, more events keep it true."""
    if flags.do_not_mail:
        return True
    if any(e.type == "contact.opt_out" for e in events):
        return True
    returned = sum(1 for e in events if e.type == "piece.returned")
    return returned >= RETURNED_SUPPRESSION_COUNT


def is_lost(events: list[Event]) -> bool:
    """A human `contact.lost` marks the conversation over — but it is revivable:
    an inbound landing after the latest `contact.lost` un-loses the contact. Unlike
    suppression, lost is not absorbing."""
    lost_at = _last_occurrence(events, "contact.lost")
    if lost_at is None:
        return False
    return not any(
        e.type in INBOUND_TYPES and e.occurred_at > lost_at for e in events
    )


def derive_stage(events: list[Event], flags: ContactFlags) -> ContactStage:
    """The contact's stage as of the full event set. Precedence, first match wins:
    suppressed (absorbing) > won > lost > in_conversation > responded > in_sequence >
    prospect. `lost` sits above the response stages so a marked-lost contact leaves the
    pipeline, but is revivable (see is_lost)."""
    if is_suppressed(events, flags):
        return ContactStage.SUPPRESSED
    if any(e.type == "signup.completed" for e in events):
        return ContactStage.WON
    if is_lost(events):
        return ContactStage.LOST
    first_response = _first_response_at(events)
    if first_response is not None:
        engaged = any(
            e.type in ENGAGE_TYPES and e.occurred_at > first_response for e in events
        )
        return ContactStage.IN_CONVERSATION if engaged else ContactStage.RESPONDED
    if any(e.type == "piece.submitted" for e in events):
        return ContactStage.IN_SEQUENCE
    return ContactStage.PROSPECT
