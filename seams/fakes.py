"""In-memory seam implementations for testing the jobs without any vendor."""

from pathlib import Path
from datetime import datetime
from uuid import UUID

from seams.snapshot_inbox import InboxObject
from seams.token_registry import TokenRegistryError


class FakeDncRegistry:
    """Programmable `DncRegistry` (design §6/S-9). One version, per-area-code sets
    of 10-digit national numbers. Delisting between runs is modeled by a second
    instance with a newer version and the number absent — exactly how the real
    registry presents it (full-list diff)."""

    def __init__(self, *, version: str, numbers: dict[str, set[str]]) -> None:
        self._version = version
        self._numbers = {code: frozenset(nums) for code, nums in numbers.items()}
        self.calls: list[str] = []

    def version(self) -> str:
        return self._version

    def listed(self, area_code: str, candidates: frozenset[str]) -> frozenset[str]:
        self.calls.append(area_code)
        return candidates & self._numbers.get(area_code, frozenset())


class FakeCloseFeed:
    """Programmable `CloseFeed` (nmc-close-feed-contract.md). Yields the closes it
    was given, filtered by the watermark the consumer passes — re-serving on
    overlap exactly as the real feed does (§4: re-serving is expected and safe)."""

    def __init__(self, closes: list) -> None:
        self._closes = closes
        self.pulls: list[datetime] = []

    def closes(self, since: datetime):
        self.pulls.append(since)
        for close in sorted(self._closes, key=lambda c: (c.recorded_at, c.id)):
            if close.recorded_at > since:
                yield close


class FakeSnapshotInbox:
    """Uploads held in memory. `add` is what a partner's client + the Worker would
    have done; `fetch` writes the bytes wherever the job asks, so the job's file
    handling is exercised for real."""

    def __init__(self) -> None:
        self.objects: list[InboxObject] = []
        self.bodies: dict[str, bytes] = {}

    def add(
        self,
        *,
        key: str,
        partner_id: UUID,
        body: bytes,
        uploaded_at: datetime,
        claimed_fetched_at: datetime | None = None,
    ) -> None:
        self.objects.append(
            InboxObject(
                key=key,
                partner_id=partner_id,
                uploaded_at=uploaded_at,
                claimed_fetched_at=claimed_fetched_at,
                size=len(body),
            )
        )
        self.bodies[key] = body

    def pending(self) -> list[InboxObject]:
        return list(self.objects)

    def fetch(self, key: str, dest: Path) -> Path:
        dest.write_bytes(self.bodies[key])
        return dest


class FakeTokenRegistry:
    """Records what reached the edge, in order — the ordering between the edge and
    the database is the property worth pinning, not just the calls themselves."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str]] = []
        self.published: list[tuple[str, UUID]] = []
        self.revoked: list[str] = []

    def publish(self, token_hash: str, partner_id: UUID) -> None:
        self.calls.append(("publish", token_hash))
        if self.fail:
            raise TokenRegistryError("fake registry unreachable")
        self.published.append((token_hash, partner_id))

    def revoke(self, token_hash: str) -> None:
        self.calls.append(("revoke", token_hash))
        if self.fail:
            raise TokenRegistryError("fake registry unreachable")
        self.revoked.append(token_hash)
