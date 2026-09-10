"""The DNC-registry seam (partner-lead-assignment.md §6/S-9, Phase 2).

Anti-corruption boundary for the FTC national do-not-call registry. The portal at
telemarketing.donotcall.gov serves per-area-code FULL lists under an org
Subscription Account Number (SAN); full-list re-download is the ratified v1,
change lists an optimization. Per the dependency rule, `seams` is imported only
by `jobs` and `service/execution` — the scrub is `jobs/dnc_refresh`;
`assign_batch` never touches this (it reads the columns the scrub wrote).

The registry lives in FILES, never a database table (decisions.md 2026-08-03):
the question is never "what is on the registry?" but "which of MY numbers are?",
so the set held in memory is ours and the portal's file streams past it —
that inversion is why the verb is `listed(candidates)` rather than a
`numbers()` that would hold ~1.5M of their numbers in memory. Snapshots land in
`marketing/dnc-lists/<YYYY-MM-DD>/` via `scripts/dnc-download.py`; the
directory name IS the registry version stamped on every check event.

Format pinned to REAL bytes (first live downloads, 2026-08-05): the Flat full
list is `AAA,NNNNNNN` LF-terminated — comma-delimited area code + 7-digit
local — one number per line, no header, inside the portal's zip. Verified over
all 7,334,547 lines of the five subscribed codes: zero deviations.
"""

import zipfile
import zlib
from pathlib import Path
from typing import Protocol, runtime_checkable


class DncRegistryError(Exception):
    """A snapshot that cannot be trusted end-to-end. Loud on purpose: a silent
    short or misread file under-blocks — marking listed numbers clear and
    putting registered consumers into a partner's sheet."""


@runtime_checkable
class DncRegistry(Protocol):
    """A registry snapshot: one version string, membership by intersection."""

    def version(self) -> str:
        """The registry version this snapshot represents. The scrub stamps it on
        every check event; same version twice must be a no-op (external_id
        dedupe), which is what makes re-runs idempotent."""
        ...

    def listed(self, area_code: str, candidates: frozenset[str]) -> frozenset[str]:
        """Which of MY candidate numbers (10-digit national strings, no +1) are
        on the registry for this area code. Contacts' E.164 phones are stripped
        of the +1 before the call. Raises DncRegistryError rather than ever
        returning an under-count."""
        ...


class FileDncRegistry:
    """The real FTC client's parser half, over one downloaded snapshot
    directory. The zip stays unopened on disk (bytes identical to what the FTC
    served); lines stream through `zipfile`, whose CRC-32 check at end of member
    is the completeness guarantee a truncated plain-text list would not give."""

    def __init__(self, snapshot_dir: Path) -> None:
        self._dir = Path(snapshot_dir)

    def version(self) -> str:
        return self._dir.name

    def listed(self, area_code: str, candidates: frozenset[str]) -> frozenset[str]:
        zips = sorted(self._dir.glob(f"*_{area_code}_*.zip"))
        if len(zips) != 1:
            raise DncRegistryError(
                f"{len(zips) or 'no'} zips for area code {area_code} in "
                f"{self._dir} — refusing to scrub against an "
                f"{'ambiguous' if zips else 'absent'} file"
            )
        prefix = f"{area_code},".encode()
        hits: set[str] = set()
        try:
            with zipfile.ZipFile(zips[0]) as zf:
                with zf.open(zf.infolist()[0]) as member:
                    for lineno, raw in enumerate(member, start=1):
                        line = raw.rstrip(b"\n")
                        if not _pinned_line(line, prefix):
                            raise DncRegistryError(
                                _format_message(zips[0].name, lineno, raw, area_code)
                            )
                        number = area_code + line[4:].decode("ascii")
                        if number in candidates:
                            hits.add(number)
        except (zipfile.BadZipFile, zlib.error, EOFError) as exc:
            raise DncRegistryError(f"{zips[0].name}: corrupt zip ({exc})") from exc
        return frozenset(hits)


def _pinned_line(line: bytes, prefix: bytes) -> bool:
    """The one definition of the pinned full-list format `AAA,NNNNNNN`."""
    return len(line) == 11 and line.startswith(prefix) and line[4:].isdigit()


def _format_message(name: str, lineno: int, raw: bytes, area_code: str) -> str:
    return (
        f"{name} line {lineno}: {raw!r} does not match the pinned format "
        f"{area_code},NNNNNNN"
    )


def validate_and_count(zip_path: Path, area_code: str) -> int:
    """Stream one snapshot zip asserting the pinned format on EVERY line, and return
    the line count. The validation half of `listed()` without the intersection — used
    by record_snapshot, which must judge a file before any contact is scrubbed against
    it. Raises DncRegistryError on the first deviation or a corrupt archive."""
    prefix = f"{area_code},".encode()
    count = 0
    try:
        with zipfile.ZipFile(zip_path) as zf:
            with zf.open(zf.infolist()[0]) as member:
                for lineno, raw in enumerate(member, start=1):
                    line = raw.rstrip(b"\n")
                    if not _pinned_line(line, prefix):
                        raise DncRegistryError(
                            _format_message(zip_path.name, lineno, raw, area_code)
                        )
                    count += 1
    except (zipfile.BadZipFile, zlib.error, EOFError, IndexError) as exc:
        raise DncRegistryError(f"{zip_path.name}: corrupt zip ({exc})") from exc
    return count
