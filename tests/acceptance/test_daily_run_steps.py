"""The production daily run consumes what is already uploaded (operator, 2026-09-13).

Uploading is its own step — NMC's uploader, the operator's Windows build, or a
rep's — and daily-run.sh only pulls, scrubs and runs the nightly, so every run
starts from the same state: whatever sits in the inbox. The script runs for real
here, from a copy in a scratch tree, with `uv` and `python3` replaced by stubs that
record their arguments: nothing reaches a database, the FTC or the Worker.
"""

import shutil
import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "daily-run.sh"

_STUB = """#!/usr/bin/env bash
echo "@NAME@ $*" >> "$CALLS"
if [ -n "${FAIL_ON:-}" ] && [[ " $* " == *" $FAIL_ON "* ]]; then exit 1; fi
exit 0
"""


def _engine(tmp_path: Path, *, db: str = "mailengine_prod") -> Path:
    """A scratch engine tree: the real script, a .env naming `db` on a port nothing
    listens on, and recording stubs for uv and python3."""
    engine = tmp_path / "engine"
    (engine / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, engine / "scripts" / "daily-run.sh")
    (engine / ".env").write_text(
        f"OWNER_DATABASE_URL=postgresql://nobody@127.0.0.1:1/{db}\n"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("uv", "python3"):
        stub = bin_dir / name
        stub.write_text(_STUB.replace("@NAME@", name))
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return engine


def _nmc_uploader_setup(tmp_path: Path, engine: Path) -> None:
    """What the box has today: NMC's ini and the repo client. Present so the run
    COULD call the uploader — the assertion is that it does not."""
    client_dir = tmp_path / "home" / "dnc-uploader-nmc"
    client_dir.mkdir(parents=True)
    (client_dir / "dnc-uploader.ini").write_text("[ftc]\n")
    (engine / "clients").mkdir()
    (engine / "clients" / "dnc_uploader.py").write_text("")


def _run(tmp_path: Path, engine: Path, *, fail_on: str = "") -> tuple[int, list[str], str]:
    calls = tmp_path / "calls.log"
    env = {
        "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "CALLS": str(calls),
        "FAIL_ON": fail_on,
    }
    done = subprocess.run(
        [str(engine / "scripts" / "daily-run.sh")],
        env=env, capture_output=True, text=True, timeout=60,
    )
    lines = calls.read_text().splitlines() if calls.exists() else []
    return done.returncode, lines, done.stdout + done.stderr


def test_the_run_is_pull_scrub_nightly_and_never_the_uploader(tmp_path):
    engine = _engine(tmp_path)
    _nmc_uploader_setup(tmp_path, engine)

    rc, calls, out = _run(tmp_path, engine)

    assert rc == 0, out
    assert calls == [
        "uv run python -m jobs.dnc_pull",
        "uv run python -m jobs.dnc_refresh --from-ledger",
        "uv run python -m jobs.nightly_cli",
    ]


def test_the_run_needs_no_uploader_setup(tmp_path):
    """A box with no NMC ini — a rep-only day, or the operator uploading from
    Windows — still runs: uploading is not this script's job."""
    engine = _engine(tmp_path)

    rc, calls, out = _run(tmp_path, engine)

    assert rc == 0, out
    assert len(calls) == 3


def test_the_run_stops_at_the_first_failed_step(tmp_path):
    engine = _engine(tmp_path)
    _nmc_uploader_setup(tmp_path, engine)

    rc, calls, _ = _run(tmp_path, engine, fail_on="jobs.dnc_pull")

    assert rc != 0
    assert calls[-1] == "uv run python -m jobs.dnc_pull"


def test_the_run_refuses_a_non_production_env(tmp_path):
    engine = _engine(tmp_path, db="mailengine_dev")

    rc, calls, _ = _run(tmp_path, engine)

    assert rc == 2 and calls == []
