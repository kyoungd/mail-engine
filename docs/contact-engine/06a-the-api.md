# contact-engine Upgrade — Part 6a: The API (the contract)

**Status:** APPROVED by the operator, 2026-10-01, at revision 6 (offered "Approve now",
"One more review", or "Read it first"; chose approve now). **BUILT 2026-10-01:** under
an approved build plan and an approved test gate: `0020.the-api.sql`; the ambient
connection in `db/session.py` (`request_connection`); `web/api.py` (`create_app`, run
by `make api`); `service/reads.py`; `service/roster.py` (with the seam
`_after_name_check`, which the race test needs); `calls._check_open`'s `lock` flag and
`calls.KNOWN_SQL`, factored out of `receive_call`; `jobs/calls_admin_cli.py` reads
`reads.open_calls`. Gate `tests/acceptance/test_api.py` (one setup fix approved while
it was being greened: test_history's former holder records No answer on a call, since
Spoke moves the contact to Follow up, which the 90 days exempt). Every mutation of §8
fails a test, except "hash the raw body", which cannot happen as written: the body is
hashed after it is parsed, so key order never reaches the hash. `make test` 784
passed; e2e, lint clean. `0020` applied to `mailengine_dev` only. Part 6 is cut
in two (answer 1): 6a is the API — this document is **the contract** between the dialer,
the website and contact-engine (answer 2); 6b is running it (alerts and switch-on gates,
9.5; when contact-engine cannot be reached, 9.17; a stand-in, 9.7). History: Revision 1
did not pass its review: request memory was written apart from the act, so a crash
between them let a retry do it twice (7.7); the app could change settings (7.3); the Get
more numbers answer and the refusal messages leaked other reps' contacts; several reads
had no service function, so their rules would have lived in routes; the roster ignored
the existing `sales_rep_id`; a deactivated rep's "don't call me again" was dropped; and
a dozen smaller gaps. Revision 2 rewrites the document around them. Revision 2's
review found the one-transaction design sound and four holes: the do-not-call route
hid a former holder's report; request memory was shared across reps; the identical-404
rule had no place to live; the roster could split an existing partner in two.
Revision 3 closes them and applies the minor findings. Revision 3's review found three
more: a read would take a row lock and its card mixed two moments; the card had no
holder rule, and no test pinned a former holder's `not_yours`; the roster's rules had no
service home. Revision 4 closes them and applies the minor findings. Revision 4's review
found the design sound and three gaps: an inactive rep's replay had no test; the roster's
order answered `name_taken` where `link_first` belongs; §12.2 said more than the design.
Revision 5 closes them and applies the minor findings. Revision 5 passed its review
(no blocking finding); its minor findings are applied here, in revision 6.
**Part of:** [the upgrade](00-overview.md). Decisions are in the decision record,
`nvermisscall/docs/active/sales-partner-dialer-decisions.md`, named here by number
("decision 1.8"); sections of this document are named "§4.1".
**Checked against:** the `contact-engine` branch at `dd22861` (parts 0 to 5 built). A
statement about the code carries its file and line.

---

## 1. Its job

Be the only way in from outside: let the dialer's backend and the website, each with its
own key, ask for what a rep or an admin may see and do, and make a rep known or
deactivated. Answer a retried request the way it was first answered: the same status
and the same stored answer.

| Decision | What it asks | Here |
|---|---|---|
| 1.1, 1.4 | App → dialer → contact-engine; the dialer asks directly | §4 |
| 1.6 | The app is thin; the server decides everything | Every answer is a verb's; the callers display it |
| 1.8 | The website's roster is the one place a rep is added or removed; the dialer makes a rep known and says when one is deactivated; reps never log in | §4.4 |
| 1.9 | The app signs in with the website's login | The callers check who the rep is; contact-engine trusts the caller's key (§4.1) |
| 6.4 | A new holder sees the history of NMC's contacts, not of a rep's own | §4.7 |
| 7.3 | The rep changes settings on the website; the app shows them | §4.1: saving settings is the website's only |
| 7.6 | The server's clock times every call | §4.2 |
| 7.7 | A success is never done twice; a refusal changed nothing; a success is remembered 90 days | §4.3 |
| 8.3, 8.4 | Calls received, firm; who is calling, over the ringing screen | §4.8 |

