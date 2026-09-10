# DNC uploader — test, compile (PyInstaller), and the first production run

How to verify the partner-supplied-snapshot pipeline (Architecture B) and build a
rep's copy of `clients/dnc_uploader.py`. Three parts: **A** test locally, **B**
compile the rep's Windows `.exe`, **C** the first production run with NMC as its
own uploader.

**Status (2026-09-10).** Phases 1–5c are built and committed. Nothing has run on
real data yet: a dev rehearsal was staged on 2026-09-10 and stopped before the FTC
fetch, in favour of running it in production. Production is not ready for Part C —
migration `0013` is unreleased (prod is at `0012`) and the Worker is undeployed
(Phase 5d). Part C's prerequisites list both.

## Hazards — read before any step

- **One FTC fetch per file per day.** Any run that downloads spends that day's
  fetch for every file it takes. A downloaded zip stays in the client's folder
  until an upload succeeds — never delete one by hand; re-running resends it.
- **Two-day freshness.** `SNAPSHOT_MAX_AGE_DAYS = 2`: a file uploaded more than two
  days after its FTC date is recorded `stale_file` and never backs a verdict.
  Download and upload the same day.
- **Never test a wrong password with the real Organization ID.** A failed login
  against the real account happened once already (2026-09-10); a negative test
  needs no real id.
- **Issuing a token ROTATES it.** `issue-token` and `make client` both kill the
  partner's previous token at the edge; any earlier build stops working at once.
- **The token is a secret in transit.** It is shown once. The baked `.py` and the
  built `.exe` both contain it — move them over a private channel, delete the
  baked source after building.
- **Shared `dnc-lists/`.** Both checkouts land pulled files in
  `marketing/dnc-lists/<holder-uuid>/<version-date>/`, and the house row's uuid is
  the same in both databases. Same bytes either way, but a dev pull and a prod
  pull write the same directory.
- **Production shell discipline.** `cd` into `mail-engine-production/` in every
  shell call and name the database in every verification query — a silently reset
  cwd once sent a "prod" sync into dev (2026-08-07).
- **Prod DNC is stale as of 2026-09-10.** Every prod contact was last checked
  2026-08-07 — past the 31-day window — so `dnc_fresh` fails for all of them until
  a scrub runs. Part C's scrub is what refreshes them.

## Part A — test locally (no FTC, no production)

**A1. Offline suite.** `make test` — green. The pipeline's own tests:
`tests/acceptance/`: `test_dnc_snapshots.py`, `test_dnc_pull.py`,
`test_dnc_refresh_snapshots.py`, `test_dnc_version_alert_per_code.py`,
`test_partner_tokens.py`; `tests/unit/`: `test_dnc_uploader.py`,
`test_build_client.py`, `test_snapshot_inbox.py`, `test_token_registry.py`,
`test_dnc_file_registry.py`.

**A2. Worker smoke.** `workers/dnc-upload/smoke.sh` — expect `12 passed, 0 failed`.
Runs the real Worker under `wrangler dev --local` (simulated R2 + KV).

