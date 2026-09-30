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
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from psycopg import sql
from psycopg.types.json import Json

from config.params import (
    ASK_AGAIN_AT,
    ASSIGNMENT_EXPIRY_DAYS,
    DNC_FRESHNESS_DAYS,
    HOUSE_PARTNER_ID,
    REGIONS,
    REP_BATCH_SIZE,
    derived_batch_size,
)
from db.session import transaction
from domain.errors import ValidationError
from service.custody import set_owner
from service.dnc import BLOCKED_SQL, LINK_FRESH_SQL

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


# Get more numbers' draw (part 4 §4.3); tests replace it with a seeded one.
_rng = random.Random()

# NMC's contacts: no primary intake row in intake_rep (part 1 answer 1).
_NMC_SQL = (
    "not exists (select 1 from intake_rep i where i.contact_id = c.id and i.is_primary)"
)


def _after_lock(cur) -> None:
    """Called once per `assign_batch`, after the partner read."""


def _request_hash(partner_id: UUID, audience_rule, count, contact_ids,
                  options: dict | None = None) -> str:
    request = {
        "partner_id": str(partner_id),
        "rule": audience_rule,
        "count": count,
        "contact_ids": [str(c) for c in contact_ids] if contact_ids else None,
    }
    if options:
        request["options"] = options
    canonical = json.dumps(request, sort_keys=True)
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
    "(c.dnc_checked_at is not null and c.dnc_checked_at >= now() - make_interval(days => %s) "
    "  and {link}) as dnc_fresh, "
    "(c.phone_e164 is not null and substring(c.phone_e164 from 3 for 3) in "
    "  (select area_code from dnc_subscriptions)) as area_subscribed, "
    "exists (select 1 from suppression_tombstones t "
    "  where t.phone_e164 = c.phone_e164 and t.channel = 'voice') as tombstoned, "
    "not {nmc} as rep_own, "
    "(select max(e.occurred_at) from events e where e.contact_id = c.id "
    "  and e.type = 'contact.assignment_expired' "
    "  and e.payload->>'previous_owner_id' = %s) as last_expired_from"
).format(link=LINK_FRESH_SQL, nmc=sql.SQL(_NMC_SQL))


