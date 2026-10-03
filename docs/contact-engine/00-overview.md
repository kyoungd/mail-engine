# contact-engine Upgrade — Overview

**Status:** Structure agreed by the operator, 2026-09-29. Part 0 is approved. Parts 1 to
6 are handed to the contact-engine session ([hand-off](handoff.md)). Nothing is built.
**Decisions:** [the decision record](../sales-partner-dialer-decisions.md). This
overview holds the structure only.
**Where this lives:** this overview and part 0 were written in the NeverMissCall
repository. Parts 1 to 6 are written in `marketing/mail-engine` by the contact-engine
session (decision 2.4).

---

## 1. The parts

| # | Part | Its job | Exists today |
|---|---|---|---|
| 0 | **Foundation** | The branch, the removals, and what the removals need | — |
| 1 | **Intake** | How a number gets in, and what is known about it | Loading a list (`service/contacts.py:84`) |
| 2 | **DNC filtering** | Is the number clean? The DNC check. "Don't call me again". | Most of it |
| 3 | **Time zone** | Where is the business, and when may it be called? | Nothing (searched) |
| 4 | **Assignment** | Who holds the number, for how long, and what happens at a sale | Holding and batches |
| 5 | **Calling rule** | The number's state; the record of every call and memo | Notes, an outcome, and a next action can be recorded (`service/ingestion.py:118`, `service/contacts.py:526, 543`). No call by a rep, and no rule. |
| 6 | **Context support** | Answering the dialer and the website, including operations | Nothing reachable from outside |
| 7 | **Vouching** | A rep's vouch lets a call past a DNC status that is not clear; lists hold only what may be called | — |
| — | Hosting | On Render, after part 6 | — |

## 2. What each part needs

| Part | Needs |
|---|---|
| 1 | 0 |
| 2 | 1 |
| 3 | 1 |
| 4 | 2 |
| 5 | 3 and 4 |
| 6 | All of them. Built last, and thinnest. |
| 7 | 2, 5 and 6 |

Parts 2 and 3 do not need each other.

## 3. How each part is done

One at a time, in order.

1. **Its design:** its job, its edges with the other parts, its rules, its tests, and
   what "done" means. Short. A part that runs past a few pages is probably doing two
   jobs.
2. **Checked against the code.** Every statement the design makes about existing code is
   checked against the code before the operator sees it, and carries the file and line.
   A statement that could not be checked is marked so.
3. **Nothing early.** A rule, a table, or a function is added in the part that first
   needs it (decision 2.8).
4. The operator's questions, one at a time. A gap that exists only while the upgrade is
   being built is not one of them (decision 2.9).
5. A review of that part alone, by a fresh reader. If it does not pass, the design is
   corrected and reviewed again.
6. The operator's approval.
7. Then the next part.

## 4. The documents

| Document | State |
|---|---|
| [The decision record](../sales-partner-dialer-decisions.md) | The source of decisions |
| [`00-purpose.md`](00-purpose.md) | The big picture: the six jobs |
| [`00-interface.md`](00-interface.md) | What is exposed, at a high level |
| [`00-foundation.md`](00-foundation.md) | Approved 2026-09-29 |
| [`01-intake.md`](01-intake.md) | Part 1. Approved and built 2026-09-30. |
| [`02-dnc-filtering.md`](02-dnc-filtering.md) | Part 2. Approved 2026-09-30 at revision 18 (the simplified design: one record of "don't call me again"). **Built** 2026-09-30. |
| [`03-time-zone.md`](03-time-zone.md) | Part 3. Approved 2026-09-30 at revision 6. **Built** 2026-09-30. |
| [`04-assignment.md`](04-assignment.md) | Part 4, holding and getting numbers; the sale moved to part 5 (its answer 1). Approved 2026-09-30 at revision 6. **Built** 2026-09-30. |
| [`05a-call-record.md`](05a-call-record.md) | Part 5a, the call record. Part 5 is cut in three: 5a the call record, 5b the rule, 5c the sale and the 90 days (its answer 1). Approved 2026-09-30 at revision 5. **Built** 2026-09-30. |
| [`05b-the-rule.md`](05b-the-rule.md) | Part 5b, the rule. Approved 2026-09-30 at revision 6. **Built** 2026-09-30. |
| [`05c-sale-and-90-days.md`](05c-sale-and-90-days.md) | Part 5c, the sale and the 90 days. Approved 2026-09-30 at revision 7. **Built** 2026-10-01. |
| [`06a-the-api.md`](06a-the-api.md) | Part 6a, the API — the contract between the dialer, the website and contact-engine. Part 6 is cut in two: 6a the API, 6b running it (its answer 1). Approved 2026-10-01 at revision 6. **Built** 2026-10-01. |
| [`06b-running-it.md`](06b-running-it.md) | Part 6b, running it — the alerts and switch-on gates (9.5), when contact-engine cannot be reached (9.17), no stand-in (9.7), and part 2's recheck by the list's age. Approved 2026-10-01 at revision 8. **Built** 2026-10-01. Part 6 is complete. |
| [`07-vouching.md`](07-vouching.md) | Part 7, vouching and callable-only lists, requested by the dialer 10-02. Approved 2026-10-02 at revision 2. **Built** 2026-10-02. |
| [`handoff.md`](handoff.md) | The note that hands them over |
