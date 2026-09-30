# contact-engine Upgrade — Part 2: DNC filtering

**Status:** DRAFT, revision 9, 2026-09-30. Revision 8 **passed** its review (the eighth;
revisions 1–7 did not pass). After it, the operator replaced the rep's 24-hour undo with
an admin-only lift (answer 8, changing decision 4.4), which removes most of the design's
undo machinery; this revision is rewritten around that, keeps revision 8's other
content, applies its review's minor findings, and adds the safety properties every
revision is checked against (§12). Not yet re-reviewed, not approved. Nothing is built.
**Part of:** [the upgrade](00-overview.md). Decisions are in the decision record,
`nvermisscall/docs/active/sales-partner-dialer-decisions.md`, named here by number
("decision 4.1"); sections of this document are named "§4.1".
**Checked against:** the `contact-engine` branch at `c3179da` (parts 0 and 1 built). A
statement about the code carries its file and line.

---

## 1. Its job

Say whether a number is clean to call, and why not when it is not; make the assignment
gate and the export refuse what that says; take a "don't call me again"; and let an
admin lift one.

| Decision | What it asks |
|---|---|
| 4.1 | Every number is checked, NMC's and a rep's alike. Unchecked, failed, or not covered: no call. |
| 4.2 | A check is good through day 31; day 32 is stale. |
| 4.3 | "Don't call me again" blocks the number for every rep at once. |
| 4.4 | *As decided 09-28:* the reporting rep can undo it within 24 hours. *Replaced 2026-09-30 by answer 8:* no rep undo; an admin lifts a block by hand, with a written reason. |
| 4.5 | DNC files stay files; their upload is unchanged. |
| 4.6 | The rep is told an area code is not covered only after the check. |

Open items it settles: 9.8, 9.9, 9.10, 9.11, and the DNC half of 9.16.

## 2. Its edges

| Part 2 does | Part 2 does not — who does |
|---|---|
| The DNC status of a contact, with its reason (§4.1) | Decide "may I call now": that adds calling hours (part 3) and the sequence (part 5). Part 5 asks part 2's status. |
| Make the assignment gate and the export refuse what the status refuses (§4.3) | Put the contact in a Closed list — part 5 (decisions 7.5, 7.11) |
| Take a rep's "don't call me again" (§4.5) and an admin's (§4.6) | Remember a request for 90 days so a retry returns its first answer (decision 7.7) — part 6 |
| Let an admin lift a block (§4.7) | Expose any of it from outside, or raise an alert — part 6 and the website (decision 1.7) |
| Record each completed daily scrub (§4.4) | Download or upload DNC files — unchanged (decision 4.5) |
| | Change who holds a contact — part 4. No verb of part 2 moves custody |

## 3. What exists, checked

