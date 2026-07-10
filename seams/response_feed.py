"""The response-feed seam (PostHog / NeverMissCall). Each feed yields canonical events
with `external_id` set (the idempotency key) and best-effort attribution — the sync job
runs them through ingestion without knowing which vendor produced them.

NMC is consumed through this same contract as any third party: no special access.
"""

from collections.abc import Iterator
from datetime import datetime
from typing import Protocol

from domain.types import Event


class ResponseFeed(Protocol):
    source: str  # the event_source label the sync job stamps on ingested events

    def pull_events(self, since: datetime) -> Iterator[Event]:
        """Yield canonical events at or after `since`. Attribution fields are
        best-effort (mailer code / thread / phone in payload, else null)."""
        ...
