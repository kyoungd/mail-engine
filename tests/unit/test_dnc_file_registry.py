"""FileDncRegistry — the real FTC client's parser half (decisions.md 2026-08-03,
format settled by the 2026-08-05 real downloads: `AAA,NNNNNNN` LF-terminated
inside the portal's own zip).

Every anomaly is LOUD: a silently short read under-blocks, marking listed
numbers clear and putting registered consumers into a partner's sheet.
"""

import zipfile
from pathlib import Path

import pytest

from seams.dnc_registry import DncRegistry, DncRegistryError, FileDncRegistry
from seams.fakes import FakeDncRegistry

REAL_SNAPSHOT = Path(__file__).resolve().parents[3] / "dnc-lists" / "2026-08-05"


def snapshot(tmp_path, *, lines, name="2026-08-05", zip_name=None, member=None):
    """A snapshot dir holding one portal-shaped zip: <date>_<area>_<guid>.txt.zip."""
    directory = tmp_path / name
    directory.mkdir(exist_ok=True)
    zip_name = zip_name or "2026-8-5_818_ABC123.txt.zip"
    member = member or zip_name.removesuffix(".zip")
    with zipfile.ZipFile(directory / zip_name, "w") as zf:
        zf.writestr(member, "".join(line + "\n" for line in lines))
    return directory


def test_version_is_the_snapshot_directory_name(tmp_path):
    directory = snapshot(tmp_path, lines=["818,0000000"])
    assert FileDncRegistry(directory).version() == "2026-08-05"


def test_listed_returns_exactly_the_candidates_on_the_registry(tmp_path):
    directory = snapshot(tmp_path, lines=["818,0000000", "818,0000818", "818,9999999"])
    hits = FileDncRegistry(directory).listed(
        "818", frozenset({"8180000818", "8185550123", "8189999999"})
    )
    assert hits == frozenset({"8180000818", "8189999999"})


def test_the_fake_still_satisfies_the_protocol():
    fake = FakeDncRegistry(version="v1", numbers={"818": {"8185550001"}})
    assert isinstance(fake, DncRegistry)
    assert fake.listed("818", frozenset({"8185550001", "8185550002"})) == frozenset(
        {"8185550001"}
    )


def test_a_missing_area_code_zip_is_loud_never_an_empty_set(tmp_path):
    directory = snapshot(tmp_path, lines=["818,0000000"])
    with pytest.raises(DncRegistryError, match="805"):
        FileDncRegistry(directory).listed("805", frozenset({"8055550001"}))


def test_two_zips_for_one_area_code_are_ambiguous_and_loud(tmp_path):
    directory = snapshot(tmp_path, lines=["818,0000000"])
    snapshot(tmp_path, lines=["818,1111111"], zip_name="2026-8-5_818_DEF456.txt.zip")
    with pytest.raises(DncRegistryError, match="818"):
        FileDncRegistry(directory).listed("818", frozenset({"8180000000"}))


def test_a_malformed_line_is_loud(tmp_path):
    directory = snapshot(tmp_path, lines=["818,0000000", "8181234567"])  # 10-digit style
    with pytest.raises(DncRegistryError):
        FileDncRegistry(directory).listed("818", frozenset({"8180000000"}))


def test_a_wrong_area_line_is_loud(tmp_path):
    directory = snapshot(tmp_path, lines=["818,0000000", "805,1234567"])
    with pytest.raises(DncRegistryError):
        FileDncRegistry(directory).listed("818", frozenset({"8180000000"}))


def test_a_corrupt_zip_fails_loudly(tmp_path):
    directory = snapshot(tmp_path, lines=[f"818,{n:07d}" for n in range(50_000)])
    path = next(directory.glob("*.zip"))
    corrupted = bytearray(path.read_bytes())
    corrupted[len(corrupted) // 2] ^= 0xFF  # flip one byte mid-payload
    path.write_bytes(bytes(corrupted))
    with pytest.raises(DncRegistryError):
        FileDncRegistry(directory).listed("818", frozenset({"8180000000"}))


@pytest.mark.skipif(
    not REAL_SNAPSHOT.exists(), reason="real 2026-08-05 download not on this machine"
)
def test_the_real_818_download_parses_end_to_end():
    """The pin against real FTC bytes: 1,469,394 lines stream without a single
    format error, and the head numbers observed on download day are hits."""
    hits = FileDncRegistry(REAL_SNAPSHOT).listed(
        "818", frozenset({"8180000000", "8180000818", "8185550123"})
    )
    assert frozenset({"8180000000", "8180000818"}) <= hits
    assert "8185550123" not in hits  # 555-01xx fiction range, absent by reservation
