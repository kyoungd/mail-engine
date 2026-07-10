"""Ingestion verbs — the write path for facts (service contract §2).

Every write is an event first: these verbs append to `events` and nothing else.
`ingest_event` is idempotent on (source, external_id); `resolve_orphans` runs the
precedence chain over unattributed events; `record_note` is human residue capture.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg import sql
from psycopg.types.json import Json

from db.session import transaction
from domain.enums import EventSource
from domain.taxonomy import UnknownEventType, is_valid_type
from domain.types import Event, ResolutionReport
from resolution.matcher import THREAD_KEY, Lookups, resolve

# Column order shared by every events SELECT that rehydrates a domain Event.
# Shared across the service layer (execution.recompute_state consumes it), so not
# module-private despite living here.
EVENT_COLS = sql.SQL(
    "id, contact_id, piece_id, source, type, occurred_at, ingested_at, external_id, payload"
)


def event_from_row(row: tuple) -> Event:
    return Event(
        id=row[0],
        contact_id=row[1],
        piece_id=row[2],
        source=EventSource(row[3]),
        type=row[4],
        occurred_at=row[5],
        ingested_at=row[6],
        external_id=row[7],
        payload=row[8] or {},
    )


def append_event(
    cur,
    source: str,
    type: str,
    occurred_at: datetime,
    payload: dict[str, Any],
    external_id: str | None = None,
    contact_id: UUID | None = None,
    piece_id: UUID | None = None,
) -> int:
    """Idempotent event insert on a caller-owned cursor. Returns the event id (the
    existing one on an (source, external_id) conflict). The caller owns the transaction
    and is responsible for `type` validity — this is the shared low-level append used by
    ingest_event and by execute_wave (which emits piece.submitted inside its own
    per-piece transaction)."""
    if external_id is not None:
        cur.execute(
            "insert into events "
            "(contact_id, piece_id, source, type, occurred_at, external_id, payload) "
            "values (%s, %s, %s, %s, %s, %s, %s) "
            "on conflict (source, external_id) do nothing returning id",
            (contact_id, piece_id, source, type, occurred_at, external_id, Json(payload)),
        )
        row = cur.fetchone()
        if row is not None:
            return row[0]
        cur.execute(
            "select id from events where source = %s and external_id = %s",
            (source, external_id),
        )
        existing = cur.fetchone()
        assert existing is not None  # conflict fired, so the row exists
        return existing[0]

    cur.execute(
        "insert into events "
        "(contact_id, piece_id, source, type, occurred_at, payload) "
        "values (%s, %s, %s, %s, %s, %s) returning id",
        (contact_id, piece_id, source, type, occurred_at, Json(payload)),
    )
    row = cur.fetchone()
    assert row is not None
    return row[0]


def ingest_event(
    source: str,
    type: str,
    occurred_at: datetime,
    payload: dict[str, Any],
    external_id: str | None = None,
    contact_id: UUID | None = None,
    piece_id: UUID | None = None,
) -> int:
    """Append a fact. Rejects unknown `type` loudly (taxonomy is closed) and an
    unknown `source`. Idempotent on (source, external_id): the same key twice
    returns the same event id and inserts no second row. Events without an
    external_id carry no idempotency key and are always appended."""
    if not is_valid_type(type):
        raise UnknownEventType(type)
    src = EventSource(source)  # raises ValueError on an unknown source

    with transaction() as conn:
        with conn.cursor() as cur:
            return append_event(
                cur, src.value, type, occurred_at, payload, external_id, contact_id, piece_id
            )


def record_note(contact_id: UUID, note_type: str, text: str) -> int:
    """Human residue capture. Wraps ingest_event(source='human'); AI-structuring of
    a raw voice note happens before this call. `note_type` is validated as taxonomy."""
    return ingest_event(
        source="human",
        type=note_type,
        occurred_at=datetime.now(UTC),
        payload={"text": text},
        contact_id=contact_id,
    )


class _DbLookups:
    """SQL-backed Lookups for resolve_orphans. Shares the caller's open cursor."""

    def __init__(self, cur) -> None:
        self._cur = cur

    def piece_by_mailer_code(self, code: str) -> tuple[UUID, UUID] | None:
        self._cur.execute(
            "select id, contact_id from pieces where mailer_code = %s", (code,)
        )
        row = self._cur.fetchone()
        return (row[0], row[1]) if row else None

    def contact_by_thread(self, thread_id: str) -> UUID | None:
        self._cur.execute(
            "select contact_id from events "
            "where payload->>%s = %s and contact_id is not null "
            "order by occurred_at limit 1",
            (THREAD_KEY, thread_id),
        )
        row = self._cur.fetchone()
        return row[0] if row else None

    def contact_by_phone(self, phone_e164: str) -> UUID | None:
        self._cur.execute(
            "select id from contacts where phone_e164 = %s", (phone_e164,)
        )
        row = self._cur.fetchone()
        return row[0] if row else None


def resolve_orphans(since: datetime | None = None) -> ResolutionReport:
    """Run the identity-resolution precedence chain over unattributed events.
    Attributes each match (and the piece, when matched by mailer code). Idempotent:
    a re-run finds only what remained orphaned. Never fuzzy-matches."""
    matched: list[tuple[int, UUID]] = []
    orphaned: list[int] = []

    with transaction() as conn:
        with conn.cursor() as cur:
            if since is not None:
                cur.execute(
                    sql.SQL(
                        "select {cols} from events "
                        "where contact_id is null and occurred_at >= %s order by id"
                    ).format(cols=EVENT_COLS),
                    (since,),
                )
            else:
                cur.execute(
                    sql.SQL(
                        "select {cols} from events "
                        "where contact_id is null order by id"
                    ).format(cols=EVENT_COLS)
                )
            rows = cur.fetchall()
            lookups: Lookups = _DbLookups(cur)
            for row in rows:
                event = event_from_row(row)
                match = resolve(event, lookups)
                if match is None:
                    orphaned.append(event.id)
                    continue
                cur.execute(
                    "update events set contact_id = %s, "
                    "piece_id = coalesce(%s, piece_id) where id = %s",
                    (match.contact_id, match.piece_id, event.id),
                )
                matched.append((event.id, match.contact_id))

    return ResolutionReport(matched=matched, orphaned=orphaned)
