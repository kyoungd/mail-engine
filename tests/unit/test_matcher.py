"""Table-driven tests for the resolution precedence chain, including the
never-fuzzy negative cases. Pure — an in-memory Lookups stands in for the DB."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from domain.enums import EventSource
from domain.types import Event
from resolution.matcher import resolve


def _ev(payload: dict) -> Event:
    at = datetime(2026, 1, 1, tzinfo=UTC)
    return Event(
        id=0, source=EventSource.NMC, type="call.inbound",
        occurred_at=at, ingested_at=at, payload=payload,
    )


class FakeLookups:
    def __init__(self, *, pieces=None, threads=None, phones=None) -> None:
        self._pieces = pieces or {}
        self._threads = threads or {}
        self._phones = phones or {}

    def piece_by_mailer_code(self, code: str) -> tuple[UUID, UUID] | None:
        return self._pieces.get(code)

    def contact_by_thread(self, thread_id: str) -> UUID | None:
        return self._threads.get(thread_id)

    def contact_by_phone(self, phone_e164: str) -> UUID | None:
        return self._phones.get(phone_e164)


def test_mailer_code_matches_piece_and_contact():
    piece_id, contact_id = uuid4(), uuid4()
    lookups = FakeLookups(pieces={"MC1": (piece_id, contact_id)})
    match = resolve(_ev({"mailer_code": "MC1"}), lookups)
    assert match is not None
    assert match.via == "mailer_code"
    assert match.contact_id == contact_id
    assert match.piece_id == piece_id


def test_unresolved_mailer_code_falls_through_to_phone():
    contact_id = uuid4()
    lookups = FakeLookups(phones={"+18186793565": contact_id})
    match = resolve(_ev({"mailer_code": "NOPE", "phone": "(818) 679-3565"}), lookups)
    assert match is not None
    assert match.via == "phone"
    assert match.contact_id == contact_id
    assert match.piece_id is None


def test_thread_continuity_matches():
    contact_id = uuid4()
    lookups = FakeLookups(threads={"T1": contact_id})
    match = resolve(_ev({"thread_id": "T1"}), lookups)
    assert match is not None
    assert match.via == "thread"
    assert match.contact_id == contact_id


def test_phone_is_normalized_before_lookup():
    contact_id = uuid4()
    lookups = FakeLookups(phones={"+18186793565": contact_id})
    match = resolve(_ev({"phone": "1-818-679-3565"}), lookups)
    assert match is not None
    assert match.via == "phone"


def test_prenormalized_phone_e164_key_matches():
    # A feed that already carries E.164 uses the phone_e164 key directly.
    contact_id = uuid4()
    lookups = FakeLookups(phones={"+18186793565": contact_id})
    match = resolve(_ev({"phone_e164": "+18186793565"}), lookups)
    assert match is not None
    assert match.via == "phone"
    assert match.contact_id == contact_id


def test_name_or_address_never_matches():
    lookups = FakeLookups(phones={"+18186793565": uuid4()})
    match = resolve(_ev({"name": "Bob Plumber", "address": "123 Main St"}), lookups)
    assert match is None


def test_empty_payload_is_an_orphan():
    assert resolve(_ev({}), FakeLookups()) is None


def test_mailer_code_wins_over_phone():
    piece_id, via_piece, via_phone = uuid4(), uuid4(), uuid4()
    lookups = FakeLookups(
        pieces={"MC1": (piece_id, via_piece)},
        phones={"+18186793565": via_phone},
    )
    match = resolve(_ev({"mailer_code": "MC1", "phone": "818-679-3565"}), lookups)
    assert match is not None
    assert match.via == "mailer_code"
    assert match.contact_id == via_piece
