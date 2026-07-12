"""Execution verbs — the I/O around the pure derivation layer (service contract §2).

`recompute_state` rehydrates events, runs the pure `derive_stage`, and refreshes the
`stage_snapshot` cache. It introduces no new fact, so — by design — it writes no
event: it is the reader-courtesy recomputation, not a state change with a fact behind
it. `do_not_mail` and human-set next_action are never touched, so they survive
recomputation. Two runs over unchanged events produce identical snapshots.

`execute_wave` (the drop verb) arrives in Phase 3 with the seams; only recompute lives
here for now.
"""

import base64
import hashlib
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg import sql

from db.session import transaction
from derivation.rules import derive_stage
from domain.errors import ValidationError
from domain.types import ContactFlags, ExecutionReport, RecomputeReport
from seams.print_api import PrintApi, Recipient
from service.ingestion import EVENT_COLS, append_event, event_from_row
from service.waves import resolve_audience

# Fraction the drop-time audience may differ from the approved size before
# execute_wave halts for re-review (Phase 3 decision: 10%).
DRIFT_TOLERANCE = 0.10


def recompute_state(contact_id: UUID | None = None) -> RecomputeReport:
    """Rerun derivations from the event stream. Called nightly for incremental
    updates; callable over all history after a definition change. One contact when
    `contact_id` is given, otherwise every contact."""
    with transaction() as conn:
        with conn.cursor() as cur:
            if contact_id is not None:
                cur.execute(
                    "select id, do_not_mail, do_not_text from contacts where id = %s",
                    (contact_id,),
                )
            else:
                cur.execute("select id, do_not_mail, do_not_text from contacts")
            contacts = cur.fetchall()
            if not contacts:
                return RecomputeReport(contacts_updated=0)

            ids = [c[0] for c in contacts]
            cur.execute(
                sql.SQL(
                    "select {cols} from events "
                    "where contact_id = any(%s) order by contact_id, occurred_at"
                ).format(cols=EVENT_COLS),
                (ids,),
            )
            by_contact: dict[UUID, list] = defaultdict(list)
            for row in cur.fetchall():
                by_contact[row[1]].append(event_from_row(row))

            now = datetime.now(UTC)
            updates = []
            for cid, do_not_mail, do_not_text in contacts:
                stage = derive_stage(
                    by_contact.get(cid, []),
                    ContactFlags(do_not_mail=do_not_mail, do_not_text=do_not_text),
                )
                updates.append((stage.value, now, cid))

            cur.executemany(
                "update contacts set stage_snapshot = %s, stage_computed_at = %s "
                "where id = %s",
                updates,
            )

    return RecomputeReport(contacts_updated=len(updates))


def _mailer_code(wave_id: UUID, contact_id: UUID) -> str:
    """Deterministic per (wave, contact) so a resumed drop regenerates the same code —
    no orphaned codes. base32, lowercased, unpadded."""
    digest = hashlib.sha256(f"{wave_id}:{contact_id}".encode()).digest()
    return base64.b32encode(digest).decode().lower().rstrip("=")[:10]


def _assign_variant(contact_id: UUID, variant_split: dict[str, Any]) -> str:
    """Deterministic weighted assignment: the same contact always lands on the same
    variant, so re-running a drop never reshuffles who saw what."""
    items = sorted(variant_split.items())
    total = sum(float(w) for _, w in items)
    if total <= 0:
        return items[0][0]
    bucket = int(hashlib.sha256(str(contact_id).encode()).hexdigest(), 16) % 10_000
    point = bucket / 10_000 * total
    cumulative = 0.0
    for variant_id, weight in items:
        cumulative += float(weight)
        if point < cumulative:
            return variant_id
    return items[-1][0]


def execute_wave(wave_id: UUID, print_api: PrintApi) -> ExecutionReport:
    """The drop verb (jobs-only). Re-resolves the audience, halts on drift beyond
    tolerance vs. the approved size, then creates one piece per contact and submits it.
    Resumable and idempotent: the unique (contact_id, wave_id) constraint plus the
    vendor's mailer-code idempotency prevent duplicates, so a killed drop is re-run
    until clean. Each piece's row and its piece.submitted event are written atomically."""
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select status, audience_rule, variant_split, approved_audience_count "
                "from waves where id = %s",
                (wave_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValidationError("no_wave", f"no wave {wave_id}")
            status, audience_rule, variant_split, approved_count = row
            if status not in ("approved", "executing"):
                raise ValidationError("not_executable", f"wave is {status}, not approved")

            audience = resolve_audience(cur, audience_rule)

            if approved_count:
                drift = abs(len(audience) - approved_count) / approved_count
                if drift > DRIFT_TOLERANCE:
                    return ExecutionReport(
                        wave_id=wave_id,
                        halted=True,
                        reason=(
                            f"audience drift {drift:.0%} exceeds {DRIFT_TOLERANCE:.0%} "
                            f"tolerance ({approved_count} approved, {len(audience)} now)"
                        ),
                        pieces_created=0,
                        pieces_submitted=0,
                        approved_count=approved_count,
                        resolved_count=len(audience),
                    )

            cur.execute(
                "select id::text, creative from variants where id::text = any(%s)",
                (list(variant_split.keys()),),
            )
            creatives = {vid: creative for vid, creative in cur.fetchall()}

            if status != "executing":
                cur.execute(
                    "update waves set status = 'executing' where id = %s", (wave_id,)
                )

    created = submitted = 0
    for contact_id in audience:
        mailer_code = _mailer_code(wave_id, contact_id)
        variant_id = _assign_variant(contact_id, variant_split)
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "insert into pieces (contact_id, wave_id, variant_id, mailer_code) "
                    "values (%s, %s, %s, %s) on conflict (contact_id, wave_id) do nothing",
                    (contact_id, wave_id, variant_id, mailer_code),
                )
                if cur.rowcount == 1:
                    created += 1
                cur.execute(
                    "select id, status from pieces where contact_id = %s and wave_id = %s",
                    (contact_id, wave_id),
                )
                piece_row = cur.fetchone()
                assert piece_row is not None
                piece_id, piece_status = piece_row
                if piece_status == "created":
                    cur.execute(
                        "select business_name, contact_name, addr_line1, addr_line2, "
                        "addr_city, addr_state, addr_zip from contacts where id = %s",
                        (contact_id,),
                    )
                    c = cur.fetchone()
                    assert c is not None
                    recipient = Recipient(
                        name=c[0] or c[1] or "Business Owner",
                        address_line1=c[2] or "",
                        address_line2=c[3],
                        city=c[4] or "",
                        state=c[5] or "",
                        zip_code=c[6] or "",
                    )
                    result = print_api.submit_piece(
                        mailer_code, creatives.get(variant_id, {}), recipient
                    )
                    cur.execute(
                        "update pieces set lob_id = %s, cost_cents = %s, "
                        "status = 'submitted', submitted_at = now() where id = %s",
                        (result.external_id, result.cost_cents, piece_id),
                    )
                    submitted += 1
                append_event(
                    cur,
                    "system",
                    "piece.submitted",
                    datetime.now(UTC),
                    {},
                    external_id=f"submitted:{piece_id}",
                    contact_id=contact_id,
                    piece_id=piece_id,
                )

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update waves set status = 'sent', executed_at = now() where id = %s",
                (wave_id,),
            )

    return ExecutionReport(
        wave_id=wave_id,
        halted=False,
        reason=None,
        pieces_created=created,
        pieces_submitted=submitted,
        approved_count=approved_count,
        resolved_count=len(audience),
    )
