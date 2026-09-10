"""The token-registry seam: how a partner's upload token reaches the Worker.

The Worker cannot read Postgres — that is the point of the architecture — so it
keeps its own hash -> partner map in KV. This seam is the push. Transport is
injected; no network.
"""

from uuid import UUID

import pytest

from seams.token_registry import TokenRegistryError, WorkerTokenRegistry

PARTNER = UUID("3f1a5c22-0000-4000-8000-00000000abcd")
HASH = "a" * 64


def _registry(fail: bool = False):
    calls = []

    def transport(method, url, headers, body=None):
        calls.append((method, url, headers, body))
        if fail:
            raise OSError("worker unreachable")
        return {"ok": True}

    return WorkerTokenRegistry("https://dnc.example", "tok_admin", transport=transport), calls


def test_publish_puts_the_hash_with_the_admin_bearer():
    registry, calls = _registry()

    registry.publish(HASH, PARTNER)

    method, url, headers, body = calls[0]
    assert method == "PUT"
    assert url == f"https://dnc.example/admin/tokens/{HASH}"
    assert headers["Authorization"] == "Bearer tok_admin"
    assert body == {"partner_id": str(PARTNER)}


def test_revoke_deletes_the_hash():
    registry, calls = _registry()

    registry.revoke(HASH)

    method, url, headers, body = calls[0]
    assert method == "DELETE"
    assert url == f"https://dnc.example/admin/tokens/{HASH}"
    assert headers["Authorization"] == "Bearer tok_admin"
    assert body is None


def test_a_transport_error_raises_rather_than_reporting_success():
    registry, _ = _registry(fail=True)

    with pytest.raises(TokenRegistryError):
        registry.publish(HASH, PARTNER)
    with pytest.raises(TokenRegistryError):
        registry.revoke(HASH)
