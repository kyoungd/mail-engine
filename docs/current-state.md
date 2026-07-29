# Current state — 2026-07-29: grain Batch A SHIPPED; Batch B in progress (migrate_grain done + dry-run-proven, rest of Phase 2 not built)

**This session** executed the grain plan for the first time. Batch A (Phase 1) is
committed, green and pushed. Batch B (Phase 2) is **partially built**: `migrate_grain`
is complete and proven against real data, everything else in the phase is untouched.
Along the way the partner design was recorded as approved, both plans were re-batched,
and two design questions were pinned in the repo rather than left in a chat log.

**⚠️ Two commits are UNPUSHED** (`faea444`, `7f03170`). Git credentials came from VS
Code's askpass provider over an IPC socket that dropped mid-session
(`VSCODE_GIT_IPC_HANDLE` unset, no credential helper anywhere, no SSH key, no `gh`).
Every repo is affected, not just this one. **Push first thing** — if it fails, reload
the VS Code window, or generate an SSH key and add it to GitHub.

## Where we are

Gates green: **315 offline tests** (was 279), ruff + pyright clean. Migrations
**0001–0008** applied. Dev DB holds its documented **102,431** contacts.

### Batch A — Phase 1, DONE (`6a99ac0`, pushed)

Additive only; no live-path behaviour changed, nothing dropped, `migrate_grain` wired
nowhere.

- **Migration `0008.intake-split.sql`** — `intake_cslb_ca` + `intake_fbn_ca` at full
  §2.1 shape, `contact_merge_map`, `contacts.seed_key`, plain index on
  `pieces (contact_id, wave_id)`, and the `unique (contact_id) where is_primary`
  partial index.
- **Adapters emit `trades`** — sorted distinct union, so `C20|C36` → `hvac|plumber`
  (§6 pins the ordering; a pipe-join needs determinism). `trade` keeps first-match
  priority, unchanged, because it feeds segment. FBN emits empty.
- **`AddressVerifier` seam** — Protocol, `VerificationResult`, the verbatim verdict
  enum, and `AddressVerificationError` as a **distinct type**. That distinction is the
  point: §5 pins a verdict as a result (stamp, never re-call, *including*
  undeliverable) against a vendor error (stamp nothing, next run retries). `FakeVerifier`
  reaches all four cases from its constructor. The Lob impl lands in Phase 3.

Compatibility was checked, not assumed: `load_list` reads columns by name and never
touches `trades`, so the `CANONICAL_FIELDS` change works both ways — proved by
re-ingesting the **old-header** `cslb-all.csv` (84,072 loaded, 0 invalid) plus FBN
(18,359). That also restored the dev DB after `make test` truncated it.

### Batch B — Phase 2, PARTIAL (`faea444`, **unpushed**)

**`jobs/migrate_grain.py` is complete**: the ground-rule-4 re-run guard, §3's pick rule,
step 1 preflight, steps 2–6, step 8's before/after report, and
`--help`/`--execute`/`--fix-source`/`--check`. 10 unit tests over the pick rule.

**The evidence that matters.** A dry run against the real 102,431-row dev DB reproduces
the design's figures *independently* — those were measured against the canonical CSV in
July; this derives them from the database:

```
phone groups merged     1785     design predicted ~1,785
rows in those groups    3772     design predicted  3,772
contacts     102431 -> 100444    plan predicted  ≈100,444
primaries marked      100444     exactly one per survivor
pieces/events        unchanged   repointed, never deleted
```

Rollback verified after: contacts still 102,431, intake tables empty.

**⚠️ DO NOT run `--execute` yet.** §7's cutover is stop-the-world and everything ships in
ONE checkout. The swap drops `contacts.list_key` while the old `load_list` still inserts
it, so committing the swap against today's code breaks ingest. The script is finished;
the phase is not.

**Still to build in Phase 2:** `load_list` resolve-then-insert + `SOURCE_REGISTRY`;
`retire_seed`; `update_contact_address`; `ensure_seed_contacts` on `seed_key`;
`ResolvedAudience` + trades-`exists` + undeliverable-exclusion-then-dedupe in `waves.py`;
`execute_wave` re-keyed on `mailer_code`; `search_contacts`; the two routes; the
conftest `clean_db` + `ensure_swapped` wiring; the Makefile wiring; and the ~40 frozen
acceptance tests (the gate list is in the implementation plan's Phase 2 — already
approved, no need to re-gate).

## How the phases are run now (ground rule 6, `ab47db7`)

