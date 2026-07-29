"""Creative and wave-lifecycle verbs (service contract §2).

The audience rule is data: a small JSON filter (segment, trade, source, stage,
city, zip_prefix, not_responded_to_wave, limit) resolved against current state. `_audience_where` is the single
source of that interpretation — `preview_audience` and (Phase 3) `execute_wave` both
resolve through it, so what is approved is exactly what fires. do_not_mail and
suppressed contacts are always excluded, unconditionally.
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg import errors as pg_errors
from psycopg import sql
from psycopg.types.json import Json

from db.readonly import readonly_connection
from db.session import transaction
from domain.enums import ContactStage
from domain.errors import ValidationError
from domain.types import AudiencePreview, ResolvedAudience, SampleContact, VariantProof
from seams.print_api import PrintApi

# Grammar of the audience rule. Unknown keys are rejected, not ignored.
_AUDIENCE_KEYS = {
    "segment",
    "trade",
    "source",
    "stage",
    "city",
    "zip_prefix",
    "not_responded_to_wave",
    "limit",
}
# A contact who received a piece but has not responded sits in one of these stages.
_NON_RESPONSE_STAGES = ["prospect", "in_sequence"]
# One table per adapter (FR-1). Readers union over them; identity is per-source.
_INTAKE_TABLES = ("intake_cslb_ca", "intake_fbn_ca")
# The one verdict that excludes (§5's verified vendor facts): the deliverable_*_unit
# variants are deliverable-family and stay mailable.
_UNDELIVERABLE = "undeliverable"
# Placeholder per-piece cost until the print seam supplies a real estimate (Phase 3).
_ESTIMATED_PIECE_COST_CENTS = 73


def validate_audience_rule(rule: dict[str, Any]) -> None:
    unknown = set(rule) - _AUDIENCE_KEYS
    if unknown:
        raise ValidationError("unknown_audience_key", f"unknown audience keys: {sorted(unknown)}")
    if "limit" in rule:
        limit = rule["limit"]
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValidationError("bad_limit", f"limit must be a positive integer, got {limit!r}")


def _audience_where(rule: dict[str, Any]) -> tuple[sql.Composed, list[Any]]:
    """Build the WHERE that selects the audience. The always-on clauses enforce the
    do_not_mail / suppressed exclusion; the rest are opt-in filters."""
    validate_audience_rule(rule)
    clauses: list[sql.Composable] = [
        sql.SQL("c.do_not_mail = false"),
        sql.SQL("c.stage_snapshot <> 'suppressed'"),
        # Seeds never come through the rule — resolve_audience appends them to every
        # wave separately, so excluding them here prevents a rule-less wave from
        # counting a seed twice (FR-4).
        sql.SQL("c.is_seed = false"),
    ]
    params: list[Any] = []
    if "segment" in rule:
        clauses.append(sql.SQL("c.segment = any(%s)"))
        params.append(list(rule["segment"]))
    if "trade" in rule:
        # Trade lives on the intake rows now, as an ARRAY: a C20|C36 licence is both an
        # hvac and a plumber business, so it must match either audience — which a
        # single-valued contacts.trade could not express. Unioned per intake table
        # because identity is per-source and a contact may have rows in more than one.
        clauses.append(
            sql.SQL("({})").format(
                sql.SQL(" or ").join(
                    sql.SQL(
                        "exists (select 1 from {t} i "
                        "where i.contact_id = c.id and i.trades && %s)"
                    ).format(t=sql.Identifier(table))
                    for table in _INTAKE_TABLES
                )
            )
        )
        for _ in _INTAKE_TABLES:
            params.append(list(rule["trade"]))
    if "source" in rule:
        clauses.append(sql.SQL("c.source = any(%s)"))
        params.append(list(rule["source"]))
    if "city" in rule:
        # Case-insensitive: CSLB city casing is as-filed ("VAN NUYS" / "Van Nuys").
        clauses.append(sql.SQL("lower(c.addr_city) = any(%s)"))
        params.append([str(c).lower() for c in rule["city"]])
    if "zip_prefix" in rule:
        # A ZIP band is the reliable region definition (e.g. SFV = 913/914/916).
        clauses.append(sql.SQL("c.addr_zip like any(%s)"))
        params.append([f"{str(z).strip()}%" for z in rule["zip_prefix"]])
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


def _state_hash(
    contact_ids: list[str],
    variant_split: dict[str, Any],
    creative_checksums: dict[str, str],
) -> str:
    """Fingerprint of exactly what a preview showed — the resolved audience, the variant
    split, AND each variant's creative. approve_wave carries it back so a wave whose
    audience OR creative drifted since preview cannot be approved stale: you approve the
    exact creative you proofed, not merely the same variant id."""
    canonical = json.dumps(
        {
            "audience": sorted(contact_ids),
            "variants": variant_split,
            "creatives": creative_checksums,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _creative_checksums(cur, variant_split: dict[str, Any]) -> dict[str, str]:
    """Checksum each variant's current creative, keyed by variant id. Folded into the
    state hash so editing a creative after preview invalidates the approval."""
    ids = list(variant_split.keys())
    if not ids:
        return {}
    cur.execute("select id::text, creative from variants where id::text = any(%s)", (ids,))
    return {
        vid: hashlib.sha256(json.dumps(creative, sort_keys=True).encode()).hexdigest()[:16]
        for vid, creative in cur.fetchall()
    }


def _primary_rows(cur, ids: list[UUID]) -> dict[UUID, tuple[str | None, str | None]]:
    """Each contact's PRIMARY intake row's (deliverability, delivery_point) — the address
    actually mailed. Non-primary rows never exclude and never dedupe anything: they are
    other licence records for the same business, not other mailings."""
    if not ids:
        return {}
    query = sql.SQL(" union all ").join(
        sql.SQL(
            "select contact_id, deliverability, delivery_point from {t} "
            "where is_primary and contact_id = any(%s)"
        ).format(t=sql.Identifier(table))
        for table in _INTAKE_TABLES
    )
    cur.execute(query, [ids for _ in _INTAKE_TABLES])
    return {cid: (verdict, dp) for cid, verdict, dp in cur.fetchall()}


def resolve_audience(cur, rule: dict[str, Any]) -> ResolvedAudience:
    """Resolve the rule to a deterministic, ordered list of contact ids, then apply the
    two address trims. Shared by preview, approval and execution so the three can never
    diverge over unchanged state. A `limit` takes a deterministic pseudo-random sample
    (hash order, not insertion order), so a capped wave is an unbiased slice AND stable
    between preview and drop.

    **Exclusion runs BEFORE dedupe, and the order is load-bearing** (§6): snapshot
    semantics let two primary rows verified at different times share a delivery point
    with different verdicts, so excluding first is what stops an undeliverable contact
    from winning the keeper pick and silently taking a deliverable duplicate down with
    it. Deliverable mail is never lost to an undeliverable twin.

    Both trims are counted and returned, never silently applied."""
    where, params = _audience_where(rule)
    if "limit" in rule:
        cur.execute(
            sql.SQL(
                "select c.id from contacts c where {where} order by md5(c.id::text), c.id limit %s"
            ).format(where=where),
            [*params, rule["limit"]],
        )
    else:
        cur.execute(
            sql.SQL("select c.id from contacts c where {where} order by c.id").format(where=where),
            params,
        )
    candidates = [r[0] for r in cur.fetchall()]
    primary = _primary_rows(cur, candidates)

    # 1. Undeliverable exclusion. An unverified row has no verdict yet, which is not the
    #    same fact as "undeliverable" — it is not excluded. Neither is a no-delivery-point
    #    verdict: that contact stays mailable at its raw picked address.
    kept = [cid for cid in candidates if (primary.get(cid, (None, None))[0]) != _UNDELIVERABLE]
    excluded_undeliverable = len(candidates) - len(kept)

    # 2. Delivery-point dedupe over what survived. A contact whose primary row is
    #    unverified or carries no delivery point does not dedupe — there is no homegrown
    #    normalization fallback, because a wrong merge here silently drops real mail.
    cur.execute(
        "select id from contacts where id = any(%s) and phone_e164 is not null", (kept,)
    )
    has_phone = {r[0] for r in cur.fetchall()} if kept else set()
    by_point: dict[str, list[UUID]] = {}
    for cid in kept:
        point = primary.get(cid, (None, None))[1]
        if point:
            by_point.setdefault(point, []).append(cid)
    dropped: set[UUID] = set()
    for sharing in by_point.values():
        if len(sharing) < 2:
            continue
        # Keeper, deterministic: a phone-bearing contact first, then the lowest id.
        keeper = min(sharing, key=lambda cid: (cid not in has_phone, str(cid)))
        dropped.update(cid for cid in sharing if cid != keeper)
    audience = [cid for cid in kept if cid not in dropped]

    # Seeds ride every wave (FR-4), independent of the rule and of any `limit`: the
    # limit caps the purchased list, not the founder's own sample pieces. They are exempt
    # from both trims too — they carry no intake rows, and a founder sample is not
    # competing for a mailbox with the list.
    cur.execute("select id from contacts where is_seed order by id")
    audience.extend(r[0] for r in cur.fetchall())
    return ResolvedAudience(
        ids=audience,
        excluded_undeliverable=excluded_undeliverable,
        deduped_delivery_point=len(dropped),
    )


def create_variant(name: str, hypothesis: str, creative: dict[str, Any]) -> UUID:
    """Hypothesis is required and non-empty — the schema enforcing the
    information-buying posture. There is no exceptions parameter."""
    if not hypothesis or not hypothesis.strip():
        raise ValidationError("empty_hypothesis", "a variant requires a non-empty hypothesis")
    with transaction() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "insert into variants (name, hypothesis, creative) "
                    "values (%s, %s, %s) returning id",
                    (name, hypothesis, Json(creative)),
                )
            except pg_errors.UniqueViolation:
                raise ValidationError(
                    "duplicate_name", f"a variant named {name!r} already exists"
                ) from None
            row = cur.fetchone()
            assert row is not None
            return row[0]


def _is_frozen(cur, variant_id: UUID) -> bool:
    """A variant is frozen once any wave that carries it has been approved. Keys on
    approved_at, which never clears — not on status, which walks approved -> executing
    -> sent and would thaw the variant the moment it mailed. Cancelling an approved
    wave does not thaw it either: the approval happened."""
    cur.execute(
        "select exists (select 1 from waves where approved_at is not null "
        "and jsonb_exists(variant_split, %s))",
        (str(variant_id),),
    )
    row = cur.fetchone()
    return bool(row and row[0])


def update_variant(variant_id: UUID, name: str, hypothesis: str, creative: dict[str, Any]) -> None:
    """Full replace, mirroring create_variant. Editable only until approved: approval
    is the promise that this exact card is what fires, so from that moment the row is
    the record of what was approved and revision means minting a new variant."""
    if not hypothesis or not hypothesis.strip():
        raise ValidationError("empty_hypothesis", "a variant requires a non-empty hypothesis")
    with transaction() as conn:
        with conn.cursor() as cur:
            if _is_frozen(cur, variant_id):
                raise ValidationError(
                    "frozen",
                    f"variant {variant_id} is in an approved wave and cannot be edited",
                )
            cur.execute(
                "update variants set name = %s, hypothesis = %s, creative = %s where id = %s",
                (name, hypothesis, Json(creative), variant_id),
            )
            if cur.rowcount == 0:
                raise ValidationError("no_variant", f"no variant {variant_id}")


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
            try:
                cur.execute(
                    "insert into waves "
                    "(name, drop_number, audience_rule, variant_split, scheduled_for) "
                    "values (%s, %s, %s, %s, %s) returning id",
                    (name, drop_number, Json(audience_rule), Json(variant_split), scheduled_for),
                )
            except pg_errors.UniqueViolation:
                raise ValidationError(
                    "duplicate_name",
                    f"an active wave named {name!r} already exists — "
                    f"cancel it or pick another name",
                ) from None
            row = cur.fetchone()
            assert row is not None
            return row[0]


def update_wave(
    wave_id: UUID,
    name: str,
    drop_number: int,
    audience_rule: dict[str, Any],
    variant_split: dict[str, Any],
    scheduled_for,
) -> None:
    """Edit a wave while it is still a worksheet. Draft-only: approval records who/when
    against a rendered preview, so anything past draft is immutable — cancel and redraft
    instead. Drift safety needs nothing here: an edit changes the preview's state_hash,
    so approving with a pre-edit hash fails stale_preview until re-previewed."""
    validate_audience_rule(audience_rule)
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("select status from waves where id = %s", (wave_id,))
            row = cur.fetchone()
            if row is None:
                raise ValidationError("no_wave", f"no wave {wave_id}")
            if row[0] != "draft":
                raise ValidationError("not_draft", f"wave is {row[0]}, not draft")
            try:
                cur.execute(
                    "update waves set name = %s, drop_number = %s, audience_rule = %s, "
                    "variant_split = %s, scheduled_for = %s where id = %s",
                    (
                        name,
                        drop_number,
                        Json(audience_rule),
                        Json(variant_split),
                        scheduled_for,
                        wave_id,
                    ),
                )
            except pg_errors.UniqueViolation:
                raise ValidationError(
                    "duplicate_name",
                    f"an active wave named {name!r} already exists — "
                    f"cancel it or pick another name",
                ) from None


def preview_audience(wave_id: UUID) -> AudiencePreview:
    """Resolve audience_rule NOW: count, breakdown by segment/stage, estimated cost,
    and a sample of 10. This is what the approval screen renders."""
    with readonly_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select audience_rule, variant_split from waves where id = %s", (wave_id,))
            row = cur.fetchone()
            if row is None:
                raise ValidationError("no_wave", f"no wave {wave_id}")
            audience_rule, variant_split = row
            # Resolve through the SAME path approval and execution use — never a
            # parallel query, or preview could diverge from what fires (e.g. `limit`).
            resolved = resolve_audience(cur, audience_rule)
            audience = resolved.ids
            checksums = _creative_checksums(cur, variant_split)
            rows = []
            if audience:
                cur.execute(
                    "select id, business_name, segment, stage_snapshot, is_seed "
                    "from contacts where id = any(%s) order by id",
                    (audience,),
                )
                rows = cur.fetchall()

    by_segment: dict[str, int] = {}
    by_stage: dict[str, int] = {}
    sample: list[SampleContact] = []
    seed_count = 0
    for cid, business_name, segment, stage, is_seed in rows:
        # Seeds count toward the total that fires (below) but are held out of the
        # segment/stage breakdown and sample — they are the founder's own pieces, not
        # part of the audience under review.
        if is_seed:
            seed_count += 1
            continue
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
        count=len(rows),  # total pieces that fire, seeds included
        seed_count=seed_count,
        by_segment=by_segment,
        by_stage=by_stage,
        estimated_cost_cents=len(rows) * _ESTIMATED_PIECE_COST_CENTS,
        sample=sample,
        state_hash=_state_hash([str(r[0]) for r in rows], variant_split, checksums),
        excluded_undeliverable=resolved.excluded_undeliverable,
        deduped_delivery_point=resolved.deduped_delivery_point,
    )


def approve_wave(wave_id: UUID, approved_by: str, state_hash: str | None = None) -> None:
    """Validate all preconditions and record who/when. Does NOT execute. When a
    `state_hash` is supplied (the UI carries the preview's), approval is rejected if the
    audience has drifted since — you approve exactly what you saw."""
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
            cur.execute("select count(*) from variants where id::text = any(%s)", (variant_ids,))
            found = cur.fetchone()
            assert found is not None
            if found[0] != len(variant_ids):
                raise ValidationError(
                    "unknown_variant",
                    "variant_split references a variant that does not exist",
                )

            if scheduled_for is None or scheduled_for <= datetime.now(UTC).date():
                raise ValidationError("not_future", "scheduled_for must be a future date")

            audience = resolve_audience(cur, audience_rule).ids
            if not audience:
                raise ValidationError("empty_audience", "audience resolves to zero contacts")

            if state_hash is not None:
                checksums = _creative_checksums(cur, variant_split)
                current = _state_hash([str(x) for x in audience], variant_split, checksums)
                if current != state_hash:
                    raise ValidationError(
                        "stale_preview",
                        "the audience has drifted since preview; re-preview before approving",
                    )

            cur.execute(
                "update waves set status = 'approved', approved_by = %s, "
                "approved_at = now(), approved_audience_count = %s where id = %s",
                (approved_by, len(audience), wave_id),
            )


def wave_proofs(wave_id: UUID, print_api: PrintApi) -> list[VariantProof]:
    """Render one Lob test-mode proof per variant in the wave — the print truth shown on
    the approval screen (FR-3). Read-only against our DB; the render itself is a
    test-environment vendor call (no piece prints, no money moves). Fail-loud: if the
    vendor can't render, this raises and the approval screen has nothing to show —
    "no proof, nothing to approve"."""
    with readonly_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("select variant_split from waves where id = %s", (wave_id,))
            row = cur.fetchone()
            if row is None:
                raise ValidationError("no_wave", f"no wave {wave_id}")
            (variant_split,) = row
            ids = list(variant_split.keys())
            if not ids:
                raise ValidationError("no_variants", "variant_split is empty")
            cur.execute(
                "select id, name, creative from variants where id::text = any(%s) order by name",
                (ids,),
            )
            variants = cur.fetchall()

    return [
        VariantProof(
            variant_id=vid,
            variant_name=name,
            pdf_url=print_api.render_proof(creative).pdf_url,
        )
        for vid, name, creative in variants
    ]


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
            cur.execute("update waves set status = 'cancelled' where id = %s", (wave_id,))
