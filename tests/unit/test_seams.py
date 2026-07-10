"""Unit tests for the fake seams' contract behavior: the print API is idempotent on
mailer code, and parse_webhook translates a vendor payload into a canonical event with
no vendor vocabulary in its shape."""

import json

from domain.enums import EventSource
from seams.fakes import FakePrintApi


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

    assert event.type == "piece.delivered"
    assert event.source == EventSource.LOB
    assert event.external_id == "evt_1"
    assert event.payload["mailer_code"] == "abc123"


def test_parse_webhook_translates_returned():
    fake = FakePrintApi()
    raw = json.dumps({"status": "returned", "mailer_code": "xyz", "id": "evt_2"}).encode()
    assert fake.parse_webhook(raw, {}).type == "piece.returned"
