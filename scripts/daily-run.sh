#!/usr/bin/env bash
# The production daily run (Architecture B): NMC's own DNC upload, then pull,
# scrub, and the nightly — in that order, stopping at the first failed step.
#
# Replaces scripts/dnc-daily.sh for production: that script scrubs against
# dnc-lists/<date>/ outside the snapshot ledger, and its download spends the same
# once-per-day FTC fetch step 1 needs. Run one or the other on a given day, never both.
set -euo pipefail

ENGINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLIENT_DIR="${NMC_CLIENT_DIR:-$HOME/dnc-uploader-nmc}"
CLIENT="$CLIENT_DIR/dnc-uploader-young.py"
INI="$CLIENT_DIR/dnc-uploader.ini"

usage() {
  cat <<EOF
usage: scripts/daily-run.sh [-h|--help]

The production daily run, from $ENGINE_DIR:
  1. NMC's uploader     download today's FTC files, upload them to the Worker
  2. jobs.dnc_pull      judge each upload, land accepted files in dnc-lists/
  3. jobs.dnc_refresh   scrub due contacts, each code against its own snapshot
  4. jobs.nightly_cli   feeds, recompute, expiry, digest, partner reports (last)

Stops at the first step that fails. Safe to re-run the same day: the uploader
never re-fetches a file it already has, the pull skips what is recorded, the
scrub skips contacts checked in the last 21 days, and the nightly dedupes.

Refuses unless .env points at mailengine_prod — this is production's run
(cron policy 2026-08-07: crons live in the production checkout only).

Needs NMC's uploader in $CLIENT_DIR (override: NMC_CLIENT_DIR):
  dnc-uploader-young.py   baked with the house row's upload token
  dnc-uploader.ini        NMC's FTC Organization ID + Downloader password
  (docs/dnc-uploader-runbook.md, Part C steps C1-C3)

Cron example (after the manual week; 7:10 AM, once the portal's files exist):
  10 7 * * * $ENGINE_DIR/scripts/daily-run.sh >> ~/daily-run.log 2>&1
EOF
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
  "") ;;
  *) echo "unknown option: $1" >&2; usage; exit 2 ;;
esac

cd "$ENGINE_DIR"
set -a; . ./.env; set +a

db="${OWNER_DATABASE_URL##*/}"
if [ "$db" != "mailengine_prod" ]; then
  echo "daily-run: .env points at '$db', not mailengine_prod — refusing" >&2
  exit 2
fi
for f in "$CLIENT" "$INI"; do
  [ -f "$f" ] || { echo "daily-run: missing $f — set up NMC's uploader first (runbook C1-C3)" >&2; exit 2; }
done

step() { echo; echo "=== $(date -Is)  $*"; }

step "1/4 NMC uploader: download + upload"
python3 "$CLIENT" --config "$INI"

step "2/4 dnc_pull"
PYTHONPATH=. uv run python -m jobs.dnc_pull

step "3/4 dnc_refresh --from-ledger"
PYTHONPATH=. uv run python -m jobs.dnc_refresh --from-ledger

step "4/4 nightly"
PYTHONPATH=. uv run python -m jobs.nightly_cli

step "done"
