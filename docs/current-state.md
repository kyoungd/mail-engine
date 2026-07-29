# Current state — 2026-07-29: grain Batches A, B and C SHIPPED; Phase 4 (🔴 prod merge) is next

Batches A, B and C are committed and green — **all three coding batches of the grain
plan are done**. The swap boundary is crossed (every fresh environment is post-swap,
`contacts` is business-grain and phone-unique), and `verify_addresses` exists behind the
seam fixed in Batch A. What remains is **Phase 4: the 🔴 prod merge**, which is an
operator ceremony rather than a coding batch — gated on reading the dry-run report.

Batch A is pushed; **Batches B and C are committed but not pushed** at the time of
writing — check `git status -sb` before assuming.

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

## Next: Phase 4 — the 🔴 prod merge

Not a coding batch: an operator ceremony. Pull the release → apply `0008` →
`migrate_grain` dry run → **read the report** → `--execute`. Stop-the-world; no ingests
and no wave verbs between `0008` and `--execute`. Gated on the operator reading the
dry-run report, per design §7 and §10 test 9.

Still open before it: the **Lob AV plan purchase** (~$920 for the ~102k backfill) and the
**live key rotation (TD-9)**, both listed below.

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

- **Activation table has NO writer** (TD-2) — unchanged; the grain preflight asserts it
  stays untouched, and halts if any activation row belongs to a merging contact.
- **Q10 close-visibility is the main-app ↔ marketing interface**, and it is the one
  direction that still needs building. Partner identity does NOT: partners are created
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
- **Lob AV plan purchase** — needed before Phase 4's live verification and the
  post-migration backfill (design §7 step 9 — an ordinary job run, NOT a numbered phase;
  the grain plan stops at Phase 4). The recorded ~$920 may be ~60% low: the per-lookup rates re-checked correct on
  2026-07-29, but the plan BASE fee (Growth "starting at $550/month") is not in that math
  and the page doesn't say whether the $450 AV allowance is inclusive of it. **TD-11** has
  the two questions to settle at checkout. A bounded `--limit N` probe costs `N × $0.05`
  with no base fee and needs no plan at all.
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
