# Current state — 2026-08-07 (later session): PROD RELEASED + FIRST REAL PROD SCRUB DONE; test architecture hardened; CI GREEN

**THE FIRST REAL PROD SCRUB (end of day, operator-approved 🔴, no purge):**
pre-scrub backup `…_1408.dump` → `subscribe_area_codes add 714 760 805 818
916` (prod `dnc_subscriptions` was empty — itself blocking every assignment)
→ suppression_report before (all zeros) → **`dnc_refresh --snapshot
../dnc-lists/2026-08-05` on `mailengine_prod`: checked=24,212 hits=11,551
cleared=0 — EXACTLY the dev numbers**, another independent arrival. Per-code
(checked / listed / dialable): 714: 4,819/2,308/**2,511** (47.9%) · 760:
4,513/2,092/**2,421** (46.4%) · 805: 4,271/2,247/**2,024** (52.6%) · 818:
6,023/2,628/**3,395** (43.6%) · 916: 4,586/2,276/**2,310** (49.6%) — total
**12,661 dialable** across the five codes. All 24,212 events stamped
`registry_version 2026-08-05`; fresh until 2026-08-26 (21-day window).
**No contacts deleted**: non-subscribed-code contacts stay in the spine per
the whole-universe decision — the `dnc_unsubscribed`/`dnc_stale` gates make
them structurally unassignable.

**PROD RELEASE EXECUTED (end of day, operator-approved 🔴, first release
through the new gate):** all four gates green same-day (520 offline · partner
e2e · STRICT integration 2/2 · fresh backup `…_1237.dump` taken pre-release),
then `mail-engine-production` fast-forwarded `16576c5` → `867176f` (14
commits), `make migrate` applied **0011+0012 in sequence** — the flagged
cancel-out question resolved exactly as designed: net-zero, `if exists`
guarded, ledger tail now `…0011.sourced-attribution, 0012.drop-sourced-
attribution`, the two columns ABSENT, contacts 100,445 / partners 3 unchanged.
Tagged **`prod-2026-08-07`**, tag pushed. Prod checkout now carries backup.sh,
so the production-checkout cron is INSTALLABLE (operator one-liner). The prod
DB's collation-version warning (2.42 vs 2.43, the known cluster condition)
surfaced during migrate — harmless here; `ALTER DATABASE … REFRESH COLLATION
VERSION` is a separate operator decision. This is the production app for the
sales-partner program.

**⚠️ CORRECTION — the "first prod sync" REPORTED EARLIER ACTUALLY WROTE TO
DEV.** The session's shell cwd silently reset between calls, so the
sender-off nightly sourced the DEV `.env`: the 25 events (9 PostHog + 15
closes from the LOCAL Medusa mirror + 1 nudge) landed in `mailengine_dev`,
not prod. Caught by explicit-URL cross-DB queries after the scrub; **dev has
been cleaned back to canonical** (25 events + 1 watermark deleted, 100,444
contacts intact). Consequences of the mix-up, corrected: the "prod .env
carries the test Lob key" finding was DEV's .env (prod's Lob is commented
out, correct); the partner-roster finding (4 rows, two unexplained `P-…`
from 2026-08-06, `sales_rep_id` NULL everywhere) was verified against PROD
and STANDS. Lesson applied: every shell call now re-`cd`s explicitly;
verification queries name their database.

**The REAL prod sync then ran (sender off, prod-verified): zero events —
truthfully.** Two causes, diagnosed: (1) **prod `.env` points at PostHog
project `384001`, dev at `515952`** — dev's project is the one holding the
real `?r=` capture events (9 in 45d), so prod's pull returns nothing.
Which project is canonical is an OPERATOR question; if 515952, prod `.env`
needs its POSTHOG_* values updated (red-tier env edit) and the sync re-run.
(2) The close correlation ran against the REAL prod Medusa (25 customers,
5 in-window, 3 attributions) and found 0 qualifying closes — plausibly
correct (smoke-test-era customers), verify at Stage E.

**PROD SCRUB EXECUTED AND VERIFIED (the real one, on the real DB):** see
below — subscriptions 5 codes, checked 24,212, hits 11,551, all stamped
`registry_version 2026-08-05` (an earlier "version None" read was a
wrong-key query, since verified).

**End state: both repos committed and pushed** (mail-engine `main` through the
tz-fix commit; nvermisscall `young` 847aace with the CLAUDE.md amendment), and
**CI's second run is GREEN.** Its FIRST run went red and earned its keep
immediately: `test_ui_waves_shows_dropped_label_and_executed_at` asserted a
PT-rendered literal — the waves template strftimes whatever zone the psycopg
SESSION hands back (server TimeZone, not process TZ), so the UTC runner
rendered 18:38 against the pinned 11:38. Fixed as an operator-approved
frozen-tier escalation: the test now derives its expected string through the
same connection machinery; verified under PT, TZ=UTC, and TZ=Asia/Tokyo (an
astimezone() variant was tried and REJECTED — process TZ and session TimeZone
diverge locally). This was the TZ=UTC owed item's predicted bug class, caught
by CI on day one. Also: three 2026-08-05/06 leftover files (real-parser
suppression tests, TD register, close-feed addendum) rode ahead in a
carry-forward commit.

Still operator-owed: the backup cron one-liner · offsite backup destination.

**Post-push (same day): direct marketing is VERSION 1.1** (operator decision,
`decisions.md`). `make e2e` now runs the partner journey only (green, ~1.5s,
touches no vendor); the Lob mail funnel moved to **`make e2e-mail`**, PARKED —
it re-enters `e2e` and the release gate at un-park, and the Lob asset-outage
chase is closed as out-of-scope. Release gate reworded accordingly. Also fixed:
`make help` had always hidden `e2e` (its grep pattern lacked digits).

**The sales-partner application is ALREADY LIVE end to end (verified
read-only, same day — no NMC changes):** `/us/sales-partners` serves 200 with
the Apply form (the 307 is Medusa's cache-cookie self-redirect) and is linked
from the home page; the sales-partner code is byte-identical young↔production
(young is ahead by docs only); prod Medusa (`website-4zds.onrender.com`) is
healthy and `POST /store/sales-partner-application` answers — a keyed
honeypot-filled probe returned `200 {ok:true}` with zero side effects (the
honeypot short-circuits before validation/email/storage). **There is no
publish step.** The ONE unverified leg is email delivery (operator
notification + Stage-2 auto-reply): the operator submits a TEST application
from the live page — the route stores nothing, so a submission is just the
two emails.

**The `PostHogFeed` integration test is BUILT and COVERED live (same day,
uncommitted):** `tests/integration/test_posthog_feed.py` + the `posthog_feed`
fixture — real auth, real HogQL against the real project, every returned row
asserted against the canonical contract (source/type/external_id/tz-aware
occurred_at/mailer_code present and not 'unknown'), never content; zero events
is a pass. Configured-but-rejected (HTTP error) is deliberately a FAILURE, not
a skip. `make integration` now covers 2/2 seams live (1.6s); the real window
held 9 events (4 visit / 4 cta / 1 signup). Remaining seam: `NmcCloseFeed` —
but decide first whether to pin the current SQL seam or the decided-2026-08-06
HTTP-endpoint contract.

---

# Earlier — 2026-08-07 (later session): the integration tier EXISTS and `NmcDemosClient` has its first test

**The amendment and the first test both landed.** `marketing/CLAUDE.md` now
carries the Rule Zero mutate/consume split and the `make integration` tier
contract (🟢, diff shown). The 🟡 gate was approved and built:

- **`tests/integration/test_nmc_demos_client.py`** — one read-only GET against
  a live local booking-system, asserting the wire contract only (exact six
  fields; `salesRepId` str-or-null — the silent-drift pin; the four counts
  int()-parseable strings — the parse outside the report's `try`). An empty
  partner list passes; content is never asserted.
- **Tier plumbing:** `integration` marker deselected by default
  (`addopts = "-m 'not e2e and not integration'"`), `make integration` target,
  `tests/integration/conftest.py` with the `nmc_demos` fixture
  (skip-if-unconfigured → skip-if-unreachable → return the real client) and a
  terminal summary printing `covered: N / skipped: M (reasons)`.
  `--integration-strict` (Makefile: `STRICT=1`) turns any would-be skip into a
  failure — verified exit 1.
- **Verified, all three paths:** skip path loud and green (exit 0), strict
  path exit 1, and — after the operator restarted the services — the COVERED
  path ran against live booking-system: `covered: 1 / skipped: 0`, both plain
  and `STRICT=1`. The live window shows the rehearsal fixture exactly
  (salesRepId '3': 7 calls / 2 unique / 0 blocked / 1 text — matches the
  2026-08-02 setup). Default suite collects 518/521 with 3 deselected (2 e2e +
  1 integration — offline suite untouched), ruff + pyright clean.
  `NMC_BOOKING_URL=http://localhost:3002` + the local `NMC_API_KEY` are now in
  dev `.env` (untracked), so `make integration` covers this seam whenever
  booking-system is up.
- ⚠️ Minor: the local booking-system `NMC_API_KEY` value was partially echoed
  into session output by a sloppy masking command. Local test key, written
  nowhere; rotate if it ever becomes load-bearing.

**Then the best-practices review landed three more artifacts (same day):**

- **`docs/coding/testing.md` is now the canonical philosophy document** (tiers,
  authority, release gate, risk rule, owed list); `test-plan.md` carries a
  status banner marking it a partially-executed historical spec (its `World`
  harness was never built). Full reasoning: `decisions.md` 2026-08-07 entry.
- **The release gate is defined:** prod release requires `make test` +
  `make e2e` + `STRICT=1 make integration` green same-day, plus the migration
  plan stated. CI-or-not is recorded as an open operator question.
- **The export-compliance invariant exists and kills mutants:**
  `tests/acceptance/test_export_compliance_invariant.py` (frozen) — adversarial
  pool with every violating condition + post-assignment flips
  (`dnc_registry` = the scrub path; raw `do_not_call` = the adversarial
  construction proving export's own predicate, since `suppress()` would also
  release custody); the forbidden set re-derived with independent SQL and
  intersected with the actual CSV; second-pull re-gating pinned. **Verified by
  manual mutant:** deleting `dnc_registry = false` from export's WHERE turned
  both tests red; `service/assignment.py` restored byte-identical (git-diff
  clean). One behavior note learned: the RULE path filters seeds in the WHERE,
  so "seed" is an id-list-path shortfall cause only.
- **The tests ran against `mailengine_test`** (guard already allowlisted it) via
  env override — `mailengine_dev` kept its canonical 100,444 untouched, no
  re-ingest owed. The scratch DB existed already; testing.md documents the
  pattern. ⚠️ New acceptance files still truncate whatever DB they point at —
  the Makefile rewire to default suites onto `mailengine_test` is NOT done.

**Then the six best-practices violations were fixed (operator-approved order):**

- **SR-6 backups EXIST:** `scripts/backup.sh` (verify-then-rename, 14-day
  rotation, always targets prod); first dump taken (16M) and **restore tested**
  (scratch DB, five counts identical, dropped). ⚠️ Cron NOT installed — the
  session was permission-blocked; the operator runs (cron policy 2026-08-07:
  crons live in the PRODUCTION checkout only — dev runs jobs manually/under
  tests):
  `crontab -e` → `10 2 * * * cd /home/young/Desktop/Code/nvermisscall/marketing/mail-engine-production && ./scripts/backup.sh >> $HOME/db-backups/backup.log 2>&1`
  ⚠️ OFFSITE destination still an open operator decision (local-only today).
- **`make test`/`make e2e` now run on `mailengine_test`** (auto-created,
  `scripts/ensure-test-db.py`) — dev survives every run; 520 green in 29s,
  dev verified untouched at 100,444. The re-ingest ritual is dead for make
  targets; bare pytest still follows `.env`. CLAUDE.md hazards updated.
- **Docs:** release gate now ends in `git tag prod-YYYY-MM-DD`; suite-growth
  rule amended (grows by default, deliberate retirement); verb-driven
  arrangement rule for new DB tests; `docs/coding/` declared canonical for the
  two review standards (commands = deployment copies); `architecture-review.md`
  swapped to the mail-engine-adapted version.
- ⚠️ **`make e2e` is RED today for a VENDOR reason:** Lob's test env stopped
  rendering assets — today's postcard (`psc_77c40e71914fb2bd`, `processed`)
  serves 404 for PDF + both thumbnails 15+ min after creation, while a
  2026-08-02 postcard's PDF serves fine. Partner journey green. The frozen
  test is correct and unchanged. **Re-run `make e2e` in a later session** —
  it must be green before the release gate is relied on. Evidence in
  `decisions.md` 2026-08-07 entry.

**CI is DECIDED and BUILT (same day):** `.github/workflows/ci.yml` — Postgres
15 service container, roles + `mailengine_test` created pre-migrations, ruff +
offline suite on every push/PR. Offline-only by design (no vendor secrets);
e2e/integration stay operator-run, release gate unchanged. Verified by running
the suite under the EXACT CI env (everything else blanked): **520 green in
31s** — which surfaced that `web/api.py` hard-reads seven `LOB_*` vars plus
`DROP_PASSWORD` on routed paths; CI sets dummies. First real run: next push.

Remaining owed: `PostHogFeed` + `NmcCloseFeed` integration tests · mutmut over
`service/assignment.py` · fake-fidelity contract tests · TZ=UTC pinning ·
offsite backup destination · e2e re-run (Lob outage above) · backup cron
install (operator one-liner).

---

# Earlier — 2026-08-07: NO CODE CHANGED — the session's output is a test-policy decision and one uncovered seam

**Read this first if you are restarting: nothing was written, nothing was
committed, and the working tree is exactly where 2026-08-06 left it.** The
session was a read of the two PRDs plus a fake-module audit, and it produced one
operator decision and one real gap. Both are unbuilt.

## The operator decision: cross-repo integration tests are REQUIRED

**Operator, this session:** *"Testing is not complete unless you can test third
parties."* Rule Zero's boundary is correct but has been read too broadly — as
"no cross-repo tests at all" — and that over-read is what produced the gap
below. The scope:

- **Lob — deferred, and fine.** Nothing is printing while mail is parked.
  Note that Lob is already the ONE third party with a real integration test
  (`make e2e` hits `api.lob.com` with the test key), so the pattern being asked
  for already exists in the repo; it was just applied to exactly one vendor.
- **PostHog and the local NMC servers — dedicated tests owed.** These feed the
  real nightly and are verified by nothing.

**The amendment (WRITTEN to `marketing/CLAUDE.md` 2026-08-07 — Rule Zero
mutate/consume split + the `make integration` tier contract; uncommitted):**

1. **Rule Zero splits in two.** *Mutating* NMC — edit its code, run its suites,
   start/stop/reconfigure its services, migrate or write its DBs — stays
   forbidden, unchanged. *Consuming* NMC across a published seam — GET an
   endpoint, SELECT through `medusa_nmc_ro` — is allowed, and for anything
   mail-engine depends on in production, **required**. The operator starts
   booking-system; the test detects it and uses it or skips. Starting it from a
   marketing session is still the forbidden act.
2. **A third tier, `make integration` / `tests/integration/`** — beside
   `acceptance/` (frozen gates) and `unit/` (disposable). Marker deselected by
   default, same mechanism as `e2e` (`pyproject.toml:30`).
   - **Read-only across every boundary** (GET/SELECT only) and **truncates
     nothing.** This is the ergonomic point: both existing tiers wipe
     `mailengine_dev`, so today an integration check costs a re-ingest.
   - **Skip-if-unconfigured, fail-on-drift.** Precedent exists at
     `tests/unit/test_dnc_file_registry.py:87` (skips without the real 818
     snapshot, pins hard with it). Unreachable ⇒ skip with a loud reason;
     reachable-but-wrong-shape ⇒ **fail**. Keeps "no red tests, ever" intact.
   - **The runner must print its skips** (`covered: N / skipped: M (reasons)`)
     plus a `--strict` mode where skip counts as failure. A suite that silently
     skips everything and reports green manufactures confidence — that is the
     failure mode to design against.
3. **Targets, in priority order:** `NmcDemosClient` (local booking-system
   :3002) · `PostHogFeed` (real project) · `NmcCloseFeed` (local `medusa_nmc`
   via `MEDUSA_READONLY_URL`).
4. **No new secrets** — `POSTHOG_API_KEY` / `POSTHOG_PROJECT_ID`
   (`jobs/nightly_cli.py:50`), `NMC_BOOKING_URL` / `NMC_API_KEY`, and
   `MEDUSA_READONLY_URL` are all already `.env` vars the nightly reads. And
   `PostHogFeed` already takes an injected `transport`
   (`tests/unit/test_posthog.py`), so the real-transport test is a constructor
   change, not a rewrite.
5. **Caution on PostHog:** assert the *contract* (auth accepted, query valid,
   whatever returns maps to valid Events) and never specific event content —
   live data ages out and the test would rot into a flaky.

## The gap that decision exposes: `NmcDemosClient` has ZERO tests

The fake inventory came out clean — **`seams/fakes.py` holds 7 fakes and every
seam Protocol has exactly one**, no Protocol uncovered, no orphan fake
(`FakePrintApi`, `FakeResponseFeed`, `FakeSender`, `FakeVerifier`,
`FakeDncRegistry`, `FakeCloseFeed`, `FakeDemosClient`), plus ~8 test-local
doubles. But **every other real seam client has a mapping test that fakes only
the transport** — `LobAddressVerifier`, `LobStatusFeed`, `PostHogFeed`,
`FileDncRegistry`, `EmailSender`, `NmcCloseFeed`. `NmcDemosClient` has none.
`FakeDemosClient` covers the *composer's* contract (omit the section when
unreachable, never placeholder); nothing covers the *client's*.

**The live contract currently MATCHES — this is not a live bug.**
`booking-system/src/partner/partner-demo.controller.ts:104-111` returns exactly
`{partners: [{partnerNumber, salesRepId: string|null, calls, uniqueProspects,
blockedCalls, textsForwarded}]}`, all counts as strings, as the seam docstring
claims. The alignment is held by two docstrings in two repos and nothing
executable. booking-system's own spec pins the server side, so drift would have
to be deliberate — but if it happened, nothing in mail-engine goes red.

**Two paths `FakeDemosClient` structurally cannot reach**, because it returns
whatever well-shaped dicts a test hands it:

- **`salesRepId` is compared as a string** (`judgment/partner_report.py:155`,
  `p.get("salesRepId") == str(sales_rep_id)`). If that field ever arrives as a
  number, `mine` is empty ⇒ section omitted ⇒ **silently, forever, no error**.
  A partner just stops seeing their demo line.
- **The `try` covers the call but not the parse.** `partner_report.py:151-154`
  guards `demos.summary()`; the `int(p["calls"])` reads at **158-161 sit outside
  it**. A KeyError there escapes `compose()` at **line 217**, which is **not**
  inside the per-partner isolation `try` at **220** (that wraps only
  `sender.send`). So a shape drift would not omit one section — it would abort
  the report step for **every** partner. 🟡 if changed: it alters the failure
  contract, and there is a real argument for leaving it loud.

**Also noted, not acted on:** the AI client is the only external dependency with
**no seam Protocol and no shared fake** — duck-typed on `complete(prompt) -> str`
(`judgment/composer.py:28`), so five one-method doubles exist across
`tests/unit/test_composer.py` and `tests/acceptance/test_judgment_discipline.py`.
Not broken; the contract just lives in five places.

## Next act

The `marketing/CLAUDE.md` amendment (🟢, write and show the diff), then the first
integration test as the 🟡 gate. **Open question the operator has not answered:
`NmcDemosClient` first (zero coverage + the silent-drift path) or `PostHogFeed`
first (it feeds real nightly data).**

## ⚠️ Fable 5 is unavailable — it runs on usage credits, not plan usage

Diagnosed this session after the `/model` picker refused the switch at 100% plan
usage remaining: **Fable 5 bills against usage credits purchased separately from
the plan, and the balance is zero.** Plan quota and this are unrelated numbers.
A `claude --model claude-fable-5 -p "hi"` probe appeared to succeed and was
misread as proof of entitlement — it returned a generic greeting that proves
nothing about which model answered; the picker's own dialog is the authority.

**Consequence worth knowing before a phase boundary:** `marketing/PRD.md` §11
plans *"Fable 5 review at phase boundaries"*, and this repo defines two subagents
pinned to Fable 5 — `Doc Reviewer` and `Product`. Whether dispatching to them
errors or quietly falls back to another model is **unverified**. If it falls
back, that matters most for `Doc Reviewer`, whose entire value is being a
fresh-context reviewer on a *different* model than the one that wrote the doc.
Confirm before relying on it as a review gate.

## Still owed from 2026-08-06 (unchanged — nothing this session touched them)

1. **`make e2e` has NOT been run** since the partner-sourced back-out.
2. **Dev DB is degraded** — killed ingest ⇒ 6m52s vs ~48s baseline. Remedy is
   drop/recreate with **`template template0`** → `make migrate` → re-ingest.
   Truncate + `vacuum analyze` is not sufficient.
3. **Prod is at `0010`, dev at `0012`**; `0011`/`0012` cancel out so prod needs
   neither — confirm how yoyo handles that skip *before* the next release.

---

# Previous — 2026-08-06: partner-sourced numbers were BUILT and CUT the same day; a referral is now a territory signal, not a lead

**The feature shipped and was reverted within hours, and the reversal is the
result worth keeping.** `f3ce10c` built the collected-numbers arc to
`partner-sourced-leads.md` rev 5; `138ee8b` backed it out in full. Production
never received any of it, nothing was ever imported, and nothing was dialed
under it.

**Why it was cut.** The design bundled three separable things — *acquisition*
(new inventory), *permission* (a legal basis to call), and *custody* (90-day
exclusivity). Only permission was hard, and it did not survive:

- What the CSV collected was **oral, relayed permission**. Both
  16 CFR § 310.4(b)(1)(iii)(B)(1) and 47 CFR § 64.1200(c)(2)(ii) require a
  **signed writing** to exempt a registry-listed number, so a referral supplies
  no basis at all. Rev 5's oral-vs-written reasoning — "~3 months vs. until
  revoked, so 90 days is the shorter of the two" — confused permission with the
  **EBR-from-inquiry** window and is withdrawn in place.
- **The decisive argument was safe-harbor contagion**, not that one:
  § 310.4(b)(3) forgives an *isolated error despite procedures*, and a
  category-wide carve-out is not an isolated error. Waiving the scrub for
  referrals risked the posture for the **whole program**, including the scrubbed
  CSLB calls. Now **counsel Q8(e)**.

**What replaces it needs no code, and already worked.** A referral is a
*targeting* request that takes no shortcut through the DNC gates: the partner
sends a **name and town, never a number** → operator looks it up
(`search_contacts`, web `/contacts`) → assigns by id (`assignment_cli assign
--ids-file`). **The explicit-id path runs the identical `_gate`**, verified in
code — a hand-picked referral is refused exactly like any other candidate.
Clears ⇒ next sheet, dialed with the referrer named in the opener.
`dnc_registry` ⇒ **not callable** (~48%, measured 11,551/24,212);
`dnc_unsubscribed` ⇒ the area-code decision; `dnc_stale` ⇒ tonight's cycle.

**The real value of a referral is territory evidence.** A partner repeatedly
introduced to people in an unsubscribed code is telling us where their social
density is — already an approved expansion trigger (2026-08-01). At the measured
listing rate a mid-tier code (619 · 951 · 310 ≈ 2,100–2,300 core contractors)
yields ~1,100 dialable for $82, about 7¢ each, worked warm.

**What moved, by repo:**

- **mail-engine `main`** — `f3ce10c` (build) then `138ee8b` (revert +
  `decisions.md` reversal entry). Migration **`0012`** drops
  `sourced_by_partner_id` / `permission_at` rather than leaving readerless
  columns — a populated-by-nothing column a future reader might trust is **TD-2
  exactly**. Removed: `service/referrals.py`, two acceptance suites, console
  item 10, `PERSONAL_WINDOW_DAYS`, `contact.permission_recorded`,
  `move_contact`, `reclaim`'s `include_sourced`, the issued/sourced holdings
  splits. **The safety-critical revert is `service/assignment.py`:** the export
  is back to an unconditional `dnc_registry = false`, and the `if not personal:`
  branch that could skip it is gone, along with the LEFT JOIN that let batchless
  contacts onto a sheet. Won-termination returned to the batch-pointer predicate
  (`set_owner` nulls the pointer on return to house, so it never re-selects).
- **Kept from `f3ce10c`** (rode along, unrelated): the DNC file registry, the
  portal scripts, `jobs/console.py`, `batch_checkpoint`, the **`area_code`
  assignment-rule key** (which closes the multi-code partition gap), and
  `partners_cli status`.
- **nvermisscall `young`** — `8197319` counsel memo **Q8** (referred numbers,
  five sub-parts; catch-all renumbered to Q9) plus a §1 fact and a §2 bullet on
  the written-permission requirement; `dd49227` **rule 2** in
  `partner-dialing-procedure.md` ("Referrals: get the name, not the number"),
  rules 2–7 renumbered 3–8, acknowledgment now cites rules 1, 2, 3, 5. The rule
  sets the ~50% expectation *before* a partner discovers it and invites the
  area-code request explicitly.
- **`partner-sourced-leads.md`** now opens with a **DEFERRED** banner — what was
  cut, why, what partners do instead, and the shape to build if revived (the
  *inverse* of rev 5: scrub first, then 90 days on survivors, unsubscribed codes
  never reaching a sheet). The body is kept for the reasoning.

**Known gap, accepted:** `move_contact` went with the feature, so nothing
adjudicates `already_assigned` when two partners claim one contact. At two
partners over 100,444 contacts the answer is "leave it"; it is in history at
`f3ce10c`.

**⚠️ `marketing/CLAUDE.md` is NEW (uncommitted, lands in the PARENT repo).**
Rule Zero is a scope boundary: working under `marketing/` means mail-engine, and
NMC service code is never edited, tested, or run — with the narrow exception of
the partner-program docs that live in the parent repo. It exists because the only
CLAUDE.md that loaded here was the root's, which is entirely NMC context; asked
for "a full test" this session, that produced a run of `test---layer1/2/3.sh`
against NMC (Layer 3 spending real OpenAI money) before it was caught. The file
also records mail-engine's own test surface — **`make test` + `make e2e`, and
neither needs ngrok or the NMC services**.

**Gates:** **518 offline tests green**, ruff + pyright clean, after the back-out.
**`make e2e` has NOT been run this session** — that verification is still owed.
Dev DB verified canonical afterwards: **100,444 contacts · 102,431 intake · 0
duplicate phones**, migration head `0012`.

**⚠️ Dev-DB performance is degraded and the fix is pending an operator act.** An
ingest was killed mid-transaction (a 2-minute tool timeout), which is exactly the
documented bloat condition: the recovery re-ingest took **6m52s against a ~48s
baseline**. Data is correct; speed is not. The remedy is drop/recreate
`mailengine_dev` (**`template template0`** — this cluster's `template1` has the
collation mismatch) → `make migrate` → re-ingest. Verified safe: 0 active
connections, `me_user` owns it and has `CREATEDB`. Truncate + `vacuum analyze`
is **not** sufficient.

**One prod-release note:** `mailengine_prod` is at **`0010`**; dev is at `0012`.
`0011` and `0012` cancel out, so prod needs **neither** — confirm how yoyo
handles that skip *before* the next prod release rather than during it.

**Also this session:** `docs/main_contacts.csv` (681 rows) was diffed against the
spine — 663 already ours by phone, 1 in-file duplicate, leaving **17 new rows,
every one in an unsubscribed area code** (941 ×15 Sarasota/Venice FL, 201 NJ,
321 FL). Under the DNC gates that file yields **zero usable leads**; it is a
Florida block, not a CA one. Contact-data CSVs are now gitignored
(`*-leads.csv`, `docs/main_contacts*.csv`) — real rows live beside the repo, as
`ingestion-app-1/` and `dnc-lists/` already do.

---

# Previous — 2026-08-05: DNC subscription is LIVE and all five files are DOWNLOADED; the format question is settled by real bytes

**The FTC wait is over.** The subscription provisioned overnight (filed
2026-08-03, live by 2026-08-05 — the portal's "~1 day" was nearly honest).
`dnc-status.py` flipped to LIVE with five URLs; all five full files were
fetched the same morning and sit in `marketing/dnc-lists/2026-08-05/`
(zips unopened, CRC-clean):

| Area | Numbers | Area | Numbers |
|------|---------|------|---------|
| 714 | 1,591,200 | 818 | 1,469,394 |
| 760 | 1,464,756 | 916 | 1,536,340 |
| 805 | 1,272,857 | **Total** | **7,334,547** |

- **The five provisioned codes are 714 · 760 · 805 · 818 · 916** — the top-5
  by measured contractor density, NOT the Chatsworth derivation set
  (818·805·310·661·323). 310, 661, 323 are not subscribed; if partner #1's
  sheet needs them, that's a purchase decision, not a download.
- **Direct GET on the URLs 404s.** The file only comes through SOAP
  `GetDNCFileByUrl(fileUrl, strSessionToken, strCoID)` → base64 inside the
  envelope. **`scripts/dnc-download.py` (NEW, uncommitted)** does the whole
  cycle: login → GetURLS → fetch-what's-missing, raw-response-first so a
  decode bug can't lose the once-per-day fetch, skip-if-on-disk so re-runs
  are free, CRC via streaming `zipfile`. `--only 818` for one code.
- **The full-list format is SETTLED by real bytes: `AAA,NNNNNNN` LF-terminated**
  (comma-delimited area code + 7-digit local; e.g. `818,0000818`). Verified
  across all 7.33M lines: 0 malformed, 0 wrong-area, no CRLF, no header row.
  The `8185551234` 10-digit guess is DEAD. `tests/fixtures/dnc/` (full-list
  half) can now be pinned to this; the CHANGE-list format remains unverified.
- **The real registry client is BUILT (2026-08-05, test-first, 🟡 gate
  approved):** `seams/dnc_registry.FileDncRegistry` over a snapshot dir;
  Protocol verb changed `numbers(area)` → **`listed(area, candidates)`** (the
  decided streaming inversion). Every anomaly is a loud `DncRegistryError`
  (absent/ambiguous zip, malformed or wrong-area line, CRC failure).
  `dnc_refresh` gained `--snapshot DIR` (one `listed()` call per area code,
  aborts before stamping on registry error); the `--fake`-only era is over.
  9 new unit tests incl. a skip-if-absent pin over the real 818 zip; suite
  490 green, ruff + pyright clean. Fixtures README: full-list format now
  VERIFIED; change-list half still unverified.
- **The FIRST REAL SCRUB ran on dev (2026-08-05), post re-ingest to canonical
  100,444:** `dnc_refresh --snapshot ../dnc-lists/2026-08-05` →
  **checked=24,212 hits=11,551 cleared=0** in 4m18s, all events
  version-stamped `2026-08-05`. **~48% of contractor phones are on the
  consumer DNC registry** (714: 47.9% · 760: 46.4% · 805: 52.6% ·
  818: 43.6% · 916: 49.6%) — sole props registering personal cells, the
  exact Chennette population the Q6 memo covers; the scrub takes them out
  conservatively. **818 dialable pool = 3,395 of 6,023** → partner #1's
  real arithmetic is ~17 batches of 200, not ~30. Dev-only: the prod scrub
  stays a C3/cutover-day act. `dnc_subscriptions` (dev) now records all
  five codes.
- Calendar note: 12-month renewal runs from purchase (2026-08-03).

---

# Previous — 2026-08-04: DNC download is FILED and blocked on the FTC; the C3 rehearsal is now the only thing moving

**Where the week stands.** The DNC arc got as far as it can without the
government: the subscription for **5 area codes was filed 2026-08-03** (portal
promised ~1 day, said chase at 3 — call it a week). Everything downstream of it
— the real scrub, partner #1's first legal dial — waits on that queue. **C3 is
therefore the only live critical path, and it is blocked on nothing but the
operator running `scripts/partner-rehearsal.sh all`.** Nothing has ever sent a
real mail-engine email yet.

**The DNC registry design is now DECIDED and recorded** (`decisions.md`, three
entries — read those, not this summary, for the reasoning):

- **Files, never a database table.** The registry is an *input, not a record*:
  we already persist the only part that matters (`contacts.dnc_registry` /
  `dnc_checked_at` + the version-stamped `contact.dnc_checked` event). The
  inversion that settles it — we never ask "what is on the registry?" but
  "which of MY 6,023 numbers in 818 are on it?", so the set in memory is OURS
  (~1 MB) and their file streams past it. Deciding factors were **backup
  propagation** (a table of 10M consumer numbers copied into every DB backup
  forever) and moving parts, NOT performance. Flips only if change lists ever
  become worth having.
- **Layout: `marketing/dnc-lists/<YYYY-MM-DD>/`** — sibling to both checkouts
  (`../dnc-lists/`), gitignored, same pattern as `ingestion-app-1/`. The
  directory name IS the registry version stamped on check events. **Keep the
  portal's `.zip` unopened** — parser streams via `zipfile`, and the CRC is a
  free completeness check (a truncated flat file looks valid and would silently
  under-block, putting registered consumers into a partner's sheet).

**The portal has a documented API, and it was exercised LIVE (2026-08-04):**
`DownloadSvc.asmx` — target namespace and SOAPAction prefix are the same string.
`Login(coID, pwd, userType=Downloader, enumCertify=Agree)` → **`LoginOK`**, so
**certifying programmatically is legitimate — no web click needed**; the whole
monthly cycle can automate. Side effect: **the Downloader password question is
RESOLVED** — the change DID go through despite the portal's system-failure
message (vault updated; the portal-issued original is dead). But
`CanGetFullFile` and `GetURLS` both return `InvalidRequest` with a fresh token
in either format — **the account has no area-code subscription provisioned yet**,
which the filing timeline explains. `GetDNCFileByUrl` was never called, so the
once-per-day allowance is untouched.

- **`scripts/dnc-status.py`** (NEW, uncommitted) turns the wait into one
  command: logs in, calls `GetURLS`, prints LIVE/PENDING with the chase date
  baked in. Exit codes are cron-shaped (0 live / 1 pending / 2 error) and it
  does NOT consume the daily download. Currently prints PENDING.

**⚠️ The DNC sample fixtures are NOT format-authoritative.**
`tests/fixtures/dnc/` was built from a search-engine synthesis and is now marked
UNVERIFIED in its README — public sources **contradict each other** (full list:
`8185551234` vs `818,5551234`; change list: comma-delimited vs **fixed-width**).
Our fixtures assumed plausibly the worst mix of the two. **Pin the parser to the
portal's Data Demo sample or the first real download — never to our guess**
(the repo's verify-external-facts rule; the seam docstring says the same).

**Secrets were swept out of all tracked documentation (2026-08-03).** New vault
at **`~/.config/nvermisscall/keys.md`** (chmod 600, outside every repo,
extending the `~/.config/render/api-key` precedent); repo docs and memory now
only POINT at it. Two findings worth acting on: a block labeled *"Fake
credentials (safe for testing)"* in `docs/backlog/TWILIO-A2P-10DLC-ISV-REFERENCE.md`
held the **REAL prod Twilio SID + auth token** (byte-identical to
`booking-system/.env`), and `test-services/docs/PRD.md` carried an
`api-service-key` whose shape suggests it may be the **prod `NMC_API_KEY`**.
Both are rotation candidates — and scrubbing the working tree does NOT scrub git
history. The **SAN Organization ID `10337886-60999`** is recorded (identifier,
not a secret); portal passwords live only in the vault.

**Contractor density, measured (for area-code choice).** Core trades only
(plumber + HVAC + electrician), phones present: **818 = 4,367** (1,501 / 871 /
1,995) — a 50% lead over #2, and it strengthens when the painter/landscaper/
roofer filler is excluded. Then 714 (2,914), 916 (2,627), 760 (2,540), 805
(2,358), 619 (2,283), 951 (2,198), 310 (2,103 — plumber-rich), 909, 707. The
org's 5 free codes cover ~14,800 core companies ≈ 74 batches of 200 pre-scrub.
**There is no locksmith data** — the six loaded trades are electrician, plumber,
painter, HVAC, landscaper, roofer; locksmiths are generally not CSLB-licensed,
so they would need a different source entirely.

**Also today:** `jobs/subscribe_area_codes --help` now carries the full
"how to get the DNC list for an area code" procedure (SAN login → add code →
download full list → record + scrub → calendar the 12-month renewal), since
that CLI is the front door where the claim gets made.

**Uncommitted here:** `scripts/partner-rehearsal.sh`, `scripts/dnc-status.py`,
`tests/fixtures/dnc/`, the three `decisions.md` DNC entries, the
`subscribe_area_codes` help text. In the PARENT repo: `marketing/.gitignore`
(dnc-lists), the PRD/doc secret scrubs, and the ceremony doc's queued-follow-up
section.

---

# Previous — 2026-08-02 (later session): C3 IS RUNNING — Stages A/B/C done, D staged for LOCAL testing; the dress rehearsal script is the next act

**The ceremony has a doc and a ledger** (parent repo,
`docs/active/to-do-partner-report-c3-ceremony.md` — placement rule: parent-repo
work executes in PARENT sessions, mail-engine work here). Progress today:

- **Stage A ✅** — the partner-lifecycle e2e journey committed (`16576c5`) and the
  FULL 22-commit partner arc pushed to origin. The journey (`tests/e2e/
  test_partner_journey.py`) walks intake → partners_cli → subscribe 818 →
  fake scrub → assign (every gate named) → export → nightly (close, won-
  termination, report via the real Sender/captured socket) → replays → reclaim;
  green beside the mail funnel under `make e2e` (10.6s); fakes ONLY where
  local-real is impossible.
- **Stage B ✅ (parent session)** — B2 was discovered NOT deployed (impressions
  came from Toolkit Phase 5); now merged `ec7fac6`, live on Render, smoke
  401-unkeyed / 200-keyed with real rep-3 aggregates.
- **Stage C ✅** — prod released: fresh dump `~/db-backups/
  mailengine_prod-2026-08-02.dump` (16 MB), prod checkout `a027210` → `16576c5`,
  migrations **0009+0010 applied to `mailengine_prod`**, partners seeded,
  contacts 100,445 unchanged, `suppression_report` ALL ZEROS — and the zeros are
  a **trusted instrument reading**: a six-case known-answer validation on dev hit
  the prediction on all seven fields, and a real `recompute_state()` landed every
  case exactly where the simulation said. Dev restored to canonical after.
- **Stage D ⏳ staged for LOCAL testing** — prod `.env` gained `SMTP_*` (login
  verified live), `MEDUSA_READONLY_URL` (verified), and — operator decision —
  `NMC_BOOKING_URL=http://localhost:3002` + the LOCAL booking-system
  `NMC_API_KEY` for the local test era (prod URL commented beside it; flip both
  at go-live). **`LOB_API_KEY` is commented out**: the prod checkout held a LIVE
  Lob key; darked during testing per the guard's live-key principle (restore at
  mail un-park; TD-9 rotation now urgent — the key appeared in session output).
  Partner row `Young-partner` (rep 3, operator email) created in prod. Findings:
  **`nmc_partner_code` is EMPTY on prod** → close crediting runs the `sold_by`
  leg (operator sets `sold_by=3` on the attribution row, the S98 manual path);
  prod `NMC_API_KEY` exists ONLY in Render env (nowhere on disk).
- **Stage E NOT run.** The permission classifier blocks this session from
  running the prod nightly (and local psql writes) — the operator runs those by
  hand. Nothing has ever sent a real mail-engine email yet.

**The next act: `scripts/partner-rehearsal.sh` (UNCOMMITTED) — the operator-run
local dress rehearsal.** Full story on disposable data: partner signs up → 818
subscribed + fake-scrubbed → **200 contacts assigned (gates make them all-818)**
→ export → an assigned contact "buys" (rows in local `medusa_nmc`) → operator
credits `sold_by=3` → nightly via the REAL `nightly_cli` (first-ever execution:
env feed-building, real PostHog pull, real close-feed SQL, real SMTP send) with
the predicted email printed before the run. Prereq `check` passes; local
booking-system demo rows moved to rep 3 (7 calls / 2 unique / 0 blocked / 1
text); local mirror holds 82 customers in the 45-day window (they ingest
uncredited — only the buyer shows in the report). Then Stage E proper: prod
nightly, operator test-signup + credit, cron, ledger.

**Design clarifications pinned today:** "assign an area code to a partner" =
the onboarding sequence (derive → purchase at SAN portal → `subscribe_area_codes
add` → scrub → batch), per the superseding one-code-to-start decision — NOT a
schema binding; **gap queued (🟡 when partner #2 onboards in a different code):
no `area_code` assignment-rule key exists**, so multi-code batches can't be
partitioned per partner yet; **queued follow-up (approved 2026-08-03): a
partner-ops umbrella CLI** — `jobs/partner_onboard.py` (one interactive command
walking derive → SAN-purchase pause → subscribe → scrub → assign → export;
`scripts/partner-rehearsal.sh` is the prototype) + a `partners status` view,
🟡 AFTER the rehearsal runs, spec'd in the C3 ceremony doc § Queued follow-up.
**TEXAS is the first expansion state after C3**
(shared typed intake table + `source` column direction; TX telemarketing law on
the Q6 agenda). Holdings verification stays deferred past C3 — never fake-scrub
prod.

---

# Earlier — 2026-08-02: SALES-PARTNER SYSTEM IS PRIMARY; build complete, waiting on two operator clocks

**The priority pivot (operator, 2026-08-01, `decisions.md`):** the sales-partner
system is the primary product; **direct mail PARKS** — wave 1, the audience-scoped
AV mode, the ghost wave, the live Lob key, creative all wait. Parked machinery
consumes nothing. mail-engine itself does NOT park: the partner spine (contacts,
custody, DNC, exports, report) IS mail-engine. Named consequence: partners dial
COLD lists until mail resumes — set partner expectations accordingly.

**Scope: NATIONWIDE, no area restriction in principle.** DNC subscription policy,
FINAL after three same-day refinements (`decisions.md` has the evolution):
**every partner starts with ONE area code** (their densest, from
`jobs/derive_area_codes.py` on their base ZIP) · **more on request when doing
good, NO cap for performers** (the request is the qualifying event, like the
refill; observables: batch worked down / closes / demo-line activity) · operator
approves each $82 purchase (org's first five free, FY2026 verified) · seed 2 at
onboarding only when #1 is thin (rural/overlay metros). **Partner-held SANs
REJECTED on 16 CFR §310.8** — the fee binds the SELLER (NMC); NMC holds the one
SAN, partners receive pre-scrubbed exports.

**The area-code derivation is BUILT and the old dispute is settled**
(`jobs/derive_area_codes.py` + pinned Census 2023 ZCTA centroids in `config/`):
Chatsworth 20 mi → **818 · 805 · 310 · 661 · 323** = 89.2% of 6,971 in-radius;
**747 ranks #6 (143) — 661 wins at every radius**, as revisions 4–5 predicted.
Re-run per partner at onboarding; record via `subscribe_area_codes`.

**Paper is drafted, counsel-ready** (root repo `docs/`):
`partner-dialing-procedure.md` (the safe-harbor written-procedures prong + five
agreement clauses) and `counsel-memo-dnc-b2b.md` (the Q6 memo: the operator's
B2B/held-out-publicly theory for stress-testing, **Chennette v. Porch.com (9th
Cir. 2022)** as the on-point adverse authority, postures A/B/C). Send both AHEAD
of the counsel hour.

**Nationwide build consequences, queued (not started):** per-contact timezone +
calling-window enforcement on exports (§6's CA-only waiver dies with CA-only);
per-state intake sources when list acquisition starts (timing undecided); state
registries/registration on the counsel agenda.

**What blocks the first legal dial: two operator clocks + one ceremony.**
1. **SAN registration** (telemarketing.donotcall.gov, NMC EIN) — **STARTED
   2026-08-03: Organization ID `10337886-60999`** — then
   `subscribe_area_codes add 818` (John's #1) and the real FTC client gets built
   against the first downloaded file.
2. **Q6 counsel hour** — memo + procedure ready to send.
3. **C3 prod ceremony** 🔴 (below) + B2 deploy + repo pushes — on request.

---

# Previous — 2026-08-01: Stages A, B, AND C1/C2 complete — the partner report exists end to end; C3 (live verification) is the remaining prod-day ceremony

**Stage C1+C2, DONE 2026-08-01 (operator gate; guard-keep decision):**

- **C1** — `seams/email_sender.py` is the real Sender (TD-10's fix): SMTP via
  `SMTP_*` env (house Gmail pattern), recipient from the partner row, first line
  of the message = subject, LOUD failure on null/`sms`/unknown channel. Dark until
  the env is set (deliberately unset — C3's act). **S-7 flip landed**
  (quiet_reengage + lost_aging → YOUNG). **The sender-None recording guard is
  KEPT permanently** (operator decision at the gate, design S-7 note amended) —
  a senderless nightly can never burn a partner nudge.
- **C2** — `judgment/partner_report.py`: cadence (heartbeat 7d / batch / removal
  triggers), the three design sections (holdings + re-pull, closes with
  orphaned-close "details pending", demo line via `seams/nmc_demos.py` → B2,
  omitted when unreachable), house excluded, stamp-only-after-successful-send,
  per-partner failure isolation, runs LAST in the nightly after expiry.
  `MEDUSA_READONLY_URL` is SET in dev `.env` (local mirror) — the close feed is
  live locally.
- **C3 remains** — the prod-day ceremony: mail-engine prod release (migrations
  0009+0010 + `suppression_report` review) · set SMTP_* + NMC_BOOKING_URL/KEY +
  prod `MEDUSA_READONLY_URL` (PRD credential) in the prod checkout's `.env` ·
  operator-as-partner receives the first real report · verify holdings/closes/
  demo-line against real data (test identity yk@nevermisscall.com, demo number
  818-418-0546) · only then does a real partner enter the send list.
- Suite: **477 offline tests**, ruff + pyright clean.

---

# Previous — 2026-08-01: Stages A AND B complete — the queue is Stage C (Sender + composer)

**Stage B, DONE 2026-08-01 (operator-approved gate + B-GATE decision):**

- **B1 reconciled** — mailer-code classification against our own `pieces` (noise →
  null), the 45-day-floor test (already correct), same-run orphan re-resolution on
  phone backfill. The backfill tests caught and fixed a live Batch C defect
  (`payload || json` missing its `::jsonb` cast — the path had never been
  exercised). The `_build_feeds` contradiction was escalated and the PROJECT PLAN
  amended (operator-ratified): the close feed keeps its pinned dedicated slot.
- **B2 shipped dark** (core repo, booking-system): `GET
  /api/partner-demo-calls/summary?from&to` — per-partner_number aggregates,
  anonymous-sentinel rules, latest-non-null salesRepId, BigInt-as-string. 792
  booking-system tests green. Nothing calls it until C2. Normal core-repo deploy
  gates apply when it ships to prod.
- **B-GATE decided: (2) sequenced + (3) regardless** (`decisions.md` 2026-08-01) —
  retire PostHog's `signup.completed` only after the close feed is proven on real
  closes; all readouts count DISTINCT CONTACTS reaching `won`, never event rows
  (binds on the readout/accrual code when it gets built).
- **Turn-on remains a deliberate act:** set `MEDUSA_READONLY_URL` in `.env`
  (local mirror for dev, the PRD credential for prod). Unset everywhere today.

---

# Previous — 2026-08-01: partner build CODE-COMPLETE in dev — Stage A (Phases 1, 2, 4) all landed

**Partner lead assignment** (`partner-lead-assignment.md` rev 7 + implementation plan,
batched per ground rule 5) is the active build:

- **Batch A — Phase 1 DONE** (`dd88a4b`): migration `0009` (partners incl. R1 report
  columns, assignment_batches, feed_watermarks, `owner_id`), `set_owner` single emitting
  writer, `current_owner` derivation, partners CLI with the registration runbook.
- **Batch B — Phase 2 DONE, 🔴-approved 2026-08-01** (committed on top of `a027210`):
  the suppression split + DNC scrub. Migration `0010` (`do_not_call`, `dnc_registry`,
  `dnc_checked_at`, `address_undeliverable`, `dnc_subscriptions`,
  `suppression_tombstones`); per-channel `suppress(contact_id, channel, reason)` +
  `clear_suppression` (dnc_registry only); derivation **v3** (`is_suppressed` = opt_out
  reading `payload.reason`; returned≥2 → `address_undeliverable`, written by recompute);
  `_audience_where` gains the undeliverable clause and keeps the stage backstop;
  `record_note` restricted to `note.*`; tombstone consult in `load_list`;
  `seams/dnc_registry` + `FakeDncRegistry`; `jobs/dnc_refresh` (21-day cycle,
  version-keyed idempotency, delisting clears), `jobs/subscribe_area_codes`,
  `jobs/suppression_report` (the before/after deliverable — **run it against PROD and
  review before the first post-deploy nightly**; all-zeros on fresh dev, as expected);
  `dnc_version_alert` judgment rule. **422 offline tests**, ruff + pyright clean.
  ⚠️ The real FTC registry client is deliberately unwritten — the portal file format is
  unverifiable until the SAN exists (Phase 0); `--fake` unblocks dev, the nightly scrub
  stays unconfigured (`nightly_cli` passes `dnc_registry=None`).
- **Batch C — Phase 4 DONE, nodded + built 2026-08-01** (assignment verbs + jobs;
  Phase 3 deferred to Stage C1, Phase 5 unscheduled): `service/assignment.py`
  (assign_batch with §5 derived counts / explicit override / id-list cutover form,
  idempotent retry receipts, every S-1 gate as a named shortfall cause, for-update
  locking against `suppress()`; export_batch stamping `last_export_at`; reclaim;
  expiry + won-termination nightly steps slotted after recompute / before digest),
  the **sender-None recording guard** in `digest.run` (partner hits skipped
  entirely until Stage C1 — remove it there), and the **Q10 close correlation**
  (`seams/nmc_closes.py` per the ratified contract §2, `jobs/close_correlation.py`
  with the 45-day watermark rule + consumer-side double-count guard, nightly slot
  after resolve_orphans / before recompute; real feed gated on the select-only
  Medusa role — `nightly_cli` activates it only when `MEDUSA_DATABASE_URL` is set).
  `jobs/assignment_cli.py` is the operator front door and the cutover tool.
  **444 offline tests**, ruff + pyright clean. **Not deployed to the production
  checkout** — migrations 0009+0010 and the first `suppression_report` review are
  the deploy-day steps.
- **The cutover runbook (the day John's first real batch is issued):** roster row on
  the main site → `partners_cli set` with `--sales-rep-id`/`--partner-code` →
  `subscribe_area_codes add <codes>` → a `dnc_refresh` pass (real registry — needs
  the SAN) → `assignment_cli assign John --key john-cutover --ids-file <surviving
  sheet rows>` → `assignment_cli export John`. Sheet void from that date.
- **Phase 0 operational items still open:** SAN registration (start now — lead time
  unknown), Q6 counsel hour, area-code re-derivation script, paper prongs, the PRD/
  partnership-program amendments.
- **The AV gate is LANDED (2026-08-01)** — verification is armed ONLY by the dedicated
  `LOB_AV_API_KEY` (unset everywhere, so the gate shipped closed); the print key never
  arms it. The armed-nightly hazard is closed. Turning AV on later = set the var to the
  LIVE key (never test — canned `undeliverable`, permanent) + build the audience-scoped
  verify mode (still the one missing enabler for verify-what-you-mail).
- **A0 + A2 are DONE (2026-08-01) — Stage A of the project plan is COMPLETE.**
  `medusa_nmc_ro` exists on prod Medusa (SELECT on exactly customer /
  nmc_sales_attribution / nmc_partner_code; credential in root PRD § Production
  connection strings, committed `f6c04ff`) and mirrors locally. `db/medusa.py` is the
  third-connection helper (`MEDUSA_READONLY_URL`; unset = feed off, no throw); the
  close feed + nightly CLI read through it, and `tests/guard.py` refuses to run the
  suite in a folder holding a remote Medusa credential. **The referral/sales tables
  ARE live on prod Medusa** (verified during A0 — 25 customers, 3 attributions), so
  Stage B1 turn-on is now purely: set `MEDUSA_READONLY_URL` in `.env` after the
  B-GATE §7 look.
- ⚠️ **Post-kill ingest slowness recurred 2026-08-01**: a re-ingest after a killed run
  took **12m9s** despite truncate + `vacuum analyze` — truncate is NOT a sufficient
  remedy; only drop/recreate restores ~48s (blocked that day by pgAdmin's superuser
  sessions holding the DB). Counts were still exact (100,444 / 102,431).

---

# Previous state — 2026-07-29: **the grain migration is COMPLETE and LIVE IN PRODUCTION**

All four phases are done. Batches A–C shipped the code; **Phase 4 executed against
`mailengine_prod` on 2026-07-29** and committed. Production is now business-grain and
phone-unique: **100,445 contacts** (100,444 list + 1 seed), down from 102,432.

The full-list `verify_addresses` backfill (design §7 step 9) is **deferred indefinitely**
(decided 2026-07-30, `decisions.md`): verification now runs **pay-as-you-go over what is
about to be mailed** (Lob Developer, $0.05/lookup, no plan — ~$50 for a 1K wave), gated
only on the live Lob key. TD-11's plan questions reopen only if a full-list pass ever
becomes worth doing. The grain work is otherwise finished; the queue moves to
`partner-lead-assignment.md` revision 7.

## Where we are

Gates green: **375 offline tests** (was 349 after Batch B, 315 before it), ruff +
pyright clean, e2e journey green against the real Lob test environment. Migrations **0001–0008** applied, plus
`migrate_grain`'s in-script swap. Dev DB holds **100,444 contacts / 102,431 intake rows**.

### Batch A — Phase 1, DONE (`6a99ac0`, pushed)

Additive only; no live-path behaviour changed, nothing dropped, `migrate_grain` wired
nowhere.

- **Migration `0008.intake-split.sql`** — `intake_cslb_ca` + `intake_fbn_ca` at full
  §2.1 shape, `contact_merge_map`, `contacts.seed_key`, plain index on
  `pieces (contact_id, wave_id)`, and the `unique (contact_id) where is_primary`
  partial index.
- **Adapters emit `trades`** — sorted distinct union, so `C20|C36` → `hvac|plumber`.
  `trade` keeps first-match priority, unchanged, because it feeds segment. FBN emits empty.
- **`AddressVerifier` seam** — Protocol, `VerificationResult`, the verbatim verdict enum,
  and `AddressVerificationError` as a **distinct type**. §5 pins a verdict as a result
  (stamp, never re-call, *including* undeliverable) against a vendor error (stamp nothing,
  next run retries). `FakeVerifier` reaches all four cases from its constructor. The Lob
  implementation is Phase 3's job.

### Batch B — Phase 2, DONE (`4142c52`)

One commit, because the phase has no green intermediate and the swap and its surviving
code cross one boundary together.

- **`load_list` is resolve-then-insert** — `SOURCE_REGISTRY` raises before a row is read;
  resolution runs in memory per file (CSLB by phone, FBN per filing); a group whose phone
  already has a contact ATTACHES without re-picking, with `do_not_mail` OR-merged as the
  single contact field an attach writes.
- **§3's pick rule now lives in `resolution/pick.py`** — one definition, imported by both
  `load_list` and `migrate_grain`. §4's equivalence claim is only true while there is one;
  ground rule 2 bars `service` from importing `jobs`, so neither caller could own it.
  `migrate_grain` re-exports the names, so its unit tests import unchanged.
- **`resolve_audience` returns `ResolvedAudience`** — undeliverable exclusion runs BEFORE
  delivery-point dedupe, which is what stops an undeliverable contact winning a keeper
  pick and taking a deliverable duplicate with it.
- **Also:** trade filter is an intake `exists` over the `trades` array (unioned per intake
  table); `execute_wave` re-keyed on `mailer_code`; `search_contacts` reads trade/list_key
  through a lateral, pipe-delimited; `ensure_seed_contacts` on `seed_key`; `retire_seed`
  and `update_contact_address` verbs + routes; `ensure_swapped` wired into `make migrate`
  and the test-DB setup.
- **34 new frozen acceptance tests** (§10 tests 1–6, 8, 10 + the re-run guard's three
  branches, which use a real scratch database).

**The evidence that matters.** The dev DB was rebuilt through the **new** `load_list` and
landed on **100,444 contacts** — the design predicted ≈100,444 from the canonical CSV in
July, the dry run derived it from the populated database, and this is a third, independent
arrival at the same number. Invariants checked rather than assumed: exactly one primary
per contact (0 violations), 0 duplicate phones, 0 FBN contacts carrying a phone, 4,723
multi-trade intake rows, 1,987 rows merged away.

**Two judgement calls worth knowing.** The frozen tests were **not** written test-first —
the circular dependency (phone-uniqueness needs the swap; the swap needs `execution.py`
converted) makes a runnable RED suite impossible — so they were mutation-tested instead:
inverting the tie-break broke exactly the two tests pinning it, disabling the exclusion
broke exactly the two pinning the ordering. And **one assertion was deliberately
inverted**: `test_pre_swap_columns_untouched` pinned the near side of a boundary Phase 2
exists to cross.

### Batch C — Phase 3, DONE

`verify_addresses` implemented against the `AddressVerifier` Protocol fixed in Batch A —
it pins nothing new, which is why it was never its own cut.

- **`jobs/verify_addresses.py`** — the two phases. STAMP sweeps intake rows where
  `std_verified_at is null` and stores the result; a verdict (including undeliverable and
  no-delivery-point) is stamped and never re-requested, a vendor error stamps nothing and
  the next run retries. Each row stamps in its own transaction, so one bad row cannot roll
  back the rows already done or hold up everything behind it. INHERIT copies a usable
  standardized address from a contact's PRIMARY row when `addr_validated_at` is still
  null — the guard that makes re-runs no-ops and stops the job overwriting an operator's
  `update_contact_address` edit.
- **`seams/lob_address.py`** — the real client. Stdlib HTTP, mirroring `seams/lob.py`.
  An unrecognized `deliverability` is deliberately an ERROR, not a verbatim store: §6's
  exclusion reads that column, so a value we don't understand must surface as an
  unverified row rather than silently failing to exclude a bad address.
- **Nightly wiring** — `run_nightly(..., verifier=...)`, skipped when unconfigured. Unlike
  zero feeds, a missing key is not a hard failure: it delays standardization, and
  unverified rows are never excluded from an audience.
- **18 frozen acceptance tests + 8 offline unit tests** over the response mapping. These
  WERE written test-first and watched fail for the right reason
  (`NameError: verify_addresses is not defined`).

**Operator decision recorded (2026-07-29):** the three `deliverable_*_unit` variants are
deliverable-family and **do inherit**. §5 named the blocked outcomes without placing them;
§6 already keeps them mailable. Pinned by `test_the_deliverable_unit_variants_still_inherit`.

Full acceptance record — including what Lob's test environment can and cannot simulate —
is in `ingest-contact-migration-implementation.md` § Acceptance record — Phase 3.

**Exercised against real dev data, bounded and reversed (2026-07-29).** `--limit` makes
this safe to do, and it was worth doing:

- `--limit 5` through the real Lob HTTP client → `stamped=5 errored=0 inherited=0`; five
  real rows stamped with the test key's canned `undeliverable`, and inherit correctly
  declined (contacts untouched).
- A second `--limit 5` stamped five DIFFERENT rows; the first five kept their original
  timestamps to the millisecond — verify-once proven on real data, not just in a fixture.
- `--fake --limit 3` → `inherited=3`, exercising the inherit path the undeliverable
  verdicts could not reach; a follow-up run returned `inherited=0`, so the null guard
  holds.
- Dev was then rebuilt from source, back to 0 verified / 0 validated.

⚠️ **Do not sweep the WHOLE dev database.** With the Lob *test* key every row comes back
`undeliverable` (canned), silently emptying every audience; with `--fake` every row gets
the SAME delivery point, collapsing the entire list to one contact under §6's dedupe.
Bounded `--limit` runs are fine and reversible; an unbounded one is not. The first real
sweep belongs to a live key.

### Phase 4 — production release + data migration, DONE 2026-07-29

Not a coding batch: an operator ceremony, executed in this order. **Nothing was merged** —
mail-engine has one branch (`main`) and two checkouts, so "prod merge" (the name until
2026-07-29) described a git operation this repo does not perform.

**How production works here:** `marketing/mail-engine/` on `mailengine_dev` is where work
happens; `marketing/mail-engine-production/` on `mailengine_prod` is production. Same
Postgres instance, same branch, different checkout.

**What was run:**

1. `pg_dump` of `mailengine_prod` → 27 MB (kept in the session scratchpad; **not durable —
   re-take one before any future migration**).
2. Migration `0008` applied. Additive; contacts unchanged at 102,432.
3. **Dry run** — full report over all rows, then rolled back. Verified untouched afterwards.
4. Operator read the report and approved.
5. Release: production checkout `c99033d` → `3b989c3` (29 commits, all three grain batches).
   `.env` is untracked and survived.
6. `migrate_grain --execute` — committed.
7. `recompute_state()` — 100,445 contacts updated (step 7).

**Result, verified against the database:**

```
contacts        102,432 -> 100,445   (-1,987)
intake rows               102,431    (84,072 CSLB + 18,359 FBN)
merge audit                 1,987    one row per merged loser
pieces / events                 0    unchanged (production has never mailed)
swap            list_key/trade/license_class dropped;
                contacts_phone_unique created;
                old pieces (contact_id, wave_id) constraint gone
integrity       0 duplicate phones · 0 orphaned intake FKs ·
                exactly one primary per NON-SEED contact · seed intact
                (seed_key set, no intake row — correct) ·
                stage_computed_at stamped on all 100,445
```

Execute figures matched the dry run exactly. **1,785 groups / 3,772 rows is now the fifth
independent arrival at the same numbers** — design prediction from the CSV, dev dry run,
dev fresh ingest through the new `load_list`, prod dry run, prod execute.

⚠️ **The seed legitimately has zero primary intake rows.** A naive "exactly one primary per
contact" check returns 1 violation in production and 0 in dev — the difference is that dev
has no seed row. The invariant applies to list contacts; seeds carry `seed_key` and no
intake row by design (§7 step 2). Exclude `is_seed` before believing that check.

**Gap found during the ceremony:** step 7 has **no runner**. `migrate_grain` prints
*"Next: recompute_state()"* and nothing performs it — no CLI, no route. It was run via a
one-off script. A required step should not depend on an operator reading a message; a small
`jobs/recompute_cli.py` would close it.

**The production checkout's `docs/current-state.md`** was locally rewritten to describe
production and never committed. It was preserved three ways before the release (git stash
in that checkout, `marketing/mail-engine-production-current-state.md`, and a scratchpad
copy); the checkout now carries the dev version. Restore or re-author it there as needed —
the nvermisscall history records losing this file once to a `reset --hard`.

## Next: the address backfill, then revision 7

1. **Pre-wave verification, pay-as-you-go** (decided 2026-07-30, `decisions.md`) — the
   full-list backfill is deferred indefinitely; instead, verify the audience of each wave
   before it drops (Lob Developer $0.05/lookup, no plan). Needs the **live Lob key** plus
   one small piece of work: an **audience-scoped mode on `verify_addresses`** (verify the
   contacts a wave rule resolves, not `--limit N` over arbitrary rows). **Do not run any
   sweep with the test key** — every row comes back canned `undeliverable`, permanently
   (verdicts are never re-asked), which would empty every audience.
2. **Revision 7** of `partner-lead-assignment.md` — twin-row stratum deletion (the grain
   merge just made it possible), plus the four columns the partner report needs
   (`partner_code`, `last_export_at`, `sales_rep_id`, `last_report_at`), the registration
   runbook, and the close feed's phase home.
3. Then partner Phases 1–4, with the partner report (RA/RB) riding along.

## Environment (local dev)

- Local Postgres `mailengine_dev` on **localhost:5432**, roles `me_user` / `me_user_ro`.
  No Docker. `make migrate` applies migrations **and then the swap** via
  `migrate_grain --ensure-swapped`. `make run` → **http://127.0.0.1:8001**; no dotenv
  loader — make targets source `.env`. Running a module directly needs
  `set -a; . ./.env; set +a` (and `PYTHONPATH=.`).
- ⚠️ **`make test` AND `make e2e` TRUNCATE `mailengine_dev`.** But `clean_db`
  truncates at test START, so the LAST test's fixtures survive the suite — **truncate
  again before re-ingesting** (2026-08-01: a straight re-ingest landed at 100,448,
  four leftover fixture contacts over the canonical 100,444). Re-ingest (~50s):
  `load_list('../ingestion-app-1/cslb-all.csv', source='cslb-ca')` then
  `load_list('../ingestion-app-1/fbn-ca-2026.csv', source='fbn-ca-2026')` → **100,444
  contacts**, not 102,431. Run the suite FIRST and re-ingest after, not the reverse.
- ⚠️ **`cslb-all.csv` was regenerated 2026-07-29** through the adapter, because the old
  file predated the `trades` column and ingesting it gave every row an empty `trades` —
  which silently matches no trade audience. The pre-`trades` file is kept beside it as
  `cslb-all.csv.pre-trades.bak`. Regenerate with
  `uv run python -m intake.cslb_ca ../ingestion-app-1/MasterLicenseData.csv -o <out>`
  (84,072 rows).
- ⚠️ **A killed ingest leaves the tables bloated, and the next ingest crawls.** Measured
  2026-07-29: a re-ingest that normally takes **~48s** took **>10 minutes** after an
  earlier run was killed mid-transaction. The rollback leaves no dead tuples (autovacuum
  clears them) but does NOT release the pages — `contacts`/`intake_cslb_ca` sat at
  30 MB/45 MB with zero live rows. The remedy is the documented one: drop/recreate
  `mailengine_dev` → `make migrate` → re-ingest (back to 48s, tables at 64 kB/56 kB). Do
  not just retry the ingest — it gets slower each time.
- ⚠️ `marketing/ingestion-app-1/` is **131 MB and versioned nowhere** — it holds
  `cslb-all.csv` and `MasterLicenseData.csv`, the only copies of the source data.
- This cluster's `template1` carries a **collation-version mismatch**, so anything that
  creates a database must use `template template0` (the swap-guard fixture does).

## Open / undecided (carryover)

- **Activation table has NO writer** (TD-2) — unchanged. The grain preflight checked it and
  **passed**: production had 0 activation rows, so none belonged to a merging contact.
- **Q10 close-visibility is the main-app ↔ marketing interface**, and it is the one
  direction that still needs building. **A contract now exists:**
  `nmc-close-feed-contract.md` (**RATIFIED** 2026-07-29) — **mail-engine reads the Medusa
  DB read-only** and consumes closes as a `ResponseFeed`; the main app writes no code, owing
  only a `select`-only role (**which does not exist yet**) and a promise not to rename the
  columns. Accepted cost is **TD-12**. One binding open question remains inside it (§7,
  double-counting against the PostHog inflow). Partner identity does NOT: partners are created
  manually in both systems (decided 2026-07-29, `decisions.md`), so no provisioning or
  sync is needed. But the spine still cannot see a partner-driven close, and until it can,
  a closed customer expires back into the assignable pool and partner #2 cold-calls a
  paying subscriber. Must be decided before the first partner close. A nullable
  `sales_rep_id` on mail-engine's `partners` row is free while migration `0009` is
  unwritten — an input to revision 7.
- **Partner reporting is decided: emailed report, no portal** (2026-07-29,
  `decisions.md`). Rides partner Phase 3's `Sender` (which is also TD-10's fix), so the
  net-new is a composer + schedule. The HOLDINGS half (batch, remaining, expiry) ships with Phase 3;
  earnings wait on Q10. Not a performance report — the spine cannot see effort.
- **Q6 counsel hour** — queued behind the grain work.
- **Live Lob key rotation (TD-9)** — still advised, still pending.
- **Lob AV plan purchase — RESOLVED as "don't buy" (2026-07-30, `decisions.md`):**
  pay-as-you-go verify-what-you-mail (Developer $0.05/lookup, no plan, no base fee).
  **TD-11** demoted from time-sensitive; its checkout questions reopen only if a
  full-list backfill ever becomes worth doing (multi-state scale). Vendor stays Lob —
  USPS-direct is batch-unusable since 2026 (60 req/hr + licensing), Google's caching
  terms conflict with §5 snapshot semantics, Smarty saves less than a swap costs today.
- **`partner-lead-assignment.md` rev 6 + its impl plan are APPROVED** (`21ca9c5`), still
  sequenced after this migration; revision 7 (twin-row stratum deletion) follows it, and
  migrations `0009`/`0010` follow `0008`.

## Watch-outs (carryover)

- Lob has **no `postcard.delivered`** event: `processed_for_delivery` is the proxy;
  tracking fires in the **live** env only.
- Proof PDFs render **asynchronously** — refresh the embed; the e2e polls for `%PDF`.
- `.env` address values must be quoted (spaces break `make run` sourcing).
- `config/seeds.json` holds a **real address** — gitignored, never commit it.
- FBN rows have **zero phones** — excluded from everything voice and from the
  phone-merge. The grain merge groups **CSLB rows only**.
- Both defects found while coding Phase 2 (a `GROUP BY` error, a test asserting a scenario
  it didn't construct) surfaced by **running** the thing, not by reading it — as did both
  stale-CSV bugs above. The suite is the check; reading is not.
