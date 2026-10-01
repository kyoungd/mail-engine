# contact-engine Upgrade — Part 6b: Running it

**Status:** APPROVED by the operator, 2026-10-01, at revision 8 (offered "Approve now",
"One more review", or "Read it first"; chose approve now). **BUILT 2026-10-01:** under
an approved build plan and an approved test gate, run to RED first: `0021.daily-runs.sql`;
the thresholds in `config/params.py`; part 2's recheck by the list's age in
`jobs/dnc_refresh.py` (`_due`'s `tonight`, `Coverage.version_date`); `service/runs.py`
(`record_daily_run`, `status`); `jobs/nightly_cli.py` records each run it completes;
`db/session.ping`; `GET /v1/status` and `GET /health` in `web/api.py`; the nightly CLI's
unit test stubs the record. Gate `tests/acceptance/test_running_it.py` (one case added
with approval while it was being greened: a code with two old subscriptions, so
counting it twice fails). Of §8's mutations every one fails a test but two that no test
can see: dropping the "has a phone" filter (a contact with no phone never matches a
subscribed code) and the status read's read-only mode (it neither locks nor writes).
`make test` 828 passed; e2e, lint clean. `0021` applied to `mailengine_dev` only. Part 6 is cut
in two (6a answer 1): 6a is the API, built 2026-10-01; 6b is running it — the alerts
and the switch-on gates (9.5), when contact-engine cannot be reached (9.17), and
whether a stand-in is still needed (9.7). Like 6a, this document is part of **the
contract** between the dialer, the website and contact-engine (6a answer 2). History:
Revision 1 did not pass its review. Its list alert watched each area code's newest list,
but a contact stops being callable 31 days after *its own* list, and the scrub rechecks
by the age of the check, not of the list. So contacts could drain with no alert, after
a pause in uploads or when a list's working copy was missing. The rule also said nothing
about a queued item that is refused. Revision 2 adds a recheck by the list's age to part
2's scrub (answer 5), alerts on the harm itself (contacts that stop being callable
soon), completes §4.5, and applies the minor findings. Revision 2's review found the drain
closed and two gaps: §4.5 did not say which answers are refusals, so a wrong key could
empty every queue; and the alert's "same rule, factored into one place" meant rewriting
the call gate's own rule without saying so. Revision 3 defines a refusal, leaves the call
gate untouched — the alert has its own expression, pinned to `dnc_status` by a test —
and applies the minor findings. Revision 3's review found the same class again: its
refusals were named by status, and the API gives 404 for a wrong path and 400 for a
dialer's bad body, so a dialer mistake could still empty every queue; and the
`--daily-run` flag would have changed a frozen gate's pinned steps. Revision 4 removes
both causes: a queued item leaves the queue only on an answer **about the item**, named
by code, and everything else keeps it (§4.5.4); the nightly records every run it
completes, so the script does not change (§4.1). Revision 4's review found the rest
sound and the queue's claim still false: a dialer mistake inside an answer about the
item — a wrong contact id, an `X-Rep` naming another rep, a misspelled outcome — is a
refusal like any other, and no sorting of answers can tell them apart. Revision 5 drops
the claim for the one it can keep: nothing is lost unseen. Every refusal is shown to the
rep **and** reported to the operator, and a refused "don't call me again" is the
operator's to record (§4.5.4). Revision 5's review found that last promise unbuildable
— the report did not carry the phone, and no admin route turns an id into one — and
the property still too wide: a misaddressed item can succeed on the wrong contact.
Revision 6 states only what the contract can hold: a "don't call me again" the app
could not get recorded reaches the operator **with the phone the rep saw**, through the
website (1.7); a misaddressed item is a known limit, guarded by the dialer's own tests.
Revision 6's review found that "still queued a day after" had nobody to notice it: a
request on a phone that never comes back online reaches no server. Revision 7 bounds
the promise at what a server receives: each time the dialer's backend cannot get a
"don't call me again" recorded, the operator is alerted with its phone; a request still
on a phone that never comes back is 8.7's limit (§6). Revision 7 **passed** its review
(no blocking finding); its minor findings are applied here, in revision 8.
**Part of:** [the upgrade](00-overview.md). Decisions are in the decision record,
`nvermisscall/docs/active/sales-partner-dialer-decisions.md`, named here by number
("decision 1.7"); sections of this document are named "§4.1".
**Checked against:** the `contact-engine` branch at `cf3154b` (parts 0 to 6a built). A
statement about the code carries its file and line.