def _gate(row, live_phones: frozenset[str], partner_id: UUID,
          returned_since: datetime | None) -> str | None:
    """First failing gate → shortfall cause; None → assignable. `live_phones` is the
    second read of blocked phones, taken after the row locks (part 2 §4.4). A rep's own
    goes to no partner but the house (part 4 §4.2); with `returned_since`, a contact
    the partner lost by expiry since then is refused (part 4 §4.5)."""
    (_id, phone, batch_ptr, owner_id, stage, do_not_call, dnc_registry, is_seed,
     _checked_at, dnc_fresh, area_subscribed, tombstoned, rep_own, last_expired) = row
    if is_seed:
        return "seed"
    if phone is None:
        return "no_phone"
    if batch_ptr is not None or owner_id != HOUSE_PARTNER_ID:
        return "already_assigned"
    if rep_own and partner_id != HOUSE_PARTNER_ID:
        return "rep_own"
    if returned_since is not None and last_expired is not None and last_expired >= returned_since:
        return "returned_recently"
    if stage == "won":
        return "won"
    if stage in ("responded", "in_conversation"):
        return "mid_funnel"
    if stage not in _ASSIGNABLE_STAGES:
        return "mid_funnel"
    if do_not_call or phone in live_phones:
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
    *,
    max_held: int | None = None,
    random_draw: bool = False,
    returned_since: datetime | None = None,
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

    options = {
        k: v for k, v in (("max_held", max_held), ("random_draw", random_draw or None))
        if v is not None
    }
    request_hash = _request_hash(partner_id, audience_rule, count, contact_ids, options)
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=ASSIGNMENT_EXPIRY_DAYS)

    with transaction() as conn:
        with conn.cursor() as cur:
            # Get more numbers locks the partner first, so two asks — or an ask and a
            # door B claim — for one rep run one after the other (part 4 §4.3).
            cur.execute(
                "select id, status, weekly_hours from partners where id = %s"
                + (" for no key update" if max_held is not None else ""),
                (partner_id,),
            )
            partner = cur.fetchone()
            _after_lock(cur)
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

            if max_held is not None:
                cur.execute(
                    f"select count(*) from contacts c where c.owner_id = %s and {_NMC_SQL}",  # noqa: S608
                    (partner_id,),
                )
                held = cur.fetchone()
                assert held is not None
                if held[0] > max_held:
                    raise ValidationError(
                        "not_yet", f"partner holds {held[0]} of NMC's contacts (> {max_held})"
                    )

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
                locked: list[UUID] = []
                if random_draw:
                    # Skip, never wait (part 4 §4.3): a contact another transaction
                    # holds is left out of this draw and reported as `locked`.
                    cur.execute(
                        sql.SQL("select c.id from contacts c where {where}").format(
                            where=where
                        ),
                        rule_params,
                    )
                    seen = [r[0] for r in cur.fetchall()]
                cur.execute(
                    sql.SQL(
                        "select {cols} from contacts c where {where} "
                        "order by c.id for update of c{skip}"
                    ).format(
                        cols=_CANDIDATE_COLS, where=where,
                        skip=sql.SQL(" skip locked" if random_draw else ""),
                    ),
                    [DNC_FRESHNESS_DAYS, DNC_FRESHNESS_DAYS, str(partner_id), *rule_params],
                )
            else:
                locked = []
                cur.execute(
                    sql.SQL(
                        "select {cols} from contacts c where c.id = any(%s) "
                        "order by c.id for update of c"
                    ).format(cols=_CANDIDATE_COLS),
                    [DNC_FRESHNESS_DAYS, DNC_FRESHNESS_DAYS, str(partner_id), [*contact_ids]],
                )

            rows = cur.fetchall()
            if random_draw and contact_ids is None:
                got = {r[0] for r in rows}
                locked = sorted((c for c in seen if c not in got), key=str)
            # A report locks the contact without updating it, so the locked re-read
            # above cannot see a block that landed while this waited: read again.
            cur.execute(
                "select phone_e164 from dnc_numbers where blocked and phone_e164 = any(%s)",
                ([r[1] for r in rows if r[1]],),
            )
            live_phones = frozenset(r[0] for r in cur.fetchall())

            passing: list[UUID] = []
            shortfall: dict[str, list[UUID]] = {}
            for row in rows:
                cause = _gate(row, live_phones, partner_id, returned_since)
                if cause is None:
                    passing.append(row[0])
                else:
                    shortfall.setdefault(cause, []).append(row[0])
            if locked:
                shortfall["locked"] = locked
            if random_draw:
                _rng.shuffle(passing)
            assigned = passing if count is None else passing[:count]

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
                        **({"options": options} if options else {}),
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
                sql.SQL(
                    "select c.id, c.business_name, c.contact_name, c.phone_e164, "
                    "c.addr_line1, c.addr_line2, c.addr_city, c.addr_state, c.addr_zip, "
                    "b.expires_at, "
                    "(c.dnc_checked_at is not null and c.dnc_checked_at >= now() - "
                    " make_interval(days => %s) and {link}) as dnc_fresh "
                    "from contacts c join assignment_batches b "
                    "  on b.id = c.assignment_batch_id "
                    "where c.owner_id = %s "
                    "and not {blocked} and c.dnc_registry = false "
                    "and substring(c.phone_e164 from 3 for 3) in "
                    "  (select area_code from dnc_subscriptions) "
                    "order by c.id"
                ).format(link=LINK_FRESH_SQL, blocked=BLOCKED_SQL),
                (DNC_FRESHNESS_DAYS, DNC_FRESHNESS_DAYS, partner_id),
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
         "city", "state", "zip", "expires_at", "generated_at"]
    )
    shortfall: dict[str, list[UUID]] = {}
    for (cid, business_name, contact_name, phone, line1, line2, city, state,
         zip_, expires_at, dnc_fresh) in rows:
        if not dnc_fresh:
            shortfall.setdefault("dnc_stale", []).append(cid)
            continue
        writer.writerow(
            [
                # the same fallback execute_wave uses for a null-name recipient
                business_name or contact_name or "Business Owner",
                contact_name or "",
                phone, line1 or "", line2 or "", city or "", state or "", zip_ or "",
                expires_at.isoformat() if expires_at else "",
                generated_at.isoformat(),
            ]
        )
    return ExportResult(csv=out.getvalue(), shortfall=shortfall)


