"""The assignment verbs and steps (partner-lead-assignment.md §7 S-1/S-2/S-4/S-5,
Phase 4). Custody moves ONLY through `set_owner` (Phase 1's single-writer rule);
these verbs own selection, gating, idempotency, and the batch bookkeeping around it.

Locking (revision 7): `suppress()` and `assign_batch` touch the SAME row since the
grain merge, so both `select … for update` their candidate rows in id order before
evaluating gates — ordinary row locking serializes them, and READ COMMITTED's
re-check on the post-lock row version is what makes "a do_not_call landing between
gate-check and commit" a storage decision, not a race. A concurrent unique-index
collision aborts loudly and is retried with the same key — never caught-and-degraded
into partial assignment; per-cause shortfall describes sequential outcomes only."""

import csv
import hashlib
import io
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from psycopg import sql
from psycopg.types.json import Json

from config.params import (
    ASSIGNMENT_EXPIRY_DAYS,
    DNC_FRESHNESS_DAYS,
    PERSONAL_WINDOW_DAYS,
    HOUSE_PARTNER_ID,
    derived_batch_size,
)
from db.session import transaction
from domain.errors import ValidationError
from service.custody import set_owner

# The rule keys assignment accepts (S-1): the wave grammar's selection keys.
# NOT `stage` (the pool gates own stage), NOT `limit` (`count` owns it), NOT
# `not_responded_to_wave` (defer until a real need).
_ALLOWED_RULE_KEYS = frozenset(
    {"segment", "trade", "source", "city", "zip_prefix", "area_code"}
)
_INTAKE_TABLES = ("intake_cslb_ca", "intake_fbn_ca")

# Pool-gate evaluation order — the FIRST failing gate names the shortfall cause.
_ASSIGNABLE_STAGES = ("prospect", "in_sequence", "lost")


@dataclass(frozen=True)
class AssignmentReport:
    batch_id: UUID
    assigned: list[UUID]
    shortfall: dict[str, list[UUID]]
    retry: bool = False
    released: list[UUID] = field(default_factory=list)


@dataclass(frozen=True)
class ExportResult:
    csv: str
    shortfall: dict[str, list[UUID]]


