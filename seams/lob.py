"""The real Lob client behind the PrintApi seam (docs.lob.com, verified 2026-07-11;
decision record: docs/decisions.md). Stdlib HTTP only — no new dependencies.

- submit: POST /v1/postcards, Basic auth (key as username), `Idempotency-Key` header =
  our mailer code (the resumability guarantee), mailer code also in metadata +
  merge_variables so webhooks and creative can both carry it.
- webhooks: HMAC-SHA256 over f"{timestamp}.{raw body}", headers Lob-Signature +
  Lob-Signature-Timestamp, 5-minute tolerance. postcard.processed_for_delivery is the
  delivery proxy (USPS never scans a postcard into the mailbox); other tracking events
  are untracked -> None.
"""

import base64
import hashlib
import hmac
import json
import urllib.request
from datetime import UTC, datetime
from typing import Any, Callable

from domain.enums import EventSource
from domain.types import Event
from seams.print_api import ProofResult, Recipient, SubmissionResult

_EVENT_TYPE_MAP = {
    "postcard.processed_for_delivery": "piece.delivered",
    "postcard.returned_to_sender": "piece.returned",
}
_SIGNATURE_TOLERANCE_SECONDS = 300

# A proof renders the creative, not a real mailing — the recipient only has to be a
# deliverable placeholder (test mode never mails it) and carries no real contact's PII.
_PROOF_RECIPIENT = Recipient(
    name="Proof Sample",
    address_line1="185 Berry St Ste 6100",
    city="San Francisco",
    state="CA",
    zip_code="94107",
)
# Substituted for {{mailer_code}} so the rendered proof shows a QR/link. Matches
# nothing real, so a scan of a proof lands as an orphan rather than a fake response.
_PROOF_MAILER_CODE = "SAMPLE7X29Q"


class BadWebhookSignature(ValueError):
    pass


def _default_transport(url: str, body: bytes, headers: dict[str, str]) -> dict:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def _truncate_name(name: str, limit: int = 40) -> str:
    """Lob rejects to.name > 40 chars (422); CSLB/FBN legal names often exceed it.
    Cut at the last word boundary inside the limit ("hello there" -> "hello", never
    "hello th"); a single word longer than the limit gets a hard cut. Truncation is
    delivery-irrelevant — USPS routes on the address."""
    if len(name) <= limit:
        return name
    cut = name[:limit]
    if name[limit] != " " and not cut.endswith(" "):
        boundary = cut.rfind(" ")
        if boundary > 0:
            cut = cut[:boundary]
    return cut.rstrip()


class LobPrintApi:
    def __init__(
        self,
        api_key: str,
        from_address: dict[str, str],
        webhook_secret: str = "",
        cost_cents: int = 87,
        base_url: str = "https://api.lob.com/v1",
        transport: Callable[[str, bytes, dict[str, str]], dict] | None = None,
    ) -> None:
        self.api_key = api_key
        self.from_address = from_address
        self.webhook_secret = webhook_secret
        self.cost_cents = cost_cents
        self.base_url = base_url
        self.transport = transport or _default_transport

    def submit_piece(
        self, mailer_code: str, creative: dict[str, Any], recipient: Recipient
    ) -> SubmissionResult:
        payload = {
            "to": {
                "name": _truncate_name(recipient.name),
                "address_line1": recipient.address_line1,
                "address_line2": recipient.address_line2 or "",
                "address_city": recipient.city,
                "address_state": recipient.state,
                "address_zip": recipient.zip_code,
            },
            "from": self.from_address,
            "front": creative.get("front", ""),
            "back": creative.get("back", ""),
            "size": creative.get("size", "4x6"),
            "mail_type": creative.get("mail_type", "usps_first_class"),
            "use_type": "marketing",
            "merge_variables": {"mailer_code": mailer_code},
            "metadata": {"mailer_code": mailer_code},
        }
        auth = base64.b64encode(f"{self.api_key}:".encode()).decode()
        headers = {
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
            "Idempotency-Key": mailer_code,
        }
        response = self.transport(
            f"{self.base_url}/postcards", json.dumps(payload).encode(), headers
        )
        return SubmissionResult(external_id=response["id"], cost_cents=self.cost_cents)

    def render_proof(self, creative: dict[str, Any]) -> ProofResult:
        """Test-mode POST /postcards: the response carries `url` (the rendered PDF) but
        nothing prints or mails. Uses this client's key — construct it with the test key
        (LOB_TEST_API_KEY), never the live one."""
        payload = {
            "to": {
                "name": _PROOF_RECIPIENT.name,
                "address_line1": _PROOF_RECIPIENT.address_line1,
                "address_line2": _PROOF_RECIPIENT.address_line2 or "",
                "address_city": _PROOF_RECIPIENT.city,
                "address_state": _PROOF_RECIPIENT.state,
                "address_zip": _PROOF_RECIPIENT.zip_code,
            },
            "from": self.from_address,
            "front": creative.get("front", ""),
            "back": creative.get("back", ""),
            "size": creative.get("size", "4x6"),
            "mail_type": creative.get("mail_type", "usps_first_class"),
            "use_type": "marketing",
            "merge_variables": {"mailer_code": _PROOF_MAILER_CODE},
        }
        auth = base64.b64encode(f"{self.api_key}:".encode()).decode()
        headers = {
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        }
        response = self.transport(
            f"{self.base_url}/postcards", json.dumps(payload).encode(), headers
        )
        return ProofResult(pdf_url=response["url"])

    def parse_webhook(self, raw: bytes, headers: dict[str, str]) -> Event | None:
        lower = {k.lower(): v for k, v in headers.items()}
        signature = lower.get("lob-signature", "")
        timestamp = lower.get("lob-signature-timestamp", "")
        expected = hmac.new(
            self.webhook_secret.encode(),
            f"{timestamp}.".encode() + raw,
            hashlib.sha256,
        ).hexdigest()
        if not signature or not hmac.compare_digest(expected, signature):
            raise BadWebhookSignature("Lob webhook signature mismatch")
        age = abs(datetime.now(UTC).timestamp() - int(timestamp) / 1000)
        if age > _SIGNATURE_TOLERANCE_SECONDS:
            raise BadWebhookSignature("Lob webhook timestamp outside tolerance")

        data = json.loads(raw)
        event_type = _EVENT_TYPE_MAP.get(data.get("event_type", {}).get("id", ""))
        if event_type is None:
            return None
        body = data.get("body", {})
        occurred = data.get("date_created")
        at = (
            datetime.fromisoformat(occurred.replace("Z", "+00:00"))
            if occurred
            else datetime.now(UTC)
        )
        return Event(
            id=0,
            source=EventSource.LOB,
            type=event_type,
            occurred_at=at,
            ingested_at=at,
            external_id=data.get("id"),
            payload={"mailer_code": (body.get("metadata") or {}).get("mailer_code")},
        )
