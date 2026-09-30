# contact-engine Upgrade — Part 2: DNC filtering

**Status:** DRAFT, revision 18, 2026-09-30. Revision 16 was approved after fifteen
reviews; the operator then questioned why the design took so long and asked for a
simpler approach. This revision keeps every approved rule and answer and replaces the
machinery underneath: **one record of "don't call me again", keyed by phone**, written by
every path that blocks and read by every place that decides. Revision 17's review found
no design hole (one test pointed the unsafe way; twelve minor findings); revision 18
applies them. Not yet re-reviewed, not approved (revision 16's approval is superseded until this one is approved). Nothing is
built. Revisions 1–16, with the options offered for every answer, are in git history.
**Part of:** [the upgrade](00-overview.md). Decisions are in the decision record,
`nvermisscall/docs/active/sales-partner-dialer-decisions.md`, named here by number
("decision 4.1"); sections of this document are named "§4.1".
**Checked against:** the `contact-engine` branch at `ea5215b` (parts 0 and 1 built; code
unchanged since `c3179da`). A statement about the code carries its file and line.

---

## 1. Its job

Say whether a number is clean to call, and why not; make the assignment gate, the
export, and door B refuse what that says; take a "don't call me again"; and let an admin
lift one recorded by part 2's own verbs.

| Decision | What it asks |
|---|---|
| 4.1 | Every number is checked, NMC's and a rep's alike. Unchecked, failed, or not covered: no call. |
| 4.2 | A check is good through day 31; day 32 is stale. |
| 4.3 | "Don't call me again" blocks the number for every rep at once. |
| 4.4 | *As decided 09-28:* the reporting rep can undo it within 24 hours. *Replaced 2026-09-30 by answers 8 and 9:* no rep undo; an admin lifts, by hand with a written reason, blocks recorded by part 2's verbs. |
| 4.5 | DNC files stay files; their upload is unchanged. |
| 4.6 | The rep is told an area code is not covered only after the check. |

Open items it settles: 9.8, 9.9, 9.10, 9.11, and the DNC half of 9.16.

## 2. Its edges

| Part 2 does | Part 2 does not — who does |
|---|---|
| The DNC status of a contact, with its reason (§4.1) | Decide "may I call now": that adds calling hours (part 3) and the sequence (part 5) |
| The one record of "don't call me again" (§4.2), read by the gate, the export, and door B (§4.4) | Put the contact in a Closed list — part 5 (decisions 7.5, 7.11) |
| A rep's report (§4.5), an admin's request (§4.6), an admin's lift (§4.7) | Remember a request for 90 days so a retry returns its first answer (decision 7.7) — part 6 |
| Record each completed daily scrub (§4.3) | Expose any of it from outside, or raise an alert — part 6 and the website (decision 1.7) |
| | Download or upload DNC files — unchanged (decision 4.5); change who holds a contact — part 4 |

## 3. What exists, checked

| Fact | Where |
|---|---|
| The daily scrub checks contacts in subscribed area codes never checked or checked over 21 days ago; a hit sets `dnc_registry`; a delisting clears it. Its daily form `dnc_refresh_all` links each checked contact to its snapshot; the single-registry `dnc_refresh` (`--fake`, `--snapshot`, `scripts/dnc-daily.sh`, `run_nightly` handed a registry) stamps a check without linking the list it used | `jobs/dnc_refresh.py:80-96`, `:106-169`, `:137-139`, `:172-200`, `:239-278`; `jobs/nightly.py:19-24`; `config/params.py:19` |
| In production every contact in a subscribed code links a snapshot (24,212 of 24,212 on 2026-09-13); the five subscribed codes are 714 · 760 · 805 · 818 · 916 | git history of `docs/current-state.md` at `4b6d5b9` |
| Freshness in the gate and the export: the check `>= now() − make_interval(days => 31)`, and, when linked, the snapshot's `version_date >= (UTC date) − 31` | `service/assignment.py:120-131`, `:328-331`; `config/params.py:33` |
| The gate's causes, in order: `seed`, no phone, `already_assigned`, `won`, mid-funnel (a non-assignable stage, `suppressed` included), `voice_suppressed` (`do_not_call`), `dnc_registry`, `tombstoned` (a voice tombstone for the phone), `dnc_unsubscribed`, `dnc_stale` — pinned by frozen tests | `service/assignment.py:134-160`; `tests/acceptance/test_partner_assignment.py:243`; `tests/acceptance/test_export_compliance_invariant.py:160-163` |
| The export drops `do_not_call` and `dnc_registry` contacts silently and reports stale ones as `dnc_stale`; it does not read the subscription or tombstones. The frozen invariant pins the shortfall as exactly `{dnc_stale: …}` and flips `do_not_call` and `dnc_registry` after assignment | `service/assignment.py:324-338`, `:351-356`; `tests/acceptance/test_export_compliance_invariant.py:170-196` |
| "Don't call me again" is recorded today in several forms: the `do_not_call` flag; voice tombstones (by phone, or by list key only); `contact.opt_out` events (with or without a reason; pre-`0010` ones set no flag); voice `contact.suppressed` events; events unmatched, or attached to another contact, that carry a phone | `service/contacts.py:421-494`; migration `0010`; `derivation/rules.py:66-79`; `resolution/matcher.py:47-69` |
| `ingest_event` accepts any taxonomy type and payload; in the code its callers are `record_note` (note types) and `record_outcome` (`contact.lost`); tests use it to create opt-outs. `resolve_orphans` later sets `contact_id` on unmatched events | `service/ingestion.py:94-115`, `:118-135`, `:170-219`; `service/contacts.py:527-540`; `tests/acceptance/test_suppression_split.py:489` |
| `suppress()` writes the flag, an event, and tombstones, and returns a held contact to the house; it has no caller on the branch. `clear_suppression` refuses `voice` — pinned; no `unsuppress` verb — pinned | `service/contacts.py:421-524`; `tests/acceptance/test_suppression_split.py:200`; `tests/acceptance/test_contacts.py:139` |
| Door A sets `do_not_call` on a new contact when a voice tombstone matches its phone or list key. Door B refuses a phone tombstone, the flag, the contact's opt-out events, and unmatched opt-outs carrying the phone | `service/contacts.py:152-169`, `:290-292`; `service/rep_intake.py` `_judge` |
| `set_owner` records each owner change with `new_owner_id` | `service/custody.py:56-57` |
| The 31 days were checked against 16 CFR 310.4(b)(3)(iv) on 2026-09-13 | git history of `docs/current-state.md` at `4b6d5b9` |

## 4. The design

### 4.1 The DNC status

`dnc_status(contact_id, at)` in a new `service/dnc.py`; `at` is time-zone-aware, handed in
(a naive `at`: `bad_time`; an unknown contact: `no_contact`). The first that applies:

| # | The contact | Status |
|---|---|---|
| 0 | Is a seed | `seed` |
| 1 | Is **blocked**: its phone has a live row in `dnc_numbers` (§4.2), or it has `do_not_call`, or a voice tombstone is on its phone | `do_not_call` |
| 2 | Has no phone | `no_phone` |
| 3 | Its area code has no subscription, and it came in before the start of the last completed daily scrub at or before `at` (§4.3) | `not_covered` |
| 4 | Its area code has no subscription, otherwise; or it was never checked; or its check is stamped after `at`; or its link is not to an accepted snapshot of its own area code | `not_checked` |
| 5 | Is on the DNC file (`dnc_registry`) | `on_dnc_file` |
| 6 | Its check is older than `at − 31 days`, or its linked list is more than 31 UTC days old | `check_too_old` |
| 7 | Otherwise | `clear` |

- Only `clear` may be called as far as DNC goes (decision 4.1). "Failed" is row 5.
- **The 31 days are kept exactly as they are** (answer 3): the list in whole days on the
  UTC date; the check as today's `make_interval(days => 31)`. The legal wall is the
  list's age; the UTC date is never behind the date in any US zone west of UTC.
- **Row 3 is decision 4.6** (answer 1). "Came in" is the later of `contacts.created_at` and
  the newest `intake_rep.added_at`, so a number a rep claims waits for the next run too.
- **Row 4's link rule**: a link counts only to an `accepted` snapshot whose `area_code` is
  not distinct from the phone's and whose `version_date` is not null; a contact with no
  link is judged on its check's age alone (answer 3). The single-registry scrub, which
  writes no link, runs only on dev and test databases (§4.8).

### 4.2 One record: `dnc_numbers`

A phone is **blocked** when it has a live row in `dnc_numbers` (§10) — one row per phone,
`blocked` true or false — kept beside an append-only `dnc_log` of every block and lift:
its kind, who, why, when. Every path that blocks writes the row:

| Path | How | Kind in the log |
|---|---|---|
| A rep's report (§4.5); an admin's request (§4.6) | Directly, through one helper | `rep` / `admin` |
| Any `contact.opt_out` whose reason is not `do_not_mail` (absent counts), or `contact.suppressed` whose channel is not `mail` or `sms` (absent counts), inserted by **any** code — `suppress()`, `ingest_event`, a test | A trigger on `events`, after insert: for the event's contact's phone and each phone the event carries | `event` |
| Those events when `resolve_orphans` later attaches one to a contact | The same trigger, after update of `events.contact_id`: for the newly attached contact's phone | `event` |
| Door A applying a voice tombstone to a contact — creating it with the flag, or attaching a list row whose key has one (`service/contacts.py:152-169`, `:256-266`, `:290-292`) | Door A upserts the row in the same transaction | `intake` |
| Everything recorded before `0015` — flags; voice tombstones by phone, or by list key resolved to phones through intake rows; qualifying events and their carried phones | A one-time backfill in `0015` | `backfill` |

A **carried phone** is `payload->>'phone_e164'` and `payload->>'phone'` — the text form,
so a JSON number counts — each normalized as `to_e164` does (digits only; eleven with a
leading 1 lose it; ten become `+1` and the ten), by one SQL function the trigger and the
backfill share. A payload that is not an object carries no phone — **but an event of a
qualifying type attached to a contact still blocks the contact's phone**: its reason or
channel reads as absent, and absent counts. Phones are stored as the contact has them;
`dnc_numbers` does not reject an unusual form, so no block is lost to a format check.
The trigger locks the phones it touches in sorted order.

So **every "don't call me again", however recorded and whatever it is later attached to,
turns its phone's row on**, and only a lift (§4.7) turns it off. The flag and voice
tombstones are still read directly too (§4.1 row 1): a test or other code can set them
without a row, and such a phone is blocked all the same, and never liftable (§4.7).

### 4.3 The daily scrub records itself

A table `dnc_runs` (§10), written by one verb, `record_scrub_run(started_at, limited)`.
`dnc_refresh_all` reads its start from the database's `now()` in the job module and calls
the verb when it finishes, a row also when nothing is subscribed; no row when it raises.
The single-registry scrub records nothing. Status row 3 reads the latest unlimited run at or before `at`.

### 4.4 The readers

One SQL fragment in `service/dnc.py` — "blocked" (§4.1 row 1) and freshness (rows 4, 6)
over a contact row and an explicit moment — read by:

- **`dnc_status`**, with `at`.
- **The assignment gate** (`service/assignment.py:134-160`), with `now()`. Causes and order
  unchanged: `voice_suppressed` for `do_not_call` **or** a live row; `tombstoned` as
  today; `dnc_stale` also covers row 4's link rule. After its `for update` lock the gate
  re-reads the live rows for its candidates' phones **in a second statement**, as door B
  does — a report locks the contact but does not update it, so the locked re-read alone
  would not see a block that landed while the gate waited.
- **The export** (`service/assignment.py:324-338`), with `now()`, shape unchanged: a
  blocked, registry-listed, or unsubscribed contact is dropped silently; a stale,
  never-checked, or wrongly linked one is in the shortfall as `dnc_stale`. Blocked,
  registry, and subscription are checked before freshness.
- **Door B** (part 1's `rep_intake._judge` row 3): also refuses `do_not_call` when the
  phone has a live row, on both paths — a phone with a contact, and a new phone. Its
  existing checks stay; they only ever refuse more.

The frozen export invariant keeps every assertion and gains new test functions, with their
own pool and oracle: contacts assigned first, then blocked by each path of §4.2, and a code
unsubscribed; none reaches the sheet or the shortfall.

### 4.5 A rep's "don't call me again" (decisions 4.3; 9.8; answers 2, 7)

`report_do_not_call(rep, contact_id, reason, at)`:

| The call | Result |
|---|---|
| `at` has no time zone | refused `bad_time` |
| No contact has the id / it has no phone | refused `no_contact` / `no_phone` |
| The rep is unknown, or is the house | refused `bad_rep` |
| The rep does not hold the contact and never has (no owner-change event names them as new owner; no `intake_rep` row of theirs) | refused `not_yours` (answer 7) |
| Otherwise | `blocked` |

Through **the block helper**, one transaction: lock the contact row, then the phone's
`dnc_numbers` row (created if absent), `for update`; set `blocked = true`; append a
`dnc_log` row — kind `rep`, the rep, the contact, the reason (blank becomes "asked not to be
called"), `at`. Nothing else: no flag, no tombstone, no event — the row blocks in every
reader, it outlives a hard delete of the contact (it is keyed by phone), and the log is the
record. **Custody does not change** (answer 2): the holder keeps the contact; part 5 takes
it out of every holder's lists (decision 7.11). A retry is another log entry on a blocked
phone: harmless.

### 4.6 An admin's "don't call me again" (9.9)

`record_do_not_call_request(phone, reason, at)`: refused `bad_time`, `no_reason`, or
`invalid_phone` (`to_e164` rejects it, or the result is not `+1` and ten ASCII digits).
Otherwise through the block helper, kind `admin`, locking the non-seed contact with the
phone if there is one. A number with no contact is blocked all the same: its row is keyed
by the phone, and every reader reads it — for a contact door A later creates, and for a
new number at door B.

### 4.7 An admin's lift (decision 4.4 as replaced; answers 8, 9)

The operator reads `dnc_history(phone)` — the phone's `dnc_log`, each entry with its `seq`
— and calls `lift_do_not_call(phone, seen_seq, reason, at)`:

| The call | Result |
|---|---|
| `at` has no time zone / blank reason / invalid phone | refused `bad_time` / `no_reason` / `invalid_phone` |
| The phone has no live row | refused `nothing_to_lift` |
| `seen_seq` is not the phone's latest log entry | refused `changed` — the operator reads it again |
| The phone's log has any entry of kind `event`, `intake`, or `backfill`, or the phone has a voice tombstone, or a contact with the phone has `do_not_call` | refused `not_liftable` — the number was blocked some way other than part 2's verbs (answer 9); it stays blocked |
| Otherwise | `lifted` |

One transaction: lock the non-seed contact with the phone, if any, then the phone's
`dnc_numbers` row, `for update` — the helper's order — and make the checks on reads taken
under those locks. Then `blocked = false`, and a `dnc_log` row of kind `lift` with the
reason, `at`, and the operator's name as actor.

**Why this is safe.** Every block of any kind turns the row on and leaves a log entry
(§4.2), so nothing blocks the phone that the log does not show. A lift proceeds only when
the log holds nothing but the verbs' own blocks, all seen by the operator, and nothing else
— no flag, no tombstone — marks the phone; so turning the row off is the whole reversal.
Anything recorded while the lift holds the row lock waits, then lands after it as a new
entry and a live row. `suppress()` is untouched and its blocks are never liftable, so
`clear_suppression` and the frozen permanence tests need no change.

The operator reaches §4.6 and §4.7 with `python -m jobs.dnc_admin_cli block <phone>
--reason …`, `history <phone>`, and `lift <phone> --seen N --reason …`; each asks for the operator's
name as the actor, as `assignment_cli` does.

### 4.8 The single-registry scrub runs only on dev and test databases (answer 5)

`dnc_refresh` reads `current_database()` before its first write and runs only on an
allowlist (`mailengine_dev`, `mailengine_test`), else raises. The allowlist is one
module-level name, which the test replaces; no test connects to production.

### 4.9 The files on Render (9.11)

Only the daily job reads DNC files; the service reads columns. On Render the pull and the
scrub run in one job; a fresh disk each run means every run must re-land each code's
newest accepted file — a requirement on hosting, not built here. It fails closed.

## 5. Part 1's hand-offs

| Part 1 left | Part 2 |
|---|---|
| Undoing a "don't call me again" would leave the tombstone | No rep undo; the admin's lift turns off the row, and nothing else marks a liftable phone (§4.7) |
| Door B does not read every form | Door B reads the one record (§4.4) |
| A held contact returns to the house on a voice block | Part 2's verbs never move custody |

## 6. Gaps and limits

| Gap or limit | Closed in |
|---|---|
| Nothing outside tests calls `dnc_status` or the verbs | Parts 5 and 6 |
| The age of each code's DNC file, for alerts | Part 6, over `dnc_snapshots` and `dnc_runs` |
| A rep's own contact is taken back to the house on a DNC hit, and by `suppress(voice)` | Part 4 (decision 6.3) |
| A retried report writes another log entry, not its first answer | Part 6 (decision 7.7) |
| Which SAN's subscription covers a code for which rep | Counsel (memo Q4) |
| A number blocked by an event, by the backfill, or by a flag or tombstone can never be lifted | Answer 9 |
| An event carrying only a mailer code blocks nothing until `resolve_orphans` attaches it, when the trigger blocks the contact's phone | Part 6's event intake: attach at once |
| A tombstone keyed only by list key whose intake rows carry no phone blocks no phone until door A applies it — creating a contact, or attaching a list row with that key, which writes the row (§4.2) | Left: identity is never fuzzy |
| The gate and the export read in their statement's snapshot: a block landing mid-batch is seen by the next; the status reads it at call time | Left |
| A sheet passes the check when pulled; a rep off the app may dial from it later | Left: "re-pull before each session"; reps on the app are checked at every call (part 5) |
| Re-landing each code's newest file on every run on Render | Hosting (9.11) |
| `dnc_status` trusts the `at` it is handed | Parts 5 and 6 pass the server's clock (decision 7.6) |
| A phone change (9.14): the new phone must be checked again, and the contact's block must be carried to it — the row is keyed by the old phone | Part 5 |
| NANP codes east of UTC (670, 671) | Before any is subscribed |
| Lock cycles across events: `resolve_orphans` attaching several events, or two `ingest_event` calls on crossing phones, can deadlock; Postgres aborts one, which its caller retries (the nightly re-runs the next day) | Left; the trigger's sorted order removes the cycle within one event |
| The operator console's "dialable" counts (`jobs/console.py:45-48`, `:397-400`) ignore `dnc_numbers` | Left: an operator view, not a path to a call |

## 7. Tests, written first

`clean_db` and the other truncates that restart event ids (`tests/e2e/test_partner_journey.py`,
`tests/acceptance/test_grain_intake.py`) gain `dnc_numbers`, `dnc_log`, `dnc_runs`; tests that
delete their reps delete those reps' `dnc_log` rows first. The backfill is a SQL function
`0015` creates and calls once, so tests can call it on a fixture.

| Test | Checks |
|---|---|
| Each path writes the row | For each path of §4.2, the `dnc_numbers` row is live and its log entry has the right kind — asserted directly, not through a reader: a report; an admin request with and without a contact; `suppress(voice)` (`event`); an `ingest_event` opt-out with a reason, with none, and with a non-object payload on a contact; a `contact.suppressed` with no channel; an unmatched opt-out carrying the phone as `phone_e164`, as `(818) 555-0123`, and as a JSON number; one attached by `resolve_orphans` to another contact; door A creating and attaching from a tombstone (`intake`) |
| Each reader refuses a live row | A live row alone — no flag, no tombstone — makes `dnc_status` read `do_not_call`, the gate refuse `voice_suppressed`, the export (row turned on after assignment, by a raw qualifying event) drop it, door B refuse an existing contact's phone, and door B refuse a new number |
| Not blocks | A `do_not_mail` opt-out; a `contact.suppressed` with channel `mail`; an **unmatched** event with a non-object payload: no row, no crash |
| The backfill | On a fixture holding every legacy form: a live `backfill` row for each blocked phone, none for others; list-key tombstones resolved through intake rows |
| Status 0–7, their order | Each status; `not_covered` only after a run; the link rule; the 31 days a minute either side, unchanged from today |
| Report | Each refusal writes nothing; by the holder, by a rep who held it, on a blocked phone; custody unchanged; no flag, tombstone, or event written |
| Lift | Each refusal writes nothing; `changed` for an entry after `seen_seq`; `not_liftable` for an `event` or `backfill` entry, a tombstone, or a flag; lifted: row off, a `lift` entry, every reader admits the number; then a new report blocks it again |
| Locking | A report, or an `ingest_event` opt-out, waiting on the phone's row while a lift holds it: after the lift, the phone is blocked again. A report committing while `assign_batch` waits on the contact: the batch's second read refuses it. A report racing `add_numbers`: refused after. Two events crossing phones in one trigger call: no deadlock |
| Lift, strictness | `seen_seq` below the latest, or another phone's `seq`: `changed`. An `intake` entry: `not_liftable`. The lift's log entry names the actor |
| The single-registry scrub | Allowlist replaced: raises, writes nothing; restored: runs |
| Frozen tests | Every existing assertion passes; the export invariant gains new functions |

## 8. Done means

| Check | How |
|---|---|
| Red-tier gate: the gate and export change, a trigger, a backfill over real data, a migration | Build plan approved first; the tests — including the frozen export invariant's new functions and the truncate lists — approved as its first step |
| The tests of §7; `make test`, `make e2e`, `make lint` | Pass |
| `0015` on production-shaped data | From a checkout without it: existing rows unchanged; the backfill's count by source form; every phone the old gate refuses by flag or tombstone, every phone the old door B would refuse by an event, and every carried phone of a qualifying event has a live row; the trigger is created before the backfill runs, in the same transaction |
| On production, read-only, by the operator | Every checked contact in a subscribed code links an accepted snapshot of its own code; phones in contacts, tombstones, and intake rows that are not `+1` and ten ASCII digits are listed |

## 9. For the operator

| # | Question | Answer (all 2026-09-30; options offered are in revision 16) |
|---|---|---|
| 1 | How "not covered" appears (4.6) | After the next daily run (§4.1 row 3) |
| 2 | After a rep's report, does the rep keep the contact (9.8) | The rep keeps it, Closed |
| 3 | How the 31 days are counted (9.10) | Keep as is — re-asked on a corrected fact |
| 4 | The undo and its tombstone | Superseded by answer 8 |
| 5 | The single-registry scrub | Refuses production — built as an allowlist (§4.8) |
| 6 | Two reps' undos | Superseded by answer 8 |
| 7 | Who may report | A rep who holds or held the contact |
| 8 | Rep undo → admin lift | No rep undo; the admin lifts by hand with a reason |
| 9 | What a lift covers | Only blocks recorded through part 2's verbs; any other block stays |

**The design's own answers**, for approval with the part:

| Point | Answer |
|---|---|
| One record | `dnc_numbers` + `dnc_log`, written by the helper, door A, a trigger on `events`, and a one-time backfill (§4.2) |
| The trigger | The schema's first trigger, and a write path outside `service/` — named as the one exception to "`service/` is the only write path", because it must catch every writer of an event, the tests' included |
| What the helper writes | The row and a log entry only — no flag, tombstone, or event (§4.5) |
| What a lift requires | Nothing but the verbs' own blocks in the log, all seen (`seen_seq`), and no flag or tombstone on the phone (§4.7) |
| 9.9, an admin request with no contact | The row and a log entry; the row is keyed by phone (§4.6) |
| 9.11 | Pull and scrub in one job; hosting re-lands files (§4.9) |
| 9.16, the 31 days | As checked 2026-09-13 against 16 CFR 310.4(b)(3)(iv) (§3) |
| Custody | No verb of part 2 moves it |
| A link to another code's list, or to a rejected snapshot | `not_checked` |
| Door B | Reads the one record on both paths (§4.4) — a change to part 1's code |

## 10. The migration, `0015.dnc-filtering.sql`

```sql
create table dnc_runs (
  id          uuid primary key default gen_random_uuid(),
  started_at  timestamptz not null,
  limited     boolean not null
);
create index dnc_runs_unlimited_idx on dnc_runs (started_at) where not limited;

create table dnc_numbers (
  phone_e164  text primary key,
  blocked     boolean not null,
  updated_at  timestamptz not null
);

create table dnc_log (
  seq         bigint generated always as identity primary key,
  phone_e164  text not null,
  kind        text not null check (kind in ('rep', 'admin', 'event', 'intake', 'backfill', 'lift')),
  actor       text not null,
  rep_id      uuid references partners(id),
  contact_id  uuid,
  event_id    bigint,
  reason      text,
  at          timestamptz not null,
  check ((kind = 'rep') = (rep_id is not null)),
  check (kind not in ('rep', 'admin', 'lift') or btrim(reason) <> '')
);
create index dnc_log_phone_idx on dnc_log (phone_e164, seq);

-- dnc_carried_phones(payload jsonb) returns text[] — §4.2's normalization.
-- dnc_block_from_event() — trigger on events, after insert and after update of
--   contact_id, for §4.2's event types: upsert dnc_numbers (blocked = true) and append
--   dnc_log (kind 'event') for the contact's phone and each carried phone.
-- dnc_backfill() — kind 'backfill', over every existing flag, voice tombstone (by
--   phone; by list key through intake rows), and qualifying event with its carried
--   phones; created here and called once, after the trigger exists.
-- dnc_numbers.updated_at is the database's now() for trigger, intake, and backfill rows,
--   and the verb's `at` for verb rows.

grant select on dnc_runs, dnc_numbers, dnc_log to me_user_ro;
```

The trigger and the backfill are written in full in the build plan, with their tests. No
foreign key on `contact_id` or `event_id`: the record outlives a hard delete, as a
tombstone does.

## 11. Proposed changes to the decision record and documents

| Where | Proposed change |
|---|---|
| Record 4.4 | Replace: no rep undo; the operator lifts, by hand with a written reason, blocks recorded by part 2's verbs; any other block stays (answers 8, 9) |
| Record 9.8, 9.9, 9.10, 9.11, 9.16 (DNC half) | As §9 |
| Record 4.3 | Add: every block of any origin is one row on the phone; a rep may report a contact they hold or held |
| Record 4.6 | Add: after the next completed daily run |
| Record 4.1 | Add: production scrubs only through the ledger path |
| `00-purpose.md:58`, `:60`; `00-interface.md:40-43`, `:97`, `:116`; `00-overview.md` §4; `01-intake.md` §4.2 row 3 | The rep undo becomes the admin lift; door B reads the one record |

## 12. Safety properties

| # | Property | Kept by |
|---|---|---|
| S1 | Every "don't call me again", however recorded, blocks its phone in every reader until an admin lifts it | §4.2 (helper, trigger, backfill), §4.4 |
| S2 | A lift reverses only blocks the verbs recorded and the operator saw, on a phone nothing else marks | §4.7: `not_liftable`, `seen_seq`, the row lock |
| S3 | Every real request is recorded and kept | §4.5, §4.6; `dnc_log` is append-only by convention |
| S4 | A check is `clear` only against a list no more than 31 days old | §4.1 rows 4 and 6; §4.8 |
| S5 | The export refuses whatever the status refuses for a DNC cause, in its frozen shape | §4.4 |
| S6 | `make test` touches only `mailengine_test`; nothing fake-scrubs production | §4.8, §7 |
| S7 | Locks are taken contact row first, then the phone's row; no table locks | §4.5, §4.7; the trigger locks only the phone's row |
