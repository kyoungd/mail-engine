"""The Lob client: submission payload/idempotency header, signed-webhook parsing,
event-type mapping. Transport is injected — no network."""

import hashlib
import hmac
import json
from datetime import UTC, datetime

import pytest

from seams.lob import BadWebhookSignature, LobPrintApi, _truncate_name
from seams.print_api import Recipient

FROM = {"name": "NMC", "address_line1": "1 Way", "address_city": "LA",
        "address_state": "CA", "address_zip": "90001"}
RECIPIENT = Recipient(
    name="Griffin's Plumbing", address_line1="3940 Laurel Canyon Blvd",
    city="Studio City", state="CA", zip_code="91604",
)


def _client(calls, secret="whsec_test"):
    def transport(url, body, headers):
        calls.append((url, json.loads(body), headers))
        return {"id": "psc_123"}
    return LobPrintApi("test_key", FROM, webhook_secret=secret, cost_cents=87,
                       transport=transport)


def test_submit_sends_idempotency_key_and_mailer_code():
    calls = []
    result = _client(calls).submit_piece("k7m2xq3vhp", {"front": "<h1>f</h1>", "back": "b"}, RECIPIENT)
    assert result.external_id == "psc_123"
    assert result.cost_cents == 87
    (url, payload, headers), = calls
    assert url.endswith("/postcards")
    assert headers["Idempotency-Key"] == "k7m2xq3vhp"
    assert payload["metadata"]["mailer_code"] == "k7m2xq3vhp"
    assert payload["merge_variables"]["mailer_code"] == "k7m2xq3vhp"
    assert payload["to"]["address_zip"] == "91604"
    assert payload["use_type"] == "marketing"
    assert payload["mail_type"] == "usps_first_class"


def test_render_proof_posts_and_returns_pdf_url():
    calls = []

    def transport(url, body, headers):
        calls.append((url, json.loads(body), headers))
        return {"id": "psc_proof", "url": "https://lob-proofs.test/psc_proof.pdf"}

    client = LobPrintApi("test_key", FROM, transport=transport)

    result = client.render_proof({"front": "<h1>{{mailer_code}}</h1>", "back": "b", "size": "6x9"})

    assert result.pdf_url == "https://lob-proofs.test/psc_proof.pdf"
    (url, payload, headers), = calls
    assert url.endswith("/postcards")
    assert payload["front"] == "<h1>{{mailer_code}}</h1>"
    assert payload["size"] == "6x9"
    assert payload["merge_variables"]["mailer_code"]      # a sample code so the QR renders
    assert headers["Authorization"].startswith("Basic ")  # uses the (test) key it was built with


def test_submit_truncates_recipient_name_to_lob_40_char_limit():
    calls = []
    long_name = Recipient(
        name="SEASON CONTROL HEATING AIR CONDITIONING INC",
        address_line1="7239 Canoga Ave", city="Canoga Park", state="CA",
        zip_code="91303",
    )
    _client(calls).submit_piece("k7m2xq3vhp", {"front": "f", "back": "b"}, long_name)
    (_, payload, _), = calls
    assert payload["to"]["name"] == "SEASON CONTROL HEATING AIR CONDITIONING"
    assert len(payload["to"]["name"]) <= 40


def test_truncate_name_cuts_at_word_boundary_never_mid_word():
    # limit falls inside "SPECIALISTS" -> the whole partial word is dropped
    assert (
        _truncate_name("ADVANCED HEATING AND AIR CONDITIONING SPECIALISTS INC")
        == "ADVANCED HEATING AND AIR CONDITIONING"
    )
    # short names pass through untouched
    assert _truncate_name("Griffin's Plumbing") == "Griffin's Plumbing"
    # a single word longer than the limit has no boundary to respect: hard cut
    assert _truncate_name("A" * 45) == "A" * 40
    # limit landing exactly on a space keeps every complete word before it
    assert _truncate_name("SEASON CONTROL HEATING AIR CONDITIONING INC") == (
        "SEASON CONTROL HEATING AIR CONDITIONING"
    )


def _signed(body: dict, secret="whsec_test", ts=None):
    raw = json.dumps(body).encode()
    ts = ts if ts is not None else str(int(datetime.now(UTC).timestamp() * 1000))
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return raw, {"Lob-Signature": sig, "Lob-Signature-Timestamp": ts}


def _webhook_body(event_type):
    return {
        "id": "evt_1",
        "date_created": "2026-07-11T18:00:00Z",
        "event_type": {"id": event_type},
        "body": {"metadata": {"mailer_code": "k7m2xq3vhp"}},
    }


def test_parse_webhook_maps_delivery_proxy_and_returned():
    client = _client([])
    for lob_type, ours in [
        ("postcard.processed_for_delivery", "piece.delivered"),
        ("postcard.returned_to_sender", "piece.returned"),
    ]:
        raw, headers = _signed(_webhook_body(lob_type))
        event = client.parse_webhook(raw, headers)
        assert event is not None
        assert event.type == ours
        assert event.payload["mailer_code"] == "k7m2xq3vhp"
        assert event.external_id == "evt_1"


def test_parse_webhook_ignores_untracked_event_types():
    raw, headers = _signed(_webhook_body("postcard.in_transit"))
    assert _client([]).parse_webhook(raw, headers) is None


def test_parse_webhook_rejects_bad_signature_and_stale_timestamp():
    client = _client([])
    raw, headers = _signed(_webhook_body("postcard.processed_for_delivery"),
                           secret="wrong_secret")
    with pytest.raises(BadWebhookSignature):
        client.parse_webhook(raw, headers)

    stale = str(int((datetime.now(UTC).timestamp() - 3600) * 1000))
    raw, headers = _signed(_webhook_body("postcard.processed_for_delivery"), ts=stale)
    with pytest.raises(BadWebhookSignature):
        client.parse_webhook(raw, headers)