#!/usr/bin/env python3
"""The sales partner's DNC uploader — runs on THEIR laptop, under THEIR SAN.

One file, standard library only, so it can be packaged and handed to a
non-technical rep. It does two things and keeps them apart:

  DOWNLOAD  log in to telemarketing.donotcall.gov, fetch whatever full lists the
            rep's own subscription covers, verify each zip's CRC, save it.
  UPLOAD    POST each saved file to NeverMissCall's upload Worker.

They are separately retryable ON PURPOSE. The FTC allows ONE fetch per file per
day, so a failed upload must never cost the rep that fetch: files stay on disk
until an upload succeeds, and a file already on disk is never fetched again.

The rep's FTC credentials live in dnc-uploader.ini beside this program and never
leave their machine. The upload token and Worker URL are baked in at build time,
one build per rep.
"""

import argparse
import base64
import configparser
import json
import re
import shutil
import sys
import urllib.error
import urllib.request
import xml.sax.saxutils as sx
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# Replaced at build time — one build per rep.
BAKED_TOKEN = ""
BAKED_UPLOAD_URL = ""

ENDPOINT = "https://telemarketing.donotcall.gov/DownloadSvc/DownloadSvc.asmx"
NS = "https://telemarketing.donotcall.gov/DownloadSvc/"
UPLOADED = "uploaded"


class ConfigError(Exception):
    """Something the rep can fix, said in words they can act on."""


class UploadError(Exception):
    """The Worker did not take the file. The file stays put."""


class PortalError(Exception):
    """The FTC service refused. Never treated as 'no files'."""


@dataclass(frozen=True)
class Config:
    org_id: str
    password: str
    token: str
    upload_url: str
    work_dir: Path


@dataclass
class Report:
    downloaded: int = 0
    uploaded: int = 0
    failed: int = 0
    corrupt: int = 0
    skipped: int = 0


def load_config(ini_path: Path, *, token: str, upload_url: str) -> Config:
    if not token or not upload_url:
        raise ConfigError(
            "This copy was not set up for a specific rep (no upload token). "
            "Ask NeverMissCall for your own copy — do not share one."
        )
    parser = configparser.ConfigParser()
    if not ini_path.exists():
        raise ConfigError(
            f"{ini_path.name} is missing. Create it next to this program with:\n"
            "  [ftc]\n  org_id = your Organization ID\n  password = your "
            "Downloader password"
        )
    parser.read(ini_path)
    org_id = parser.get("ftc", "org_id", fallback="").strip()
    password = parser.get("ftc", "password", fallback="").strip()
    missing = [n for n, v in (("org_id", org_id), ("password", password)) if not v]
    if missing:
        raise ConfigError(
            f"{ini_path.name} is missing {' and '.join(missing)}. Fill in the "
            "Organization ID and Downloader password from your "
            "telemarketing.donotcall.gov account."
        )
    return Config(
        org_id=org_id,
        password=password,
        token=token,
        upload_url=upload_url.rstrip("/"),
        work_dir=ini_path.parent,
    )


def _tag(xml: str, name: str) -> str | None:
    start = xml.find(f"<{name}>")
    if start < 0:
        return None
    start += len(name) + 2
    end = xml.find(f"</{name}>", start)
    return xml[start:end] if end >= 0 else None


