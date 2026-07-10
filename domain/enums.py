"""Enums mirroring the DDL's `create type ... as enum` definitions exactly.
The values are the SQL labels verbatim; tests/acceptance/test_enum_ddl_parity.py
asserts they cannot drift from migration 0001."""

from enum import StrEnum


class ContactStage(StrEnum):
    PROSPECT = "prospect"
    IN_SEQUENCE = "in_sequence"
    RESPONDED = "responded"
    IN_CONVERSATION = "in_conversation"
    WON = "won"
    LOST = "lost"
    SUPPRESSED = "suppressed"


class WaveStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    EXECUTING = "executing"
    SENT = "sent"
    CANCELLED = "cancelled"


class PieceStatus(StrEnum):
    CREATED = "created"
    SUBMITTED = "submitted"
    PRINTED = "printed"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    RETURNED = "returned"
    FAILED = "failed"


class EventSource(StrEnum):
    LOB = "lob"
    POSTHOG = "posthog"
    NMC = "nmc"
    HUMAN = "human"
    SYSTEM = "system"


# Maps each SQL enum type name to its Python enum, for the parity test.
DDL_ENUM_TYPES: dict[str, type[StrEnum]] = {
    "contact_stage": ContactStage,
    "wave_status": WaveStatus,
    "piece_status": PieceStatus,
    "event_source": EventSource,
}
