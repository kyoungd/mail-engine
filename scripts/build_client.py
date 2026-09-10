"""Bake one sales rep's identity into the uploader client and build the artifact.

One build per rep: the upload token and the Worker URL become constants in the
shipped program, so a rep double-clicks one file and nothing else. Their FTC
credentials are NOT baked — those go in dnc-uploader.ini beside it, and never
leave their machine.

Rebuilding ROTATES the token: only its hash is stored, so a previous token can
never be recovered and a new build necessarily mints a new one. The old token
dies at the edge as part of issuing the new one.

usage: build-client.py --partner NAME [--token TOKEN] [--url URL] [--out DIR]
"""

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "clients" / "dnc_uploader.py"


class BakeError(Exception):
    pass


def bake(source: str, *, token: str, upload_url: str) -> str:
    """Replace the two build-time constants. Refuses rather than producing an
    artifact that would only fail once it is in a rep's hands."""
    if not token or not upload_url:
        raise BakeError("both a token and an upload URL are required")
    if '"' in token or '"' in upload_url:
        raise BakeError("token and URL must not contain quotes")
    baked, token_count = re.subn(
        r'^BAKED_TOKEN = ""$', f'BAKED_TOKEN = "{token}"', source, flags=re.M
    )
    baked, url_count = re.subn(
        r'^BAKED_UPLOAD_URL = ""$', f'BAKED_UPLOAD_URL = "{upload_url}"', baked,
        flags=re.M,
    )
    if token_count != 1 or url_count != 1:
        raise BakeError(
            "did not find exactly one BAKED_TOKEN and one BAKED_UPLOAD_URL to "
            "replace — clients/dnc_uploader.py has changed shape"
        )
    return baked


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build_client.py",
        description="Build one rep's copy of the DNC uploader.",
        epilog=(
            "Examples:\n"
            "  make client PARTNER='Jane Doe'          # issues a token, then builds\n"
            "  scripts/build_client.py --partner 'Jane Doe' --token nmcdnc_… \\\n"
            "      --url https://dnc.nevermisscall.com\n\n"
            "NOTE: PyInstaller does not cross-compile. Run on WINDOWS (or under\n"
            "wine) to produce the .exe a rep can use; a Linux build is only good\n"
            "for testing the bake."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--partner", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", default=str(ROOT / "dist"))
    parser.add_argument(
        "--bake-only", action="store_true",
        help="write the baked source and stop (no PyInstaller)",
    )
    args = parser.parse_args(argv)

    try:
        baked = bake(SOURCE.read_text(), token=args.token, upload_url=args.url)
    except BakeError as exc:
        print(f"build_client: {exc}", file=sys.stderr)
        return 2

    name = f"dnc-uploader-{_slug(args.partner)}"
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as staging:
        source = Path(staging) / f"{name}.py"
        source.write_text(baked)
        if args.bake_only:
            target = out / f"{name}.py"
            target.write_text(baked)
            print(f"baked source: {target}")
            return 0
        result = subprocess.run(
            [
                sys.executable, "-m", "PyInstaller", "--onefile", "--clean",
                "--name", name, "--distpath", str(out),
                "--workpath", str(Path(staging) / "build"),
                "--specpath", staging, str(source),
            ],
            check=False,
        )
        if result.returncode != 0:
            print("build_client: PyInstaller failed", file=sys.stderr)
            return 1

    print(f"\nbuilt: {out / name}")
    print("Send the rep BOTH this program and an dnc-uploader.ini containing:")
    print("  [ftc]\n  org_id = <their Organization ID>\n  password = <their Downloader password>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
