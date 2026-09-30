# contact-engine Upgrade — Part 2: DNC filtering

**Status:** DRAFT, revision 13, 2026-09-30. Revision 8 **passed** its review; the operator
then replaced the rep's 24-hour undo with an admin lift (answer 8). Revision 9's lift —
over every form of block, by an event-id mark — did not pass (a later-attached opt-out
could be lifted unseen; a concurrent request could be erased; lifts deadlocked). The
operator narrowed the lift to requests recorded through part 2's own verbs (answer 9).
Revision 10, rewritten around that, did not pass (an opt-out carrying a phone stopped
blocking that phone once attached to another contact). Revision 11 did not pass (a lift
could erase a live request the admin never saw): a lift now names the requests it lifts.
The check's 31 days go back to exactly what answer 3 kept. Revision 12 did not pass (no
test could tell a by-id tombstone delete from a phone-wide one). This revision adds that
test, makes door B read the shared voice block, and applies the minor findings. Not yet re-reviewed, not approved. Nothing is built.
**Part of:** [the upgrade](00-overview.md). Decisions are in the decision record,
`nvermisscall/docs/active/sales-partner-dialer-decisions.md`, named here by number
("decision 4.1"); sections of this document are named "§4.1".
**Checked against:** the `contact-engine` branch at `070b5a4` (parts 0 and 1 built; the
code is unchanged since `c3179da`). A statement about the code carries its file and line.

---

## 1. Its job

Say whether a number is clean to call, and why not when it is not; make the assignment
gate and the export refuse what that says; take a "don't call me again"; and let an
admin lift one recorded by part 2's own verbs.

| Decision | What it asks |
|---|---|
| 4.1 | Every number is checked, NMC's and a rep's alike. Unchecked, failed, or not covered: no call. |
| 4.2 | A check is good through day 31; day 32 is stale. |
| 4.3 | "Don't call me again" blocks the number for every rep at once. |
| 4.4 | *As decided 09-28:* the reporting rep can undo it within 24 hours. *Replaced 2026-09-30 by answers 8 and 9:* no rep undo; an admin lifts requests recorded by part 2's verbs, by hand, with a written reason. |
| 4.5 | DNC files stay files; their upload is unchanged. |
| 4.6 | The rep is told an area code is not covered only after the check. |

Open items it settles: 9.8, 9.9, 9.10, 9.11, and the DNC half of 9.16.

## 2. Its edges

| Part 2 does | Part 2 does not — who does |
|---|---|
| The DNC status of a contact, with its reason (§4.1) | Decide "may I call now": that adds calling hours (part 3) and the sequence (part 5). Part 5 asks part 2's status. |
| Make the assignment gate and the export refuse what the status refuses (§4.3) | Put the contact in a Closed list — part 5 (decisions 7.5, 7.11) |
| Take a rep's "don't call me again" (§4.5) and an admin's (§4.6) | Remember a request for 90 days so a retry returns its first answer (decision 7.7) — part 6 |
| Let an admin lift requests part 2 recorded (§4.7) | Expose any of it from outside, or raise an alert — part 6 and the website (decision 1.7) |
| Record each completed daily scrub (§4.4) | Download or upload DNC files — unchanged (decision 4.5) |
| | Change who holds a contact — part 4. No verb of part 2 moves custody |

## 3. What exists, checked