**A3. PyInstaller packaging on Linux.** Proves the bake and the packaging; the
binary is for testing only (a rep needs Part B's `.exe`). No database is touched —
`build_client.py` only bakes and packages.

```bash
uv run python scripts/build_client.py --partner "Test Build" \
    --token nmcdnc_not_a_real_token --url http://127.0.0.1:8788
mkdir -p /tmp/uploader-check && cd /tmp/uploader-check
<mail-engine>/dist/dnc-uploader-test-build     # empty folder, no ini
```

Expect `Setup needed:` / `dnc-uploader.ini is missing …`, exit 2. The other
message a rep can meet — an unbaked copy — comes from the plain source:
`uv run python clients/dnc_uploader.py` → `This copy was not set up for a specific
rep …`, exit 2. Delete `dist/` afterwards.

**A4. Dev dress run (optional — SPENDS TODAY'S FTC FETCH).** The whole chain against
`mailengine_dev` with a local Worker. Do not do this on a day Part C is planned.

1. Back up dev: `pg_dump -Fc "$OWNER_DATABASE_URL" -f <scratch>/mailengine_dev.dump`.
2. Start the Worker with a throwaway admin token:
   `cd workers/dnc-upload && npx --yes wrangler@4 dev --local --port 8788 --var ADMIN_TOKEN:<throwaway>`
3. In the shell only (never `.env`): `export SNAPSHOT_INBOX_URL=http://127.0.0.1:8788 SNAPSHOT_INBOX_TOKEN=<throwaway>`
4. `uv run python -m jobs.partners_cli issue-token Young` — the house row, i.e.
   NMC's own SAN, so the recorded holder is true.
5. `uv run python scripts/build_client.py --partner Young --token <token> --url http://127.0.0.1:8788 --bake-only --out <scratch>/client`
6. Put `dnc-uploader.ini` (NMC's Organization ID + Downloader password, from the
   vault) beside the baked source, then continue at **C4** below with the dev
   checkout and `mailengine_dev` in place of production.
7. Tear down: stop the Worker, delete the ini, the baked source and the token.

## Part B — compile the rep's `.exe` (Windows)

PyInstaller does not cross-compile: a Linux build cannot run on a rep's Windows
laptop. So the token is issued and baked on the box, and only the packaging
happens on Windows. (`make client PARTNER=…` does issue + bake + package in one
go on ONE machine — use it only when that machine is the rep's platform.)

**B1. Issue the token** (production checkout, after 5d):

```bash
cd …/marketing/mail-engine-production && set -a && . ./.env && set +a
uv run python -m jobs.partners_cli issue-token "<Partner>"
```

Store the printed token in the vault. The partner must be an active row.

**B2. Bake** (same shell):

```bash
uv run python scripts/build_client.py --partner "<Partner>" \
    --token <token> --url "$SNAPSHOT_INBOX_URL" --bake-only
```

→ `dist/dnc-uploader-<slug>.py` (slug = the name lowercased, non-alphanumerics → `-`).

**B3. Move the baked `.py` to the Windows machine** over a private channel.

**B4. Package on Windows** (Python 3.12+ from python.org; PyInstaller pinned to the
repo's dev version):

```bat
py -m pip install pyinstaller==6.22.2
py -m PyInstaller --onefile --clean --name dnc-uploader-<slug> dnc-uploader-<slug>.py
```

→ `dist\dnc-uploader-<slug>.exe`. These are the flags `build_client.py` uses.

**B5. Smoke the `.exe` without touching the FTC:** run it from an empty folder —
expect `Setup needed: … dnc-uploader.ini is missing`, exit 2.

**B6. Ship and clean up.** Send the rep the `.exe` plus an ini template with the
password left blank (`[ftc]` / `org_id = …` / `password =`). Delete the baked
`.py` and the `build\` directory from both machines.

## Part C — first production run (NMC as its own uploader)

NMC uploads its own five files through the partner pipeline, under the house row.
This exercises everything but the Windows `.exe`, and its scrub refreshes prod's
stale DNC state. The box is Linux, so the baked `.py` runs directly — no build.

### Prerequisites — each a 🔴 act with its own approval

- [ ] **Prod release of `0013`** per the release gate (`docs/coding/testing.md`):
      `make test` + `make e2e` + `STRICT=1 make integration` green same-day,
      migration plan stated (`0013` only), fresh backup, prod checkout
      fast-forwarded, `make migrate`, `git tag prod-YYYY-MM-DD`.
- [ ] **Phase 5d**: R2 bucket, KV namespace (id into `wrangler.toml`),
      `ADMIN_TOKEN` secret, DNS, `wrangler deploy` — commands in
      `workers/dnc-upload/wrangler.toml`. Then the prod `.env` gains
      `SNAPSHOT_INBOX_URL` (the deployed URL) and `SNAPSHOT_INBOX_TOKEN`
      (== `ADMIN_TOKEN`).
- [ ] **Fresh prod backup** the same day: `scripts/backup.sh`.
- [ ] The day's FTC files not yet fetched: `uv run python scripts/dnc-status.py`
      shows LIVE with today's date (it does not spend the fetch).

### Steps

Every shell call begins
`cd …/marketing/mail-engine-production && set -a && . ./.env && set +a`.

**C1. Token for the house row.** `uv run python -m jobs.partners_cli issue-token Young`
→ vault.

**C2. Bake.** `uv run python scripts/build_client.py --partner Young --token <token> --url "$SNAPSHOT_INBOX_URL" --bake-only --out <private-dir>`

**C3. Credentials.** Write `<private-dir>/dnc-uploader.ini` (chmod 600) with NMC's
Organization ID and Downloader password from the vault.

**C4. Run the client.** `python3 <private-dir>/dnc-uploader-young.py --config <private-dir>/dnc-uploader.ini`
→ expect `downloaded 5, sent 5`, exit 0. The five zips move to
`<private-dir>/uploaded/`. Exit 1 means something is waiting or damaged — re-run
it, never delete files.

**C5. Pull.** `uv run python -m jobs.dnc_pull` → `pulled=5 accepted=5 rejected=0`.
A second run → `skipped=5`, each `already_recorded`. Any rejection: read
`dnc_snapshots.reject_reason` before going on.

**C6. Scrub.** `uv run python -m jobs.dnc_refresh --from-ledger` → about
`checked=24212` (every contact is due), hits near 11.5k, `cleared` = numbers
delisted since August, **no `SKIP` lines**. ~4–5 minutes, one transaction per
contact — do not kill it.

**C7. Verify** (read-only; first line always names the database):

```sql
select current_database();                         -- mailengine_prod

select area_code, status, reject_reason, version_date, line_count, checks_written
from dnc_snapshots order by recorded_at;           -- 5 accepted, checks_written = per-code checked

select substring(phone_e164 from 3 for 3) code, count(*) n,
       count(*) filter (where dnc_registry) listed,
       count(*) filter (where dnc_checked_at::date = current_date) checked_today,
       count(*) filter (where dnc_snapshot_id is null) no_snapshot
from contacts where not is_seed and phone_e164 is not null
  and substring(phone_e164 from 3 for 3) in ('714','760','805','818','916')
group by 1 order by 1;                             -- checked_today = n, no_snapshot = 0

select count(*) from events where type = 'contact.dnc_checked'
  and external_id like 'dnc:%:snap:%';             -- = C6's checked
```

Sanity: listing rates near the 2026-08-07 baseline — 714 47.9% · 760 46.4% ·
805 52.6% · 818 43.6% · 916 49.6%.

**C8. Idempotency.** Re-run C6 → `checked=0`.

**C9. Clean up.** Delete the ini and the baked source; keep `uploaded/` until
the scrub is verified.

### After Part C

- The nightly still calls the single-registry `dnc_refresh(registry)`, and
  `nightly_cli` leaves the scrub unconfigured. Until it is rewired to
  `--from-ledger` (queued with 5d), C6 is a manual act.
- `scripts/dnc-daily.sh` downloads into `dnc-lists/<date>/` — on the day of Part C
  it finds the fetch already spent.
