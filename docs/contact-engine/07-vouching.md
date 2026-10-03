# contact-engine Upgrade — Part 7: Vouching, and callable-only lists

**Status:** APPROVED by the operator, 2026-10-02, at revision 2, with §5's frozen-test
changes, the migration (§10) and answer 1's scrub change (offered "Approve now", "One
more review", or "Read it first"; chose approve now). **BUILT 2026-10-02** under the
approved gate test: `0022.vouches.sql`, `service/vouch.py`; `_check_open` and `open_call`
in `service/calls.py`; door B's vouches in `service/rep_intake.py`; the scrub's skip in
`jobs/dnc_refresh.py`; the card, lists and search in `service/reads.py`; two routes in
`web/api.py`; §5's two frozen-test changes. Gate `tests/acceptance/test_vouching.py`
(red for the right reasons — the verbs missing, door B writing no vouch, the scrub
taking the contact, no route; two tests' setup corrected while greening it, no assertion
changed: a batch's freshness is judged by the real clock, so those contacts are checked
now and then set to their state at `AT`). `make test` 852 passed, `make e2e` passed,
lint clean, `make smoke` passed against the restarted dev API. 18 of §8's 19 mutations
fail the gate; "pass `no_phone`" cannot change behaviour — a contact with no phone fails
§4.3's phone condition, and `vouches.phone_e164` is not null — so it is equivalent, and
its test pins the outcome. `0022` applied to `mailengine_dev`. §9: answers 1–4 given. Revision 1 **passed**
its fresh review (no blocking finding); its nine minor findings are applied here: the
order of a rep's vouches (`seq`); a test for `seed` and `no_phone`; §6's day-90 claim
corrected; search's own shape and its `at`; the bodies' optional fields; buildable
"whose vouch counts" tests; §3's lines; door B's confirmation and the notice; fixtures
held through `set_owner`. Gate test `tests/acceptance/test_vouching.py` approved
2026-10-02, with §10's change (no foreign key on `vouches.rep_id`). Next: build.
**Asked for by:** the dialer, in
`nvermisscall/docs/active/contact-engine/upgrade-vouch-and-callable-lists.md` (named here
"the request"; its rules V1–V7, L1, L2). Where the request and this design differ, this
design wins once the operator approves it.
**Part of:** [the upgrade](00-overview.md). Decisions are in the decision record,
`nvermisscall/docs/active/sales-partner-dialer-decisions.md`, named here by number
("decision 4.12"); sections of this document are named "§4.1".
**Checked against:** the `contact-engine` branch at `cd19846` (parts 0 to 6 built). A
statement about the code carries its file and line.
**Tier:** 🔴 throughout — it changes the gate on a call (part 2's status read in
`_check_open`), the nightly DNC scrub, and adds a migration.

---

## 1. Its job

Let a rep call a business they can vouch for even when its DNC check is not clear, and
list only what the rep may act on.

| Decision | What it asks | Here |
|---|---|---|
| 4.12 | A rep vouches for a number they hold: met in person, or they contacted me. A vouched number may be called when its check is not clear; never past a "don't call me again". Adding a number with either reason vouches for it. To go past counsel before production (9.16). | §4.1–§4.5 |
| 8.14 | A number that can't be called (not clear, not vouched) is not listed | §4.6 |
| 4.3 | "Don't call me again" blocks the number for every rep | Unchanged; a vouch never passes it (§4.2) |
| 1.6 | The server decides | The app reads `may_call` and the lists; it decides nothing |

## 2. Its edges

| Part 7 does | Part 7 does not — who does |
|---|---|
| Records vouches; lets a counting vouch pass part 2's DNC status on a call | Change any contact's `dnc_status`, the 31 days, the checks, or the files — part 2 |
| Filters `GET /v1/me/lists`; adds fields to the card, lists and search | Give out vouched contacts in batches — part 4's gate is unchanged |
| Changes the scrub's take-back for a vouched contact (§4.4, answer 1) | Change the export or its compliance predicates (`service/assignment.py`) — untouched |
| | The confirmation text the rep sees — the app and the website show it; contact-engine stores what was agreed to |

## 3. What exists, checked