| Fact | Where |
|---|---|
| The daily scrub checks contacts in subscribed area codes never checked or checked over 21 days ago, rep-held first; a hit sets `dnc_registry` and takes the contact back to the house; a delisting clears it | `jobs/dnc_refresh.py:80-96`, `:106-169`; `config/params.py:19` |
| The daily run is pull → scrub → nightly; its scrub is `dnc_refresh_all` (`--from-ledger`), which links each checked contact to its snapshot. The single-registry `dnc_refresh` (`--fake`, `--snapshot`, `scripts/dnc-daily.sh`, and `run_nightly` when handed a registry) stamps a fresh check, writes no new link and keeps any earlier one (`coalesce`): the linked list may be newer or older than the one it judged against, `--fake` judges against none, and a contact with no link is judged on its stamp alone | `scripts/daily-run.sh`; `jobs/dnc_refresh.py:137-139`, `:172-200`, `:239-278`; `jobs/nightly.py:19-24` |
| In production every contact in a subscribed code links a snapshot (24,212 of 24,212 on 2026-09-13); the single-registry scrub had been run on production before, on 2026-08-05 (`dnc_refresh --snapshot`) | git history of `docs/current-state.md` at `4b6d5b9` |
| Area codes nobody subscribes to are never scrubbed: a contact in a code never subscribed keeps `dnc_checked_at` null; one in a code unsubscribed after scrubbing keeps its old stamp and link. `subscribe_area_codes remove` deletes one holder's subscription row; the code stays covered while another holder's row remains | `jobs/dnc_refresh.py:80-96`; `jobs/subscribe_area_codes.py:113-118`; migration `0013` |
| Freshness, in the gate and in the export: the check `>= now() − make_interval(days => 31)`, and, when the contact links a snapshot, its `version_date >= (UTC date) − 31`. No session sets a time zone, so the first follows the server's zone across a daylight-saving change (743 or 745 hours in a Pacific session) | `service/assignment.py:120-131`, `:328-331`; `config/params.py:33`; `db/session.py` |
| The gate's causes, in order: seed, no phone, `already_assigned`, `won`, mid-funnel (any non-assignable stage, `suppressed` included), `voice_suppressed` (`do_not_call`), `dnc_registry`, `tombstoned` (a voice tombstone for the phone), `dnc_unsubscribed`, `dnc_stale`. `tombstoned` is pinned by frozen tests | `service/assignment.py:42-43`, `:129-130`, `:134-160`; `tests/acceptance/test_partner_assignment.py:243`; `tests/acceptance/test_export_compliance_invariant.py:160-163` |
| The export drops `do_not_call` and `dnc_registry` contacts silently, and reports a stale or never-checked contact as a `dnc_stale` shortfall. It does not read the subscription, tombstones, or opt-out events. The frozen invariant pins the shortfall as exactly `{dnc_stale: …}` | `service/assignment.py:324-338`, `:351-356`; `tests/acceptance/test_export_compliance_invariant.py:194-196` |
| The frozen export invariant changes `dnc_registry`, `do_not_call`, the check's age and the list's age after assignment; never the subscription, a tombstone, or an event. Its oracle `_forbidden_phones` reads no events | `tests/acceptance/test_export_compliance_invariant.py:117-134`, `:170-187` |
| "Don't call me again" can exist with no flag and no tombstone: a pre-`0010` `contact.opt_out`, one recorded by `ingest_event`, an unmatched one carrying the phone, a voice `contact.suppressed` recorded without the flag. Part 1's intake counts all but the last; `is_suppressed` reads `contact.opt_out` whose reason is not `do_not_mail` (a missing reason included) | `derivation/rules.py:66-79`; `service/rep_intake.py` `_judge`; `tests/acceptance/test_suppression_split.py:489` (an event-only opt-out) |
| `ingest_event` accepts any taxonomy type from any valid source, with any payload. An event's `source` is one of `lob`, `posthog`, `nmc`, `human`, `system`; nothing in an event shows which verb wrote it. `events.id` is an identity column | `service/ingestion.py:94-115`; `domain/enums.py:36-41`; migration `0001` |
| `suppress()` sets the flag, appends the event with the clock's time, writes a tombstone per channel, and for `voice` / `all` returns a held contact to the house (not when the house holds it); it has no caller on the branch; its docstring says "Permanent by design" | `service/contacts.py:421-494`, `:426`, `:443`, `:487` |
| `clear_suppression` clears `dnc_registry` only, `voice` refused — pinned by frozen tests; its docstring calls it "the single public write path" for `contact.suppression_cleared` and says it "rejects the permanent channels"; it can clear `dnc_registry` with no check and no list; only the scrub calls it. No `unsuppress` verb exists — pinned | `service/contacts.py:496-524`, `:504-507`, `:511`; `tests/acceptance/test_suppression_split.py:200`; `tests/acceptance/test_contacts.py:139` |
| Tombstones have an `id`, phone, list key, channel, reason, and `created_at` (default `now()`); nothing links one to the event that wrote it | migration `0010` |
| Door A makes a contact with `do_not_call` set when a voice tombstone matches its phone **or its list key**, and stores any number `to_e164` accepts. Door B refuses a number with a voice tombstone for the phone | `service/contacts.py:139`, `:152-168`, `:290-292`; `service/rep_intake.py` |
| `set_owner` records each owner change as an event carrying `previous_owner_id` and `new_owner_id` | `service/custody.py:56-57` |
| `contacts.created_at` defaults to the database's `now()` | migration `0001` |
| `clean_db` truncates a fixed list of tables; the test guard refuses any database not on an allowlist (`mailengine_dev`, `mailengine_test`) — fail-closed | `tests/conftest.py:109-113`; `tests/guard.py:16`, `:40` |
| The DNC files are read by the pull (to judge each upload) and the scrub (from local working copies). The pull re-lands an accepted file whose copy is missing, only for objects the upload Worker still lists as pending; a truncated listing is refused | `jobs/dnc_pull.py:60-81`, `:91-111`; `seams/snapshot_inbox.py:86-96` |
| The 31 days were checked against 16 CFR 310.4(b)(3)(iv) on 2026-09-13: "obtained from the Commission no more than thirty-one (31) days prior to the date any call is made" | git history of `docs/current-state.md` at `4b6d5b9` |

