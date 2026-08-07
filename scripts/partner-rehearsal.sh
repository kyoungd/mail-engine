#!/usr/bin/env bash
# partner-rehearsal.sh — the C3 dress rehearsal, run BY HAND against the LOCAL stack.
#
# The story, end to end, on disposable data:
#   a sales partner signs up → gets 200 contacts in one area code (818) →
#   someone makes a purchase → the operator credits the partner → the nightly
#   runs and a REAL EMAIL reports the batch, the credited close, and the demo line.
#
# Everything runs the real front doors (partners_cli, subscribe_area_codes,
# dnc_refresh --fake, assignment_cli, nightly_cli) against mailengine_dev, the
# local medusa_nmc, and the local booking-system on :3002. Real SMTP sends.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"   # nvermisscall/
ME="$ROOT/marketing/mail-engine"
PARTNER="Rehearsal Partner"
AREA=818
BATCH=200
KEY=rehearsal-b1
CUSTOMER_ID=cus_rehearsal_1
REPORT_EMAIL="${REPORT_EMAIL:-young@nevermisscall.com}"
EXPORT_CSV=/tmp/rehearsal-leads.csv

usage() {
  cat <<EOF
Usage: scripts/partner-rehearsal.sh <step|all>

Steps, in story order:
  check      prerequisites: dev DB, local medusa_nmc, booking-system :3002, creds
  partner    sign up "$PARTNER" (email -> \$REPORT_EMAIL, sales_rep_id 3)
  subscribe  record DNC area code $AREA + fake-registry scrub (stamps freshness)
  assign     give the partner $BATCH contacts (gates limit them to $AREA)
  export     write the partner's working CSV -> $EXPORT_CSV
  purchase   an assigned contact "buys": customer + attribution rows in medusa_nmc
  credit     the operator credits the partner: attribution.sold_by = 3
  nightly    print the PREDICTED email, then run the real nightly (REAL SMTP SEND)
  verify     check every DB effect against the prediction
  clean      remove rehearsal rows + print the canonical re-ingest commands
  all        run check..verify in order, pausing before each step

The rehearsal fakes the DNC scrub (--fake). For a REAL partner, get the real
list first: log in at https://telemarketing.donotcall.gov (org SAN), add the
area code (first 5 free, then \$82/code/year), download the full list, THEN
subscribe_area_codes add + dnc_refresh. Details:
  uv run python -m jobs.subscribe_area_codes --help

Env overrides: REPORT_EMAIL (default young@nevermisscall.com),
SMTP_PASS (default: read from phone-gateway/.env — PRD § Gmail SMTP).
Examples:
  scripts/partner-rehearsal.sh all
  scripts/partner-rehearsal.sh nightly
  REPORT_EMAIL=me@example.com scripts/partner-rehearsal.sh partner
EOF
}

env_me() { cd "$ME"; set -a; . ./.env; set +a; }
psql_me() { psql "$OWNER_DATABASE_URL" -qtA "$@" 2>/dev/null; }
medusa_url() {  # website/.env DATABASE_URL, query-params stripped for psql
  local url; url=$(grep -m1 '^DATABASE_URL=' "$ROOT/website/.env" | cut -d= -f2- | tr -d '"')
  echo "${url%%\?*}"
}

step_check() {
  env_me
  psql_me -c "select 1" >/dev/null && echo "OK  mailengine_dev reachable"
  psql "$(medusa_url)" -qtAc "select 1" >/dev/null && echo "OK  local medusa_nmc reachable"
  [ -n "${MEDUSA_READONLY_URL:-}" ] && echo "OK  MEDUSA_READONLY_URL set (close feed will run)"
  curl -sf http://localhost:3002/health >/dev/null && echo "OK  booking-system :3002 up" \
    || { echo "FAIL booking-system not running on :3002 — start the local stack"; exit 1; }
  grep -q '^NMC_API_KEY=' "$ROOT/booking-system/.env" && echo "OK  local NMC_API_KEY readable"
  [ -n "${SMTP_PASS:-}" ] || grep -q '^SMTP_PASS=' "$ROOT/phone-gateway/.env" \
    && echo "OK  SMTP_PASS available" || echo "WARN SMTP_PASS not found — nightly will refuse"
  echo "contacts in dev: $(psql_me -c 'select count(*) from contacts')"
}