---

## 1. Its job

Let the operator know, through the website, when something has stopped that would
silently stop the reps; keep contacts callable while a newer DNC list exists; say what
the dialer does when contact-engine does not answer; and say what has to be proven
before the first real rep calls.

| Decision | What it asks | Here |
|---|---|---|
| 1.7 | contact-engine sends no message; the website raises every alert | §4.3: contact-engine names the alert; the website sends it |
| 9.5 | The switch-on gates and the alerts, drawn again for the API | §4.3, §4.7 |
| 9.17 | What the rep is told, and what the dialer does, when contact-engine cannot be reached | §4.5 |
| 9.7 | Whether a stand-in for contact-engine is still needed | §4.6 |
| 2.6, 2.7 | A known limit over something that works most of the time; no step that adds no real check | Throughout |

## 2. Its edges

| 6b does | 6b does not — who does |
|---|---|
| Record each daily run that finishes (§4.1) | Run it on a schedule — the production checkout's cron (cron policy, 2026-08-07); on Render, hosting |
| Recheck a contact whose list is old when a newer one exists (§4.2) | Change which list a code is scrubbed against, or the 31 days — part 2 |
| Name the alerts that hold now, in one read (§4.3) | Send them, decide how often, to whom — the website (1.7) |
| A health check that says the service and its database answer (§4.4) | Render's settings — hosting |
| The rule for when contact-engine does not answer (§4.5) | Carry it out — the dialer's backend and the app |
| The switch-on gates, as a list (§4.7) | Prove them — the operator, at hosting, with the website and the app built |

## 3. What exists, checked

| Fact | Where |
|---|---|
| The production daily run is `scripts/daily-run.sh`: pull, scrub, nightly, stopping at the first step that exits non-zero. It records no run of its own; the scrub's `dnc_runs` row is the only trace, and it is written whether or not the nightly then succeeds | `scripts/daily-run.sh:58-69`; `jobs/dnc_refresh.py:270`, `:300` |
| The pull and the scrub exit 0 when they skip: an upload that fails its checks, a code with no accepted list, a list whose working copy cannot be read | `jobs/dnc_pull.py:164-166`; `jobs/dnc_refresh.py:279-282`, `:286-292`, `:360-370` |
| The steps of `daily-run.sh` are pinned, exactly, by a frozen gate | `tests/acceptance/test_daily_run_steps.py:75-78` |
| Nothing on the nightly's path catches an exception; it exits non-zero on any failure. Without `MEDUSA_READONLY_URL` it runs without the customer feed | `jobs/nightly.py:15-34`; `jobs/nightly_cli.py:33-45` |
| A contact stops being callable (`check_too_old`) when its check is over 31 days old, **or** the list it was checked against is dated over 31 days ago | `service/dnc.py:134-144`; `config/params.py:39` |
| The scrub takes a contact only when its check is over 21 days old — it does not look at the list's date. A contact checked against a list already 12 days old is past 31 days on that list before it is due again | `jobs/dnc_refresh.py:80-96`; `config/params.py:20` |
| A call left without an outcome stays open until an admin clears it (7.9); the open calls are listed for the admin. Once cleared, an outcome on it is refused `no_call` | `service/calls.py` `clear_call`, `:211`; `service/reads.py` `open_calls` |
| A retried action with the same key is answered from memory for 90 days, scoped to the rep; a refusal or a 500 is not kept, so it is asked again. A retry that arrives while the first is still running waits for it on the key's lock, then replays it | 6a §4.3; `web/api.py` `_act` |
| A call is placed only after `POST /contacts/{id}/calls` succeeds; a second open by the same rep is refused `call_open` with the open call's id | 5a; `service/calls.py` `open_call` (`:135`), through `_check_open`, `:101-104` |
| Every request opens its own connection; there is no pool | `db/session.py` `request_connection`; 6a §6 |
| No route answers without a key today | `web/api.py` |

