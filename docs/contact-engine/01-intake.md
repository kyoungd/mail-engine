# contact-engine Upgrade — Part 1: Intake

**Status:** APPROVED by the operator, 2026-09-30 (revision 8; offered "Approve", "One
more review", or "Read it first"; chose approve). Approval does not start the build:
the `suppress()` and scrub lock fix comes first, then the build plan under the red-tier
gate (§8). History: Revision 1 did not pass its review (a
missing result for a rep's own contact held by the house, a clock test that
contradicted the clock rule, no locking). Revision 2 did not pass (a migration check
that could not be carried out). Revision 3 did not pass (an opted-out contact with no
`do_not_call` flag could be claimed). Revision 4 did not pass (a false statement that the seller of a sale is not
kept — question 12 was re-asked on the corrected fact — and a contact on NMC's own
sheet treated as held by nobody). Revision 5 did not pass (a sale not yet matched to a
contact was not refused). Revision 6 did not pass (a sale matched to a contact but not
yet recomputed to `won` was not refused). Revision 7 **passed** its review (no blocking
finding); its minor findings are corrected here, in revision 8. Questions in §9, all
answered, including two that revision 7's review raised (14, 15). **Not approved.** Nothing is built.
**Part of:** [the upgrade](00-overview.md). Decisions are in the decision record,
`nvermisscall/docs/active/sales-partner-dialer-decisions.md`, named here by number
("decision 4.1"); sections of this document are named "§4.1".
**Checked against:** the `contact-engine` branch at `fa3042f` (part 0 built). A
statement about the code carries its file and line.

---

## 1. Its job

Get a number in, and know whose it is. Two doors:

| Door | Who | Exists today |
|---|---|---|
| **A. NMC loads a list** | The operator, from the command line | Yes: `python -m jobs.intake_cli`, over `load_list` (`service/contacts.py:84`) |
| **B. A rep adds numbers** | A rep: one number in the app or on the website, or a file on the website (decision 3.1) | No |

What part 1 keeps about each number: the business, the number, whose contact it is
(NMC's or the rep's own), and, for door B, how the rep got it and the confirmation they
gave (decision 3.2).

## 2. Its edges

| Part 1 does | Part 1 does not — who does |
|---|---|
| Creates the contact, or finds the one that has the number | Checks it against a DNC file — part 2. The daily scrub checks contacts in a subscribed area code that were never checked or were checked over 21 days ago (`jobs/dnc_refresh.py:80-96`; `config/params.py:19`), so a new number a rep adds is checked on the next production run with no new code; a claimed contact keeps its last check; a number in an area code nobody subscribes to is never checked. A hit takes the contact from its holder back to the house (`jobs/dnc_refresh.py:140-146`), a rep's own included; see §6. |
| Says whose contact it is | Works out its time zone — part 3 |
| Makes the adding rep hold it (decision 3.3) | The 90 days, batches, taking back, a sale — part 4 |
| Refuses a number it must not take, with a reason | Decides when it is called — part 5 |
| | Reads a file, speaks HTTP, names the reason in words for the rep, remembers a request for 90 days (decision 7.7) — part 6. Part 1's verb takes rows and returns a result for each row. |

## 3. What exists, checked

| Fact | Where |
|---|---|
| One contact per phone, seeds apart | index `contacts_phone_unique` (`jobs/migrate_grain.py:113`) |
| A load dedupes on each row's `list_key`, then resolves rows to contacts by the source's identity rule; an unknown source is refused before a row is read | registry `service/contacts.py:47-75`; dedupe `:107-129`; resolution `:171-181`, `:225-297` |
| A CSLB (phone-rule) row whose phone already has a contact **attaches** to it: the contact keeps its first row as primary, and no field changes except that `do_not_mail` can be turned on. An FBN row never attaches. | `service/contacts.py:242-266` |
| A new contact takes its suppression columns from any tombstone for its phone or list key, so a "don't call me again" survives a hard delete | `service/contacts.py:152-168`, `:290-292` |
| A contact can have opted out with neither `do_not_call` nor a tombstone: before `0010`, `suppress()` recorded every opt-out as a `contact.opt_out` event; `0010` added `do_not_call` defaulting to false, with no backfill, and tombstones begin there; `ingest_event` still records `contact.opt_out` without either. Such a contact derives stage `suppressed` (any `contact.opt_out` whose reason is not `do_not_mail`), which the assignment refuses | `derivation/rules.py:66-79`; `0010.suppression-split.sql:15`; `service/ingestion.py:94`; `service/assignment.py:43`, `:148-149` |
| Who holds a contact is `contacts.owner_id`; NMC is the house partner, itself an active `partners` row. `set_owner` is the one writer; it emits only `contact.assigned`, `contact.assignment_expired`, `contact.reclaimed`, and stamps the event with the clock | `service/custody.py:19`, `:65`; `derivation/custody.py:18-20`; migration `0009` |
| A held contact goes back to the house on a DNC hit, on a voice or all-channel suppression, and on `reclaim` — whoever holds it | `jobs/dnc_refresh.py:140-146`; `service/contacts.py:486-492`; `service/assignment.py:370-388` |
| `assign_batch`, `reclaim`, and the expiry and won steps lock rows `for update`, in id order; `recompute_state` does not lock. `suppress()` does **not**: it reads the owner with a plain `select`, although `service/assignment.py:5-10` says both lock. The DNC scrub reads the owner in one transaction (`_due`) and acts on it in another (`_apply`) | `service/assignment.py:5-10`, `:257`, `:265`, `:379`, `:400`, `:420`; `service/contacts.py:446-447`; `jobs/dnc_refresh.py:80-96`, `:125-146` |
| A contact held by anyone but the house is never put in another rep's batch; `responded` and `in_conversation` are refused as `mid_funnel` | `service/assignment.py:142-149` |
| A sold contact (`stage_snapshot = 'won'`, recomputed nightly) held through a batch goes back to the house at night | `service/assignment.py:412-428` |
| Who sold it is kept on the `signup.completed` event (`sold_by`, `partner_code`) when the website's feed supplies it; nothing reads it, and it can be empty | `jobs/close_correlation.py:127-138`; `seams/nmc_closes.py:55` |
| A sale whose phone matches no contact is stored unmatched: `signup.completed` with no contact and the phone in the payload. Checkout collects no phone; the wizard writes it days later, and the feed backfills it within 45 days, so a sale can sit unmatched with **no phone** for days. The nightly `resolve_orphans` attaches an unmatched event by mailer code, then thread, then exact phone | `jobs/close_correlation.py:18-23`, `:68-80`, `:88-100`, `:127-141`; `resolution/matcher.py:50-67`; `jobs/nightly.py:25` |
| Matching an orphan sale to its contact (`resolve_orphans`) and deriving `won` (`recompute_state`) commit in separate transactions, so a matched sale can sit on a contact whose stage is not yet `won` — until the next recompute that succeeds | `service/ingestion.py:170-215`; `service/state.py:26-74`; `jobs/nightly.py:25-30` |
| A phone is any 10 digits (11 with a leading 1) | `domain/phone.py:8-16` |
| An FBN row keeps its phone off the contact; FBN rows carry no phone today | `service/contacts.py:253`, `:278-281`; `intake/fbn_ca.py:74` |
| There is no marker of who sourced a contact. It was built and removed on 2026-08-06. | migrations `0011`, `0012` |

## 4. The design

### 4.1 Door A: NMC loads a list

Unchanged. A CSLB load that meets a number a rep already added attaches, as today
(`service/contacts.py:261`); the contact stays the rep's own and the rep keeps holding
it, because the rep's row is its primary row. An FBN load never attaches: it makes a
separate contact with no phone (`service/contacts.py:229-230`, `:253`).

A new kind of list NMC buys (decision 1.10; 9.6 left open) gets its own converter and
its own registry entry when it arrives (decision 2.8).

### 4.2 Door B: a rep adds numbers — one verb

`add_numbers(rep, rows, how_obtained, confirmation, at)`, in `service/`. One number is a
list of one; a file is a list of many. One transaction. It returns one result for each
row, in order.

**What a row carries:** the phone (required); the business name; the contact's name and
role; the trade; the city; the state; optionally its own `how_obtained`.

**The whole call is refused, and nothing is written, for the first of these that applies, in order:**

| The call | Refused as |
|---|---|
| The rep is unknown, inactive, or the house — read with `select … for share` on the rep's `partners` row, so a deactivation waits for the call or the call sees it | `bad_rep` |
| The confirmation is missing, or empty once whitespace is stripped (`str.strip()`) | `no_confirmation` |
| A row has no `how_obtained` of its own and the call has none; or any given `how_obtained` is not one of `met_in_person`, `they_contacted_me`, `referral`, `public_or_research` | `bad_how_obtained` |
| There are no rows | `no_rows` |

**Otherwise each row gets the first result that applies:**

| # | The number | Result | What is written |
|---|---|---|---|
| 1 | Is not a valid number: `to_e164` gives nothing, or the area code or exchange starts with 0 or 1, or either is an N11 code | `invalid_phone` | Nothing |
| 2 | Has the same E.164 as an earlier valid row in the call | `duplicate_in_request` | Nothing |
| 3 | Has "don't call me again": `do_not_call`; a voice tombstone for the phone; or its events make `derivation.rules.is_suppressed` true — a `contact.opt_out` whose reason is not `do_not_mail`, a missing reason included (read from the events, not the nightly stage); or an unmatched `contact.opt_out` event carries the phone | `do_not_call` | Nothing |
| 4 | Is sold, and this rep does not hold it: the contact has a `signup.completed` event (read from the events, not the nightly stage), or its `stage_snapshot = 'won'`, or an unmatched `signup.completed` event carries the phone | `held` | Nothing |
| 5 | Is held by another rep | `held` | Nothing |
| 5a | Is on NMC's own sheet: held by the house through a batch (`assignment_batch_id` set) | `held` — NMC is dialing it (decisions 3.3, 6.1). A rep's own contact is refused here too while it is on NMC's sheet, and taken back once it leaves (answers 7, 15) | Nothing |
| 6 | Is another rep's own, now held by the house | `held` — a rep's own are never taken back (decision 6.3; answer 14) | Nothing |
| 7 | Is held by this rep | `already_yours` | Nothing |
| 8 | Is this rep's own, now held by the house | `claimed` — the rep holds it again (answer 7) | The rep's row, not primary; the rep holds it |
| 9 | Is NMC's, held by the house (decision 3.3) | `claimed` — stays NMC's; this rep holds it | The rep's row; the rep holds it |
| 10 | Has no contact | `added` — the rep's own; this rep holds it | A new contact; the rep's row as its primary; the rep holds it |

- **"Held by the house"** in rows 6, 8 and 9 means `owner_id` is the house **and** no
  batch: `assign_batch` accepts the house as a partner (`service/assignment.py:213-225`),
  so the operator's own sheet is a house batch, and `_gate` counts a batch pointer as
  held (`service/assignment.py:142`).
- **Rows 4 to 6 say the same thing,** so a rep learns nothing about another rep's
  contact (interface §5), and row 5a says it too. No test can tell them apart, and none
  needs to.
- **Row 4** refuses every sold business the rep does not already hold (answer 12). The
  seller is recorded when the feed supplies it (§3), but nothing reads it and it can be
  empty; how decision 6.5 reads it is part 4's (decision 9.1). This carries part of
  decision 6.5 into part 1 early, because door B would otherwise hand a sold business to
  a rep; part 4 may narrow it to "everyone but the rep who sold it". `won` is set by the nightly recompute, so a sale
  made is not seen until the nightly feed brings it (`jobs/nightly.py:26-29`), and a sale
  that arrives with no phone is not seen until its phone does — days, per decision 9.2
  (§3). A rep can claim or add such a business in that window; the holding then stays
  with the rep (§6), a known limit until part 4. Row 4
  reads the contact's own `signup.completed` events as well as its stage, because a sale
  is matched to its contact before `won` is derived, in a separate transaction (§3), and
  a recompute that fails leaves that gap open until one succeeds. `correlate_closes`
  writes a matched sale without locking the contact (`jobs/close_correlation.py:74-80`,
  `:136-139`), so one that commits after `add_numbers` reads the events is not seen —
  the same known limit.
- **Row 3** refuses a blocked number because it would never be callable
  (decision 7.11; answer 3). It reads the opt-out events as well as the flag, because
  older opt-outs carry no flag and no tombstone (§3). Decision 4.4 lets the reporting
  rep undo a "don't call me again" within 24 hours; the tombstone and the events stay,
  so row 3 would still refuse after an undo — part 2's to reconcile. The row lock of
  §4.3 does not cover an opt-out recorded as an event alone (`ingest_event`,
  `service/ingestion.py:94`, touches no contact row): one committing after
  `add_numbers` reads the events leaves the rep holding an opted-out contact. No code
  records such an event today (`suppress()` sets the flag too, `service/contacts.py:455-463`);
  a known limit, the same one a batch holding has. The same holds for a
  `contact.suppressed` event with channel `voice` recorded without the flag: row 3 does
  not read it (`is_suppressed` reads `contact.opt_out` only, `derivation/rules.py:74-79`),
  and no code records one without the flag (`suppress()` writes the flag at
  `service/contacts.py:455-463` and the tombstone at `:477-482`).
- **Unmatched events** (rows 3 and 4) are read by phone with the matcher's own rule —
  `payload.phone_e164`, else `payload.phone` normalized by `to_e164`
  (`resolution/matcher.py:63`) — so an event row 3 or 4 finds is one `resolve_orphans`
  would attach by phone, unless a mailer code or thread matches it first
  (`resolution/matcher.py:50-61`). Refusing then is the safe side. They are not covered by the row lock: an unmatched sale or
  opt-out stored after `add_numbers` reads them is not seen. The same night
  `resolve_orphans` attaches it; a sale then leaves a door-B holding with its holder
  (§6), a known limit until part 4.
- **Row 9** claims whatever stage the contact is in, including `responded` and
  `in_conversation`, which `assign_batch` refuses (answer 8).
- **A `dnc_registry = true` contact** is claimed or added like any other. The call is
  blocked later by the DNC check, not by intake (decision 4.1).
- **A mail- or sms-only tombstone** does not refuse; the new contact carries
  `do_not_mail` / `do_not_text` from it, as `load_list` does.
- **The phone is looked up on `contacts` only.** This is right while every source
  that carries a phone puts it on the contact; an FBN-like source that kept a phone
  only on its intake row would make door B create a second contact. A test pins the
  assumption; a new source that breaks it (9.6) must change this lookup. For the same
  reason a voice tombstone written for a contact with no phone (keyed by list key only,
  `service/contacts.py:477-482`) is not found by a rep who adds that business by phone:
  a known limit, because identity is never matched fuzzily.
- **A refused row writes nothing,** so the same call can be sent again. Sending it
  again is judged against the contact as it is then, not remembered: if the holding
  changed in between, the second send is a new claim. Remembering a request is part 6's
  (decision 7.7).

### 4.3 Locking

Before judging rows 3 to 10, `add_numbers` locks the contact rows of every valid phone
in the call — `where phone_e164 = any(…) and is_seed = false order by id for update` —
in id order, the order `assign_batch`, `reclaim`, and the expiry and won steps use, so they
serialize on the same rows. New contacts are inserted in phone order, so two
`add_numbers` calls adding the same new phones do not deadlock: the later one waits,
then hits `contacts_phone_unique`. A door-A load inserts in its own group order
(`service/contacts.py:171-181`, `:225-239`) and locks the existing contacts it attaches
to in that order too (the foreign-key check of each intake insert, `:183-207`; the
`do_not_mail` update, `:262-265`), so a load and a call that touch overlapping phones,
new or existing, can deadlock, or collide on a new phone at `contacts_phone_unique`;
either way the load may be the one that aborts (`service/contacts.py:269-294`), and then
it rolls back the whole file. `recompute_state` updates every contact in one transaction in no set order
(`service/state.py:34`, `:70-74`), so it can deadlock with a call too, as it already can
with `assign_batch`; if the recompute is the victim, that night's recompute rolls back.
Of the nightly steps, only expiry and the won step lock in id order. A unique-index collision or a deadlock aborts the whole call with
an error, to be sent again — never partly applied (the `assign_batch` precedent,
`service/assignment.py:10-11`).

The `for share` lock on the rep's `partners` row (§4.2) makes a deactivation wait for
the call; it also makes `export_batch`'s stamp of the rep's row
(`service/assignment.py:340-343`) and the token writes of `partners_cli`
(`jobs/partners_cli.py:92`, `:157`) and its `set` upsert — how a deactivation is issued
(`jobs/partners_cli.py:268-271`) — wait. That is waiting, not deadlock. `reclaim`
selects the rep's holdings by `owner_id` (`service/assignment.py:377-381`), so a claim
that commits while a reclaim runs is left with the rep: a known limit; the order
"deactivate, then reclaim" avoids it.

`suppress()` does not lock (§3), so a suppression and a claim landing together can leave
`do_not_call` on a contact the rep holds. That defect exists today against
`assign_batch`; it is red-tier code outside this part. It is fixed before part 1 is
built, as its own red-tier change (answer 9). The DNC scrub has the same pattern (§3): a
claim between `_due` and `_apply` leaves `dnc_registry = true` on a contact the rep
holds. It is fixed with `suppress()` (answer 11). Neither lets a number onto a sheet: the export filters both flags
(`service/assignment.py:335`).

### 4.4 Where it is kept

**The rep's row** goes in a new intake table, `intake_rep` (§10): immutable; what the
rep entered, the rep, how they got the number, the confirmation, and when. It is the
record decision 3.2 asks for. It is **not** added to `load_list`'s source registry
(`service/contacts.py:47-51`): `load_list(source='rep')` stays refused.

**A new contact (row 10)** is inserted by `add_numbers` itself, not by `load_list`'s
helpers, which key on `list_key` and address fields a rep's row does not have. It sets:
`phone_e164`, `business_name`, `contact_name`, `addr_city`, `addr_state` from the row;
`source = 'rep'`; `segment` null; and `do_not_mail` / `do_not_text` from any mail or
sms tombstone for the phone (by phone only — a rep's row has no list key). The rep's
row is inserted with `is_primary = true`.

**A claimed contact (row 9)** is not changed; the rep's row is inserted with
`is_primary = false`.

**Holding:** `set_owner` to the rep, event `contact.assigned`, reason `added_by_rep`,
no batch and no expiry. No new event type.

**Whose it is (answer 1):** the contact's primary intake row. A contact whose primary
row is in `intake_rep` is that rep's own; any other is NMC's. At most one intake row per
contact is primary, across all three tables; a contact with none (a retired seed,
`service/contacts.py:355`) is NMC's. The database enforces one per table only
(the partial unique indexes); the rule across tables is the code's: door B marks one
only when it creates the contact, and door A attaches without marking one
(`service/contacts.py:266`). §7 "Door A after door B" pins it.

### 4.5 The confirmation

The website and the app show the wording. contact-engine stores, on each row, the text
the rep confirmed, with surrounding whitespace stripped by Python's `str.strip()` (stricter
than the table's `btrim` check), so a later change of wording does
not change what an earlier rep confirmed. A confirmation that is empty once stripped is
refused (`no_confirmation`).

### 4.6 The clock (decision 9.15; answer 4)

`add_numbers` does not ask what time it is. The time comes in as `at` from the
outermost layer, and `add_numbers` writes it as `intake_rep.added_at`. `at` must carry
a time zone; a naive `datetime` is refused, because `added_at` is `timestamptz` and would
be read in the session's zone. Times that
existing code sets are not changed by this part: `set_owner` stamps its event with the
clock (`service/custody.py:65`), and `created_at` / `ingested_at` take the database's
`now()` by default.

## 5. The decision of 2026-08-06, reconciled

(`docs/mail-engine-backup/decisions.md:1061-1165`; handoff §4.) The first 08-06 entry
(partner-sourced numbers, with its addendum) was **reversed the same day** (`:1130`).
The rows below that name it say what part 1 does about each idea; none of them was in
force.

| The decision of 08-06 | Part 1 |
|---|---|
| A rep's word is no basis to call a number on a DNC file; a signed writing is required | **Stands.** Every number a rep adds is checked like any other (decision 4.1). Nothing is waived. |
| Waiving the check for one category risks the safe harbor for the whole program | **Stands.** |
| A referral is a name and a town, never a number; the operator assigns by id | **Replaced** by decisions 3.1–3.3. The rep adds the number. The partner-facing procedure still says otherwise (`nvermisscall/docs/partner-dialing-procedure.md:20-24`, rule 2); a change to it is proposed to the operator when door B ships, not before. |
| A contact the rep brings that NMC already has goes to the rep ("he worked for it"; reversed 08-06) | **Re-decided** by decision 3.3. |
| The marker of who sourced a contact was a column, never cleared automatically (reversed 08-06) | **Replaced:** the primary intake row, which nobody writes (answer 1). |
| A conflict with another rep is judged by the operator (reversed 08-06) | **Replaced** by decisions 3.3 and 6.1: refused, `held`. |
| A hand-picked referral goes through the assignment's `_gate`, all DNC predicates included | **Does not apply to door B.** A claim does not run `_gate`: it skips `mid_funnel` (answer 8) and the DNC predicates, which apply at calling time (parts 2 and 5) and at export. |
| When a partnership ends, custody returns at once and the attribution clears after 30 days (reversed 08-06) | **Replaced** by decision 8.8 (a departed rep's own contacts: 30 days after they leave) and by the put-off departure automation (record §10). Not part 1's. |

## 6. Gaps while the upgrade is built

Not questions (decision 2.9). Listed so they are not mistaken for the design.

| Gap | Where | Closed in |
|---|---|---|
| A holding from door B never goes back: expiry acts on batches only | `service/assignment.py:397-400` | Part 4 (decision 6.3) |
| A rep's own contact is taken back to the house by `reclaim`, by a DNC hit, and by a voice suppression | `service/assignment.py:370-388`; `jobs/dnc_refresh.py:140-146`; `service/contacts.py:486-492` | Part 4 (decision 6.3); part 2 (decision 9.8) |
| A sold contact held through door B stays with its holder: the won step acts on batches only | `service/assignment.py:419-420` | Part 4 (decisions 6.5, 9.1) |
| A holding from door B is not on the rep's exported sheet: the export joins batches | `service/assignment.py:332-333` | Part 4 (decision 6.6) |
| The assignment's trade rule does not read `intake_rep` | `service/assignment.py:40`, `:87-99` | Part 4, if it needs it |
| Nothing outside `add_numbers` reads "whose it is" yet | — | Part 4 (decisions 6.3, 6.4, 9.13) |
| The console counts a door-B holding as NMC's available inventory: it treats any contact with no batch as available | `jobs/console.py:44-48`, `:397-401` | Part 4 |
| **Consequence, to close before anything is deployed:** once part 1 exists, a rep's own contact sent back to the house (by `reclaim` or a DNC hit, and batchable again after a delisting, `jobs/dnc_refresh.py:140-160`) can go into another rep's batch and onto their sheet, because `_gate` does not read whose it is | `service/assignment.py:134-160`, `:325-337` | Part 4 (decisions 6.3, 9.13) |
| No door B from outside; the verb is reached from tests only | — | Part 6 |

## 7. Tests, written first

The new tests create their reps as `partners` rows. `clean_db` truncates `contacts …
cascade`, which clears `intake_rep`, but never `partners` (`tests/conftest.py:116-118`);
so each test deletes, at teardown, its `intake_rep` rows and then its reps
(`intake_rep.rep_id` references `partners`), as tests that create partners do today.

| Test | Checks |
|---|---|
| Each whole-call refusal (§4.2) | The result, and nothing written: `bad_rep` for an unknown rep, an inactive rep, and the house; `bad_how_obtained` for one missing from both row and call, and for an invalid value; `no_confirmation` for a confirmation of only whitespace; `no_rows` |
| The stored confirmation | Equals the input's `strip()` |
| A row's own `how_obtained` | It overrides the call's, and is the value stored on that row |
| Each row result, 1 to 10 and 5a | The result, and that a refused row writes nothing. Row 1 includes an N11 area code (`211…`) and an N11 exchange (`…411…`), which only the verb refuses |
| The order | Pairs that can meet: invalid + duplicate → `invalid_phone`; duplicate + `do_not_call` → `duplicate_in_request`; `do_not_call` + this rep's own at the house → `do_not_call`; sold + held by this rep → `already_yours`; sold + NMC's at the house → `held`; sold + this rep's own at the house → `held`; `do_not_call` + held by this rep → `do_not_call`; `do_not_call` + held by another rep → `do_not_call`; `do_not_call` + sold → `do_not_call`; on NMC's sheet + NMC's → `held`; on NMC's sheet + this rep's own → `held`; `bad_rep` + `no_rows` → `bad_rep`; `do_not_call` + on NMC's sheet → `do_not_call`; `do_not_call` + another rep's own at the house → `do_not_call`; `(818) 555-0123` then `18185550123` → the second is `duplicate_in_request` |
| A new number | A contact with `source = 'rep'`; one `intake_rep` row, primary; the rep holds it; one `contact.assigned` event, reason `added_by_rep` |
| NMC's number, held by the house | The contact's fields unchanged; its primary row still NMC's; the rep's row not primary; the rep holds it |
| Another rep's own, back at the house | `held`; nothing written |
| This rep's own, back at the house after a DNC hit or `reclaim` | `claimed`; the rep holds it; its primary row is still the rep's first |
| A voice tombstone | `do_not_call`; no contact created |
| An unmatched sale | An unmatched `signup.completed` carrying the phone, no contact: `held`; nothing written. Again with the phone as `(818) 555-0123` in `payload.phone`: `held` |
| An unmatched opt-out | An unmatched `contact.opt_out` carrying the phone: `do_not_call`; nothing written. Once with the phone in `payload.phone_e164`, once as `(818) 555-0123` in `payload.phone` |
| A matched sale before the recompute | An NMC contact at the house with a `signup.completed` event and `stage_snapshot` not `won`: `held`; nothing written |
| An old opt-out | An NMC contact at the house with a `contact.opt_out` event, reason `phone`, `do_not_call = false`, no tombstone, stage not yet recomputed: `do_not_call`; nothing written. Again with no reason in the payload: `do_not_call` |
| A mail-only opt-out event | An NMC contact at the house with a `contact.opt_out` event, reason `do_not_mail`: `claimed` |
| A mail- or sms-only tombstone | `added`, with `do_not_mail` / `do_not_text` set |
| A `dnc_registry = true` house contact | `claimed` |
| An `in_conversation` house contact | `claimed` |
| The same call twice | The second returns `already_yours` for every row the first added or claimed; nothing new written |
| Whose it is | Rep's own for row 10, NMC's for row 9, and unchanged after the contact goes back to the house |
| Door A after door B | The list's row attaches; the contact stays the rep's own and held; exactly one primary row for it across the three tables |
| The clock | `intake_rep.added_at` equals `at`; a naive `at` is refused and nothing written |
| The source registry | `load_list(source='rep')` is refused |
| Read access | The read-only role can select from `intake_rep` |
| The phone lookup | A phone that sits only on an intake row, not on a contact, is `added` as a new contact — the assumption of §4.2, pinned |
| Locking | Another connection locks the contact row `for update`, sets `do_not_call = true` (in a second run: moves the owner to another rep), and commits only after `add_numbers` has started waiting. The result is `do_not_call` (second run: `held`). Two more runs, flag untouched: the other connection, while holding the lock, inserts a voice tombstone for the phone; or inserts a `contact.opt_out` event for the contact. Both give `do_not_call`. A fifth run: it inserts a `signup.completed` event for the contact; the result is `held` — so a judgment from any read taken before the lock fails the test |
| A unique-index collision | A hook in `add_numbers`, between its locking select and its insert, lets a second connection insert a contact with the same phone and commit. The call raises and writes nothing |
| A deactivation | A deactivation issued while `add_numbers` holds the `for share` lock waits until the call commits; a call started after it is refused `bad_rep` |

## 8. Done means

| Check | How |
|---|---|
| The build follows the red-tier gate | `add_numbers` creates contacts and consults tombstones, and `0014` is a migration — both red-tier (`marketing/CLAUDE.md`). The build plan is shown and explicitly approved before any code; the tests are approved as its first step |
| The `suppress()` and scrub locks (answers 9, 11) are built first | Their own commit, before part 1's |
| The tests of §7 pass; the existing intake tests pass unchanged | `make test` |
| `make e2e`, `make lint` | Pass |
| `0014` applies over production's data and changes no existing row | Restore the newest `mailengine_prod` backup into a scratch database (never `mailengine_prod` itself). Record which migrations it already has. Bring it to `0013` from a checkout without `0014` (e.g. `git worktree add <dir> fa3042f`): `yoyo apply --batch --database <scratch owner URL> db/migrations`, then `OWNER_DATABASE_URL=<scratch owner URL> python -m jobs.migrate_grain --ensure-swapped` — it reads the URL from the environment (`jobs/migrate_grain.py:277`, `db/session.py:12`), and there is no dotenv loader, so without the prefix it would reach whatever `OWNER_DATABASE_URL` the shell holds. Record which migrations that applied. That is the baseline. Then, from this branch, `yoyo apply --batch --database <scratch owner URL> db/migrations`, which applies `0014` alone. For every table in the baseline except yoyo's (`_yoyo_*`, `yoyo_lock`), compare the baseline with the result: row count, and an `md5` over its rows ordered by `t::text`. Every pair matches; `intake_rep` exists and is empty; and `has_table_privilege('me_user_ro', 'intake_rep', 'select')` is true on the scratch database. |

## 9. For the operator, one at a time

| # | Question | Proposed |
|---|---|---|
| 1 | ~~Whose it is: the primary intake row, or a column~~ | **Answered 2026-09-29:** the primary intake row. Offered "First intake row" or "A column on contacts"; chose the first intake row. |
| 2 | ~~The choices for how a rep got a number~~ | **Answered 2026-09-29:** the four drafted — met them in person, they contacted me, referral, public listing or my own research. Offered also "Four plus Other" and "Two: direct / not direct". |
| 3 | ~~A number with "don't call me again": refuse it at intake, or take it and show it blocked~~ | **Answered 2026-09-29:** refuse it (§4.2 row 3). Offered "Refuse it" or "Take it, show it blocked". |
| 4 | ~~The clock rule (9.15)~~ | **Answered 2026-09-29:** new code only, as in §4.6. Offered "New code only", "New code + retrofit", or "No rule". |
| 5 | ~~What expanding NMC's list covers (9.6)~~ | **Answered 2026-09-29:** leave 9.6 open until a list is in hand. Offered "Leave open", "More of California", or "Other states". |
| 6 | ~~The migration: the new table `intake_rep`~~ | **Answered 2026-09-29:** the SQL approved as shown; two checks added by answer 10. |
| 7 | ~~A rep adds their own contact that has gone back to the house (§4.2 row 8)~~ | **Answered 2026-09-29:** take it back — `claimed`, the rep holds it again. Offered "Take it back" or "Refuse it". A contact that went back by a voice suppression never reaches row 8: row 3 refuses it first. |
| 8 | ~~Row 9 claims an NMC contact in any stage, including `responded` / `in_conversation`~~ | **Answered 2026-09-29:** claim it. Offered "Claim it" or "Refuse it". |
| 9 | ~~`suppress()` does not lock the contact row (§4.3)~~ | **Answered 2026-09-29:** fix it before part 1 is built, as its own red-tier change: a failing test first, the plan shown before any code. Offered "Fix before part 1", "Fix inside part 1", or "Leave it, record it". |
| 10 | ~~Two additions to the approved SQL~~ | **Answered 2026-09-29:** add both — `check (confirmation <> '')` and the phone pattern (§10). Offered "Add both", "Confirmation only", or "Neither". The pattern does not exclude N11 codes; the verb does (§4.2 row 1). |
| 11 | ~~The DNC scrub acts on an owner read in an earlier transaction (§4.3)~~ | **Answered 2026-09-29:** fix it with `suppress()`, in the same red-tier change. Offered "Fix with suppress()" or "Record for part 2". |
| 12 | ~~§4.2 row 4 refuses every sold business the rep does not hold (part of 9.1, early)~~ | **Answered 2026-09-29:** keep row 4 until part 4 designs 9.1. Offered "Keep until part 4" or "Allow any rep". **Re-asked 2026-09-30:** the question had said who sold it is not recorded; it is, on the signup event, when the feed supplies it. Offered "Refuse all, until part 4" or "Let the recorded seller"; chose refuse all, until part 4. |
| 13 | ~~Two changes to the SQL~~ | **Answered 2026-09-29:** both — `btrim(confirmation) <> ''`, and the two indexes nothing in part 1 reads are dropped (§10). Offered "Both", "btrim only", or "Neither". |
| 14 | ~~§4.2 row 6: another rep's own contact, back with NMC~~ | **Answered 2026-09-30:** refuse it, `held`. Offered "Refuse, `held`" or "Let them claim it". |
| 15 | ~~§4.2 row 5a against answer 7: a rep's own contact on NMC's own sheet~~ | **Answered 2026-09-30:** refuse it while it is on NMC's sheet; once it leaves, the rep takes it back. Offered "Refuse while on NMC's sheet" or "Rep takes it back". |

## 10. The migration, `0014.intake-rep.sql`

Additive: one new table, no existing row changed. As approved (answer 6), with the two
checks of answer 10 and the changes of answer 13.

```sql
create table intake_rep (
  id             uuid primary key default gen_random_uuid(),
  contact_id     uuid not null references contacts(id),
  is_primary     boolean not null default false,
  rep_id         uuid not null references partners(id),
  phone_e164     text not null
                   check (phone_e164 ~ '^\+1[2-9][0-9]{2}[2-9][0-9]{6}$'),  -- q10
  business_name  text,
  contact_name   text,
  contact_role   text,
  trade          text,
  addr_city      text,
  addr_state     text,
  how_obtained   text not null check (how_obtained in
                   ('met_in_person', 'they_contacted_me', 'referral', 'public_or_research')),
  confirmation   text not null check (btrim(confirmation) <> ''),  -- q10, q13
  added_at       timestamptz not null
);

create index intake_rep_contact_idx on intake_rep (contact_id);
create unique index intake_rep_primary_key on intake_rep (contact_id) where is_primary;
```

- **Unlike `intake_cslb_ca`:** no `list_key` (a rep's rows have no list to dedupe
  against), no mail-address or delivery columns, no `trades` or `segment` (part 4 adds
  what its trade rule needs, if it needs it), and `added_at` has no default — it is
  always the `at` handed in.
- **Read access:** migrations run as the owner role (`Makefile`, `migrate`), the role
  that ran `0002.readonly-grants.sql`, whose default privileges give the read-only role
  SELECT on new tables. Checked by a test that the read-only role can read
  `intake_rep`.
- **No cascade on `contact_id`,** like the other intake tables. Nothing is deleted
  automatically in the first version (decision 8.8); a hand deletion removes a contact's
  `intake_rep` rows first, and with them the record of decision 3.2 for it. The phone's
  tombstone survives.

## 11. Proposed changes to the decision record

The record is the NeverMissCall repository's; the operator approves changes to it
(handoff §7). Proposed once part 1 is approved:

| Record item | Proposed change |
|---|---|
| 9.15, the clock rule | Move to decided: new code only (answer 4) |
| 9.6, expanding NMC's list | Stays open (answer 5) |
| 9.13, a rep's own contact kept out of batches | Stays open for part 4; add that "whose it is" is the primary intake row (answer 1), and that door B refuses another rep's own contact at the house as `held`, from decision 6.3 |
| 3.2 | Add the four choices (answer 2) |
| §4, DNC | Add: a number with "don't call me again" is refused at intake (answer 3) |
| §3, Intake | Add: a rep re-adding their own contact from the house takes it back, unless it is on NMC's own sheet (answer 7, with row 5a); a claim takes an NMC contact in any stage (answer 8) |
| 9.1 | Stays open for part 4; add that door B refuses every sold business the rep does not hold until then (answer 12) |
