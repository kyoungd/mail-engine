# Current state — 2026-10-01: contact-engine parts 0 to 6 are built; dev is reloaded and the API runs for the main site

**mail-engine pivoted to contact-engine.** It no longer does direct mail. Its job now is
the contact services for NeverMissCall's sales-partner dialer: intake, DNC filtering,
time zone, assignment, the calling rule, and answering the dialer and the website. See
[`PRD.md`](PRD.md) (v2.0, rewritten 2026-09-29) and [`contact-engine/`](contact-engine/).
The name changed; the folders, the repository (`kyoungd/mail-engine`), and the
databases keep their old names.

History before 2026-09-29 is in git: this file as of commit `4b6d5b9` holds every
session record from 2026-07-29 to 2026-09-13.

## Where the work stands

| | State |
|---|---|
| Branch `contact-engine` | Cut from `main` at `4b6d5b9`, 2026-09-29; pushed. Not yet the GitHub default: a settings change by the operator (`gh` is not installed here). |
| Part 0, Foundation | Approved and **built** 2026-09-29 ([`00-foundation.md`](contact-engine/00-foundation.md)). `make test` 395 passed, `make e2e` passed, ruff + pyright clean. |
| Part 1, Intake | Approved and **built** 2026-09-30 ([`01-intake.md`](contact-engine/01-intake.md)): migration `0014` (`intake_rep`), `service/rep_intake.add_numbers`, gate `tests/acceptance/test_rep_intake.py`. `make test` 458 passed; e2e, lint clean. `0014` applied to `mailengine_dev` only. |
| Part 2, DNC filtering | Revision 16 approved 2026-09-30 after fifteen reviews; the operator asked for a simpler approach, and the redesign around one phone-keyed record of "don't call me again" ([`02-dnc-filtering.md`](contact-engine/02-dnc-filtering.md)) was **approved at revision 18** the same day and **built** the same day: migration `0015`, `service/dnc.py`, `jobs/dnc_admin_cli.py`, gate `tests/acceptance/test_dnc_filtering.py`. `make test` 511 passed; e2e, lint clean. `0015` applied to `mailengine_dev` only. The rep's 24-hour undo was replaced by an admin lift of recorded requests (answers 8, 9 — decision 4.4, recorded 2026-10-01). |
| Parts 3 to 6 | Approved and **built** 2026-09-30 to 10-01, each with its gate; see the queue below and [`00-overview.md`](contact-engine/00-overview.md). Part 6 is the API (`web/api.py`, run with `make api`) and running it (`GET /v1/status`, `GET /health`). HEAD `1e5f8b6`, pushed. `make test` 828 passed; e2e, lint clean. |
| The decision record | Brought up to date 2026-10-01 from parts 1 to 6, approved by the operator: §9 holds only 9.6 and 9.16. The follow-up docs (`00-interface.md`, `00-purpose.md`, `handoff.md`, `00-overview.md` in both repos; notes in `01-intake.md` and `05a-call-record.md`) are edited too. **Committed** 2026-10-01: `31cc227` here, `891ec9d9` in NeverMissCall (branch `young`). Neither pushed. |
| `mailengine_dev` | Backed up, dropped, rebuilt from zero and reloaded 2026-10-01 (below). Test-only: nothing in it is assigned to a real rep. |
| The API for the main site | Runs from `./test-services.sh` on :8002; the interface for the website and the dialer is `nvermisscall/docs/active/contact-engine-api.md` (below). |
| Hosting on Render | Next, after the blank production start is planned |
| Code | Newest migration `0021` (applied to `mailengine_dev` only; production is still on `main`, below). |
| Docs | `PRD.md` v2.0; mail-engine's documents moved to `mail-engine-backup/`. |

**The source of decisions** is the decision record in the NeverMissCall repository,
`nvermisscall/docs/active/sales-partner-dialer-decisions.md`. Its §9 is the list of
what is not settled. This project proposes changes to it; the operator approves them.