| Fact | Where |
|---|---|
| `open_call` and `may_call` both go through `_check_open`; it refuses `not_callable` for any status but `clear`, after the holder and open-call checks and before the zone, the rule and the hours | `service/calls.py:82-132`; `service/rule.py:341-348` |
| The card's `may_call` is `_check_open` with no lock; its `dnc_status` is `dnc.dnc_status` | `service/reads.py:107-113` |
| `dnc_status` returns the first of `seed`, `do_not_call`, `no_phone`, `not_covered`/`not_checked`, `on_dnc_file`, `check_too_old`, `clear`; one contact per call | `service/dnc.py:95-144` |
| An opened call must carry `dnc_checked_at` — constraint `calls_check3` | `db/migrations/0017.call-record.sql:37-39`; `pg_constraint` in `mailengine_dev` |
| `open_call` stores the contact's `dnc_checked_at` and `dnc_snapshot_id` on the call | `service/calls.py:143-150` |
| `GET /v1/me/lists` returns every held contact with its 5b state; the filter-free `rule.rep_lists` is also read by part 5b's tests | `service/reads.py:182-209`; `service/rule.py:310-324`; `tests/acceptance/test_the_rule.py:556` |
| Search returns the rep's held contacts, at most 50, `{id, phone, business, contact_name}` | `service/reads.py:236-252` |
| Door B: `how_obtained` is one of four; rows end `added`, `claimed`, `already_yours`, or a refusal; refused rows write nothing; `already_yours` writes no intake row | `service/rep_intake.py:24-26`, `:118-157`, `:226-257` |
| Door B answers `do_not_call` for a blocked number; it does not read `dnc_registry` | `service/rep_intake.py:92-99`, `:118-124` |
| Door B refuses for 90 days the rep a contact went back from by expiry; a return by `reclaim` starts no wait | `service/rep_intake.py:141-149`; part 4 §7 |
| A rep's Got a callback or Follow up contact is exempt from the 90-day return | `service/assignment.py:551-557` |
| Search takes no `at`; `_identities` is shared with known callers, whose keys a frozen test pins | `web/api.py:420-423`; `service/reads.py:212-216`, `:236-252`; `tests/acceptance/test_api.py:893` |
| **The nightly scrub takes every contact whose number it finds on the file from any rep — a rep's own included — to the house** (`contact.reclaimed`, reason `dnc_registry`) | `jobs/dnc_refresh.py:165-171`; accepted for a rep's own in part 1 §6 and part 4 §6 |
| The scrub rechecks a contact 21 days after its last check | `config/params.py:20`; `jobs/dnc_refresh.py:83-114` |
| `set_owner` is the one writer of the holder; every event carries `previous_owner_id` and `new_owner_id`, and returns its id | `service/custody.py:19-66` |
| A Signed up that moves a contact to the rep already holding it (when it has a batch pointer and is neither blocked nor on a DNC file) emits `contact.assigned` with `previous_owner_id` = `new_owner_id` = that rep | `service/sale.py:71-75`; `service/custody.py:46-58` |
| A refusal `not_yours` on a contact answers `404 no_contact` | `web/api.py:157-165`; `service/reads.py:31-43` |
| Frozen tests pin the card's fields and a list entry's exact shape | `tests/acceptance/test_api.py:736-741`, `:864-881` |

## 4. The design

### 4.1 A vouch (V1, V4, V6)

New verb `service/vouch.py: vouch(rep, contact_id, reason, confirmation, at) -> "vouched"`,
one transaction. Refusals, in order:

1. `bad_rep` — not a rep (as `rule._check_rep`).
2. Lock the contact `for update`; `no_contact`; `not_yours` unless the rep holds it now
   (the API answers both as `404 no_contact`).
3. `bad_reason` — `reason` not `met_in_person` or `they_contacted_me`.
4. `no_confirmation` — `confirmation` missing or blank once stripped.
5. `not_vouchable` — `dnc_status` is `do_not_call`, `no_phone` or `seed`
   (`detail.status`).

Then it appends one `vouches` row (§10): rep, contact, the contact's phone, reason, the
stripped confirmation, `source` `rep`, `at`, and **the custody mark** — the id of the
latest custody event on the contact (§4.3). A second vouch adds another row. A `clear`
contact can be vouched: the vouch matters once its check ages.

