# contact-engine Upgrade — Part 2: DNC filtering

**Status:** DRAFT, revision 3, 2026-09-30. Revision 1 did not pass its review (the status
missed event-only opt-outs; a report on a contact the rep no longer held was thrown
away; the UTC-date claim was false for the check's age — question 3 re-asked; the
export did not refuse what the status refuses). Revision 2 did not pass (the gate would
lose its `tombstoned` cause, breaking two frozen tests; "not later cleared" was
undefined, so an undo could erase a different block). This revision corrects those and
the minor findings. Not yet re-reviewed, not approved. Nothing is built.
**Part of:** [the upgrade](00-overview.md). Decisions are in the decision record,
`nvermisscall/docs/active/sales-partner-dialer-decisions.md`, named here by number
("decision 4.1"); sections of this document are named "§4.1".
**Checked against:** the `contact-engine` branch at `bb1940c` (parts 0 and 1 built). A
statement about the code carries its file and line.

---

## 1. Its job

Say whether a number is clean to call, and why not when it is not; make every place
that hands a number to a rep refuse what that says; and take, and undo, a "don't call
me again".

| Decision | What it asks |
|---|---|
| 4.1 | Every number is checked, NMC's and a rep's alike. Unchecked, failed, or not covered: no call. |
| 4.2 | A check is good through day 31; day 32 is stale. |
| 4.3 | "Don't call me again" blocks the number for every rep at once. |
| 4.4 | The rep who reported it can undo it within 24 hours, with a written reason. No admin step. |
| 4.5 | DNC files stay files; their upload is unchanged. |
| 4.6 | The rep is told an area code is not covered only after the check. |

Open items it settles: 9.8, 9.9, 9.10, 9.11, and the DNC half of 9.16.

## 2. Its edges

| Part 2 does | Part 2 does not — who does |
|---|---|
| The DNC status of a contact, with its reason (§4.1) | Decide "may I call now": that adds calling hours (part 3) and the sequence (part 5). Part 5 asks part 2's status. |
| Make the assignment gate and the export refuse what the status refuses (§4.3) | Put the contact in a Closed list — part 5 (decision 7.5) |
| Take a rep's "don't call me again", and its undo (§4.5, §4.6) | Remember a request for 90 days so a retry returns its first answer (decision 7.7) — part 6 |
| Take an admin's "don't call me again", with or without a contact (§4.7) | Expose any of it from outside, or raise an alert — parts 6 and the website (decision 1.7) |
| Record each completed daily scrub (§4.4) | Download or upload DNC files — unchanged (decision 4.5) |

## 3. What exists, checked

