"""What counts as activity on an assigned contact — read by the `partners status`
view (jobs/partners_cli). One definition, so every reader agrees."""

from derivation.rules import INBOUND_TYPES

ACTIVITY_TYPES = frozenset(INBOUND_TYPES) | {
    "signup.completed",
    "note.demo_call",
    "note.partner",
    "note.general",
}