Route `POST /v1/contacts/{id}/vouch`, `{reason, confirmation}` — both `str | None =
None` in the body (not the stripped `Text` type), so a missing field reaches the verb
and answers its 409 rather than `400 bad_request` (`web/api.py:624-627`) — either key, `X-Rep`,
`Idempotency-Key` — a contact action like `/move` (`web/api.py:504-507`): `200
{"result": "vouched"}`, refusals `409` with their code.

### 4.2 What a vouch passes (V3, V5)

One function decides the DNC part of a call, in `service/vouch.py`:

```
dnc_basis(cur, rep, contact_id, status) -> Basis
  clear                                        -> callable, no vouch
  not_checked | not_covered | on_dnc_file |
  check_too_old, and a counting vouch (§4.3)   -> callable, under that vouch
  anything else                                -> refused not_callable (detail.status)
```

`_check_open` calls it where it now compares to `clear` (`service/calls.py:115-120`), so
`open_call`, `may_call` and the card's `may_call` all read it. Everything after it — the
zone, the rule (closed, limit, paused, not due), the hours and their confirmation — is
unchanged. `do_not_call`, `no_phone`, `seed` are never passed.

**The call records its basis.** `open_call` writes `vouch_id` (the counting vouch) and
`vouched_status` (the status it passed) on a call opened under a vouch; both null on a
clear call. `dnc_checked_at` stays what the contact had, which may be null under a
vouch; `calls_check3` is replaced so an opened call needs `dnc_checked_at` **or**
`vouch_id` (§10).

### 4.3 Whose vouch counts (V2)

A vouch counts for rep R on contact C when, read under C's lock or in the read's
snapshot:

1. R holds C now;
2. the vouch's phone is C's phone now; and
3. **nothing has taken C from R since the vouch:** no custody event on C with an id
   above the vouch's custody mark has `previous_owner_id` = R and `new_owner_id` ≠ R;
   and
4. it is not withdrawn (§4.4a).

The counting vouch is R's latest such row by `seq` (an identity column, as `dnc_log`'s;
`id` is random and `at` is handed in). By event id, never by clock (as part 5c's
answer 7). So a vouch dies when the contact leaves R by expiry, a reclaim, a
suppression or a DNC hit, and does **not** come back if R holds C again — R vouches
again. A sale's same-rep `contact.assigned` (§3) does not end it.

### 4.4 The nightly scrub and a vouched contact (answer 1)

Today a hit takes the contact from its rep the same night (§3). With that unchanged, a
vouch on `on_dnc_file` lasts at most until the next recheck (21 days), and a number a
rep met in person, added with `met_in_person`, and found on the file is taken from them
the first night it is checked. 4.12's "on the DNC file" would mostly not hold.

Answer 1: **the scrub leaves a contact with a rep whose vouch counts
(§4.3)**, checked under the contact's lock in `_apply`; it still stamps `dnc_registry`,
`dnc_checked_at`, the snapshot and the `contact.dnc_checked` event, as for every
contact. Every other held contact goes back as today. If the contact later leaves the
rep, the house holds a listed contact and part 4's gate refuses it (`dnc_registry`).

### 4.4a Withdrawing a vouch (answer 2)

New verb `withdraw(rep, contact_id, reason, at) -> "withdrawn"`, any time, by the rep
who vouched. Refusals, in order: `bad_rep`; the contact's lock, `no_contact`,
`not_yours` (the API: `404 no_contact`); `no_reason` — blank once stripped;
`not_vouched` — no counting vouch (§4.3). It appends one `vouch_withdrawals` row for
**each** of the rep's vouches on the contact that would otherwise count, with the
stripped reason and `at`. From then on none of them counts: the contact leaves the
lists and a call is refused `not_callable` unless the status is `clear`. A new vouch
afterwards counts again. A call already open stays open for its outcome; only opening
reads the vouch.

