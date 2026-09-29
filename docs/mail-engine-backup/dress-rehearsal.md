# Dress rehearsal — the 100-piece test drop

A full campaign run on the Lob **test** key: real lifecycle, real vendor API, rendered
proofs, zero mail, zero cost — then faked delivery events and faked responses to prove
capture end-to-end. Repeatable: restore the DB backup and run it again.

## What it proves / what it deliberately doesn't

| Proves | Stays unproven (by design) |
|---|---|
| Wave lifecycle: draft → preview → approve (hash) → job-run drop | Physical print/delivery quality (that's the live-key ghost wave, ~10 pieces to founders) |
| Lob submission: idempotent submit, creative rendering (proofs in dashboard) | Lob's real webhook POSTs (tracking events are live-env-only; we self-sign fakes) |
| Webhook path: signature check, event mapping, idempotent ingestion | PostHog / NMC feed clients (not built yet — responses are injected at the ingestion layer) |
| Attribution: mailer code → piece → contact; phone precedence; orphans | |
| Derived state: prospect → in_sequence → responded; pipeline/dashboard/nudges | |

## Prerequisites

- [ ] DB backup taken (`pg_dump`) — the restore point for re-runs
- [ ] Lists loaded (`cslb-ca` 4,568 / `fbn-ca-2026` 18,359 — re-ingest is 2s if a test run truncated)
- [ ] `.env`: `LOB_API_KEY=test_…` (wired), `LOB_WEBHOOK_SECRET=<any local value>` (we sign our own fakes)
- [ ] `make run` → UI on http://127.0.0.1:8001

## Runbook

**1. Design loop (one piece at a time).** Create the variant at `/variants` (hypothesis
required). Submit a single test piece; open the rendered PDF proof at dashboard.lob.com
(Test environment → Postcards); redline; repeat. Creative contract: `creative` JSON =
`{front, back, size?, mail_type?}`, HTML with `{{mailer_code}}` merge variable in the
QR/`?r=` URL. Iterate until the proof looks right.

**2. Draft the wave** at `/waves/new`:
```json
{"segment": ["plumber-los-angeles"], "stage": ["prospect"], "limit": 100}
```
(`stage: prospect` = never mailed; `limit` = deterministic unbiased sample.)
Variant split: `{"<variant-id>": 1}` (IDs on the Variants page). Schedule for tomorrow.

**3. Approve in the UI** — `/approvals` → review preview (count must read 100) → approve.
This is the system's one gated action; the hash you approve is what fires.

**4. Run the drop the production way** (job, not HTTP):
```bash
set -a && . ./.env && set +a && uv run python -c "
from datetime import date, timedelta
from jobs.drop import run_drops
from seams.lob import LobPrintApi
import os
api = LobPrintApi(os.environ['LOB_API_KEY'], {
  'name': os.environ['LOB_FROM_NAME'], 'address_line1': os.environ['LOB_FROM_LINE1'],
  'address_city': os.environ['LOB_FROM_CITY'], 'address_state': os.environ['LOB_FROM_STATE'],
  'address_zip': os.environ['LOB_FROM_ZIP']})
print(run_drops(api, date.today() + timedelta(days=1)))"
```
Expect: `pieces_created=100, pieces_submitted=100, halted=False`. Kill it mid-run and
re-run to watch resumability (no duplicates — vendor idempotency).

**5. Verify the drop**: 100 proofs in the Lob test dashboard; `/waves/{id}` shows 100
pieces submitted with costs; `pieces` rows carry mailer codes + `psc_…` ids.

**6. Fake delivery webhooks** — sign payloads with the local secret, POST to
`http://127.0.0.1:8001/webhooks/lob` (`processed_for_delivery` for most, a couple of
`returned_to_sender`). Verify: piece statuses flip, `FAIL_PCT` math on the dashboard,
replay a payload → no duplicate event (idempotent on `(source, external_id)`).

**7. Fake responses at the ingestion layer** (stands in for the unbuilt PostHog/NMC
feeds): inject `page.visit` events with real mailer codes from step 4, one
`call.inbound` with a contact's real phone (tests precedence #3), one with an unknown
phone (must land as an orphan). Run `resolve_orphans` + `recompute_state`.

**8. Watch the spine light up**: `/pipeline` (responders moved in), `/waves/{id}`
(responses + cost-per-response), `/contacts/{id}` timelines, `/orphans` (exactly the
unknown-phone event), then run the nightly judgment and check `/nudges` (hot-response
nudge fires).

**9. Reset**: restore the DB backup. Mailer codes are deterministic per (wave, contact),
so a re-run after restore regenerates identical codes — new wave = new codes.

## Exit criteria (go/no-go for the live ghost wave)

- 100/100 submitted, idempotent under a mid-run kill
- Proof design approved by operator
- Delivery + response events all attributed (orphan rate = only the planted orphan)
- Dashboard numbers arithmetically correct against the faked inputs
- Nudge generation fired per rules