## 4. The design

### 4.1 The DNC status

`dnc_status(contact_id, at)` in a new `service/dnc.py`. `at` is a time-zone-aware
instant, handed in (the clock rule, part 1 §4.6); a naive `at` is refused (`bad_time`),
an unknown contact too (`no_contact`). The first that applies:

| # | The contact | Status |
|---|---|---|
| 1 | Has "don't call me again" in any recorded form (the **voice block**, below) | `do_not_call` |
| 2 | Has no phone | `no_phone` |
| 3 | Its area code has no subscription, and it came in before the start of the last completed daily scrub at or before `at` (§4.4) | `not_covered` |
| 4 | Its area code has no subscription, otherwise; or it was never checked; or its check is stamped after `at` | `not_checked` |
| 5 | Is on the DNC file (`dnc_registry`) | `on_dnc_file` |
| 6 | Its check is older than 744 hours, or the list behind it is more than 31 UTC days old (§4.2) | `check_too_old` |
| 7 | Otherwise | `clear` |

**The voice block** is any of the following, **not covered by a lift** (§4.7):

- `do_not_call`;
- a voice tombstone for the phone, or for the list key of any of its intake rows;
- its events make `is_suppressed` true (a `contact.opt_out` whose reason is not
  `do_not_mail`, a missing reason included);
- a **voice** `contact.suppressed` event on the contact — its `channel` absent, or
  anything but `mail` or `sms`;
- an unmatched `contact.opt_out` or voice `contact.suppressed` event carrying the phone
  (the matcher's rule, part 1 §4.2).

An event is **covered by a lift** when its id is at or below the latest lift's mark for
the contact or the phone (§4.7). Tombstones and the flag are removed by the lift itself.

- **Every form is read as currently recorded, whatever its recorded time** — a block
  recorded with a future time blocks now. Only freshness and row 3's run lookup use
  `at`.
- **Only `clear` may be called** as far as DNC goes (decision 4.1). "Failed" in 4.1 is
  row 5; a check that could not run leaves the old one, which becomes row 6.
- **The voice block covers everything part 1's intake row 3 refuses, and more** (the
  flagless voice `contact.suppressed`). The unmatched forms are read the way part 1
  reads unmatched opt-outs: their phones are computed in Python with the matcher's rule
  (`rep_intake._unmatched_phones`) and passed to the shared SQL as an array.
- **Row 6's "list behind it"** is the contact's linked snapshot, and only when that
  snapshot's area code is the phone's; a link to another code's list counts as none. The
  single-registry scrub, which does not link its list, runs only on dev and test
  databases (§4.10), so every check from the build on links the list of its verdict;
  checks made before the build are verified by §8.
- **Row 3 is decision 4.6** (answer 1). "Came in" is the later of `contacts.created_at`
  and the newest `intake_rep.added_at` for the contact, compared with the run's start: a
  contact a rep claims from NMC's list reads `not_checked` until the next run, like a new
  one. `added_at` is the caller's `at` and the run's start the database's clock; a skew
  between them can move a claim to `not_covered` a run early — harmless, both refuse.
- **Which SAN covers a code is not asked here.** A code any holder subscribes to counts
  as covered for every rep, as today (§6).

### 4.2 The 31 days (decision 4.2; 9.10; answer 3)

Kept as they are (answer 3, re-asked on the corrected fact): the list's age in whole
days on the UTC date, `version_date >= (UTC date of the moment) − 31`; the check's age as
an exact interval, written `make_interval(hours => 744)` so the session's time zone
cannot shift it (§3), equal to Python's `timedelta(days=31)`. Both err toward stale: the
UTC date is never behind a US date, and an exact interval never counts a partial day as a
whole one.

### 4.3 One rule, three readers

`service/dnc.py` holds the SQL for the voice block and for freshness, each over a
contact row and an explicit moment. Three readers:

- **`dnc_status`** (§4.1), with `at` handed in.
- **The assignment gate** (`service/assignment.py:134-160`), with `now()` as the moment.
  **Its causes and their order are unchanged**; one form is added: `voice_suppressed` is
  returned for `do_not_call` **or** any other form of the voice block except a
  tombstone — so a contact whose opt-out is only an event is refused before the nightly
  stage catches up. A tombstone, for the phone or any of the contact's list keys, gives
  `tombstoned`, in its place. Freshness is read from the shared SQL.
