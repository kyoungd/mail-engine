# contact-engine Upgrade — Part 2: DNC filtering

**Status:** DRAFT, revision 1, 2026-09-30. The operator's four questions answered (§9).
Not reviewed, not approved. Nothing is built.
**Part of:** [the upgrade](00-overview.md). Decisions are in the decision record,
`nvermisscall/docs/active/sales-partner-dialer-decisions.md`, named here by number
("decision 4.1"); sections of this document are named "§4.1".
**Checked against:** the `contact-engine` branch at `3d41750` (parts 0 and 1 built). A
statement about the code carries its file and line.

---

## 1. Its job

Say whether a number is clean to call, and why not when it is not; and take, and undo,
a "don't call me again".

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
| Take a rep's "don't call me again", and its undo (§4.4, §4.5) | Put the contact in a Closed list — part 5 (decision 7.5) |
| Take an admin's "don't call me again", with or without a contact (§4.6) | Expose any of it from outside — part 6 |
| Record each completed daily scrub (§4.3) | Raise an alert from it — the website (decision 1.7); which alerts, 9.5, is part 6's |
| Count the two 31-day ages the same way (§4.2) | Download or upload DNC files — unchanged (decision 4.5) |

## 3. What exists, checked

| Fact | Where |
|---|---|
| The daily scrub checks contacts in subscribed area codes never checked or checked over 21 days ago, rep-held first; a hit sets `dnc_registry` and takes the contact back to the house; a delisting clears it | `jobs/dnc_refresh.py:80-96`, `:106-169`; `config/params.py:19` |
| The daily run is pull → scrub (`--from-ledger`, i.e. `dnc_refresh_all`) → nightly | `scripts/daily-run.sh`; `jobs/dnc_refresh.py:239` |
| Area codes nobody subscribes to are never scrubbed; their contacts keep `dnc_checked_at` null | `jobs/dnc_refresh.py:80-96` |
| The assignment gate and the export count a check fresh when `dnc_checked_at >= now() − 31 days` — an exact interval — and the list behind it when its `version_date >= (UTC date) − 31` — whole days | `service/assignment.py:120-131`, `:328-331`; `config/params.py:33` |
| The gate refuses, in order, … `do_not_call`, `dnc_registry`, a voice tombstone for the phone, an unsubscribed area code, a stale check | `service/assignment.py:134-160` |
| `suppress()` sets the channel's flag, appends the event, writes a tombstone per channel, and for `voice` / `all` returns a held contact to the house. It records no reporter. It reads the owner `for update` since the lock fix | `service/contacts.py:421-494` |
| `clear_suppression` clears `dnc_registry` only; every other channel is refused as permanent — pinned by frozen tests | `service/contacts.py:496-524`; `tests/acceptance/test_suppression_split.py:127`, `:154`, `:200` |
| Tombstones hold phone, list key, channel, reason, time; no link to the event that wrote them | migration `0010` |
| Intake refuses a number with a voice tombstone, `do_not_call`, or an opt-out event (part 1, row 3) | `service/rep_intake.py` `_judge` |
| `contacts.created_at` is set when a contact is created | migration `0001` |
| The DNC files are read only by the scrub, from local working copies; the pull re-lands any accepted file whose copy is missing, from R2 | `jobs/dnc_refresh.py:239-278`; `jobs/dnc_pull.py:60-81`, `:92-95` |
| The 31 days were checked against 16 CFR 310.4(b)(3)(iv) on 2026-09-13: "obtained from the Commission no more than thirty-one (31) days prior to the date any call is made" | git history of `docs/current-state.md` at `4b6d5b9` |

## 4. The design

### 4.1 The DNC status

`dnc_status(contact_id, today)` in a new `service/dnc.py`. `today` is the UTC date,
handed in (the clock rule, part 1 §4.6). The first that applies:

