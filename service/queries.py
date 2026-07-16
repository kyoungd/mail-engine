"""Query verbs — the recurring reads the UI panels are built on (service contract §2).

Reads go through the read-only role. Each verb is exactly one round trip: no N+1,
no per-row queries. Cross-cutting math (days quiet, stalled, cost-per-response) is
folded in Python from that single result set.
"""

from datetime import UTC, date, datetime
from uuid import UUID

from psycopg import sql

from db.readonly import readonly_connection
from derivation.rules import INBOUND_TYPES
from domain.enums import ContactStage
from domain.errors import ValidationError
from domain.types import (
    ActivationCard,
    ContactCard,
    ContactSummary,
    Event,
    Nudge,
    Variant,
    VariantStat,
    WaveDashboard,
    WaveDetail,
    WaveSummary,
)
from service.ingestion import EVENT_COLS, event_from_row

# Days without a first captured lead after signup before activation is "stalled".
# Mirrors the judgment job's STALL_DAYS default until Phase 4's config table owns it.
_STALL_DAYS = 14


def get_wave_dashboard(wave_id: UUID) -> WaveDashboard:
    """Pieces by status, response counts by variant, cost-per-response. One query
    returns a row per piece (with its variant and a responded flag); the rest is folded
    here."""
    with readonly_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select p.variant_id, v.name, p.status, coalesce(p.cost_cents, 0), "
                "exists (select 1 from events e where e.contact_id = p.contact_id "
                "and e.type = any(%s)) "
                "from pieces p join variants v on v.id = p.variant_id "
                "where p.wave_id = %s",
                (list(INBOUND_TYPES), wave_id),
            )
            rows = cur.fetchall()

    pieces_by_status: dict[str, int] = {}
    per_variant: dict[UUID, dict] = {}
    total_responses = 0
    total_cost = 0
    for variant_id, variant_name, status, cost_cents, responded in rows:
        pieces_by_status[status] = pieces_by_status.get(status, 0) + 1
        total_cost += cost_cents
        stat = per_variant.setdefault(
            variant_id,
            {"name": variant_name, "pieces": 0, "responses": 0, "cost": 0},
        )
        stat["pieces"] += 1
        stat["cost"] += cost_cents
        if responded:
            stat["responses"] += 1
            total_responses += 1

    by_variant = [
        VariantStat(
            variant_id=vid,
            variant_name=s["name"],
            pieces=s["pieces"],
            responses=s["responses"],
            cost_cents=s["cost"],
        )
        for vid, s in per_variant.items()
    ]
    cost_per_response = total_cost // total_responses if total_responses else None
    return WaveDashboard(
        wave_id=wave_id,
        pieces_by_status=pieces_by_status,
        by_variant=by_variant,
        responses=total_responses,
        cost_cents=total_cost,
        cost_per_response_cents=cost_per_response,
    )


def get_approval_queue() -> list[WaveSummary]:
    with readonly_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id, name, drop_number, status, scheduled_for from waves "
                "where status = 'draft' order by scheduled_for nulls last, created_at"
            )
            return [
                WaveSummary(
                    id=r[0],
                    name=r[1],
                    drop_number=r[2],
                    status=r[3],
                    scheduled_for=r[4],
                )
                for r in cur.fetchall()
            ]


def get_contact_timeline(contact_id: UUID) -> list[Event]:
    """The full story of one contact, chronological — the single most used view when
    a prospect calls back."""
    with readonly_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "select {cols} from events where contact_id = %s "
                    "order by occurred_at, id"
                ).format(cols=EVENT_COLS),
                (contact_id,),
            )
            return [event_from_row(r) for r in cur.fetchall()]


def get_pipeline() -> list[ContactCard]:
    """Contacts in responded/in_conversation, with last inbound, next action, days
    quiet. The 'CRM' in its entirety."""
    today = datetime.now(UTC).date()
    with readonly_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select c.id, c.business_name, c.segment, c.stage_snapshot, "
                "c.next_action_at, c.next_action_note, "
                "(select max(e.occurred_at) from events e where e.contact_id = c.id "
                "and e.type = any(%s)) "
                "from contacts c "
                "where c.stage_snapshot in ('responded', 'in_conversation') "
                "order by c.id",
                (list(INBOUND_TYPES),),
            )
            rows = cur.fetchall()

    cards = []
    for cid, name, segment, stage, next_at, note, last_inbound in rows:
        days_quiet = (today - last_inbound.date()).days if last_inbound else None
        cards.append(
            ContactCard(
                id=cid,
                business_name=name,
                segment=segment,
                stage_snapshot=ContactStage(stage),
                last_inbound_at=last_inbound,
                next_action_at=next_at,
                next_action_note=note,
                days_quiet=days_quiet,
            )
        )
    return cards


