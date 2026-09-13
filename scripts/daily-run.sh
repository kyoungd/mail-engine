#!/usr/bin/env bash
# The production daily run (Architecture B): pull, scrub, and the nightly — in
# that order, stopping at the first failed step. Uploading is NOT part of it
# (operator, 2026-09-13): NMC's uploader, the operator's Windows build and every
# rep upload to the Worker first, and this run consumes whatever is in the inbox.
#
# Replaces scripts/dnc-daily.sh for production: that script scrubs against
# dnc-lists/<date>/ outside the snapshot ledger, and its download spends the same
# once-per-day FTC fetch NMC's uploader needs. Never run it in production.
set -euo pipefail

ENGINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<EOF
usage: scripts/daily-run.sh [-h|--help]

The production daily run, from $ENGINE_DIR:
  1. jobs.dnc_pull      judge each upload in the inbox, land accepted files in dnc-lists/
  2. jobs.dnc_refresh   scrub due contacts, each code against its own snapshot
  3. jobs.nightly_cli   feeds, recompute, expiry, digest, partner reports (last)

Upload FIRST — this run downloads and uploads nothing. NMC's own upload:
  python3 $ENGINE_DIR/clients/dnc_uploader.py --config ~/dnc-uploader-nmc/dnc-uploader.ini
or the same client's Windows build; reps upload from their own machines.
A day with no new upload is safe: the pull finds nothing, the scrub uses each
code's newest recorded list, and a code whose uploads stop drains once its list
is past 31 days old (the nightly's DNC alert fires past 24).

Stops at the first step that fails. Safe to re-run the same day: the pull skips
what is recorded, the scrub skips contacts checked in the last 21 days, and the
nightly dedupes.

Refuses unless .env points at mailengine_prod — this is production's run
(cron policy 2026-08-07: crons live in the production checkout only).

Cron example (after the manual week; the upload first, once the portal's files exist):
  10 7 * * * python3 $ENGINE_DIR/clients/dnc_uploader.py --config \$HOME/dnc-uploader-nmc/dnc-uploader.ini >> ~/dnc-upload.log 2>&1
  40 7 * * * $ENGINE_DIR/scripts/daily-run.sh >> ~/daily-run.log 2>&1
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

step() { echo; echo "=== $(date -Is)  $*"; }

step "1/3 dnc_pull"
PYTHONPATH=. uv run python -m jobs.dnc_pull

step "2/3 dnc_refresh --from-ledger"
PYTHONPATH=. uv run python -m jobs.dnc_refresh --from-ledger

step "3/3 nightly"
PYTHONPATH=. uv run python -m jobs.nightly_cli

step "done"