| # | The contact | Status |
|---|---|---|
| 1 | Has `do_not_call`, or a voice tombstone for its phone | `do_not_call` |
| 2 | Has no phone | `no_phone` |
| 3 | Its area code has no subscription, and it came in before the start of the last completed daily scrub (§4.3) | `not_covered` |
| 4 | Its area code has no subscription, otherwise; or it was never checked | `not_checked` |
| 5 | Is on the DNC file (`dnc_registry`) | `on_dnc_file` |
| 6 | Its check, or the list behind it, is more than 31 days old (§4.2) | `check_too_old` |
| 7 | Otherwise | `clear` |

- **Only `clear` may be called** as far as DNC goes (decision 4.1). "Failed" in 4.1 is
  row 5; a check that could not run leaves the old one, which becomes row 6.
- **Row 3 is decision 4.6** (answer 1): a number in an area code nobody covers reads
  `not_checked` until a daily run has finished since it came in, then `not_covered`.
  "Came in" is `contacts.created_at`; a contact a rep claims from NMC's list came in
  long ago, so it reads `not_covered` at once.
- **One rule, three readers.** The freshness test is one SQL expression in
  `service/dnc.py`, used by `dnc_status`, the assignment gate, and the export, so
  they cannot drift (`service/assignment.py:120-131`, `:328-331` read it instead of
  their own copies).

### 4.2 The 31 days (decision 4.2; 9.10; answer 3)

Both ages are counted in whole days on the UTC date:

```
fresh ⇔ (today_utc − check_date_utc) ≤ 31  and  (today_utc − list_date) ≤ 31
```

where `check_date_utc` is `dnc_checked_at` at time zone UTC, as a date, and
`list_date` is the snapshot's `version_date` (when the contact has one). Day 31 is
good; day 32 is stale. The UTC date is never behind a US date, so any error is toward
stale. This changes the gate and the export — red-tier — from an exact interval to
whole days for the check's age; the list's age is already counted this way.

### 4.3 The daily scrub records itself

A new table `dnc_runs` (§10). `dnc_refresh` and `dnc_refresh_all` each write one row
when they finish — started and finished times, counts, skips — and none when they
fail. `dnc_status` row 3 reads the latest `started_at`. Part 6 reads the same table
for "the last run of each job and whether it succeeded" (interface job 6).

Jobs are the outermost layer, so they read the clock themselves.

### 4.4 A rep's "don't call me again" (decisions 4.3; 9.8; answer 2)

`report_do_not_call(rep, contact_id, reason, at)` in `service/dnc.py`:

| The call | Result |
|---|---|
| The rep is unknown, inactive, or the house | refused `bad_rep` |
| The rep does not hold the contact | refused `not_yours` |
| The contact already has `do_not_call` | refused `already_blocked` |
| Otherwise | blocked |

One transaction, the contact row locked `for update`:

- `do_not_call = true`.
- A voice tombstone for the phone, with the primary list key when there is one.
- A `contact.suppressed` event, `occurred_at = at`, payload `{channel: voice, reason,
  source: rep, reported_by: <rep>, tombstone_id: <the tombstone's id>}`. `reason`
  defaults to "asked not to be called".
- **No reclaim** (answer 2): the rep keeps the contact. It can never be called or
  assigned — every reader of `do_not_call` refuses it — and part 5 shows it in the
  rep's Closed list.

This is its own verb, not `suppress()`: `suppress()` keeps returning a held contact to
the house for every other voice block, as its frozen tests pin.

Blocking is at once and for every rep (decision 4.3): the flag is on the contact, and
the tombstone on the phone.

### 4.5 The undo (decision 4.4; answer 4)

`undo_do_not_call(rep, contact_id, reason, at)`:

| The call | Result |
|---|---|
| The reason is missing or blank | refused `no_reason` |
| The contact's latest voice block is not a rep report | refused `nothing_to_undo` |
| It was reported by another rep | refused `not_yours` |
| `at` is more than 24 hours after the report's `occurred_at` | refused `too_late` |
| The phone has another voice tombstone, or the contact an opt-out event | refused `still_blocked` |
| Otherwise | undone |

