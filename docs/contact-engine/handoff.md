# contact-engine Upgrade — Hand-off to the contact-engine session

**Date:** 2026-09-29
**From:** the NeverMissCall session that planned the Sales Partner Dialer.
**To:** the contact-engine session, in the marketing project (`marketing/mail-engine`).
**Why:** operator, 2026-09-29, asked "Should we let contact-engine AI work on the design
for its upgrade?": "Yes." The contact-engine session knows the code and its history.
The NeverMissCall session read it from outside and changed nothing in it.

---

## 1. What to read, in this order

Paths are from the NeverMissCall repository's root.

| # | Document | What it is |
|---|---|---|
| 1 | `docs/active/contact-engine/00-purpose.md` | The big picture: the six jobs contact-engine does |
| 2 | `docs/active/contact-engine/00-interface.md` | What it exposes, at a high level. Not the contract. |
| 3 | `docs/active/sales-partner-dialer-decisions.md` | What the operator has decided (§1–8), what is not settled (§9), what was withdrawn (§10). The only source of decisions. |
| 4 | `docs/active/contact-engine/00-overview.md` | The seven parts, what each needs, and how each is done |
| 5 | `docs/active/contact-engine/00-foundation.md` | Part 0. Approved by the operator. Not built. |

Do not read `docs/archive/sales-partner-dialer-2026-09/` as a source. It is history,
and its documents conflict with each other.

## 2. What is handed over

| Work | State |
|---|---|
| Part 0, Foundation | Designed and approved. To be built. Its statements about the code were checked at commit `4b6d5b9`; check them again if `main` has moved. |
| Parts 1 to 6 | To be designed and built, one at a time, in the order of the overview |
| Hosting on Render | After part 6 |

## 3. What the operator asked for, in how the work is done

| Rule | Decision |
|---|---|
| One part at a time: design, the operator's questions, a fresh review, approval, then the next | 2.2, overview §3 |
| Questions one at a time, with options and a recommendation | 2.5 |
| Nothing is added before a part needs it | 2.8 |
| A gap that exists only while the upgrade is being built is not a question for the operator | 2.9 |
| A known limit over something that works most of the time | 2.6 |
| The operator's words: DNC file, DNC check, "don't call me again", adding a contact, a sale, marking a sale, a blocked request | The record's header |

## 4. To reconcile first: the decision of 2026-08-06

contact-engine built partner-sourced numbers and cut them the same day
(`docs/decisions.md:1061-1165`; migrations `0011` and `0012`). The operator has now
decided that a rep adds their own numbers (decisions 3.1 to 3.3) and confirmed the
reversal of contact-engine's stated non-goals.

| The decision of 08-06 | The decisions of 09-27 to 09-29 |
|---|---|
| A rep's word that a business gave permission is no basis to call a number on a DNC file; a signed writing is required | Agrees. Every number a rep adds is checked like any other (4.1). Calling past a DNC block is put off and not built (§10). |
| Waiving the check for one category risks the safe harbor for the whole program | Agrees. Nothing is waived. |
| A referral is a name and a town, never a number; the operator assigns by id | **Differs.** The rep adds the number. It is checked before it can be called. |
| The marker of who sourced a contact was a column, never cleared automatically | Not decided. How "NMC's" and "a rep's own" are told apart is part 1's design. |

Part 1 should say plainly which parts of the 08-06 decision stand and which the new
decisions replace, and put any conflict to the operator.

## 5. The largest open conflict

Record §9.0. NMC's contacts go back after 90 days unless they are in Got a callback or
Follow up (6.3). A contact that reached its calling limit rests, 3 months by default,
and then the rep restarts or closes it (7.2). A resting contact goes back at day 90,
before its rest ends. The operator has not been asked. It belongs to parts 4 and 5.

## 6. What the NeverMissCall session learned the hard way

| Mistake | What to do instead |
|---|---|
| Statements about the code written from memory. The first part 0 failed its review on them. | Check each against the code; cite file and line |
| Rules and a table added before any part needed them | Nothing early |
| Decisions reconstructed from a pile of documents | One record. When a decision changes, change the record and move the old line to its §10. |
| Working code replaced without reading it | Read what is being replaced first |

## 7. What stays with the NeverMissCall repository

| Work | When |
|---|---|
| The decision record | Kept here. The contact-engine session proposes changes; the operator approves them. |
| The contract between the dialer and contact-engine | contact-engine's `06a-the-api.md` with `06b-running-it.md`; linked from here (record 8.9) |
| The dialer's backend, the website's pages, the app | After contact-engine. The dialer waits (2.1). |
| The several-days check on the Samsung S10 | One call on or after 2026-10-01 |