- **The export** (`service/assignment.py:324-338`), with `now()`: a contact is on the
  sheet only if none of the gate's DNC causes applies. **Its shape is unchanged:** a
  contact refused for the voice block, `dnc_registry`, or an unsubscribed code is dropped
  silently, as `do_not_call` and `dnc_registry` are today; a stale or never-checked one is
  in the shortfall as `dnc_stale`, as today. Today's export misses an unsubscribed code,
  a tombstone with no flag, an event-only opt-out, an unmatched opt-out or voice event,
  and a flagless voice `contact.suppressed` (§3); decision 6.6 keeps the export for the
  operator and for reps not on the app.

The frozen export invariant keeps every assertion and gains **new test functions**, with
their own pool (a second subscribed code, to unsubscribe, beside 818) and their own
oracle — a new function; the frozen `_forbidden_phones` is not edited — written
independently of `service/dnc.py` and `rep_intake`. They change a contact **after** it is
assigned — its code unsubscribed, a voice tombstone added, an opt-out recorded only as an
event, a flagless voice `contact.suppressed`, an unmatched opt-out carrying the phone —
each dropped from the sheet and absent from the shortfall. These additions are put to
the operator with the tests (§8).

### 4.4 The daily scrub records itself

A new table `dnc_runs` (§10), written by one verb, `record_scrub_run(started_at,
limited)` in `service/dnc.py` — `service/` stays the only write path. `dnc_refresh_all`,
the daily run's scrub, reads its start from the database's `now()` when it begins (the
database's clock, because row 3 compares it with `contacts.created_at`, which the database
stamps; a job is the outermost layer and may read a clock). It calls the verb when it
finishes; no row when it raises; a row when nothing is subscribed. The single-registry
`dnc_refresh` records nothing.

Status row 3 reads the latest `started_at` of an unlimited run at or before `at`. A run
still in progress has no row. The table holds only what part 2 reads; part 6 adds what
its job-status report needs (decision 2.8).

### 4.5 A rep's "don't call me again" (decisions 4.3; 9.8; answers 2, 7)

`report_do_not_call(rep, contact_id, reason, at)` in `service/dnc.py`. **Every real
report is recorded, and none is undone by the rep** (decision 4.3; decision 8.8,
"permanently"; answer 8).

| The call | Result |
|---|---|
| `at` has no time zone | refused `bad_time` |
| No contact has the id | refused `no_contact` (§6) |
| The contact has no phone | refused `no_phone` |
| The rep is unknown, or is the house (the house uses §4.6) | refused `bad_rep` |
| The rep does not hold the contact and never has — no owner-change event names them as its new owner, and no `intake_rep` row of theirs is on it | refused `not_yours` (answer 7) |
| Otherwise | `blocked` — whoever holds it now, active or inactive rep, whether or not it was already blocked |

One transaction, the contact row locked `for update`, every read taken under the lock,
through a helper shared with §4.6:

- `do_not_call = true` (already true is fine).
- A voice tombstone for the phone, with the primary list key when there is one,
  `created_at = at`.
- A `contact.suppressed` event, `occurred_at = at`, payload `{channel: voice, reason,
  reported_by: <rep>}`. `reason` defaults to "asked not to be called".
- **Custody does not change.** The rep who holds it keeps it (answer 2) and part 5 shows
  it in their Closed list; a contact another rep or the house holds stays where it is.
  Wherever it sits, every reader of the voice block refuses it, and part 5 takes it out
  of every holder's lists (decision 7.11).

A retry writes another event and tombstone: harmless, and after a lift it blocks the
number again — the safe side. `suppress()` is unchanged.

### 4.6 An admin's "don't call me again" (9.9)

`record_do_not_call_request(phone, reason, at)` in `service/dnc.py`, for a request that
reached NMC by email or phone:

| The call | Result |
|---|---|
| `at` has no time zone | refused `bad_time` |
| The reason is missing or blank | refused `no_reason` |
| A non-seed contact has the phone (as stored — any number `to_e164` accepts) | `blocked` through the helper of §4.5, no `reported_by`; custody unchanged |
| No contact has it, and `to_e164` rejects it | refused `invalid_phone` |
| No contact has it | a voice tombstone for the phone, `created_at = at`, nothing else — even for a number part 1's stricter rule rejects, because door A stores any number `to_e164` accepts |

Door B refuses the number from then on; door A creates it with `do_not_call` set
(`service/contacts.py:152-168`, `:290-292`). If a contact with the phone is created at the
same moment, it can land without the flag; the voice block reads the tombstone, and the
gate and the export read the voice block, so the number is refused everywhere.

### 4.7 An admin lifts a block (decision 4.4 as replaced; answer 8)

