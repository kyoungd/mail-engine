"""The snapshot-inbox seam: partner-uploaded DNC snapshots waiting to be judged.

A partner's client uploads to a Cloudflare Worker, which authenticates the per-rep
token, derives the object key from it, and writes into R2 through its binding. This
seam is the read side of that: mail-engine never speaks S3 and holds no bucket
credentials — the Worker is the one place that decides who may touch the bucket.

`partner_id` and `claimed_fetched_at` arrive in the LISTING rather than from a file
the uploader wrote: the Worker recorded them when it authenticated the upload, so
they are trusted by construction and there is no sidecar to tamper with.
"""

import json
import shutil
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

KEY_PREFIX = "dnc/"


class InboxError(Exception):
    """The inbox offered something that cannot be trusted — a key outside the
    prefix the Worker is supposed to write, or a listing that will not map."""


@dataclass(frozen=True)
class InboxObject:
    key: str
    partner_id: UUID
    uploaded_at: datetime
    claimed_fetched_at: datetime | None
    size: int


@runtime_checkable
class SnapshotInbox(Protocol):
    """Uploads not yet recorded. Read-only: nothing here deletes or rewrites."""

    def pending(self) -> list[InboxObject]:
        ...

    def fetch(self, key: str, dest: Path) -> Path:
        ...


def _default_transport(
    url: str, headers: dict[str, str], dest: Path | None = None
) -> Any:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=600) as response:
        if dest is None:
            return json.loads(response.read().decode())
        with open(dest, "wb") as handle:
            shutil.copyfileobj(response, handle)
        return dest


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class WorkerSnapshotInbox:
    """The real client, over the upload Worker's admin endpoints."""

    def __init__(
        self,
        base_url: str,
        token: str,
        transport: Callable[..., Any] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.transport = transport or _default_transport

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def pending(self) -> list[InboxObject]:
        payload = self.transport(f"{self.base_url}/pending", self._headers())
        if payload.get("truncated"):
            # Keys sort lexicographically, so a full listing page can hide newer
            # uploads indefinitely. Refusing beats pulling a partial set and
            # reporting success — the silent-shortfall class this whole pipeline
            # is built against.
            raise InboxError(
                "the inbox listing was truncated — refusing a partial pull; "
                "the bucket needs pruning or the lister needs pagination"
            )
        objects = []
        for row in payload["objects"]:
            uploaded_at = _when(row["uploaded_at"])
            if uploaded_at is None:
                raise InboxError(f"{row.get('key')!r}: listing has no uploaded_at")
            if not row.get("partner_id"):
                # A listing that cannot name its uploader is unusable — and it is
                # the shape R2 returns when the Worker forgets to ask for
                # customMetadata. Named error beats a TypeError at 2am.
                raise InboxError(f"{row.get('key')!r}: listing has no partner_id")
            objects.append(
                InboxObject(
                    key=row["key"],
                    partner_id=UUID(row["partner_id"]),
                    uploaded_at=uploaded_at,
                    claimed_fetched_at=_when(row.get("claimed_fetched_at")),
                    size=int(row["size"]),
                )
            )
        return objects

    def fetch(self, key: str, dest: Path) -> Path:
        if not key.startswith(KEY_PREFIX) or ".." in key.split("/"):
            raise InboxError(
                f"{key!r} is outside {KEY_PREFIX} — the Worker writes nowhere else"
            )
        url = f"{self.base_url}/object/{urllib.parse.quote(key)}"
        self.transport(url, self._headers(), dest)
        return dest