## Production (unchanged, still on `main`)

- The production checkout (`marketing/mail-engine-production/`) is on `main` at
  `6579cc0`, tag `prod-2026-09-13.2`. It stays there until contact-engine is complete
  and hosted (decision 2.9).
- The daily routine as of 2026-09-13: in the production checkout, after ~7 AM PT,
  `python3 clients/dnc_uploader.py --config ~/dnc-uploader-nmc/dnc-uploader.ini`, then
  `./scripts/daily-run.sh` (console menu 7). Whether it has run since 2026-09-13 was
  not checked today.
- Newest backups in `~/db-backups/` are from 2026-09-13 (`…_1213.dump`,
  `…_1327.dump`). No offsite copy.

## The queue

1. ~~**The lock fix**~~ — **done 2026-09-30.** `suppress()` reads the owner `for
   update`; the scrub's `_apply` re-reads it `for update` in each contact's
   transaction. Frozen gate `tests/acceptance/test_lock_races.py` (red for the
   predicted reasons, then green); `make test` 398 passed, e2e and lint clean.
2. ~~**Build part 1**~~ — done 2026-09-30.
3. ~~**Propose the decision-record changes**~~ — done 2026-10-01, for parts 1 to 6 together:
   the operator approved the record's changes, then the follow-up docs'. Not committed.