def get_activation_board() -> list[ActivationCard]:
    """Won customers with checklist status; stalled ones (no first lead past
    _STALL_DAYS) flagged."""
    today = datetime.now(UTC).date()
    with readonly_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select a.contact_id, c.business_name, a.signed_up_at, a.forwarding_at, "
                "a.calendar_at, a.first_lead_at "
                "from activation a join contacts c on c.id = a.contact_id "
                "order by a.signed_up_at"
            )
            rows = cur.fetchall()

    cards = []
    for cid, name, signed_up, forwarding, calendar, first_lead in rows:
        stalled = first_lead is None and (today - signed_up.date()).days > _STALL_DAYS
        cards.append(
            ActivationCard(
                contact_id=cid,
                business_name=name,
                signed_up_at=signed_up,
                forwarding_at=forwarding,
                calendar_at=calendar,
                first_lead_at=first_lead,
                stalled=stalled,
            )
        )
    return cards


def list_waves() -> list[WaveSummary]:
    """Every wave regardless of status, newest drop first — the wave index view."""
    with readonly_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id, name, drop_number, status, scheduled_for, executed_at "
                "from waves order by drop_number desc, created_at desc"
            )
            return [
                WaveSummary(
                    id=r[0],
                    name=r[1],
                    drop_number=r[2],
                    status=r[3],
                    scheduled_for=r[4],
                    executed_at=r[5],
                )
                for r in cur.fetchall()
            ]


def get_wave(wave_id: UUID) -> WaveDetail:
    """One wave as stored — the edit form renders exactly what draft_wave persisted."""
    with readonly_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id, name, drop_number, status, audience_rule, variant_split, "
                "scheduled_for from waves where id = %s",
                (wave_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValidationError("no_wave", f"no wave {wave_id}")
            return WaveDetail(
                id=row[0],
                name=row[1],
                drop_number=row[2],
                status=row[3],
                audience_rule=row[4],
                variant_split=row[5],
                scheduled_for=row[6],
            )


def get_variant(variant_id: UUID) -> Variant:
    """One variant with its creative — the preview page renders exactly what's stored."""
    with readonly_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id, name, hypothesis, creative, created_at "
                "from variants where id = %s",
                (variant_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValidationError("no_variant", f"no variant {variant_id}")
            return Variant(
                id=row[0], name=row[1], hypothesis=row[2], creative=row[3],
                created_at=row[4],
            )


def list_variants() -> list[Variant]:
    """Every creative variant with its hypothesis, newest first."""
    with readonly_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id, name, hypothesis, creative, created_at from variants "
                "order by created_at desc"
            )
            return [
                Variant(
                    id=r[0],
                    name=r[1],
                    hypothesis=r[2],
                    creative=r[3],
                    created_at=r[4],
                )
                for r in cur.fetchall()
            ]


def search_contacts(q: str, limit: int = 50) -> list[ContactSummary]:
    """Browse/search contacts by name, trade, phone, list key, segment, or source.
    An empty query browses (source is not null, so every contact matches '%%')."""
    pattern = f"%{q.strip()}%"
    with readonly_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id, business_name, contact_name, trade, segment, phone_e164, "
                "list_key, source, stage_snapshot, do_not_mail from contacts "
                "where business_name ilike %s or contact_name ilike %s or trade ilike %s "
                "or phone_e164 ilike %s or list_key ilike %s or segment ilike %s "
                "or source ilike %s "
                "order by business_name nulls last, id limit %s",
                (pattern, pattern, pattern, pattern, pattern, pattern, pattern, limit),
            )
            return [
                ContactSummary(
                    id=r[0],
                    business_name=r[1],
                    contact_name=r[2],
                    trade=r[3],
                    segment=r[4],
                    phone_e164=r[5],
                    list_key=r[6],
                    source=r[7],
                    stage_snapshot=ContactStage(r[8]),
                    do_not_mail=r[9],
                )
                for r in cur.fetchall()
            ]


def list_orphans() -> list[Event]:
    """Unattributed events, newest first — the orphan queue FR-6 surfaces instead of
    guessing at attribution."""
    with readonly_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "select {cols} from events where contact_id is null "
                    "order by occurred_at desc, id desc"
                ).format(cols=EVENT_COLS)
            )
            return [event_from_row(r) for r in cur.fetchall()]


def list_due_nudges(as_of: date | None = None) -> list[Nudge]:
    """What the push system would send: contacts whose next_action_at is due."""
    when = as_of if as_of is not None else datetime.now(UTC).date()
    with readonly_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id, next_action_at, next_action_note from contacts "
                "where next_action_at is not null and next_action_at <= %s "
                "order by next_action_at, id",
                (when,),
            )
            return [
                Nudge(contact_id=r[0], next_action_at=r[1], next_action_note=r[2])
                for r in cur.fetchall()
            ]
