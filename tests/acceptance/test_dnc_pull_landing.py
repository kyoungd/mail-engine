"""The pull's landing step, pinned after the first production pull (2026-09-10).

On the production box /tmp is tmpfs and dnc-lists/ is ext4, so a file staged in the
system temp dir could not be renamed into place (EXDEV). The row was already committed
as accepted and the job never revisits a recorded object — so 714 and 760 were
stranded: judged, with no working copy for the scrub to read.

Staging therefore happens beside the destination, and an ACCEPTED snapshot whose
working copy is missing is landed again on the next pull — only if its bytes are
the bytes that were judged. Judging still happens exactly once.
"""

import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg

from config.params import HOUSE_PARTNER_ID
from jobs.dnc_pull import pull_snapshots
from seams.fakes import FakeSnapshotInbox

NOW = datetime(2026, 9, 9, 17, 0, tzinfo=UTC)
FULL_818 = [f"818,{2596712 + n}" for n in range(10)]
NAME = "2026-9-9_818_abc.txt.zip"
KEY = f"dnc/{HOUSE_PARTNER_ID}/{NAME}"


def _zip_bytes(name: str, lines: list[str], tmp_path: Path) -> bytes:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name.removesuffix(".zip"), "\n".join(lines) + "\n")
    data = path.read_bytes()
    path.unlink()
    return data


def _inbox(tmp_path: Path) -> FakeSnapshotInbox:
    inbox = FakeSnapshotInbox()
    inbox.add(
        key=KEY,
        partner_id=HOUSE_PARTNER_ID,
        body=_zip_bytes(NAME, FULL_818, tmp_path),
        uploaded_at=NOW,
        claimed_fetched_at=NOW - timedelta(minutes=1),
    )
    return inbox


def _snapshots(owner_url: str) -> list[tuple]:
    with psycopg.connect(owner_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select object_key, status, reject_reason from dnc_snapshots "
                "order by recorded_at"
            )
            return cur.fetchall()


def _landed(lists_root: Path) -> Path:
    return lists_root / str(HOUSE_PARTNER_ID) / "2026-09-09" / NAME


def test_staging_happens_under_the_lists_root(clean_db, tmp_path):
    lists_root = tmp_path / "dnc-lists"
    inbox = _inbox(tmp_path)
    staged: list[Path] = []
    fetch = inbox.fetch

    def recording_fetch(key: str, dest: Path) -> Path:
        staged.append(dest)
        return fetch(key, dest)

    inbox.fetch = recording_fetch
    pull_snapshots(inbox, lists_root=lists_root)

    assert staged and all(lists_root in dest.parents for dest in staged)
    assert _landed(lists_root).exists()


def test_a_missing_working_copy_is_landed_again(clean_db, tmp_path, owner_url):
    lists_root = tmp_path / "dnc-lists"
    inbox = _inbox(tmp_path)
    pull_snapshots(inbox, lists_root=lists_root)
    _landed(lists_root).unlink()  # the 2026-09-10 production state

    report = pull_snapshots(inbox, lists_root=lists_root)

    assert _landed(lists_root).exists()
    assert _landed(lists_root).read_bytes() == inbox.bodies[KEY]
    assert (report.pulled, report.relanded, report.skipped) == (0, 1, 0)
    assert len(_snapshots(owner_url)) == 1  # judged once, not twice


def test_bytes_that_differ_from_the_judged_file_are_never_landed(clean_db, tmp_path):
    lists_root = tmp_path / "dnc-lists"
    inbox = _inbox(tmp_path)
    pull_snapshots(inbox, lists_root=lists_root)
    _landed(lists_root).unlink()
    inbox.bodies[KEY] = _zip_bytes(NAME, FULL_818[:5], tmp_path)  # replaced after judging

    report = pull_snapshots(inbox, lists_root=lists_root)

    assert (KEY, "sha_mismatch") in report.skips
    assert not _landed(lists_root).exists()
    assert report.relanded == 0
    assert list(lists_root.rglob("*.zip")) == []
