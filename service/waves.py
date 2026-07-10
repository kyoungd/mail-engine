"""Creative and wave-lifecycle verbs (service contract §2).

The audience rule is data: a small JSON filter (segment, trade, stage,
not_responded_to_wave) resolved against current state. `_audience_where` is the single
source of that interpretation — `preview_audience` and (Phase 3) `execute_wave` both
resolve through it, so what is approved is exactly what fires. do_not_mail and
suppressed contacts are always excluded, unconditionally.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg import sql
from psycopg.types.json import Json

from db.readonly import readonly_connection
from db.session import transaction
from domain.enums import ContactStage
from domain.errors import ValidationError
from domain.types import AudiencePreview, SampleContact

# Grammar of the audience rule. Unknown keys are rejected, not ignored.
_AUDIENCE_KEYS = {"segment", "trade", "stage", "not_responded_to_wave"}
# A contact who received a piece but has not responded sits in one of these stages.
_NON_RESPONSE_STAGES = ["prospect", "in_sequence"]
# Placeholder per-piece cost until the print seam supplies a real estimate (Phase 3).
_ESTIMATED_PIECE_COST_CENTS = 73


def validate_audience_rule(rule: dict[str, Any]) -> None:
    unknown = set(rule) - _AUDIENCE_KEYS
    if unknown:
        raise ValidationError(
            "unknown_audience_key", f"unknown audience keys: {sorted(unknown)}"
        )


def _audience_where(rule: dict[str, Any]) -> tuple[sql.Composed, list[Any]]:
    """Build the WHERE that selects the audience. The always-on clauses enforce the
    do_not_mail / suppressed exclusion; the rest are opt-in filters."""
    validate_audience_rule(rule)
    clauses: list[sql.Composable] = [
        sql.SQL("c.do_not_mail = false"),
        sql.SQL("c.stage_snapshot <> 'suppressed'"),
    ]
    params: list[Any] = []
    if "segment" in rule:
        clauses.append(sql.SQL("c.segment = any(%s)"))
        params.append(list(rule["segment"]))
    if "trade" in rule:
        clauses.append(sql.SQL("c.trade = any(%s)"))
        params.append(list(rule["trade"]))
    if "stage" in rule:
        clauses.append(sql.SQL("c.stage_snapshot::text = any(%s)"))
        params.append(list(rule["stage"]))
    if "not_responded_to_wave" in rule:
        clauses.append(
            sql.SQL(
                "c.stage_snapshot::text = any(%s) and exists "
                "(select 1 from pieces p where p.contact_id = c.id and p.wave_id = %s)"
            )
        )
        params.append(list(_NON_RESPONSE_STAGES))
        params.append(rule["not_responded_to_wave"])
    return sql.SQL(" and ").join(clauses), params


def resolve_audience(cur, rule: dict[str, Any]) -> list[UUID]:
    """Resolve the rule to a deterministic, ordered list of contact ids. Shared by
    preview and execution so the two can never diverge over unchanged state."""
    where, params = _audience_where(rule)
    cur.execute(
        sql.SQL("select c.id from contacts c where {where} order by c.id").format(
            where=where
        ),
        params,
    )
    return [r[0] for r in cur.fetchall()]


def create_variant(name: str, hypothesis: str, creative: dict[str, Any]) -> UUID:
    """Hypothesis is required and non-empty — the schema enforcing the
    information-buying posture. There is no exceptions parameter."""
    if not hypothesis or not hypothesis.strip():
        raise ValidationError(
            "empty_hypothesis", "a variant requires a non-empty hypothesis"
        )
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into variants (name, hypothesis, creative) "
                "values (%s, %s, %s) returning id",
                (name, hypothesis, Json(creative)),
            )
            row = cur.fetchone()
            assert row is not None
            return row[0]


def draft_wave(
    name: str,
    drop_number: int,
    audience_rule: dict[str, Any],
    variant_split: dict[str, Any],
    scheduled_for,
) -> UUID:
    """Persist the rule as data. Validates the grammar but does NOT resolve the
    audience — resolution happens at preview and execution time."""
    validate_audience_rule(audience_rule)
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into waves "
                "(name, drop_number, audience_rule, variant_split, scheduled_for) "
                "values (%s, %s, %s, %s, %s) returning id",
                (name, drop_number, Json(audience_rule), Json(variant_split), scheduled_for),
            )
            row = cur.fetchone()
            assert row is not None
            return row[0]


def preview_audience(wave_id: UUID) -> AudiencePreview:
    """Resolve audience_rule NOW: count, breakdown by segment/stage, estimated cost,
    and a sample of 10. This is what the approval screen renders."""
    with readonly_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select audience_rule from waves where id = %s", (wave_id,))
            row = cur.fetchone()
            if row is None:
                raise ValidationError("no_wave", f"no wave {wave_id}")
            where, params = _audience_where(row[0])
            cur.execute(
                sql.SQL(
                    "select c.id, c.business_name, c.segment, c.stage_snapshot "
                    "from contacts c where {where} order by c.id"
                ).format(where=where),
                params,
            )
            rows = cur.fetchall()

    by_segment: dict[str, int] = {}
    by_stage: dict[str, int] = {}
    sample: list[SampleContact] = []
    for cid, business_name, segment, stage in rows:
        key = segment if segment is not None else "(none)"
        by_segment[key] = by_segment.get(key, 0) + 1
        by_stage[stage] = by_stage.get(stage, 0) + 1
        if len(sample) < 10:
            sample.append(
                SampleContact(
                    id=cid,
                    business_name=business_name,
                    segment=segment,
                    stage_snapshot=ContactStage(stage),
                )
            )
    return AudiencePreview(
        count=len(rows),
        by_segment=by_segment,
        by_stage=by_stage,
        estimated_cost_cents=len(rows) * _ESTIMATED_PIECE_COST_CENTS,
        sample=sample,
    )


def approve_wave(wave_id: UUID, approved_by: str) -> None:
    """Validate all preconditions and record who/when. Does NOT execute."""
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status, variant_split, scheduled_for, audience_rule "
                "from waves where id = %s",
                (wave_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValidationError("no_wave", f"no wave {wave_id}")
            status, variant_split, scheduled_for, audience_rule = row

            if status != "draft":
                raise ValidationError("not_draft", f"wave is {status}, not draft")

            variant_ids = list(variant_split.keys())
            if not variant_ids:
                raise ValidationError("no_variants", "variant_split is empty")
            cur.execute(
                "select count(*) from variants where id::text = any(%s)", (variant_ids,)
            )
            found = cur.fetchone()
            assert found is not None
            if found[0] != len(variant_ids):
                raise ValidationError(
                    "unknown_variant",
                    "variant_split references a variant that does not exist",
                )

            if scheduled_for is None or scheduled_for <= datetime.now(UTC).date():
                raise ValidationError(
                    "not_future", "scheduled_for must be a future date"
                )

            audience = resolve_audience(cur, audience_rule)
            if not audience:
                raise ValidationError(
                    "empty_audience", "audience resolves to zero contacts"
                )

            cur.execute(
                "update waves set status = 'approved', approved_by = %s, "
                "approved_at = now(), approved_audience_count = %s where id = %s",
                (approved_by, len(audience), wave_id),
            )


def cancel_wave(wave_id: UUID) -> None:
    """Valid until status='executing'. After that, mail is physical."""
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("select status from waves where id = %s", (wave_id,))
            row = cur.fetchone()
            if row is None:
                raise ValidationError("no_wave", f"no wave {wave_id}")
            if row[0] in ("executing", "sent"):
                raise ValidationError("too_late", f"cannot cancel a {row[0]} wave")
            if row[0] == "cancelled":
                return
            cur.execute(
                "update waves set status = 'cancelled' where id = %s", (wave_id,)
            )
