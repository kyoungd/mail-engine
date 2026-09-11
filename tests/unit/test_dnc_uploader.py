"""Phase 5c gate: the partner's uploader client.

The client runs on a sales rep's own laptop under their own SAN. The FTC allows
ONE fetch per file per day, which is the constraint the whole design turns on:
downloading and uploading are separately retryable, and a file already on disk is
never fetched again.
"""

import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from clients.dnc_uploader import (
    Config,
    ConfigError,
    UploadError,
    load_config,
    run,
)

TOKEN = "nmcdnc_test_token"
URL = "https://dnc.example"
NAME = "2026-9-9_818_abc.txt.zip"
FILE_URL = f"https://telemarketing.donotcall.gov/files/{NAME}"


def _zip_bytes(name: str, lines: list[str]) -> bytes:
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(name.removesuffix(".zip"), "".join(f"{line}\n" for line in lines))
    return buffer.getvalue()


GOOD = _zip_bytes(NAME, ["818,5550009"])


class FakePortal:
    """The FTC download service. Records every fetch — the assertion that matters
    is how FEW times it is called."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.fetched: list[str] = []

    def urls(self) -> list[str]:
        return list(self.files)

    def fetch(self, url: str) -> bytes:
        self.fetched.append(url)
        return self.files[url]


def _transport(fail: bool = False):
    calls = []

    def transport(url, headers, path):
        calls.append((url, headers, path.name, path.read_bytes()))
        if fail:
            raise UploadError("worker unreachable")

    return transport, calls


def _config(tmp_path: Path) -> Config:
    return Config(
        org_id="10337886-60999",
        password="secret",
        token=TOKEN,
        upload_url=URL,
        work_dir=tmp_path,
    )


def test_a_file_already_on_disk_is_never_refetched(tmp_path):
    (tmp_path / NAME).write_bytes(GOOD)
    portal = FakePortal({FILE_URL: GOOD})
    transport, _ = _transport()

    report = run(_config(tmp_path), portal=portal, transport=transport)

    assert portal.fetched == []  # the day's one fetch is not spent
    assert report.downloaded == 0
    assert report.uploaded == 1


def test_a_downloaded_file_is_uploaded_with_the_token_and_fetch_time(tmp_path):
    portal = FakePortal({FILE_URL: GOOD})
    transport, calls = _transport()

    report = run(_config(tmp_path), portal=portal, transport=transport)

    assert (report.downloaded, report.uploaded) == (1, 1)
    url, headers, name, body = calls[0]
    assert url == f"{URL}/upload/{NAME}"        # the FTC filename, verbatim
    assert headers["X-API-KEY"] == TOKEN
    assert name == NAME and body == GOOD
    fetched_at = datetime.fromisoformat(headers["X-Fetched-At"])
    assert fetched_at.tzinfo is not None
    assert abs((datetime.now(UTC) - fetched_at).total_seconds()) < 300


def test_a_failed_upload_leaves_the_file_for_the_next_run(tmp_path):
    portal = FakePortal({FILE_URL: GOOD})
    transport, _ = _transport(fail=True)

    report = run(_config(tmp_path), portal=portal, transport=transport)

    assert report.failed == 1 and report.uploaded == 0
    assert (tmp_path / NAME).exists()
    assert not (tmp_path / "uploaded" / NAME).exists()


def test_a_successful_upload_moves_the_file_out_of_the_queue(tmp_path):
    portal = FakePortal({FILE_URL: GOOD})
    transport, calls = _transport()
    run(_config(tmp_path), portal=portal, transport=transport)

    second = run(_config(tmp_path), portal=portal, transport=transport)

    assert (tmp_path / "uploaded" / NAME).exists()
    assert not (tmp_path / NAME).exists()
    assert second.uploaded == 0          # not sent twice
    assert portal.fetched == [FILE_URL]  # and not fetched twice


def test_a_crc_failure_is_never_uploaded(tmp_path):
    corrupt = bytearray(GOOD)
    corrupt[-20:] = b"\x00" * 20
    portal = FakePortal({FILE_URL: bytes(corrupt)})
    transport, calls = _transport()

    report = run(_config(tmp_path), portal=portal, transport=transport)

    assert calls == []  # a file we cannot verify never reaches the bucket
    assert report.uploaded == 0 and report.corrupt == 1


def test_missing_config_refuses_with_a_message_a_salesperson_can_act_on(tmp_path):
    ini = tmp_path / "dnc-uploader.ini"
    ini.write_text(f"[ftc]\norg_id = \npassword = \n[nmc]\ntoken = {TOKEN}\n")

    with pytest.raises(ConfigError) as caught:
        load_config(ini)

    message = str(caught.value)
    assert "dnc-uploader.ini" in message
    assert "org_id" in message and "password" in message


def _ini(tmp_path: Path, nmc: str) -> Path:
    ini = tmp_path / "dnc-uploader.ini"
    ini.write_text(f"[ftc]\norg_id = 10337886-60999\npassword = secret\n{nmc}")
    return ini


def test_the_token_comes_from_the_ini_and_the_worker_url_is_built_in(tmp_path):
    """One universal build (2026-09-11): nothing per-rep is compiled in."""
    config = load_config(_ini(tmp_path, f"[nmc]\ntoken = {TOKEN}\n"))

    assert config.token == TOKEN
    assert config.upload_url == "https://dnc-upload.nevermisscall.workers.dev"
    assert (config.org_id, config.password, config.work_dir) == (
        "10337886-60999", "secret", tmp_path)


def test_an_ini_url_overrides_the_built_in_worker(tmp_path):
    config = load_config(_ini(tmp_path, f"[nmc]\ntoken = {TOKEN}\nurl = {URL}/\n"))

    assert config.upload_url == URL  # local testing against `wrangler dev`


def test_an_ini_without_a_token_says_where_to_get_one(tmp_path):
    """Otherwise the first sign of a missing token is a 401 in the field."""
    with pytest.raises(ConfigError) as caught:
        load_config(_ini(tmp_path, ""))

    message = str(caught.value)
    assert "token" in message and "NeverMissCall" in message
