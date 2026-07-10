"""The closed event-type vocabulary (data document §3). Sync jobs and the
judgment job must agree on these names; unknown types are rejected, not invented.
Additions are deliberate: extend this set only when the taxonomy is extended."""

EVENT_TYPES: frozenset[str] = frozenset(
    {
        "piece.submitted",
        "piece.delivered",
        "piece.returned",
        "page.visit",
        "page.cta_click",
        "call.inbound",
        "call.missed",
        "call.answered",
        "sms.inbound",
        "sms.outbound",
        "demo.booked",
        "demo.held",
        "demo.no_show",
        "signup.completed",
        "note.demo_call",
        "note.partner",
        "note.general",
        "contact.opt_out",
        "contact.lost",
        "nudge.sent",
    }
)


def is_valid_type(event_type: str) -> bool:
    return event_type in EVENT_TYPES


class UnknownEventType(ValueError):
    """Raised when a write attempts an event type outside the closed taxonomy.
    The taxonomy is extended by editing EVENT_TYPES, never by ingesting past this."""

    def __init__(self, event_type: str) -> None:
        super().__init__(f"unknown event type: {event_type!r}")
        self.event_type = event_type
