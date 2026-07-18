"""In-memory seam implementations for testing the jobs and execute_wave without any
vendor. They model the two properties the real clients must have: submit is idempotent
on the mailer code (the vendor idempotency key), and a feed can fail.
"""

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from domain.enums import EventSource
from domain.types import Event
from seams.print_api import ProofResult, SubmissionResult

_WEBHOOK_STATUS_TO_TYPE = {
    "delivered": "piece.delivered",
    "returned": "piece.returned",
}


class FakePrintApi:
    """Idempotent on mailer_code (a re-submit returns the cached result, never a second
    print). `fail_after` raises once this many distinct pieces have printed — a clean
    way to simulate a crash mid-drop and prove resumability."""

    def __init__(self, fail_after: int | None = None, cost_cents: int = 73) -> None:
        self.fail_after = fail_after
        self.cost_cents = cost_cents
        self.printed: dict[str, SubmissionResult] = {}
        self.submit_calls = 0
        self.proof_calls = 0

    def submit_piece(
        self, mailer_code: str, creative: dict[str, Any], recipient=None
    ) -> SubmissionResult:
        if mailer_code in self.printed:
            return self.printed[mailer_code]
        if self.fail_after is not None and len(self.printed) >= self.fail_after:
            raise RuntimeError("print api down")
        self.submit_calls += 1
        result = SubmissionResult(external_id=f"lob_{mailer_code}", cost_cents=self.cost_cents)
        self.printed[mailer_code] = result
        return result

    def render_proof(self, creative: dict[str, Any]) -> ProofResult:
        """Deterministic fake proof: the url encodes a checksum of the creative, so a
        test can tell two variants' proofs apart without a vendor."""
        checksum = hashlib.sha256(json.dumps(creative, sort_keys=True).encode()).hexdigest()[:12]
        self.proof_calls += 1
        return ProofResult(pdf_url=f"https://lob.test/proof/{checksum}.pdf")

    def parse_webhook(self, raw: bytes, headers: dict[str, str]) -> Event | None:
        data = json.loads(raw)
        event_type = _WEBHOOK_STATUS_TO_TYPE.get(data["status"])
        if event_type is None:
            return None
        at = datetime.now(UTC)
        return Event(
            id=0,
            source=EventSource.LOB,
            type=event_type,
            occurred_at=at,
            ingested_at=at,
            external_id=data.get("id"),
            payload={"mailer_code": data["mailer_code"]},
        )


@dataclass
class FakeResponseFeed:
    source: str
    events: list[Event] = field(default_factory=list)
    fail: bool = False

    def pull_events(self, since: datetime) -> Iterator[Event]:
        if self.fail:
            raise RuntimeError(f"{self.source} feed down")
        for event in self.events:
            if event.occurred_at >= since:
                yield event


@dataclass
class FakeSender:
    sent: list[tuple[str, str]] = field(default_factory=list)

    def send(self, founder: str, message: str) -> None:
        self.sent.append((founder, message))
