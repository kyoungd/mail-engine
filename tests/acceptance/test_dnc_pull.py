"""Phase 3 gate: the pull job — inbox object -> record_snapshot -> working copy.

The job never judges a file itself; record_snapshot does that. What is pinned here
is the plumbing around the verdict: where an accepted file lands, that a rejected
one leaves no working copy (R2 keeps the bytes), that an object is judged exactly
once, and that one bad object cannot take the run down with it.
"""

import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg

from config.params import HOUSE_PARTNER_ID
from jobs.dnc_pull import pull_snapshots
from seams.fakes import FakeSnapshotInbox

NOW = datetime(2026, 9, 9, 17, 0, tzinfo=UTC)
FULL_818 = [f"818,{2596712 + n}" for n in range(10)]


def _zip_bytes(name: str, lines: list[str], tmp_path: Path) -> bytes:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name.removesuffix(".zip"), "\n".join(lines) + "\n")
    data = path.read_bytes()
    path.unlink()
    return data


def _inbox(tmp_path, *, partner: UUID = HOUSE_PARTNER_ID, name="2026-9-9_818_abc.txt.zip",
           lines=None, uploaded_at=NOW):
    inbox = FakeSnapshotInbox()
    inbox.add(
        key=f"dnc/{partner}/{name}",
        partner_id=partner,
        body=_zip_bytes(name, FULL_818 if lines is None else lines, tmp_path),
        uploaded_at=uploaded_at,
        claimed_fetched_at=uploaded_at - timedelta(minutes=1),
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


def test_accepted_object_lands_in_the_snapshot_dir(clean_db, tmp_path, owner_url):
    lists_root = tmp_path / "dnc-lists"

    report = pull_snapshots(_inbox(tmp_path), lists_root=lists_root)

    assert (report.pulled, report.accepted, report.rejected) == (1, 1, 0)
    landed = lists_root / str(HOUSE_PARTNER_ID) / "2026-09-09" / "2026-9-9_818_abc.txt.zip"
    assert landed.exists()
    assert [r[1] for r in _snapshots(owner_url)] == ["accepted"]


def test_already_recorded_object_is_skipped(clean_db, tmp_path, owner_url):
    lists_root = tmp_path / "dnc-lists"
    inbox = _inbox(tmp_path)
    pull_snapshots(inbox, lists_root=lists_root)

    report = pull_snapshots(inbox, lists_root=lists_root)

    assert (report.pulled, report.skipped) == (0, 1)
    assert len(_snapshots(owner_url)) == 1


def test_rejected_object_records_the_row_and_leaves_no_local_file(clean_db, tmp_path, owner_url):
    lists_root = tmp_path / "dnc-lists"
    inbox = _inbox(tmp_path, name="not-an-ftc-name.zip")

    report = pull_snapshots(inbox, lists_root=lists_root)

    assert (report.pulled, report.accepted, report.rejected) == (1, 0, 1)
    assert _snapshots(owner_url)[0][1:] == ("rejected", "bad_filename")
    assert list(lists_root.rglob("*.zip")) == []


def test_unknown_partner_is_skipped_not_recorded(clean_db, tmp_path, owner_url):
    lists_root = tmp_path / "dnc-lists"

    report = pull_snapshots(_inbox(tmp_path, partner=uuid4()), lists_root=lists_root)

    assert (report.pulled, report.skipped) == (0, 1)
    assert report.skips[0][1] == "unknown_partner"
    assert _snapshots(owner_url) == []


def test_one_bad_object_does_not_abort_the_rest(clean_db, tmp_path, owner_url):
    lists_root = tmp_path / "dnc-lists"
    inbox = _inbox(tmp_path, partner=uuid4())
    inbox.add(
        key=f"dnc/{HOUSE_PARTNER_ID}/2026-9-9_818_zzz.txt.zip",
        partner_id=HOUSE_PARTNER_ID,
        body=_zip_bytes("2026-9-9_818_zzz.txt.zip", FULL_818, tmp_path),
        uploaded_at=NOW,
        claimed_fetched_at=NOW,
    )

    report = pull_snapshots(inbox, lists_root=lists_root)

    assert (report.accepted, report.skipped) == (1, 1)
    assert [r[1] for r in _snapshots(owner_url)] == ["accepted"]
