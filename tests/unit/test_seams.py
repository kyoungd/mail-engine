"""Unit tests for the fake seams' contract behavior: the print API is idempotent on
mailer code, and parse_webhook translates a vendor payload into a canonical event with
no vendor vocabulary in its shape."""

import json

from domain.enums import EventSource
from seams.fakes import FakePrintApi

_ADDR = {
    "addr_line1": "301 South Mills Avenue",
    "addr_line2": "",
    "addr_city": "Lodi",
    "addr_state": "CA",
    "addr_zip": "95242",
}


def test_submit_piece_is_idempotent_on_mailer_code():
    fake = FakePrintApi()
    first = fake.submit_piece("MC1", {})
    second = fake.submit_piece("MC1", {})
    assert first == second
    assert fake.submit_calls == 1  # the re-submit did not print again


def test_parse_webhook_translates_delivered_to_canonical_event():
    fake = FakePrintApi()
    raw = json.dumps({"status": "delivered", "mailer_code": "abc123", "id": "evt_1"}).encode()

    event = fake.parse_webhook(raw, {})

    assert event is not None
    assert event.type == "piece.delivered"
    assert event.source == EventSource.LOB
    assert event.external_id == "evt_1"
    assert event.payload["mailer_code"] == "abc123"


def test_parse_webhook_translates_returned():
    fake = FakePrintApi()
    raw = json.dumps({"status": "returned", "mailer_code": "xyz", "id": "evt_2"}).encode()
    event = fake.parse_webhook(raw, {})
    assert event is not None
    assert event.type == "piece.returned"


# --- AddressVerifier seam (Phase 1 gate, design §5) --------------------------------


def test_fake_verifier_satisfies_the_protocol():
    from seams.address_verifier import AddressVerifier
    from seams.fakes import FakeVerifier

    assert isinstance(FakeVerifier(), AddressVerifier)


def test_deliverable_verdict_carries_components_and_delivery_point():
    from seams.fakes import FakeVerifier

    result = FakeVerifier().verify(_ADDR)
    assert result.deliverability == "deliverable"
    assert result.delivery_point  # 11-digit USPS barcode, §5
    assert result.std_addr_line1 and result.std_addr_city and result.std_addr_zip


def test_no_delivery_point_is_a_verdict_not_an_error():
    """§5: an empty/absent barcode is the 'no delivery point' case — a RESULT. The
    inherit step skips it and §6 does not dedupe on it, but it is never re-called."""
    from seams.fakes import FakeVerifier

    result = FakeVerifier(delivery_point="").verify(_ADDR)
    assert result.delivery_point == ""
    assert result.deliverability == "deliverable"


def test_undeliverable_is_the_only_excluding_verdict():
    """§5 pins the enum; §6 pins that only `undeliverable` excludes. The three
    deliverable_*_unit variants are deliverable-family — CSLB unit data is spotty."""
    from seams.fakes import FakeVerifier

    assert FakeVerifier(deliverability="undeliverable").verify(_ADDR).deliverability == (
        "undeliverable"
    )
    for variant in (
        "deliverable_missing_unit",
        "deliverable_incorrect_unit",
        "deliverable_unnecessary_unit",
    ):
        assert FakeVerifier(deliverability=variant).verify(_ADDR).deliverability == variant


def test_vendor_error_is_distinguishable_from_a_verdict():
    """§5's pinned failure semantics: a verdict is a result (stamp, never re-call); an
    ERROR stamps nothing so the next job run retries it. If the Fake cannot express
    both, Phase 3's job cannot be tested for the difference."""
    import pytest

    from seams.address_verifier import AddressVerificationError
    from seams.fakes import FakeVerifier

    with pytest.raises(AddressVerificationError):
        FakeVerifier(fail=True).verify(_ADDR)
