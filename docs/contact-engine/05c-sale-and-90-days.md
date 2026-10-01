# contact-engine Upgrade — Part 5c: The sale and the 90 days

**Status:** APPROVED by the operator, 2026-09-30, at revision 7, with §5's frozen-test
changes (offered "Approve now", "One more review", or "Read it first"; chose approve
now). **BUILT 2026-10-01:** under an approved build plan and an approved test gate:
`0019.web-seller.sql`, `service/sale.py`; the Signed up's partner lock, seller check
and hold in 5a's `service/calls.py`; a sold contact Closed *a customer* in 5b's
`service/rule.py`; part 4's gate (`won` read again after the locks, `closed` and
`resting`, `state_at`), `max_held`, both expiry rules and the won step in
`service/assignment.py`; door B's sold test in `service/rep_intake.py`; the approved
frozen-test changes (and the e2e's import of the house id, no longer used). Gate
`tests/acceptance/test_sale_and_90_days.py` (one test split in two while it was being
written, before the code: two calls cannot be open on one contact). Every §8 mutation
failed the gates. Five
questions were put to the operator before the design (answers 1 to 5) and one after
revision 1's review (answer 6). History: Revision 1 did not pass its review: a second
Signed up could take a sold contact from its seller; a former partner's or blocked
contact's Signed up could pull it back after a reclaim; the batch expiry rule did not
re-read the skips after its lock; "not closed" left out the block; the list of frozen
tests to change was incomplete (the e2e journey, and a second assertion); one mutation
had no test; Get more numbers would lock out a rep with many sales (asked: answer 6); the
gate's moment was unstated. Revision 2 fixes the eight and applies the minor findings.
Revision 2 did not pass: who sold a website sale was inferred and could not be built; a
Signed up that could not move the contact left it with another rep for good; a reclaim
could race a Signed up; four tests could not catch their mutations or could not pass;
the resting check read the clock. Revision 3 **records the website sale's seller once**
(`contact_state.web_seller`), returns the contact to the house when a Signed up cannot
move it, locks the signing rep first, passes `at`, and fixes the tests. Revision 3's
review found the frozen-test list complete and three holes: a Signed up could undo a
reclaim of a rep still active; the batch gate did not re-read "sold" after its lock;
`web_seller` was not written when a Signed up existed, so an undo could hand a website
sale to a third rep. Revision 4 closes the three and applies the minor findings.
Revision 4's review found the design logic sound and five gaps: `web_seller`'s foreign
key would break a frozen helper that deletes partners; three mutations had no test; one
test row could not pass. Revision 5 drops the foreign key, adds the rows, and applies
the minor findings. Revision 5's review found: a website sale kept with its rep still
read as callable in 5b; the gate's closed/resting read had no race test; property 4
overstated the "latest custody event" check (asked: answer 7). Revision 6 makes every
sold contact Closed *a customer* in 5b, adds the test, and replaces the check with
answer 7's. Revision 6 **passed** its review (no blocking finding); its minor findings
are applied here, in revision 7 — among them, answer 7's check is made clock-free.
**Part of:** [the upgrade](00-overview.md). Decisions are in the decision record,
`nvermisscall/docs/active/sales-partner-dialer-decisions.md`, named here by number
("decision 6.5"); sections of this document are named "§4.1".
**Checked against:** the `contact-engine` branch at `fb63a92` (parts 0 to 4, 5a and 5b
built). A statement about the code carries its file and line.

---

## 1. Its job

Keep a sold business with the rep who sold it; keep NMC's contacts in Got a callback or
Follow up from going back at 90 days; keep closed and resting contacts out of batches.

| Decision | What it asks | Here |
|---|---|---|
| 6.5 | Once sold, a business is out of reach of everyone but the rep who made the sale | §4.1, §4.2 (answers 1, 2) |
| 6.3 | NMC's contacts go back after 90 days, never one in Got a callback or Follow up | §4.3 |
| 9.0 | The 90 days against the rest | §4.3 (answer 3): a resting contact goes back, state and all |
| 9.1 | A sale and the pool | §4.2: a sold contact never returns to the pool from its seller |
| 9.2 | How contact-engine hears of a sale | §4.1 (answer 1): a rep's Signed up, or the website's nightly feed |
| 9.3 | Two reps, one sale | §4.1 (answer 2): the rep who signed |
| 9.12 | What a batch may give out again | §4.4 (answer 4): all but Closed and resting |
| 9.14 | Replacing a wrong number | Not built (answer 5): the rep adds the right number through door B |
| 6.2 | The ask-again point of Get more numbers | §4.5 (answer 6): sold, Got a callback and Follow up contacts do not count |
| 7.11 | A customer is out of the working lists | §4.2: every sold contact reads as Closed, *a customer*, in 5b |

## 2. Its edges

| 5c does | 5c does not — who does |
|---|---|
| Sale, seller, and the hold that follows (§4.1, §4.2) | Commission, credit, or anything the website does with a sale — the website |
| The 90-day exception and the batch gate (§4.3, §4.4) | Expose any of it — part 6 |
| | A replace-number action (answer 5) |

## 3. What exists, checked

| Fact | Where |
|---|---|
| A website sale arrives through the nightly close feed as a `signup.completed` event, matched to a contact by phone; `recompute_state` then derives stage `won` | `jobs/close_correlation.py`; `service/state.py`; `jobs/nightly.py:25-33` |
| The nightly's won step returns every `won` contact that still has a batch pointer to the house, after the expiry step | `service/assignment.py:557-573`; `jobs/nightly.py:32-33` |
| Three frozen tests and the e2e journey pin that return | `tests/acceptance/test_partner_assignment.py:478-499`, `:502-522`, `:609-633`; `tests/e2e/test_partner_journey.py:163-165`, `:194` |
| The expiry's second rule re-reads its skips after the lock; its batch rule does not | `service/assignment.py:529-546` |
| `max_held` counts every NMC contact the partner holds | `service/assignment.py:283-293` |
| `record_outcome` checks the rep is a partner, not that the partner is active; `reclaim` does not close open calls | `service/calls.py:57-60`; `service/assignment.py:458-476` |
| Door B locks the rep's partner row `for share` before the contacts | `service/rep_intake.py:56` |
| The assignment gate refuses `won` | `service/assignment.py:173-174` |
| The expiry's second rule skips a contact sold by stage, by a `signup.completed` on it, or by an unmatched sale carrying its phone; its batch rule skips nothing | `service/assignment.py:502-518`, `:519-555` |
| Door B answers `held` to anyone but the holder for a contact sold by the same three tests | `service/rep_intake.py:124-130` |
| 5a records a rep's Signed up (on a call or from the card), undoable for 24 hours; a former holder may record it on their own open call | `05a-call-record.md` §4.3, §4.7, §6 |
| 5b's `contact_state` keeps each contact's list; `rule._states` reads it in bulk | `service/rule.py` |
| `set_owner` is the one writer of the holder | `service/custody.py:19-66` |

## 4. The design

### 4.1 Sold, and the seller (answers 1, 2)

A contact is **sold** when it has a Signed up not undone, or stage `won`, or a
`signup.completed` on it, or an unmatched `signup.completed` carrying its phone — door
B's three tests plus Signed up. One SQL predicate, `SOLD_SQL`, in `service/sale.py`,
read by every place below, the won step included.

**The seller** — recorded, never inferred:
1. the rep of the latest Signed up not undone; failing that,
2. `contact_state.web_seller`: the nightly's won step writes it **once**, for every
   contact sold by the website (stage `won`, a `signup.completed` on it, or an unmatched
   one with its phone) that has no `web_seller` yet, **whatever its Signed ups** — the rep
   who holds it at that moment, or the house (NMC's own sale). It never changes after. A
   contact with no state row gets one, with the defaults (it reads as at the start). The
   step locks each such contact `for update` (in id order, with the pointer-bearing
   ones) and reads its holder after the lock, then writes through `rule._write_state`
   with `updated_at` from its own clock (existing code, part 1 §4.6).

A contact sold by an unmatched sale carrying its phone is refused by the gate as `won`
too, now that the gate reads `SOLD_SQL`: as intended.

### 4.2 The hold that follows (6.5, 9.1)

- **A Signed up** (5a `record_outcome`) locks the signing rep's partner row `for share`
  first — before the contact, as door B does — so a deactivation cannot slip between its
  check and its move (a `reclaim` takes no partner lock; the contact's lock orders it).
  Then, under the contact's lock, in its transaction:
  - **refused `sold`** when the contact has a seller (§4.1) other than the signing rep:
    the first sale stands, and no one takes a sold contact from its seller;
  - otherwise, if the contact is not with the signing rep, or still has a batch pointer,
    it **moves to that rep** with no batch (`set_owner`, `contact.assigned`, reason
    `sold`) — when the signing rep is an active partner, the contact is neither blocked
    (part 2's `BLOCKED_SQL`) nor on a DNC file (`dnc_registry`), **and nothing has taken
    the contact from the signing rep since they last held it** (answer 7): the latest
    custody event naming the signer — as `new_owner_id` or `previous_owner_id`, by event
    `id`, never by clock — is not a `contact.reclaimed` taking it from them.
    Every return to the house but expiry emits `contact.reclaimed` — a reclaim, a
    suppression, a DNC hit, the won step's, and this design's own return below — so an
    admin's take-back always wins over a later sale on a call opened before it, whatever
    happened to the contact since; a return by expiry may still be followed by the
    seller's move. A Signed up from the card is the holder's, so nothing can have taken
    it;
  - when it may not move there and **another rep** holds it, it **returns to the house**
    (`set_owner`, `contact.reclaimed`, reason `sold`): a sold contact never stays with a
    rep who did not sell it. When the house holds it, it stays. When the signing rep
    holds it with a pointer but may not move it, it stays with that rep, pointer and all,
    until the won step clears the pointer that night.
  A former holder's Signed up on their own open call therefore takes the contact from a
  holder who has not sold it (answer 2).
- **The website's sale** — the nightly's won step no longer returns a rep's contact. A
  sold contact (`SOLD_SQL`) held by a rep with a batch pointer keeps its holder and loses
  the pointer (`set_owner` to the same rep, `contact.assigned`, reason `sold`); one on
  NMC's own sheet returns to the house as before. It also writes `web_seller` (§4.1).
  The step still returns how many pointers it cleared.
- **Out of the working lists:** 5b reads **every sold contact** (`SOLD_SQL`) as Closed,
  *a customer* — not only a Signed up — so `open_call` refuses it (`closed`) and the rep's
  lists show it under Closed, website sales included (decision 7.11). A blocked sold
  contact reads *asked not to be called*: 5b checks the block first.
- **A Signed up refused as `sold` on an open call** writes nothing; the call stays open
  for another outcome or an admin's clear.
- **Never returned:** both expiry rules skip a sold contact, re-reading `SOLD_SQL` after
  the lock for **both** rules (a Signed up locks the contact without changing its row,
  so the lock alone does not re-check it); the batch gate refuses it (`won`, now read
  through `SOLD_SQL`, **re-read after the lock in a separate statement**, as the gate's
  live rows are — a Signed up that left the row unchanged is seen); door B answers `held`
  to anyone but its holder.
- **An undo** (5a) locks only the call row; a race with a Signed up's seller check or an
  expiry re-read can at worst refuse a Signed up as `sold` once, or delay an expiry a
  night.
- **An undo** of Signed up within 24 hours leaves the contact with the rep who signed; it
  is then an ordinary NMC contact held without a batch, under the 90 days of part 4,
  counted from its latest `contact.assigned` — the move's, when there was one; the
  earlier assignment's when the holder signed with no move, so an old claim can go back
  the next night — including one a former holder took from another rep and then undid
  (§6).
- `reclaim`, a DNC hit and a suppression still return it — the admin's act and the
  compliance paths override (part 1 §6).

### 4.3 The 90 days (6.3; answer 3)

Both expiry rules skip NMC's contact **held by a rep** whose 5b state is **Got a
callback or Follow up** and not closed (NMC's own sheet is not a rep's working list): `contact_state.list` in those two, **not blocked** (`BLOCKED_SQL`), no
closing outcome that is not undone, no `rep_closed` — 5b's Closed exactly. The skip is
re-read after the lock for both rules (a move or a resolution locks the contact without
changing its row). It reads the stored list, so a paused Got a callback or Follow up
contact is skipped too.
A resting contact goes back at day 90 like any other, its state with it (answer 3): its
next holder inherits *resting* and then restarts or closes it.

### 4.4 What a batch may give out (9.12; answer 4)

The assignment gate gains two causes, **after the compliance causes** (so a blocked
contact still reports `voice_suppressed`, as today): **`closed`** — 5b says Closed by an
outcome or the rep; **`resting`** — 5b says Limit reached and the rest is not over. The
state is read with the batch partner's settings (the house: the defaults), through
`rule._states` in bulk, after the lock, for the candidates that have a state row or a
closing; every other candidate is at the start. Its moment is a new option, `state_at`,
kept out of the request hash and record, as `returned_since` is: Get more numbers
passes its `at` (the clock rule, 9.15); the operator's batch, existing code, passes its
own clock. A contact whose rest is over is given out, and its new rep sees *rest over*.

### 4.5 The ask-again count (6.2; answer 6)

`max_held` counts NMC's contacts the rep holds that are **not sold, and not in Got a
callback or Follow up** (as §4.3 reads them): the contacts still to be worked through
the sequence. A rep with many sales or callbacks can keep asking.

## 5. Earlier parts

- 5a's `record_outcome` on Signed up moves the contact (§4.2).
- Part 4's expiry rules, won step and gate change as §4.2–§4.4 say; door B reads
  `SOLD_SQL`.
- Part 4's `max_held` count changes (§4.5).
- 5b's `_states` reads `SOLD_SQL`: a sold contact is Closed, *a customer* (§4.2).
- Door B reads `SOLD_SQL` for its unmatched sales: it reads `phone` as well as
  `phone_e164`, through `dnc_normalize`, so it catches at least what it caught before.
- **Frozen tests change — approved by the operator with the design, 2026-09-30**
  (decision 6.5 replaces the behaviour they pin):
  - `test_a_won_contact_never_reenters_the_pool`: the owner afterwards is the partner,
    not the house, and the batch pointer is gone; the re-assign's shortfall is
    `already_assigned` (the partner holds it), not `won`.
  - `test_nightly_runs_steps_after_recompute` and
    `test_a_codeless_close_ends_the_assignment_before_expiry`: the owner afterwards is the
    partner, not the house; the pointer is gone.
  - `tests/e2e/test_partner_journey.py`: Reseda's owner afterwards is the partner
    (`:163-165`), and the closing reclaim returns 2 contacts, not 1 (`:194`).
  Every other assertion in them is unchanged.

## 6. Gaps and limits

| Gap | Handling |
|---|---|
| A website sale on a contact with no matching phone sits unmatched until the feed carries the phone | Door B and the expiry already read unmatched sales by phone (part 1 §3) |
| The seller of a website sale is the holder when the nightly sees it, not when the customer paid | Accepted: the nightly is the first moment contact-engine knows |
| A wrong number is never replaced (answer 5) | The rep adds the right number through door B |
| A sold contact can still be reclaimed by an admin | The admin's act (part 1 §6) |
| A former holder who takes a contact with Signed up and then undoes it keeps it, as an ordinary NMC contact, for 90 days | Accepted: the undo is the rep's own, within 24 hours |
| A resting contact returned at day 90 is refused by the gate until its rest is over | Its next holder can still claim it through door B, inheriting *resting* |
| A website sale the nightly has not yet seen (no `web_seller`) can be taken by a former holder's Signed up, which ranks first | Consistent with answers 1 and 2 |
| A Got a callback or Follow up contact the batch rule skips keeps its expired batch pointer, and stays on that partner's export | Harmless: it is the rep's to work; the rule re-skips it each night |
| A sold contact whose holder may not move it keeps its pointer, and its place on the export, until the won step that night | As today |

## 7. Tests, written first

`tests/acceptance/test_sale_and_90_days.py`, the gate:

| Test | Pins |
|---|---|
| Signed up holds | a rep's Signed up on a batch contact → the pointer is gone; the second rule leaves it at 91 days; another partner's batch → `already_assigned`; door B gives another rep `held`; reclaimed to the house, then batched → `won` |
| The rep who signed | A's open call; the contact returned from A **by expiry**, then claimed by B (B has not sold); A's Signed up → the contact is A's |
| A take-back before the call | the contact reclaimed from A, later assigned to A again, a new call, returned by expiry, then A's Signed up → moves to A (the take-back was before A last held it) |
| The first sale stands | B's card Signed up, then A's on A's open call → `sold`, B keeps it; a website sale while B held it (the nightly records B), then B reclaimed, then A's Signed up → `sold`; the same, then **B's own** Signed up on B's open call → recorded, not `sold`, and the house keeps it; A's Signed up, a website sale the same day (the nightly records A), A's undo, then a former holder B's Signed up → `sold` |
| No pull-back | after a `reclaim` of an ended partner, a `reclaim` of a partner **still active**, a suppression, or a DNC-file hit (the house holds it), the former holder's Signed up → recorded, the contact stays with the house; after a return by expiry, the former holder's Signed up → the contact moves to them; a `reclaim` of A still active, then the contact put on NMC's own sheet, then A's Signed up on the open call → stays on the sheet (answer 7); A deactivated but **not** reclaimed, the contact returned by expiry, A's Signed up → stays with the house; the same with B holding it → returns to the house; the contact returned by expiry, then a DNC-file hit (no custody event), the former holder's Signed up → stays with the house; with another rep B holding and the number blocked by B's "don't call me again" (a live row, no custody change), A's Signed up → the contact returns to the house |
| Lock order | a blocker holding A's partner row `for update` while A's Signed up waits → the Signed up waits on the partner, before any contact lock |
| Undo | a Signed up undone → stays with the rep who signed; returned by the second rule after 90 days |
| The website's sale | a won contact held by a rep in a batch → stays, pointer gone; one on NMC's sheet → the house; **a won contact whose batch expired the same night, through `run_nightly` → stays with the rep**; a contact sold by an unmatched sale with an expired batch → the won step clears the pointer |
| Re-read after the lock, the gate | a Signed up that leaves the row unchanged (the house holds it; the signer may not move it) holds the contact through `calls._after_lock` while an operator batch waits on it → `won`; a former holder's Wrong number on their open call on a house contact, held the same way → `closed` |
| A website sale is closed | a won contact the won step keeps with its rep → 5b Closed, *a customer*; `open_call` → `closed` |
| Re-read after the lock | a blocker holds the contact while the expiry step waits, and: a batch-expired contact moved to Got a callback; a 91-day door B claim given the holder's card Signed up (no pointer, the row unchanged); a 91-day door B claim given a card Follow up → none returned |
| Re-read after the lock, the batch rule and sold | an expired-batch contact whose holder may not move it (inactive) records a card Signed up, holding the contact while the expiry step waits → not returned |
| Got a callback / Follow up | each list × each rule (a batch expired; a claim 91 days old) → not returned; paused there → not returned; closed after, or blocked after ("don't call me again") → returned; on NMC's own sheet → not exempt |
| Resting goes back | an NMC contact resting at day 90 → returned; another rep claims it through door B and sees *resting* |
| Batches | Closed by Wrong number, Not interested, or the rep → `closed`; Closed as a customer → `won`; resting → `resting`; rest over → given out; a blocked contact with a state row → `voice_suppressed`; a contact resting under the partner's 1-month rest but not the default 3 → given out to that partner |
| Ask again | 50 ordinary NMC contacts held plus 1 sold, 1 in Got a callback and 1 in Follow up → allowed; counting any one of the three gives 51 → `not_yet` |
| The moment | Get more numbers at `at` gives out a contact whose rest ends on `at`'s day, though the clock is earlier |
| The changed frozen tests | green with §5's changes |

## 8. Done means

The gate green, every other frozen test unchanged and green; `make test`, `make e2e`,
`make lint` clean; mutation checks each failing a test — return a sold rep's contact in
the won step; skip the move on a former holder's Signed up; let a second Signed up take
a sold contact; move on an ended partner's or a blocked contact's Signed up; move after a
reclaim of an active partner; read sold only in the gate's candidate select; write
`web_seller` only with no Signed up; check only the latest custody event instead of
any take-back since the call opened; read the 5b state in the gate's candidate select;
read only a Signed up as a customer in 5b; drop the active-partner check; drop the
`dnc_registry` check; drop the batch rule's sold re-read; leave a
not-moved sold contact with another rep; infer the website seller from the current
holder; take the partner lock after the contact; let either
expiry rule return a sold contact; drop the re-read after the lock; drop the Got a
callback / Follow up exception from either rule; keep a blocked follow-up exempt; keep a
resting contact past day 90; give out a closed or resting contact; refuse a rest-over
contact; read the defaults instead of the partner's settings; count sold or follow-up
contacts toward `max_held`; read the clock instead of `at`. Migration `0019` applied to
`mailengine_dev`.

## 9. For the operator

| # | Question | Answer |
|---|---|---|
| 1 | How does contact-engine know a sale and its seller? | **Answered 2026-09-30: Signed up, or the holder** (§4.1). Offered that (recommended), "Only Signed up", or "Only the website". |
| 2 | 9.3: a former holder's Signed up while another rep holds the contact | **Answered 2026-09-30: the rep who signed.** Offered that (recommended), "The holder keeps it", or "An admin decides". |
| 3 | 9.0: a resting contact at day 90 | **Answered 2026-09-30: it goes back, state and all.** Offered that (recommended), "It stays until the rest ends", or "It stays until restarted or closed". |
| 4 | 9.12: what a batch may give out again | **Answered 2026-09-30: all but Closed and resting.** Offered that (recommended), "Only fresh ones", or "Everything not Closed". |
| 5 | 9.14: replacing a wrong number | **Answered 2026-09-30: no replace; add it through door B.** Offered that (recommended), "Replace if free", or "Replace and merge". |
| 7 | After NMC takes a contact back from rep A while A has a call open on it, can A's Signed up on that call pull it back? | **Answered 2026-09-30: no, never** — a take-back after the call opened always wins; the Signed up is recorded. Offered that (recommended) or "Yes, unless blocked". |
| 6 | Which contacts count toward Get more numbers' 50? | **Answered 2026-09-30: not sold, not callback** — sold, Got a callback and Follow up contacts do not count. Offered that (recommended), "Only sold excluded", or "Everything counts". |

## 10. The migration, `0019.web-seller.sql`

```sql
alter table contact_state add column web_seller uuid;
```

No foreign key: partners are never deleted in production, and the frozen test helper
`_rm_partner` deletes partners at the end of a test while their contacts keep their
state rows.

Written once by the nightly's won step (§4.1); read with the Signed ups to give the
seller.

## 11. Proposed changes to the decision record and documents

| Item | Proposal |
|---|---|
| 6.5 | Add: a sale is a rep's Signed up or the website's; the seller is the rep who signed, else the holder when the website's sale arrives (answers 1, 2) |
| 9.0, 9.1, 9.2, 9.3, 9.12, 9.14 | Settled as §1 says (answers 1 to 5) |
| 6.2 | Add: sold, Got a callback and Follow up contacts do not count toward the ask-again point (answer 6) |

## 12. Safety properties

Each revision is checked against these before review.

1. A sold contact is never returned to the pool from its seller by expiry, the won step,
   or a batch, never given to another rep, never taken by a second Signed up, and never
   left with a rep who did not sell it.
2. NMC's contact held by a rep, in Got a callback or Follow up and not closed, is never
   returned by expiry.
3. A batch never gives out a closed or resting contact.
4. A Signed up never moves a contact that was taken from its rep after the call opened.
5. A batch never gives out a contact sold by a Signed up, even one recorded while the
   batch waited. (A website sale ingested without the contact's lock can still land
   after the re-read, as today; the won step then keeps it with its holder.)