A rep who reported by mistake asks the operator. `lift_do_not_call(phone, reason, at)` in
`service/dnc.py` lifts **the whole voice block on the number** — every form, whoever
recorded it — because a person has judged that the business wants calls again.

| The call | Result |
|---|---|
| `at` has no time zone | refused `bad_time` |
| The reason is missing or blank | refused `no_reason` |
| `to_e164` rejects the phone | refused `invalid_phone` |
| Nothing blocks it | refused `not_blocked` |
| Otherwise | `lifted` |

One transaction. It takes `lock table events in share mode` — blocking new events until
it commits, so no event can slip under its mark — and locks the contact row with the
phone (non-seed), if one exists, `for update`. Then:

- `do_not_call = false` on that contact.
- Every voice tombstone for the phone, and for the list keys of that contact's intake
  rows, is deleted.
- A `contact.suppression_cleared` event, `occurred_at = at`, payload `{channel: voice,
  reason, lifted_by: admin}` (on the contact, or unmatched with the phone).
- A **`dnc_lifts`** row (§10): the phone, the contact, the reason, `at`, and the **mark**
  — the largest event id at that moment. Only this verb writes the table.

After a lift, events at or below its mark no longer count toward the voice block for the
contact or the phone; anything recorded afterwards — a new report, a new opt-out, a
retry — blocks again. A forged event can neither lift (the table, not an event, holds
the mark) nor escape one (it gets an id above the mark).

`clear_suppression` still refuses `voice`, and no `unsuppress` verb appears, so the
frozen tests at `test_suppression_split.py:200` and `test_contacts.py:139` stand. The
build updates, with the approved tests (§8), exactly these texts, each to name the one
exception — an admin's lift: `suppress()`'s docstring ("Permanent by design",
`service/contacts.py:426`); `clear_suppression`'s docstring ("the single public write
path", "rejects the permanent channels", `:504-507`) and its error message (`:511`); and
the matrix-row comment at `test_suppression_split.py:164` ("do_not_call … permanent").

The operator reaches §4.6 and §4.7 with a new command, `python -m jobs.dnc_admin_cli
block|lift <phone> --reason …`, which closes part 0's gap "cannot record an opt-out". The
website reaches them in part 6.

### 4.8 The files on Render (9.11)

Only the daily job reads DNC files (the pull to judge them, the scrub to check against
them); the service reads the columns the scrub wrote. So on Render the pull and the scrub
run in one job, as `daily-run.sh` runs them today. A Render job's disk is fresh each run,
so every run must re-land each code's newest accepted file; today the pull re-lands only
objects the Worker still lists as pending (`jobs/dnc_pull.py:91-95`) and refuses a
truncated listing (`seams/snapshot_inbox.py:86-96`). That is a requirement on hosting,
not built here (§6). It fails closed: a code with no working copy is skipped and its
contacts go stale.

### 4.9 The law (9.16, DNC half)

The 31 days stand as checked on 2026-09-13 (§3); §4.2 keeps both counts strict. The
calling-hours half of 9.16 is part 3's.

### 4.10 The single-registry scrub runs only on dev and test databases (answer 5)

`dnc_refresh` — the single-registry scrub, reached by `--fake`, `--snapshot`,
`scripts/dnc-daily.sh`, and `run_nightly` when handed a registry — reads
`current_database()` before its first write and runs only when the name is on an
allowlist of dev and test databases (`mailengine_dev`, `mailengine_test`); on any other it
raises. Fail-closed, as `tests/guard.py` is: production cannot slip past it by being
hosted under another name. Production scrubs only through `dnc_refresh_all`. The
allowlist is one module-level name, so the test replaces it and proves the refusal
without connecting to production (§7).

## 5. Part 1's hand-offs

| Part 1 left | Part 2 |
|---|---|
| Undoing a "don't call me again" (4.4) would leave the tombstone, so intake would keep refusing | Replaced: there is no rep undo; an admin's lift deletes the number's voice tombstones (§4.7) |
| A voice `contact.suppressed` recorded without the flag is not read by intake row 3 | The voice block reads it (§4.1); intake row 3 is part 1's and unchanged |
| A held contact returns to the house on a voice block | Part 2's verbs never move custody. `suppress(voice)` still does; it has no caller on the branch, and part 4 decides (§6) |

## 6. Gaps and limits

Gaps are not questions (decision 2.9).

