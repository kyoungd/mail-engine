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
    list_key: str | None = None
    business_name: str | None = None
    contact_name: str | None = None
    trade: str | None = None
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


# --- Phase 2: report and view DTOs (returned by the contract verbs) ---


@dataclass(frozen=True)
class IntakeReport:
    loaded: int
    deduped: int
    invalid: int
    suppressed: int


@dataclass(frozen=True, kw_only=True)
class SampleContact:
    id: UUID
    business_name: str | None
    segment: str | None
    stage_snapshot: ContactStage


@dataclass(frozen=True, kw_only=True)
class AudiencePreview:
    count: int
    by_segment: dict[str, int]
    by_stage: dict[str, int]
    estimated_cost_cents: int
    sample: list[SampleContact]
    state_hash: str  # fingerprint of the resolved audience + variant split (approve carries it back)


@dataclass(frozen=True, kw_only=True)
class WaveSummary:
    id: UUID
    name: str
    drop_number: int
    status: WaveStatus
    scheduled_for: date | None


@dataclass(frozen=True, kw_only=True)
class VariantStat:
    variant_id: UUID
    variant_name: str
    pieces: int
    responses: int
    cost_cents: int


@dataclass(frozen=True, kw_only=True)
class WaveDashboard:
    wave_id: UUID
    pieces_by_status: dict[str, int]
    by_variant: list[VariantStat]
    responses: int
    cost_cents: int
    cost_per_response_cents: int | None


@dataclass(frozen=True, kw_only=True)
class ContactSummary:
    """search_contacts row — the browse/search view, distinct from the pipeline's
    ContactCard (which carries response-state math this view doesn't need)."""

    id: UUID
    business_name: str | None
    contact_name: str | None
    trade: str | None
    segment: str | None
    phone_e164: str | None
    list_key: str | None
    source: str
    stage_snapshot: ContactStage
    do_not_mail: bool


@dataclass(frozen=True, kw_only=True)
class ContactCard:
    id: UUID
    business_name: str | None
    segment: str | None
    stage_snapshot: ContactStage
    last_inbound_at: datetime | None
    next_action_at: date | None
    next_action_note: str | None
    days_quiet: int | None


@dataclass(frozen=True, kw_only=True)
class ActivationCard:
    contact_id: UUID
    business_name: str | None
    signed_up_at: datetime
    forwarding_at: datetime | None
    calendar_at: datetime | None
    first_lead_at: datetime | None
    stalled: bool


@dataclass(frozen=True, kw_only=True)
class Nudge:
    contact_id: UUID
    next_action_at: date
    next_action_note: str | None


@dataclass(frozen=True, kw_only=True)
class ExecutionReport:
    wave_id: UUID
    halted: bool
    reason: str | None
    pieces_created: int
    pieces_submitted: int
    approved_count: int | None
    resolved_count: int