## 4. The design

### 4.1 The daily run's record

Migration `0021` adds `daily_runs`, one row per nightly that completes:
`jobs/nightly_cli.py`, after `run_nightly` returns, records it through
`service/runs.record_daily_run(at)`, with `at` its own clock (the outermost layer, 9.15).
`daily-run.sh` is not changed: it runs the nightly last and stops at the first step
that exits non-zero, so in production a row means the pull, the scrub and the nightly
all exited 0 — not that nothing was skipped; skips are caught by what they cause
(§4.3, `dnc_checks_expiring`). A run that breaks and a run that never starts look the
same — no row — and are one alert. A nightly run by hand also records a row: it is a
completed nightly, and a stopped scrub still shows as `dnc_checks_expiring`.

### 4.2 The recheck by the list's age (answer 5) — a change to part 2

`dnc_refresh_all` also takes a contact whose **linked list is dated more than
`DNC_RECHECK_DAYS` (21) ago, when the list its code would be scrubbed against tonight
is newer than the one it is linked to** — whatever the age of its check. Exactly:
*dated more than 21 days ago* is `version_date < (now() at time zone 'UTC')::date − 21`
— the database's clock and UTC date, as `LINK_FRESH_SQL` reads them; *newer* is a `version_date` strictly greater than the
linked list's — a list of the same date from another SAN holder is not newer. The
dates of tonight's lists come from `_coverage`, which already runs before `_due`
(`jobs/dnc_refresh.py:273-274`; `Coverage` gains the list's `version_date`, beside the
string `version` it holds today, `:239`) and is passed into it as a keyword-only, optional
argument, so the single-registry path and the frozen lock-race wrappers
(`tests/acceptance/test_lock_races.py:116`, `:147`) call it as today. Its *linked list* is read as
`dnc_status` and `LINK_FRESH_SQL` read it: accepted, of the contact's own area code,
with a date; a contact with no such list is taken by its check's age alone, as today. So a contact
checked during a pause in uploads is checked again once uploads resume, before its list
reaches 31 days; and while no newer list exists, nothing is rechecked in vain. The 21
days, the 31 days, the order (rep-held first), and which list a code is scrubbed
against are unchanged. It only adds rechecks; it never removes one, and a recheck goes
through the same `_apply` as today. 🔴: it is the compliance area (`CLAUDE.md`), so it is
in the build plan's explicit approval.

### 4.3 The alerts (9.5, 1.7)

`GET /v1/status` — **the website's key only**. It is not under `/admin`: 6a's admin
routes need an `X-Admin`, and a scheduled read names no admin (2.7). A read (6a §4.8): one REPEATABLE READ, READ ONLY transaction.
It answers the facts and the alerts that hold **now**, worked out by
`service/runs.status(at)`; the thresholds are in `config/params.py`:

```json
{
  "daily_run": {"last_finished_at": "…"},
  "scrub": {"last_started_at": "…"},
  "dnc_checks_expiring": {"held": 0, "pool": 0, "never_checked": 0,
                          "by_area_code": {"818": {"held": 0, "pool": 0,
                                                   "never_checked": 0}}},
  "calls_open_over_24h": 0,
  "alerts": [{"code": "…", "detail": {}}]
}
```

