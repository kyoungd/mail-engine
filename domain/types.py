"""Domain value types — one frozen dataclass per table, mirroring the DDL rows.
Report/preview DTOs (AudiencePreview, IntakeReport, ...) are defined by the
phases whose verbs return them, not here."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID

from domain.enums import ContactStage, EventSource, PieceStatus, WaveStatus


@dataclass(frozen=True, kw_only=True)
class Contact:
    id: UUID
    cslb_license: str | None = None
    business_name: str | None = None
    contact_name: str | None = None
    trade: str
    license_class: str | None = None
    phone_e164: str | None = None
    email: str | None = None
    addr_line1: str | None = None
    addr_line2: str | None = None
    addr_city: str | None = None
    addr_state: str | None = None
    addr_zip: str | None = None
    addr_validated_at: datetime | None = None
    segment: str | None = None
    source: str = "cslb"
    stage_snapshot: ContactStage = ContactStage.PROSPECT
    stage_computed_at: datetime | None = None
    next_action_at: date | None = None
    next_action_note: str | None = None
    do_not_mail: bool = False
    do_not_text: bool = False
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, kw_only=True)
class Variant:
    id: UUID
    name: str
    hypothesis: str
    creative: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, kw_only=True)
class Wave:
    id: UUID
    name: str
    drop_number: int
    audience_rule: dict[str, Any]
    variant_split: dict[str, Any]
    status: WaveStatus = WaveStatus.DRAFT
    scheduled_for: date | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    executed_at: datetime | None = None
    created_at: datetime


@dataclass(frozen=True, kw_only=True)
class Piece:
    id: UUID
    contact_id: UUID
    wave_id: UUID
    variant_id: UUID
    mailer_code: str
    lob_id: str | None = None
    status: PieceStatus = PieceStatus.CREATED
    cost_cents: int | None = None
    submitted_at: datetime | None = None
    delivered_at: datetime | None = None
    created_at: datetime


@dataclass(frozen=True, kw_only=True)
class Event:
    id: int
    contact_id: UUID | None = None
    piece_id: UUID | None = None
    source: EventSource
    type: str
    occurred_at: datetime
    ingested_at: datetime
    external_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class Activation:
    contact_id: UUID
    signed_up_at: datetime
    forwarding_at: datetime | None = None
    calendar_at: datetime | None = None
    first_lead_at: datetime | None = None
    notes: str | None = None


@dataclass(frozen=True, kw_only=True)
class ContactFlags:
    """Human-authored suppression flags a contact carries into derivation.
    Columns already on `contacts`; this is the value the pure rules receive."""

    do_not_mail: bool = False
    do_not_text: bool = False


@dataclass(frozen=True)
class ResolutionReport:
    """resolve_orphans output: what the precedence chain matched, what remains."""

    matched: list[tuple[int, UUID]]
    orphaned: list[int]


@dataclass(frozen=True)
class RecomputeReport:
    contacts_updated: int
