# PRD — contact-engine

*Internal tooling for NeverMissCall. Version 2.0, September 2026. Replaces the Direct
Mail AI (Mail Engine) PRD, v1.0, July 2026.*
*The name changed; the folders, the repository (`kyoungd/mail-engine`), and the
databases keep their old names. Work happens on the `contact-engine` branch; production
stays on `main` until the upgrade is complete.*

**Sources.** This PRD is the consolidated statement of what and why. It adds no
decision. Every rule points to its number in the decision record,
`nvermisscall/docs/active/sales-partner-dialer-decisions.md` (the only source of
decisions). The companions carry the detail:

| Document | What it is |
|---|---|
| [`contact-engine/00-purpose.md`](contact-engine/00-purpose.md) | The six jobs, in plain words |
| [`contact-engine/00-interface.md`](contact-engine/00-interface.md) | What is exposed, at a high level. Not the contract. |
| [`contact-engine/00-overview.md`](contact-engine/00-overview.md) | The parts, what each needs, how each is done |
| [`contact-engine/00-foundation.md`](contact-engine/00-foundation.md) | Part 0. Approved 2026-09-29. |
| [`contact-engine/handoff.md`](contact-engine/handoff.md) | What was handed to this project |

---

## 1. Problem

NeverMissCall is adding a sales-partner dialer: reps call service businesses from an
Android app. Every such call has to be lawful and fair between reps: the number checked
against the DNC file for its area code and against every "don't call me again", placed
inside the calling hours where the business is, held by one rep only, and recorded. Reps
also bring their own numbers, which must pass the same checks. Today the contact data,
the DNC check, and the holding of batches live in mail-engine, which was built around
direct mail, is reachable from nowhere outside the operator's machine, and has no rule
for when a contact is called again.

## 2. Product thesis

One service holds every business a rep might call and answers one question for the
dialer: **who may this rep call right now, and what do we know about them?**

```
The app  ──►  the dialer's backend  ──►  contact-engine
(screens)     (who is the rep?)          (everything about a contact)
```

The app is thin and the server decides everything (1.6). contact-engine does every
contact service (1.2): intake, DNC filtering, time zone, assignment, the calling rule,
and answering the dialer and the website. It holds both NMC's contacts and each rep's
own, with their memos and call history (1.3). It sends no message of any kind (1.7) and
nobody logs in to it (1.8).

## 3. Goals

1. **No unlawful call.** A number that is unchecked, on a DNC file, checked too long
   ago, or not covered cannot be called (4.1, 4.2), unless the rep who holds it has
   vouched for it (4.12). "Don't call me again" blocks the
   number for every rep at once (4.3).
2. **Calls at the right hour.** The business's zone is known before the first call, and
   the rep is warned outside the calling window (5.1–5.4).
3. **One rep per number.** No two reps ever hold the same number (6.1); a sold business
   is out of reach of everyone but the rep who sold it (6.5).
4. **A calling rule the rep does not have to track.** The server says what is due, ends
   a sequence at its limit, and rests the contact (7.1–7.4).
5. **Every call recorded.** Timed by the server's clock (7.6), never recorded twice
   (7.7), kept per 8.8.

## 4. Non-goals

- **Not a mail system.** The mail code is removed on the branch (2.3).
- **Not a sender.** No email, report, alert, or SMS. The website composes and sends any
  report and raises every alert from what contact-engine reports (1.7).
- **Not a roster, and not something anyone logs in to.** A rep is added or removed on
  the website's roster; the dialer makes the rep known to contact-engine (1.8).
- **Not the judge of commissions.** The website is.
- **No export to a sheet for a rep on the app** (6.6). The export stays for the operator
  and for a rep not yet on the app.
- **No DNC files or numbers on them given out** (4.5).
- **No calling past a DNC block** except under the holding rep's vouch (4.12, turned on
  10-02); never past a "don't call me again".

## 5. Users

contact-engine has no human users of its own. It is asked by:

