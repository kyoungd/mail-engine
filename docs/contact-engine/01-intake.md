# contact-engine Upgrade — Part 1: Intake

**Status:** DRAFT, revision 3, 2026-09-29. Revision 1 did not pass its review (a
missing result for a rep's own contact held by the house, a clock test that
contradicted the clock rule, no locking). Revision 2 did not pass its review (a
migration check that could not be carried out). This revision corrects both and the
minor findings. Questions in §9. Not yet re-reviewed, not approved. Nothing is built.
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
| A load dedupes on each row's `list_key`, then resolves rows to contacts by the source's identity rule; an unknown source is refused before a row is read | `service/contacts.py:47-75`, `:84` |
| A CSLB (phone-rule) row whose phone already has a contact **attaches** to it: the contact keeps its first row as primary, and no field changes except that `do_not_mail` can be turned on. An FBN row never attaches. | `service/contacts.py:242-266` |
| A new contact takes its suppression columns from any tombstone for its phone or list key, so a "don't call me again" survives a hard delete | `service/contacts.py:152-168`, `:290-292` |
| Who holds a contact is `contacts.owner_id`; NMC is the house partner, itself an active `partners` row. `set_owner` is the one writer; it emits only `contact.assigned`, `contact.assignment_expired`, `contact.reclaimed`, and stamps the event with the clock | `service/custody.py:19`, `:65`; `derivation/custody.py:18-20`; migration `0009` |
| A held contact goes back to the house on a DNC hit, on a voice or all-channel suppression, and on `reclaim` — whoever holds it | `jobs/dnc_refresh.py:140-146`; `service/contacts.py:486-492`; `service/assignment.py:370-388` |
| `assign_batch`, `reclaim`, and the nightly steps lock rows `for update`, in id order. `suppress()` does **not**: it reads the owner with a plain `select`, although `service/assignment.py:5-10` says both lock. The DNC scrub reads the owner in one transaction (`_due`) and acts on it in another (`_apply`) | `service/assignment.py:5-10`, `:257`, `:265`, `:379`, `:400`, `:420`; `service/contacts.py:446-447`; `jobs/dnc_refresh.py:80-96`, `:125-146` |
| A contact held by anyone but the house is never put in another rep's batch; `responded` and `in_conversation` are refused as `mid_funnel` | `service/assignment.py:142-149` |
| A sold contact (`stage_snapshot = 'won'`, recomputed nightly) held through a batch goes back to the house at night; who sold it is not kept (decision 9.1) | `service/assignment.py:412-428` |
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

**The whole call is refused, and nothing is written, when:**

| The call | Refused as |
|---|---|
| The rep is unknown, inactive, or the house — read with `select … for share` on the rep's `partners` row, so a deactivation waits for the call or the call sees it | `bad_rep` |
| The confirmation is missing, or empty once spaces are stripped | `no_confirmation` |
| `how_obtained`, for the call or any row, is not one of `met_in_person`, `they_contacted_me`, `referral`, `public_or_research` | `bad_how_obtained` |

**Otherwise each row gets the first result that applies:**

| # | The number | Result | What is written |
|---|---|---|---|
| 1 | Is not a valid number: `to_e164` gives nothing, or the area code or exchange starts with 0 or 1, or either is an N11 code | `invalid_phone` | Nothing |
| 2 | Is repeated earlier in the same call | `duplicate_in_request` | Nothing |
| 3 | Has "don't call me again": `do_not_call`, or a voice tombstone for the phone | `do_not_call` | Nothing |
| 4 | Is sold (`stage_snapshot = 'won'`), and this rep does not hold it | `held` | Nothing |
| 5 | Is held by another rep | `held` | Nothing |
| 6 | Is another rep's own, now held by the house | `held` | Nothing |
| 7 | Is held by this rep | `already_yours` | Nothing |
| 8 | Is this rep's own, now held by the house | `claimed` — the rep holds it again (answer 7) | The rep's row, not primary; the rep holds it |
| 9 | Is NMC's, held by the house (decision 3.3) | `claimed` — stays NMC's; this rep holds it | The rep's row; the rep holds it |
| 10 | Has no contact | `added` — the rep's own; this rep holds it | A new contact; the rep's row as its primary; the rep holds it |

- **Rows 4 to 6 say the same thing,** so a rep learns nothing about another rep's
  contact (interface §5). No test can tell them apart, and none needs to.
- **Row 4** refuses every sold business the rep does not already hold, because who sold
  it is not kept (decision 9.1). This carries part of decision 6.5 into part 1 early,
  because door B would otherwise hand a sold business to a rep; part 4 may narrow it to
  "everyone but the rep who sold it". `won` is set by the nightly recompute, so a sale
  made today is not seen until the next night.
