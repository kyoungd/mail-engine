# contact-engine Upgrade — Part 4: Assignment

**Status:** APPROVED by the operator, 2026-09-30, at revision 6 (offered "Approve now",
"One more review", or "Read it first"; chose approve now). **BUILT 2026-09-30:** under
an approved build plan and an approved test gate: `REGIONS`, `REP_BATCH_SIZE`,
`ASK_AGAIN_AT` in `config/params.py`; `rep_own` and `returned_recently`, the `max_held` /
`random_draw` / `returned_since` options, the `_after_lock` hook, `get_more_numbers`, and
the one-pass `run_expiry_step` in `service/assignment.py`; door B's 90-day `held` in
`service/rep_intake.py`; the console's two "available" counts. Gate
`tests/acceptance/test_assignment_regions.py`; one missing setup line in it (a
subscription) was added with the operator's approval, no assertion changed. Every §8
mutation failed the gate; every frozen test is unchanged and green. No migration. Two questions
were put to the operator before the design (answers 1 and 2), and one after revision 1's
review (answer 3). History: Revision 1 did not pass its review: keeping a rep's own out of
*every* batch broke a frozen part 1 test that puts it on NMC's own sheet; a contact that
went back after 90 days could be claimed again by the same rep the next day (asked:
answer 3); the partner lock came after the retry lookup, which broke a simultaneous retry
and could deadlock; no test pinned that the 90 days run from the *latest* assignment; the
clock rule was not addressed. Revision 2 did not pass: a moment in the request hash
would have turned every retry into `key_mismatch`; the two expiry rules locked in two
passes and could deadlock with an ask; the new rule would have taken a sold contact from
the rep who sold it. Revision 3 fixes the three, applies the minor findings, and answers
the gaps part 1 handed to part 4 (§6). Revision 3 did not pass: no test caught the
two-pass lock its §8 named; one of part 1's gaps (the console's count) was missing; the
nightly's `recompute_state` and `resolve_orphans` lock contacts out of id order, so a rep's
ask during the nightly could deadlock it; the lock tests had no hook to hold a
transaction open. Revision 4 fixes the four and applies the minor findings. Revision 4 did
not pass: a third nightly writer (`correlate_closes`) and `load_list` also lock contacts
out of id order, and no test caught a stale read of the 90-day wait. Three rounds had now
each found another writer an ask could deadlock with, so revision 5 removes the cause
instead: **an ask skips contacts someone else has locked** (`for update skip locked`) and
never waits on a contact, so it cannot deadlock with any of them; the id-order changes to
the nightly are dropped. Revision 5 **passed** its review (no blocking finding); its
minor findings are applied here, in revision 6 (all but its optional fourth: a second
read of the 90-day wait would be code no test can pin).
**Part of:** [the upgrade](00-overview.md). Decisions are in the decision record,
`nvermisscall/docs/active/sales-partner-dialer-decisions.md`, named here by number
("decision 6.2"); sections of this document are named "§4.1".
**Checked against:** the `contact-engine` branch at `8d36409` (parts 0 to 3 built). A
statement about the code carries its file and line.

---

## 1. Its job

Keep each number with one rep at a time; give a rep more numbers from a region when they
ask; return NMC's numbers after 90 days, counted for each contact, and keep them from the
same rep for 90 days more; never give a rep's own contact to another rep, and never
return it by expiry.

| Decision | What it asks | Here |
|---|---|---|
| 6.1 | One number, one contact, one rep at a time | Exists (§3); unchanged |
| 6.2 | Get more numbers: the rep picks a region and nothing else; drawn in proportion from its area codes, at random; the batch size and the ask-again point are an admin's settings | §4.1, §4.3 |
| 6.3 | NMC's contacts go back after 90 days, counted for each contact; never one in Got a callback or Follow up; a rep's own never | §4.4, §4.5; the Got a callback / Follow up exception is part 5's (answer 1) |
| 6.4 | A new holder sees the history of NMC's contacts, not of a rep's own | Part 6, which shows history; "whose" is part 1's rule (§3) |
| 6.5 | A sold business is out of reach of everyone but the rep who sold it | Part 5 (answer 1) |
| 6.6 | No export for a rep on the app; the export stays for the operator and a rep not on the app | Exists; unchanged |