| Fact | Where |
|---|---|
| The daily scrub checks contacts in subscribed area codes never checked or checked over 21 days ago, rep-held first; a hit sets `dnc_registry` and takes the contact back to the house; a delisting clears it | `jobs/dnc_refresh.py:80-96`, `:106-169`; `config/params.py:19` |
| The daily run is pull → scrub → nightly; its scrub is `dnc_refresh_all` (`--from-ledger`), which links each checked contact to its snapshot. The single-registry `dnc_refresh` (`--fake`, `--snapshot`, `scripts/dnc-daily.sh`, and `run_nightly` when handed a registry) stamps a fresh check, writes no new link and keeps any earlier one (`coalesce`): the linked list may be newer or older than the one it judged against, `--fake` judges against none, and a contact with no link is judged on its stamp alone | `scripts/daily-run.sh`; `jobs/dnc_refresh.py:137-139`, `:172-200`, `:239-278`; `jobs/nightly.py:19-24` |
| In production every contact in a subscribed code links a snapshot (24,212 of 24,212 on 2026-09-13); the single-registry scrub had been run on production before, on 2026-08-05 (`dnc_refresh --snapshot`) | git history of `docs/current-state.md` at `4b6d5b9` |
| Area codes nobody subscribes to are never scrubbed: a contact in a code never subscribed keeps `dnc_checked_at` null; one in a code unsubscribed after scrubbing keeps its old stamp and link. `subscribe_area_codes remove` deletes one holder's subscription row; the code stays covered while another holder's row remains | `jobs/dnc_refresh.py:80-96`; `jobs/subscribe_area_codes.py:112-117`; migration `0013` |
| Freshness, in the gate and in the export: the check `>= now() − make_interval(days => 31)`, and, when the contact links a snapshot, its `version_date >= (UTC date) − 31`. No session sets a time zone, so the first follows the server's zone across a daylight-saving change (743 or 745 hours in a Pacific session) | `service/assignment.py:120-131`, `:328-331`; `config/params.py:33`; `db/session.py` |
| The gate's causes, in order: `seed`, no phone, `already_assigned`, `won`, mid-funnel (any non-assignable stage, `suppressed` included), `voice_suppressed` (`do_not_call`), `dnc_registry`, `tombstoned` (a voice tombstone for the phone), `dnc_unsubscribed`, `dnc_stale`. `tombstoned` is pinned by frozen tests | `service/assignment.py:134-160`; `tests/acceptance/test_partner_assignment.py:243`; `tests/acceptance/test_export_compliance_invariant.py:160-163` |
| The export drops `do_not_call` and `dnc_registry` contacts silently, and reports a stale or never-checked contact as a `dnc_stale` shortfall. It does not read the subscription, tombstones, or opt-out events. The frozen invariant pins the shortfall as exactly `{dnc_stale: …}` | `service/assignment.py:324-338`, `:351-356`; `tests/acceptance/test_export_compliance_invariant.py:194-196` |
| The frozen export invariant changes `dnc_registry`, `do_not_call`, the check's age and the list's age after assignment; never the subscription, a tombstone, or an event. Its oracle `_forbidden_phones` reads no events | `tests/acceptance/test_export_compliance_invariant.py:117-134`, `:170-187` |
| "Don't call me again" can exist with no flag and no tombstone: a pre-`0010` `contact.opt_out`, one recorded by `ingest_event`, an unmatched one carrying the phone, a voice `contact.suppressed` recorded without the flag. Part 1's intake counts all but the last; `is_suppressed` reads `contact.opt_out` whose reason is not `do_not_mail` (a missing reason included), and a `suppressed` stage never reverts | `derivation/rules.py:66-79`, `:103-106`; `service/rep_intake.py` `_judge`; `tests/acceptance/test_suppression_split.py:489` (an event-only opt-out) |
| `ingest_event` accepts any taxonomy type from any valid source, with any payload; `resolve_orphans` later sets `contact_id` on unmatched events, by mailer code, thread, or exact phone | `service/ingestion.py:94-115`, `:170-203`; `resolution/matcher.py:47-69` |
| `suppress()` sets the flag, appends the event with the clock's time, writes a tombstone per channel, and for `voice` / `all` returns a held contact to the house (not when the house holds it); it has no caller on the branch; its docstring says "Permanent by design" | `service/contacts.py:421-494`, `:426`, `:443`, `:487` |
| `clear_suppression` clears `dnc_registry` only, `voice` refused — pinned by frozen tests; its docstring calls it "the single public write path" for `contact.suppression_cleared` and says it "rejects the permanent channels"; it can clear `dnc_registry` with no check and no list; only the scrub calls it. No `unsuppress` verb exists — pinned | `service/contacts.py:496-524`, `:504-507`, `:511`; `tests/acceptance/test_suppression_split.py:200`; `tests/acceptance/test_contacts.py:139` |
| Tombstones have an `id`, phone, list key, channel, reason, and `created_at` (default `now()`); nothing links one to the event that wrote it | migration `0010` |
| Door A makes a contact with `do_not_call` set when a voice tombstone matches its phone **or its list key**, and stores any number `to_e164` accepts. Door B refuses a number with a voice tombstone for the phone | `service/contacts.py:139`, `:152-168`, `:290-292`; `service/rep_intake.py` |
| `set_owner` records each owner change as an event carrying `previous_owner_id` and `new_owner_id` | `service/custody.py:56-57` |
| `contacts.created_at` defaults to the database's `now()` | migration `0001` |
| `clean_db` truncates a fixed list of tables; the test guard refuses any database not on an allowlist (`mailengine_dev`, `mailengine_test`) — fail-closed; `make test` points it at `mailengine_test` | `tests/conftest.py:110-114`; `tests/guard.py:16`, `:40`; `Makefile` |
| The DNC files are read by the pull (to judge each upload) and the scrub (from local working copies). The pull re-lands an accepted file whose copy is missing, only for objects the upload Worker still lists as pending; a truncated listing is refused | `jobs/dnc_pull.py:60-81`, `:91-111`; `seams/snapshot_inbox.py:86-96` |
| The 31 days were checked against 16 CFR 310.4(b)(3)(iv) on 2026-09-13: "obtained from the Commission no more than thirty-one (31) days prior to the date any call is made" | git history of `docs/current-state.md` at `4b6d5b9` |

## 4. The design

### 4.1 The DNC status

`dnc_status(contact_id, at)` in a new `service/dnc.py`. `at` is a time-zone-aware
instant, handed in (the clock rule, part 1 §4.6); a naive `at` is refused (`bad_time`),
an unknown contact too (`no_contact`). The first that applies:

| # | The contact | Status |
|---|---|---|
| 0 | Is a seed | `seed` |
| 1 | Has "don't call me again" in any form the voice block reads (below) | `do_not_call` |
| 2 | Has no phone | `no_phone` |
| 3 | Its area code has no subscription, and it came in before the start of the last completed daily scrub at or before `at` (§4.4) | `not_covered` |
| 4 | Its area code has no subscription, otherwise; or it was never checked; or its check is stamped after `at`; or its link is to another area code's list | `not_checked` |
| 5 | Is on the DNC file (`dnc_registry`) | `on_dnc_file` |
| 6 | Its check is older than 31 days (today's interval), or its linked list is more than 31 UTC days old (§4.2) | `check_too_old` |
| 7 | Otherwise | `clear` |

**The voice block** is any of:

- `do_not_call`;
- a voice tombstone for the phone, or for the list key of any of its intake rows;
- its events make `is_suppressed` true (a `contact.opt_out` whose reason is not
  `do_not_mail`, a missing reason included);
- a **voice** `contact.suppressed` event on the contact — its `channel` absent, or
  anything but `mail` or `sms` — that is not the event of a **lifted** request (§4.7);
- **any** `contact.opt_out` event whose reason is not `do_not_mail`, or any voice
  `contact.suppressed` event (other than a lifted request's), that **carries the phone** —
  `to_e164(payload.phone_e164)` **and** `to_e164(payload.phone)`, both counted, a value
  that is not a string taken through `str()` first and a payload that is not an object
  read as empty — one
  stricter than the matcher, which uses `phone_e164` raw and ignores `phone` when it is
  present —
  **whether or not it is attached to a contact, and to which.** An opt-out attached by
  mailer code to another contact still blocks the phone it carried.

- **Every form is read as currently recorded, whatever its recorded time** — a block
  recorded with a future time blocks now. Only freshness, row 3's run lookup, and row 4's
  "stamped after `at`" use `at`.
- **Only `clear` may be called** as far as DNC goes (decision 4.1). "Failed" in 4.1 is
  read as row 5; a check that could not run leaves the old one, which becomes row 6 (§9,
  design answer).
- **The voice block covers what part 1's intake row 3 refuses, and more:** the flagless
  voice `contact.suppressed`, list-key tombstones, and carried phones of attached events.
  One difference runs the other way: part 1 refuses an unmatched `do_not_mail` opt-out,
  which the voice block — like `is_suppressed` — does not count; intake is the stricter,
  and so safe. The carried phones are computed in Python over every such event, matched
  or not, and passed to the shared SQL as an array.
- **An unmatched opt-out with no phone** — only a mailer code — blocks nothing until the
  nightly `resolve_orphans` attaches it to its contact (§6).
- **Row 4's link rule.** A contact's link is the list its verdict came from. A link to
  another area code's list is not that, so the contact reads `not_checked` — stricter
  than answers 3 and 5, which declined requiring a link, and not ruled out by them. A
  contact with no link is judged on its check's age alone (answer 3). The single-registry
  scrub, which writes no link, runs only on dev and test databases (§4.10); checks made
  before the build are verified by §8.
- **Row 3 is decision 4.6** (answer 1). "Came in" is the later of `contacts.created_at`
  and the newest `intake_rep.added_at` for the contact, compared with the run's start: a
  contact a rep claims from NMC's list reads `not_checked` until the next run, like a new
  one. `added_at` is the caller's `at` and the run's start the database's clock; a skew
  between them can move a claim to `not_covered` a run early — harmless, both refuse.
- **Which SAN covers a code is not asked here.** A code any holder subscribes to counts
  as covered for every rep, as today (§6).

### 4.2 The 31 days (decision 4.2; 9.10; answer 3)

Kept exactly as they are (answer 3, re-asked on the corrected fact): the list's age in
whole days on the UTC date, `version_date >= (UTC date of the moment) − 31`; the check's
age as today's exact interval, `>= moment − make_interval(days => 31)`. The legal wall is
the list's age, which stays strict: the UTC date is never behind the date in any US zone
west of UTC (all of today's subscribed codes are in California). The check's interval
follows the database session's zone across a daylight-saving change (743 or 745 hours,
§3); the shared SQL keeps it as it is, and the status computes it the same way in the
database, so the three readers agree.

### 4.3 One rule, three readers

`service/dnc.py` holds the SQL for the voice block and for freshness, each over a
contact row and an explicit moment. Three readers:

- **`dnc_status`** (§4.1), with `at` handed in.
- **The assignment gate** (`service/assignment.py:134-160`), with `now()` as the moment.
  **Its causes and their order are unchanged**; three of them read more: `voice_suppressed`
  is returned for `do_not_call` **or** any other form of the voice block except a
  tombstone — so a contact whose opt-out is only an event is refused before the nightly
  stage catches up; `tombstoned` matches a tombstone for the phone **or any of the
  contact's list keys** (today the phone only, `service/assignment.py:129-130`); and
  `dnc_stale` also covers the link rule of §4.1 row 4. Freshness is read from the shared
  SQL.
- **The export** (`service/assignment.py:324-338`), with `now()`: a contact is on the
  sheet only if none of the gate's DNC causes applies. **Its shape is unchanged:** a
  contact refused for the voice block, `dnc_registry`, or an unsubscribed code is dropped
  silently, as `do_not_call` and `dnc_registry` are today; a stale, never-checked, or
  wrongly linked one is in the shortfall as `dnc_stale`, as today. Today's export misses
  an unsubscribed code, a tombstone with no flag, an event-only opt-out, an unmatched
  opt-out or voice event, and a flagless voice `contact.suppressed` (§3); decision 6.6
  keeps the export for the operator and for reps not on the app.

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
stamps). The start is read in the job module, not in `service/`: jobs are the outer layer
that may read a clock. It calls the verb when it
finishes; no row when it raises; a row when nothing is subscribed. The single-registry
`dnc_refresh` records nothing.

Status row 3 reads the latest `started_at` of an unlimited run at or before `at`. A run
still in progress has no row. The table holds only what part 2 reads; part 6 adds what
its job-status report needs (decision 2.8).

### 4.5 A rep's "don't call me again" (decisions 4.3; 9.8; answers 2, 7)

`report_do_not_call(rep, contact_id, reason, at)` in `service/dnc.py`. **Every real
report is recorded** (decision 4.3; decision 8.8, "permanently"), and only an admin's
lift (§4.7) takes one back.

| The call | Result |
|---|---|
| `at` has no time zone | refused `bad_time` |
| No contact has the id | refused `no_contact` (§6) |
| The contact has no phone | refused `no_phone` |
| The rep is unknown, or is the house (the house uses §4.6) | refused `bad_rep` |
| The rep does not hold the contact and never has — no owner-change event names them as its new owner, and no `intake_rep` row of theirs is on it | refused `not_yours` (answer 7) |
| Otherwise | `blocked` — whoever holds it now, active or inactive rep, whether or not it was already blocked |

One transaction, the contact row locked `for update`, every read taken under the lock,
through a **request helper** shared with §4.6:

- A **`dnc_requests`** row (§10) — the verb-only record of the request: its kind (`rep`),
  the contact, the phone, the rep, the reason, `at`, the event and tombstone below, and
  **whether `do_not_call` was already set** before it.
- `do_not_call = true` (already true is fine).
- A voice tombstone for the phone, with the primary list key when there is one,
  `created_at = at`.
- A `contact.suppressed` event, `occurred_at = at`, payload `{channel: voice, reason,
  reported_by: <rep>}`. A missing or blank `reason` becomes "asked not to be called".
- **Custody does not change.** The rep who holds it keeps it (answer 2) and part 5 shows
  it in their Closed list; a contact another rep or the house holds stays where it is.
  Wherever it sits, every reader of the voice block refuses it, and part 5 takes it out
  of every holder's lists (decision 7.11).

A retry writes another request: harmless — a lift lifts every live request on the
number. `suppress()` is unchanged.

### 4.6 An admin's "don't call me again" (9.9)

`record_do_not_call_request(phone, reason, at)` in `service/dnc.py`, for a request that
reached NMC by email or phone. The phone is normalized with `to_e164` first.

| The call | Result |
|---|---|
| `at` has no time zone | refused `bad_time` |
| The reason is missing or blank | refused `no_reason` |
| `to_e164` rejects the phone | refused `invalid_phone` |
| A non-seed contact has the phone | `blocked` through the request helper of §4.5, kind `admin`, no rep, the event's payload `reported_by: admin`; custody unchanged |
| No non-seed contact has it | a `dnc_requests` row (kind `admin`, no contact, no event) and a voice tombstone for the phone, `created_at = at` — even for a number part 1's stricter rule rejects, because door A stores any number `to_e164` accepts |

The request row keeps the phone, the reason, and the time for good (decision 8.8), even
after a lift deletes the tombstone. Door B refuses the number from then on; door A creates
it with `do_not_call` set (`service/contacts.py:152-168`, `:290-292`). If a contact with the
phone is created at the same moment, it can land without the flag; the voice block reads
the tombstone, so the number is refused everywhere.

### 4.7 An admin lifts recorded requests (decision 4.4 as replaced; answers 8, 9)

A rep who reported by mistake asks the operator. The operator first reads
`live_requests(phone)` in `service/dnc.py` — exactly the set the lift will lock: every live
request on the non-seed contact with the phone, or on the phone itself; its id, kind, rep,
reason, `requested_at` — and judges it. Then
`lift_do_not_call(phone, request_ids, reason, at)` lifts **exactly the requests the operator
named**, reps' or admins', and nothing else (answer 9). The phone is normalized with
`to_e164` first. It returns the ids it lifted.

| The call | Result |
|---|---|
| `at` has no time zone | refused `bad_time` |
| The reason is missing or blank | refused `no_reason` |
| `to_e164` rejects the phone | refused `invalid_phone` |
| No live request is on the number | refused `nothing_to_lift` |
| The live requests on the number, once locked, are not exactly `request_ids` — one was added, or one named is gone or already lifted | refused `changed` — the operator reads them again |
| Anything else blocks it | refused `other_block` — the number stays blocked |
| A contact was created while it ran | refused `retry` — nothing changed |
| Otherwise | `lifted` |

One transaction. It locks the non-seed contact with the phone, if one exists, `for
update`, then the live `dnc_requests` rows on that contact or phone, `for update`, in `seq`
order. Then comes the first hook the locking tests pause at (§7); **after it** are made,
in the table's order, the `nothing_to_lift`, `changed`, `retry`, and `other_block`
checks, as the last reads. Then a second hook, and then the first write. If, once the rows are locked, any
of them names a contact the lift did not lock, or a contact with the phone now exists
that it did not lock, it is refused `retry` and changes nothing — a contact was created
while it ran. **Anything else** is any form of
the voice block (§4.1) other than these requests' own traces:

- a voice tombstone, for the phone or any of the contact's list keys, that is not one of
  these requests' tombstones;
- an opt-out under `is_suppressed`;
- a voice `contact.suppressed` event on the contact that is not one of these requests'
  events (or of requests lifted earlier);
- an opt-out or voice event carrying the phone, attached or not, that is not one of these
  requests' events;
- a flag already on before these requests: the first of them **in recording order**
  (`seq`, §10 — not `requested_at`, which the caller supplies) has `flag_was_set` true.

When nothing else blocks it:

- `do_not_call = false` on the contact, if there is one.
- **Only these requests' own tombstones are deleted, by id.** A request that arrives
  before the lift locks its rows makes the set differ from what the operator named, so
  the lift is refused `changed`; one that arrives after is recorded after the lift and
  blocks again.
- Each request row is marked lifted (`lifted_at`, `lift_reason`); the rows are kept.
- A `contact.suppression_cleared` event on the contact, if there is one, `occurred_at =
  at`, payload `{channel: voice, reason, lifted_by: admin}`.

The lift takes the same locks, in the same order, as every writer of the contact row —
the contact first, then its own rows in `seq` order — and no table lock, so it cannot
deadlock with them or with another lift. Two lifts on one number serialize on the rows;
the second finds nothing live and is refused `nothing_to_lift`. A forged event can neither lift (only the `dnc_requests` table does)
nor be lifted (it is not a request's event, so it is "anything else"). An opt-out that
`resolve_orphans` attaches to the contact after a lift was never covered, so it blocks.

After a lift, the stage derivation does not refuse the number, and part 1's intake — which
reads the same voice block (§4.11) — refuses nothing the status admits except an unmatched
`do_not_mail` opt-out, where intake stays the stricter: a request's event is a `contact.suppressed`, which
neither `is_suppressed` nor intake row 3 reads, and an opt-out would have refused the lift.

`clear_suppression` still refuses `voice`, and no `unsuppress` verb appears, so the frozen
tests at `test_suppression_split.py:200` and `test_contacts.py:139` stand. What
`suppress()` writes is never lifted — its tombstone and event are always "anything else"
— so its docstring ("Permanent by design", `service/contacts.py:426`) stays true. The
build updates two texts, with the approved tests (§8): `clear_suppression`'s docstring
("the single public write path" for `contact.suppression_cleared`, `:504-507`), to name the
lift as the second writer; and the matrix-row comment at `test_suppression_split.py:164`
("do_not_call (voice, human, permanent)"), because the `do_not_call` column can now be
cleared by a lift of recorded requests.

The operator reaches §4.6 and §4.7 with a new command, `python -m jobs.dnc_admin_cli
block <phone> --reason …`, `show <phone>`, and `lift <phone> --ids … --reason …` — `lift`
shows the live requests first and lifts only the ids given, which closes part 0's gap "cannot record an opt-out". The
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

### 4.11 Door B reads the voice block

Part 1's `rep_intake._judge` row 3 is changed to read the shared voice-block SQL of §4.1
(and keeps its own unmatched-`do_not_mail` refusal, which is stricter). Without this, door B
would claim a contact whose only block is a list-key tombstone, a flagless voice
`contact.suppressed`, or a carried phone on an attached event — numbers the status refuses —
and a rep would hold them. It is a change to part 1's built code (§9, design answer), made
under part 2's red-tier build with part 1's gate test extended, not loosened.

## 5. Part 1's hand-offs

| Part 1 left | Part 2 |
|---|---|
| Undoing a "don't call me again" (4.4) would leave the tombstone, so intake would keep refusing | Replaced: there is no rep undo; an admin's lift deletes the lifted requests' tombstones (§4.7), and intake then admits the number unless something else blocks it |
| A voice `contact.suppressed` recorded without the flag is not read by intake row 3 | Intake row 3 now reads the voice block (§4.11) |
| A held contact returns to the house on a voice block | Part 2's verbs never move custody. `suppress(voice)` still does; it has no caller on the branch, and part 4 decides (§6) |

## 6. Gaps and limits

Gaps are not questions (decision 2.9).

| Gap or limit | Closed in |
|---|---|
| Nothing outside tests calls `dnc_status` or `report_do_not_call` | Parts 5 and 6 |
| The age of each area code's DNC file, for alerts (interface job 2) | Part 6, over `dnc_snapshots` and `dnc_runs` |
| A rep's own contact is taken back to the house on a DNC hit (`jobs/dnc_refresh.py:147-153`) and by `suppress(voice)` | Part 4 (decision 6.3) |
| A retried report writes another request, not its first answer | Part 6 (decision 7.7) |
| Which SAN's subscription covers a code for which rep | Counsel (memo Q4); part 4 if it changes who may be given a code |
| A number blocked by an old opt-out or any block not recorded through part 2's verbs cannot be lifted | Answer 9: it stays blocked |
| An unmatched opt-out carrying only a mailer code blocks nothing until the nightly `resolve_orphans` attaches it | Left: the nightly attaches it; the status reads it from then on |
| A report queued on a phone (decision 8.7) whose contact has since been hard-deleted is refused `no_contact` | When a hard delete is built (FR-8): it must route such a report to §4.6 by phone |
| A hard delete (FR-8, not built) that removes events loses an event-only opt-out or flagless voice event, which have no tombstone; FR-8 must write a voice tombstone for each | When a hard delete is built |
| The gate and the export read tombstones, events and requests in their statement's first snapshot, and the carried-phone array from an earlier statement — outside the row lock: an opt-out landing mid-batch is not seen by that batch; the next one sees it, and the status reads it at call time. (Door B judges with fresh statements after its lock, so it does see it.) | Left |
| A sheet passes the 31-day check when it is pulled; a rep not on the app may dial from it later, past 31 days | Left: the export's rule "re-pull before each session" (`service/assignment.py:311-317`); reps on the app are checked at every call (part 5) |
| `clear_suppression(contact, 'dnc_registry')` clears a registry verdict with no check and no list; only the scrub calls it | Left: part 6 must not expose it |
| The re-landing of each code's newest DNC file on every run (§4.8) | Hosting (9.11) |
| `dnc_status` trusts the `at` it is handed | Parts 5 and 6 pass the server's clock (decision 7.6) |
| Part 5's wrong-number replacement (9.14) changes a phone: the new phone must be checked again, and a lift or request on the old phone does not follow it | Part 5; §4.1 row 4 refuses a verdict linked to another code |
| The console's inventory counts do not read the voice block | Left: an operator view, not a path to a call |
| A no-contact lift that commits while `load_list` is between reading tombstones (`service/contacts.py:160-169`) and creating the contact (`:268-294`) leaves the contact flagged with no live request: it can never be lifted. A future hard delete of a contact with a live request leaves a request naming a deleted contact: a lift on a re-created contact is refused `retry`. Both over-block | Left, safe; FR-8 must re-point or close such requests |
| NANP codes in zones east of UTC (Guam 671, Northern Mariana Islands 670): the UTC date can be behind theirs, so the list's age would not err toward stale there | Before any such code is subscribed |
| An unmatched opt-out carrying only a mailer code or thread blocks nothing until the nightly `resolve_orphans` attaches it — short of decision 4.3's "at once". No code writes such an event today | When one does (part 6's event intake): resolve it at once, by `pieces.mailer_code` or thread, as the matcher's first steps do |

## 7. Tests, written first

`clean_db` gains `dnc_runs` and `dnc_requests` in its truncate list (`tests/conftest.py`),
and so do the other truncates that restart event ids: the e2e journey's wipe
(`tests/e2e/test_partner_journey.py:48-57`) and `tests/acceptance/test_grain_intake.py:70-71`.
A test that creates reps deletes its `dnc_requests` rows before deleting the reps
(`rep_id` references `partners`), as the `intake_rep` tests do.
The verbs have a no-op hook inside their transaction, after their locks and before their
first write, for the locking tests to pause at — as part 1's `rep_intake._before_insert`.
`make test` runs them on `mailengine_test`; the single-registry test replaces its allowlist
and never names another database.

| Test | Checks |
|---|---|
| The voice block, each form, in each reader | `do_not_call`; a voice tombstone on the phone; one on a list key but not the phone; an opt-out event with a reason, and with none; an unmatched opt-out under `phone_e164`, and as `(818) 555-0123` under `phone`; an unmatched voice `contact.suppressed`; an unmatched `contact.suppressed` with channel `mail` → not a block; an opt-out carrying phone P attached (by mailer code) to a contact with another phone → P still blocked; an opt-out ingested on a contact but carrying another phone → that phone blocked; a flagless voice `contact.suppressed` — each gives `do_not_call` in `dnc_status`, a refusal by the gate (`voice_suppressed`, or `tombstoned` for a tombstone), and absence from the export |
| A future time | A flagless opt-out recorded with an `occurred_at` a day ahead: `do_not_call` now, in the status, the gate and the export |
| Status 0, 2 to 7 | The status; a naive `at` refused; an unknown contact refused; a seed → `seed` |
| The order | status 1 + on the DNC file → `do_not_call`; not covered + on the DNC file → `not_covered`; on the DNC file + stale → `on_dnc_file`; no phone + unsubscribed → `no_phone`; unsubscribed + never checked + before the last run → `not_covered` |
| Not covered after the run | A contact in an unsubscribed code: `not_checked`; `dnc_refresh_all` completes; `not_covered`. A contact created, or claimed by a rep, after that run began: `not_checked`. An `at` before the run: `not_checked`. A `--limit` run or a single-registry run does not count |
| Runs | `dnc_refresh_all` writes one row when it finishes, one when nothing is subscribed, none when it raises; `dnc_refresh` writes none |
| The 31 days | Through `dnc_status` and the shared SQL with an explicit moment: the check a minute inside `31 days` fresh, a minute past stale, computed the same way in all three readers; the list 31 UTC days old fresh, 32 stale, under `PGTZ` at UTC+14 and UTC−11. Through the gate and the export with `now()`: the same, without the daylight-saving case. A check stamped after `at`: `not_checked` for `at` |
| The link | A fresh check linked to another code's list: `not_checked` in the status; refused `dnc_stale` by the gate; in the export's shortfall |
| The gate | Every existing cause name and order unchanged; an event-only opt-out on a released contact → `voice_suppressed` before any recompute |
| The export | Assigned, then each form of §4.3's additions: none on the sheet, none in the shortfall; the existing frozen assertions unchanged |
| Report | Each refusal, nothing written; by the holder (keeps it; one request, one tombstone, one event); by a rep who held it and lost it (recorded); held by another rep, and by the house (custody unchanged); on an already blocked contact (another request); from an inactive rep (recorded); a rep who never held it → `not_yours` |
| Admin request | Each refusal; with a contact a rep holds: blocked, custody unchanged; a contact whose stored phone part 1's rule rejects: blocked; without a contact: a request row and a tombstone, no contact, no event; door B refuses; door A creates it with `do_not_call` |
| Lift | Each refusal. `live_requests` lists them. Two reps' reports and an admin's request on a number, all three named → lifted, their ids returned: flag false, their three tombstones gone, any other tombstone untouched, the rows kept and marked lifted, one clear event, status not `do_not_call`, the gate and the export admit it, intake no longer refuses, and after a recompute the stage is not `suppressed`. Then a new report → `do_not_call` again. A lift on a number with no contact, then door A creates it: no flag. Refused `other_block` for each: an old opt-out event; a list-key tombstone not from a request; a phone tombstone from `suppress(voice)` after a request; a flagless voice event; an unmatched opt-out; an unmatched voice event; the flag already on before the first request. A queued report recorded second but with an earlier `at` does not make the lift refuse. A live request not named → `changed`, nothing lifted. A request recorded after `live_requests` was read and before the lift → `changed`. A contact created by door A while a no-contact lift waits: refused `retry`, nothing changed. A live request naming a contact the lift did not lock: `retry` |
| Later attachment | An unmatched opt-out with a mailer code only; a lift of the contact's requests; `resolve_orphans` attaches the opt-out → `do_not_call` |
| Forgery | An ingested `contact.suppression_cleared` lifts nothing; an ingested voice `contact.suppressed` on a reported contact makes the lift refuse `other_block` |
| Locking | A report paused at its hook while `assign_batch` waits: the batch refuses (`do_not_call` on the locked row, re-read after the wait). A report paused while `add_numbers` waits: `do_not_call`. A lift paused at its first hook while a report on the same contact waits: the lift commits, then the report is recorded and blocks. **A no-contact lift paused at its second hook** (after its checks, before its first write) while an admin no-contact request for the same phone commits: the lift returns `lifted`, the new request's tombstone still exists, the new request is still live, and `dnc_status` / door B refuse the number — which a phone-wide delete would fail. An admin no-contact request committed while a lift is paused at its first hook: `changed`. A lift paused while an admin request with no contact is written for the same phone: that request's tombstone survives the lift and blocks. Two lifts on one number: the second is refused `nothing_to_lift`. A lift paused while `assign_batch` waits on the contact: no deadlock; the batch refuses the contact as `voice_suppressed` (the re-read row shows the flag false, but the request's voice event, not yet lifted in the statement's first snapshot, still blocks, and `voice_suppressed` comes before `tombstoned`) |
| The clock | `occurred_at` of every event, `created_at` of every tombstone, and `requested_at` / `lifted_at` of every request the new verbs write equal `at` |
| The operator's command | `jobs.dnc_admin_cli` blocks, shows, and lifts named ids, with and without a contact, and refuses a blank reason |
| Carried phones | An opt-out with a badly formed `phone_e164` and a valid `phone` blocks the valid one; one with `phone_e164` in another format blocks its normalized form; one with `phone_e164` stored as a JSON number, and one whose payload is a JSON array, neither crash any reader |
| Door B | A list-key tombstone, a flagless voice `contact.suppressed`, and a carried phone on an attached event each make door B refuse `do_not_call`; part 1's existing tests stay green |
| The single-registry scrub | With the allowlist replaced so that `mailengine_test` is not on it, `dnc_refresh` raises and writes nothing; restored, it runs |
| Frozen tests | Every existing assertion passes; the export invariant gains new functions (§4.3); the edited docstrings and `:164` comment (§4.7) change no assertion |

## 8. Done means

| Check | How |
|---|---|
| The build follows the red-tier gate: the gate and the export change, suppression verbs, tombstone deletes, a migration | Build plan approved first; the tests — including the export invariant's new functions and the edited `:164` comment — approved as its first step |
| The tests of §7 pass; every existing assertion passes unchanged | `make test` |
| `make e2e`, `make lint` | Pass |
| `0015` changes no existing row on production-shaped data | As part 1's §8 check, from a checkout without `0015` |
| On production-shaped data, read-only: every contact in a subscribed code with `dnc_checked_at` set has a link, the link's area code is the phone's, and the latest `contact.dnc_checked` event's `snapshot_id` equals the link; every non-null contact phone matches `^\+1[0-9]{10}$` (else a report on it would fail `dnc_requests`' check); and a count of contacts the new rules refuse that today's gate does not | Before the build ships; any mismatch is put to the operator |

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
| 8 | Replace the rep's 24-hour undo (4.4) with an admin-only lift | **Answered 2026-09-30:** the admin lifts it — no rep undo, by hand with a written reason. Offered "Admin lifts it", "No undo at all for now", or "Keep the 24h rep undo". |
| 9 | What the admin lift covers | **Answered 2026-09-30:** only requests recorded through part 2's verbs; a number also blocked any other way stays blocked (§4.7). Offered "Lift recorded requests only" or "No lift at all for now". Narrows answer 8's "the whole block". |