4. ~~**Build part 2**~~ — done 2026-09-30. Production release (`0015` in `mailengine_prod`) waits on the operator.
5. ~~**Build part 3**~~ — done 2026-09-30 ([`03-time-zone.md`](contact-engine/03-time-zone.md), approved at revision 6): migration `0016`, `domain/zones.py` (NANPA's file), `service/zones.py`, `jobs/zone_admin_cli.py`, gate `tests/acceptance/test_time_zone.py`. `make test` 587 passed; e2e, lint clean. `0016` applied to `mailengine_dev` only. Production will start from a blank database and be reloaded (operator, 2026-09-30). The operator changed decision 5.5 (answer 3: the holding rep can set the zone) — recorded 2026-10-01.
6. ~~**Build part 4**~~ — done 2026-09-30 ([`04-assignment.md`](contact-engine/04-assignment.md), approved at revision 6; assignment — holding and getting numbers; no migration): `get_more_numbers`, `rep_own`, the 90-day return per contact, door B's 90-day `held`, the console counts; gate `tests/acceptance/test_assignment_regions.py`. `make test` 613 passed; e2e, lint clean. The sale, the Got a callback / Follow up exception, 9.0 and 9.12 moved to part 5 (answer 1); a contact returned by expiry cannot come back to the same rep for 90 days (answer 3).
6a. **The largest open conflict:** 9.0, the 90 days against the rest — now part 5c's.
6b. ~~**Build part 5a**~~ — done 2026-09-30 ([`05a-call-record.md`](contact-engine/05a-call-record.md), approved at revision 5): migration `0017`, `service/calls.py`, `jobs/calls_admin_cli.py`; gate `tests/acceptance/test_call_record.py`. `make test` 668 passed; e2e, lint clean. `0017` applied to `mailengine_dev` only. Next: build 5c.
6c. ~~**Build part 5b**~~ — done 2026-09-30 ([`05b-the-rule.md`](contact-engine/05b-the-rule.md), approved at revision 6): migration `0018`, `service/rule.py`, 5a's `calls.py` writes the state and applies the rule; gate `tests/acceptance/test_the_rule.py`. `make test` 708 passed; e2e, lint clean. `0018` applied to `mailengine_dev` only.
6d. ~~**Build part 5c**~~ — done 2026-10-01 ([`05c-sale-and-90-days.md`](contact-engine/05c-sale-and-90-days.md), approved at revision 7): migration `0019`, `service/sale.py`, changes to parts 4, 5a, 5b and door B, the approved frozen-test changes; gate `tests/acceptance/test_sale_and_90_days.py`. `make test` 749 passed; e2e, lint clean. `0019` applied to `mailengine_dev` only. Part 5 is complete. Next: part 6, context support. Part 5 is cut in three: 5a, 5b the rule, 5c the sale and the 90 days. Do not call is part 2's report, not an outcome (answer 3); calls received list contacts held now or once (answer 4).
6e. ~~**Build part 6a**~~ — done 2026-10-01 ([`06a-the-api.md`](contact-engine/06a-the-api.md), approved at revision 6): migration `0020`, `web/api.py`, `service/reads.py`, `service/roster.py`, the ambient connection in `db/session.py`; gate `tests/acceptance/test_api.py`. `make test` 784 passed; e2e, lint clean. `0020` applied to `mailengine_dev` only. Run it with `make api` (needs `CE_DIALER_KEY` and `CE_WEBSITE_KEY` in `.env`). Next: design part 6b.
6f. ~~**Build part 6b**~~ — done 2026-10-01 ([`06b-running-it.md`](contact-engine/06b-running-it.md), approved at revision 8): migration `0021`, `service/runs.py`, `GET /v1/status`, `GET /health`, the nightly's run record, part 2's recheck by the list's age; gate `tests/acceptance/test_running_it.py`. `make test` 828 passed; e2e, lint clean. `0021` applied to `mailengine_dev` only. Part 6 is complete.
7. **Make `contact-engine` the GitHub default** — the operator, in GitHub's settings.
8. ~~**Commit the decision record and docs**~~ — done 2026-10-01 (`31cc227` here, `891ec9d9` in NeverMissCall); not pushed. NeverMissCall also has an untracked `docs/affiliate-program-review-2026-09-26.md` that is not this project's.
8a. **The first rep journey through the API against the reloaded dev** — offered, not run: make a test rep known, Get more numbers (LA area), card and may-call, open a call, an outcome, history, a "don't call me again". The same path as switch-on gate 1 (6b §4.7).
8b. **The main site's side** — in `website/`, a parent-repo session: the contact-engine client (reads `CONTACT_ENGINE_URL`, `CE_DIALER_KEY`, `CE_WEBSITE_KEY`), the roster's `PUT /v1/reps/{id}`, Call Control.
9. **Plan the blank production start and the reload** — `mailengine_prod` starts from blank (operator, 2026-09-30): migrations from zero, then the contact lists, the DNC snapshots, partners, subscriptions.
10. **Hosting on Render** — the open limits named for it: 9.11's disk (record 4.10), the connection pool (6a §6, 6b §6), the switch-on gates (record 8.12).

## 2026-10-01 — dev reloaded, the API made runnable for the main site

**`mailengine_dev` reloaded** (operator's choices: drop and rebuild, CSLB + FBN, no
partners or subscriptions restored from the backup):

1. Backup `~/db-backups/mailengine_dev-2026-10-01_1444.dump` (16.7 MB; `pg_restore
   --list` reads it; 31 tables of data). It holds the old dev's 5 partners (one linked
   to `sales_rep_id` 47), 5 subscriptions and 6,123 events.
2. Dropped, recreated from `template0`, `make migrate` from zero: 21 migrations through
   `0021`, the grain swap on the empty database. The first full run of "migrations from
   zero" that the blank production start (queue 9) needs — it worked.
3. `jobs.intake_cli`: `cslb-all.csv --source cslb-ca` loaded 84,072 (36 s);
   `fbn-ca-2026.csv --source fbn-ca-2026` loaded 18,359 (6 s). 100,444 contacts,
   102,431 intake rows, 0 duplicate phones — the canonical numbers.

**DNC loaded into dev** (approved plan):

- `jobs.subscribe_area_codes add 714 760 805 818 916` (house SAN).
- The five 2026-09-13 lists in `../dnc-lists/<house id>/2026-09-13/` recorded with
  `service.dnc_snapshots.record_snapshot`, called directly: dev has no
  `SNAPSHOT_INBOX_URL`, so `dnc_pull` cannot be used, and no CLI records a file already
  on disk. `uploaded_at` is each file's mtime; `recorded_by` `operator`. All accepted;
  line counts equal production's for the same files.
