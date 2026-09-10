"""The token-registry seam: publishing a partner's upload token to the edge.

The upload Worker authenticates partners, but it cannot read Postgres — no inbound
port to this box is the whole point of the architecture. So it keeps its own map
of `sha256(token) -> partner_id` in Cloudflare KV, and this seam is the push.

The Worker never sees a plaintext token from us: the partner's client sends the raw
value, the Worker hashes it and looks the hash up. What travels here is only ever
the digest.
"""

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable
from uuid import UUID


class TokenRegistryError(Exception):
    """The edge did not confirm the change. Loud on purpose: a revoke that only
    half happened must never be reported as done."""


@runtime_checkable
class TokenRegistry(Protocol):
    def publish(self, token_hash: str, partner_id: UUID) -> None:
        ...

    def revoke(self, token_hash: str) -> None:
        ...


def _default_transport(
    method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None = None
) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url, data=data, headers={**headers, "User-Agent": "nmc-mail-engine/1.0"},
        method=method,
    )
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode()
    return json.loads(raw) if raw else {}


class WorkerTokenRegistry:
    """The real client, over the upload Worker's admin token endpoints."""

    def __init__(
        self,
        base_url: str,
        admin_token: str,
        transport: Callable[..., Any] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.admin_token = admin_token
        self.transport = transport or _default_transport

    def _call(self, method: str, token_hash: str, body: dict[str, Any] | None) -> None:
        try:
            self.transport(
                method,
                f"{self.base_url}/admin/tokens/{token_hash}",
                {"Authorization": f"Bearer {self.admin_token}"},
                body,
            )
        except (OSError, urllib.error.URLError, ValueError) as exc:
            raise TokenRegistryError(f"{method} to the upload Worker failed: {exc}") from exc

    def publish(self, token_hash: str, partner_id: UUID) -> None:
        self._call("PUT", token_hash, {"partner_id": str(partner_id)})

    def revoke(self, token_hash: str) -> None:
        self._call("DELETE", token_hash, None)
