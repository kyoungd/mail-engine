"""Derived state — the I/O around the pure derivation layer (service contract §2).

`recompute_state` rehydrates events, runs the pure `derive_stage`, and refreshes the
`stage_snapshot` cache. It introduces no new fact, so — by design — it writes no
event: it is the reader-courtesy recomputation, not a state change with a fact behind
it. `do_not_mail` and human-set next_action are never touched, so they survive
recomputation. Two runs over unchanged events produce identical snapshots.
"""

from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from psycopg import sql

from db.session import transaction
from derivation.rules import derive_stage, is_address_undeliverable
from domain.types import ContactFlags, RecomputeReport
from service.ingestion import EVENT_COLS, event_from_row


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
            # contact.dnc_checked is compliance audit trail, not judgment signal —
            # ~300k events/year that would dwarf every other type in rehydration
            # (Phase 2; "were we compliant that day" queries hit the type directly).
            cur.execute(
                sql.SQL(
                    "select {cols} from events "
                    "where contact_id = any(%s) and type <> 'contact.dnc_checked' "
                    "order by contact_id, occurred_at"
                ).format(cols=EVENT_COLS),
                (ids,),
            )
            by_contact: dict[UUID, list] = defaultdict(list)
            for row in cur.fetchall():
                by_contact[row[1]].append(event_from_row(row))

            now = datetime.now(UTC)
            updates = []
            for cid, do_not_mail, do_not_text in contacts:
                events = by_contact.get(cid, [])
                stage = derive_stage(
                    events,
                    ContactFlags(do_not_mail=do_not_mail, do_not_text=do_not_text),
                )
                # address_undeliverable's named writer (Phase 2): derived from the
                # piece.returned events already in the stream. The human-authored
                # do_not_* columns stay untouched (FR-7).
                updates.append(
                    (stage.value, now, is_address_undeliverable(events), cid)
                )

            cur.executemany(
                "update contacts set stage_snapshot = %s, stage_computed_at = %s, "
                "address_undeliverable = %s where id = %s",
                updates,
            )

    return RecomputeReport(contacts_updated=len(updates))
