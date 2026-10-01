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
| Part 1, Intake | Approved and **built** 2026-09-30 ([`01-intake.md`](contact-engine/01-intake.md)): migration `0014` (`intake_rep`), `service/rep_intake.add_numbers`, gate `tests/acceptance/test_rep_intake.py`. `make test` 458 passed; e2e, lint clean. `0014` applied to `mailengine_dev` only. |
| Part 2, DNC filtering | Revision 16 approved 2026-09-30 after fifteen reviews; the operator asked for a simpler approach, and the redesign around one phone-keyed record of "don't call me again" ([`02-dnc-filtering.md`](contact-engine/02-dnc-filtering.md)) was **approved at revision 18** the same day and **built** the same day: migration `0015`, `service/dnc.py`, `jobs/dnc_admin_cli.py`, gate `tests/acceptance/test_dnc_filtering.py`. `make test` 511 passed; e2e, lint clean. `0015` applied to `mailengine_dev` only. The rep's 24-hour undo was replaced by an admin lift of recorded requests (answers 8, 9 — a change to decision 4.4, to be recorded). |
| Parts 3 to 6 | Not designed. One at a time, in order ([`00-overview.md`](contact-engine/00-overview.md)). |
| Hosting on Render | After part 6 |
| Code | The mail code, web pages, and messages are removed; ~7,200 lines of app code and ~7,700 of tests remain (from ~11,000 and ~12,700). New: `jobs/intake_cli.py`, `service/state.py`, `derivation/activity.py`. Newest migration `0014` (dev only). |
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
3. **Propose the decision-record changes** of `01-intake.md` §11 and `02-dnc-filtering.md` §11
   to the operator (decision 4.4 changed by answers 8 and 9).
4. ~~**Build part 2**~~ — done 2026-09-30. Production release (`0015` in `mailengine_prod`) waits on the operator.
5. ~~**Build part 3**~~ — done 2026-09-30 ([`03-time-zone.md`](contact-engine/03-time-zone.md), approved at revision 6): migration `0016`, `domain/zones.py` (NANPA's file), `service/zones.py`, `jobs/zone_admin_cli.py`, gate `tests/acceptance/test_time_zone.py`. `make test` 587 passed; e2e, lint clean. `0016` applied to `mailengine_dev` only. Production will start from a blank database and be reloaded (operator, 2026-09-30). The operator changed decision 5.5 (answer 3: the holding rep can set the zone) — to be recorded with the other decision-record changes.
6. ~~**Build part 4**~~ — done 2026-09-30 ([`04-assignment.md`](contact-engine/04-assignment.md), approved at revision 6; assignment — holding and getting numbers; no migration): `get_more_numbers`, `rep_own`, the 90-day return per contact, door B's 90-day `held`, the console counts; gate `tests/acceptance/test_assignment_regions.py`. `make test` 613 passed; e2e, lint clean. The sale, the Got a callback / Follow up exception, 9.0 and 9.12 moved to part 5 (answer 1); a contact returned by expiry cannot come back to the same rep for 90 days (answer 3).
6a. **The largest open conflict:** 9.0, the 90 days against the rest — now part 5c's.
6b. ~~**Build part 5a**~~ — done 2026-09-30 ([`05a-call-record.md`](contact-engine/05a-call-record.md), approved at revision 5): migration `0017`, `service/calls.py`, `jobs/calls_admin_cli.py`; gate `tests/acceptance/test_call_record.py`. `make test` 668 passed; e2e, lint clean. `0017` applied to `mailengine_dev` only. Next: build 5b, then design 5c.
6c. ~~**Build part 5b**~~ — done 2026-09-30 ([`05b-the-rule.md`](contact-engine/05b-the-rule.md), approved at revision 6): migration `0018`, `service/rule.py`, 5a's `calls.py` writes the state and applies the rule; gate `tests/acceptance/test_the_rule.py`. `make test` 708 passed; e2e, lint clean. `0018` applied to `mailengine_dev` only. Next: design 5c (the sale and the 90 days). Part 5 is cut in three: 5a, 5b the rule, 5c the sale and the 90 days. Do not call is part 2's report, not an outcome (answer 3); calls received list contacts held now or once (answer 4).
7. **Make `contact-engine` the GitHub default** — the operator, in GitHub's settings.

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
