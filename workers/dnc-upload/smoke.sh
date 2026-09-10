#!/usr/bin/env bash
# Ten assertions against the upload Worker running locally (workerd via
# `wrangler dev --local`, with simulated R2 + KV). Not part of make test /
# make e2e / make integration — a Worker sits outside all three tiers, and
# promoting this into `make integration` would mean amending that tier's
# read-only contract, which is an operator decision.
#
# usage: workers/dnc-upload/smoke.sh [--port N] [-h|--help]
#
# Requires node + npx (wrangler is fetched on demand). Writes a throwaway
# .dev.vars for the local admin token; local state lives under .wrangler/.
set -uo pipefail

PORT=8787
case "${1:-}" in
  -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
  --port) PORT="$2" ;;
esac

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="http://127.0.0.1:$PORT"
ADMIN=smoke-admin-token
TOKEN=nmcdnc_smoke_partner_token
PARTNER=3f1a5c22-0000-4000-8000-00000000abcd
FILE=2026-9-9_818_smoke.txt.zip
pass=0; fail=0

check() { # check <name> <expected> <actual>
  if [ "$2" = "$3" ]; then pass=$((pass+1)); echo "  ok    $1"
  else fail=$((fail+1)); echo "  FAIL  $1: expected $2, got $3"; fi
}

cd "$HERE"
printf 'ADMIN_TOKEN=%s\n' "$ADMIN" > .dev.vars
rm -rf .wrangler/state

npx --yes wrangler@4 dev --local --port "$PORT" >/tmp/dnc-worker.log 2>&1 &
WORKER_PID=$!
trap 'kill $WORKER_PID 2>/dev/null; wait $WORKER_PID 2>/dev/null' EXIT

for _ in $(seq 1 60); do
  curl -sf -o /dev/null "$BASE/pending" -H "Authorization: Bearer $ADMIN" && break
  sleep 1
done

code() { curl -s -o /tmp/dnc-body -w '%{http_code}' "$@"; }
TOKEN_HASH=$(printf '%s' "$TOKEN" | sha256sum | cut -d' ' -f1)
BODY=/tmp/dnc-payload.zip
head -c 2048 /dev/urandom > "$BODY"

echo "upload auth"
check "unknown partner token is refused" 401 \
  "$(code -X POST "$BASE/upload/$FILE" -H "X-API-KEY: nope" --data-binary @"$BODY")"

check "admin bearer alone cannot upload" 401 \
  "$(code -X POST "$BASE/upload/$FILE" -H "Authorization: Bearer $ADMIN" --data-binary @"$BODY")"

code -X PUT "$BASE/admin/tokens/$TOKEN_HASH" -H "Authorization: Bearer $ADMIN" \
  -H 'content-type: application/json' -d "{\"partner_id\":\"$PARTNER\"}" >/dev/null

echo "upload"
check "a valid token uploads" 201 \
  "$(code -X POST "$BASE/upload/$FILE" -H "X-API-KEY: $TOKEN" \
      -H "X-Fetched-At: 2026-09-09T14:02:11+00:00" --data-binary @"$BODY")"
check "the key is derived from the token" "\"key\":\"dnc/$PARTNER/$FILE\"" \
  "$(tr -d ' ' < /tmp/dnc-body | grep -o "\"key\":\"[^\"]*\"")"

check "a traversal filename is refused" 400 \
  "$(code -X POST "$BASE/upload/..%2Fescape.zip" -H "X-API-KEY: $TOKEN" --data-binary @"$BODY")"

# A real oversized body, not a lied-about content-length: curl would block
# forever waiting to send bytes it does not have.
head -c 68000000 /dev/zero > /tmp/dnc-big
check "an oversized body is refused" 413 \
  "$(code -X POST "$BASE/upload/big.zip" -H "X-API-KEY: $TOKEN" \
      --data-binary @/tmp/dnc-big)"
rm -f /tmp/dnc-big
echo "admin"
check "/pending needs the admin token" 401 "$(code "$BASE/pending")"

check "/pending lists the upload" "$PARTNER" \
  "$(code "$BASE/pending" -H "Authorization: Bearer $ADMIN" >/dev/null; \
     grep -o "\"partner_id\":\"[^\"]*\"" /tmp/dnc-body | head -1 | cut -d'"' -f4)"
check "/pending carries the attestation" "2026-09-09T14:02:11+00:00" \
  "$(grep -o '"claimed_fetched_at":"[^"]*"' /tmp/dnc-body | head -1 | cut -d'"' -f4)"

curl -s "$BASE/object/dnc%2F$PARTNER%2F$FILE" -H "Authorization: Bearer $ADMIN" \
  -o /tmp/dnc-fetched
check "/object returns the exact bytes" "$(sha256sum < "$BODY" | cut -d' ' -f1)" \
  "$(sha256sum < /tmp/dnc-fetched | cut -d' ' -f1)"

check "/object refuses a key outside the prefix" 400 \
  "$(code "$BASE/object/secrets%2Fx.zip" -H "Authorization: Bearer $ADMIN")"

echo "revocation"
code -X DELETE "$BASE/admin/tokens/$TOKEN_HASH" -H "Authorization: Bearer $ADMIN" >/dev/null
check "a revoked token stops working" 401 \
  "$(code -X POST "$BASE/upload/$FILE" -H "X-API-KEY: $TOKEN" --data-binary @"$BODY")"

echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