Open items it settles: 9.13. Moved to part 5 by answer 1: 9.0, 9.1, 9.2, 9.3, 9.12.

## 2. Its edges

| Part 4 does | Part 4 does not — who does |
|---|---|
| Get more numbers (§4.3) | Record a sale, keep a sold business with its seller, or change the nightly step that returns a won contact to the house — part 5 (answer 1) |
| Keep a rep's own out of every other rep's batch (§4.2) | Spare a contact in Got a callback or Follow up from the 90 days; settle 9.0 and 9.12 — part 5, which defines those states |
| The 90 days for a contact held without a batch (§4.4); the 90 days after, for the same rep (§4.5) | Expose any of it, show history (6.4), or remember a request (7.7) — part 6 |
| | "Give a contact up" (drafted in `00-interface.md`, in no decision) — not built |

## 3. What exists, checked

| Fact | Where |
|---|---|
| One holder per contact: `contacts.owner_id`; one contact per phone: `contacts_phone_unique`. `set_owner` is the one writer of the holder, emitting `contact.assigned`, `contact.assignment_expired`, or `contact.reclaimed`; only `contact.assigned` moves a contact to anyone but the house | `service/custody.py:19-66`; `jobs/migrate_grain.py:113` (the grain swap); `db/migrations/0009.partner-custody.sql:61` |
| Whose a contact is: a contact whose primary intake row is in `intake_rep` is that rep's own; any other is NMC's. A primary row is written only when a contact is created | `01-intake.md` §4.4 (answer 1); `db/migrations/0014.intake-rep.sql:15`, `:32` |
| A rep's own may be on NMC's own sheet — held by the house through a batch — and door B then answers `held`; a frozen test puts one there with `assign_batch(HOUSE_PARTNER_ID, …)` | `01-intake.md` §4.2 row 5a (answer 15); `tests/acceptance/test_rep_intake.py:119-121`, `:692-697` |
| `assign_batch` reads the partner (no lock), looks up the idempotency key, locks every candidate `for update` in id order, runs the gate, and takes the first `count` that pass in id order — pinned by a frozen test. It writes the batch row, then moves each contact with `set_owner`. It stamps its own `now` | `service/assignment.py:188-317`, `:208-209`, `:213-240`; `tests/acceptance/test_partner_assignment.py:250` |
| The gate's causes, in order: `seed`, `no_phone`, `already_assigned`, `won`, `mid_funnel`, `voice_suppressed`, `dnc_registry`, `tombstoned`, `dnc_unsubscribed`, `dnc_stale`. A frozen test pins the exact set of causes for a pool with no rep's own | `service/assignment.py:133-160`; `tests/acceptance/test_export_compliance_invariant.py:160-163` |
| **Nothing in the gate reads whose a contact is.** A rep's own that `reclaim` returned to the house, or whose block was lifted, passes the gate and can go into another rep's batch (9.13). One returned by a DNC hit or a suppression is refused by those causes | `service/assignment.py:133-160`; `service/assignment.py:381-399` |
| The 90 days are per batch: `expires_at = now + 90 days` on the batch; the nightly `run_expiry_step` returns every contact whose batch has expired. Two frozen tests expire a contact and then assign it straight back **to the same partner** with `assign_batch`; the first pins that it succeeds, the second builds on it | `service/assignment.py:208-209`, `:402-420`; `config/params.py:49`; `tests/acceptance/test_partner_assignment.py:442-472`, `:670-700` |
| **A contact held without a batch never expires.** Door B's claim of NMC's contact (part 1 row 9) calls `set_owner` with reason `added_by_rep` and no batch | `service/rep_intake.py:161-165`, `:239-244` |
| **A returned contact can be claimed again at once.** Door B answers `claimed` for NMC's contact held by the house without a batch, whoever held it before | `service/rep_intake.py:133-144` |
| Door B locks the partner `for share`, then the contacts | `service/rep_intake.py:56`, `:183-186` |
| Several writers lock contacts in their own order, not by id: the nightly's `recompute_state` (unordered updates), `resolve_orphans` (event order), `correlate_closes` (feed order; each event insert takes a key-share lock on its contact through the foreign key), and `load_list` (group order). Any of them can deadlock with a transaction that waits on many contacts in id order (part 1 §3's "`recompute_state` does not lock" is loose: its updates lock) | `service/state.py:34`, `:70-74`; `service/ingestion.py:177-203`; `jobs/close_correlation.py:64-140`; `service/contacts.py:171-215` |
| The console's "available" count is every checked, unblocked contact with no batch — a rep's holding and a rep's own included | `jobs/console.py:44-48`, `:397-401` |
| Events carry `occurred_at` and `ingested_at`; `set_owner` stamps `occurred_at` with the clock | `db/migrations/0001.create-schema.sql:98-99`; `service/custody.py:65` |
| The clock rule (9.15): new code takes `at`; existing code keeps its clock (part 1 §4.6) | `01-intake.md` §4.6 |
| The nightly returns a won contact with a batch pointer to the house — against 6.5, left to part 5 | `service/assignment.py:423-439`; `jobs/nightly.py:32-33` |
| `reclaim` returns all of a partner's holdings — the admin's "take contacts back" | `service/assignment.py:381-399` |
| The dev list, 2026-09-30: the five subscribed area codes are 714, 760, 805, 818, 916 | query on `mailengine_dev` |