step_partner() {
  env_me
  uv run python -m jobs.partners_cli set "$PARTNER" --channel email \
    --channel-address "$REPORT_EMAIL" --sales-rep-id 3
  uv run python -m jobs.partners_cli list
}

step_subscribe() {
  env_me
  uv run python -m jobs.subscribe_area_codes add $AREA
  echo "scrubbing every $AREA contact against the fake registry (no hits) — may take a few minutes..."
  uv run python -m jobs.dnc_refresh --fake rehearsal-v1
}

step_assign() {
  env_me
  uv run python -m jobs.assignment_cli assign "$PARTNER" --key $KEY --rule '{}' --count $BATCH
  echo "holdings: $(psql_me -c "select count(*) from contacts c join partners p on p.id = c.owner_id where p.name = '$PARTNER'") (expect $BATCH, all $AREA)"
  echo "non-$AREA holdings: $(psql_me -c "select count(*) from contacts c join partners p on p.id = c.owner_id where p.name = '$PARTNER' and substring(c.phone_e164 from 3 for 3) <> '$AREA'") (expect 0)"
}

step_export() {
  env_me
  uv run python -m jobs.assignment_cli export "$PARTNER" -o $EXPORT_CSV
  echo "rows (incl. header): $(wc -l < $EXPORT_CSV)"; head -3 $EXPORT_CSV
}

