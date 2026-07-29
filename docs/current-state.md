# Current state — 2026-07-29: grain Batches A and B SHIPPED; Batch C (Phase 3) is next

Batch A (Phase 1) and Batch B (Phase 2) are both committed and green. **The swap
boundary is crossed**: every fresh environment from here is post-swap, `contacts` is
business-grain and phone-unique, and the old `list_key`/`trade`/`license_class` columns
are gone. What remains of the grain plan is Batch C (Phase 3, `verify_addresses`) and
then Phase 4's 🔴 prod merge.

Everything here is pushed as of the Batch A commit; **Batch B (`4142c52`) is committed
but not yet pushed** at the time of writing — check `git status -sb` before assuming.

## Where we are

Gates green: **349 offline tests** (was 315), ruff + pyright clean, e2e journey green
against the real Lob test environment. Migrations **0001–0008** applied, plus
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

## Next: Batch C — Phase 3, `verify_addresses`

Phase 3 implements the job against the `AddressVerifier` Protocol **already fixed in
Batch A** — it pins nothing new, which is why it is not its own cut. Two phases:

1. **Stamp** — sweep intake rows where `std_verified_at is null`, call the seam, store
   `std_*`/`delivery_point`/`deliverability`/`std_verified_at`. A *verdict* (including
   undeliverable and no-delivery-point) stamps and is never re-called; a vendor *error*
   stamps nothing and the next run retries.
2. **Inherit** — for every contact whose primary row is verified
   **deliverable-with-components** and whose `addr_validated_at` is still null, copy the
   `std_*` address onto `contacts.addr_*` and stamp. Any other outcome leaves the raw
   picked address alone. The null guard makes re-runs no-ops and is what stops the job
   overwriting an operator's `update_contact_address` edit.

Design §5 + §10 test 7. Then Phase 4's 🔴 prod merge, gated on the operator reading the
dry-run report.

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
- ⚠️ `marketing/ingestion-app-1/` is **131 MB and versioned nowhere** — it holds
  `cslb-all.csv` and `MasterLicenseData.csv`, the only copies of the source data.
- This cluster's `template1` carries a **collation-version mismatch**, so anything that
  creates a database must use `template template0` (the swap-guard fixture does).

## Open / undecided (carryover)

- **Activation table has NO writer** (TD-2) — unchanged; the grain preflight asserts it
  stays untouched, and halts if any activation row belongs to a merging contact.
- **Q6 counsel hour** and **Q10** close-visibility — queued behind the grain work.
- **Live Lob key rotation (TD-9)** — still advised, still pending.
- **Lob AV plan purchase** — needed before Phase 4's live verification and the Phase 5
  backfill; dashboard-confirm prices then (~$920 one-time for the ~102k backfill).
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
