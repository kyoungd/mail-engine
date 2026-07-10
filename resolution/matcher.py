"""Identity resolution — the precedence chain, never fuzzy (data document §3).

Pure: it never touches the database. The service verb `resolve_orphans` supplies a
`Lookups` backed by SQL; tests supply an in-memory one. That is what keeps the
precedence logic table-testable and keeps DB access out of this layer.

Order of attempts, stopping at the first *successful* match (a present-but-unresolved
key falls through to the next):
  1. mailer_code -> piece -> contact   (strongest; also attributes the piece)
  2. thread continuity                 (same conversation as an already-matched event)
  3. exact normalized phone
Never name, never address. A wrong attribution poisons response data silently; an
orphan is visible and fixable.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from domain.phone import to_e164
from domain.types import Event

# Payload key carrying conversation-thread identity. Ingestion's thread lookup
# reads prior events under this same key — single-sourced here so the two sides
# can never drift apart.
THREAD_KEY = "thread_id"


@dataclass(frozen=True)
class Match:
    contact_id: UUID
    piece_id: UUID | None
    via: str  # 'mailer_code' | 'thread' | 'phone'


class Lookups(Protocol):
    def piece_by_mailer_code(self, code: str) -> tuple[UUID, UUID] | None:
        """(piece_id, contact_id) for the piece carrying this code, or None."""

    def contact_by_thread(self, thread_id: str) -> UUID | None:
        """Contact of an already-matched event on the same conversation thread."""

    def contact_by_phone(self, phone_e164: str) -> UUID | None:
        """Contact whose stored phone exactly equals this normalized number."""


def resolve(event: Event, lookups: Lookups) -> Match | None:
    payload = event.payload or {}

    code = payload.get("mailer_code")
    if code:
        hit = lookups.piece_by_mailer_code(code)
        if hit is not None:
            piece_id, contact_id = hit
            return Match(contact_id=contact_id, piece_id=piece_id, via="mailer_code")

    thread_id = payload.get(THREAD_KEY)
    if thread_id:
        contact_id = lookups.contact_by_thread(thread_id)
        if contact_id is not None:
            return Match(contact_id=contact_id, piece_id=None, via="thread")

    phone = payload.get("phone_e164") or to_e164(payload.get("phone"))
    if phone:
        contact_id = lookups.contact_by_phone(phone)
        if contact_id is not None:
            return Match(contact_id=contact_id, piece_id=None, via="phone")

    return None