- **Row 3** refuses a blocked number because it would never be callable
  (decision 7.11; answer 3).
- **Row 9** claims whatever stage the contact is in, including `responded` and
  `in_conversation`, which `assign_batch` refuses (answer 8).
- **A `dnc_registry = true` contact** is claimed or added like any other. The call is
  blocked later by the DNC check, not by intake (decision 4.1).
- **A mail- or sms-only tombstone** does not refuse; the new contact carries
  `do_not_mail` / `do_not_text` from it, as `load_list` does.
- **The phone is looked up on `contacts` only.** This is right while every source
  that carries a phone puts it on the contact; an FBN-like source that kept a phone
  only on its intake row would make door B create a second contact. A test pins the
  assumption; a new source that breaks it (9.6) must change this lookup.
- **A refused row writes nothing,** so the same call can be sent again. Sending it
  again is judged against the contact as it is then, not remembered: if the holding
  changed in between, the second send is a new claim. Remembering a request is part 6's
  (decision 7.7).

### 4.3 Locking

Before judging rows 3 to 10, `add_numbers` locks the contact rows of every valid phone
in the call — `where phone_e164 = any(…) and is_seed = false order by id for update` —
in id order, the order `assign_batch`, `reclaim`, and the nightly steps use, so they
serialize on the same rows. New contacts are inserted in phone order. Deadlock is still
possible (two calls inserting overlapping new phones); like a unique-index collision on
`contacts_phone_unique`, it aborts the whole call with an error, to be sent again —
never partly applied (the `assign_batch` precedent, `service/assignment.py:10-11`).

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
row is in `intake_rep` is that rep's own; any other is NMC's. Exactly one intake row per
contact is primary, across all three tables: door B marks one only when it creates the
contact, and door A attaches without marking one (`service/contacts.py:266`).

### 4.5 The confirmation

The website and the app show the wording. contact-engine stores, on each row, the text
the rep confirmed, with surrounding spaces stripped, so a later change of wording does
not change what an earlier rep confirmed. A confirmation that is empty once stripped is
refused (`no_confirmation`).

### 4.6 The clock (decision 9.15; answer 4)

`add_numbers` does not ask what time it is. The time comes in as `at` from the
outermost layer, and `add_numbers` writes it as `intake_rep.added_at`. Times that
existing code sets are not changed by this part: `set_owner` stamps its event with the
clock (`service/custody.py:65`), and `created_at` / `ingested_at` take the database's
`now()` by default.

## 5. The decision of 2026-08-06, reconciled

(`docs/mail-engine-backup/decisions.md:1061-1165`; handoff §4.)

