#!/usr/bin/env bash
# Nightly backup of mailengine_prod (PRD SR-6). Dumps custom-format via pg_dump,
# verifies the archive is readable, rotates old dumps. Read-only against the DB.
#
# The target is ALWAYS mailengine_prod regardless of which checkout runs this —
# credentials come from ./.env's OWNER_DATABASE_URL with the database name
# retargeted, so the dev checkout's cron entry backs up production.
set -euo pipefail

usage() {
    cat <<'EOF'
usage: backup.sh [--dir DIR] [--keep DAYS] [-h|--help]

Nightly pg_dump of mailengine_prod (PRD SR-6).

  --dir DIR    where dumps land (default: ~/db-backups, or $BACKUP_DIR)
  --keep DAYS  delete dumps older than this many days (default: 14, or $BACKUP_KEEP)
  -h, --help   this help

Run from a mail-engine checkout (needs ./.env for OWNER_DATABASE_URL).
Each dump is written to a .tmp file, verified with pg_restore --list, then
renamed — a truncated dump can never overwrite a good one or be mistaken for
one. Cron example (02:10 nightly):

  10 2 * * * cd /home/young/Desktop/Code/nvermisscall/marketing/mail-engine && ./scripts/backup.sh >> ~/db-backups/backup.log 2>&1

NOTE: this is a LOCAL backup. SR-6 asks for offsite; copying $BACKUP_DIR to an
offsite destination is a separate, operator-chosen step.
EOF
}

DIR="${BACKUP_DIR:-$HOME/db-backups}"
KEEP="${BACKUP_KEEP:-14}"
while [ $# -gt 0 ]; do
    case "$1" in
        --dir) DIR="$2"; shift 2 ;;
        --keep) KEEP="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
    esac
done

[ -f ./.env ] || { echo "no ./.env here — run from a mail-engine checkout" >&2; exit 2; }
set -a; . ./.env; set +a
[ -n "${OWNER_DATABASE_URL:-}" ] || { echo "OWNER_DATABASE_URL not in .env" >&2; exit 2; }
PROD_URL="${OWNER_DATABASE_URL%/*}/mailengine_prod"

mkdir -p "$DIR"
STAMP="$(date +%Y-%m-%d_%H%M)"
OUT="$DIR/mailengine_prod-$STAMP.dump"

pg_dump --format=custom --file="$OUT.tmp" "$PROD_URL"
pg_restore --list "$OUT.tmp" > /dev/null
mv "$OUT.tmp" "$OUT"

DELETED=$(find "$DIR" -name 'mailengine_prod-*.dump' -mtime "+$KEEP" -print -delete | wc -l)
COUNT=$(find "$DIR" -name 'mailengine_prod-*.dump' | wc -l)
echo "$(date -Is) backed up mailengine_prod -> $OUT ($(du -h "$OUT" | cut -f1)); rotated $DELETED, $COUNT kept"
