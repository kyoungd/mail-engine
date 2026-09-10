"""Recording a DNC registry snapshot (Architecture B, Phase 2).

A partner downloads the FTC full list under their OWN SAN on their own machine and
uploads it; this verb is what decides whether that file may ever back a verdict. The
scrub (`jobs/dnc_refresh`) reads only snapshots this verb accepted.

Two rules shape the whole module:

  - **A rejection is RECORDED, never raised.** `transaction()` rolls back on any
    exception, so a verb that threw would destroy the row that IS the evidence of
    the refusal. Validation outcomes are the return value; exceptions are reserved
    for programmer error.
  - **Identity comes from the file, never the caller.** Area code, version date and
    the FTC's guid are parsed out of the portal's own filename, so an uploader
    cannot assert what it is sending.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

from config.params import SNAPSHOT_MAX_AGE_DAYS, SNAPSHOT_MIN_LINE_RATIO
from db.session import transaction
from seams.dnc_registry import DncRegistryError, validate_and_count

# The portal's own filename, e.g. 2026-8-5_818_2f3c….txt.zip — its date and guid are
# FTC-generated, which is why they are trusted over anything the uploader claims.
FTC_FILENAME = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})_(\d{3})_([^_/]+)\.txt\.zip$")


@dataclass(frozen=True)
class SnapshotOutcome:
    id: UUID
    status: str
    reject_reason: str | None
    version_date: date | None
    line_count: int | None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record_snapshot(
    zip_path: Path,
    *,
    san_holder_id: UUID,
    object_key: str,
    uploaded_at: datetime,
    claimed_fetched_at: datetime | None = None,
    recorded_by: str = "system",
) -> SnapshotOutcome:
    """Judge one uploaded snapshot and record the verdict. Returns the outcome;
    an already-recorded file returns its existing row unchanged (the pull may
    retry — the FTC allows one download per file per day, so a re-send must never
    cost the partner that fetch)."""
    zip_path = Path(zip_path)
    sha256 = _sha256(zip_path)

    def insert(
        cur,
        *,
        status: str,
        reason: str | None,
        area_code: str | None,
        version_date: date | None,
        file_guid: str | None,
        line_count: int | None,
    ) -> SnapshotOutcome:
        cur.execute(
            "insert into dnc_snapshots (area_code, san_holder_id, version_date, "
            "file_guid, sha256, object_key, line_count, claimed_fetched_at, "
            "uploaded_at, recorded_by, status, reject_reason) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
            (area_code, san_holder_id, version_date, file_guid, sha256, object_key,
             line_count, claimed_fetched_at, uploaded_at, recorded_by, status, reason),
        )
        row = cur.fetchone()
        assert row is not None
        return SnapshotOutcome(row[0], status, reason, version_date, line_count)

    parsed = FTC_FILENAME.match(zip_path.name)
    with transaction() as conn:
        with conn.cursor() as cur:
            if parsed is None:
                return insert(cur, status="rejected", reason="bad_filename",
                              area_code=None, version_date=None, file_guid=None,
                              line_count=None)

            year, month, day, area_code, file_guid = parsed.groups()
            version_date = date(int(year), int(month), int(day))

            def reject(reason: str, line_count: int | None = None) -> SnapshotOutcome:
                return insert(cur, status="rejected", reason=reason,
                              area_code=area_code, version_date=version_date,
                              file_guid=file_guid, line_count=line_count)

            cur.execute(
                "select id, sha256, status, reject_reason, version_date, line_count "
                "from dnc_snapshots where san_holder_id = %s and file_guid = %s",
                (san_holder_id, file_guid),
            )
            seen = cur.fetchone()
            if seen is not None:
                if seen[1] == sha256:
                    return SnapshotOutcome(seen[0], seen[2], seen[3], seen[4], seen[5])
                return reject("duplicate_guid")

            cur.execute(
                "select 1 from dnc_snapshots where san_holder_id = %s and sha256 = %s",
                (san_holder_id, sha256),
            )
            if cur.fetchone() is not None:
                return reject("duplicate_content")

            if (uploaded_at.date() - version_date).days > SNAPSHOT_MAX_AGE_DAYS:
                return reject("stale_file")

            try:
                line_count = validate_and_count(zip_path, area_code)
            except DncRegistryError:
                return reject("bad_format")

            cur.execute(
                "select line_count from dnc_snapshots where area_code = %s "
                "and status = 'accepted' and line_count is not null "
                "order by version_date desc limit 1",
                (area_code,),
            )
            prior = cur.fetchone()
            if prior is not None and line_count < prior[0] * SNAPSHOT_MIN_LINE_RATIO:
                return reject("short_file", line_count)

            return insert(cur, status="accepted", reason=None, area_code=area_code,
                          version_date=version_date, file_guid=file_guid,
                          line_count=line_count)