**Not exposed**, and why: the next contact in a list (the app takes it from the list);
editing a contact's details, giving a contact up, editing a memo, correcting the last
outcome, the admin's log (all *drafted* in `00-interface.md`, in no decision);
replacing a wrong number (part 5c answer 5); a reopen of Closed, reactivating a rep
(not decided). `reclaim`, though *drafted* in `00-interface.md`, is exposed: it is an
existing admin act (part 4, 5c).

## 2. Its edges

| 6a does | 6a does not — who does |
|---|---|
| Keys, the rep or admin, request memory, errors (§4.1–§4.5) | Check who a rep or an admin is — the callers (1.9) |
| A route for each verb of §5 | Change any verb's rules |
| The reads: card, history, lists with identities, known callers, search, open calls (§4.6–§4.8), in a service module | Hold unsent items on the phone (8.7) — the app |
| Make a rep known; deactivate one (§4.4) | Anything else on departure — by hand (decision §10) |
| | Read an uploaded file into rows (part 1 §2) — the website, which sends rows; put a refusal code into words for the rep — the callers |
| | When the calling window next opens (part 3 §6, 5b §2) — not built; the card gives each zone's local time, which is what 5.4's warning shows |
| | Taking events from outside (part 2 §6's "event intake") — none is exposed; a sale arrives through the nightly feed |
| | Alerts, switch-on gates, unreachable behaviour, a stand-in, connection pooling — 6b |

## 3. What exists, checked

| Fact | Where |
|---|---|
| No HTTP layer exists: the mail-engine era's `web/` was removed in part 0; FastAPI and uvicorn are dependencies, httpx a dev dependency | `00-foundation.md`; `pyproject.toml:10-12`, `:22` |
| `transaction()` opens a new connection per call and commits it alone | `db/session.py:17-22` |
| Verbs refuse with `ValidationError(code, message, detail)`; most take `at`, but `get_settings`, `reclaim` and `dnc_history` do not, and `assign_batch` and `set_owner` read the clock themselves | `domain/errors.py:6-10`; `service/assignment.py:269`; `service/custody.py:65` |
| `partners` has `sales_rep_id bigint` — the website roster's id (`nmc_sales_rep.id`) — not unique; `name` is unique and not null. The seeded partner `John` has no `sales_rep_id` | `db/migrations/0009.partner-custody.sql:16`, `:27`, `:38-40`; `jobs/partners_cli.py:219-220` |
| `jobs/partners_cli.py set` upserts a partner by name and can set its status and `sales_rep_id` | `jobs/partners_cli.py:257` (`_set`) |
| Rep verbs refuse `not_yours` with their own message, distinct from `no_contact`; `report_do_not_call` checks the phone before the holder and accepts a rep who held the contact once; `record_outcome` on a call refuses `no_call` for another rep's contact | `service/calls.py:95`, `:186-191`, `:218`, `:264`, `:297`; `service/rule.py:298`; `service/zones.py:104`; `service/dnc.py:157-173` |
| `get_more_numbers` passes its key to `assign_batch`, whose `idempotency_key` is unique across all partners and kept for ever; its report lists contact ids for every cause, region-wide | `service/assignment.py:293-305`, `:157-193`; `db/migrations/0009.partner-custody.sql:45` |
| `rep_lists` returns received calls by id only | `service/rule.py:319-324` |
| "Held now or once" exists inside `receive_call` (by phone, seeds excluded) and, separately, inside `report_do_not_call` (by id) | `service/calls.py:285-293`; `service/dnc.py:166-173` |
| `rule.may_call` goes through `calls._check_open`, which locks the contact `for update` | `service/rule.py:341-347`; `service/calls.py:78-82` |
| The open-calls list exists only in a job | `jobs/calls_admin_cli.py:15-24` |

## 4. The design

`web/api.py`, a FastAPI app run by uvicorn: routes parse, call a verb or a read, and
shape the answer. Every rule is in `service/`; the new reads are `service/reads.py`, the
roster and the resolving of `X-Rep` are `service/roster.py`. A refusal that means "no
such rep" (`unknown_rep`) is 404 on a path that names the rep, 403 in `X-Rep`; every other
`ValidationError` is §4.5's.

### 4.1 Who asks (1.4, 1.8, 1.9, 7.3)

| Header | Meaning |
|---|---|
| `X-API-Key` | `CE_DIALER_KEY` or `CE_WEBSITE_KEY`. The app refuses to start if either is unset, empty, or equal to the other; keys are compared in constant time. Anything else → 401 `bad_key` |
| `X-Rep` | On a rep route: the rep's `nmc_sales_rep.id` on the website, matched to `partners.sales_rep_id` by `roster.resolve_rep(sales_rep_id, allow_inactive)`. Missing, not a whole number, out of a bigint's range, unknown, or the house → 403 `unknown_rep`; an inactive partner → 403 `rep_inactive` — except on `POST /contacts/{id}/do-not-call`, which an inactive rep may still send (a "don't call me again" is never dropped) |
| `X-Admin` | On an admin route: the admin's name, the actor. Blank → 403 `no_admin` |

| Routes | Keys |
|---|---|
| Rep routes, except settings writes | both (the app through the dialer; Call Control on the website) |
| `PUT /me/settings`, `POST /me/settings/restore` | the website's only (7.3) |
| Roster routes | the dialer's only (1.8) |
| Admin routes | the website's only |

Another key → 403 `wrong_key`. contact-engine trusts the caller to have checked who the
rep or admin is (1.9).

### 4.2 Time

Every `at` is `web.api._now()` — the server's clock when the request arrives, taken once
per request (7.6; the clock rule, 9.15). `_now` is the tests' seam. `assign_batch` and
`set_owner` keep their own clock for batch expiry and custody events (existing code,
part 1 §4.6).

### 4.3 Request memory (7.7) — one transaction

Every action (`POST`, `PUT`) carries `Idempotency-Key` (400 `no_key` without it).

**The act and its memory commit together.** `db/session.transaction()` gains an ambient
connection: when the API has opened one for the request (a context variable), every
`transaction()` inside the request uses it — a nested `with conn.transaction()` is a
savepoint, and an inner `transaction()` neither commits nor closes it — and the API
commits once at the end. The connection is READ COMMITTED (pinned), so each statement
after the key lock sees what committed before it. Lock, memory, verb and commit run in
one synchronous function (FastAPI runs a sync dependency and a sync endpoint in separate
threads, so the context variable is set inside that one function). Outside the API,
`transaction()` is as today. Memory is scoped to **(caller, who, key)** — `who` the rep or
admin, canonical: `rep:{partner id}`, `admin:{name}`, or `roster:{sales_rep_id}` on the
roster routes — so one rep's key never touches another's. For an action:

1. Open the connection. A path id that is not a UUID is answered (§4.5) here, before
   the memory is read. Resolve the rep (§4.1) on the connection, reading the partner row
   `for share`, so a deactivation cannot commit between the check and the act; an
   inactive rep's retry is refused like any other request (except do-not-call). Take
   `pg_advisory_xact_lock(hashtextextended(caller || ':' || who || ':' || key, 0))` —
   hashed by Postgres, so every process and worker takes the same lock.
2. A row in `api_requests` for (caller, who, key), stored within 90 days: if method,
   path and canonical body hash (keys sorted, no whitespace) match, answer it again with
   `Idempotent-Replay: true` — the verb is not called; if not, 409 `key_mismatch`.
3. Otherwise run the verb on the ambient connection, and on success
   **insert** the row, or update it only where the stored one is older than 90 days,
   and commit; a racing insert (only a broken lock allows one) is then a unique
   violation that rolls the second act back, never a silent second act. The answer is
   stored as text, so a replay is the same bytes. On a refusal, roll
   back: nothing is kept, and sending it again asks again. Any other error is a 500,
   rolled back, not kept. `web.api._before_memory()`, a no-op between the verb and the
   memory write, is the tests' failure seam.

A second request with the same key waits on the lock, then replays. Every read a verb
makes inside the request (part 2's status and part 3's hours inside `open_call`) reads in
the same transaction. Nothing is deleted (8.8). A client uses a new key per intent: an
old key with the same body replays, it does not repeat.

An `Idempotency-Key` blank, or longer than 200 characters → 400 `no_key`.

**Get more numbers** passes `assign_batch` the key `api:{caller}:{who}:{key}:{date}` —
the UTC date of `_now` — so two callers or reps cannot collide, and a key reused after 90
days asks again. The 90-day window compares a memory row's `at` with `_now`. `assign_batch`'s own memory is
for ever; the API's is 90 days.

### 4.4 The roster (1.8)

Keyed on `sales_rep_id`, made unique by the migration; `service/roster.py`:
`make_known(sales_rep_id, name)`, `deactivate(sales_rep_id)`,
`resolve_rep(sales_rep_id, allow_inactive)`.

- `PUT /v1/reps/{sales_rep_id}` `{name}` — dialer only. In this order:
  1. A blank name → 400 `bad_request` — a schema constraint on the body (stripped, at
     least one character), answered as §4.5's 422 → 400. The dialer sends a name distinct
     among its reps: two reps with one name get `name_taken` for the second.
  2. **The name first:** a partner other than this id's that has the name — an
     **unlinked** one (no `sales_rep_id`) → 409 `link_first` (the operator links it with
     `partners_cli set NAME --sales-rep-id N` before the rep's first sign-in, so a rep
     still on the export, 6.6, never becomes two partners), unless this id is already
     known (a rename) → 409 `name_taken`; a linked one, or the house → 409 `name_taken`.
  3. Then `insert … on conflict (sales_rep_id) do nothing` and `select … for update`,
     so two `PUT`s for one id take turns: a new active partner, or the known one's name
     updated; an inactive one → 409 `rep_inactive`.
  4. A unique-name violation from a race is caught in a savepoint, the name's holder
     re-read, and classified as in step 2.
  A known but inactive rep whose new name clashes is answered for the clash (step 2)
  before `rep_inactive` (step 3). The house is never on the roster (`unknown_rep`).
- `POST /v1/reps/{sales_rep_id}/deactivate` — dialer only. Status → inactive; an
  inactive one stays so; unknown → 404 `unknown_rep`. Nothing else: holdings are an
  admin's `reclaim` (§5).
- `jobs/partners_cli.py` stays the operator's tool, for partners not on the app (a rep
  still on the export, decision 6.6); its existing `--status` can set a partner active
  again. The API does not reactivate.

