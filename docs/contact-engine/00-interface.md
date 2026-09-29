# contact-engine — What It Exposes

**Date:** 2026-09-29
**What this is:** a high-level list of the information contact-engine gives out and the
actions it accepts. For orientation.
**What it is not:** the contract. No path, no field, no status code is settled here.
Part 6 designs those. A line marked *drafted* comes from earlier drafts and is not a
decision; a line with a number points to
[the decision record](../sales-partner-dialer-decisions.md).

---

## 1. Who asks

| Asker | For whom | Asks about |
|---|---|---|
| The dialer's backend | A rep, on the app | Their lists, cards, calls, memos |
| The website | A rep, on Call Control | Adding numbers, their settings, their lists |
| The website | An admin | Keeping it running |
| The website | Itself | The state of the jobs, to raise alerts |

contact-engine trusts the asker to have checked who the rep or admin is. It does not
check again. A rep sees only the contacts they hold (*drafted*).

## 2. What is exposed, by job

### Job 1. Intake

| Exposed | Kind |
|---|---|
| Add one contact, with how the rep got it and their confirmation (3.1, 3.2) | Action |
| Add many, from a file; a result for each row (3.1) | Action |
| Edit a contact's details | Action, *drafted* |
| Load one of NMC's lists | Command line only. Not exposed. |

### Job 2. DNC filtering

| Exposed | Kind |
|---|---|
| Whether a contact may be called, and if not, why: never checked, on a DNC file, check too old, area code not covered (4.1, 4.2, 4.6) | Information, on every card |
| "Don't call me again", from the rep (4.3) | Action |
| Undo it, within 24 hours, with a reason (4.4) | Action |
| "Don't call me again" that reached NMC by email or phone | Admin action, *drafted* |
| The age of each area code's DNC file | Information, for alerts |

### Job 3. Time zone

| Exposed | Kind |
|---|---|
| Every zone the business could be in (5.1) | Information, on every card |
| Fill in a missing zone, or narrow several to one (5.2, 5.5) | Action |
| Set any zone | Admin action (5.5) |
| The calling window | Admin setting (5.3) |
| "It is outside calling hours there", with the local times, and the rep's confirmation (5.4) | Part of opening a call |

### Job 4. Assignment

| Exposed | Kind |
|---|---|
| The regions a rep can choose from (6.2) | Information |
| Get more numbers, for a region (6.2) | Action |
| Give a contact up | Action, *drafted* |
| The day one of NMC's contacts goes back (6.3) | Information, on the card |
| Mark a sale (6.5) | Action |
| Take contacts back from a rep | Admin action, *drafted* |
| The batch size, the point at which a rep may ask again, the regions (6.2) | Admin settings |
| A sale the rep did not start from the app | **Not settled** (9.2) |

### Job 5. Calling rule

| Exposed | Kind |
|---|---|
| The rep's four settings: read, save (7.1, 7.3) | Information and action |
| **May I call this contact now?** Yes with the number to dial, or no with the reason | The central question. Asked before every call. |
| The outcome of a call, with an optional memo | Action |
| Correct the last outcome | Action, *drafted* |
| Move a contact to Got a callback, Follow up, or Closed | Action, *drafted* |
| Restart a sequence after its rest (7.2) | Action |
| Replace a wrong number | Action, *drafted* |
| Undo a Signed up or a Wrong number, within 24 hours (7.10) | Action |
| Add a memo; edit one, the earlier text kept | Action, *drafted* |
| A call received from a known contact: record it, list them, and the rep's choice of spoke, missed and call back, or dismiss (8.3) | Action and information |
| Calls with no outcome: list them, clear one (7.9) | Admin |

### Job 6. Context support

| Exposed | Kind |
|---|---|
| A count for every list (7.5) | Information |
| The contacts in a list | Information |
| The next contact to call in a list | Information |
| Search, among the rep's own contacts | Information |
| One contact's card (§3) | Information |
| A contact's call history, and its memos | Information |
| The list of known callers, for the phone to recognize who is calling (8.3, 8.4) | Information |
| Make a rep known; say a rep is deactivated (1.8) | Action |
| The log: calling-hours confirmations, undone "don't call me again", changes of zone, contacts taken back | Admin, *drafted* |
| The state: the last run of each job and whether it succeeded, the age of each DNC file, calls open too long, checks near 31 days (1.7) | Information, for alerts |

## 3. The card

What contact-engine says whenever it describes a contact to a rep. *Drafted*, as a list
of what is on it and not of fields.

| On the card | From job |
|---|---|
| The business, the contact's name and role, the number, the city, the state, the trade | 1 |
| Whose it is: NMC's or the rep's own | 1 |
| May it be called now, and if not, why, and until when | 2, 3, 5 |
| Every zone it could be in | 3 |
| The day it goes back, if it is NMC's | 4 |
| Which list it is in | 5 |
| The latest memo; the last call and its outcome | 5 |
| Calls made against the limit; voicemails left against the limit | 5 |
| When it is next due, or until when it rests | 5 |
| Which of the rep's own actions can still be undone | 2, 5 |

## 4. Ground rules

| Rule | State |
|---|---|
| Only the dialer's backend and the website ask, each with a key | *Drafted* |
| contact-engine's clock times everything; the phone's time is shown and decides nothing | 7.6 |
| A request that succeeded is never done twice; a blocked request is asked again | 7.7 |
| A blocked request changes nothing about the contact | 7.7 |
| A rep sees only what they hold; anything else looks as if it does not exist | *Drafted* |
| What happens when contact-engine cannot be reached | **Not settled** (9.17) |
| Whether the dialer is built against a stand-in | **Not settled** (9.7) |

## 5. Not exposed

| | Why |
|---|---|
| DNC files, and any list of numbers on them | They stay inside contact-engine (4.5) |
| Another rep's contacts, or who holds a number | One rep per number; a rep is told only that it is held (6.1) |
| The history of a rep's own contact, to a later holder | 6.4 |
| Any way for a rep to log in | 1.8 |
| Any export to a sheet for a rep on the app | 6.6 |