## 4. The design

### 4.1 The settings (answer 2)

In `config/params.py`, like the calling window (part 3, answer 2):

| Constant | Value |
|---|---|
| `REGIONS` | `LA area`: 213 323 738 310 424 818 747 626 562 661 714 657 949 909 840 951 805 820 · `San Diego`: 619 858 760 442 · `Northern CA`: 415 628 510 341 650 408 669 925 707 369 916 279 530 837 209 350 831 |
| `REP_BATCH_SIZE` | 250 |
| `ASK_AGAIN_AT` | 50 |

559 and 357 (Fresno) are in no region. An overlay's codes are always in the same region.

### 4.2 A rep's own is never in another rep's batch (9.13)

The gate gains a cause, **`rep_own`**, right after `already_assigned`: the batch is for a
partner **other than the house** and the contact's primary intake row is in `intake_rep`.
That covers every path to a rep — the operator's id-list and rule paths, and Get more
numbers — and refuses a rep's own even to its own rep, since a batch pointer would let
the batch expiry return it. NMC's own sheet may still hold a rep's own (part 1 answer 15;
the frozen test stays green). `_gate` takes the batch's partner id.

### 4.3 Get more numbers (6.2)

`get_more_numbers(rep, region, idempotency_key, at)`. Refused first, writing nothing:
`bad_region` (not a key of `REGIONS`), then `bad_rep` (`rep` is the house), then
`bad_time` (`at` has no time zone). Then it calls `assign_batch` for `rep` with the rule
`{"area_code": REGIONS[region]}`, the count `REP_BATCH_SIZE`, and three options, all off
for every existing caller. `assign_batch` gains a no-op hook, `_after_lock(cur)`, called
once after the partner read — as part 2's `dnc._after_lock` — which the lock tests
replace to hold the first ask's transaction open; they detect the second ask waiting on
the partner row through `pg_locks`, as part 2's lock tests do.

- **Skip, never wait.** With these options, the candidate statement locks
  `for update skip locked`: a contact another transaction holds — the nightly, door B, a
  load, the operator — is left out of this draw, not waited for. An ask then waits on
  on no contact — only on its own partner row, and on another transaction's insert of the
  same idempotency key, which holds everything it needs already — so it cannot deadlock
  with any writer, whatever order that writer locks contacts in. A skipped contact is not
  drawn this time, and the shortfall reports it under **`locked`**, so an empty or short
  batch says why.