- `jobs.dnc_refresh --from-ledger`: checked 24,212, hits 11,571 (4 m 38 s). By
  `dnc_status`: 12,641 `clear`, 11,571 `on_dnc_file`. Contacts outside the five codes
  are `not_checked`. Dev is test-only; the lists' age does not matter there (operator).

**The API runnable for the main site:**

- `nvermisscall/test-services.sh`: its mail-engine block ran `make run`, removed on
  this branch, so it was already broken. It now starts contact-engine with `make api`
  on :8002 (log `logs/contact-engine.log`), stops it by port, and skips with a warning
  when the keys are absent. Tested by running only its start and stop functions:
  `/health` 200; `/v1/status` 200 with the website key, 403 `wrong_key` with the
  dialer's, 401 without a key.
- Dev keys `CE_DIALER_KEY` and `CE_WEBSITE_KEY` generated (random, 32 bytes each), in
  this checkout's `.env`, the vault (section "contact-engine API keys — DEV"), and
  `nvermisscall/website/.env` with `CONTACT_ENGINE_URL=http://127.0.0.1:8002`.
  `website/.env` is not committed (it holds other uncommitted changes).
- `nvermisscall/docs/active/contact-engine-api.md`: the working reference for the
  website and the dialer — running it, headers and keys, idempotency, errors, every
  route with body, answer and refusals, the card, the values, the unreachable rules.
  The contract stays `06a-the-api.md` and `06b-running-it.md`, which win where they
  differ (6a answer 2).

**What the main site should know:** no rep is known yet — the website's first call is
`PUT /v1/reps/{sales_rep_id}` with the dialer's key; a region's batch reports a
shortfall for its unsubscribed area codes (LA area: 3 of 18 covered); `/v1/status`
shows `daily_run_missing` until a nightly runs; the API listens on 127.0.0.1, reached
through the website's dialer backend only.

## Part 0, as built — what to know

- **Steps 3–5 were done as one pass** (they rewrite the same nightly); the suite was
  checked after it rather than after each.
- **Kind-B test changes** (shown to the operator after, by their waiver): the
  opt-out checks in `test_suppression_split` and `test_contacts` now pin the
  assignment gate that refuses the contact (`voice_suppressed`, or `mid_funnel` for
  the suppressed stage) — a bare "not assignable" would pass on the never-checked
  contact for the wrong reason. `test_grain_intake`'s multi-trade check asks the
  assignment's rule. `test_partner_assignment`'s nightly-order test keeps its won and
  return checks without the digest.
- **Kept on purpose:** the live-Lob-key check in `tests/guard.py` (the production
  folder's `.env` still holds that key); `pyproject.toml` unchanged, so `uvicorn`,
  FastAPI, and the `integration` marker remain until part 6.
- **Unexplained, once in three full runs:** `test_grain_swap_guard` errored at
  teardown — `drop database … with (force)` was refused because a process of another
  role was connected to the scratch database. It passed 5/5 alone and in two later
  full runs; nothing was connected when looked at. Possibly the 2026-09-10 failure.
  Seen again 2026-09-30, dropping a scratch database right after restoring the
  production backup into it; again nothing was connected when looked at. Unproven
  hypothesis: an autovacuum/autoanalyze worker on the freshly loaded database.
  The teardown now prints the scratch database's sessions (`pg_stat_activity`) to
  stderr before the drop — a normal run shows one idle `me_user` session (yoyo's) —
  so the next failure names the other role. The two leftover `me_scratch_*`
  databases were dropped.

## Small things noticed

- The docs in `contact-engine/` link to `../sales-partner-dialer-decisions.md`. That
  path worked in the NeverMissCall repository; here it points to nothing.