def reclaim(partner_id: UUID, reason: str, actor: str) -> int:
    """S-5: return every holding of a partner to the house, one event each. Works
    on inactive partners (Step 12 removes access; reclaim retrieves the leads)."""
    if not reason.strip():
        raise ValidationError("bad_reason", "a reclaim carries its reason")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id from contacts where owner_id = %s "
                "order by id for update",
                (partner_id,),
            )
            holdings = [r[0] for r in cur.fetchall()]
            for cid in holdings:
                set_owner(
                    cur, cid, HOUSE_PARTNER_ID,
                    event_type="contact.reclaimed", reason=reason, actor=actor,
                )
    return len(holdings)


def get_more_numbers(
    rep: UUID, region: str, idempotency_key: str, at: datetime
) -> AssignmentReport:
    """Get more numbers (docs/contact-engine/04-assignment.md §4.3): a batch drawn at
    random from the region's area codes, through the same gate as every batch."""
    if region not in REGIONS:
        raise ValidationError("bad_region", f"unknown region {region!r}")
    if rep == HOUSE_PARTNER_ID:
        raise ValidationError("bad_rep", "the house is not a rep")
    if at.tzinfo is None:
        raise ValidationError("bad_time", "at must carry a time zone")
    return assign_batch(
        rep, idempotency_key, str(rep),
        audience_rule={"area_code": list(REGIONS[region])},
        count=REP_BATCH_SIZE,
        max_held=ASK_AGAIN_AT,
        random_draw=True,
        returned_since=at - timedelta(days=ASSIGNMENT_EXPIRY_DAYS),
    )


# Rule 2 of the expiry (part 4 §4.4): NMC's contact held without a batch, whose latest
# assignment is over the limit old. Written over the alias `c`.
_STALE_HOLDING_SQL = (
    "c.owner_id <> %(house)s and c.assignment_batch_id is null "
    "and c.stage_snapshot <> 'won' and " + _NMC_SQL + " "
    "and (select max(e.occurred_at) from events e where e.contact_id = c.id "
    "     and e.type = 'contact.assigned') < now() - make_interval(days => %(days)s)"
)

# Door B's three tests of sold, less the stage (part 1 `_judge`): a sale on the contact,
# or an unmatched sale carrying its phone.
_SOLD_SQL = (
    "exists (select 1 from events e where e.type = 'signup.completed' "
    "  and (e.contact_id = c.id or (e.contact_id is null "
    "       and (e.payload->>'phone_e164' = c.phone_e164 "
    "            or dnc_normalize(e.payload->>'phone') = c.phone_e164))))"
)


def run_expiry_step() -> int:
    """The nightly expiry (S-4): contacts whose batch is past `expires_at`, and NMC's
    contacts held without a batch whose latest assignment is over the limit old (part 4
    §4.4), return to the house with `contact.assignment_expired`. One lock pass in id
    order; the second read sees a claim or a sale that landed while it waited. Slotted
    after recompute_state and before digest.run in run_nightly — the ordering is
    load-bearing."""
    params = {"house": HOUSE_PARTNER_ID, "days": ASSIGNMENT_EXPIRY_DAYS}
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select c.id, b.expires_at < now() from contacts c "  # noqa: S608
                "left join assignment_batches b on b.id = c.assignment_batch_id "
                "where b.expires_at < now() or (" + _STALE_HOLDING_SQL + ") "
                "order by c.id for update of c",
                params,
            )
            rows = cur.fetchall()
            batch_due = [cid for cid, by_batch in rows if by_batch]
            held = [cid for cid, by_batch in rows if not by_batch]
            if held:
                cur.execute(
                    "select c.id from contacts c where c.id = any(%(ids)s) "  # noqa: S608
                    "and " + _STALE_HOLDING_SQL + " and not " + _SOLD_SQL,
                    {**params, "ids": held},
                )
                still = {r[0] for r in cur.fetchall()}
                held = [cid for cid in held if cid in still]
            due = sorted(batch_due + held, key=str)
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
            cur.execute(
                "select id from contacts where stage_snapshot = 'won' "
                "and assignment_batch_id is not null order by id for update",
            )
            due = [r[0] for r in cur.fetchall()]
            for cid in due:
                set_owner(
                    cur, cid, HOUSE_PARTNER_ID,
                    event_type="contact.reclaimed", reason="won", actor="system",
                )
    return len(due)