| Fact | Where |
|---|---|
| The daily scrub checks contacts in subscribed area codes never checked or checked over 21 days ago, rep-held first; a hit sets `dnc_registry` and takes the contact back to the house; a delisting clears it | `jobs/dnc_refresh.py:80-96`, `:106-169`; `config/params.py:19` |
| The daily run is pull → scrub → nightly; its scrub is `dnc_refresh_all` (`--from-ledger`), which links each checked contact to its snapshot. The single-registry `dnc_refresh` (`--fake`, `--snapshot`, `scripts/dnc-daily.sh`) writes no new link and keeps any earlier one (`coalesce`) | `scripts/daily-run.sh`; `jobs/dnc_refresh.py:137-139`, `:172-200`, `:239-278` |
| In production every contact in a subscribed code links a snapshot (24,212 of 24,212 on 2026-09-13) | git history of `docs/current-state.md` at `4b6d5b9` |
| Area codes nobody subscribes to are never scrubbed; their contacts keep `dnc_checked_at` null. `subscribe_area_codes remove` deletes a subscription outright | `jobs/dnc_refresh.py:80-96`; `jobs/subscribe_area_codes.py:114-118` |
| Freshness, in the gate and in the export: the check `>= now() − make_interval(days => 31)`, and, when the contact links a snapshot, its `version_date >= (UTC date) − 31`. No session sets a time zone, so the first follows the server's zone across a daylight-saving change (743 or 745 hours in a Pacific session) | `service/assignment.py:120-131`, `:328-331`; `config/params.py:33`; `db/session.py` |
| The gate's causes, in order: seed, no phone, held, `won`, mid-funnel (any non-assignable stage, `suppressed` included), `voice_suppressed` (`do_not_call`), `dnc_registry`, `tombstoned` (a voice tombstone), `dnc_unsubscribed`, `dnc_stale`. `tombstoned` is pinned by frozen tests | `service/assignment.py:43`, `:134-160`; `tests/acceptance/test_partner_assignment.py:243`; `tests/acceptance/test_export_compliance_invariant.py:160-163` |
| The export filters only `do_not_call` and `dnc_registry`, and reports a stale or never-checked contact as a `dnc_stale` shortfall. It does not read the subscription, tombstones, or opt-out events | `service/assignment.py:324-338` |
| The frozen export invariant changes `dnc_registry`, `do_not_call`, the check's age and the list's age after assignment; never the subscription, a tombstone, or an event. Its oracle reads no events | `tests/acceptance/test_export_compliance_invariant.py:117-134`, `:170-187` |
| "Don't call me again" can exist with no flag and no tombstone: a pre-`0010` `contact.opt_out`, one recorded by `ingest_event`, an unmatched one carrying the phone, a voice `contact.suppressed` recorded without the flag. Part 1's intake counts all but the last; `is_suppressed` reads `contact.opt_out` whose reason is not `do_not_mail` (a missing reason included) | `derivation/rules.py:66-79`; `service/rep_intake.py` `_judge`; `tests/acceptance/test_suppression_split.py:489` |
| `ingest_event` accepts any taxonomy type from any valid source, `contact.suppression_cleared` included | `service/ingestion.py:94-115`; `domain/taxonomy.py:31` |
| `suppress()` sets the flag, appends the event with the clock's time, writes a tombstone per channel, and for `voice` / `all` returns a held contact to the house (not when the house holds it); it records no reporter; its docstring says "Permanent by design" | `service/contacts.py:421-494`, `:426`, `:443`, `:487` |
| `clear_suppression` clears `dnc_registry` only, `voice` refused — pinned by frozen tests; its docstring calls it "the single public write path" for `contact.suppression_cleared`; no `unsuppress` verb exists — pinned | `service/contacts.py:496-524`, `:504-507`; `tests/acceptance/test_suppression_split.py:200`; `tests/acceptance/test_contacts.py:139` |
| Tombstones have an `id`, phone, list key, channel, reason, time; nothing links one to the event that wrote it | migration `0010` |
| Door A makes a contact whose phone has a voice tombstone with `do_not_call` set; door B refuses the number | `service/contacts.py:152-168`, `:290-292`; `service/rep_intake.py` |
| `contacts.created_at` defaults to the database's `now()` | migration `0001` |
| The DNC files are read by the pull (to judge each upload) and the scrub (from local working copies). The pull re-lands an accepted file whose copy is missing, for objects the upload Worker still lists as pending; a truncated listing is refused | `jobs/dnc_pull.py:60-81`, `:92-111`; `seams/snapshot_inbox.py:86-96` |
| The 31 days were checked against 16 CFR 310.4(b)(3)(iv) on 2026-09-13: "obtained from the Commission no more than thirty-one (31) days prior to the date any call is made" | git history of `docs/current-state.md` at `4b6d5b9` |

## 4. The design

### 4.1 The DNC status

`dnc_status(contact_id, at)` in a new `service/dnc.py`. `at` is a time-zone-aware
instant, handed in (the clock rule, part 1 §4.6). The first that applies:

| # | The contact | Status |
|---|---|---|
| 1 | Has "don't call me again" in any recorded form (the **voice block**, below) | `do_not_call` |
| 2 | Has no phone | `no_phone` |
| 3 | Its area code has no subscription, and it came in before the start of the last completed daily scrub (§4.4) | `not_covered` |
| 4 | Its area code has no subscription, otherwise; or it was never checked | `not_checked` |
| 5 | Is on the DNC file (`dnc_registry`) | `on_dnc_file` |
| 6 | Its check is older than 744 hours, or the list behind it is more than 31 UTC days old (§4.2) | `check_too_old` |
| 7 | Otherwise | `clear` |

**The voice block** is any of:

- `do_not_call`;
- a voice tombstone for the phone;
- its events make `is_suppressed` true (a `contact.opt_out` whose reason is not
  `do_not_mail`, a missing reason included);
- an **uncleared** voice `contact.suppressed` event: one no `contact.suppression_cleared`
  written by `undo_do_not_call` names, by `report_event_id` (§4.6). A clear written any
  other way — by `ingest_event`, say — clears nothing;
- an unmatched `contact.opt_out` event carrying the phone (the matcher's rule, part 1
  §4.2).

