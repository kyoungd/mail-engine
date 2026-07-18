"""The print-vendor seam (Lob/PostGrid). Anti-corruption boundary: the vendor's data
model, error types, and payload shapes never leak above this module — everything
crossing upward is either a canonical `Event` or one of the small result types here.

The Protocol carries only what a real caller uses today: `submit_piece` (the drop) and
`parse_webhook` (the delivery feed). `verify_address` (the deferred NCOA/CASS job) and
`cost_estimate` (preview) join it when their callers are built — not before.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from domain.types import Event


@dataclass(frozen=True)
class SubmissionResult:
    """What the vendor returns for one submitted piece, in our vocabulary."""

    external_id: str  # the vendor's id for the piece (e.g. Lob's id)
    cost_cents: int


@dataclass(frozen=True)
class ProofResult:
    """The vendor's final rendering of a creative — the print truth (fonts, bleed trim,
    address block), not our HTML design preview. Produced in the vendor's test
    environment: rendered, never printed or mailed."""

    pdf_url: str


@dataclass(frozen=True, kw_only=True)
class Recipient:
    """The mailing destination for one piece, built from the contact row."""

    name: str
    address_line1: str
    address_line2: str | None = None
    city: str
    state: str
    zip_code: str


class PrintApi(Protocol):
    def submit_piece(
        self, mailer_code: str, creative: dict[str, Any], recipient: Recipient
    ) -> SubmissionResult:
        """Submit one piece to `recipient`. MUST be idempotent on `mailer_code` (the
        vendor idempotency key), so a resumed drop never double-prints."""
        ...

    def render_proof(self, creative: dict[str, Any]) -> ProofResult:
        """Render one creative in the vendor's test environment and return the final
        PDF — no piece is printed or mailed. This is what the approval screen shows so
        the founder approves the file that will actually print, not our design preview.
        MUST be called against a test-environment key (real money never moves here)."""
        ...

    def parse_webhook(self, raw: bytes, headers: dict[str, str]) -> Event | None:
        """Translate a vendor delivery webhook into a canonical taxonomy event, or
        None for vendor event types we don't track. Raises on a bad signature.
        Vendor field names never appear in the returned event's shape."""
        ...
