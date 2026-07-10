"""In-memory seam implementations for testing the jobs and execute_wave without any
vendor. They model the two properties the real clients must have: submit is idempotent
on the mailer code (the vendor idempotency key), and a feed can fail.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from domain.enums import EventSource
from domain.types import Event
from seams.print_api import SubmissionResult

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

    def submit_piece(self, mailer_code: str, creative: dict[str, Any]) -> SubmissionResult:
        if mailer_code in self.printed:
            return self.printed[mailer_code]
        if self.fail_after is not None and len(self.printed) >= self.fail_after:
            raise RuntimeError("print api down")
        self.submit_calls += 1
        result = SubmissionResult(external_id=f"lob_{mailer_code}", cost_cents=self.cost_cents)
        self.printed[mailer_code] = result
        return result

    def parse_webhook(self, raw: bytes, headers: dict[str, str]) -> Event:
        data = json.loads(raw)
        at = datetime.now(UTC)
        return Event(
            id=0,
            source=EventSource.LOB,
            type=_WEBHOOK_STATUS_TO_TYPE[data["status"]],
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