- **Only `clear` may be called** as far as DNC goes (decision 4.1). "Failed" in 4.1 is
  row 5; a check that could not run leaves the old one, which becomes row 6.
- **The voice block covers everything part 1's intake row 3 refuses**, and one form
  more: a flagless voice `contact.suppressed` on the contact. An unmatched voice
  `contact.suppressed` carrying the phone is read by neither (§6).
- **Row 3 is decision 4.6** (answer 1). "Came in" is `contacts.created_at`, compared
  with the run's start on the database's clock. A contact a rep claims from NMC's list
  came in long ago and has been through runs, so it reads `not_covered` at once (§9,
  design answer).
- **Which SAN covers a code is not asked here.** A code any holder subscribes to counts
  as covered for every rep, as today (§6).

### 4.2 The 31 days (decision 4.2; 9.10; answer 3)

Kept as they are (answer 3, re-asked on the corrected fact): the list's age in whole
days on the UTC date, `version_date >= (UTC date of the moment) − 31`; the check's age as
an exact interval. The one fix: the interval is written `make_interval(hours => 744)`,
so it is 31×24 hours whatever the session's time zone (§3), and it equals Python's
`timedelta(days=31)`. Both err toward stale: the UTC date is never behind a US date, and
an exact interval never counts a partial day as a whole one.

### 4.3 One rule, three readers

`service/dnc.py` holds the SQL for the voice block and for freshness, each over a
contact row and a moment. Three readers:

- **`dnc_status`** (§4.1), with `at` handed in.
- **The assignment gate** (`service/assignment.py:134-160`), with `now()` as the moment.
  **Its causes and their order are unchanged**; one form is added: `voice_suppressed`
  is returned for `do_not_call` **or** any other form of the voice block except the
  tombstone — so a contact whose opt-out is only an event is refused before the nightly
  stage catches up. A tombstone still gives `tombstoned`, in its place. Freshness is
  read from the shared SQL.
- **The export** (`service/assignment.py:324-338`): a contact is on the sheet only if
  the gate's DNC causes are all absent — the voice block, `dnc_registry`, an
  unsubscribed code, a stale or never-checked check. Today it misses an unsubscribed
  code, a tombstone with no flag, and an event-only opt-out (§3); decision 6.6 keeps
  the export for the operator and for reps not on the app. A stale or never-checked
  contact stays in the shortfall as `dnc_stale`, as today; one refused for any other
  DNC cause is in the shortfall under the gate's name for that cause.

The frozen export invariant gains cases that change a contact **after** it is assigned —
its code unsubscribed, a voice tombstone added, an opt-out recorded only as an event —
and asserts none reaches the sheet. Its oracle gains the event forms. These additions
are put to the operator with the tests (§8).

### 4.4 The daily scrub records itself

A new table `dnc_runs` (§10), written by one verb, `record_scrub_run(started_at,
finished_at, limited, checked, skips)` in `service/dnc.py` — `service/` stays the only
write path. `dnc_refresh_all`, the daily run's scrub, reads its start from the
database's `now()` when it begins and calls the verb when it finishes; no row when it
raises; a row when nothing is subscribed (`checked = 0`). The single-registry
`dnc_refresh` records nothing: it is not the daily run.

Status row 3 reads the latest `started_at` of an unlimited run. A run still in progress
has no row, so a contact that came in during it stays `not_checked` until the next.
`finished_at`, `checked`, and `skips` are there for part 6's "the last run and whether
it succeeded" (interface job 6) — added now because the row is written now, and a later
part could not recover them for past runs.

### 4.5 A rep's "don't call me again" (decisions 4.3; 9.8; answer 2)

`report_do_not_call(rep, contact_id, reason, at)` in `service/dnc.py`. **The block is
always recorded** (decision 4.3; decision 8.8, "permanently"): a report can wait on the
phone and arrive after the rep has lost the contact (decision 8.7), and throwing it
away would leave the number callable.

| The call | Result |
|---|---|
| `at` has no time zone | refused `bad_time` |
| No contact has the id | refused `no_contact` |
| The contact has no phone | refused `no_phone` |
| The contact already has `do_not_call` | refused `already_blocked` |
| The rep holds the contact | blocked; **the rep keeps it** (answer 2) |
| The house holds it | blocked; custody unchanged |
| Another rep holds it, or the reporter is unknown or inactive | blocked; the contact returns to the house, as `suppress(voice)` does |

