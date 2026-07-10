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


class PrintApi(Protocol):
    def submit_piece(self, mailer_code: str, creative: dict[str, Any]) -> SubmissionResult:
        """Submit one piece. MUST be idempotent on `mailer_code` (the vendor
        idempotency key), so a resumed drop never double-prints."""
        ...

    def parse_webhook(self, raw: bytes, headers: dict[str, str]) -> Event:
        """Translate a vendor delivery webhook into a canonical taxonomy event.
        Vendor field names never appear in the returned event's shape."""
        ...