def _request_hash(partner_id: UUID, audience_rule, count, contact_ids) -> str:
    canonical = json.dumps(
        {
            "partner_id": str(partner_id),
            "rule": audience_rule,
            "count": count,
            "contact_ids": [str(c) for c in contact_ids] if contact_ids else None,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _rule_clauses(rule: dict) -> tuple[list, list]:
    unknown = set(rule) - _ALLOWED_RULE_KEYS
    if unknown:
        raise ValidationError(
            "bad_rule_key",
            f"assignment rules accept {sorted(_ALLOWED_RULE_KEYS)}; got {sorted(unknown)}",
        )
    clauses: list = []
    params: list = []
    if "segment" in rule:
        clauses.append(sql.SQL("c.segment = any(%s)"))
        params.append(list(rule["segment"]))
    if "trade" in rule:
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
        clauses.append(sql.SQL("lower(c.addr_city) = any(%s)"))
        params.append([str(c).lower() for c in rule["city"]])
    if "zip_prefix" in rule:
        clauses.append(sql.SQL("c.addr_zip like any(%s)"))
        params.append([f"{str(z).strip()}%" for z in rule["zip_prefix"]])
    if "area_code" in rule:
        # The phone's area code — the unit of DNC-subscription legality, so this
        # is how a batch stays local when the org owns several codes (a phoneless
        # contact never matches, which is right for a dialing audience).
        clauses.append(sql.SQL("substring(c.phone_e164 from 3 for 3) = any(%s)"))
        params.append([str(a).strip() for a in rule["area_code"]])
    return clauses, params


# Candidate row: id + everything the gates read, computed in SQL so the post-lock
# re-check evaluates against the row's committed version.
_CANDIDATE_COLS = sql.SQL(
    "c.id, c.phone_e164, c.assignment_batch_id, c.owner_id, c.stage_snapshot::text, "
    "c.do_not_call, c.dnc_registry, c.is_seed, c.dnc_checked_at, "
    "(c.dnc_checked_at is not null and c.dnc_checked_at >= now() - make_interval(days => %s)) "
    "  as dnc_fresh, "
    "(c.phone_e164 is not null and substring(c.phone_e164 from 3 for 3) in "
    "  (select area_code from dnc_subscriptions)) as area_subscribed, "
    "exists (select 1 from suppression_tombstones t "
    "  where t.phone_e164 = c.phone_e164 and t.channel = 'voice') as tombstoned, "
    "c.sourced_by_partner_id"
)


def _gate(row, requesting_partner_id: UUID) -> str | None:
    """First failing gate → shortfall cause; None → assignable."""
    (_id, phone, batch_ptr, owner_id, stage, do_not_call, dnc_registry, is_seed,
     _checked_at, dnc_fresh, area_subscribed, tombstoned, sourced_by) = row
    if is_seed:
        return "seed"
    if phone is None:
        return "no_phone"
    if batch_ptr is not None or owner_id != HOUSE_PARTNER_ID:
        return "already_assigned"
    if sourced_by is not None and sourced_by != requesting_partner_id:
        # Another partner collected this number: it returns to them, never into
        # someone else's batch (partner-sourced-leads.md §4, requirement 2).
        return "sourced_elsewhere"
    if stage == "won":
        return "won"
    if stage in ("responded", "in_conversation"):
        return "mid_funnel"
    if stage not in _ASSIGNABLE_STAGES:
        return "mid_funnel"
    if do_not_call:
        return "voice_suppressed"
    if dnc_registry:
        return "dnc_registry"
    if tombstoned:
        return "tombstoned"
    if not area_subscribed:
        return "dnc_unsubscribed"
    if not dnc_fresh:
        return "dnc_stale"
    return None


def _retry_receipt(cur, batch_row) -> AssignmentReport:
    """A same-key retry returns the batch's ORIGINAL membership — the rows still
    pointing at it plus those since released (reported as such). A receipt for what
    was assigned, not a live view; reconstructed from the `contact.assigned` events
    carrying the batch id, so release paths clearing the pointer cannot erase it."""
    batch_id = batch_row[0]
    cur.execute(
        "select distinct contact_id from events where type = 'contact.assigned' "
        "and payload->>'batch_id' = %s",
        (str(batch_id),),
    )
    original = {r[0] for r in cur.fetchall()}
    cur.execute(
        "select id from contacts where assignment_batch_id = %s", (batch_id,)
    )
    holding = {r[0] for r in cur.fetchall()}
    return AssignmentReport(
        batch_id=batch_id,
        assigned=sorted(holding, key=str),
        shortfall={},
        retry=True,
        released=sorted(original - holding, key=str),
    )


def assign_batch(
    partner_id: UUID,
    idempotency_key: str,
    actor: str,
    audience_rule: dict | None = None,
    count: int | None = None,
    contact_ids: list[UUID] | None = None,
) -> AssignmentReport:
    """S-1: assign a batch to a partner. The audience rule is the selection; the
    gates are the floor. Selection is `order by id` after gates — never the
    cursor's whim. `count` defaults to the §5 derived batch; an explicit count is
    the founder override (bypasses floor AND cap); the id-list is the cutover form.
    Batch creation and contact moves are one transaction."""
    if audience_rule is not None and contact_ids is not None:
        raise ValidationError("bad_request", "pass a rule or an id-list, not both")
    if audience_rule is None and contact_ids is None and count is None:
        # a bare derived-count call still needs a selection to draw from
        audience_rule = {}

    request_hash = _request_hash(partner_id, audience_rule, count, contact_ids)
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=ASSIGNMENT_EXPIRY_DAYS)

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id, status, weekly_hours from partners where id = %s",
                (partner_id,),
            )
            partner = cur.fetchone()
            if partner is None:
                raise ValidationError("no_partner", f"no partner {partner_id}")
            if partner[1] != "active":
                # Step 12's "remove lead access": inactive is rejected loudly;
                # reclaim and expiry still operate on inactive partners' holdings.
                raise ValidationError(
                    "inactive_partner", f"partner {partner_id} is not active"
                )

            cur.execute(
                "select id, request_hash from assignment_batches "
                "where idempotency_key = %s",
                (idempotency_key,),
            )
            existing = cur.fetchone()
            if existing is not None:
                if existing[1] != request_hash:
                    raise ValidationError(
                        "key_mismatch",
                        "idempotency key reused with different parameters — "
                        "it is a retry contract, not a lookup API",
                    )
                return _retry_receipt(cur, existing)

            if contact_ids is None:
                if count is None:
                    if partner[2] is None:
                        raise ValidationError(
                            "no_count",
                            "partner has no weekly_hours and no explicit count given",
                        )
                    count = derived_batch_size(partner[2])
                rule_clauses, rule_params = _rule_clauses(audience_rule or {})
                where = sql.SQL(" and ").join(
                    [sql.SQL("c.is_seed = false"), *rule_clauses]
                )
                cur.execute(
                    sql.SQL(
                        "select {cols} from contacts c where {where} "
                        "order by c.id for update of c"
                    ).format(cols=_CANDIDATE_COLS, where=where),
                    [DNC_FRESHNESS_DAYS, *rule_params],
                )
            else:
                cur.execute(
                    sql.SQL(
                        "select {cols} from contacts c where c.id = any(%s) "
                        "order by c.id for update of c"
                    ).format(cols=_CANDIDATE_COLS),
                    [DNC_FRESHNESS_DAYS, [*contact_ids]],
                )

            assigned: list[UUID] = []
            shortfall: dict[str, list[UUID]] = {}
            for row in cur.fetchall():
                cause = _gate(row, partner_id)
                if cause is None and (count is None or len(assigned) < count):
                    assigned.append(row[0])
                elif cause is not None:
                    shortfall.setdefault(cause, []).append(row[0])

            # batch row written BEFORE contacts move (S-1)
            cur.execute(
                "insert into assignment_batches "
                "(partner_id, idempotency_key, requested_count, delivered_count, "
                "expires_at, actor, request, request_hash) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s) returning id",
                (
                    partner_id, idempotency_key, count, len(assigned), expires_at,
                    actor,
                    Json({
                        "rule": audience_rule,
                        "count": count,
                        "contact_ids": [str(c) for c in contact_ids]
                        if contact_ids else None,
                    }),
                    request_hash,
                ),
            )
            row = cur.fetchone()
            assert row is not None
            batch_id = row[0]

            for cid in assigned:
                set_owner(
                    cur, cid, partner_id,
                    event_type="contact.assigned", reason="assigned", actor=actor,
                    batch_id=batch_id, expires_at=expires_at,
                )

    return AssignmentReport(batch_id=batch_id, assigned=assigned, shortfall=shortfall)