**The design's own answers**, for approval with the part (each has one obvious reading):

| Point | Answer |
|---|---|
| 9.9, an admin's request with no contact | A request row and a voice tombstone (§4.6) |
| 9.11, the files on Render | Pull and scrub in one job; the service reads no file; hosting re-lands each code's newest file every run (§4.8) |
| 9.16, the 31 days | As checked 2026-09-13 (§4.9) |
| Custody | No verb of part 2 moves it (§4.5) |
| A retry of a report | Writes another request (§4.5) |
| A link to another code's list | Reads `not_checked` (§4.1 row 4) |
| A seed | Reads `seed` (§4.1 row 0) |
| "Came in" for status row 3 | The later of `contacts.created_at` and the newest `intake_rep.added_at` (§4.1) |
| "Failed" in decision 4.1 | On the DNC file (row 5); a check that could not run ages into row 6 (§4.1) |
| A carried phone | Blocks whether or not its event is attached, and to which contact; both `phone_e164` and `phone` count, normalized (§4.1) |
| What a lift lifts | Exactly the requests the operator named after reading them; anything else live refuses it (§4.7) |
| Door B and the voice block | Part 1's intake row 3 reads the shared voice block (§4.11) — a change to part 1's built code |

## 10. The migration, `0015.dnc-filtering.sql`

