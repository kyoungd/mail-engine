"""Run a response feed through ingestion. The feed yields canonical events; this
stamps the feed's source and appends each idempotently. A feed error propagates —
that is what lets the nightly orchestrator halt before recomputing on stale data."""

from datetime import datetime

from seams.response_feed import ResponseFeed
from service.ingestion import ingest_event


def sync(feed: ResponseFeed, since: datetime) -> int:
    count = 0
    for event in feed.pull_events(since):
        ingest_event(
            source=feed.source,
            type=event.type,
            occurred_at=event.occurred_at,
            payload=event.payload,
            external_id=event.external_id,
            contact_id=event.contact_id,
            piece_id=event.piece_id,
        )
        count += 1
    return count