def export_batch(partner_id: UUID) -> ExportResult:
    """S-2: the partner-facing export — fresh on every pull, expiry + generation
    timestamp columns in the file (the stale-sheet mitigation is the partner
    re-pulling before each session). Voice-suppressed contacts are excluded on
    every regeneration; stale-DNC rows fall out as reported shortfall rather than
    silently shipping an uncallable row. Stamps `partners.last_export_at` (R1 —
    the report's 'your last export' line has no other source)."""
    generated_at = datetime.now(UTC)
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("select id from partners where id = %s", (partner_id,))
            if cur.fetchone() is None:
                raise ValidationError("no_partner", f"no partner {partner_id}")
            cur.execute(
                "select c.id, c.business_name, c.contact_name, c.phone_e164, "
                "c.addr_line1, c.addr_line2, c.addr_city, c.addr_state, c.addr_zip, "
                "b.expires_at, "
                "(c.dnc_checked_at is not null and c.dnc_checked_at >= now() - "
                " make_interval(days => %s)) as dnc_fresh, "
                # The personal-list window: attributed to THIS partner and inside
                # PERSONAL_WINDOW_DAYS of the recorded permission date.
                "(c.sourced_by_partner_id = c.owner_id and c.permission_at is not null "
                " and c.permission_at >= current_date - make_interval(days => %s)) "
                "  as personal, "
                "c.dnc_registry, "
                "exists (select 1 from suppression_tombstones t "
                "  where t.phone_e164 = c.phone_e164 and t.channel = 'voice') "
                "  as tombstoned "
                # LEFT: a sourced holding carries no batch pointer and would
                # otherwise vanish from the partner's own sheet.
                "from contacts c left join assignment_batches b "
                "  on b.id = c.assignment_batch_id "
                "where c.owner_id = %s "
                # Our own list is never waived — not by permission, not by anything.
                "and c.do_not_call = false "
                "order by c.id",
                (DNC_FRESHNESS_DAYS, PERSONAL_WINDOW_DAYS, partner_id),
            )
            rows = cur.fetchall()
            cur.execute(
                "update partners set last_export_at = %s where id = %s",
                (generated_at, partner_id),
            )

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        ["business_name", "contact_name", "phone", "addr_line1", "addr_line2",
         "city", "state", "zip", "origin", "expires_at", "generated_at"]
    )
    shortfall: dict[str, list[UUID]] = {}
    for (cid, business_name, contact_name, phone, line1, line2, city, state,
         zip_, expires_at, dnc_fresh, personal, dnc_registry, tombstoned) in rows:
        # The rule (partner-sourced-leads.md §4): on the sheet if it is in their
        # personal list, or if it came off the main list and clears DNC. The
        # personal window waives the FTC-REGISTRY checks only — a tombstone is
        # our own list and is never waived.
        if tombstoned:
            shortfall.setdefault("tombstoned", []).append(cid)
            continue
        if not personal:
            if dnc_registry:
                shortfall.setdefault("dnc_registry", []).append(cid)
                continue
            if not dnc_fresh:
                shortfall.setdefault("dnc_stale", []).append(cid)
                continue
        writer.writerow(
            [
                # the same fallback execute_wave uses for a null-name recipient
                business_name or contact_name or "Business Owner",
                contact_name or "",
                phone, line1 or "", line2 or "", city or "", state or "", zip_ or "",
                "sourced" if personal else "issued",
                expires_at.isoformat() if expires_at else "",
                generated_at.isoformat(),
            ]
        )
    return ExportResult(csv=out.getvalue(), shortfall=shortfall)