step_purchase() {
  env_me
  local pick phone name
  pick=$(psql_me -c "select c.phone_e164 || '|' || coalesce(c.business_name,'') from contacts c
                     join partners p on p.id = c.owner_id where p.name = '$PARTNER' order by c.id limit 1")
  phone=${pick%%|*}; name=${pick#*|}
  echo "the buyer: $name ($phone) — an ASSIGNED contact, so the close must phone-match"
  psql "$(medusa_url)" -q <<SQL
insert into customer (id, email, has_account, created_at, updated_at, metadata)
values ('$CUSTOMER_ID', 'rehearsal-buyer@nevermisscall.com', false, now(), now(),
        jsonb_build_object('business_phone', '$phone', 'nmc_subscription_status', 'active'))
on conflict (id) do nothing;
insert into nmc_sales_attribution (customer_id, source, signed_up_via)
select '$CUSTOMER_ID', 'rehearsal', 'rehearsal'
where not exists (select 1 from nmc_sales_attribution where customer_id = '$CUSTOMER_ID');
SQL
  echo "purchase recorded (attribution sold_by is NULL — not yet credited)"
}

step_credit() {
  psql "$(medusa_url)" -c "update nmc_sales_attribution set sold_by = 3 where customer_id = '$CUSTOMER_ID'"
  echo "credited: sold_by = 3 (rep 3 = $PARTNER)"
}

step_nightly() {
  env_me
  local window
  window=$(uv run python -c "
import os,psycopg
with psycopg.connect(os.environ['MEDUSA_READONLY_URL']) as c:
    with c.cursor() as cur:
        cur.execute(\"select count(*) from customer where created_at > now() - interval '45 days'\")
        print(cur.fetchone()[0])")
  cat <<EOF
================ PREDICTION (check the email against this) ================
feeds line:      posthog only (lob deliberately unset for this run)
close feed:      ~$window mirror customers ingest; ONLY the credited one shows in the report
email to:        $REPORT_EMAIL   subject: Your NeverMissCall partner report — $(date +%F)
  Your list
    ~90 days left on your earliest batch
    - assigned $BATCH contacts on $(date +%F), expires $(date -d "+90 days" +%F)
    Contacts currently yours: $((BATCH-1))   <- the buyer left via won-termination
    Removed since your last report: 0 opted out, 1 reclaimed, 0 expired
    Your last export was generated $(date +%F) (0 days ago)
    Re-pull your sheet before your next calling session.
  Closes credited since your last report: 1
    - <the buyer's business name> ($(date +%F))
    Total closes to date: 1
  On your demo line since your last report: 7 calls (2 unique prospects, 0 from blocked numbers), 1 text forwarded
(a second email — the house digest — may also arrive; that is the judgment job, fine)
===========================================================================
EOF
  read -rp "run the nightly now? [y/N] " go; [ "${go:-n}" = y ] || { echo "aborted"; return 1; }
  SMTP_PASS="${SMTP_PASS:-$(grep -m1 '^SMTP_PASS=' "$ROOT/phone-gateway/.env" | cut -d= -f2- | tr -d '"')}"
  [ -n "$SMTP_PASS" ] || { echo "SMTP_PASS unavailable — see --help"; exit 1; }
  LOB_API_KEY= \
  SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_USER=young@nevermisscall.com \
  SMTP_PASS="$SMTP_PASS" SMTP_FROM="NeverMissCall <young@nevermisscall.com>" \
  NMC_BOOKING_URL=http://localhost:3002 \
  NMC_API_KEY="$(grep -m1 '^NMC_API_KEY=' "$ROOT/booking-system/.env" | cut -d= -f2- | tr -d '"')" \
  uv run python -m jobs.nightly_cli
}

step_verify() {
  env_me
  local pid
  pid=$(psql_me -c "select id from partners where name = '$PARTNER'")
  echo "credited close event:   $(psql_me -c "select count(*) from events where type='signup.completed' and (payload->>'sold_by')::bigint = 3") (expect 1)"
  echo "buyer stage:            $(psql_me -c "select c.stage_snapshot from events e join contacts c on c.id=e.contact_id where e.type='signup.completed' and (e.payload->>'sold_by')::bigint=3") (expect won)"
  echo "buyer back at house:    $(psql_me -c "select count(*) from events e join contacts c on c.id=e.contact_id where e.type='signup.completed' and (e.payload->>'sold_by')::bigint=3 and c.owner_id='00000000-0000-4000-8000-000000000001'") (expect 1)"
  echo "holdings now:           $(psql_me -c "select count(*) from contacts where owner_id='$pid'") (expect $((BATCH-1)))"
  echo "report stamped:         $(psql_me -c "select (last_report_at is not null) from partners where id='$pid'") (expect t)"
  echo "watermark set:          $(psql_me -c "select count(*) from feed_watermarks where feed_name='nmc_closes'") (expect 1)"
  echo "total closes ingested:  $(psql_me -c "select count(*) from events where type='signup.completed'")"
}

step_clean() {
  env_me
  psql "$(medusa_url)" -c "delete from nmc_sales_attribution where customer_id = '$CUSTOMER_ID'" \
                      -c "delete from customer where id = '$CUSTOMER_ID'"
  uv run python -m jobs.assignment_cli reclaim "$PARTNER" --reason "rehearsal over" || true
  psql_me -c "delete from partners where name = '$PARTNER'" >/dev/null || true
  rm -f $EXPORT_CSV
  cat <<'EOF'
Medusa rehearsal rows removed; partner reclaimed + deleted.
mailengine_dev still holds rehearsal events/batches/subscriptions — restore canonical with:
  cd marketing/mail-engine && set -a && . ./.env && set +a && uv run python - <<'PY'
import os, psycopg
with psycopg.connect(os.environ['OWNER_DATABASE_URL']) as conn:
    with conn.cursor() as cur:
        cur.execute("truncate activation, events, pieces, waves, variants, contacts, "
                    "intake_cslb_ca, intake_fbn_ca, contact_merge_map, assignment_batches, "
                    "feed_watermarks, suppression_tombstones, dnc_subscriptions restart identity cascade")
    conn.commit()
from service.contacts import load_list
print(load_list('../ingestion-app-1/cslb-all.csv', source='cslb-ca'))
print(load_list('../ingestion-app-1/fbn-ca-2026.csv', source='fbn-ca-2026'))
PY
EOF
}

main() {
  case "${1:-}" in
    -h|--help|"") usage ;;
    check|partner|subscribe|assign|export|purchase|credit|nightly|verify|clean)
      "step_$1" ;;
    all)
      for s in check partner subscribe assign export purchase credit nightly verify; do
        echo; read -rp "── next: $s — press enter (or Ctrl-C to stop) ──" _
        "step_$s"
      done ;;
    *) echo "unknown step: $1"; usage; exit 2 ;;
  esac
}
main "$@"