### 4.5 Errors

JSON `{code, message, detail}`; dates, times and ids in `detail` as strings.

| Cause | Status |
|---|---|
| A verb's `ValidationError` | 409, its code |
| On a rep contact route, **a contact the rep never held** — a `not_yours`, any refusal on a contact the rep neither holds nor once held (`calls.KNOWN_SQL`), an id that does not exist, an id that is not a UUID | 404 with **exactly** `{code: "no_contact", message: "no such contact", detail: {}}`. This is `reads.hide(rep, contact_id, error)`, applied by every rep contact route to a refusal **after** the verb has refused — never before, so a former holder's own open call (5a §6) and a former holder's "don't call me again" (part 2 answer 7) still reach their verbs. `not_yours` itself always becomes the 404. A path id that is not a UUID never reaches a verb: the route reads it as text and answers this 404 itself |
| A body that does not parse, or a path id that is not a UUID on a route that names no contact | 400 `bad_request` (FastAPI's own 422 and 405 are answered in this shape: 400 `bad_request`, 405 `no_route`) |
| §4.1, §4.3 | as stated |
| An unknown route | 404 `no_route` |

**Get more numbers' answer** is `{batch_id, assigned, shortfall: {cause: count},
retry}` — counts, never other contacts' ids.

### 4.6 The card — `reads.card(rep, contact_id, at)`

`GET /v1/contacts/{id}`, the contract's description of a contact (`00-interface.md` §3),
**for a contact the rep holds now** — anything else refuses `not_yours`, the 404:

| Field | From |
|---|---|
| `id`, `business`, `contact_name`, `phone`, `city`, `state`, `trade` | the contact and its primary intake row |
| `whose`: `nmc` or `own` | part 1's rule |
| `list`, `reason`, `calls`, `voicemails`, `limits`, `due`, `rest_until`, `pause_until` | 5b's `_states` and the rep's settings |
| `may_call` | `{yes: true}`, or `{yes: false, code, detail}` — 5b's `may_call` |
| `zones`, `local_times`, `inside` | part 3 |
| `dnc_status` | part 2 |
| `goes_back_on` | NMC's contact held by the rep: its batch's `expires_at`, or else its latest `contact.assigned` + `ASSIGNMENT_EXPIRY_DAYS` — **null exactly when expiry would skip it**, read from the expiry's own predicates (`SOLD_SQL`, `_EXEMPT_SQL`); a rep's own: null |
| `latest_memo`, `last_call` (time, outcome) | 5a, filtered as history is (6.4): on a rep's own contact, only this rep's |
| `undoable` | ids of the rep's own Signed up and Wrong number within `UNDO_WINDOW`, not undone |

### 4.7 History (6.4) — `reads.history(rep, contact_id)`

`GET /v1/contacts/{id}/history`: the contact's calls and memos, newest first, each with
`by_you`; no other rep is named. NMC's contact: every entry. A rep's own: only this
rep's. A contact the rep does not hold → §4.5's 404.

### 4.8 Lists, known callers, search, open calls

- **Reads:** each `GET` runs in one transaction, **REPEATABLE READ, READ ONLY**, on the
  ambient connection, so every field of an answer comes from one snapshot. No read
  takes a lock: `calls._check_open` gains `lock: bool` (default true); `rule.may_call`
  and the card call it with `lock=False`, which reads the contact without
  `for update` — the same checks, in the same order.
- `reads.lists(rep, at)` — `GET /v1/me/lists`: each list with, per contact, `id`,
  `business`, `contact_name`, `phone`, `list`, `reason`, `due`, `rest_until`,
  `pause_until` (enough to show the list; the card is fetched when one is opened); and
  **Calls received**: per unresolved row, `id`, `contact_id`, `business`, `phone`,
  `received_at` (8.3).
- `reads.known_callers(rep)` — `GET /v1/me/known-callers`: every contact the rep holds now
  or once held — the predicate `calls.KNOWN_SQL` (holder, or an event naming the rep as
  `new_owner_id`, or an `intake_rep` row; seeds excluded), factored as it is out of
  `receive_call` and used by both and by `reads.hide` — each with phone, business and
  contact name (8.4). Part 2's `report_do_not_call` keeps its own check (by id, seeds
  included): it is part 2's rule.
- `reads.search(rep, q)` — `GET /v1/me/search?q=`: among the contacts the rep holds, the
  business or contact name containing `q` (case-insensitive); and, when `q` has at least
  4 digits, the phone containing them; `%`, `_` and `\` in `q` are escaped. At most 50.
  `q` shorter than 2 characters → 400 `bad_request` (a query schema constraint).
- `reads.open_calls()` — `GET /v1/admin/calls/open`, oldest first; `jobs/calls_admin_cli.py`
  uses it too.

## 5. The routes

All under `/v1`. *R* — a rep route; *W* — the website's key only; *D* — dialer only; *A* —
admin. Bodies are JSON; every `POST`/`PUT` carries `Idempotency-Key`.

| Method and path | Who | Calls |
|---|---|---|
| `PUT /reps/{sales_rep_id}` `{name}`; `POST /reps/{sales_rep_id}/deactivate` | D | §4.4 |
| `GET /regions` | R | the keys of `REGIONS` |
| `GET /me/settings` | R | 5b `get_settings` |
| `PUT /me/settings` `{voicemails, calls, days_between, rest_months}` | R, W | 5b `save_settings` |
| `POST /me/settings/restore` | R, W | 5b `restore_defaults` |
| `GET /me/lists`; `GET /me/known-callers`; `GET /me/search?q=` | R | §4.8 |
| `POST /me/more-numbers` `{region}` | R | part 4 `get_more_numbers` (§4.3, §4.5) |
| `POST /contacts` `{rows, how_obtained, confirmation}` | R | part 1 `add_numbers`; a result per row |
| `GET /contacts/{id}`; `GET /contacts/{id}/history` | R | §4.6, §4.7 |
| `GET /contacts/{id}/may-call` | R | 5b `may_call` |
| `POST /contacts/{id}/calls` `{confirm_outside_hours}` | R | 5a `open_call` |
| `POST /contacts/{id}/outcomes` `{outcome, call_id?, memo?}` | R | 5a `record_outcome` |
| `POST /outcomes/{id}/undo` `{reason}` | R | 5a `undo_outcome` |
| `POST /contacts/{id}/memos` `{text}` | R | 5a `add_memo` |
| `POST /contacts/{id}/zone` `{zone}` | R | part 3 `set_zone`, as the rep |
| `POST /contacts/{id}/move` `{to}`; `/pause` `{until}`; `/unpause`; `/restart` | R | 5b |
| `POST /contacts/{id}/do-not-call` `{reason?}` | R (inactive allowed) | part 2 `report_do_not_call` |
| `POST /calls-received` `{phone}`; `POST /calls-received/{id}/resolve` `{resolution}` | R | 5a; a phone the rep never held (`not_yours`) → §4.5's 404 |
| `GET /admin/calls/open`; `POST /admin/calls/{id}/clear` `{reason}` | A | §4.8; 5a `clear_call` |
| `POST /admin/do-not-call` `{phone, reason}`; `GET /admin/do-not-call/{phone}`; `POST /admin/do-not-call/{phone}/lift` `{seen, reason}` | A | part 2 |
| `POST /admin/contacts/{id}/zone` `{zone}` | A | part 3 `set_zone`, as the admin |
| `POST /admin/reps/{sales_rep_id}/reclaim` `{reason}` | A | part 4 `reclaim`; unknown → 404 `unknown_rep` |

A successful action answers 200 with its verb's result as JSON. `reads.hide` is applied
by every rep route whose path names a contact.

## 6. Gaps and limits

| Gap | Handling |
|---|---|
| Reactivating a rep | An admin's act through `partners_cli` (§4.4); not on the dialer's roster |
| The ambient connection changes how verbs read inside a request: one transaction, not one per call | Outside the API nothing changes; inside, a verb's nested reads see the same snapshot as its writes — what 7.7's "never twice" needs |
| Two shared keys | Rotated by a redeploy; per-rep authentication is the callers' (1.9) |
| SQL `now()` drives the gates' freshness (`LINK_FRESH_SQL`, `dnc_fresh`) and the expiry, not `_now` | Existing code keeps its clock; tests that move `_now` far set the data to match |
| A rep renamed on the roster changes the name `partners_cli` keys on | The operator uses the new name |
| One connection per request, no pool | 6b, with hosting |

## 7. Tests, written first

`tests/acceptance/test_api.py`, through FastAPI's `TestClient`; `web.api._now` set by
the tests.

| Test | Pins |
|---|---|
| Keys | none, wrong → 401; the dialer's key on admin or settings-write routes, the website's on roster routes → 403 `wrong_key`; the app refuses to start with a key unset, empty, or both equal |
| The rep | missing, not a number, unknown, the house → 403 `unknown_rep`; inactive → 403 `rep_inactive`, except the do-not-call route, which records the block |
| The roster | `PUT` makes a rep known; again updates the name; a new id with an unlinked partner's name (the seeded `John`) → 409 `link_first`, and after `partners_cli` links it, the `PUT` finds it; a known rep renamed to an unlinked partner's name → 409 `name_taken`; the house's name → 409 `name_taken`; another linked clash → 409 `name_taken`; blank name → 400; deactivate → inactive, twice is fine, unknown → 404; `PUT` on an inactive rep → 409 |
| Request memory | a success replayed with `Idempotent-Replay: true` and nothing written twice; a body re-sent with keys in another order replays; a different body, method or path → 409; the same key from another rep is a separate request; a blank key → 400; **a success, then the rep deactivated, then the same key and body → 403 `rep_inactive`, while the do-not-call route's replay is still served**; a refusal re-sent is asked again; two at once (a pause seam inside the verb) → one act, one answer; a key stored 91 days ago → asked again and the row replaced; no key → 400; **a failure injected after the verb and before the memory row → nothing of the act is left** |
| Get more numbers | the same key string from two reps → two batches; the same rep's key again after 91 days (`_now` moved; a small pool, so the rep stays within `ASK_AGAIN_AT`) → a new batch, not the old receipt; the answer carries counts, never another contact's id |
| Errors | a refusal → 409 with its code and string detail; on every contact route, a contact the rep never held, a random UUID and a non-UUID give the identical 404 body — `POST …/outcomes` with a `call_id` included; a former holder's outcome on their own open call is recorded; a bad body → 400; FastAPI's 422 → 400 `bad_request` |
| A former holder | a contact that went back from the rep and is now another rep's: memo, open a call, move, pause, unpause, restart, zone, may-call, an outcome without `call_id`, the card and history each give the identical 404 body |
| The edges | blank `X-Admin` → 403 `no_admin`; an unknown route → 404 `no_route`; a wrong method → 405 `no_route`; a key over 200 characters → 400 `no_key`; an `X-Rep` beyond a bigint → 403 `unknown_rep`; a non-UUID id on a non-contact route → 400 `bad_request`; a non-integer roster id → 400; search escapes `%` and `_` and ignores case; two `PUT`s racing for one name → one partner, the other `name_taken` |
| Reads take no lock | a blocker holds the contact `for update`; `GET` the card and `/may-call` answer without waiting |
| One snapshot | `reads._after_first_read()`, a no-op seam after the card's first query (where REPEATABLE READ takes its snapshot); another connection commits a memo and an outcome while it waits → the card shows neither |
| Do-not-call by a former holder | a contact that went back from the rep by expiry: the rep's queued "don't call me again" is recorded, and an inactive rep's too |
| Every route | each route of §5 once on its happy path, through to its verb, at `_now` |
| The card | every field for an NMC contact and a rep's own; `goes_back_on` equals the batch's `expires_at`, and for a door B claim its `contact.assigned` + 90 days; null for sold, callback, follow-up and own; a date for a blocked callback and a rep-closed callback (which expiry returns) |
| History | NMC's contact: another rep's entries shown, `by_you` false, no name; a rep's own (set up with `set_owner`): only its rep's; not held → 404 |
| Lists | the identity fields; Calls received with contact, phone and time |
| Known callers | held now and once listed; another rep's not |
| Search | a name search leaves out a non-matching held contact; 4+ digits match a phone; others' contacts never; at most 50; 1 character → 400 |

## 8. Done means

The gate green; `make test`, `make e2e`, `make lint` clean, every earlier gate unchanged
and green with the ambient connection; mutation checks each failing a test — accept a
wrong key; let the dialer save settings or use admin routes; serve an inactive rep; drop
an inactive rep's do-not-call; hide a former holder's do-not-call or open-call outcome;
check the holder in the route before the verb; scope memory without the rep; drop the
date from the Get more numbers key; resolve the rep after the memory lookup; read a
card at READ COMMITTED; lock in a read; let the card show a contact held by
another rep; keep a
refusal in memory; let the roster add a second partner for an unlinked name; write the memory in its own
transaction; replay across a different body; hash the raw body; drop the key lock; pass
the client's key to `assign_batch` as is; list ids in the shortfall; answer `not_yours`
as itself; show another rep's own history; name another rep; let the card's
`goes_back_on` differ from the expiry; match every phone on a name search. Migration
`0020` applied to `mailengine_dev`.

## 9. For the operator

| # | Question | Answer |
|---|---|---|
| 1 | How should part 6 be cut? | **Answered 2026-10-01: two parts** — 6a the API, 6b running it. Offered that (recommended), "Three parts", or "Keep part 6 whole". |
| 2 | Where does the contract live? | **Answered 2026-10-01: here**, as this document, linked from the NeverMissCall repository. Offered that (recommended), "In NMC, as the hand-off said", or "Both, kept in step". |

## 10. The migration, `0020.the-api.sql`

```sql
alter table partners add constraint partners_sales_rep_id_unique unique (sales_rep_id);