def reclaim(
    partner_id: UUID, reason: str, actor: str, *, include_sourced: bool = False
) -> int:
    """S-5: return every holding of a partner to the house, one event each. Works
    on inactive partners (Step 12 removes access; reclaim retrieves the leads).

    Their own collected numbers are NOT ours to take, so a plain reclaim leaves
    them (partner-sourced-leads.md §4). `include_sourced` is the explicit
    operator act for the partnership-ends case."""
    if not reason.strip():
        raise ValidationError("bad_reason", "a reclaim carries its reason")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id from contacts where owner_id = %s "
                + ("" if include_sourced else
                   "and (sourced_by_partner_id is null "
                   "     or sourced_by_partner_id <> owner_id) ")
                + "order by id for update",
                (partner_id,),
            )
            holdings = [r[0] for r in cur.fetchall()]
            for cid in holdings:
                set_owner(
                    cur, cid, HOUSE_PARTNER_ID,
                    event_type="contact.reclaimed", reason=reason, actor=actor,
                )
    return len(holdings)


def move_contact(contact_id: UUID, to_partner_id: UUID, reason: str, actor: str) -> None:
    """Move ONE contact's custody between partners — the conflict-resolution verb
    (partner-sourced-leads.md §6). `reclaim` is all-or-nothing and too blunt when
    two partners both claim one number; the operator adjudicates on evidence and
    this records the outcome as an ordinary custody event with its reason."""
    if not reason.strip():
        raise ValidationError("bad_reason", "a custody move carries its reason")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("select id from partners where id = %s", (to_partner_id,))
            if cur.fetchone() is None:
                raise ValidationError("no_partner", f"no partner {to_partner_id}")
            cur.execute(
                "select owner_id from contacts where id = %s for update", (contact_id,)
            )
            row = cur.fetchone()
            if row is None:
                raise ValidationError("no_contact", f"no contact {contact_id}")
            if row[0] == to_partner_id:
                return
            set_owner(
                cur, contact_id, to_partner_id,
                event_type="contact.assigned", reason=reason, actor=actor,
            )


def run_expiry_step() -> int:
    """The nightly expiry (S-4): contacts whose batch is past `expires_at` return
    to the house with `contact.assignment_expired`. Slotted after recompute_state
    and before digest.run in run_nightly — the ordering is load-bearing."""
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select c.id from contacts c "
                "join assignment_batches b on b.id = c.assignment_batch_id "
                "where b.expires_at < now() order by c.id for update of c",
            )
            due = [r[0] for r in cur.fetchall()]
            for cid in due:
                set_owner(
                    cur, cid, HOUSE_PARTNER_ID,
                    event_type="contact.assignment_expired", reason="expired",
                    actor="system",
                )
    return len(due)


def run_won_termination_step() -> int:
    """The nightly won-termination (S-1's permanent exclusion): a WON contact still
    holding a batch pointer returns to the house immediately — a partner must never
    be dialing a paying customer, and expiry is months too slow for that."""
    with transaction() as conn:
        with conn.cursor() as cur:
            # owner <> house, NOT "has a batch pointer": a SOURCED holding carries
            # no batch, and a won sourced contact staying on a partner's sheet is
            # S-10's worst case. Keying on the owner also stops the step
            # re-selecting won contacts already in the pool every night forever.
            cur.execute(
                "select id from contacts where stage_snapshot = 'won' "
                "and owner_id <> %s order by id for update",
                (HOUSE_PARTNER_ID,),
            )
            due = [r[0] for r in cur.fetchall()]
            for cid in due:
                set_owner(
                    cur, cid, HOUSE_PARTNER_ID,
                    event_type="contact.reclaimed", reason="won", actor="system",
                )
    return len(due)