- **`max_held`**: the first read of the partner — before the idempotency lookup — takes
  the row `for no key update`, so the status check and the count are read under the lock.
  That lock conflicts with itself and with door B's `for share`, so two asks, or an ask and
  a door B claim, for the same rep run one after the other; it does not conflict with the
  key-share locks that foreign-key checks take, so an operator batch to the same rep
  cannot deadlock with it. A same-key retry waits, then finds the key and returns the
  first receipt. After the lookup, the call is refused (`not_yet`) when the partner holds
  more than `max_held` of NMC's contacts, however they came to hold them.
- **`random_draw`**: after the gate, the passing contacts are shuffled before the first
  `count` are taken, with a module-level `random.Random` that tests replace with a seeded
  one. A uniform draw from all passing contacts is in proportion to each area code's
  share of them. The contacts are still locked in id order.
- **`returned_since`**: a moment; the gate refuses (`returned_recently`, right after
  `rep_own`) a contact the partner lost by expiry at or after that moment (§4.5). Get more
  numbers passes `at − ASSIGNMENT_EXPIRY_DAYS`. It is a column of the candidate
  statement. Since the ask never waits on a contact, the only stale case is an expiry
  committing between the statement's start and its lock on that very row — §6. (A second
  read after the locks would close it, but no test can land an expiry inside one
  statement, so it would be code no test pins.)

`random_draw` and `max_held` enter the request hash, and the batch's `request` record,
when set; `returned_since` never does, so a retry stamped with a later `at` still hashes
the same and gets its first receipt. Existing callers hash as before. The hash holds the
region's codes, so a deploy that changes `REGIONS` turns a retry in flight into
`key_mismatch` — accepted: `REGIONS` changes by deploy only.
`no_partner` and `inactive_partner` come from `assign_batch` as today. The actor is the
rep id as text. Only subscribed area codes can pass the gate (`dnc_unsubscribed`), so a
region draws from its subscribed codes; a region with none gives an empty batch and a
shortfall. Each ask locks every unlocked contact in the region's codes for one short
transaction (measured, §6); asks by different reps skip each other's rows rather than
queue.

The ask-again count is NMC's contacts the rep holds. When part 5 records calls it may
narrow this to those not yet called; until then, every one counts.

### 4.4 The 90 days, counted for each contact (6.3)

`run_expiry_step` keeps its batch rule — the frozen tests drive it — and adds a second:
a contact held by a partner other than the house, **with no batch pointer**, that is
**NMC's**, **not sold** (not `won`, no `signup.completed` event on it, and no unmatched
`signup.completed` carrying its phone — door B's three tests of sold), whose **latest** `contact.assigned` event (by `occurred_at`, ties by `id`)
is more than `ASSIGNMENT_EXPIRY_DAYS` old (strictly older, as the batch rule's
`expires_at < now()`), returns to the house with `contact.assignment_expired`. The latest
`contact.assigned` is always the one that gave the current holder the contact (§3). A
sold contact stays with its holder, as today (part 1 §6), until part 5 carries out 6.5.

**One lock pass.** Both rules share one candidate statement — rule 1 *or* rule 2's
conditions (holder, batch pointer, stage, NMC's, and the latest `contact.assigned` older
than 90 days) — locked `for update of c` in id order, so the step takes its locks in one
global id order, like every other locker. After the lock, READ COMMITTED re-checks the
contact row's own columns on its current version. "NMC's" reads `intake_rep`, but a
primary row is written only when the contact is created, so it cannot change. A second
statement then re-reads, for the rule-2 rows, the latest `contact.assigned` and the three
sale tests: a claim or a sale that committed while the step waited is seen. The lock must be
`for update`, not `for no key update`: an event insert naming the contact takes a
key-share lock through its foreign key, which only `for update` waits for, so a sale in
flight is either committed before the re-read or waits for the step. The step returns the
number of contacts it returned, both rules together.

