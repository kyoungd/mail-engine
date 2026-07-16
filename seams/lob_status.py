"""The Lob status feed: postcard tracking events -> canonical events (FR-5's delivery
half). Consumed through the same ResponseFeed contract as any third party.

POLLED, not pushed. The PRD specified webhooks under SR-5's assumption of a VPS; with
production running locally Lob cannot reach it inbound, and the only consumer of these
events is the nightly judgment job — so real-time buys nothing. A poll is also robust to
downtime, where a webhook missed while the box was asleep is gone for good. See
decisions.md.

⚠️ A tracking event's `name` is NOT the webhook's event id. The webhook keys on
`postcard.processed_for_delivery`; the tracking event keys on `Processed for Delivery`
(verified against Lob's OpenAPI spec, shared/resources/tracking_events/models/
tracking_event_normal.yml). Reusing lob.py's _EVENT_TYPE_MAP here would match nothing
and this feed would run clean forever while ingesting zero events.

`Processed for Delivery` maps to piece.delivered — matching lob.py's webhook map rather
than Lob's separate, more literal `Delivered` scan, so poll and webhook stay semantically
identical. Changing that meaning is a decision, not an implementation detail.
"""

import json
import urllib.request
from collections.abc import Callable, Iterator
from datetime import datetime

from domain.enums import EventSource
from domain.types import Event

# Lob tracking-event name -> canonical type. Lob emits eight names; the taxonomy is
# closed (FR-5) and takes two. `Mailed` is Enterprise-only per Lob's spec anyway.
_EVENT_TYPE_BY_TRACKING_NAME = {
    "Processed for Delivery": "piece.delivered",
    "Returned to Sender": "piece.returned",
}
_PAGE_SIZE = 100


def _default_transport(url: str, headers: dict[str, str]) -> dict:
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def _parse(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


class LobStatusFeed:
    source = "lob"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.lob.com/v1",
        transport: Callable[[str, dict[str, str]], dict] | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.transport = transport or _default_transport

    def _auth_header(self) -> dict[str, str]:
        import base64

        token = base64.b64encode(f"{self.api_key}:".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def pull_events(self, since: datetime) -> Iterator[Event]:
        """Every mapped tracking event scanned at or after `since`.

        Filters on the tracking event's own `time` — when USPS registered the scan —
        never on the postcard's date_created: a piece mailed three weeks ago can earn
        a Returned to Sender scan today, so paging by postcard age would go blind on
        most of the mail. Overlapping pulls are free; external_id is Lob's stable
        evnt_ id and ingestion dedupes on (source, external_id).
        """
        url = f"{self.base_url}/postcards?limit={_PAGE_SIZE}"
        while url:
            page = self.transport(url, self._auth_header())
            for postcard in page.get("data", []):
                # A postcard with no mailer code was not mailed by this system
                # (dashboard/foreign). Yielding it would flood the orphan queue.
                code = (postcard.get("metadata") or {}).get("mailer_code")
                if not code:
                    continue
                for tracking_event in postcard.get("tracking_events") or []:
                    event_type = _EVENT_TYPE_BY_TRACKING_NAME.get(tracking_event.get("name", ""))
                    if event_type is None:
                        continue
                    occurred = _parse(tracking_event["time"])
                    if occurred < since:
                        continue
                    yield Event(
                        id=0,  # not yet ingested; ingestion assigns the real row id
                        source=EventSource.LOB,
                        type=event_type,
                        occurred_at=occurred,
                        ingested_at=occurred,
                        external_id=tracking_event["id"],
                        payload={"mailer_code": code},
                    )
            url = page.get("next_url")
