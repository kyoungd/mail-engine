# contact-engine Upgrade — Part 5b: The rule

**Status:** APPROVED by the operator, 2026-09-30, at revision 6 (offered "Approve now",
"One more review", or "Read it first"; chose approve now). **BUILT 2026-09-30:** under
an approved build plan and an approved test gate: `0018.the-rule.sql`, `service/rule.py`,
and in 5a's `service/calls.py` the contact lock and state write in `record_outcome` and
`resolve_received` and the rule in `open_call` (through `_check_open`, shared with
`may_call`); 5a's frozen test got its approved setup change. Gate
`tests/acceptance/test_the_rule.py` (one call in it rewritten from `*b` to four indexed
arguments for pyright; no assertion changed). Every §8 mutation that can be written as
a change failed the gate; the separate-transaction mutant was run on the two
transaction tests alone, since it hangs every other test on the contact's lock. Four questions
were put to the operator (§9, answers 1 to 4). History: Revisions 1 and 2 did not pass
their reviews. Revision 2 worked each contact's state out of its whole history on every
read, and its review found six holes of one kind: event order and ties across three
tables, a restart and a call at the same moment, "who held it then" compared across two
clocks, counts left undefined outside the sequence, a pause's reach, a former holder's
acts. Revision 3 removes the cause: **each contact's state is stored in one row, written
by the act that changes it, under the contact's lock**. Order is the order of the writes;
holding is checked at the write. Only dates — when a contact is due, when its rest ends —
are still worked out on read, from the stored last call and the current settings.
Revision 3 did not pass: a single stored `closed` value lost other closings when one was
undone; one 5a frozen test opens a second call on a contact it has just recorded Busy on,
which the rule now refuses; one mutation could not be caught. Revision 4 reads the
outcome closings from the record (only the rep's own close is stored), proposes the 5a
test's one-line setup change for the operator's approval (§5), drops the mutation, and
applies the minor findings. Revision 4's review found the design sound and three gaps:
the bulk lists were not checked against `contact_state`; the new lock in
`resolve_received` had no test; a former holder's open call could straddle a restart.
Revision 5 closes the three and applies the minor findings. Revision 5 **passed** its
review (no blocking finding); its minor findings are applied here, in revision 6.
**Part of:** [the upgrade](00-overview.md). Decisions are in the decision record,
`nvermisscall/docs/active/sales-partner-dialer-decisions.md`, named here by number
("decision 7.2"); sections of this document are named "§4.1".
**Checked against:** the `contact-engine` branch at `2d195b7` (parts 0 to 4 and 5a
built). A statement about the code carries its file and line.

---

## 1. Its job

Keep where every contact stands — its list, its sequence's counts, its last call, a
pause — and refuse a call the rule does not allow. Keep each rep's four settings. Let the
rep move a contact, pause it, and restart it after its rest.

| Decision | What it asks | Here |
|---|---|---|
| 7.1 | Four settings, fixed choices, the rep's own: voicemails 1/2/3 (2), calls 3/5/8 (5), days between calls 3/5/7 (3), rest 1/3/6 months (3) | §4.1 |
| 7.2 | A sequence ends at whichever limit comes first; then the contact rests; after the rest the rep restarts or closes | §4.3, §4.5 |
| 7.3 | The rep changes the settings, on the website; the app shows them | §4.1 (the verbs; the website is part 6) |
| 7.4 | Stopping at the limit is automatic; a pause is something the rep asks for | §4.3, §4.5 (answer 2) |
| 7.5 | The lists: Calls received, Got a callback, Follow up, Never called, All due retries, Waiting, Limit reached, Closed | §4.4 |
| 7.11 | Out of the working lists: asked not to be called, a customer, a wrong number, not interested, closed by the rep (shown under Closed, with the reason); another rep holds it (in none of this rep's lists). Shown but not callable: the sequence ended, or the next call not due | §4.4, §4.6 |
| 9.4 | A limit lowered below what a contact already has | §4.4 (answer 3) |

## 2. Its edges

| 5b does | 5b does not — who does |
|---|---|
| The settings, each contact's stored state, the lists, the rep's moves (§4.1–§4.5) | — |
| Have 5a's `record_outcome` and `resolve_received` update the state in their transaction (§4.3), and add the rule to `open_call` (§4.6) | Any other change to 5a, except one test's setup (§5) |
| | What a sale does to holding (6.5, 9.1–9.3, a former holder's Signed up among them), the 90 days against the lists (6.3's exception, 9.0), which released contacts are free for a batch (9.12), a wrong-number replacement (9.14) — 5c |
| | The card's "until when" for calling hours, any exposure, the website's settings page — part 6 |

## 3. What exists, checked

| Fact | Where |
|---|---|
| 5a's `calls` holds every call a rep opened and every outcome from the card; `happened` says which rows are calls; Signed up and Wrong number can be undone | `db/migrations/0017.call-record.sql`; `05a-call-record.md` §4.8 |
| 5a's outcomes: no_answer, left_voicemail, owner_unavailable, busy, call_not_placed, spoke, follow_up, not_interested, wrong_number, signed_up | `service/calls.py:21-26` |
| `open_call` locks the contact first; `record_outcome` locks the contact (from the card) or the call row (on a call); `resolve_received` and `undo_outcome` lock their own row only | `service/calls.py:73`, `:149`, `:170`, `:268`, `:325` |
| A former holder may record the outcome of their own open call, and may resolve a call received from a contact they once held | `05a-call-record.md` §4.3, §4.5 |
| Part 2's `dnc_status` gives `do_not_call` for a "don't call me again"; `BLOCKED_SQL` reads the same in bulk | `service/dnc.py:126-127`, `:26-29` |
| Part 3's `calling_hours` gives each contact's zones | `service/zones.py:44-74` |
| Holding is `contacts.owner_id` | `db/migrations/0009.partner-custody.sql:61` |

## 4. The design

The verbs live in `service/rule.py`. Every rep verb refuses `bad_time`, then `bad_rep`,
as 5a's do.

### 4.1 The settings (7.1, 7.3; answers 3, 4)

`rep_settings`: one row per rep who has saved — voicemails, calls, days between, rest
months, `updated_at`. A rep with no row has the defaults (2, 5, 3, 3).
`get_settings(rep)`; `save_settings(rep, voicemails, calls, days_between, rest_months,
at)`, each value one of its fixed choices (`bad_setting`); `restore_defaults(rep, at)`
deletes the row. **Every setting takes effect at once** (answers 3, 4): the state stores
counts and the last call, never a date, so the dates of §4.4 follow the current settings.

### 4.2 The state

`contact_state`, one row per contact that has had any act; a contact with no row is at
the start (sequence, no calls). Columns:

| Column | Meaning |
|---|---|
| `list` | `sequence`, `got_callback` or `follow_up` |
| `rep_closed` | the rep moved it to Closed |
| `calls`, `voicemails` | the sequence's calls that happened and its voicemails |
| `last_call_at`, `last_call_busy` | the sequence's last call that happened, and whether it was Busy |
| `pause_until` | a date, or null |

A new holder inherits the row: the business is not called more because it changed hands.

### 4.3 What writes it (answer 1)

Each act below updates the row **in the same transaction as the act, under a lock on the
contact** — so the order of acts is the order they committed. The verbs that did not
lock the contact (`record_outcome` on a call, `resolve_received`) now read their row's
contact first (the column never changes), lock the contact, then lock their own row;
`calls._after_lock` fires after the row lock, as now. The write is one function,
`rule._write_state(cur, contact_id, change)`, which `service/calls.py` calls through the
module (`from service import rule`; the two modules import each other as modules only),
after the outcome or resolution and before any memo. A state write that fails rolls the
act back with it. Whether an outcome counts is judged on the list as it
stands before the act (a Spoke on a sequence call counts, then moves to Follow up). A no-op hook, `rule._after_lock(cur)`,
runs right after the contact lock in §4.5's verbs, for the lock tests.

| Act | Change |
|---|---|
| An outcome on a call that happened, while `list` is `sequence` | `calls` + 1; `voicemails` + 1 for Left voicemail; `last_call_at` = the call's `opened_at`; `last_call_busy` |
| An outcome on a call while `list` is `got_callback` or `follow_up`, or any outcome from the card, or Call not placed | no count moves |
| Spoke, Follow up (on a call or from the card) | `list` = `follow_up` |
| Not interested, Wrong number, Signed up | nothing here: closings by outcome are read from the record (§4.4), so an undo (5a §4.7) needs no write and never loses another closing; counts stay — a call whose Wrong number is undone still happened |
| A call received resolved `spoke` / `call_back` **by the contact's holder at the moment of resolving** | `list` = `follow_up` / `got_callback`; a former holder's resolution writes nothing here |
| `move` to `got_callback` | `list` = `got_callback` |
| `move` to `closed` | `rep_closed` = true |
| `pause` / `unpause` | `pause_until` = the date / null |
| `restart` (§4.5) | `list` = `sequence`; counts, last call and `pause_until` cleared |

An outcome is the call's history wherever the rep is now: a former holder's outcome on
their own open call (5a §6) writes the state like any other. Whether a call counts is
judged when its outcome is recorded. §4.5's `move` and `pause` refuse `call_open` while
the rep's own call is open on the contact (as 5a's card outcomes do); `restart` refuses
it while **any** call is open on the contact, the former holder's too, so a restart never
lands in the middle of a call. A move or a pause by the new holder can still land during
a former holder's open call; that call's outcome is then judged on the new list. A resolution of a call received is a choice about
the contact, so only its holder's counts. A closed contact's row still takes counts and
lists — they matter only if the closing is undone.

### 4.4 Reading: the list (answers 3, 4)

`contact_state(rep, contact_id, at)` reads the row, the rep's current settings, part 2's
status and part 3's zones, and gives the list, the reason, the counts, and the date that
applies. It takes no lock, so `open_call` can call it under its own. Refused: `bad_time`,
`bad_rep`, `no_contact`, `not_yours`. The first that applies:

1. **Closed**, *asked not to be called* — part 2's status is `do_not_call`.
2. **Closed**, *a customer* — a Signed up on the contact, not undone.
3. **Closed**, *wrong number* — a Wrong number, not undone.
4. **Closed**, *not interested* — a Not interested.
5. **Closed**, *closed* — `rep_closed`.
6. **Limit reached** — `list` is `sequence` and `voicemails` ≥ the voicemails setting or
   `calls` ≥ the calls setting. *Resting until R*, R = the date of `last_call_at` + the
   rest months; *rest over* once R has arrived.
7. **Waiting**, *paused until U* — `pause_until` is U and U has not arrived.
8. **Got a callback** / **Follow up** — `list` is that.
9. **Never called** — `calls` is 0 (a restarted contact too).
10. **All due retries** — D has arrived: the date of `last_call_at` + 1 day if
   `last_call_busy`, else + the days between.
11. **Waiting**, *due on D*.

Rows 2 to 4 read the whole record: a closed contact is never restarted, so no earlier
run can hold a closing that no longer applies. A contact whose part 2 status is anything
else that is not `clear` (not checked, too old, on a DNC file, not covered, no phone)
stays in its list here; `open_call` and `may_call` refuse it as `not_callable` (5a).
Part 2's `dnc_status` reads `seed` before `do_not_call`; reps never hold seeds.

**Days in several zones** (V1 Minimum §1, row 7: retries by whole days; never early is
this design's rule): the date of a moment
is its **latest** local date across the contact's current zones; a day X **has arrived**
when the **earliest** local date of `at` across them is ≥ X. With no zone known, UTC
(no call can open then: 5a's `no_zone`). A month is a calendar month, the day clamped to
the month's last (Jan 31 + 1 month = Feb 28, or 29), by `rule.add_months(date, n)`. A
zone set after a call moves its dates with it (part 3's zones are the current ones).

### 4.5 What the rep asks for (7.2, 7.4; answer 2)

All on a contact the rep holds, the contact locked `for update`. Refused, in this order:
`bad_time`, `bad_rep`, `no_contact`, `not_yours`, `call_open` (for `move` and `pause`, the
rep's own call is open on it, with its id; for `restart`, any call is open on it), and:

| Verb | Refused also |
|---|---|
| `move(rep, contact_id, to, at)`, `to` one of `got_callback`, `closed` | `bad_list` (a move to Follow up is 5a's Follow up from the card); `closed_already` when §4.4 says Closed |
| `pause(rep, contact_id, until, at)` | `closed_already`; `not_pausable` when Limit reached; `bad_date` when U has already arrived |
| `unpause(rep, contact_id, at)` | `not_paused` when §4.4 does not say *paused* |
| `restart(rep, contact_id, at)` | `not_limit_reached` when §4.4 does not say Limit reached; `still_resting` before R has arrived |

### 4.6 May I call now?

`open_call` (5a) gains the rule: after part 3's `no_zone` and before `outside_hours`,
under its lock, it reads §4.4 and refuses, writing nothing — so a rep is never asked to
confirm outside hours on a contact that is not due, and a contact with no zone gets
`no_zone` first:

| Code | When |
|---|---|
| `closed` with `reason` | Closed (a "don't call me again" is already refused as `not_callable`) |
| `limit_reached` with `rest_until` | Limit reached |
| `paused` with `until` | Waiting, paused |
| `not_due` with `due` | Waiting, not due |

Never called, All due retries, Got a callback and Follow up may be called, if part 2's
status is `clear`. Every act that writes the state locks the contact, so none can land
between `open_call`'s read and its call; a settings change only orders before or after
the read. An undo (5a) changes what §4.4 reads without the contact's lock, but it only
ever removes a closing, so a stale read can only refuse a call, never allow one.

`may_call(rep, contact_id, at)` gives the answer without opening a call: yes with the
number, or the refusal `open_call` would give without a confirmation — `call_open`, or
`outside_hours` with the local times, so the app can ask the rep to confirm.

### 4.7 The lists (7.5)

`rep_lists(rep, at)`: every contact `rep` holds, each in exactly one list by §4.4, read in
bulk (the rows, the closing outcomes, settings, zones, and part 2's block through
`BLOCKED_SQL`); and **Calls received**, the rep's calls received not yet resolved — a
list of calls, beside the contact lists, so a contact can be in it and in its own list.

## 5. Parts 1 to 5a

5a's `record_outcome` and `resolve_received` lock the contact and write the state
(§4.3); `open_call` reads §4.4 (§4.6). **One 5a frozen test changes — approved by the operator
2026-09-30 (offered "Approve the change" or "Discuss first"), applied when 5b is built:** `test_outcome_on_a_call_refusals` records Busy on a contact and then opens a
second call on the same contact, to clear it; the rule now refuses that call (`not_due`,
correctly — Busy is due the next day). The call to be cleared is opened on a fresh
contact instead, and the refusal it checks (`no_call` on a cleared call) is made on that
contact. No assertion changes.

## 6. Gaps and limits

| Gap | Handling |
|---|---|
| A new holder inherits the state, resting, closed and paused included | As intended. A rep's own never reaches another rep (part 4's `rep_own`; door B's `held`). Which released contacts are free for a batch is 9.12 — 5c |
| Closed has no way back except an undo of Wrong number or Signed up | Not decided; a reopen is not built |
| Settings changes move every waiting and resting contact's dates at once | Answers 3, 4 |
| A former holder's outcome on their own open call writes the new holder's state | §4.3: the call is history. A former holder's Signed up touches 9.3 — 5c |
| "Never called" also names a restarted contact | The list's name; its counts are zero |
| A pause kept while the contact is Closed or Limit reached (`unpause` then says `not_paused`) shows again if the contact returns to a callable list — an undo, or a move to Got a callback | Accepted: the rep set it; it ends on its day |

## 7. Tests, written first

`tests/acceptance/test_the_rule.py`, the gate. Times are chosen inside calling hours
unless a test is about hours; contacts are freshly checked against `at`. Its fixture
removes `rep_settings` before its partners; `rep_settings` and `contact_state` join the
test truncate lists by name.

| Test | Pins |
|---|---|
| Settings | defaults (2, 5, 3, 3); save and read; each value outside its choices → `bad_setting`; restore defaults |
| Never called | a held contact with no act |
| Sequence outcomes | No answer, Owner unavailable, Left voicemail → Waiting *due on* the call's date + days between, All due retries that day; Busy → due the next day; Call not placed → unchanged; counts after each |
| Limits | the voicemail limit, and the call limit (whichever first) → Limit reached, *resting until* the last call + the rest months; on R, *rest over* |
| Settings at once | 6 calls, calls 8 → 5: Limit reached at once, R from the last call (answer 3); days between 3 → 7 moves D; rest 6 → 1 ends a running rest (answer 4) |
| Month clamp | `rule.add_months`: Jan 31 + 1 month → Feb 28 (2027), Feb 29 (2028) |
| Leaving the sequence | Spoke, Follow up → Follow up; Not interested, Wrong number, Signed up → Closed with the reason; calls on Follow up or Got a callback leave the counts as they were |
| Undo | 4 of 5 calls, call 5 Wrong number, undone → Limit reached (the call counts); a card Signed up undone → back where it stood, counts unchanged |
| Undo with several closings | Not interested then Wrong number, the Wrong number undone → Closed *not interested*; moved to Closed then Signed up, the Signed up undone → Closed *closed*; two Wrong numbers, one undone → Closed *wrong number* |
| Do not call | part 2's report → Closed *asked not to be called* |
| Calls received | the holder's `spoke` → Follow up; `call_back` → Got a callback; `dismiss` → unchanged; **a former holder's resolution writes nothing**; unresolved calls in Calls received |
| A former holder's outcome | on their own open call, after the contact changed hands → the new holder sees its effect |
| During the rest | a `call_back` resolution → Got a callback; a `got_callback` move → Got a callback; a card Spoke → Follow up |
| Moves | to Got a callback and Closed; `bad_list` (follow_up); `closed_already`; with the rep's own call open → `call_open` for move, pause and restart |
| Pause | Waiting *paused until*; back on the day, counts and D unchanged; `unpause` early; a later pause replaces; `bad_date`; `not_paused` (none, or one over); `not_pausable`; `closed_already`; a restart clears a pause |
| Restart | `not_limit_reached`; `still_resting` the day before R; on R → Never called, counts zero |
| Several zones | a Los Angeles area code with state AZ (Los Angeles, Phoenix and Denver; Phoenix and Denver share an offset in winter), in winter: a call at 23:30 Pacific (confirmed outside hours) is dated by Phoenix's next day; at 23:30 Pacific on the day before D the contact is still Waiting |
| A new holder | inherits Limit reached, Closed and a pause |
| Lists agree with `contact_state` | contacts covering every row of §4.4 — each Closed reason, Limit reached resting and rest over, paused, Got a callback, Follow up, Never called, due, not due, and one in several zones — `rep_lists` places each exactly where `contact_state` does, with the same reason and date |
| Order, an outcome | a former holder A has a call open; the new holder B's `move` to Got a callback holds the contact through `rule._after_lock` while A's outcome on the call waits → the outcome is judged after the move and counts nothing |
| Order, a resolution | a blocker connection locks the contact and moves it with `set_owner` to another rep while the old holder's `resolve_received('call_back')` waits; the blocker commits → the resolution writes nothing |
| Restart with a former holder's call open | `restart` → `call_open` |
| One transaction | `rule._write_state` made to raise → the outcome is not recorded; a failure raised just after it, before commit → the state is unchanged too; both with a timeout, so a write in a separate transaction (which would wait on the contact's lock) fails the test rather than hanging it |
| Not callable by part 2 | a held contact checked 40 days ago stays Never called; `open_call` refuses `not_callable` |
| May I call | `open_call` refuses `closed`, `limit_reached`, `paused`, `not_due` with their detail; a contact with no zone gets `no_zone`, not `not_due`; allows the four callable lists; `may_call` agrees, and gives `outside_hours` with the local times |
| 5a's gate | green, with §5's one setup change |
| Refusals | every verb: `bad_time`, `bad_rep`; every verb on a contact: `no_contact`, `not_yours` |

## 8. Done means

The gate green, and 5a's gate green with §5's one setup change; `make test`, `make e2e`, `make lint`
clean; mutation checks each failing a test — count Call not placed; count a card outcome;
count calls on Follow up; let an undo remove the count; drop Busy's next day; store a due
date instead of reading the settings; take a date from the earliest zone; take "arrived"
from the latest zone; drop the month clamp; let a former holder's resolution write; skip
the state write in `record_outcome` or `resolve_received`; drop the contact lock in
`resolve_received`; let `restart` pass a former holder's open call; write the state in its
own transaction; read the bulk lists differently from `contact_state`; let an undo null every closing (store one `closed`); let a pause move the
counts; allow a call while Closed, Limit reached, paused, or not due; restart before the
rest ends; allow a move while the rep's call is open. Migration `0018` applied
to `mailengine_dev`.

## 9. For the operator

| # | Question | Answer |
|---|---|---|
| 1 | How does each outcome move a contact? | **Answered 2026-09-30: the proposed table**, built from the V1 Minimum (§4.3). Offered that (recommended) or "I'll adjust it". |
| 2 | What does a pause do? | **Answered 2026-09-30: one contact, until a date.** Offered that (recommended), "One contact, until unpaused", or "All of a rep's calling". |
| 3 | 9.4: a limit lowered below a contact's counts | **Answered 2026-09-30: at once, the rest from the last call.** Offered that (recommended) or "Next time the rep calls it". |
| 4 | Do waiting and resting contacts follow a change of days between or rest months? | **Answered 2026-09-30: yes, at once.** Offered that (recommended) or "No, keep their dates". |

## 10. The migration, `0018.the-rule.sql`

```sql
create table rep_settings (
  rep_id         uuid primary key references partners(id),
  voicemails     smallint not null check (voicemails in (1, 2, 3)),
  calls          smallint not null check (calls in (3, 5, 8)),
  days_between   smallint not null check (days_between in (3, 5, 7)),
  rest_months    smallint not null check (rest_months in (1, 3, 6)),
  updated_at     timestamptz not null
);

create table contact_state (
  contact_id      uuid primary key references contacts(id),
  list            text not null default 'sequence'
                    check (list in ('sequence', 'got_callback', 'follow_up')),
  rep_closed      boolean not null default false,
  calls           integer not null default 0 check (calls >= 0),
  voicemails      integer not null default 0 check (voicemails between 0 and calls),
  last_call_at    timestamptz,
  last_call_busy  boolean not null default false,
  pause_until     date,
  updated_at      timestamptz not null,
  check ((calls = 0) = (last_call_at is null)),
  check (last_call_at is not null or not last_call_busy)
);

create index calls_closings_idx on calls (contact_id)
  where outcome in ('signed_up', 'wrong_number', 'not_interested');

grant select on rep_settings, contact_state to me_user_ro;
```

## 11. Proposed changes to the decision record and documents

| Item | Proposal |
|---|---|
| 7.2 | Add the table of §4.3 (answer 1) |
| 7.3 | Add: every setting takes effect at once, for contacts already waiting or resting (answers 3, 4) |
| 7.4 | Add: a pause is one contact, until a date (answer 2) |
| 7.11 | Add: asked not to be called, a customer, a wrong number, not interested and closed by the rep are shown under Closed, with the reason; a contact another rep holds is in none of this rep's lists |
| 9.4 | Settled: at once, the rest from the last call (answer 3) |
| `05a-call-record.md` §4.3, §4.5 | `record_outcome` on a call and `resolve_received` read their row's contact, lock the contact first, then their row as before |
| `unpause` | Was part of answer 2's option ("the rep can unpause it early"); kept |

## 12. Safety properties

Each revision is checked against these before review.

1. No call opens on a contact the rule does not allow: Closed, Limit reached, paused, or
   not due.
2. No sequence call opens once the current limits are met.
3. Only calls that happened while in the sequence count.
4. A day never comes early in any zone the contact could be in.
5. Every contact a rep holds is in exactly one list.
6. Every act that changes the state writes it under the contact's lock, in the act's own
   transaction. Of the resolutions of calls received, only the holder's writes it.