| The decision of 08-06 | Part 1 |
|---|---|
| A rep's word is no basis to call a number on a DNC file; a signed writing is required | **Stands.** Every number a rep adds is checked like any other (decision 4.1). Nothing is waived. |
| Waiving the check for one category risks the safe harbor for the whole program | **Stands.** |
| A referral is a name and a town, never a number; the operator assigns by id | **Replaced** by decisions 3.1–3.3. The rep adds the number. |
| A contact the rep brings that NMC already has goes to the rep ("he worked for it") | **Stands**, as decision 3.3. |
| The marker of who sourced a contact was a column, never cleared automatically | **Replaced:** the primary intake row, which nobody writes (answer 1). |
| A conflict with another rep is judged by the operator | **Replaced** by decisions 3.3 and 6.1: refused, `held`. |
| A hand-picked referral goes through the assignment's `_gate`, all DNC predicates included | **Does not apply to door B.** A claim does not run `_gate`: it skips `mid_funnel` (answer 8) and the DNC predicates, which apply at calling time (parts 2 and 4) and at export. |
| When a partnership ends, custody returns at once and the attribution clears after 30 days | **Replaced** by decision 8.8 (a departed rep's own contacts: 30 days after they leave) and by the put-off departure automation (record §10). Not part 1's. |

## 6. Gaps while the upgrade is built

Not questions (decision 2.9). Listed so they are not mistaken for the design.

| Gap | Where | Closed in |
|---|---|---|
| A holding from door B never goes back: expiry acts on batches only | `service/assignment.py:391` | Part 4 (decision 6.3) |
| A rep's own contact is taken back to the house by `reclaim`, by a DNC hit, and by a voice suppression | `service/assignment.py:370-388`; `jobs/dnc_refresh.py:140-146`; `service/contacts.py:486-492` | Part 4 (decision 6.3); part 2 (decision 9.8) |
| A sold contact held through door B stays with its holder: the won step acts on batches only | `service/assignment.py:419-420` | Part 4 (decisions 6.5, 9.1) |
| A holding from door B is not on the rep's exported sheet: the export joins batches | `service/assignment.py:332-333` | Part 4 (decision 6.6) |
| The assignment's trade rule does not read `intake_rep` | `service/assignment.py:40`, `:87-99` | Part 4, if it needs it |
| Nothing outside `add_numbers` reads "whose it is" yet | — | Part 4 (decisions 6.3, 6.4, 9.13) |
| **Consequence, to close before anything is deployed:** once part 1 exists, a rep's own contact sent back to the house (by `reclaim` or a DNC delisting) can go into another rep's batch and onto their sheet, because `_gate` does not read whose it is | `service/assignment.py:100-102`, `:134-160`, `:325-337` | Part 4 (decisions 6.3, 9.13) |
| No door B from outside; the verb is reached from tests only | — | Part 6 |

## 7. Tests, written first

| Test | Checks |
|---|---|
| Each whole-call refusal (§4.2) | The result, and nothing written |
| Each row result, 1 to 10 | The result, and that a refused row writes nothing |
| The order | Pairs that can meet: invalid + duplicate → `invalid_phone`; duplicate + `do_not_call` → `duplicate_in_request`; `do_not_call` + this rep's own at the house → `do_not_call`; sold + held by this rep → `already_yours`; sold + NMC's at the house → `held`; sold + this rep's own at the house → `held` |
| A new number | A contact with `source = 'rep'`; one `intake_rep` row, primary; the rep holds it; one `contact.assigned` event, reason `added_by_rep` |
| NMC's number, held by the house | The contact's fields unchanged; its primary row still NMC's; the rep's row not primary; the rep holds it |
| Another rep's own, back at the house | `held`; nothing written |
| This rep's own, back at the house after a DNC hit or `reclaim` | `claimed`; the rep holds it; its primary row is still the rep's first |
| A voice tombstone | `do_not_call`; no contact created |
| A mail- or sms-only tombstone | `added`, with `do_not_mail` / `do_not_text` set |
| A `dnc_registry = true` house contact | `claimed` |
| An `in_conversation` house contact | `claimed` |
| The same call twice | The second returns `already_yours` for every row the first added or claimed; nothing new written |
| Whose it is | Rep's own for row 10, NMC's for row 9, and unchanged after the contact goes back to the house |
| Door A after door B | The list's row attaches; the contact stays the rep's own and held; exactly one primary row for it across the three tables |
| The clock | `intake_rep.added_at` equals `at` |
| The source registry | `load_list(source='rep')` is refused |
| Read access | The read-only role can select from `intake_rep` |
| The phone lookup | A phone that sits only on an intake row, not on a contact, is `added` as a new contact — the assumption of §4.2, pinned |
| Locking | While another transaction holds the contact row `for update`, `add_numbers` waits for it and then judges the row as that transaction left it |
| A unique-index collision | Two connections: one inserts the phone's contact and commits after `add_numbers` has begun; the call raises and writes nothing |
| A deactivation | A rep deactivated while holding `for share` waits; a call after it is refused `bad_rep` |

## 8. Done means

| Check | How |
|---|---|
| The `suppress()` and scrub locks (answers 9, 11) are built first | Their own commit, before part 1's |
| The tests of §7 pass; the existing intake tests pass unchanged | `make test` |
| `make e2e`, `make lint` | Pass |
| `0014` applies over production's data and changes no existing row | Restore the newest `mailengine_prod` backup into a scratch database (never `mailengine_prod` itself). Record which migrations it already has. Bring it to `0013` as `make migrate` does; that is the baseline. Apply `0014` alone. For every user table (not yoyo's `_yoyo_*`), compare the baseline with the result: row count, and an `md5` over its rows ordered by `t::text`. Every pair matches. |

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
| 12 | ~~§4.2 row 4 refuses every sold business the rep does not hold (part of 9.1, early)~~ | **Answered 2026-09-29:** keep row 4 until part 4 designs 9.1. Offered "Keep until part 4" or "Allow any rep". |
| 13 | ~~Two changes to the SQL~~ | **Answered 2026-09-29:** both — `btrim(confirmation) <> ''`, and the two indexes nothing in part 1 reads are dropped (§10). Offered "Both", "btrim only", or "Neither". |

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
| 9.13, a rep's own contact kept out of batches | Stays open for part 4; add that "whose it is" is the primary intake row (answer 1) |
| 3.2 | Add the four choices (answer 2) |
| §4, DNC | Add: a number with "don't call me again" is refused at intake (answer 3) |
| §3, Intake | Add: a rep re-adding their own contact from the house takes it back (answer 7); a claim takes an NMC contact in any stage (answer 8) |
| 9.1 | Stays open for part 4; add that door B refuses every sold business the rep does not hold until then (answer 12) |
