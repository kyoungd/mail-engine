# Current state — 2026-09-29: the project is now contact-engine; branch cut, part 0 approved, nothing built

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
| Branch `contact-engine` | Cut from `main` at `4b6d5b9`, 2026-09-29. **Local only, not pushed.** Not yet the GitHub default: that needs a push, then a settings change by the operator (`gh` is not installed here). |
| Part 0, Foundation | Designed and approved 2026-09-29 ([`00-foundation.md`](contact-engine/00-foundation.md)). **Not built.** |
| Parts 1 to 6 | Not designed. One at a time, in order, by this project ([`00-overview.md`](contact-engine/00-overview.md)). |
| Hosting on Render | After part 6 |
| Code | Unchanged from `main`. Newest migration `0013`. |
| Docs today | `PRD.md` rewritten for contact-engine; this file reset. Both uncommitted. |

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

1. **Before building part 0:** part 0 says `main` gets one commit first, the three
   files changed there (`creative/README.md`, `docs/INSTALL.md`,
   `docs/direct-marketing-101.md`). The branch was cut before that commit, so those
   changes are now uncommitted on `contact-engine`. Settle where they are committed.
2. **Push the branch and make it the default** — on the operator's "push".
3. **Re-check part 0's code citations.** They were checked at `4b6d5b9`; `main` has not
   moved, so they should still hold.
4. **Build part 0** — the removals, per its eight steps. Changes of test kind B are
   shown to the operator first.
5. **Design part 1, Intake.** It must first reconcile the 2026-08-06 partner-sourcing
   decision with decisions 3.1–3.3 ([`handoff.md`](contact-engine/handoff.md) §4).
6. **The largest open conflict:** 9.0, the 90 days against the rest (parts 4 and 5).

## Small things noticed

- The docs in `contact-engine/` link to `../sales-partner-dialer-decisions.md`. That
  path worked in the NeverMissCall repository; here it points to nothing.