create table api_requests (
  caller       text not null check (caller in ('dialer', 'website')),
  who          text not null,
  key          text not null check (btrim(key) <> '' and length(key) <= 200),
  method       text not null,
  path         text not null,
  body_hash    text not null,
  status       integer not null,
  answer       text not null,
  at           timestamptz not null,
  primary key (caller, who, key)
);

grant select on api_requests to me_user_ro;
```

## 11. Proposed changes to the decision record and documents

| Item | Proposal |
|---|---|
| Hand-off §7, "the contract … with part 6" | The contract is `06a-the-api.md` in contact-engine; the NeverMissCall repository links to it (answer 2) |
| `00-interface.md` §1, §4, §3 | The drafted lines on keys, "a rep sees only what they hold" and the card become this contract's §4.1, §4.5, §4.6 |

## 12. Safety properties

Each revision is checked against these before review.

1. No request is served without a known key, and no key reaches a route outside its
   list; the app never saves settings.
2. No rep route is served for an unknown or inactive rep, replays included, except a
   "don't call me again", which is never dropped. On rep contact routes, a contact the
   rep never held is indistinguishable from one that does not exist, in status and body;
   the card and history show a contact only to its holder. The decided exceptions: a
   former holder's known callers, their own calls received and their own open call
   (5a answer 4, 5a §6); and door B's `held` for a number another rep holds (3.3, 6.1).
3. A success and its memory commit together: never done twice within 90 days; a refusal
   is never remembered.
4. No rule lives in a route.
5. A rep's own contact's history is never shown to another rep; no other rep is named;
   no answer carries a contact the rep never held.
6. A "don't call me again" from a rep who holds or once held the contact is never
   dropped by the API.