The step waits on contacts, in id order, as `reclaim` and the batch rule do today; an
ask never holds a contact the step waits for while waiting itself, since an ask waits on
no contact. An unmatched sale takes no lock on the contact, so one committing after the
second read is not seen (§6).

It covers door B's claim of NMC's contact. The first rule can meet a rep's own only on
NMC's own sheet, where it returns it from the house to the house. Neither rule returns a
rep's own from a rep, nor a sold contact held without a batch.

**The clock — a choice.** `run_expiry_step` is existing code and keeps its clock, as
`set_owner` does (part 1 §4.6): the new rule compares with `now()`, like the batch rule
beside it, rather than taking `at` from the nightly. Likewise Get more numbers' batch
`expires_at` comes from `assign_batch`'s clock; only its own checks read `at`.

### 4.5 Not the same rep for 90 days (answer 3)

For `ASSIGNMENT_EXPIRY_DAYS` after a contact goes back from a rep **by expiry** — a
`contact.assignment_expired` event whose `previous_owner_id` is that rep — the same rep
cannot come to hold it through their own actions:

- **Get more numbers** skips it (`returned_recently`, §4.3).
- **Door B** answers `held` for it, in `_judge`, after row 7 (`already_yours`) and before
  rows 8 and 9 (`claimed`): an expiry
  from this rep at or after `at − ASSIGNMENT_EXPIRY_DAYS`, the call's `at`, never the
  clock.

Other reps can get it at once. The operator's `assign_batch` is not limited: the admin
can give it back (the frozen tests do). A return by `reclaim`, a DNC hit, or a
suppression starts no wait.

## 5. Parts 1 to 3

Part 1's door B gains §4.5's `held`. Nothing else changes; part 4 reads part 1's "whose"
rule.

## 6. Gaps and limits

| Gap | Handling |
|---|---|
| The nightly returns a won contact to the house, against 6.5 | Part 5 (answer 1) |
| `reclaim`, a DNC hit, and a suppression return a rep's own to the house | As part 1 accepted (its §3, §6); only expiry is limited here |
| A rep's own on NMC's own sheet whose batch expires goes from the house to the house | Harmless |
| A region whose codes nobody subscribes to gives nothing | The shortfall says `dnc_unsubscribed` |
| Each ask locks every unlocked contact in the region's codes | Measured on dev, 2026-09-30: locking all 37,473 LA-area contacts took 83 ms; the 250 moves follow in the same transaction |
| A contact locked elsewhere during an ask is not drawn. An ask locks every candidate in its region, so a second rep asking within about 100 ms, or an ask during `recompute_state` (one transaction over every contact) or a `load_list`, gets a short or empty batch; the key is then spent, and a retry returns that receipt | Accepted: the shortfall says `locked` with the count; the rep asks again with a new key |
| An expiry from rep R committing in the instant between R's ask starting its statement and locking that contact can hand the contact straight back to R | Accepted: a window of milliseconds, needing the nightly's expiry and R's own ask on the same contact at once; the harm is a contact R lost coming back early, not a compliance breach |
| A sale with no contact (an unmatched `signup.completed`) committing after the expiry step's second read is not seen, and the step can return that sold contact | Accepted: a window of milliseconds inside the nightly, where `resolve_orphans` has just run; part 5 carries out 6.5 |
| The writers that lock contacts out of id order (§3) can still deadlock with each other, or with `reclaim`, door B or the operator's `assign_batch`, as before this part | Unchanged by part 4; an ask is never one side of it |

**The gaps part 1 handed to part 4** (`01-intake.md` §6):

| Part 1's gap | Here |
|---|---|
| A holding from door B never goes back | Closed: §4.4's second rule |
| A sold contact held through door B stays with its holder | Kept so: the second rule skips a sold contact; 6.5 itself is part 5's (answer 1) |
| A rep's own is taken back by `reclaim`, a DNC hit, and a voice suppression | Left as part 1 accepted; part 4 limits only expiry. 9.8 was part 2's |
| A holding from door B is not on the rep's exported sheet | Left: a rep who adds numbers is on the app, and 6.6 gives no export to a rep on the app |
| The assignment's trade rule does not read `intake_rep` | Not needed: Get more numbers takes a region and nothing else (6.2) |
| Nothing outside door B reads "whose it is" | Closed: §4.2, §4.3's count, §4.4 |
| The console counts a door-B holding as NMC's available inventory | Closed: "available" counts contacts whose holder is the house, with no batch pointer, that are not a rep's own (`jobs/console.py:44-48`, `:397-401`) |

