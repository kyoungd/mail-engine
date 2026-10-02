# contact-engine — What It Does

**Date:** 2026-09-29
**What this is:** the big picture. The six jobs contact-engine does, in plain words.
**What it is not:** a design. Each job is designed in its own part. This page adds no
decision: every rule here points to its number in
[the decision record](../sales-partner-dialer-decisions.md).

---

## 1. In one sentence

contact-engine holds every business a rep might call, and answers one question for the
dialer: **who may this rep call right now, and what do we know about them?**

```
The app  ──►  the dialer's backend  ──►  contact-engine
(screens)     (who is the rep?)          (everything about a contact)
```

The website asks contact-engine too, for its own pages and for the admin. Nobody else
does. Reps never log in to it (1.8), and it sends no message itself (1.7).

## 2. The six jobs

| # | Job | The question it answers |
|---|---|---|
| 1 | **Intake** | How did this number get in, and whose is it? |
| 2 | **DNC filtering** | Is this number clean to call? |
| 3 | **Time zone** | Where is the business, and is it a good hour there? |
| 4 | **Assignment** | Which rep holds this number, and for how long? |
| 5 | **Calling rule** | What happened on each call, and when is the next one due? |
| 6 | **Context support** | What does the dialer need to know, right now, to show the rep? |

Underneath them is part 0, the clean-up: the mail code and the web pages come out, so
contact-engine carries these six jobs and nothing else.

---

## 3. Each job

### Job 1. Intake

| | |
|---|---|
| **Does** | Takes numbers in, from two doors: a list NMC loads, and a number a rep adds |
| **Keeps** | The business, its number, whose contact it is (NMC's or the rep's own), and how the rep got it |
| **Rules** | A rep can add one number, or a file of them (3.1). How they got it is recorded, with the confirmation they gave (3.2). A number that is already NMC's and held by nobody stays NMC's, and the rep holds it (3.3). One number, one contact (6.1). |
| **Exists today** | Loading NMC's lists. No door for a rep. |
| **Open** | What expanding NMC's list covers (9.6) |

### Job 2. DNC filtering

| | |
|---|---|
| **Does** | Checks every number against the DNC file for its area code, and against every "don't call me again" |
| **Keeps** | The result, the day of the check, and which DNC file it was checked against |
| **Rules** | Every number is checked, NMC's and a rep's alike; unchecked, failed, or not covered means no call (4.1). A check is good through day 31 (4.2). "Don't call me again" blocks the number for every rep at once (4.3); an admin lifts it by hand, with a written reason (4.4). DNC files stay as files, uploaded as today (4.5). |
| **Exists today** | Most of it: the check, the 21-day recheck, the 31-day limit, the uploads |
| **Open** | 9.16 |

### Job 3. Time zone

| | |
|---|---|
| **Does** | Works out where the business is, and whether now is inside the calling window there |
| **Keeps** | Every zone the business could be in, and who set it |
| **Rules** | Area code first, the state as a cross-check; in doubt, the hours safe in every possible zone (5.1). No zone known: the rep says where the business is before the first call (5.2). The window is 9 AM to 7 PM, NMC's, a setting in code (5.3). Outside it is a warning; the rep confirms and the confirmation is recorded (5.4). The holding rep or an admin sets the zone (5.5). |
| **Exists today** | Nothing |
| **Open** | 9.16 |

### Job 4. Assignment

| | |
|---|---|
| **Does** | Decides which rep holds which number, gives out more numbers when a rep asks, takes them back, and handles a sale |
| **Keeps** | Who holds each contact, since when, and the history of who held it before |
| **Rules** | One rep per number (6.1). Get more numbers: the rep picks a region; the batch is drawn in proportion from its area codes, at random (6.2). NMC's contacts go back after 90 days, counted for each contact, never one the rep is working; a rep's own are never taken back (6.3). A new holder sees the history of NMC's contacts, not of a rep's own (6.4). Once sold, a business is out of reach of everyone but the rep who sold it (6.5). |
| **Exists today** | Holding, batches, and taking back a whole batch at 90 days |
| **Open** | None (settled by parts 4 and 5c) |

### Job 5. Calling rule

| | |
|---|---|
| **Does** | Records every call, outcome, and memo; decides when a contact is due, when its sequence ends, and how long it rests |
| **Keeps** | The record of calls and memos, never edited; each rep's four settings; each contact's counts and dates |
| **Rules** | Four settings with fixed choices (7.1). A sequence ends at whichever limit comes first, then the contact rests (7.2). The rep can change the settings (7.3). Stopping at the limit is automatic (7.4). Every contact a rep holds is in one list (7.5, 7.11). The server's clock times every call (7.6), and works out whether a call happened (7.8). A request that succeeded is never done twice (7.7). A rep can undo their own Signed up or Wrong number within 24 hours (7.10). |
| **Exists today** | A note, an outcome, and a next action can be recorded. No call by a rep, and no rule. |
| **Open** | None (settled by parts 5b and 5c) |

### Job 6. Context support

| | |
|---|---|
| **Does** | Answers the dialer and the website. It is the only way in from outside. |
| **Gives** | The rep's lists and cards; the answer to "may I call this one now?"; the list of known callers for the phone; what the admin needs to keep it running |
| **Rules** | The dialer asks directly (1.4). contact-engine sends no message; the website raises every alert from what contact-engine reports (1.7). |
| **Exists today** | Nothing reachable from outside |
| **Open** | None (settled by part 6b) |
| **More** | [What it exposes](00-interface.md) |

---

## 4. The life of one contact

| Step | What happens | Job |
|---|---|---|
| 1 | It gets in: from NMC's list, or a rep adds it | 1 |
| 2 | It is checked against the DNC file and "don't call me again" | 2 |
| 3 | Its time zone is worked out | 3 |
| 4 | A rep comes to hold it: they added it, or it came in a batch | 4 |
| 5 | The rep calls. Each call is allowed or blocked, then recorded with its outcome. | 5, 6 |
| 6 | It comes due again, or its sequence ends and it rests | 5 |
| 7 | It ends: a sale, "don't call me again", a wrong number, closed by the rep, or taken back | 4, 5 |

## 5. What contact-engine is not

| Not | Who is |
|---|---|
| A mail system | Nobody. The mail code is removed on the branch (2.3). |
| The place a rep is added or removed | The website's roster (1.8) |
| The sender of any email, report, or alert | The website (1.7) |
| The judge of commissions | The website |
| Something a rep logs in to | The rep uses the app and the website (1.8) |