```sql
create table dnc_runs (
  id          uuid primary key default gen_random_uuid(),
  started_at  timestamptz not null,
  limited     boolean not null
);

create index dnc_runs_unlimited_idx on dnc_runs (started_at) where not limited;

create table dnc_requests (
  id            uuid primary key default gen_random_uuid(),
  seq           bigint generated always as identity,
  kind          text not null check (kind in ('rep', 'admin')),
  contact_id    uuid,
  phone_e164    text not null check (phone_e164 ~ '^\+1[0-9]{10}$'),
  rep_id        uuid references partners(id),
  reason        text not null check (btrim(reason) <> ''),
  requested_at  timestamptz not null,
  event_id      bigint,
  tombstone_id  uuid not null,
  flag_was_set  boolean not null,
  lifted_at     timestamptz,
  lift_reason   text,
  check ((kind = 'rep') = (rep_id is not null)),
  check (rep_id is null or rep_id <> '00000000-0000-4000-8000-000000000001'),
  check (kind = 'admin' or contact_id is not null),
  check ((contact_id is null) = (event_id is null)),
  check (contact_id is not null or not flag_was_set),
  check ((lifted_at is null) = (lift_reason is null)),
  check (lift_reason is null or btrim(lift_reason) <> '')
);

create index dnc_requests_contact_live_idx on dnc_requests (contact_id) where lifted_at is null;
create index dnc_requests_phone_live_idx on dnc_requests (phone_e164) where lifted_at is null;
create unique index dnc_requests_event_idx on dnc_requests (event_id);
create unique index dnc_requests_tombstone_idx on dnc_requests (tombstone_id);

grant select on dnc_runs, dnc_requests to me_user_ro;
```

