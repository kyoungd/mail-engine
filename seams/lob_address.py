"""The real Lob client behind the `AddressVerifier` seam (Lob US Address Verification,
fields verified 2026-07-27 — design §5's vendor facts). Stdlib HTTP only, matching
`seams/lob.py`: no new dependencies.

POST /v1/us_verifications, Basic auth with the API key as the username. The response
carries `deliverability` (the verdict enum), a `components` block with
`delivery_point_barcode` and the standardized parts, and `primary_line`/`secondary_line`
as the standardized street lines.

The anti-corruption boundary matters most in the failure mapping, because §5 pins two
categories that a naive client would collapse into one:

  VERDICT  any recognized `deliverability` value, INCLUDING `undeliverable` and a
           response with an empty delivery-point barcode. Returned as a result.
  ERROR    transport failure, non-2xx, unparseable body, or a `deliverability` value
           outside the pinned enum. Raised as `AddressVerificationError`, which leaves
           the row unstamped for the next run.

An unrecognized verdict is deliberately an ERROR rather than a verbatim store: §6's
audience exclusion reads this column, so a value we do not understand must surface as an
unverified row rather than silently failing to exclude an undeliverable address.
"""

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Any

from seams.address_verifier import (
    VERDICTS,
    AddressVerificationError,
    VerificationResult,
)

_BASE_URL = "https://api.lob.com/v1/us_verifications"
_TIMEOUT_SECONDS = 20


class LobAddressVerifier:
    """`AddressVerifier` implementation. One vendor call per `verify`, no retry loop —
    retry is the next job run's business (§5)."""

    def __init__(self, api_key: str, *, base_url: str = _BASE_URL, timeout: float = _TIMEOUT_SECONDS):
        if not api_key:
            raise ValueError("LobAddressVerifier requires an API key")
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "LobAddressVerifier":
        key = os.environ.get("LOB_API_KEY", "")
        if not key:
            raise ValueError("LOB_API_KEY is not set")
        return cls(key)

    def _post(self, payload: dict[str, str]) -> dict[str, Any]:
        body = json.dumps(payload).encode()
        token = base64.b64encode(f"{self.api_key}:".encode()).decode()
        request = urllib.request.Request(
            self.base_url,
            data=body,
            headers={
                "Authorization": f"Basic {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()[:200] if hasattr(exc, "read") else ""
            raise AddressVerificationError(f"Lob returned HTTP {exc.code}: {detail}") from exc
        except Exception as exc:  # URLError, timeout, socket error
            raise AddressVerificationError(f"Lob unreachable: {str(exc)[:160]}") from exc

        try:
            parsed = json.loads(raw)
        except ValueError as exc:
            raise AddressVerificationError("Lob returned an unparseable body") from exc
        if not isinstance(parsed, dict):
            raise AddressVerificationError("Lob returned a non-object body")
        return parsed

    def verify(self, address: dict[str, str]) -> VerificationResult:
        payload = {
            "primary_line": address.get("addr_line1", "") or "",
            "secondary_line": address.get("addr_line2", "") or "",
            "city": address.get("addr_city", "") or "",
            "state": address.get("addr_state", "") or "",
            "zip_code": address.get("addr_zip", "") or "",
        }
        parsed = self._post(payload)
        return self._to_result(parsed)

    @staticmethod
    def _to_result(parsed: dict[str, Any]) -> VerificationResult:
        verdict = str(parsed.get("deliverability") or "")
        if verdict not in VERDICTS:
            raise AddressVerificationError(
                f"Lob returned an unrecognized deliverability {verdict!r}; "
                "the audience exclusion reads this column, so it is not stored blind"
            )
        components = parsed.get("components") or {}
        if not isinstance(components, dict):
            components = {}

        zip_code = str(components.get("zip_code") or "")
        plus4 = str(components.get("zip_code_plus_4") or "")
        return VerificationResult(
            deliverability=verdict,
            delivery_point=str(components.get("delivery_point_barcode") or ""),
            std_addr_line1=str(parsed.get("primary_line") or ""),
            std_addr_line2=str(parsed.get("secondary_line") or ""),
            std_addr_city=str(components.get("city") or ""),
            std_addr_state=str(components.get("state") or ""),
            std_addr_zip=f"{zip_code}-{plus4}" if zip_code and plus4 else zip_code,
        )
