# Current state — 2026-08-01: partner build CODE-COMPLETE in dev — Stage A (Phases 1, 2, 4) all landed

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
- **Parked, wants ⚠️ attention:** the AV gate (`LOB_AV_API_KEY`) — approved-in-principle
  test shown 2026-08-01, then paused for the partner work. Until it lands, `LOB_API_KEY`
  ARMS the nightly `verify_addresses` sweep in BOTH .envs: dev would sweep with the test
  key (permanent canned `undeliverable` on every row — catastrophic), prod with the live
  key (~$5.1k uncapped). No cron exists, so the hazard is one manual `nightly_cli` run
  away. Land the gate before anyone runs a nightly by hand.
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
- ⚠️ **`make test` AND `make e2e` TRUNCATE `mailengine_dev`.** Re-ingest (~50s):
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