Additive. `contact_id`, `event_id` and `tombstone_id` carry no foreign key: a request, like a
tombstone, must outlive a hard delete of its contact and events, and a lift deletes the
tombstone while the row keeps its id. A request with no contact is an admin's, with no
event and `flag_was_set` false. `seq` is the order requests were recorded in. `lifted_at`
is not checked against `requested_at`: both are caller-supplied, and a request may be
recorded with a future time (§4.1). The explicit grant does not rely on `0002`'s default
privileges.

## 11. Proposed changes to the decision record and the upgrade's documents

| Where | Proposed change |
|---|---|
| Record 4.4 | Replace: no rep undo; the operator lifts, by hand with a written reason, the requests recorded through part 2's verbs; a number blocked any other way stays blocked (answers 8, 9). Move the 09-28 wording to §10 |
| Record 9.8 | Decided: the reporting rep, if they hold it, keeps the contact, Closed (answer 2) |
| Record 9.9 | Decided: a request row and a voice tombstone (§9, design answer) |
| Record 9.10 | Decided: kept as it is — the list in whole UTC days, the check as `now() − 31 days` (answer 3) |
| Record 9.11 | Decided for part 2: pull and scrub in one job; hosting must re-land each code's newest file on every run (not yet built) |
| Record 9.16 (DNC half) | Decided: the 31 days as checked against 16 CFR 310.4(b)(3)(iv) on 2026-09-13. State DNC lists and Sunday rules stay open with counsel |
| Record 4.3 | Add: every report is recorded, whoever holds the contact; a rep may report a contact they hold or have held (answer 7); no report moves custody |
| Record 4.6 | Add: "after the check" is after the next completed daily run (answer 1) |
| Record 4.1 | Add: production scrubs only through the ledger path; the single-registry scrub runs only on named dev and test databases (answer 5) |
| `00-purpose.md:58` | "the rep who reported it can undo it within 24 hours" → an admin lifts recorded requests |
| `00-interface.md:42`, `:43`, `:97`, `:116` | "undone 'don't call me again'" → lifted; "which of the rep's own actions can still be undone" loses the part-2 case; `:43` (admin "don't call me again") is built |
| `00-overview.md` §4 | Part 2's row |