Route `POST /v1/contacts/{id}/vouch/withdraw`, `{reason: str | None = None}`, as §4.1's route: `200
{"result": "withdrawn"}`.

### 4.5 Adding a number (V7)

In `add_numbers`, after the holds: for each row whose result is `added`, `claimed` or
`already_yours` and whose `how_obtained` (row, else request) is `met_in_person` or
`they_contacted_me`, append a vouch with that reason, the call's stripped
confirmation, `source` `intake`, the same `at`, and the custody mark read after the
hold. Rows with `referral` or `public_or_research`, and refused rows, get none. The row
results are unchanged. Door B already refuses a blocked number (`do_not_call`), so V4
holds there.

The intake vouch stores door B's confirmation, which today need not carry answer 3's
notice. The dialer is asked (§11) to show answer 3's text when a rep adds a number with
either reason, so the stored confirmation is the vouch's own; contact-engine does not
check the text (answer 3).

### 4.6 The lists, the card, search (L1, L2)

- **`GET /v1/me/lists`** (`reads.lists`): a held contact is listed only when
  `dnc_basis` would pass it — `clear`, or a counting vouch with a passable status. Every
  list is filtered, Closed included. Each entry gains `whose` (`nmc`/`own`, as the card)
  and `vouched` (a counting vouch exists). `calls_received` unchanged.
  `rule.rep_lists` stays unfiltered (it is the rule's read, and 5b's tests pin it).
- **The card** gains `vouched`: `{"reason", "at"}` of the counting vouch, or `null`.
  `dnc_status` stays the true status; `may_call` follows §4.2.
- **`GET /v1/me/search`** is not filtered; each result gains `dnc_status` and `vouched`.
  `reads.search` gains `at` (the route passes it, as the other reads do) and builds its
  own shape; `_identities` and known callers are unchanged.

The status is read with `dnc.dnc_status`, one contact at a time, as the card does
today; part 2's query is not touched (§6).

### 4.7 Not built

`GET /v1/contacts/{id}/vouches` (the request's §3.2, "can wait"); an admin view of
vouches (the request's §4).

## 5. Earlier parts

- Part 5a: `_check_open` reads `dnc_basis`; `open_call` writes `vouch_id`,
  `vouched_status`; `calls_check3` replaced.
- Part 1 (door B): vouches for its two reasons (§4.5).
- Part 2: the scrub's take-back skips a vouched contact (§4.4, answer 1). `dnc_status`
  unchanged.
- Part 6a: one new route; fields added to the card, lists and search; the lists
  filtered.
- **Frozen tests that change — for the operator's approval with the design:**
  - `tests/acceptance/test_api.py:736-741` `CARD_FIELDS` gains `vouched`.
  - `tests/acceptance/test_api.py:874-877` (`test_lists`): the entry gains
    `"whose": "nmc", "vouched": False`.
  Every other assertion unchanged. No other frozen test holds a vouch, so none other
  sees a change; `make test` will say.

## 6. Gaps and limits

| Gap | Handling |
|---|---|
| Counsel has not seen vouching (4.12, 9.16). Our own memo reads a registry exemption as needing a **written** agreement, and "they contacted me" as the inquiry relationship, about 3 months (`nvermisscall/docs/counsel-memo-dnc-b2b.md` §2) | Answer 4: no expiry now; counsel sets any limit before production. Every vouch and every call under one is recorded, so the limit can be applied to the record |
| A vouch lets a rep call where NMC has no subscription (`not_covered`) or an old check | As 4.12 decides |
| A contact blocked by "don't call me again", with no phone, or a seed, no longer shows in any list — Closed included | L1 as written; search still finds it |
| The lists read `dnc_status` once per held contact | Measured at build on the smoke rep (250 contacts); a bulk read of part 2's status is a separate 🔴 change if needed |
| A vouch is not re-asked when the phone of a contact changes | Condition 2 of §4.3: it stops counting |
| A rep holding a vouched listed contact keeps it past every recheck (answer 1) | NMC's goes back at day 90 **unless** it is in Got a callback or Follow up (exempt, `service/assignment.py:551-557`); a rep's own never expires. So a vouched contact on the DNC file in Follow up, or the rep's own, stays with the rep until a reclaim, a block, or a withdrawal — for counsel to see (answer 4) |
| A number added through door B with either reason is vouched with door B's confirmation | §4.5: the dialer shows answer 3's text there |

## 7. Tests, written first

`tests/acceptance/test_vouching.py`, the gate:

| Test | Pins |
|---|---|
| A vouch is recorded | each reason → `vouched`; the row has rep, contact, phone, reason, stripped confirmation, `at`, source `rep`, the custody mark; a second vouch adds a row |
| Refusals | `referral`, `public_or_research`, missing → `bad_reason`; blank → `no_confirmation`; `do_not_call`, `no_phone`, `seed` → `not_vouchable` with the status; a contact the rep does not hold → `not_yours` (the API: `404 no_contact`, the same body); a replay → the stored answer |
| Passes | a vouched contact with each of `not_checked`, `not_covered`, `on_dnc_file`, `check_too_old` → `open_call` opens; `may_call` and the card's `may_call` say yes; the call has `vouch_id`, `vouched_status`, null `dnc_checked_at` when unchecked |
| Never passes | vouched, then blocked by "don't call me again" → `not_callable` `do_not_call`; a vouch row inserted by SQL on a seed the rep holds → `not_callable` `seed`; the same on a contact whose phone is then set null → `not_callable` `no_phone` |
| Everything else stands | vouched and outside hours → `outside_hours`; not due → `not_due`; paused, limit reached, closed → as before; no zone → `no_zone` |
| A clear call | carries no `vouch_id` |
| Whose vouch counts | A vouches; the contact goes back by expiry, B claims it through door B → B refused `not_callable`; B vouches → opens. A vouches; `reclaim` of A, then A claims it again through door B (`referral`; a reclaim starts no wait) → A refused until A vouches again. A's Signed up on a batch contact (same-rep `contact.assigned`) → A's vouch still counts. A's vouch, then the contact's phone changed by SQL (no verb writes it) → does not count. Two vouches with the same `at` → the counting one is the later `seq` |
| Withdrawal | a withdrawn vouch → `not_callable`, out of the lists, the card's `vouched` `null`; two counting rows → both withdrawn; a new vouch after → counts; blank reason → `no_reason`; nothing counting → `not_vouched`; another rep's contact → `not_yours`; a call open under it → its outcome still records |
| Door B | `met_in_person` and `they_contacted_me` rows `added`, `claimed`, `already_yours` → vouched, source `intake`; `referral` and `public_or_research` → not; `held`, `do_not_call`, `invalid_phone` rows → no vouch; the request-level `how_obtained` with no row value → vouched |
| The scrub | a vouched contact found on the file → stays with its rep, `dnc_registry` set, the event written; an unvouched one → the house, as today; a vouch that no longer counts → the house |
| Lists | a not-clear, not-vouched contact → in no list; vouched → back in its list; a blocked contact → in no list; search finds both; `whose` and `vouched` on every entry; search entries carry `dnc_status` and `vouched` |
| The card | `vouched` is the latest counting vouch, or `null`; `dnc_status` still `on_dnc_file` when vouched |
| The changed frozen tests | green with §5's changes |

New tests hold contacts through `set_owner` (batches, door B, `reclaim`), never by
setting `owner_id` in SQL, so every held contact has a custody mark.

## 8. Done means

The gate green; every other frozen test unchanged and green; `make test`, `make e2e`,
`make lint`, `make smoke` clean; migration `0022` applied to `mailengine_dev`. Mutation
checks each failing a test: pass `do_not_call` under a vouch; pass `no_phone` or `seed`;
let another rep's vouch count; count a withdrawn vouch; withdraw only the latest row; let a vouch survive a take-back; end a vouch on a
same-rep `contact.assigned`; ignore the phone condition; skip the vouch on an opened
call's record; vouch `referral` rows at door B; vouch refused door-B rows; leave a
non-callable contact in the lists; filter search; read the vouch in the lists but not in
`_check_open` (or the reverse); the scrub keeping an unvouched contact; the scrub returning a vouched one.

## 9. For the operator

| # | Question | Answer |
|---|---|---|
| 1 | The nightly scrub takes a contact on the DNC file from its rep. Does it still, when the rep has vouched for it? | **Answered 2026-10-02: the rep keeps it** (§4.4). Offered that (recommended) or "Taken back as today". |
| 2 | Can a rep withdraw a vouch? (request §7) | **Answered 2026-10-02: yes, any time** (§4.4a), with a written reason. Offered that (recommended), "No withdrawal", or "Within 24 hours only". |
| 3 | The confirmation wording (request §7) | **Answered 2026-10-02: the fact, then the DNC notice.** Met in person: "I met someone from this business in person, and they agreed to hear from me." They contacted me: "This business contacted me first and asked me to follow up." Both end: "I understand this lets me call a number that has not been cleared against the Do Not Call list, and that this confirmation is recorded with my name." Offered that (recommended), "Fact only", or "Leave it to the website". The app and the website show it; contact-engine stores the text sent and does not check it. |
| 4 | Does a vouch expire? (counsel's reading, §6) | **Answered 2026-10-02: no expiry; counsel sets it** before production, applied then to the recorded vouches. Offered that (recommended), "They-contacted-me: 3 months", or "Both expire at 3 months". |

The request's third open item — a Vouch action on the website's rep page — needs nothing
here: the route takes either key. It is the website's call.

## 10. The migration, `0022.vouches.sql`

```sql
create table vouches (
  id             uuid primary key default gen_random_uuid(),
  seq            bigint generated always as identity unique,
  contact_id     uuid not null references contacts(id),
  rep_id         uuid not null,
  phone_e164     text not null check (phone_e164 ~ '^\+1[0-9]{10}$'),
  reason         text not null check (reason in ('met_in_person', 'they_contacted_me')),
  confirmation   text not null check (btrim(confirmation) <> ''),
  source         text not null check (source in ('rep', 'intake')),
  custody_mark   bigint not null,
  at             timestamptz not null
);
create index vouches_contact_rep_idx on vouches (contact_id, rep_id, seq);

