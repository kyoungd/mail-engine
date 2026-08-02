"""The demo-line summary feed (Stage C2's Section 3 client; the server half is
booking-system's B2 endpoint, `to-do-partner-report-support.md` Deliverable 4).

`GET {NMC_BOOKING_URL}/api/partner-demo-calls/summary?from=<ISO>&to=<ISO>` under
`X-API-KEY`. The window is the CALLER's job (since-last-report); the endpoint does
no calendar math. All counts arrive as strings (the frozen BigInt-as-string wire
convention). A transport or HTTP error raises — the composer's contract is to
OMIT the section when the feed is unreachable, never render a placeholder.
"""

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Protocol

_TIMEOUT_SECONDS = 10.0


class DemosClient(Protocol):
    def summary(self, from_: datetime, to: datetime) -> list[dict[str, Any]]:
        """Per-partner aggregates over [from_, to)."""
        ...


class NmcDemosClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    @classmethod
    def from_env(cls) -> "NmcDemosClient":
        url = os.environ.get("NMC_BOOKING_URL", "")
        key = os.environ.get("NMC_API_KEY", "")
        if not url or not key:
            raise ValueError("NMC_BOOKING_URL / NMC_API_KEY are not set")
        return cls(url, key)

    def summary(self, from_: datetime, to: datetime) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode(
            {"from": from_.isoformat(), "to": to.isoformat()}
        )
        request = urllib.request.Request(
            f"{self.base_url}/api/partner-demo-calls/summary?{query}",
            headers={"X-API-KEY": self.api_key},
        )
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode())
        return payload["partners"]