| Gap or limit | Closed in |
|---|---|
| Nothing outside tests calls `dnc_status` or `report_do_not_call` | Parts 5 and 6 |
| The age of each area code's DNC file, for alerts (interface job 2) | Part 6, over `dnc_snapshots` and `dnc_runs` |
| A rep's own contact is taken back to the house on a DNC hit (`jobs/dnc_refresh.py:147-153`) and by `suppress(voice)` | Part 4 (decision 6.3) |
| A retried report writes another event and tombstone, not its first answer | Part 6 (decision 7.7) |
| Which SAN's subscription covers a code for which rep | Counsel (memo Q4); part 4 if it changes who may be given a code |
| A report queued on a phone (decision 8.7) whose contact has since been hard-deleted is refused `no_contact` | When a hard delete is built (FR-8): it must route such a report to §4.6 by phone |
| A hard delete (FR-8, not built) that removes events loses an event-only opt-out or flagless voice event, which have no tombstone; FR-8 must write a voice tombstone for each | When a hard delete is built |
| The gate and the export read tombstones, events, and unmatched phones outside the row lock (their statement's first snapshot): an opt-out landing mid-batch is not seen by that batch; the next one sees it, and the status reads it at call time | Left: as part 1's intake |
| A sheet passes the 31-day check when it is pulled; a rep not on the app may dial from it later, past 31 days | Left: the export's rule "re-pull before each session" (`service/assignment.py:311-317`); reps on the app are checked at every call (part 5) |
| `clear_suppression(contact, 'dnc_registry')` clears a registry verdict with no check and no list; only the scrub calls it | Left: part 6 must not expose it |
| The re-landing of each code's newest DNC file on every run (§4.8) | Hosting (9.11) |
| `dnc_status` trusts the `at` it is handed | Parts 5 and 6 pass the server's clock (decision 7.6) |
| Part 5's wrong-number replacement (9.14) changes a phone: the new phone must be checked again | Part 5; §4.1 row 6's area-code match refuses a verdict linked to another code |
| The console's inventory counts do not read the voice block | Left: an operator view, not a path to a call |
| Door B (part 1) still claims a contact whose only block is a flagless voice `contact.suppressed`; the rep holds a number the status refuses | Left: the status, the gate and the export refuse it |
| A mistaken report stays until the operator lifts it | Answer 8: the operator's call |

## 7. Tests, written first

`clean_db` gains `dnc_runs` and `dnc_lifts` in its truncate list (`tests/conftest.py`). The
verbs have a no-op hook inside their transaction, after the row lock, for the locking
tests to pause at — as part 1's `rep_intake._before_insert`.

| Test | Checks |
|---|---|
| The voice block, each form, in each reader | `do_not_call`; a voice tombstone on the phone; one on a list key but not the phone; an opt-out event with a reason, and with none; an unmatched opt-out under `phone_e164`, and as `(818) 555-0123` under `phone`; an unmatched voice `contact.suppressed`; a flagless voice `contact.suppressed` — each gives `do_not_call` in `dnc_status`, a refusal by the gate (`voice_suppressed`, or `tombstoned` for a tombstone), and absence from the export |
| A future time | A flagless opt-out recorded with an `occurred_at` a day ahead: `do_not_call` now, in the status, the gate and the export |
| Status 2 to 7 | The status; a naive `at` refused; an unknown contact refused |
| The order | status 1 + on the DNC file → `do_not_call`; not covered + on the DNC file → `not_covered`; on the DNC file + stale → `on_dnc_file`; no phone + unsubscribed → `no_phone`; unsubscribed + never checked + before the last run → `not_covered` |
| Not covered after the run | A contact in an unsubscribed code: `not_checked`; `dnc_refresh_all` completes; `not_covered`. A contact created, or claimed by a rep, after that run began: `not_checked`. An `at` before the run: `not_checked`. A `--limit` run or a single-registry run does not count |
| Runs | `dnc_refresh_all` writes one row when it finishes, one when nothing is subscribed, none when it raises; `dnc_refresh` writes none |
| The 31 days | Through `dnc_status` and the shared SQL with an explicit moment: the check a minute inside 744 hours fresh, a minute past stale, including across a daylight-saving change under `PGTZ=America/Los_Angeles`; the list 31 UTC days old fresh, 32 stale, under `PGTZ` at UTC+14 and UTC−11. Through the gate and the export with `now()`: the same, without the daylight-saving case. A check stamped after `at`: `not_checked` for `at` |
| A link to another code's list | Reads as if unlinked |
| The gate | Every existing cause name and order unchanged; an event-only opt-out on a released contact → `voice_suppressed` before any recompute |
| The export | Assigned, then each form of §4.3's additions: none on the sheet, none in the shortfall; the existing frozen assertions unchanged |
| Report | Each refusal, nothing written; by the holder (keeps it; one tombstone, one event); by a rep who held it and lost it (recorded); held by another rep, and by the house (custody unchanged); on an already blocked contact (another event and tombstone); from an inactive rep (recorded); a rep who never held it → `not_yours` |
| Admin request | Each refusal; with a contact a rep holds: blocked, custody unchanged; a contact whose stored phone part 1's rule rejects: blocked; without a contact: a tombstone, no contact; door B refuses; door A creates it with `do_not_call` |
| Lift | Each refusal. A number with a report, an old opt-out event, a list-key tombstone, and an unmatched opt-out → lifted: flag false, every voice tombstone for the phone and its list keys gone, one `dnc_lifts` row with the mark, status not `do_not_call`, the gate and the export admit it, intake no longer refuses. Then a new report → `do_not_call` again. A lift on a number with no contact, then door A creates it: no flag |
| Forgery | An ingested `contact.suppression_cleared` naming anything lifts nothing; an event ingested after a lift blocks |
| Locking | A report paused at its hook while `assign_batch` waits: the batch refuses (`do_not_call` on the locked row, re-read after the wait). A report paused while `add_numbers` waits: `do_not_call` (its judging statements run after the lock). A lift paused at its hook while `ingest_event` writes an opt-out on another connection: the event waits, gets an id above the mark, and blocks |
| The clock | `occurred_at` of every event, `created_at` of every tombstone, and `lifted_at` of every lift the new verbs write equal `at` |
| The operator's command | `jobs.dnc_admin_cli` blocks and lifts, with and without a contact, and refuses a blank reason |
| The single-registry scrub | With the allowlist replaced so that `mailengine_test` is not on it, `dnc_refresh` raises and writes nothing; restored, it runs. No test connects to any database but `mailengine_test` |
| Frozen tests | Every existing assertion passes; the export invariant gains new functions (§4.3); the edited docstrings and `:164` comment (§4.7) change no assertion |

## 8. Done means

| Check | How |
|---|---|
| The build follows the red-tier gate: the gate and the export change, suppression verbs, tombstone deletes, a migration | Build plan approved first; the tests — including the export invariant's new functions and the edited suppression comment — approved as its first step |
| The tests of §7 pass; every existing assertion passes unchanged | `make test` |
| `make e2e`, `make lint` | Pass |
| `0015` changes no existing row on production-shaped data | As part 1's §8 check, from a checkout without `0015` |
| On production-shaped data, read-only: every contact in a subscribed code has a link, the link's area code is the phone's, and the latest `contact.dnc_checked` event's `snapshot_id` equals the link; and a count of contacts the new rules refuse that today's gate does not | Before the build ships; any mismatch is put to the operator |

## 9. For the operator

| # | Question | Answer |
|---|---|---|
| 1 | How "not covered" appears (4.6) | **Answered 2026-09-30:** after the next daily run — the run is recorded; before it, `not_checked`. Offered "After the next daily run", "Immediately", or "Never say it". |
| 2 | After a rep's "don't call me again", does the rep keep the contact (9.8) | **Answered 2026-09-30:** the rep keeps it, Closed. Offered "Rep keeps it, Closed" or "Back to NMC". |
| 3 | How the 31 days are counted (9.10) | **Answered 2026-09-30:** whole UTC days for both. **Re-asked 2026-09-30:** the question had said UTC-date counting errs toward stale; for the check's age it can make a check up to about a day younger. Offered "Keep as is", "Whole days + require a list", or "Whole days, as answered"; chose keep as is. |
| 4 | The undo and the report's tombstone (4.4) | **Answered 2026-09-30:** the undo removes that tombstone. **Superseded by answer 8:** there is no rep undo. |
| 5 | The single-registry scrub can read `clear` on an old list or none | **Answered 2026-09-30:** it refuses to run on production — built as an allowlist of dev and test databases (§4.10). Offered "Refuse it on production", "Require a recorded list", or "Leave it, record the limit". |
| 6 | Two reps report one number: who may undo | **Answered 2026-09-30:** each can withdraw their own. **Superseded by answer 8:** there is no rep undo. |
| 7 | Who may report | **Answered 2026-09-30:** a rep who holds the contact or held it (§4.5). Offered "Holds it, or held it", "Any known rep", or "Only the current holder". |
| 8 | Replace the rep's 24-hour undo (4.4) with an admin-only lift | **Answered 2026-09-30:** the admin lifts it — no rep undo; the operator lifts the whole block by hand with a written reason (§4.7). Offered "Admin lifts it", "No undo at all for now", or "Keep the 24h rep undo". |

**The design's own answers**, for approval with the part (each has one obvious reading):

| Point | Answer |
|---|---|
| 9.9, an admin's request with no contact | A voice tombstone only (§4.6) |
| 9.11, the files on Render | Pull and scrub in one job; the service reads no file; hosting re-lands each code's newest file every run (§4.8) |
| 9.16, the 31 days | As checked 2026-09-13 (§4.9) |
| Custody | No verb of part 2 moves it (§4.5) |
| A retry of a report | Writes another event and tombstone (§4.5) |
| What a lift covers | The whole voice block on the number, every form, whoever recorded it (§4.7) |
| How a lift covers events | A mark — the largest event id, taken with new events held back — recorded in a table only the lift writes (§4.7) |
| "Came in" for status row 3 | The later of `contacts.created_at` and the newest `intake_rep.added_at` (§4.1) |
| The check's 31 days | `make_interval(hours => 744)` (§4.2) |

## 10. The migration, `0015.dnc-filtering.sql`

```sql
create table dnc_runs (
  id          uuid primary key default gen_random_uuid(),
  started_at  timestamptz not null,
  limited     boolean not null
);

create index dnc_runs_started_idx on dnc_runs (started_at);

create table dnc_lifts (
  id          uuid primary key default gen_random_uuid(),
  phone_e164  text not null,
  contact_id  uuid,
  reason      text not null check (btrim(reason) <> ''),
  lifted_at   timestamptz not null,
  mark        bigint not null
);

create index dnc_lifts_phone_idx on dnc_lifts (phone_e164);
create index dnc_lifts_contact_idx on dnc_lifts (contact_id);

grant select on dnc_runs, dnc_lifts to me_user_ro;
```

Additive. `dnc_lifts.contact_id` carries no foreign key, so a lift outlives a hard delete
of its contact, as a tombstone does. The explicit grant does not rely on `0002`'s default
privileges.

## 11. Proposed changes to the decision record

| Record item | Proposed change |
|---|---|
| 4.4 | Replace: no rep undo; the operator lifts a block by hand, with a written reason, for the whole number (answer 8). Move the 09-28 wording to §10 |
| 9.8 | Decided: the reporting rep, if they hold it, keeps the contact, Closed (answer 2) |
| 9.9 | Decided: a voice tombstone only (§9, design answer) |
| 9.10 | Decided: the list in whole UTC days, the check as an exact interval (answer 3); written as 744 hours (§9, design answer) |
| 9.11 | Decided for part 2: pull and scrub in one job; hosting must re-land each code's newest file on every run (not yet built) |
| 9.16 (DNC half) | Decided: the 31 days as checked against 16 CFR 310.4(b)(3)(iv) on 2026-09-13 |
| 4.3 | Add: every report is recorded, whoever holds the contact; a rep may report a contact they hold or have held (answer 7); no report moves custody |
| 4.6 | Add: "after the check" is after the next completed daily run (answer 1) |
| 4.1 | Add: production scrubs only through the ledger path; the single-registry scrub runs only on named dev and test databases (answer 5) |

## 12. Safety properties

Every revision is checked against these before review. Each names where the design keeps
it.

| # | Property | Kept by |
|---|---|---|
| S1 | A number with "don't call me again" in any recorded form is never `clear`, never assigned, never exported — until an admin lifts it | The voice block (§4.1), read by all three readers (§4.3); the lift (§4.7) |
| S2 | Nothing but an admin's lift clears a voice block, and a lift is always on the record with a reason | §4.7; `clear_suppression` still refuses `voice`; forged events clear nothing |
| S3 | Every real request is recorded | A report is refused only for a missing contact or phone, a naive time, an unknown rep or the house, or a rep who never had the contact (§4.5); an admin's request is recorded even with no contact (§4.6) |
| S4 | A check is `clear` only against a list no more than 31 days old, linked to its verdict | Freshness (§4.2), the area-code-matched link (§4.1 row 6), the single-registry scrub confined to dev and test (§4.10) |
| S5 | The export refuses whatever the status refuses, and keeps its frozen shape | §4.3 |
| S6 | No test connects to any database but the test database; nothing fake-scrubs production | §4.10, §7 |
| S7 | A claim that something is safe or unchanged is checked against the code or the tests before it is written | The process of this revision |