## 7. Tests, written first

`tests/acceptance/test_assignment_regions.py`, the gate:

| Test | Pins |
|---|---|
| The settings | `REGIONS` holds exactly §4.1's three regions and codes; read from `domain/data/npa_report.csv` directly: every code is a California code, no code is in two regions, each overlay group's codes share a region; 250 and 50 |
| A rep's own | held by the house, refused as `rep_own` to another rep by `assign_batch` on the id-list path and on the rule path, and by Get more numbers; refused to its own rep too; `assign_batch(HOUSE_PARTNER_ID, …)` still takes it; NMC's contact beside it is assigned |
| Draw from the region | with 818 and 916 subscribed, a San Diego ask draws nothing (`dnc_unsubscribed`); an LA-area ask draws only LA-area codes |
| At random, in proportion | `assign_batch` with `random_draw` and `count=200`, seeded, two codes of 300 and 100 passing contacts: the drawn set is not the first 200 by id; both codes are drawn; the 300-code gives between 130 and 170 |
| The count | 250 when there are more; all when fewer |
| Ask again | holding 51 of NMC's, one of them a door B claim without a batch → `not_yet`, nothing written; holding 50 → assigned; a rep's own held does not count |
| Two asks at once | two keys for the same rep, the second waiting on the partner lock → the second is `not_yet` |
| Same key at once | the second, waiting on the partner lock, returns the first receipt |
| Retry | the same key with a **later `at`** returns the first receipt, even when the rep now holds more than 50 |
| Refusals | `bad_region`, `bad_rep`, `bad_time`, `no_partner`, `inactive_partner` write nothing |
| The gate still applies | a do-not-call, a DNC-file, a stale, a won, a tombstoned contact, and one with a live `dnc_numbers` row, in the region, are never drawn |
| The 90 days, per contact | door B's claim of NMC's contact, its `contact.assigned` `occurred_at` moved back 91 days → returned with `contact.assignment_expired`; at 89 days it stays; **an old batch assignment 200 days back, its expiry event moved back 110 days, then a door B claim 10 days back → it stays**; a rep's own held 91 days stays; **a sold (`won`) door B claim 91 days old stays**, and one with only a `signup.completed` event stays |
| Both rules at once | one batch-expired contact and one rule-2 contact → the step returns 2 |
| One lock pass | a blocker holds the lower-id rule-2 contact; the step waits; `select … for update nowait` on the higher-id batch-expired contact succeeds. And the mirror: a blocker holds the lower-id batch-expired contact; `nowait` on the higher-id rule-2 contact succeeds. A two-pass step fails one of the two |
| Skip, never wait | a blocker holds one contact in the region; the ask returns without waiting, that contact is not drawn, and the shortfall lists it under `locked`; a blocker holding every contact in the region → an empty batch at once, all under `locked` |
| The console | in both `_owned_inventory` and `_subscription_view`, a door-B holding and a rep's own at the house are not counted as available |
| The latest, read after the lock | a blocker connection holds the contact's lock and, on its own cursor, moves it with `set_owner` to the house and back to the rep (a fresh `contact.assigned`), while the step waits → not returned |
| A wait landing mid-call | an expiry from rep R commits while R's door B waits on the contact → `held` |
| Sold, by an unmatched sale | a door B claim 91 days old whose phone an unmatched `signup.completed` carries → stays |
| The 90-day edge | an expiry exactly 90 days before `at` → still `held`; 90 days and one second → `claimed` |
| Not the same rep for 90 days | after expiry from rep R: R's door B → `held`; **another rep's door B → `claimed`**; R's Get more numbers skips it (`returned_recently`); another rep's Get more numbers can draw it; the operator's `assign_batch` to R succeeds; R's door B with an `at` 91 days after the return → `claimed`, and R's Get more numbers with that `at` can draw it; a return by `reclaim` starts no wait |
| Existing callers unchanged | `assign_batch` without the options still takes the first by id, and its request hash is unchanged |