class FtcPortal:
    """The download service, over the same SOAP calls scripts/dnc-download.py
    uses. Duplicated rather than shared: this file ships alone to a machine with
    no repository on it."""

    def __init__(self, org_id: str, password: str) -> None:
        self.org_id = org_id
        self.password = password
        self._session = ""

    def _call(self, op: str, body: str, timeout: int = 1800) -> str:
        envelope = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
            f'<soap:Body><{op} xmlns="{NS}">{body}</{op}></soap:Body></soap:Envelope>'
        )
        request = urllib.request.Request(
            ENDPOINT,
            data=envelope.encode(),
            headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": NS + op},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode()

    def _login(self) -> str:
        if self._session:
            return self._session
        answer = self._call(
            "Login",
            f"<strCoID>{sx.escape(self.org_id)}</strCoID>"
            f"<strCoPwd>{sx.escape(self.password)}</strCoPwd>"
            "<userType>Downloader</userType><enumCertify>Agree</enumCertify>",
            timeout=90,
        )
        if _tag(answer, "code") != "LoginOK":
            raise PortalError(
                "The registry refused your login. Check org_id and password in "
                "dnc-uploader.ini."
            )
        token = _tag(answer, "value") or ""
        self._session = (
            f"<strSessionToken>{token}</strSessionToken>"
            f"<strCoID>{sx.escape(self.org_id)}</strCoID>"
        )
        return self._session

    def urls(self) -> list[str]:
        session = self._login()
        answer = self._call("GetURLS", f"<fileFormat>Flat</fileFormat>{session}", 90)
        strings = re.findall(r"<string>(.*?)</string>", answer)
        for note in (s for s in strings if not s.lower().startswith(("http", "invalid"))):
            print(f"  note from the registry: {note}")
        return [s for s in strings if s.lower().startswith("http")]

    def fetch(self, url: str) -> bytes:
        session = self._login()
        answer = self._call(
            "GetDNCFileByUrl", f"<fileUrl>{sx.escape(url)}</fileUrl>{session}"
        )
        code = _tag(answer, "code")
        if code != "DownloadOK":
            raise PortalError(f"the registry returned {code} for {Path(url).name}")
        payload = _tag(answer, "value")
        if not payload:
            raise PortalError(f"{Path(url).name}: no file in the reply")
        return base64.b64decode(payload)


def _default_transport(url: str, headers: dict[str, str], path: Path) -> None:
    with open(path, "rb") as handle:
        request = urllib.request.Request(
            url, data=handle.read(), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                json.loads(response.read().decode() or "{}")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise UploadError(str(exc)) from exc


def _crc_ok(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            return zf.testzip() is None
    except (zipfile.BadZipFile, OSError):
        return False


def _download(config: Config, portal, report: Report) -> None:
    done = config.work_dir / UPLOADED
    for url in portal.urls():
        name = Path(url).name
        if (config.work_dir / name).exists() or (done / name).exists():
            report.skipped += 1
            continue  # the day's one fetch for this file is not spent again
        (config.work_dir / name).write_bytes(portal.fetch(url))
        report.downloaded += 1
        print(f"  downloaded {name}")


def _upload(config: Config, transport, report: Report) -> None:
    done = config.work_dir / UPLOADED
    for path in sorted(config.work_dir.glob("*.zip")):
        if not _crc_ok(path):
            report.corrupt += 1
            print(f"  {path.name} is damaged and was NOT sent — delete it and re-run")
            continue
        fetched_at = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
        try:
            transport(
                f"{config.upload_url}/upload/{path.name}",
                {
                    "X-API-KEY": config.token,
                    "X-Fetched-At": fetched_at,
                    "Content-Type": "application/zip",
                },
                path,
            )
        except UploadError as exc:
            report.failed += 1
            print(f"  could not send {path.name} ({exc}) — it will go next time")
            continue
        done.mkdir(exist_ok=True)
        shutil.move(str(path), str(done / path.name))
        report.uploaded += 1
        print(f"  sent {path.name}")


def run(config: Config, *, portal, transport) -> Report:
    """Download whatever is new, then send whatever is waiting."""
    report = Report()
    _download(config, portal, report)
    _upload(config, transport, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dnc-uploader",
        description="Download your Do-Not-Call lists and send them to NeverMissCall.",
        epilog=(
            "Run this once a day. It is safe to run again at any time: files\n"
            "already downloaded are never downloaded twice, and anything that\n"
            "failed to send is sent on the next run.\n\n"
            "Setup: put your Organization ID and Downloader password in\n"
            "dnc-uploader.ini, next to this program:\n"
            "  [ftc]\n"
            "  org_id = 10337886-60999\n"
            "  password = your downloader password\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config", metavar="FILE", default=None,
        help="path to dnc-uploader.ini (default: beside this program)",
    )
    args = parser.parse_args(argv)

    here = Path(sys.argv[0]).resolve().parent
    ini = Path(args.config) if args.config else here / "dnc-uploader.ini"
    try:
        config = load_config(ini, token=BAKED_TOKEN, upload_url=BAKED_UPLOAD_URL)
    except ConfigError as exc:
        print(f"Setup needed:\n{exc}")
        return 2

    print("Checking the Do-Not-Call registry...")
    try:
        report = run(
            config, portal=FtcPortal(config.org_id, config.password),
            transport=_default_transport,
        )
    except PortalError as exc:
        print(f"The registry could not be reached: {exc}")
        return 2

    print(
        f"\nDone. downloaded {report.downloaded}, sent {report.uploaded}, "
        f"waiting {report.failed}, already had {report.skipped}"
    )
    if report.corrupt:
        print(f"{report.corrupt} damaged file(s) were not sent.")
    return 1 if (report.failed or report.corrupt) else 0


if __name__ == "__main__":
    sys.exit(main())