One transaction, the contact row locked `for update`, through a helper shared with §4.7:

- `do_not_call = true`.
- A voice tombstone for the phone, with the primary list key when there is one.
- A `contact.suppressed` event, `occurred_at = at`, payload `{channel: voice, reason,
  source: rep, reported_by: <rep>, tombstone_id: <the tombstone's id>}`. `reason`
  defaults to "asked not to be called".
- When another rep holds it, `set_owner` to the house, reason `do_not_call`.

When the reporting rep holds it, it can never be called or handed on — every reader of
the voice block refuses it — and part 5 shows it in the rep's Closed list.

`suppress()` is unchanged and keeps returning a held contact to the house for every
other voice block, as its frozen tests pin. A retried report after success is refused
`already_blocked`; returning the first answer instead is part 6's (decision 7.7).

### 4.6 The undo (decision 4.4; answer 4)

`undo_do_not_call(rep, contact_id, reason, at)`. The contact's **voice history** is its
`contact.suppressed` (channel voice), `contact.opt_out` (reason not `do_not_mail`), and
the `contact.suppression_cleared` events `undo_do_not_call` wrote, in event-id order —
not by `occurred_at`, which the caller supplies.

| The call | Result |
|---|---|
| `at` has no time zone | refused `bad_time` |
| No contact has the id | refused `no_contact` |
| The rep is unknown, inactive, or the house | refused `bad_rep` |
| The reason is missing or blank | refused `no_reason` |
| The last event of the voice history is not a rep's report (none; an opt-out; an admin block; an undo) | refused `nothing_to_undo` |
| It was reported by another rep | refused `not_yours` |
| `at` is more than 24 hours after the report's `occurred_at` | refused `too_late` |
| Anything else in the voice block remains: another voice tombstone for the phone, `is_suppressed`, an unmatched opt-out carrying the phone, or an uncleared voice `contact.suppressed` other than this report | refused `still_blocked` |
| Otherwise | undone |

One transaction, the contact row locked `for update`: `do_not_call = false`; the one
tombstone named by the report's `tombstone_id` is deleted; a
`contact.suppression_cleared` event, `occurred_at = at`, payload `{channel: voice,
reason, source: rep, undone_by: <rep>, report_event_id}`. The events keep the whole
history. Custody is not changed back: a contact the report sent to the house stays
there (§6).

**This reverses a block the code calls permanent.** Decision 4.4 and answer 4 require
it. `clear_suppression` still refuses `voice`, and no `unsuppress` verb appears, so the
frozen tests at `test_suppression_split.py:200` and `test_contacts.py:139` stand. The
build updates, as part of the approved tests and plan (§8): `suppress()`'s docstring
("Permanent by design"), `clear_suppression`'s docstring ("the single public write
path" — the undo is a second writer), and the suppression matrix header in
`test_suppression_split.py`, each to name the one exception — a rep's own report,
undone within 24 hours.

After an undo, part 1's intake no longer refuses the number: the flag is false, the
tombstone is gone, and intake row 3 never counted the report's `contact.suppressed`.

### 4.7 An admin's "don't call me again" (9.9)

`record_do_not_call_request(phone, reason, at)` in `service/dnc.py`, for a request that
reached NMC by email or phone:

