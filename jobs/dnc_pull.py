"""Pull partner-uploaded DNC snapshots and record them (Architecture B, Phase 3).

Runs nightly before the scrub. The job judges nothing itself — `record_snapshot`
owns every verdict; this is the plumbing around it: what has already been judged,
whose upload it is, where an accepted file lands as the scrub's working copy.

An object is judged EXACTLY ONCE: `dnc_snapshots.object_key` is the ledger, so a
rejected upload is not re-judged on the next run either. R2 keeps the bytes of
everything, accepted or not; the local copy exists only so `FileDncRegistry` has a
directory to stream. An accepted object whose local copy is missing is landed
again — never re-judged, and only if its bytes match the sha256 that was judged.
"""

import argparse
import hashlib
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from uuid import UUID

from db.session import transaction
from seams.snapshot_inbox import SnapshotInbox, WorkerSnapshotInbox
from service.dnc_snapshots import record_snapshot

LISTS_ROOT = Path(__file__).resolve().parents[2] / "dnc-lists"


@dataclass
class PullReport:
    pulled: int = 0
    accepted: int = 0
    rejected: int = 0
    relanded: int = 0
    skipped: int = 0
    skips: list[tuple[str, str]] = field(default_factory=list)

    def skip(self, key: str, reason: str) -> None:
        self.skipped += 1
        self.skips.append((key, reason))


def _ledger() -> tuple[set[str], dict[str, tuple[str, date, UUID]], set[UUID]]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("select object_key from dnc_snapshots")
            recorded = {row[0] for row in cur.fetchall()}
            cur.execute(
                "select object_key, sha256, version_date, san_holder_id "
                "from dnc_snapshots where status = 'accepted'"
            )
            accepted = {row[0]: (row[1], row[2], row[3]) for row in cur.fetchall()}
            cur.execute("select id from partners where status = 'active'")
            partners = {row[0] for row in cur.fetchall()}
    return recorded, accepted, partners


def _reland(
    inbox: SnapshotInbox, key: str, judged: tuple[str, date, UUID], lists_root: Path,
    report: PullReport,
) -> None:
    """An accepted snapshot whose working copy is gone: fetch it again and land it,
    but only if these are the bytes that were judged."""
    sha256, version_date, holder = judged
    name = Path(key).name
    destination = lists_root / str(holder) / version_date.isoformat()
    if (destination / name).exists():
        report.skip(key, "already_recorded")
        return
    with tempfile.TemporaryDirectory(dir=lists_root, prefix=".staging-") as staging:
        local = inbox.fetch(key, Path(staging) / name)
        with open(local, "rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != sha256:
                report.skip(key, "sha_mismatch")
                return
        destination.mkdir(parents=True, exist_ok=True)
        local.replace(destination / name)
        report.relanded += 1


def pull_snapshots(inbox: SnapshotInbox, *, lists_root: Path = LISTS_ROOT) -> PullReport:
    """One pass over the inbox. Returns what happened to every object offered."""
    recorded, accepted, partners = _ledger()
    report = PullReport()
    # Staging lives under lists_root so landing is a same-filesystem rename: on the
    # production box the system temp dir is tmpfs and dnc-lists/ is not (EXDEV).
    lists_root.mkdir(parents=True, exist_ok=True)

    for obj in inbox.pending():
        if obj.key in recorded:
            if obj.key in accepted:
                _reland(inbox, obj.key, accepted[obj.key], lists_root, report)
            else:
                report.skip(obj.key, "already_recorded")
            continue
        if obj.partner_id not in partners:
            report.skip(obj.key, "unknown_partner")
            continue

        with tempfile.TemporaryDirectory(dir=lists_root, prefix=".staging-") as staging:
            local = inbox.fetch(obj.key, Path(staging) / Path(obj.key).name)
            outcome = record_snapshot(
                local,
                san_holder_id=obj.partner_id,
                object_key=obj.key,
                uploaded_at=obj.uploaded_at,
                claimed_fetched_at=obj.claimed_fetched_at,
                recorded_by="dnc_pull",
            )
            report.pulled += 1
            if outcome.status == "accepted":
                assert outcome.version_date is not None
                destination = (
                    lists_root / str(obj.partner_id) / outcome.version_date.isoformat()
                )
                destination.mkdir(parents=True, exist_ok=True)
                local.replace(destination / local.name)
                report.accepted += 1
            else:
                report.rejected += 1

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dnc_pull",
        description="Pull partner-uploaded DNC snapshots from the upload Worker and "
        "record each one (Architecture B, Phase 3). Runs nightly, before the scrub.",
        epilog=(
            "Every object is judged exactly once — an upload already in dnc_snapshots\n"
            "is skipped, accepted or rejected. Accepted files land in\n"
            f"{LISTS_ROOT}/<partner>/<version-date>/ as the scrub's working copy.\n\n"
            "Examples:\n"
            "  uv run python -m jobs.dnc_pull\n"
            "  uv run python -m jobs.dnc_pull --lists-root /tmp/snapshots\n\n"
            "Requires SNAPSHOT_INBOX_URL, SNAPSHOT_INBOX_TOKEN and OWNER_DATABASE_URL —\n"
            "make targets source .env; this module does not."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--lists-root", metavar="DIR", default=None,
        help=f"where accepted snapshots land (default {LISTS_ROOT})",
    )
    args = parser.parse_args(argv)

    url = os.environ.get("SNAPSHOT_INBOX_URL", "")
    token = os.environ.get("SNAPSHOT_INBOX_TOKEN", "")
    if not url or not token:
        print("dnc_pull: SNAPSHOT_INBOX_URL and SNAPSHOT_INBOX_TOKEN must be set")
        return 2

    report = pull_snapshots(
        WorkerSnapshotInbox(url, token),
        lists_root=Path(args.lists_root) if args.lists_root else LISTS_ROOT,
    )
    print(
        f"pulled={report.pulled} accepted={report.accepted} "
        f"rejected={report.rejected} relanded={report.relanded} skipped={report.skipped}"
    )
    for key, reason in report.skips:
        print(f"  SKIP  {key}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
