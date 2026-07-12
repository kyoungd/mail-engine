"""The PostHog response feed: landing-page events -> canonical events (FR-5).

Pulls via the Query endpoint (HogQL) — the legacy /events API is deprecated and
window-capped. Keyset pagination on (timestamp, uuid); OFFSET is rejected by PostHog
for programmatic queries. Overlapping pulls are free: ingestion dedupes on
(source, external_id), and external_id here is PostHog's event uuid.

Mapping (decided 2026-07-12): $pageview -> page.visit, checkout_started ->
page.cta_click, landing_purchase_completed -> signup.completed (a landing purchase IS
the signup — the future NMC feed must NOT also emit signup.completed). Only events
carrying a mailer_code are pulled; attribution stays downstream in resolution.
"""

import json
import urllib.request
from collections.abc import Callable, Iterator
from datetime import datetime

from domain.enums import EventSource
from domain.types import Event

_EVENT_TYPE_BY_POSTHOG = {
    "$pageview": "page.visit",
    "checkout_started": "page.cta_click",
    "landing_purchase_completed": "signup.completed",
}
_PAGE_SIZE = 1000


def _default_transport(url: str, body: bytes, headers: dict[str, str]) -> dict:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


class PostHogFeed:
    source = "posthog"

    def __init__(
        self,
        api_key: str,
        project_id: str,
        host: str = "https://us.posthog.com",
        transport: Callable[[str, bytes, dict[str, str]], dict] | None = None,
    ) -> None:
        self.api_key = api_key
        self.project_id = project_id
        self.host = host.rstrip("/")
        self.transport = transport or _default_transport

    def _query(self, hogql: str) -> list[list]:
        body = json.dumps(
            {"query": {"kind": "HogQLQuery", "query": hogql}, "name": "mail-engine-sync"}
        ).encode()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        response = self.transport(
            f"{self.host}/api/projects/{self.project_id}/query/", body, headers
        )
        return response["results"]

    def pull_events(self, since: datetime) -> Iterator[Event]:
        names = ", ".join(f"'{n}'" for n in _EVENT_TYPE_BY_POSTHOG)
        cursor = (since.strftime("%Y-%m-%d %H:%M:%S.%f"), "")
        while True:
            rows = self._query(
                "select uuid, event, timestamp, properties.mailer_code, "
                "properties.tier, properties.amount from events "
                f"where event in ({names}) "
                # 'unknown' is the landing page's no-code sentinel (organic traffic).
                # It stays in PostHog to measure uncoded lift, but must not reach the
                # spine — every such event would fail resolution and flood the orphan
                # queue.
                "and properties.mailer_code is not null "
                "and properties.mailer_code != 'unknown' "
                f"and (timestamp, toString(uuid)) > ('{cursor[0]}', '{cursor[1]}') "
                f"order by timestamp, toString(uuid) limit {_PAGE_SIZE}"
            )
            for uuid, name, timestamp, mailer_code, tier, amount in rows:
                payload = {"mailer_code": mailer_code}
                if tier is not None:
                    payload["tier"] = tier
                if amount is not None:
                    payload["amount"] = amount
                yield Event(
                    id=0,  # not yet ingested; ingestion assigns the real row id
                    source=EventSource.POSTHOG,
                    type=_EVENT_TYPE_BY_POSTHOG[name],
                    occurred_at=datetime.fromisoformat(timestamp),
                    ingested_at=datetime.fromisoformat(timestamp),
                    external_id=str(uuid),
                    payload=payload,
                )
            if len(rows) < _PAGE_SIZE:
                return
            cursor = (rows[-1][2], str(rows[-1][0]))