Three batches, cut only where a contract or schema becomes fixed, running free between
cuts: **A** = Phase 1 · **B** = Phase 2 · **C** = Phase 3. Phase 4 is the 🔴 prod merge,
an operator ceremony rather than a batch. The method is packaged as the `/batch-build`
skill (user-level at `~/.claude/skills/`, so it resolves in this cwd; versioned copy in
the nvermisscall repo).

**Phase 2 has no green intermediate** — the phone-uniqueness test needs the swap wired,
and the swap can't be wired until `execution.py` is converted. No ordering puts a green
suite in the middle, so plan one sitting with room to finish. Full note at the top of
Phase 2 in the implementation plan.

## Decisions pinned this session

- **`resolve_audience` returns `ResolvedAudience(ids, excluded_undeliverable,
  deduped_delivery_point)`** (operator, 2026-07-29 — design §6). All three callers read
  `.ids`; only preview reads the counts. Rejected: a separate
  `resolve_audience_with_counts`, which would reintroduce the preview/execution
  divergence `14a58ae` fixed.
- **`clean_db` must also truncate** `intake_cslb_ca`, `intake_fbn_ca`,
  `contact_merge_map` — now a listed Phase 2 deliverable. Without it intake rows leak
  between tests and the resolve-then-insert cases pass or fail on execution order.
- **`partner-lead-assignment.md` rev 6 + its impl plan are APPROVED** (`21ca9c5`) —
  approval had been given verbally and never written down. Still sequenced **after**
  this migration: revision 7 (twin-row stratum deletion) follows it, migrations
  `0009`/`0010` follow `0008`, and building rev 6 first means writing twin-row
  machinery in order to delete it. Its Phase 0 (SAN registration, counsel hour,
  area-code script, paper prongs) is unblocked and operator-owned.

## Next session

1. **Push.** Two commits are waiting.
2. **Finish Phase 2** — one sitting, per the note above. Frozen tests already approved.
3. When the swap lands, the dev DB drops to **≈100,444**; ground rule 6's remedy is
   drop/recreate `mailengine_dev` → `make migrate` → re-ingest through the **new**
   `load_list`, which is also that path's first real exercise.
4. Then Phase 3 (`verify_addresses`), then Phase 4's 🔴 prod merge gated on the dry-run
   report.

## Environment (local dev)

- Local Postgres `mailengine_dev` on **localhost:5432**, roles `me_user` / `me_user_ro`.
  No Docker. `make migrate` applies through **0008**. `make run` →
  **http://127.0.0.1:8001**; no dotenv loader — make targets source `.env`. Running a
  module directly needs `set -a; . ./.env; set +a` first.
- ⚠️ **`make test` AND `make e2e` TRUNCATE `mailengine_dev`.** Re-ingest (idempotent,
  ~2s): `load_list('../ingestion-app-1/cslb-all.csv', source='cslb-ca')` then
  `load_list('../ingestion-app-1/fbn-ca-2026.csv', source='fbn-ca-2026')` → 102,431.
- ⚠️ `marketing/ingestion-app-1/` is **131 MB and versioned nowhere** — it holds
  `cslb-all.csv` and `MasterLicenseData.csv`, the only copies of the source data.

## Open / undecided (carryover)

- **Activation table has NO writer** (TD-2) — unchanged; the grain preflight asserts it
  stays untouched, and halts if any activation row belongs to a merging contact.
- **Q6 counsel hour** and **Q10** close-visibility — queued behind the grain work.
- **Live Lob key rotation (TD-9)** — still advised, still pending.
- **Lob AV plan purchase** — needed before Phase 4's live verification and the Phase 5
  backfill; dashboard-confirm prices then (~$920 one-time for the ~102k backfill).

## Watch-outs (carryover)

- Lob has **no `postcard.delivered`** event: `processed_for_delivery` is the proxy;
  tracking fires in the **live** env only.
- Proof PDFs render **asynchronously** — refresh the embed; the e2e polls for `%PDF`.
- `.env` address values must be quoted (spaces break `make run` sourcing).
- `config/seeds.json` holds a **real address** — gitignored, never commit it.
- FBN rows have **zero phones** — excluded from everything voice and from the
  phone-merge (one contact per filing stays). The grain merge groups **CSLB rows only**.
- The six review rounds repeatedly found defects **in the newest patch text** — when
  editing a design doc, re-review the paragraph you just wrote against §11.2 before
  moving on. The same held while coding: both defects found this session
  (a `GROUP BY` error, a test asserting a scenario it didn't construct) surfaced by
  *running* the thing, not by reading it.
