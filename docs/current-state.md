# Current state — 2026-07-12 (dress rehearsal PASSED)

**2026-07-12: dress rehearsal steps 1–8 complete** on the Lob test key: 100-piece
drop (resumed cleanly through a real mid-run 422 crash — resumability proven live),
proofs operator-approved, fake webhooks (97 delivered / 3 returned, replay deduped,
unsigned 401), fake responses → 8 responders attributed (mailer-code + phone
precedence), orphan queue = exactly the planted unknown-phone + `evt_hook_1` (known
2026-07-11 smoke leftover), dashboard CPR arithmetic correct (8700¢/8 = 1087¢),
hot_response nudges fired with 5/day budget + 3 deferred + 1 digest (FakeSender).
**Fixes that came out of it:** Lob 40-char to.name truncation (word-boundary, in the
seam); pieces.status now derived from delivery events at resolution (returned
outranks delivered). **PostHog feed client BUILT** (`seams/posthog.py`, HogQL query
endpoint, keyset pagination; keys not yet collected — see INSTALL §3b).
**⚠️ BLOCKER before ghost wave:** live variants print `nevermisscall.com/?r=…` but
`?r=` capture lives on `getnevermisscall.com` — create corrected variants; also
landing-pages cell-parser removal still uncommitted there (checkout e2e, then push).

Read this to restart with zero context loss. Companion docs: `decisions.md` (vendor),
`list-shapes.md` (list data + traps), `dress-rehearsal.md` (the next thing to execute),
`INSTALL.md`, PRD.

## Where we are

Mail-engine is **v1-complete and live-smoked against Lob's test API**. All software
gates green: 212 tests, ruff + pyright clean. The next action is the **dress
rehearsal** (docs/dress-rehearsal.md): 100-piece test drop on the Lob test key →
design loop → fake webhooks/responses → verify capture. After that: live ghost wave
(~10 real cards to founders), then wave 1.

## Environment (local dev)

- Local Postgres `mailengine_dev` on **localhost:5432**, roles `me_user` /
  `me_user_ro` (password in `.env`), migrations 0001–**0005** applied. No Docker.
- `make run` → UI on **http://127.0.0.1:8001** (port moved from 8000). App has no
  dotenv loader — `make run`/`make migrate` source `.env`.
- ⚠️ **`make test` TRUNCATES this same DB** (clean_db fixture). Re-ingest after any
  test run (2s, idempotent):
  `intake CSVs are in the session scratchpad` — or regenerate:
  `uv run python -m intake.cslb_ca ../ingestion-app-1/MasterLicenseData.csv --county "Los Angeles" --classes C36 -o /tmp/cslb.csv`
  then `load_list(path, source='cslb-ca')`; same for `intake.fbn_ca --year 2026`
  (source `fbn-ca-2026`). Operator also keeps a pg_dump backup as the restore point.

## Data loaded

- `cslb-ca`: 4,568 LA-county plumbers (CLEAR C36), 100% phones E.164.
- `fbn-ca-2026`: 18,359 LA-county 2026 FBN filers, **no phones** (mail-only attribution).
- Facts + filter traps (WC-exempt trap, RDI, etc.): `list-shapes.md`.

## Key decisions (settled)

- **Print vendor: Lob** (`decisions.md`) — Developer (free) tier for campaign 1
  ($0.872/4×6 FC, 500/mo cap → monthly drops), Startup $260 at >~1k/mo. Stannp =
  verified runner-up; Poplar rejected (architecture). Keys in root `PRD.md` § Shared
  Credentials (test key wired in `.env`; live key for ghost wave; `LOB_WEBHOOK_SECRET`
  minted when webhook URL registered).
- **Attribution**: per-piece hash mailer codes won; landing-pages repo updated
  (cell-code parsing removed — **uncommitted there**; run checkout e2e before pushing,
  Netlify auto-deploys main).
- Campaign = chain of waves (no campaign table): drop 1 selects, drops 2/3 chain via
  `not_responded_to_wave`; fresh batches use `stage: ["prospect"]` (never-mailed) —
  disjoint automatically after recompute.

## Built since v1 commit `14a58ae` (uncommitted)

- Port 8001; audience-rule keys **`city`** (case-insensitive) + **`zip_prefix`**
  (SFV = `["913","914","916"]` → 5,394 contacts verified); wave-form hint;
  `dress-rehearsal.md`; this file.
- 2026-07-12: **full CSLB statewide load** — 84,072 contacts / six trades via
  `intake.cslb_ca` no-filter run (canonical CSV kept at `../ingestion-app-1/cslb-all.csv`
  for post-`make test` re-ingest); DB total 102,431 with FBN.
- 2026-07-12: **wave edit while draft** — `update_wave` verb + `/waves/{id}/edit`
  form + `POST /api/waves/{id}/update`; approval still locks. Migration **0006**:
  wave-name uniqueness excludes cancelled waves (cancel frees the name).
- 2026-07-12: **"Run drops" UI button** — `/drops` page triggers the same `run_drops`
  job, gated by `DROP_PASSWORD` in `.env` (fail-closed; PRD FR-11 exception recorded).
  `sync`/`recompute`/nightly remain unrouted. `run-mail-engine.sh` launcher in
  `marketing/`.

## In `14a58ae` (committed, main; repo has NO remote)

Full UI (every founder verb; Pico.css; `make run`), `list_key`/nullable-trade
migration + intake adapters (`intake/cslb_ca.py`, `intake/fbn_ca.py`), audience
`source`+`limit` (deterministic md5 sample; preview unified through
`resolve_audience` — fixed a real preview/execution divergence), **Lob client**
(`seams/lob.py`: idempotency header = mailer code — empirically verified live,
same psc_ id on re-submit; HMAC-SHA256 webhook verify, fail-closed `/webhooks/lob`
route), `Recipient` added to the PrintApi contract, judgment dead-wave rule,
`run_drops` resumes executing waves.

## Not built (the remaining work)

1. **PostHog feed client** (web-response pull) — next dev task after rehearsal.
2. **NMC feed client** + campaign line "nevermisscall" vertical config.
3. Deploy to VPS + register Lob webhook URL; cron `run_drops`/`run_nightly`;
   backups with tested restore (SR-6).
4. Postcard creative — operator to supply copy or redline the placeholder.
5. NCOA/CASS address job (Lob endpoints; stamps `addr_validated_at`, RDI flag).

## Watch-outs

- Lob has **no `postcard.delivered`** event: `processed_for_delivery` is the proxy
  (mapped to `piece.delivered`); tracking events fire in **live env only**.
- FBN responses can only match by mailer code (no phones) — orphans expected.
- `.env` address values must be quoted (spaces break `make run` sourcing).
- Wave-1 shape agreed: `{"segment": ["plumber-los-angeles"], "stage": ["prospect"],
  "limit": 500}` — but the dress rehearsal (limit 100) comes first.