One transaction, the contact row locked `for update`: `do_not_call = false`; the one
tombstone named by the report's `tombstone_id` is deleted; a
`contact.suppression_cleared` event, payload `{channel: voice, reason, source: rep,
undone_by: <rep>, report_event_id}`. The events keep the whole history.

`clear_suppression` is unchanged: it still refuses `voice`, so its frozen tests stand.
The undo is a separate, narrower door.

After an undo, part 1's intake no longer refuses the number: the flag is false, the
tombstone is gone, and the report was a `contact.suppressed`, which row 3's opt-out
reading does not count (part 1 §4.2; the 4.4 limit part 1 left for part 2 is closed).

### 4.6 An admin's "don't call me again" (9.9)

`record_do_not_call_request(phone, reason, at)` in `service/dnc.py`, for a request
that reached NMC by email or phone:

- A contact has the phone: `suppress(contact, "voice", reason)`, as today — it returns
  a held contact to the house.
- No contact has the phone: a voice tombstone for the phone, nothing else. Both doors
  of intake refuse the number from then on (`service/contacts.py:152-168`; part 1
  row 3).
- An invalid phone is refused (`invalid_phone`, part 1's rule).

The operator reaches it with a new command, `python -m jobs.dnc_request_cli <phone>
--reason …`, which closes part 0's gap "cannot record an opt-out" for the operator.
The website reaches it in part 6.

### 4.7 The files on Render (9.11)

Only the daily job reads DNC files; the service reads the columns the scrub wrote.
So on Render the pull and the scrub run in one job, on the job's own disk, as
`daily-run.sh` runs them today; the pull re-lands from R2 any accepted file whose copy
is missing (`jobs/dnc_pull.py:92-95`). No disk is shared with the service. That it
re-lands every accepted file, not only the newest per code, is a cost for hosting to
trim, not a correctness question.

### 4.8 The law (9.16, DNC half)

The 31 days stand as checked on 2026-09-13 (§3). §4.2 counts them on the UTC date of
the call, which is never behind the US date of the call. The calling-hours half of
9.16 is part 3's.

## 5. Part 1's hand-offs, closed

| Part 1 left | Part 2 |
|---|---|
| Undoing a "don't call me again" (4.4) would leave the tombstone, so intake would keep refusing | §4.5 deletes the report's own tombstone |
| A held contact goes back to the house on a voice suppression (part 1 §6) | For a rep's own report, no longer (§4.4). Other voice blocks and a DNC hit still return it — part 4 decides for a rep's own contact (decision 6.3) |

## 6. Gaps while the upgrade is built

Not questions (decision 2.9).

| Gap | Closed in |
|---|---|
| Nothing outside tests calls `dnc_status`, `report_do_not_call`, `undo_do_not_call` | Parts 5 and 6 |
| The age of each area code's DNC file, for alerts (interface job 2) | Part 6, over `dnc_snapshots` and `dnc_runs` |
| A rep's own contact is still taken back to the house on a DNC hit (`jobs/dnc_refresh.py:147-153`) | Part 4 (decision 6.3) |

## 7. Tests, written first

| Test | Checks |
|---|---|
| Each status, 1 to 7 | The status |
| The order | `do_not_call` + on the DNC file → `do_not_call`; on the DNC file + stale → `on_dnc_file`; no subscription + never checked + before the last run → `not_covered` |
| Not covered after the run | A contact in an unsubscribed code: `not_checked`; a scrub completes; `not_covered`. A contact created after that run's start: still `not_checked` |
| A failed scrub writes no run | A scrub that raises leaves `dnc_runs` unchanged |
| The 31-day wall on the check | Checked 31 UTC days ago: fresh in the status, the gate, and the export; 32: stale in all three. Run under `PGTZ` at UTC+14 and UTC−11, as the list's wall test does |
| Report: each refusal | The result; nothing written |
| Report: blocked | The flag; one voice tombstone; one `contact.suppressed` with `reported_by` and the tombstone's id; the rep still holds the contact; the gate refuses it; intake refuses the number for another rep |
| Undo: each refusal | Including 24 hours and one second after the report → `too_late`; exactly 24 hours → undone |
| Undo: undone | Flag false; the report's tombstone gone, any other untouched; one `contact.suppression_cleared`; intake no longer refuses the number |
| Admin request | With a contact: as `suppress(voice)`, the contact back at the house. Without: one voice tombstone, no contact; both intake doors refuse the phone |
| The clock | Every event the new verbs write carries `at` |
| Frozen tests | `clear_suppression` still refuses `voice`; `suppress()` still returns a held contact on `voice` |

## 8. Done means

| Check | How |
|---|---|
| The build follows the red-tier gate: the gate and export change, suppression verbs, a tombstone delete, and a migration | Build plan approved first; the tests approved as its first step |
| The tests of §7 pass; every existing test passes unchanged | `make test` |
| `make e2e`, `make lint` | Pass |
| `0015` changes no existing row on production-shaped data | As part 1's §8 check, from a checkout without `0015` |

## 9. For the operator

| # | Question | Answer |
|---|---|---|
| 1 | How "not covered" appears (4.6) | **Answered 2026-09-30:** after the next daily run — the run is recorded; before it, `not_checked`. Offered "After the next daily run", "Immediately", or "Never say it". |
| 2 | After a rep's "don't call me again", does the rep keep the contact (9.8) | **Answered 2026-09-30:** the rep keeps it, Closed. Offered "Rep keeps it, Closed" or "Back to NMC". |
| 3 | How the 31 days are counted (9.10) | **Answered 2026-09-30:** whole days on the UTC date, for the check and the list alike. Offered "Whole days, UTC date", "Keep as is", or "Exact intervals for both". |
| 4 | The undo and the report's tombstone (4.4) | **Answered 2026-09-30:** the undo removes that tombstone; the events keep the record. Offered "Remove that tombstone", "Mark it undone", or "Leave it". |

**The design's own answers**, for approval with the part (no decision or answer names
them; each has one obvious reading):

