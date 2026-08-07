#!/usr/bin/env bash
# The daily DNC cycle: download today's files, scrub against the newest snapshot.
# (decisions.md 2026-08-05: daily keeps every check <=1-day-old version and every
# dial <=22 days old — comfortably inside the 31-day safe harbor.)
#
# Both halves are independently safe to re-run: the download skips files already
# on disk (never wastes the once-per-day fetch), and the scrub is a no-op for
# contacts inside the 21-day recheck window.
set -euo pipefail

ENGINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LISTS_DIR="$(cd "$ENGINE_DIR/.." && pwd)/dnc-lists"

usage() {
  cat <<EOF
usage: scripts/dnc-daily.sh [--download-only | --scrub-only]

Runs the daily DNC cycle from $ENGINE_DIR:
  1. scripts/dnc-download.py        fetch any live files not yet on disk
  2. jobs.dnc_refresh --snapshot    scrub against the NEWEST dnc-lists/<date>/

options:
  --download-only   step 1 only
  --scrub-only      step 2 only (uses the newest snapshot already on disk)
  -h, --help        this text

Cron example (7:10 AM daily; the portal generates files by early morning):
  10 7 * * * $ENGINE_DIR/scripts/dnc-daily.sh >> ~/dnc-daily.log 2>&1

Snapshots land in $LISTS_DIR/<YYYY-MM-DD>/ — the directory name is the
registry version stamped on every check event. Credentials come from
~/.config/nvermisscall/keys.md; DB URL from $ENGINE_DIR/.env.
EOF
}

download=true scrub=true
case "${1:-}" in
  -h|--help) usage; exit 0 ;;
  --download-only) scrub=false ;;
  --scrub-only) download=false ;;
  "") ;;
  *) echo "unknown option: $1" >&2; usage; exit 2 ;;
esac

cd "$ENGINE_DIR"

if $download; then
  # exit 1 = nothing new to fetch (e.g. all files already pulled today) — the
  # scrub should still run against what is on disk; exit 2 stays fatal.
  uv run python scripts/dnc-download.py || [ $? -eq 1 ]
fi

if $scrub; then
  newest="$(ls -1d "$LISTS_DIR"/????-??-?? 2>/dev/null | sort | tail -1 || true)"
  if [ -z "$newest" ]; then
    echo "dnc-daily: no snapshot directories under $LISTS_DIR — nothing to scrub" >&2
    exit 1
  fi
  set -a; . ./.env; set +a
  PYTHONPATH=. uv run python -m jobs.dnc_refresh --snapshot "$newest"
fi