| Asker | For whom | Asks about |
|---|---|---|
| The dialer's backend (in `website/`) | A rep, on the app | Their lists, cards, calls, memos |
| The website | A rep, on Call Control | Adding numbers, their settings, their lists |
| The website | An admin | Keeping it running |
| The website | Itself | The state of the jobs, to raise alerts |

It trusts the asker to have checked who the rep or admin is (`00-interface.md` §1). The
operator also runs it from the command line and the console (`make console`), for
loading NMC's lists, DNC uploads, and the daily cycle.

## 6. Functional requirements

One requirement per job; each job is one part, designed and built in order (2.2).

**FR-1 Intake (part 1).** Numbers come in through two doors: a list NMC loads (command
line only), and a number a rep adds — one at a time in the app or on the website, or a
file on the website (3.1). How the rep got the number is recorded, with the
confirmation they gave (3.2). A number that is already NMC's and held by nobody stays
NMC's, and the rep holds it; a number another rep holds is refused (3.3, 6.1). One
number, one contact. Open: what expanding NMC's list covers (1.10, 9.6); how NMC's and
a rep's own are told apart, and which parts of the 2026-08-06 partner-sourcing decision
stand (`handoff.md` §4).

**FR-2 DNC filtering (part 2).** Every number, NMC's and a rep's alike, is checked
against the DNC file for its area code and against every "don't call me again".
Unchecked, failed, or not covered: no call (4.1). A rep can vouch for a contact they
hold — met in person, or they contacted me — and then call it past any of those, never
past a "don't call me again" (4.12, part 7). A check is good through day 31; day
32 is stale (4.2). "Don't call me again" blocks the number for every rep at once (4.3);
the rep who reported it can undo it within 24 hours with a written reason, with no
admin step (4.4). DNC files stay files, uploaded as today (4.5). The rep is told an area
code is not covered only after the check (4.6). Open: 9.8–9.11, 9.16.

**FR-3 Time zone (part 3).** No zone is assumed: area code first, the state as a
cross-check; when more than one zone is possible, the hours safe in every one (5.1). No
zone known: the rep says where the business is before the first call (5.2). The window
is 9 AM to 7 PM the business's time, the same for every rep, changeable by an admin
(5.3). Outside it is a warning; the rep confirms and the confirmation is recorded (5.4).
A holding rep can fill in or narrow a zone; an admin can set any (5.5). Open: 9.16.

**FR-4 Assignment (part 4).** One rep per number (6.1). Get more numbers: the rep picks
a region and nothing else; the batch is drawn in proportion from the region's area
codes, at random; batch size and the refill point are admin settings (6.2). NMC's
contacts go back after 90 days, counted per contact, never one in Got a callback or
Follow up; a rep's own are never taken back (6.3). A new holder sees the history of
NMC's contacts, not of a rep's own (6.4). Once sold, a business is out of reach of
everyone but the rep who sold it (6.5). Open: 9.0–9.3, 9.12, 9.13.

**FR-5 Calling rule (part 5).** Four settings per rep, fixed choices: voicemails 1/2/3
(default 2), calls 3/5/8 (default 5), days between calls 3/5/7 (default 3), rest
1/3/6 months (default 3) (7.1). A sequence ends at whichever limit comes first, then the
contact rests; after the rest the rep restarts or closes it (7.2). The rep changes the
settings on the website; the app only shows them (7.3). Stopping at the limit is
automatic; a pause is the rep's request (7.4). The lists: Calls received, Got a
callback, Follow up, Never called, All due retries, Waiting, Limit reached, Closed
(7.5, 7.11). The server's clock times every call (7.6) and works out whether a call
happened (7.8). A request that succeeded is never done twice; a success is remembered
for 90 days (7.7). A call with no outcome is cleared by an admin; nothing closes on a
timer (7.9). A rep can undo their own Signed up or Wrong number within 24 hours with a
written reason (7.10). The record of calls and memos is never edited. Open: 9.4, 9.14.

