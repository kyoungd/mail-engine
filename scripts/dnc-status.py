#!/usr/bin/env python3
"""Is the DNC area-code subscription live yet?

Filed 2026-08-03 for 5 area codes; the portal said ~1 day and to chase them at 3.
Rather than visiting the site daily, ask the download service directly: log in
with the Downloader credential and call GetURLS. While the subscription is still
pending the service answers "Invalid request." for everything; the moment it is
provisioned, GetURLS returns real download URLs.

Cheap and safe to run often: GetURLS does NOT consume the once-per-day file
download (that is GetDNCFileByUrl, which this script never calls).

Exit codes are meant for cron: 0 = LIVE, 1 = still pending, 2 = error.
"""

import argparse
import re
import sys
import urllib.error
import urllib.request
import xml.sax.saxutils as sx
from pathlib import Path

ENDPOINT = "https://telemarketing.donotcall.gov/DownloadSvc/DownloadSvc.asmx"
NS = "https://telemarketing.donotcall.gov/DownloadSvc/"  # also the SOAPAction prefix
VAULT = Path.home() / ".config/nvermisscall/keys.md"


def _vault_credentials() -> tuple[str, str]:
    text = VAULT.read_text()
    org = re.search(r"Organization ID: `([^`]+)`", text)
    pwd = re.search(r"Downloader Password: `([^`]+)`", text)
    if not (org and pwd):
        raise SystemExit(f"could not read DNC credentials from {VAULT}")
    return org.group(1), pwd.group(1)


def _call(op: str, body: str) -> str:
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
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read().decode()


def _tag(xml: str, name: str) -> str | None:
    match = re.search(rf"<{name}>(.*?)</{name}>", xml, re.S)
    return match.group(1) if match else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dnc-status.py",
        description="Check whether the DNC area-code subscription is provisioned yet.",
        epilog=(
            "Examples:\n"
            "  scripts/dnc-status.py\n"
            "  scripts/dnc-status.py --quiet && echo 'subscription is live'\n\n"
            "Exit codes: 0 = live (URLs returned), 1 = still pending, 2 = error.\n"
            f"Credentials come from {VAULT} (never from the repo)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--quiet", action="store_true", help="print nothing; use the exit code only"
    )
    args = parser.parse_args(argv)

    def say(*parts: object) -> None:
        if not args.quiet:
            print(*parts)

    org, password = _vault_credentials()
    try:
        login = _call(
            "Login",
            f"<strCoID>{sx.escape(org)}</strCoID>"
            f"<strCoPwd>{sx.escape(password)}</strCoPwd>"
            "<userType>Downloader</userType><enumCertify>Agree</enumCertify>",
        )
    except (urllib.error.URLError, TimeoutError) as exc:
        say(f"ERROR  could not reach the download service: {exc}")
        return 2

    code = _tag(login, "code")
    if code != "LoginOK":
        say(f"ERROR  login returned {code} (expected LoginOK)")
        if code == "LoginDisabled":
            say("       account is DISABLED — do not retry; contact the portal.")
        return 2

    token = _tag(login, "value") or ""
    session = f"<strSessionToken>{token}</strSessionToken><strCoID>{sx.escape(org)}</strCoID>"
    urls = re.findall(
        r"<string>(.*?)</string>", _call("GetURLS", f"<fileFormat>Flat</fileFormat>{session}")
    )
    live = [u for u in urls if not u.lower().startswith("invalid")]

    if not live:
        say("PENDING  login OK, but no download URLs yet — the subscription is not")
        say("         provisioned. Filed 2026-08-03; chase the portal if this still")
        say("         says PENDING after 2026-08-06.")
        return 1

    say(f"LIVE  {len(live)} download URL(s) available:")
    for url in live:
        say("  ", url)
    say("")
    say("Next: pull a file and pin the parser to real bytes. Note the once-per-day")
    say("limit (AlreadyDownloadedToday) — save what you fetch into")
    say("marketing/dnc-lists/<YYYY-MM-DD>/ and never re-fetch blindly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