create table vouch_withdrawals (
  id        uuid primary key default gen_random_uuid(),
  vouch_id  uuid not null unique references vouches(id),
  reason    text not null check (btrim(reason) <> ''),
  at        timestamptz not null
);

alter table calls add column vouch_id uuid references vouches(id);
alter table calls add column vouched_status text check (vouched_status in
  ('not_checked', 'not_covered', 'on_dnc_file', 'check_too_old'));
alter table calls add check ((vouch_id is null) = (vouched_status is null));
alter table calls add check (vouch_id is null or opened_at is not null);
alter table calls drop constraint calls_check3;
alter table calls add check (opened_at is null or (
  (dnc_checked_at is not null or vouch_id is not null)
  and inside is not null and zones is not null and cardinality(zones) > 0
  and (inside or outside_confirmed)));

grant select on vouches, vouch_withdrawals to me_user_ro;
```

No foreign key on `rep_id` (approved with the gate test, 2026-10-02): partners are never
deleted in production, and frozen fixtures delete their reps at teardown after door B
has vouched (`tests/acceptance/test_rep_intake.py:64`, `:459-505`) — as 5c's
`web_seller` (05c §10).

Append-only: `service/vouch.py` is the only writer of both tables and only inserts (as
`dnc_log`); a vouch is withdrawn once (`unique`). Kept
per 8.8 with the calls (5 years). `custody_mark` is not null: a contact a rep holds has
at least the `contact.assigned` that gave it to them.

## 11. Proposed changes to the decision record and documents

| Item | Proposal |
|---|---|
| 4.12 | Add answers 1, 2 and 4; "counts only while that rep holds it, since they last got it" (§4.3) |
| 8.14 | Add: the filter covers every list, Closed included; search is not filtered |
| `PRD.md` §4 | "No calling past a DNC block … until the operator turns it on" — turned on by 4.12 |
| `nvermisscall/docs/active/contact-engine-api.md` | The new routes and fields, and answer 3's wording for the app and the website — including door B with either reason (§4.5) — after the build |

## 12. Safety properties

Each revision is checked against these before review.

1. No call opens on a `do_not_call`, `no_phone` or `seed` contact, vouched or not.
2. No call opens on a not-clear contact without a vouch that counts for the calling rep
   at that moment, and the call records which.
3. A vouch counts only for its rep, while they hold the contact, since they last got it,
   and until it is withdrawn.
4. A list never holds a contact `_check_open` would refuse for its DNC status.
5. Nothing in part 4's gate or the export changes: a vouch never puts a contact in a
   batch or on a sheet.