**FR-6 Context support (part 6).** The only way in from outside; built last and
thinnest. The dialer asks directly (1.4). It gives the rep's lists and counts, the
contact card, the next contact to call, search among the rep's own contacts, call
history and memos, and the answer to **"may I call this contact now?"** — yes with the
number to dial, or no with the reason. It gives the list of known callers so the phone
recognizes who is calling, and records calls received and the rep's choice for each
(8.3, 8.4). It accepts "make a rep known" and "a rep is deactivated" (1.8). For the
website it reports the state: the last run of each job and whether it succeeded, the
age of each DNC file, calls open too long, checks near 31 days (1.7). Paths, fields,
and status codes are part 6's design. Open: 9.5, 9.7, 9.17.

## 7. System requirements

- **SR-1** Postgres 15+. Events and the record of calls and memos are append-only. The
  existing tables are left alone on the branch (2.3); new tables arrive with the part
  that first needs them (2.8).
- **SR-2** A single typed service layer is the only write path; reads may use the
  read-only role.
- **SR-3** Dependency rule: `jobs` and the part-6 interface → `service` →
  `derivation`/`resolution` → `domain`. `service/` does not import `jobs/`.
- **SR-4** Every write is idempotent; a blocked request changes nothing about the
  contact (7.7).
- **SR-5** The export's compliance predicates (`service/assignment.py`) and the
  suppression and tombstone machinery are kept and remain the gate on any number
  reaching a rep.
- **SR-6** Hosted on Render (1.5), after part 6. Not deployed until the upgrade is
  complete (2.9). Only the production checkout runs cron.
- **SR-7** Records are kept per 8.8: "don't call me again" permanently; calls, with the
  check at the time and any calling-hours confirmation, 5 years; nothing deleted
  automatically in the first version.
- **SR-8** Nightly offsite backups.

## 8. Done means

Each part defines its own "done" in its design (overview §3). The upgrade is done when:

- Parts 0 to 6 are each designed, reviewed by a fresh reader, approved, and built.
- `make test` and `make lint` pass on the branch.
- The dialer's backend can ask every question in `00-interface.md` §2 and get an answer.
- No path exists by which a number that fails FR-2 is offered to a rep as callable.
- It runs on Render, and the branch replaces `main` in production.

No numeric success metric has been decided.

## 9. Risks

- **An unlawful call.** Mitigation: FR-2 is the gate on every call, for every source;
  unchecked means no call; the compliance predicates stay 🔴. The 31 days and the
  calling hours are to be verified against 16 CFR § 310.4 before building (9.16).
- **A wrong zone.** Mitigation: nothing assumed; the narrowest safe window when in
  doubt; the rep must say where before a first call (5.1, 5.2).
- **Two reps on one number.** Mitigation: one number, one contact, one rep (6.1).
- **A rep's own number leaking into another rep's batch.** Open (9.13).
- **Losing a working feature while removing mail.** Mitigation: every removal step in
  part 0 leaves the suite green; production stays on `main` (`00-foundation.md`).
- **Split disks on Render.** The DNC fetch job and the reader may not share a disk
  (9.11).

## 10. Dependencies

The website's roster and login (1.8, 1.9); the dialer's backend in `website/`; the
`nmc-dialer-app` repository (8.1); the FTC DNC download and upload flow as it runs
today (4.5); a Render account (1.5).

## 11. Milestones

In order, one at a time (2.2; overview §3): Part 0 Foundation → 1 Intake → 2 DNC
filtering → 3 Time zone → 4 Assignment → 5 Calling rule → 6 Context support → hosting
on Render. Each part is designed, checked against the code, put to the operator one
question at a time, reviewed by a fresh reader, and approved before the next begins.
The dialer waits for contact-engine (2.1). Part 7, vouching and callable-only lists, was
added 10-02 (4.12, 8.14).

## 12. Open questions

The not-settled list is the decision record's §9. Each waits for its part; none is
decided by this PRD. The largest is **9.0, the 90 days against the rest** (parts 4 and
5).
