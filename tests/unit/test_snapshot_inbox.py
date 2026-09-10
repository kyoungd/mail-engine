"""The snapshot inbox seam: the Worker's wire contract, auth, and streaming fetch.
Transport is injected — no network.

The Worker is the only thing holding the R2 binding, so it is also the only thing
that knows which partner an object came from: it authenticated the upload token and
derived the key. That is why `partner_id` and `claimed_fetched_at` arrive in the
listing rather than being parsed out of a file the uploader wrote.
"""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from seams.snapshot_inbox import InboxError, WorkerSnapshotInbox

PARTNER = "3f1a5c22-0000-4000-8000-00000000abcd"
LISTING = {
    "objects": [
        {
            "key": f"dnc/{PARTNER}/2026-9-9_818_abc.txt.zip",
            "partner_id": PARTNER,
            "claimed_fetched_at": "2026-09-09T14:02:11+00:00",
            "uploaded_at": "2026-09-09T14:02:40+00:00",
            "size": 4096,
        }
    ]
}


def _inbox(response, body=b""):
    calls = []

    def transport(url, headers, dest=None):
        calls.append((url, headers, dest))
        if dest is not None:
            dest.write_bytes(body)
            return dest
        return response

    return WorkerSnapshotInbox("https://dnc.example", "tok_admin", transport=transport), calls


def test_pending_maps_the_wire_contract():
    inbox, calls = _inbox(LISTING)

    objects = inbox.pending()

    assert len(objects) == 1
    obj = objects[0]
    assert obj.key == f"dnc/{PARTNER}/2026-9-9_818_abc.txt.zip"
    assert obj.partner_id == UUID(PARTNER)
    assert obj.size == 4096
    assert obj.uploaded_at == datetime(2026, 9, 9, 14, 2, 40, tzinfo=UTC)
    assert obj.claimed_fetched_at == datetime(2026, 9, 9, 14, 2, 11, tzinfo=UTC)

    url, headers, _ = calls[0]
    assert url == "https://dnc.example/pending"
    assert headers["Authorization"] == "Bearer tok_admin"


def test_pending_tolerates_a_missing_claimed_fetch_time():
    listing = {"objects": [dict(LISTING["objects"][0])]}
    del listing["objects"][0]["claimed_fetched_at"]
    inbox, _ = _inbox(listing)

    assert inbox.pending()[0].claimed_fetched_at is None


def test_fetch_streams_to_dest_and_returns_the_path(tmp_path):
    inbox, calls = _inbox(None, body=b"zip-bytes")
    dest = tmp_path / "2026-9-9_818_abc.txt.zip"

    got = inbox.fetch(f"dnc/{PARTNER}/2026-9-9_818_abc.txt.zip", dest)

    assert got == dest
    assert dest.read_bytes() == b"zip-bytes"
    url, headers, passed_dest = calls[0]
    assert url.startswith("https://dnc.example/object/")
    assert headers["Authorization"] == "Bearer tok_admin"
    assert passed_dest == dest


def test_a_key_outside_the_dnc_prefix_is_refused(tmp_path):
    inbox, calls = _inbox(None, body=b"x")

    for key in ("../secrets.zip", "other/1.zip", "dnc/../../etc/passwd"):
        with pytest.raises(InboxError):
            inbox.fetch(key, tmp_path / "out.zip")

    assert calls == []


def test_a_truncated_listing_raises_rather_than_pulling_a_partial_set():
    """R2 pages its listing and keys sort lexicographically, so a full page can
    hide newer uploads forever. A partial pull that reports success is exactly the
    silent shortfall this pipeline exists to prevent."""
    inbox, _ = _inbox({**LISTING, "truncated": True})

    with pytest.raises(InboxError):
        inbox.pending()


def test_a_listing_without_a_partner_id_raises():
    """R2 omits customMetadata from list() unless explicitly included — the shape
    a misconfigured Worker returns. Unusable, and it must say so by name."""
    listing = {"objects": [dict(LISTING["objects"][0])]}
    listing["objects"][0]["partner_id"] = None
    inbox, _ = _inbox(listing)

    with pytest.raises(InboxError):
        inbox.pending()
