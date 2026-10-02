# contact-engine Upgrade — Part 5a: The call record

**Later parts changed this one,** and their documents are the current word: part 5b has
`record_outcome` on a call and `resolve_received` lock the contact first, then their row,
and write the rule's state; part 5c adds the Signed up's partner lock and seller check.
**Status:** APPROVED by the operator, 2026-09-30, at revision 5 (offered "Approve now",
"One more review", or "Read it first"; chose approve now). **BUILT 2026-09-30:** under
an approved build plan and an approved test gate: `0017.call-record.sql`,
`service/calls.py`, `jobs/calls_admin_cli.py`, and the optional `detail` on
`ValidationError`; gate `tests/acceptance/test_call_record.py`. Every §8 mutation failed
the gate; where two layers guard the same thing (the outcome check and the update's
condition; the open-call check and the unique index), each is caught once both are
removed. Part 5 was
cut in three (answer 1): 5a records calls, outcomes, memos and calls received — facts
only; 5b is the rule over them; 5c is the sale and the 90 days. History: Revisions 1 to
3 did not pass their reviews. Most of their blocking findings came from one place: a Do
not call *outcome* that also called part 2's report — the order of the two, a block lost
when 5a refused the outcome, a block landing on the wrong contact. Answer 2 called Do
not call "part 2's report", and decision 8.7 lists "don't call me again" as its own item,
apart from an outcome. Revision 4 takes that literally: **Do not call is not one of 5a's
outcomes; the rep sends part 2's report as it stands**, and 5a never touches a block.
Revisions 1 to 3's other findings stay fixed: the house cannot act as a rep; an outcome
is set once, under a lock; the call keeps the check it relied on; `happened` is computed
by the database; the table's checks forbid illegal rows. Revision 4 **passed** its review
(no blocking finding); it raised two questions for the operator, answered 3 and 4.
Revision 5 applies the answers and the minor findings.
**Part of:** [the upgrade](00-overview.md). Decisions are in the decision record,
`nvermisscall/docs/active/sales-partner-dialer-decisions.md`, named here by number
("decision 7.8"); sections of this document are named "§4.1".
**Checked against:** the `contact-engine` branch at `fd63cf0` (parts 0 to 4 built). A
statement about the code carries its file and line.

---

## 1. Its job

Record every call a rep opens, with what was known when it opened and its outcome;
record memos and calls received; let an admin clear a call left without an outcome; let
a rep undo their own Signed up or Wrong number within 24 hours. It decides nothing about
*when* a contact may be called again — that is 5b.

| Decision | What it asks | Here |
|---|---|---|
| 1.3 | contact-engine holds memos and call history | §4.2–§4.5 |
| 5.2 | No zone known: the rep says where the business is before the first call. No skip. | §4.2: opening a call is refused with no zone |
| 5.4 | Outside the window is a warning; the rep confirms, and the confirmation is recorded | §4.2 |
| 7.6 | The server's clock times every call | §4.2: `at` from the outermost layer, the server's |
| 7.8 | The server works out whether a call happened from how the outcome was recorded; the rep is never asked | §4.1 (answer 2), §4.8's `happened` |
| 7.9 | A call with no outcome is cleared by an admin; nothing closes on a timer | §4.6 |
| 7.10 | A rep can undo their own Signed up or Wrong number within 24 hours, with a written reason | §4.7 |
| 8.3 | Calls received: every incoming call from a known contact is listed; the rep picks spoke, missed and call back, or dismiss | §4.5 |
| 8.8 | Calls are kept with the check at the time and any calling-hours confirmation; nothing is deleted automatically | §4.2, §4.8 |

## 2. Its edges

