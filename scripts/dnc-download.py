#!/usr/bin/env python3
"""Download the DNC full-list files the subscription makes available.

The portal's direct URLs 404 on plain GET — the file only comes through the
SOAP operation GetDNCFileByUrl(fileUrl, strSessionToken, strCoID), which
returns the zip base64-encoded inside the envelope. Each file may be fetched
once per day (AlreadyDownloadedToday after that), so this script is careful
never to waste a fetch:

  - a URL whose file already exists under marketing/dnc-lists/<date>/ is
    skipped, never re-fetched;
  - the raw SOAP response is written to disk BEFORE any decoding, so a
    parse/decode bug cannot lose the one download the day allows;
  - the zip is saved unopened and CRC-verified by streaming (zipfile
    testzip) — a truncated flat file would silently under-block, so a bad
    CRC is a loud error, not a warning.

Exit codes: 0 = all requested files on disk and CRC-clean, 1 = nothing to
do (no live URLs), 2 = error (including any AlreadyDownloadedToday on a
file we do not already have).
"""

import argparse
import base64
import re
import sys
import urllib.error
import urllib.request
import xml.sax.saxutils as sx
import zipfile
from pathlib import Path

ENDPOINT = "https://telemarketing.donotcall.gov/DownloadSvc/DownloadSvc.asmx"
NS = "https://telemarketing.donotcall.gov/DownloadSvc/"  # also the SOAPAction prefix
VAULT = Path.home() / ".config/nvermisscall/keys.md"
LISTS_ROOT = Path(__file__).resolve().parents[2] / "dnc-lists"


def _vault_credentials() -> tuple[str, str]:
    text = VAULT.read_text()
    org = re.search(r"Organization ID: `([^`]+)`", text)
    pwd = re.search(r"Downloader Password: `([^`]+)`", text)
    if not (org and pwd):
        raise SystemExit(f"could not read DNC credentials from {VAULT}")
    return org.group(1), pwd.group(1)


def _call(op: str, body: str, timeout: int = 90) -> str:
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        f"<soap:Body><{op} xmlns=\"{NS}\">{body}</{op}></soap:Body></soap:Envelope>"
    )
    request = urllib.request.Request(
        ENDPOINT,
        data=envelope.encode(),
        headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": NS + op},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode()


def _tag(xml: str, name: str) -> str | None:
    # find-based, not regex: the <value> payload can be tens of MB of base64
    start = xml.find(f"<{name}>")
    if start < 0:
        return None
    start += len(name) + 2
    end = xml.find(f"</{name}>", start)
    return xml[start:end] if end >= 0 else None


def _date_dir(url: str) -> str:
    """2026-8-5_818_<guid>.txt.zip -> 2026-08-05 (the portal's own file date)."""
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})_", Path(url).name)
    if not match:
        raise SystemExit(f"cannot read a date from {url}")
    y, m, d = match.groups()
    return f"{y}-{int(m):02d}-{int(d):02d}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dnc-download.py",
        description="Fetch the subscription's DNC full-list zips via GetDNCFileByUrl.",
        epilog=(
            "Examples:\n"
            "  scripts/dnc-download.py            # fetch every live file not yet on disk\n"
            "  scripts/dnc-download.py --only 818 # just one area code\n\n"
            f"Files land in {LISTS_ROOT}/<YYYY-MM-DD>/ (the portal's file date), zips\n"
            "kept unopened. Each file downloads once per day — already-present files\n"
            "are skipped, so re-running is safe.\n"
            f"Credentials come from {VAULT} (never from the repo)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--only", metavar="AREA", help="fetch only this area code (e.g. 818)"
    )
    args = parser.parse_args(argv)

    org, password = _vault_credentials()
    try:
        login = _call(
            "Login",
            f"<strCoID>{sx.escape(org)}</strCoID>"
            f"<strCoPwd>{sx.escape(password)}</strCoPwd>"
            "<userType>Downloader</userType><enumCertify>Agree</enumCertify>",
        )
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"ERROR  could not reach the download service: {exc}")
        return 2
    if _tag(login, "code") != "LoginOK":
        print(f"ERROR  login returned {_tag(login, 'code')} (expected LoginOK)")
        return 2
    token = _tag(login, "value") or ""
    session = f"<strSessionToken>{token}</strSessionToken><strCoID>{sx.escape(org)}</strCoID>"

    strings = re.findall(
        r"<string>(.*?)</string>", _call("GetURLS", f"<fileFormat>Flat</fileFormat>{session}")
    )
    # Non-URL strings are per-file service messages, e.g.
    # "714:File was already downloaded Today.Only one download allowed per day per file"
    urls = [s for s in strings if s.lower().startswith("http")]
    for note in (s for s in strings if not s.lower().startswith(("http", "invalid"))):
        print(f"NOTE  {note}")
    if args.only:
        urls = [u for u in urls if Path(u).name.split("_")[1] == args.only]
    if not urls:
        print("NOTHING  no live download URLs" + (f" for {args.only}" if args.only else ""))
        return 1

    failures = 0
    for url in urls:
        name = Path(url).name
        dest_dir = LISTS_ROOT / _date_dir(url)
        dest = dest_dir / name
        if dest.exists():
            print(f"SKIP  {name} already on disk")
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)

        print(f"FETCH {name} ...", flush=True)
        try:
            response = _call(
                "GetDNCFileByUrl",
                f"<fileUrl>{sx.escape(url)}</fileUrl>{session}",
                timeout=1800,
            )
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"ERROR  {name}: {exc}")
            failures += 1
            continue

        code = _tag(response, "code")
        if code != "DownloadOK":
            print(f"ERROR  {name}: service returned {code}")
            if code == "AlreadyDownloadedToday":
                print("       today's fetch is spent and the file is NOT on disk — ")
                print("       if a raw .soap.xml exists beside it, recover from that;")
                print("       otherwise this file must wait until tomorrow.")
            failures += 1
            continue

        # raw first: if anything below throws, the day's one download survives
        raw = dest.with_suffix(dest.suffix + ".soap.xml")
        raw.write_text(response)
        payload = _tag(response, "value")
        if not payload:
            print(f"ERROR  {name}: DownloadOK but no <value> payload; raw kept at {raw}")
            failures += 1
            continue
        dest.write_bytes(base64.b64decode(payload))
        raw.unlink()

        with zipfile.ZipFile(dest) as zf:
            bad = zf.testzip()
            if bad is not None:
                print(f"ERROR  {name}: CRC FAILED on {bad} — do not scrub from this file")
                failures += 1
                continue
            members = ", ".join(
                f"{i.filename} ({i.file_size:,} bytes)" for i in zf.infolist()
            )
        print(f"OK    {dest} — CRC clean: {members}")

    return 2 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