## 8. Done means

The gate green, and every frozen test unchanged and green; `make test`, `make e2e`,
`make lint` clean; mutation checks each failing a test — drop `rep_own`; apply it to the
house; draw in id order; drop the partner lock; lock the partner after the lookup; count
a rep's own toward `not_yet`; count only batch-held contacts; drop the second expiry rule;
use the earliest `contact.assigned`; let it return a rep's own; let it return a sold
contact; ignore an unmatched sale; lock the two rules in two passes (either order); drop
the second read; wait on locked contacts instead of skipping; leave `locked` out of the shortfall; count a rep's holding as available (in either
console query); put `returned_since`'s
moment in the hash; drop door B's wait; hold against every rep; read the wait against the
clock; drop the draw's wait. No migration.

## 9. For the operator

| # | Question | Answer |
|---|---|---|
| 1 | How should part 4 be cut? | **Answered 2026-09-30: the sale moves to part 5.** Part 4 is holding and getting numbers; the sale (6.5, 9.1–9.3), the Got a callback / Follow up exception, 9.0 and 9.12 go to part 5, where those states are built. Offered that (recommended), "Split 4a and 4b", or "Keep part 4 whole". |
| 2 | Which area codes make each region? | **Answered 2026-09-30: the proposed mapping** (§4.1), Fresno in none; the regions, batch size and ask-again point are constants in code. Offered that or "I'll give the lists". |
| 3 | When NMC's contact goes back from a rep after 90 days, can the same rep get it again right away? | **Answered 2026-09-30: not for 90 days.** Offered that (recommended), "Yes, right away", or "Never again". The operator's own `assign_batch` is not limited (§4.5). |

## 10. The migration

None.

## 11. Proposed changes to the decision record and documents

| Item | Proposal |
|---|---|
| 6.2 | Add: the regions (§4.1), the batch size and the ask-again point are constants in code, changed by a deploy (answer 2); the ask-again count is NMC's contacts the rep holds |
| 6.3 | Add: a contact that goes back from a rep by expiry cannot come back to that rep through their own actions for 90 days (answer 3) |
| 9.13 | Settled: a rep's own is never in another rep's batch (§4.2) |
| `01-intake.md` §4.2, door B's rows | Add, after row 7 and before rows 8 and 9: "this rep lost it by expiry within 90 days → `held`" (answer 3) |
| 9.0, 9.1, 9.2, 9.3, 9.12 | Part column: 5 (answer 1) |
| §10, "claiming again" | Note: a rep may claim a contact again, except within 90 days of losing it by expiry (answer 3) |
| `00-overview.md` | Part 4 is holding and getting numbers; the sale is part 5's |

## 12. Safety properties

Each revision is checked against these before review.

1. A rep's own is never assigned by any batch to a rep, and never returned from a rep
   by expiry.
2. Get more numbers passes every contact through the same gate as every batch; no DNC
   rule is skipped.
3. A rep cannot hold more than `ASK_AGAIN_AT` + `REP_BATCH_SIZE` of NMC's contacts through
   Get more numbers, whatever the timing of their asks.
4. NMC's contact held without a batch, not sold, returns 90 days after its latest
   assignment; a batch-held contact returns as today.
5. A contact returned from a rep by expiry does not come back to that rep through their
   own actions within 90 days, except in the millisecond window of §6.
6. Existing callers of `assign_batch` behave as before, except that `rep_own` refuses a
   rep's own to a rep; every frozen test is unchanged and green.
7. A sold contact is not returned from its holder by the second expiry rule, except a
   sale with no contact committing in §6's window.
8. An ask never waits on a contact lock, so it is never one side of a deadlock over
   contacts.