| The call | Result |
|---|---|
| `at` has no time zone | refused `bad_time` |
| The reason is missing or blank | refused `no_reason` |
| The phone is invalid (part 1's rule) | refused `invalid_phone` |
| A contact has the phone, already with `do_not_call` | refused `already_blocked` |
| A contact has the phone | blocked through the helper of §4.5, `source: admin`, no `reported_by`; a contact another rep holds returns to the house, a rep's own included (§6) |
| No contact has the phone | a voice tombstone for the phone, nothing else |

Every time it writes is `at`. Door B refuses the number from then on; door A creates it
with `do_not_call` set (`service/contacts.py:152-168`, `:290-292`). If a contact with the
phone is created at the same moment, it can land without the flag; the voice block
reads the tombstone, and the gate and the export read the voice block, so the number is
refused everywhere all the same.

The operator reaches it with a new command, `python -m jobs.dnc_request_cli <phone>
--reason …`, which closes part 0's gap "cannot record an opt-out" for the operator. The
website reaches it in part 6.

### 4.8 The files on Render (9.11)

Only the daily job reads DNC files (the pull to judge them, the scrub to check against
them); the service reads the columns the scrub wrote. So on Render the pull and the
scrub run in one job, as `daily-run.sh` runs them today. A Render job's disk is fresh
each run, so every run must re-land each code's newest accepted file; today the pull
re-lands only objects the Worker still lists as pending (`jobs/dnc_pull.py:92-95`) and
refuses a truncated listing (`seams/snapshot_inbox.py:88-96`). That is a requirement on
hosting, recorded here. It fails closed: a code with no working copy is skipped and its
contacts go stale.

### 4.9 The law (9.16, DNC half)

The 31 days stand as checked on 2026-09-13 (§3); §4.2 keeps both counts strict. The
calling-hours half of 9.16 is part 3's.

## 5. Part 1's hand-offs, closed

| Part 1 left | Part 2 |
|---|---|
| Undoing a "don't call me again" (4.4) would leave the tombstone, so intake would keep refusing | §4.6 deletes the report's own tombstone |
| A held contact goes back to the house on a voice suppression | For the holding rep's own report, no longer (§4.5). Other blocks still return it (§6) |
| A voice `contact.suppressed` recorded without the flag is not read by intake row 3 | The voice block reads it (§4.1); intake row 3 is part 1's and unchanged |

## 6. Gaps and limits

Gaps are not questions (decision 2.9).

| Gap or limit | Closed in |
|---|---|
| Nothing outside tests calls `dnc_status`, `report_do_not_call`, `undo_do_not_call` | Parts 5 and 6 |
| The age of each area code's DNC file, for alerts (interface job 2) | Part 6, over `dnc_snapshots` and `dnc_runs` |
| A rep's own contact is taken back to the house on a DNC hit (`jobs/dnc_refresh.py:147-153`), on an admin's request (§4.7), and on another rep's report (§4.5); an undo does not give it back | Part 4 (decision 6.3) |
| A retried report or undo gets `already_blocked` / `nothing_to_undo`, not its first answer | Part 6 (decision 7.7) |
| Which SAN's subscription covers a code for which rep | Counsel (memo Q4); part 4 if it changes who may be given a code |
| An unmatched voice `contact.suppressed` carrying a phone is read by nothing | Left: no code writes one |
| The console's inventory counts do not read the voice block | Left: an operator view, not a path to a call |

## 7. Tests, written first

| Test | Checks |
|---|---|
| The voice block, each form | `do_not_call`; a voice tombstone; an opt-out event with a reason, and with none (null reason, in SQL too); an unmatched opt-out under `phone_e164`, and as `(818) 555-0123` under `phone`; a flagless voice `contact.suppressed`; the same after its undo → not blocked; after an ingested `contact.suppression_cleared` → still blocked |
| An undo cannot clear another block | A flagless voice `contact.suppressed` E0; then a report; its undo → `still_blocked`, the number stays `do_not_call` |
| Status 2 to 7 | The status |
| The order | status 1 + on the DNC file → `do_not_call`; on the DNC file + stale → `on_dnc_file`; no phone + unsubscribed → `no_phone`; unsubscribed + never checked + before the last run → `not_covered` |
| Not covered after the run | A contact in an unsubscribed code: `not_checked`; `dnc_refresh_all` completes; `not_covered`. A contact created after that run began: `not_checked`. A `--limit` run or a single-registry run does not count |
| Runs | `dnc_refresh_all` writes one row when it finishes, one when nothing is subscribed, none when it raises; `dnc_refresh` writes none |
| The 31 days | The check a minute inside 744 hours: fresh; a minute past: stale; the list 31 UTC days old fresh, 32 stale — in the status, the gate, and the export, under `PGTZ` at UTC+14, UTC−11, and `America/Los_Angeles` across a daylight-saving change |
| The gate | An event-only opt-out on a released contact → `voice_suppressed` before any recompute; a tombstone only → `tombstoned`; every existing cause name and order unchanged |
| The export | Assigned, then: code unsubscribed → shortfall `dnc_unsubscribed`; voice tombstone added → `tombstoned`; opt-out recorded only as an event → `voice_suppressed`; a held contact the rep reported → `voice_suppressed`; none is on the sheet |
| Report: each refusal | The result; nothing written |
| Report: by the holder | The flag; one voice tombstone; one `contact.suppressed` with `reported_by` and the tombstone's id; the rep still holds it; status `do_not_call`; after release, the gate `voice_suppressed`; intake for another rep → `do_not_call` |
| Report: not the holder | After a `reclaim` (house holds: custody unchanged, no reclaim event); held by another rep (returns to the house); from an inactive rep — the flag, the tombstone, the event |
| Undo: each refusal | Including a second undo; an admin block last; 24 hours and one second → `too_late`; exactly 24 hours → undone |
| Undo: undone | Flag false; the report's tombstone gone, any other untouched; one `contact.suppression_cleared` naming the report; status not `do_not_call`; intake no longer refuses |
| Admin request | Each refusal; with a contact another rep holds: blocked, back at the house; without a contact: one voice tombstone, no contact; door B refuses; door A creates it with `do_not_call` |
| The clock | Every event and row the new verbs write carries `at`; a naive `at` is refused |
| Frozen tests | Every existing test passes, the export invariant with its additions (§4.3) |

## 8. Done means

| Check | How |
|---|---|
| The build follows the red-tier gate: the gate and the export change, suppression verbs, a tombstone delete, a migration | Build plan approved first; the tests approved as its first step — including the additions to the frozen export invariant and the edited suppression matrix header in `test_suppression_split.py` |
| The tests of §7 pass; every other existing test passes unchanged | `make test` |
| `make e2e`, `make lint` | Pass |
| `0015` changes no existing row on production-shaped data | As part 1's §8 check, from a checkout without `0015` |

## 9. For the operator

| # | Question | Answer |
|---|---|---|
| 1 | How "not covered" appears (4.6) | **Answered 2026-09-30:** after the next daily run — the run is recorded; before it, `not_checked`. Offered "After the next daily run", "Immediately", or "Never say it". |
| 2 | After a rep's "don't call me again", does the rep keep the contact (9.8) | **Answered 2026-09-30:** the rep keeps it, Closed. Offered "Rep keeps it, Closed" or "Back to NMC". |
| 3 | How the 31 days are counted (9.10) | **Answered 2026-09-30:** whole UTC days for both. **Re-asked 2026-09-30:** the question had said UTC-date counting errs toward stale; for the check's age it can make a check up to about a day younger. Offered "Keep as is", "Whole days + require a list", or "Whole days, as answered"; chose keep as is. |
| 4 | The undo and the report's tombstone (4.4) | **Answered 2026-09-30:** the undo removes that tombstone; the events keep the record. Offered "Remove that tombstone", "Mark it undone", or "Leave it". |

**The design's own answers**, for approval with the part (each has one obvious reading):

| Point | Answer |
|---|---|
| 9.9, an admin's request with no contact | A voice tombstone only (§4.7) |
| 9.11, the files on Render | Pull and scrub in one job; the service reads no file; every run re-lands each code's newest file (§4.8) |
| 9.16, the 31 days | As checked 2026-09-13 (§4.9) |
| Who may report | Any rep; the block is always recorded; only the holder keeps the contact (§4.5) |
| A second report on a blocked number | Refused `already_blocked` (§4.5) |
| The 24 hours | From the report's `occurred_at`, on the server's clock (decision 7.6); inclusive |
| "Came in" for status row 3 | `contacts.created_at`: a claimed NMC contact has been through runs, so reads `not_covered` at once (§4.1) |
| The check's 31 days | `make_interval(hours => 744)`, so a session's time zone cannot shift it (§4.2) |

## 10. The migration, `0015.dnc-runs.sql`

```sql
create table dnc_runs (
  id           uuid primary key default gen_random_uuid(),
  started_at   timestamptz not null,
  finished_at  timestamptz not null,
  limited      boolean not null,
  checked      integer not null,
  skips        jsonb not null default '[]'
);

create index dnc_runs_started_idx on dnc_runs (started_at);

grant select on dnc_runs to me_user_ro;
```

Additive. The explicit grant does not rely on `0002`'s default privileges holding for
whichever role runs `0015`.

## 11. Proposed changes to the decision record

| Record item | Proposed change |
|---|---|
| 9.8 | Decided: the reporting rep, if they hold it, keeps the contact, Closed (answer 2) |
| 9.9 | Decided: a voice tombstone only (§9) |
| 9.10 | Decided: the list in whole UTC days, the check as an exact 744 hours (answer 3) |
| 9.11 | Decided for part 2: pull and scrub in one job; every run re-lands each code's newest file |
| 4.3 | Add: a rep's report is always recorded, whoever holds the contact |
| 4.4 | Add: the undo removes the report's tombstone (answer 4) |
| 4.6 | Add: "after the check" is after the next completed daily run (answer 1) |
