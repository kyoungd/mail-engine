"""Phase 2 gate: record_snapshot — the six checks, per-holder identity, and the
rule that a rejection is RECORDED, never raised.

A rejection cannot raise: `with transaction()` rolls back on any exception, so a
verb that threw would destroy the very row that is the evidence of the refusal.
"""

import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

import psycopg

from config.params import HOUSE_PARTNER_ID
from service.dnc_snapshots import record_snapshot

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "dnc"
NOW = datetime(2026, 9, 9, 17, 0, tzinfo=UTC)

FULL_818 = [f"818,{2596712 + n}" for n in range(10)]
SHORT_818 = FULL_818[:3]


def _zip(tmp_path, name: str, lines: list[str]) -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name.removesuffix(".zip"), "\n".join(lines) + "\n")
    return path


def _record(path: Path, *, holder: UUID = HOUSE_PARTNER_ID, uploaded_at=NOW):
    return record_snapshot(
        path,
        san_holder_id=holder,
        object_key=f"dnc/{holder}/{path.name}",
        uploaded_at=uploaded_at,
        claimed_fetched_at=uploaded_at,
        recorded_by="test",
    )


def _rows(owner_url: str) -> list[tuple]:
    with psycopg.connect(owner_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select area_code, san_holder_id, version_date, file_guid, "
                "line_count, status, reject_reason from dnc_snapshots "
                "order by recorded_at"
            )
            return cur.fetchall()


def _other_partner(owner_url: str) -> UUID:
    with psycopg.connect(owner_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into partners (name, status) values ('Snapshot Partner', 'active') "
                "on conflict (name) do update set status = 'active' returning id"
            )
            row = cur.fetchone()
            assert row is not None
        conn.commit()
        return row[0]


def test_accepts_a_well_formed_snapshot(clean_db, tmp_path, owner_url):
    out = _record(_zip(tmp_path, "2026-9-9_818_abc.txt.zip", FULL_818))

    assert out.status == "accepted"
    assert out.reject_reason is None
    assert out.version_date == date(2026, 9, 9)
    assert out.line_count == 10

    rows = _rows(owner_url)
    assert len(rows) == 1
    area_code, holder, version_date, guid, line_count, status, _ = rows[0]
    assert (area_code, guid, line_count, status) == ("818", "abc", 10, "accepted")
    assert holder == HOUSE_PARTNER_ID
    assert version_date == date(2026, 9, 9)


def test_a_rejection_is_recorded_not_raised(clean_db, tmp_path, owner_url):
    out = _record(_zip(tmp_path, "not-an-ftc-name.zip", FULL_818))

    assert out.status == "rejected"
    assert out.reject_reason == "bad_filename"
    rows = _rows(owner_url)
    assert len(rows) == 1 and rows[0][5] == "rejected"


def test_same_guid_different_bytes_is_the_relabel_case(clean_db, tmp_path, owner_url):
    _record(_zip(tmp_path, "2026-9-9_818_abc.txt.zip", FULL_818))
    (tmp_path / "2026-9-9_818_abc.txt.zip").unlink()
    out = _record(_zip(tmp_path, "2026-9-9_818_abc.txt.zip", FULL_818 + ["818,9999999"]))

    assert out.status == "rejected"
    assert out.reject_reason == "duplicate_guid"
    assert [r[5] for r in _rows(owner_url)] == ["accepted", "rejected"]


def test_same_guid_same_bytes_is_idempotent(clean_db, tmp_path, owner_url):
    first = _record(_zip(tmp_path, "2026-9-9_818_abc.txt.zip", FULL_818))
    second = _record(tmp_path / "2026-9-9_818_abc.txt.zip")

    assert second.id == first.id
    assert second.status == "accepted"
    assert len(_rows(owner_url)) == 1


def test_rejects_a_file_dated_before_the_freshness_window(clean_db, tmp_path, owner_url):
    out = _record(
        _zip(tmp_path, "2026-9-9_818_abc.txt.zip", FULL_818),
        uploaded_at=NOW + timedelta(days=3),
    )

    assert out.status == "rejected"
    assert out.reject_reason == "stale_file"


def test_rejects_a_change_list_masquerading_as_a_full_list(clean_db, tmp_path, owner_url):
    lines = (FIXTURES / "dnc-change-818-sample.txt").read_text().splitlines()
    out = _record(_zip(tmp_path, "2026-9-9_818_abc.txt.zip", lines))

    assert out.status == "rejected"
    assert out.reject_reason == "bad_format"


def test_rejects_a_line_count_far_below_the_prior_snapshot(clean_db, tmp_path, owner_url):
    _record(_zip(tmp_path, "2026-9-8_818_aaa.txt.zip", FULL_818),
            uploaded_at=NOW - timedelta(days=1))
    out = _record(_zip(tmp_path, "2026-9-9_818_bbb.txt.zip", SHORT_818))

    assert out.status == "rejected"
    assert out.reject_reason == "short_file"


def test_identical_bytes_from_a_different_holder_are_accepted(clean_db, tmp_path, owner_url):
    other = _other_partner(owner_url)
    _record(_zip(tmp_path, "2026-9-9_818_abc.txt.zip", FULL_818))
    out = _record(tmp_path / "2026-9-9_818_abc.txt.zip", holder=other)

    assert out.status == "accepted"
    assert len(_rows(owner_url)) == 2