| Point | Answer |
|---|---|
| 9.9, an admin's request with no contact | A voice tombstone only (§4.6) |
| 9.11, the files on Render | Pull and scrub in one job; the service reads no file (§4.7) |
| 9.16, the 31 days | As checked 2026-09-13 (§4.8) |
| Who may report | Only the rep who holds the contact (§4.4) |
| A second report on a blocked number | Refused `already_blocked` (§4.4) |
| The 24 hours | From the report's `occurred_at`, on the server's clock (decision 7.6); inclusive |

## 10. The migration, `0015.dnc-runs.sql`

```sql
create table dnc_runs (
  id           uuid primary key default gen_random_uuid(),
  entry        text not null check (entry in ('registry', 'ledger')),
  started_at   timestamptz not null,
  finished_at  timestamptz not null,
  checked      integer not null,
  hits         integer not null,
  cleared      integer not null,
  skips        jsonb not null default '[]'
);

create index dnc_runs_started_idx on dnc_runs (started_at);
```

Additive. `entry` is which entry point ran: `dnc_refresh` (`registry`) or
`dnc_refresh_all` (`ledger`). The read-only role reads it by `0002`'s default
privileges.

## 11. Proposed changes to the decision record

| Record item | Proposed change |
|---|---|
| 9.8 | Decided: the reporting rep keeps the contact, Closed (answer 2) |
| 9.9 | Decided: a voice tombstone only (§9) |
| 9.10 | Decided: whole days on the UTC date (answer 3) |
| 9.11 | Decided for part 2: pull and scrub in one job; confirm at hosting |
| 4.4 | Add: the undo removes the report's tombstone (answer 4) |
| 4.6 | Add: "after the check" is after the next completed daily run (answer 1) |