| Alert | Holds when | Why |
|---|---|---|
| `daily_run_missing` | No daily run has finished in the last `DAILY_RUN_ALERT_HOURS` (26) — a run exactly 26 hours old still counts | The scrub, the customer feed and the expiry have stopped. One alert covers a run that broke and a run that never started |
| `dnc_checks_expiring` | Either (a) a contact in a subscribed area code, with a phone, not a seed, not blocked and not on the DNC file, that has been checked, stops being callable within `DNC_EXPIRY_ALERT_DAYS` (7) — or already has. With `t = at + 7 days`, that is `dnc_status`'s two tests at `t`: `dnc_checked_at < t − 31 days`, or its list's `version_date < (UTC date of t) − 31`. Its list counts only as `dnc_status` reads it — accepted, of the contact's own area code, with a date; a contact linked otherwise is `not_checked` and outside (a). Or (b): such a contact in a subscribed code was never checked, and the later of its coming in (`created_at`, or its latest `intake_rep.added_at`, as `dnc_status` reads it) and its code's **earliest** subscription is more than `NEVER_CHECKED_ALERT_HOURS` (48) ago. A code is subscribed once however many SAN holders subscribe it (`dnc_subscriptions` has a row per holder, `0013:24-25`); a contact is counted once. A contact checked but linked to a list `dnc_status` does not count is `not_checked` and in neither (a) nor (b) — deliberately: a list's status never changes once recorded (`0013:64`), so none exists. Detail: (a) counted held (any partner's, `owner_id` not the house — export partners included) and pool (the house's), (b) as `never_checked`, and each by area code | The harm itself: contacts the reps — or Get more numbers — are about to lose, or never had. It holds whatever the cause: uploads stopped, a working copy missing, a code with no list, a scrub that stopped. With daily lists and §4.2, it holds for none |
| `call_left_open` | A call has been open more than `CALL_OPEN_ALERT_HOURS` (24). Detail: how many | 7.9: only an admin clears it, and nobody else can call the contact while it is open |

`dnc_checks_expiring` is worked out by its own SQL in `service/runs.py`. The call gate,
`dnc_status`, is **not** changed: the alert can only say too much or too little, never
let a call through, and a test pins that the two agree on every case (§7). (A third
reading of freshness, the assignment gate's `LINK_FRESH_SQL`, also stays as it is.)

An alert is a code and its detail; the website composes the message (1.7). `scrub` is
a fact, not an alert: the start of the newest full scrub (`dnc_runs`, not limited), so
a nightly run by hand after a failed scrub is still visible.

The website reads the status on its own schedule and sends what it finds (1.7). When
the read itself fails — contact-engine down, or answering 5xx — the website raises its
own alert, `contact_engine_unreachable`; contact-engine cannot report its own absence.
How often the website reads, and whether it repeats an alert, is the website's.

### 4.4 Health

`GET /health` — no key, the one route without one; it answers `{"ok": true}` when a
`select 1` succeeds on a connection opened as the routes open theirs — the owner role
(`OWNER_DATABASE_URL`) — so it fails when they would; with a 3-second connect timeout
and a 2-second statement timeout, passed by a `connect_timeout` and `statement_timeout`
argument added to `db/session.py`'s connect for this route alone, and 503
`{"ok": false}` when it does not. It says nothing else. For Render's health check
(hosting) and the website's reachability test.

### 4.5 When contact-engine cannot be reached (9.17)

Part of the contract, carried out by the dialer and the app:

1. **No answer** is a refused connection, no reply within 10 seconds, or a 5xx. The
   dialer's backend tries once more after two seconds, **with the same
   `Idempotency-Key`**, then tells the rep: "Can't reach NeverMissCall right now. Try
   again in a minute."
2. **Nothing is done on a stored answer.** No call starts unless `POST
   /contacts/{id}/calls` answered now; a list or a card shown from before is shown as
   such and its Call button is off.
3. **The three things that wait on the phone** (8.7) — an outcome, a memo, a "don't
   call me again" — keep the key they were made with, and are sent again when **the
   same rep** is signed in and contact-engine answers. 6a's memory makes a resend safe
   for 90 days: if the first try was done and its answer lost, the second gets the
   first answer and does nothing again. Past 90 days a resend is asked again (6a §4.3).
4. **A queued item leaves the queue only on an answer about the item**: 200 (done); a
   verb's refusal — 409 with any code but `key_mismatch`; or 404 `no_contact`. A refusal
   is shown to the rep, and the item is never resent. **Every other answer** — no answer
   after the retry, any 5xx, 401, any 403, any 400, 404 `no_route` or `unknown_rep`,
   405, 409 `key_mismatch` — keeps the item queued as it is, and the website alerts the
   operator (1.7). Within 90 days, the same request resent is answered as it was first
   answered, so an item that was recorded but whose answer was lost is not shown as
   refused. Past 90 days it is asked again, and an outcome that was recorded can then be
   refused `no_call` (§6).
5. **A "don't call me again" the dialer's backend cannot get recorded** — refused, or
   answered in any way that keeps it queued — is sent to the operator by the website,
   **each time** — the alert raised and held by the website **before** the app is told
   the item is refused, so a crash between them cannot lose it — with the phone number the rep saw on the card (the app sends it with
   the request for this) and the answer it got. The operator records it by that number
   (`POST /v1/admin/do-not-call`, part 2); a later resend that succeeds does no harm, as
   recording a blocked number again changes nothing (`service/dnc.py:73-92`). A queued
   "don't call me again" is accepted from a deactivated rep (6a §4.1). Every other alert
   of §4.5.4 carries the answer's code; how the website groups or throttles them is its
   own (1.7).
6. **An open whose answer was lost.** If both tries of `POST …/calls` get no answer, the
   rep's next try is refused `call_open` with the call's id when the first was done.
   The app then asks the rep to record that call's outcome — Call not placed, if it never
   rang — before calling again. It never places a call on that answer. Every new try is
   a new intent, with a new `Idempotency-Key`; a reused one would replay an old open as
   if it were answered now.

### 4.6 A stand-in (9.7)

**None.** The stand-in was for building the dialer while contact-engine did not exist.
It exists now (6a): the dialer is built against contact-engine itself, run locally
(`make api` on `mailengine_dev`), and the website's own unit tests fake its client as
they fake any other service. A stand-in would be a second copy of the rules, kept in
step by hand — a step that adds no real check (2.7).

### 4.7 The switch-on gates (9.5)

Proven in production, with the operator's own test rep, before any real rep is added:

| Gate | Met when |
|---|---|
| 1. The path | The test rep is made known by the website's roster; Get more numbers gives a batch; a contact's card says `clear` and may call; the call is placed from the app and its outcome recorded; the history shows it; a "don't call me again" from the app blocks the number |
| 2. The daily run | Three daily runs in a row are recorded in the status; one day the run is skipped on purpose, and the website's `daily_run_missing` alert reaches the operator |
| 3. Not reachable | contact-engine is stopped: the app shows the message and no call can start; the website's `contact_engine_unreachable` alert reaches the operator; started again, an outcome and a "don't call me again" that waited on the phone are each recorded once |

The old gate's "one run broken on purpose" is gone: a broken run and a skipped run are
the same alert (§4.1). §4.5's items 4 to 6 — a refused queued item, a "don't call me again" sent on to the
operator, a lost open — are the app's and the website's, proven by their own tests, not
by a gate.

## 5. The routes

| Method and path | Who | Calls |
|---|---|---|
| `GET /v1/status` | the website's key | `service/runs.status` |
| `GET /health` | none | `select 1` |

## 6. Gaps and limits

| Gap | Handling |
|---|---|
| An alert is only as timely as the website's reading of the status | The website's schedule |
| The nightly runs without the customer feed when `MEDUSA_READONLY_URL` is unset; sales are then not seen | Production sets it (part 5c); not an alert (answer 1) |
| On Render, the job that fetches DNC files and the service that reads them may not share a disk (9.11) | Open, for hosting. Until then a missing working copy shows as `dnc_checks_expiring` a week ahead |
| One connection per request, no pool; `/health` opens one per ping | Kept: a few reps, and uvicorn's thread pool bounds concurrent requests well below Postgres's connections. Revisited at hosting if Render's database limit or ping rate needs it |
| A nightly run by hand after a failed scrub records a run, which clears `daily_run_missing` (§4.1) | The status's `scrub.last_started_at` shows the scrub stopped; `dnc_checks_expiring` follows a week before any contact drains |
| The health check can say yes while the daily run has stopped | Its job is reachability; the status says the rest |
| A queued item resent after 90 days is asked again (§4.5.3) | 7.7's 90 days; 8.7 sends items at the rep's next sign-in |
| An item still on a phone that never signs in online again — the rep deactivated, the phone lost, wiped, or no longer used — reaches no server (8.7: items are sent at the rep's next sign-in). An outcome or memo sent after deactivation gets 403 `rep_inactive` and stays queued | Known limit (2.6) of 8.7's queue on the phone: no server can see what it was never sent. contact-engine accepts a deactivated rep's "don't call me again"; the admin has the rep open the app online before deactivating them |
| A dialer fault keeps items queued until it is fixed | The website alerts the operator (§4.5.4) |
| A misaddressed request — a wrong contact id or `X-Rep`, an outcome's name out of step — is refused, or, when it names another contact the rep holds or once held, **done on that contact** (an outcome recorded, another number blocked). Online or queued alike | Known limit (2.6). contact-engine cannot tell a misaddressed request from a meant one. The dialer's tests against contact-engine run locally (§4.6) are the guard; a refused or stuck "don't call me again" still reaches the operator with its phone (§4.5.5) |
| An admin clears a call whose outcome is waiting on an offline phone (`call_left_open`); a call outcome — No answer, Left a voicemail, Busy, Owner unavailable, Call not placed — cannot then be recorded, since those need an open call, and the attempt does not count toward 5b's limits | Known limit (2.6). The card's outcomes (Spoke, Signed up, …) can be recorded again |
| A code that stays stale — a SAN holder gone, a code never uploaded — keeps `dnc_checks_expiring` on, which can hide a new cause | The remedy is to upload a list for it or unsubscribe it (`jobs/subscribe_area_codes.py`); the detail names the code |
| `/health` opens a database connection for anyone who asks, with no pool | The two timeouts bound each one; Render's network is the limit on who asks. Revisited at hosting |

## 7. Tests, written first

`tests/acceptance/test_running_it.py`:

| Test | Pins |
|---|---|
| The record | `nightly_cli` records one run, at its clock, when the nightly completes; a nightly that raises records nothing; `--dry-run` records nothing; `test_daily_run_steps.py` unchanged and green. `tests/unit/test_nightly_cli.py`, which stubs `run_nightly` without a database, stubs the record too (unit tests are disposable) |
| `daily_run_missing` | none recorded → alert; one exactly 26 hours old → none; 26 hours and a minute → alert; `last_finished_at` is the newest |
| The recheck | a contact checked 5 days ago against a list 22 days old (UTC date) is rechecked when tonight's list is newer, and linked to it; 21 days old → not; not when tonight's list is the one it has, nor a same-date list from another SAN holder; one checked 5 days ago against a list 20 days old, with a newer list present, is not; under `--limit`, rep-held contacts still come first; a newer list whose working copy is missing → no recheck, and the contact is counted by the alert; the same results with the database's session in a non-UTC zone; the single-registry path's due set unchanged; the existing scrub tests unchanged |
| `dnc_checks_expiring` | a contact whose list is 25 days old → counted; 23 days → not; whose check is 25 days old, no list → counted; the exact 7-day boundary, on both the check and the list; already `check_too_old` → counted; blocked, on the DNC file, a seed, no phone, an unsubscribed code → not; a contact linked to a 25-day list while its code's newest accepted list is fresh (a working copy missing) → counted; never checked, in 49 hours ago → `never_checked`, 47 hours → not; held (a rep's and an export partner's) and pool counted apart, and by area code; a contact linked to a rejected list, or another code's → not; never-checked measured from a code subscribed 10 hours ago → not; created 60 hours ago but added by a rep 10 hours ago → not; a code subscribed by two SAN holders, 60 and 10 hours ago → counted once, from the earlier; on every case, counted under (a) exactly when `dnc_status` at `at + 7 days` is `check_too_old` |
| `call_left_open` | a call open 25 hours → alert, count 1; exactly 24 hours → none; 23 hours → none; cleared or with an outcome → none |
| The route | the website's key → 200 with the shape of §4.3, with or without `X-Admin`; the dialer's key → 403 `wrong_key`; no key → 401; an alert carries no message; it takes no lock |
| Health | `/health` → 200 `{"ok": true}` with no key; the database unreachable (a seam) → 503 `{"ok": false}`; it connects with the 3-second connect timeout and the 2-second statement timeout |

## 8. Done means

The gate green; `make test`, `make e2e`, `make lint` clean, every earlier gate unchanged;
mutation checks each failing a test — record a run when the nightly fails; let 26
hours alert; count the list side with `<=`; recheck only by the
check's age; recheck when tonight's list is no newer; read expiry by the check alone;
count a blocked contact, a seed, one with no phone, one in an unsubscribed code, or one
on the DNC file; swap held and pool; leave out a never-checked contact; leave out a
contact whose code's newest list is fresh; treat a same-date list as newer; let an
open call alert early; show the status to the dialer's key; answer health 200 with the
database down; drop health's timeouts; record a run on `--dry-run`;
count a two-holder code twice, or from its later subscription; let a call open exactly
24 hours alert; read the status in a write transaction. Migration `0021` applied to
`mailengine_dev`.

## 9. For the operator

| # | Question | Answer |
|---|---|---|
| 1 | The alerts? | **Answered 2026-10-01: these four** — the three of §4.3 and the website's own. Offered that (recommended), "Fewer", or "More". The second alert was then redrawn by answer 5. |
| 2 | When contact-engine cannot be reached? | **Answered 2026-10-01: that rule** — §4.5. Offered that (recommended) or "Change it". Items 4 and 5 were added after the review, to complete it. |
| 3 | A stand-in? | **Answered 2026-10-01: no stand-in** — §4.6. Offered that (recommended) or "Build a stand-in". |
| 4 | The switch-on gates? | **Answered 2026-10-01: these three** — §4.7. Offered that (recommended) or "Change them". |
| 5 | Revision 1's review found contacts can drain with no alert: the scrub rechecks by the check's age, but a contact also expires with its list. What does 6b do? | **Answered 2026-10-01: fix the recheck, and alert on the harm** — §4.2, §4.3. Offered that (recommended), "Alert only", or "Discuss first". |

## 10. The migration, `0021.daily-runs.sql`

```sql
create table daily_runs (
  id           bigint generated always as identity primary key,
  finished_at  timestamptz not null
);
create index daily_runs_finished_idx on daily_runs (finished_at);

grant select on daily_runs to me_user_ro;
```

## 11. Proposed changes to the decision record and documents

| Item | Proposal |
|---|---|
| 9.5, 9.7, 9.17 | Settled by this part's answers; moved out of §9 |
| A new line under §4 (DNC filtering) | A contact is rechecked when its list is over 21 days old and a newer one exists (answer 5) |
| `00-interface.md` lines 127–128 | Point at §4.5 and §4.6 |
| 9.11 | Stays open, for hosting; §6 says what shows it until then |

## 12. Safety properties

1. contact-engine sends no message (1.7); it only names what holds.
2. No call starts on a stored answer; contact-engine's silence stops calling, it never
   lets a call through.
3. A retry after no answer never acts twice within 90 days. A "don't call me again"
   that reaches the dialer's backend is recorded by contact-engine, or reaches the
   operator with its phone (§4.5.5) — unless it is misaddressed (§6). One that never
   leaves the phone is 8.7's limit (§6).
4. While a newer list exists, a contact is checked against it before its own list
   expires; when none does, or a contact is about to stop being callable for any other
   reason, the operator is told a week before.
5. Every call is still against a check and a list each at most 31 days old, as today.
   The recheck only adds checks; like every scrub, it may clear a number the newer list
   no longer carries — the newest list governs.
6. The health check reveals nothing but that the service answers.