## 12. Safety properties

Every revision is checked against these before review. Each names where the design keeps
it.

| # | Property | Kept by |
|---|---|---|
| S1 | A number with "don't call me again" in any form the voice block reads is never `clear`, never assigned, never exported — until an admin lifts the requests part 2 recorded, and only when nothing else blocks it | The voice block (§4.1), read by all three readers (§4.3); the lift's `other_block` refusal (§4.7) |
| S2 | Nothing but an admin's lift clears a block, and a lift clears only the requests it locked, on the record with a reason | §4.7: row locks, tombstones deleted by id, rows kept; `clear_suppression` still refuses `voice`; forged events clear nothing |
| S3 | Every real request is recorded, and kept | A report is refused only for a missing contact or phone, a naive time, an unknown rep or the house, or a rep who never had the contact (§4.5); an admin's request is recorded even with no contact (§4.6); no verb deletes a request row — a convention of the code, not enforced by §10 |
| S4 | A check is `clear` only against a list no more than 31 days old: the linked list, or — only for a contact with no link — the check's own age | Freshness (§4.2), row 4's link rule (§4.1), the single-registry scrub confined to dev and test (§4.10), §8's check of past links |
| S5 | The export refuses whatever the status refuses for a DNC cause, and keeps its frozen shape (seeds and phoneless contacts never reach it: the gate refuses them) | §4.3 |
| S6 | `make test` touches only `mailengine_test`; nothing fake-scrubs production | §4.10, §7 |
| S7 | (Process, not a property of the design:) a claim that something is safe or unchanged is checked against the code or the tests before it is written | How each revision is written |
| S8 | No verb of part 2 takes a table lock or takes locks in an order other writers of the contact row do not | §4.5–§4.7: the contact row first, then its own rows in `seq` order |
| S9 | An event's carried phone blocks that phone however the event is later attached | §4.1, the carried-phone form |
| S10 | A lift lifts only what the operator saw and named | §4.7: `live_requests`, the named ids, `changed` |
