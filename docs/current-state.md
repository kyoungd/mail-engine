# Current state — 2026-09-29: the project is now contact-engine; part 0 (the removals) is built

**mail-engine pivoted to contact-engine.** It no longer does direct mail. Its job now is
the contact services for NeverMissCall's sales-partner dialer: intake, DNC filtering,
time zone, assignment, the calling rule, and answering the dialer and the website. See
[`PRD.md`](PRD.md) (v2.0, rewritten today) and [`contact-engine/`](contact-engine/).
The name changed; the folders, the repository (`kyoungd/mail-engine`), and the
databases keep their old names.

History before today is in git: this file as of commit `4b6d5b9` holds every session
record from 2026-07-29 to 2026-09-13.

## Where the work stands

| | State |
|---|---|
| Branch `contact-engine` | Cut from `main` at `4b6d5b9`, 2026-09-29; pushed. Not yet the GitHub default: a settings change by the operator (`gh` is not installed here). |
| Part 0, Foundation | Approved and **built** 2026-09-29 ([`00-foundation.md`](contact-engine/00-foundation.md)). `make test` 395 passed, `make e2e` passed, ruff + pyright clean. |
| Parts 1 to 6 | Not designed. One at a time, in order, by this project ([`00-overview.md`](contact-engine/00-overview.md)). |
| Hosting on Render | After part 6 |
| Code | The mail code, web pages, and messages are removed; ~7,200 lines of app code and ~7,700 of tests remain (from ~11,000 and ~12,700). New: `jobs/intake_cli.py`, `service/state.py`, `derivation/activity.py`. No migration; newest is `0013`. |
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

1. **Design part 1, Intake.** It must first reconcile the 2026-08-06 partner-sourcing
   decision with decisions 3.1–3.3 ([`handoff.md`](contact-engine/handoff.md) §4).
2. **The largest open conflict:** 9.0, the 90 days against the rest (parts 4 and 5).
3. **Make `contact-engine` the GitHub default** — the operator, in GitHub's settings.

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
  Two leftover `me_scratch_*` databases remain in the local cluster. Proposed: log
  `pg_stat_activity` in that teardown before the drop.

## Small things noticed

- The docs in `contact-engine/` link to `../sales-partner-dialer-decisions.md`. That
  path worked in the NeverMissCall repository; here it points to nothing.