| 5a does | 5a does not — who does |
|---|---|
| Open a call: a rep who holds it; its DNC status is clear (part 2); a zone is known and the hours confirmed if outside (part 3) | Refuse a call because it is not due, the sequence ended, it is resting, or it carries a Wrong number or Signed up (7.2, 7.11) — 5b, which adds its checks to opening a call |
| Record an outcome, a memo, a call received and its resolution | Count calls and voicemails, set due dates, move a contact between lists (7.1–7.5, 7.11) — 5b, reading `happened` |
| Record Signed up and Wrong number, and their undo | What a sale does to holding (6.5, 9.1–9.3, including a former holder's Signed up); replacing a wrong number (9.14) — 5c |
| | "Don't call me again": part 2's `report_do_not_call`, sent by the rep as its own request (8.7), unchanged. The call it happened on gets an ordinary outcome, Spoke as a rule |
| | Remember a request so a retry returns its first answer (7.7), hold unsent items (8.7), expose any of it — part 6 |

## 3. What exists, checked

| Fact | Where |
|---|---|
| Nothing records a call by a rep. The mail-engine era's human writes are `record_note` (`note.*` events), `record_outcome` in `service/contacts.py` (only `contact.lost`), and `set_next_action` | `service/ingestion.py:118-136`; `service/contacts.py:538-564` |
| Part 2's `dnc_status(contact_id, at)` gives one of `seed`, `do_not_call`, `no_phone`, `not_covered`, `not_checked`, `on_dnc_file`, `check_too_old`, `clear`. Part 2's `report_do_not_call` records a rep's "don't call me again" for any rep who holds or once held the contact | `service/dnc.py:95-144`, `:147-176`; `02-dnc-filtering.md` §4.5 |
| A contact's check is `dnc_checked_at` and, for the daily scrub, `dnc_snapshot_id` — the DNC file it was checked against | `db/migrations/0013.partner-dnc-snapshots.sql:99`; `jobs/dnc_refresh.py:138-140` |
| Part 3's `calling_hours(contact_id, at)` gives the zones, who set them, the local times, and `inside` (`None` with no zone known) | `service/zones.py:44-74` |
| `dnc_status` and `calling_hours` each open their own connection and take no lock | `service/dnc.py:98`; `service/zones.py:46` |
| Holding is `contacts.owner_id`; the house is `HOUSE_PARTNER_ID`, itself a `partners` row, and holds every contact nobody else does. Parts 2, 3 and 4 refuse the house as a rep (`bad_rep`), each at its own point in its order | `db/migrations/0009.partner-custody.sql:61`; `config/params.py:15`; `service/dnc.py:163`; `service/zones.py:101`; `service/assignment.py:486` |
| A refusal is `ValidationError(code, message)`, with no other field | `domain/errors.py:6-9` |
| The clock rule (9.15): new code takes `at`, timezone-aware | `01-intake.md` §4.6 |
| The event taxonomy is closed; its `call.*` types are the NeverMissCall-era inbound feed, not a rep's call | `domain/taxonomy.py:5-34` |

## 4. The design

The verbs live in `service/calls.py`. Every rep verb refuses `bad_time` (`at` has no
time zone) first and `bad_rep` (the house, or not a partner) second, before reading
anything else. **A refusal may carry data:** `ValidationError` gains an optional
`detail: dict`, empty by default — every existing raise is unchanged. 5a uses it for
`call_open` (`call_id`), `not_callable` (`status`) and `outside_hours` (`local`, zone to
local time).

### 4.1 Outcomes (answer 2)

| Outcome | Needs a call | From the card, with no call |
|---|---|---|
| No answer | yes | — |
| Left voicemail | yes | — |
| Owner unavailable | yes | — |
| Busy | yes | — |
| Call not placed | yes | — |
| Spoke | — | allowed (spoke in person, or on a call received) |
| Follow up | — | allowed |
| Not interested | — | allowed |
| Wrong number | — | allowed |
| Signed up | — | allowed |

Do not call is part 2's report (answers 2 and 3; decision 8.7), not a row here: when a
customer says "don't call me again" on a call, the rep sends part 2's report and records
the call as Spoke.

**Whether a call happened (7.8):** an outcome recorded on a call the rep opened is a call,
except Call not placed; an outcome recorded from the card is not; a cleared call is not.
It is the table's `happened` column (§4.8), computed by the database from how the row was
written. The rep is never asked; 5b counts `happened`.

### 4.2 Opening a call

`open_call(rep, contact_id, at, confirm_outside_hours=False)`. After `bad_time` and
`bad_rep`, it locks the contact `for update`, so a "don't call me again" that part 2
records (it locks the contact first), a suppression, a DNC scrub, or an event naming the
contact either lands before and is seen, or waits for the call. Then it reads part 2's
status and part 3's hours through their own functions — their own connections, after
the lock, so they see what committed before it. A no-op hook, `_after_lock(cur)`, runs
right after each verb's lock in this module, for the lock tests. Refused, writing
nothing, in this order:

| Code | When |
|---|---|
| `bad_time`, `bad_rep` | as above |
| `no_contact` | no such contact |
| `call_open` with `call_id` | `rep` has an open call (§4.8) on this contact — whether or not `rep` still holds it — so a rep whose answer was lost can record its outcome |
| `not_yours` | the contact's holder is not `rep` |
| `call_open` | another rep's call is open on the contact (reached only by its holder after a change of holder); no id |
| `not_callable` with `status` | part 2's status is anything but `clear` |
| `no_zone` | part 3 knows no zone (5.2): the rep sets it first (part 3 §4.5) |
| `outside_hours` with `local` | part 3's `inside` is `False` and `confirm_outside_hours` is not set (5.4) |

Otherwise it writes the call and returns its id and the number to dial. The call keeps
**the check it relied on** (8.8): the contact's `dnc_checked_at` and `dnc_snapshot_id`
read under the lock; the zones and `inside`; and `outside_confirmed`, true only when the
hours were outside and the rep confirmed — a confirmation sent while inside is not
recorded as one. A rep may open a call on another contact while one is open; only that
contact waits.

### 4.3 Recording an outcome

`record_outcome(rep, contact_id, outcome, at, *, call_id=None, memo=None)`. After
`bad_time` and `bad_rep`: `bad_outcome` (not in §4.1, or a call outcome without a call),
`no_text` (a memo given blank), `no_contact`, and then:

- **On a call** (`call_id` given): the call row is locked `for update`; it must be
  `rep`'s, on this contact, open, and opened no later than `at` — else `no_call`. The
  update also requires the call still open, so two outcomes sent at once (8.7's queued
  send and a second tap) cannot both land: the second is `no_call`. A former holder may
  record the outcome of their own open call.
- **From the card** (no `call_id`): the contact is locked `for update`; if `rep` has an
  open call on it, `call_open` with its id — the outcome belongs on the call; its holder
  must be `rep` (`not_yours`); it writes an outcome row with no call.

A memo given with an outcome is stored as a memo (§4.4) pointing at the outcome row.

### 4.4 Memos

`add_memo(rep, contact_id, text, at)`: the contact is locked `for update`; its holder must
be `rep`; the text is not blank once stripped. Refused: `bad_time`, `bad_rep`,
`no_contact`, `not_yours`, `no_text`. Memos are never edited or deleted.

### 4.5 Calls received (8.3)

`receive_call(rep, phone, at)`: an incoming call to the rep's phone from a **known
contact** is listed — answered or not. Known means the rep holds it now or held it before
(answer 4): the same rule as part 2's report — the contact's holder is `rep`, or a
`contact.assigned` event gave it to `rep`, or `rep` has an `intake_rep` row on it. So a
business calling back after a 90-day return is not lost, and listing it shows the rep
nothing they did not already have. Refused: `bad_time`, `bad_rep`, `invalid_phone` (not a
phone), `not_yours` (no contact carries the number, or the rep never held the one that
does — so a rep learns nothing about contacts they never held). It takes no lock: a call
received while the contact changes holder is listed for whichever rule held at the read.

`resolve_received(rep, received_id, resolution, at)`, resolution one of `spoke`,
`call_back`, `dismiss`: the row is locked `for update`; it must be `rep`'s and not yet
resolved, with `at` no earlier than `received_at`. Refused: `bad_time` (both cases),
`bad_rep`, `bad_resolution`, `no_received` (no such row, or another rep's),
`already_resolved`. What each resolution does to the lists is 5b's.

### 4.6 An admin clears a call (7.9)

`clear_call(call_id, actor, reason, at)`: the call row is locked `for update`; an open
call is closed as cleared, with the actor, the reason and `at`, no earlier than
`opened_at`. It is not a call that happened and carries no outcome. Nothing closes on a
timer. Refused: `bad_time` (no zone, or before `opened_at`), `bad_actor` (blank),
`no_reason`, `no_call`, `not_open` (it has an outcome or is already cleared).
`jobs/calls_admin_cli.py` lists the open calls, oldest first, and clears one.

### 4.7 Undo Signed up or Wrong number (7.10)

`undo_outcome(rep, outcome_id, reason, at)`: the row is locked `for update`; it must be
`rep`'s own Signed up or Wrong number, recorded no more than 24 hours before `at` (24
hours exactly is allowed) and no later than `at`, not already undone; the reason is not
blank. It marks the outcome undone, with the reason and `at`; the row stays. Refused:
`bad_time` (also when the outcome was recorded after `at`), `bad_rep`, `no_reason`,
`no_outcome` (no such row, or another rep's — it looks as if it does not exist),
`not_undoable` (an outcome other than Signed up or Wrong number), `too_late`,
`already_undone`.

### 4.8 The record

Three tables. A row is closed once by a later fact and otherwise never changes:

| Table | Holds | Written after insert only by |
|---|---|---|
| `calls` | one row per call opened, and one per outcome from the card (no `opened_at`): rep, contact, phone, `opened_at`, the contact's `dnc_checked_at` and `dnc_snapshot_id`, zones, `inside`, `outside_confirmed`; `outcome`, `outcome_at`; `cleared_*`; `undone_*`; and `happened`, generated | `record_outcome` (the outcome, once), `clear_call`, `undo_outcome` |
| `memos` | rep, contact, text, `at`, the outcome row it came with, if any | nothing |
| `calls_received` | rep, contact, phone, `received_at`; `resolution`, `resolved_at` | `resolve_received` (once) |

A call is **open** when it has `opened_at`, no outcome, and is not cleared. At most one
open call per contact (a partial unique index). The checks in §10 forbid the illegal
combinations listed in §7's table test. Nothing is deleted (8.8).

## 5. Parts 1 to 4

`domain/errors.py`'s `ValidationError` gains the optional `detail` (§4); nothing else in
parts 1 to 4 changes. 5a reads part 2's status and part 3's hours.

## 6. Gaps and limits

| Gap | Handling |
|---|---|
| A contact that changes holder with a call open | The call stays the first rep's; they can record its outcome; the new holder's `open_call` waits for it (`call_open`), or an admin clears it. A former holder's Signed up touches 9.3 — 5c |
| Outcomes other than Signed up and Wrong number cannot be corrected | Not decided (7.10 names only those two); "correct the last outcome" is drafted in `00-interface.md` and not built |
| A call on which the customer said "don't call me again" | The rep records Spoke and sends part 2's report; two requests, as 8.7 lists them |
| A block from an unmatched event carrying only a phone does not touch the contact row, so it can land between `open_call`'s status read and its commit | As part 2 accepted for its readers (its §6): a window of milliseconds; the call records the check it relied on |
| A call received from a contact the rep held once is listed (answer 4); resolving it changes nothing on a contact the rep no longer holds | 5b reads a resolution only for the holder |
| The table is named `calls` but also holds outcomes from the card | `happened` says which rows are calls |
| `calls.phone_e164` and `memos.call_id` are kept consistent by the verbs only (the phone is the contact's, the memo's call is its own contact's) | The verbs write them; no other writer exists |
| `service/calls.record_outcome` shares its name with the mail-engine era's `service/contacts.record_outcome` | Different modules; the old one is left |
| A wrong-number replacement (9.14, 5c) can make the dialled phone differ from the contact's later phone | 5c's |

## 7. Tests, written first

`tests/acceptance/test_call_record.py`, the gate:

| Test | Pins |
|---|---|
| Opening | a held, clear, zoned, inside-hours contact **linked to a DNC file** opens; the call records the phone, `opened_at = at`, the contact's `dnc_checked_at` and `dnc_snapshot_id`, the zones, `inside` |
| Refusals, in order | each of §4.2's codes, writing nothing; `not_callable` for each non-clear status, with `detail["status"]`; `bad_rep` for the house and for an unknown partner, before `no_contact` |
| No zone | `no_zone`; after the rep sets the zone (part 3), it opens |
| Outside hours | refused with `detail["local"]`; with the confirmation, opened and `outside_confirmed`; the confirmation sent while inside → opened, `outside_confirmed` false |
| One open call per contact | a second open by the same rep → `call_open` with `detail["call_id"]`; after the contact changes holder: the former holder → `call_open` with the id, and **records the call's outcome**; the new holder → `call_open` without an id; a rep who neither holds it nor has a call → `not_yours`; another contact → opens |
| A block landing | a "don't call me again" holding the contact through part 2's `dnc._after_lock` while `open_call` waits on it, then committing → `not_callable` |
| Outcomes on a call | each of §4.1's call outcomes; `happened` true for each but Call not placed; an outcome on another rep's call, on a cleared call, on the rep's own call on **another contact**, a second one, or with `at` before `opened_at` → `no_call`; an unknown outcome and `do_not_call` → `bad_outcome` |
| Two outcomes at once | the first holds the call row (`_after_lock`); the second, waiting, → `no_call`; the first outcome stands |
| Outcomes from the card | the allowed ones write a row with `happened` false; No answer from the card → `bad_outcome`; not the holder → `not_yours`; with the rep's own call open on the contact → `call_open` with its id |
| Memos | stored with and without an outcome; blank → `no_text`, alone and with an outcome; not the holder → `not_yours` |
| Calls received | a held contact's number is listed; **a contact the rep held once (returned by expiry) is listed**; a contact the rep never held and an unknown number → `not_yours`; not a phone → `invalid_phone`; a resolution outside the three → `bad_resolution`; each resolution; a second → `already_resolved`; no such row, and another rep's row → `no_received`; `at` before `received_at` → `bad_time` |
| Clear | an open call cleared with the actor and reason, `happened` false; a call with an outcome → `not_open`; a cleared one → `not_open`; a blank actor → `bad_actor`; no reason → `no_reason`; no such call → `no_call`; `at` before `opened_at` → `bad_time`; then the contact opens again |
| Undo | Signed up and Wrong number undone at 24 hours exactly; at 24 hours and one second → `too_late`; another rep's, or no such row → `no_outcome`; No answer → `not_undoable`; twice → `already_undone`; no reason → `no_reason`; recorded after `at` → `bad_time` |
| `bad_rep` everywhere | the house and an unknown partner → `bad_rep` in `record_outcome`, `add_memo`, `receive_call`, `resolve_received`, `undo_outcome` |
| The table's checks | direct inserts, each refused by the database: an undone row with no outcome; an undone No answer; `undone_at` before `outcome_at`; a card row with a call outcome; a card row with a phone, zones, `inside`, `dnc_checked_at`, a snapshot, or `outside_confirmed`; a row with neither `opened_at` nor an outcome; an opened row with no `dnc_checked_at`; an opened row with no zones; an opened row outside hours unconfirmed; a confirmed row inside hours; a cleared row without a reason, from the card, or with an outcome; an outcome dated before its call; a received call resolved before it came |
| The clock | a naive `at` → `bad_time` in every verb |
| Existing refusals | `ValidationError(code, message)` still works with `detail` empty |

## 8. Done means

The gate green; `make test`, `make e2e`, `make lint` clean; mutation checks each failing a
test — skip the holder check; let the house call; allow a non-clear status; allow no
zone; open outside hours without the confirmation; record a confirmation while inside;
allow two open calls on a contact; let a second outcome overwrite the first; make
`happened` true for Call not placed; allow a call outcome from the card; let an undo pass
24 hours; clear a call that has an outcome; allow a card outcome while the rep's call is
open; check `not_yours` before the rep's own `call_open`. Migration `0017` applied to
`mailengine_dev`.

## 9. For the operator

| # | Question | Answer |
|---|---|---|
| 1 | How should part 5 be cut? | **Answered 2026-09-30: three parts** — 5a the call record, 5b the rule, 5c the sale and the 90 days. Offered that (recommended), "Two parts", or "Keep part 5 whole". |
| 2 | Which outcomes can a rep record? | **Answered 2026-09-30: V1 Minimum's set** (§4.1) with Signed up, "plus Do not call, which is part 2's report"; a call happened when an outcome is recorded on a call the rep opened, except Call not placed. Offered that (recommended), "Smaller set", or "I'll give the list". |
| 3 | When a customer says "don't call me again" during a call, is Do not call a call outcome? | **Answered 2026-09-30: no** — the rep sends part 2's report and records the call as Spoke. Offered that (recommended) or "Yes: an outcome too". |
| 4 | Which contacts count as known for calls received (8.3)? | **Answered 2026-09-30: held now or once** — as part 2's report. Offered that (recommended) or "Held now only". |

## 10. The migration, `0017.call-record.sql`

```sql
create table calls (
  id                 uuid primary key default gen_random_uuid(),
  contact_id         uuid not null references contacts(id),
  rep_id             uuid not null references partners(id),
  phone_e164         text check (phone_e164 ~ '^\+1[0-9]{10}$'),
  opened_at          timestamptz,
  dnc_checked_at     timestamptz,
  dnc_snapshot_id    uuid references dnc_snapshots(id),
  zones              text[],
  inside             boolean,
  outside_confirmed  boolean not null default false,
  outcome            text check (outcome in ('no_answer', 'left_voicemail',
                       'owner_unavailable', 'busy', 'call_not_placed', 'spoke',
                       'follow_up', 'not_interested', 'wrong_number', 'signed_up')),
  outcome_at         timestamptz,
  cleared_by         text,
  cleared_reason     text,
  cleared_at         timestamptz,
  undone_reason      text,
  undone_at          timestamptz,
  happened           boolean generated always as (
                       opened_at is not null and outcome is not null
                       and outcome <> 'call_not_placed') stored,
  -- a call opened, or an outcome from the card
  check ((opened_at is null) = (phone_e164 is null)),
  check (opened_at is not null or outcome is not null),
  check (opened_at is not null or outcome not in ('no_answer', 'left_voicemail',
         'owner_unavailable', 'busy', 'call_not_placed')),
  -- an opened call relied on a check, and on the hours or a confirmation
  check (opened_at is null or (dnc_checked_at is not null and inside is not null
         and zones is not null and cardinality(zones) > 0
         and (inside or outside_confirmed))),
  check (opened_at is not null or (dnc_checked_at is null and dnc_snapshot_id is null
         and zones is null and inside is null and not outside_confirmed)),
  check (not outside_confirmed or inside is false),
  check ((outcome is null) = (outcome_at is null)),
  check (outcome_at is null or opened_at is null or outcome_at >= opened_at),
  check ((cleared_at is null) = (cleared_by is null)),
  check ((cleared_at is null) = (cleared_reason is null)),
  check (cleared_at is null or (btrim(cleared_reason) <> '' and btrim(cleared_by) <> ''
         and outcome is null and opened_at is not null and cleared_at >= opened_at)),
  check ((undone_at is null) = (undone_reason is null)),
  check (undone_at is null or (btrim(undone_reason) <> ''
         and outcome is not null and outcome in ('signed_up', 'wrong_number')
         and undone_at >= outcome_at))
);
create unique index calls_one_open_per_contact on calls (contact_id)
  where opened_at is not null and outcome is null and cleared_at is null;

create table memos (
  id          uuid primary key default gen_random_uuid(),
  contact_id  uuid not null references contacts(id),
  rep_id      uuid not null references partners(id),
  call_id     uuid references calls(id),
  text        text not null check (btrim(text) <> ''),
  at          timestamptz not null
);
create index memos_contact_idx on memos (contact_id, at);

create table calls_received (
  id           uuid primary key default gen_random_uuid(),
  contact_id   uuid not null references contacts(id),
  rep_id       uuid not null references partners(id),
  phone_e164   text not null check (phone_e164 ~ '^\+1[0-9]{10}$'),
  received_at  timestamptz not null,
  resolution   text check (resolution in ('spoke', 'call_back', 'dismiss')),
  resolved_at  timestamptz,
  check ((resolution is null) = (resolved_at is null)),
  check (resolved_at is null or resolved_at >= received_at)
);
create index calls_received_rep_idx on calls_received (rep_id, received_at);

grant select on calls, memos, calls_received to me_user_ro;
```

Additive. No cascade: a contact with calls is never hard-deleted (the only hard delete is
the one-time grain swap, `jobs/migrate_grain.py:442`).

## 11. Proposed changes to the decision record and documents

| Item | Proposal |
|---|---|
| 7.8 | Add: an outcome recorded on a call the rep opened is a call, except Call not placed; one recorded from the card is not (answer 2) |
| New, §7 | The outcomes are §4.1's; "don't call me again" is part 2's report, sent as its own request, and the call is recorded as Spoke (answers 2, 3; 8.7) |
| 8.3 | Add: a known contact is one the rep holds or once held (answer 4) |
| `00-overview.md` | Part 5 is three parts: 5a the call record, 5b the rule, 5c the sale and the 90 days (answer 1) |

## 12. Safety properties

Each revision is checked against these before review.

1. No call opens on a contact whose DNC status is not `clear`, on a contact the rep does
   not hold, or for the house.
2. No call opens with no zone known, or outside hours without the rep's recorded
   confirmation; a confirmation is recorded only when the hours were outside.
3. A call records the check it relied on (`dnc_checked_at`, `dnc_snapshot_id`), the zones,
   `inside`, and the confirmation.
4. A contact has at most one open call.
5. Whether a call happened is computed from how the row was written, never asked.
6. Nothing in the record is deleted; an outcome is set once, never overwritten, and only
   undone (Signed up, Wrong number, 24 hours) or never set (cleared).
7. 5a never writes or removes a "don't call me again"; part 2's report is the only way a
   rep records one, unchanged.
