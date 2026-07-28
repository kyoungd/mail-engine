# Ingest / Contact Migration — Implementation Plan

*Execution brief for `ingest-contact-migration.md` (revision 7, operator-approved
2026-07-27). Read that document first; this one sequences it. Where this plan and
the design conflict, escalate — do not resolve silently. Companions:
`to-fix-ingest-and-contact.md` (evidence), `direct-mail-ai-code-layout.md`
(dependency rule), `technical-debt.md`, `decisions.md`,
`partner-lead-assignment-implementation.md` (renumbered by Phase 0).*

*Status: design approved; Phase 0 complete (2026-07-27); phase gates as
marked. Phases 1–3 are 🟡 — the frozen acceptance tests are the approval gate
(show them, get the nod, green them; they are the design's §10 tests mapped to
phases, plus phase-local scaffolding tests such as migration idempotence and
seam conformance). **Since 2026-07-28 that gate is taken per BATCH, not per
phase — ground rule 6 defines the three batches (A: Phase 1 · B: Phase 2 ·
C: Phase 3) and how a batch runs.** Phase 4 — the prod merge itself — is 🔴 and
gated on the dry-run report per the design.*

*Revision 2 (2026-07-27, after a fresh-context review of this plan verified
against the codebase): old Phases 2–3 merged into one phase — the swap
boundary — because the schema swap and the code that survives it must land
together (old `execute_wave`'s `on conflict (contact_id, wave_id)` is a hard
Postgres error once the constraint drops; old `load_list`/`_audience_where`
read dropped columns). Each phase now states which schema its suite runs
against; `migrate_grain` gained a pinned re-run contract (ground rule 4).*

*Revision 3 (2026-07-27): second plan review (verdict: approve-as-is with four
notes) — the notes pinned anyway: test-9 scratch-DB fixture, seam prior-art
acknowledgment, raw-insert authorization for the uniqueness test, Phase 3
verdict-class definition, plus two wording nits.*

---

## Executor ground rules

1. **The design document is decided.** The merge rule (same phone ⇒ same
   contact, CSLB only), the pick rule (max-frequency-tuple candidate set →
   lowest `list_key`), the pinned answers to all five original open questions,
   and every revision-2..7 pin are settled. A genuine flaw found mid-build is an
   escalation, not a patch.
2. **The dependency rule is law.** `web`/`jobs` → `service` → `derivation`/
   `resolution` → `domain`; `seams` imported only by `jobs` and
   `service/execution`. Known prior art, acknowledged so it isn't read as
   license: `web/api.py` and `service/waves.py` already import the print seam
   (proofs/webhooks) — pre-existing exceptions, not precedent. For THIS
   feature the rule binds strictly: `AddressVerifier` is touched only by the
   `verify_addresses` job (nightly-run); `load_list`, `waves`, and `web`
   never import it.
3. **Test-first, two tiers.** Frozen acceptance tests in `tests/acceptance/`
   written from the design's §10 criteria through public verbs only; disposable
   unit tests below. Modifying a frozen test is an escalation. **One
   pre-authorized exception:** §10 test 4 (phone uniqueness) asserts a DB
   constraint no public verb can violate by design (`load_list` attaches on a
   phone match, never inserts a twin) — its fixture uses a raw SQL insert to
   probe the unique index. That is a fixture action, not a verb bypass, and
   it is the only one. The three
   inherited frozen tests (`tests/acceptance/test_recompute.py:86`,
   `test_contacts.py:102-120`, `test_human_set_next_action_survives_recompute`)
   follow design §10 test 11: fixture helpers may mechanically follow the
   schema; assertions and scenario semantics change by zero characters.
4. **Schema truth after this feature = migrations 0001–0008 + `migrate_grain`'s
   in-script swap — staged, not immediate.** The order-dependent DDL
   (pieces-constraint drop, phone-unique index, contact column drops)
   deliberately lives in the script, not a migration file (design §7). The
   swap and the code that survives it must cross **one boundary together**:
   Phase 1's suite runs against the **pre-swap** schema (0001–0008, swap NOT
   wired); Phase 2 lands every swap-dependent code change AND wires
   `migrate_grain` into `make migrate`/test-DB setup in the same phase — from
   Phase 2 on, every fresh environment's schema is migrations + swap. Wiring
   it earlier breaks the suite (old `execute_wave`'s
   `on conflict (contact_id, wave_id)` errors outright on a swapped schema);
   wiring it later makes Phase 2's phone-uniqueness test unwritable.
   **Re-run contract (pinned):** invoked from `make migrate`/test setup the
   script must be safe to run repeatedly — post-swap schema detected (no
   `contacts.list_key` column) → clean no-op exit ("already migrated");
   pre-swap schema **with data** → fail loud, demanding the full dry-run
   ceremony (never auto-merge someone's populated DB); pre-swap **empty** DB
   (fresh env) → apply the swap DDL automatically (the merge over zero rows
   is trivially the ceremony). The guard must never mask a prod preflight
   halt — prod is never empty.
5. **Escalation triggers:** any schema change beyond migration `0008` + the
   script's pinned swap; any change to the five operator-decided answers or the
   brand-merge judgment; any verb signature beyond those **the design doc**
   specifies (`retire_seed(contact_id)`,
   `update_contact_address(contact_id, addr…)`, the `load_list`/
   `ensure_seed_contacts` reshapes — the design is the signature authority,
   this plan only sequences); anything that makes a §10 test unwritable as
   specified; any Lob verification fact that contradicts Phase 0's findings.
6. **Three batches, not one-phase-per-session** (amended 2026-07-28; supersedes
   the original "one phase per session"). Phases were sized by session length,
   which is a context budget, not a property of the work. Cut only where a
   contract or schema becomes **fixed**; run free between cuts:

   | Batch | Phases | What is fixed at the cut |
   |---|---|---|
   | **A** | 1 | Migration `0008` DDL; the `AddressVerifier` Protocol + Fake. Schema and seam contract pinned; suite still runs **pre-swap** |
   | **B** | 2 | **The swap boundary** — spine verbs + audience + execution re-key + `migrate_grain` wiring, all crossing together per ground rule 4 |
   | **C** | 3 | `verify_addresses` implemented against the Protocol already fixed in A — it pins nothing new, which is why it is not its own cut |

   Phase 4 is **not** a coding batch: it is the 🔴 prod merge, gated on the
   operator reading the dry-run report.

   **The gate is per batch, not per phase.** Show the frozen acceptance tests
   for every phase in the batch, once, get the nod, then green them without
   further approval. Batching removes *approval* points, never *verification*
   points — so inside a batch:

   - `make test` + `ruff` + `pyright` clean at **every internal phase
     boundary**, not only at the batch's end.
   - **Commit at every internal phase boundary.** Each is a recovery point; a
     long free run with one commit at the end is one bad step from losing it.
   - **Halt and escalate** on anything that would change a contract or schema
     fixed in an *earlier* batch. That is the one thing a free run must never
     absorb. Ground rule 5's triggers bind unchanged — running free is
     permission to skip approval, never to exceed scope.

   (Local convenience: the `/batch-build` skill runs this method. The rules
   above are self-contained and authoritative if it is unavailable.)

   ⚠️ `make test` / `make e2e` **truncate `mailengine_dev`** — re-ingest per
   `current-state.md` before manual verification against dev data. **Dev remedy
   for the re-run guard's halt** (it WILL fire on the populated dev remnant
   after Phase 2): drop/recreate `mailengine_dev` → `make migrate` (empty
   pre-swap DB → swap auto-applies) → re-ingest through the new `load_list`.
   The prod ceremony is never the dev path.
7. **Renumbering (design §12):** this feature owns migration `0008`. The
   partner plan's "Migration 0008 (partners…)" becomes `0009`+; update
   `partner-lead-assignment-implementation.md`'s numbering in Phase 0 here, and
   `partner-lead-assignment.md` revision 7 follows this feature's completion.

---

## Phase 0 — Facts, amendments, decisions (no code) — ✅ COMPLETE 2026-07-27

*All deliverables below exist; listed for the record, not for execution. Do
not redo. (Lob findings live in design §5 "Vendor facts — VERIFIED
2026-07-27"; the decisions.md entries, PRD FR-1/FR-4, TD-2 note, and the
partner-plan 0009/0010 renumbering are all in place.)*

- **Lob verification facts** — verified against Lob's current
  primary docs, per the verify-external-facts rule; findings recorded in the
  design doc's §5 (needed before Phase 3 code): (a) US Verification pricing/volume terms
  for the ~102k backfill (84,072 CSLB + 18,359 FBN) and per-ingest increments;
  (b) exact response fields backing `std_*`, `delivery_point`,
  `deliverability`; (c) the verdict values that pin §6's undeliverable
  exclusion and §5's deliverable-with-components inherit rule. If terms are
  unacceptable: fallback is scoping the backfill to mailed audiences only
  (schema unchanged) — an operator decision, not an executor one.
- **`decisions.md` entries** (design was approved 2026-07-27, so these are now
  due, per the write-at-approval convention): the grain decision (one row per
  business; same phone ⇒ same contact), the brand-merge ratification, the
  one-time readout restatement, address standardization at ingest with
  identity-stays-phone-only, and the two standing conventions (authority map,
  writer-named-at-declaration).
- **PRD amendments** (design §12): FR-1 (resolve-then-insert intake, per-source
  tables, verification job); FR-4 ("hard constraint" → enforcement at audience
  resolution + `mailer_code` idempotency).
- **`technical-debt.md`**: TD-2 note (authority map adopted as standing
  convention; this migration neither fixes nor worsens TD-2's dead columns).
- **Partner-plan renumbering** (ground rule 7) — done: 0009/0010.
- **`current-state.md`** rewrite at end of each session, as usual.

**Accepted 2026-07-27:** Lob findings recorded in design §5, decisions.md
entries written, both PRD FRs amended, partner migration numbers renumbered.

## Phase 1 — Additive schema + adapters + seam (🟡, no live-path behavior change)

**Frozen tests first:** migration `0008` applies cleanly twice
(`test_migrations_idempotent` pattern); adapter emits `trades` (a C20|C36 row
→ `{hvac,plumber}`, `trade` still first-match — design §2.1); `FakeVerifier`
satisfies the `AddressVerifier` Protocol.

- **Migration `0008.intake-split.sql`** — additive only (design §7):
  `intake_cslb_ca`, `intake_fbn_ca` (full §2.1 DDL including `do_not_mail`,
  `is_primary`, the `std_*`/`delivery_point`/`deliverability`/`std_verified_at`
  columns, and the `unique (contact_id) where is_primary` index),
  `contact_merge_map`, `contacts.seed_key text unique`, plain index on
  `pieces (contact_id, wave_id)`.
- **Adapters** (`intake/cslb_ca.py`, `intake/fbn_ca.py`): `trades` joins
  `CANONICAL_FIELDS`; CSLB emits all matching NMC trades pipe-joined; FBN
  emits empty.
- **`seams/`**: `AddressVerifier` Protocol + `FakeVerifier` in `seams/fakes.py`
  (programmable verdicts: deliverable-with-components, no-delivery-point,
  undeliverable, error). The Lob implementation lands in Phase 3 per
  Phase 0's verified facts.
**Suite schema this phase: PRE-swap** (migrations 0001–0008 only;
`migrate_grain` is NOT wired anywhere yet — ground rule 4). All existing code
paths still run against the old columns; that is the point of "additive only."

**Accept when:** the frozen tests above are green, `0008` is idempotent, the
full suite (279 + new) passes against the pre-swap schema, and nothing about
live behavior changed.

## Phase 2 — The swap boundary: spine verbs + audience + execution (🟡)

*One phase, one boundary (revision 2): every code path that reads the old
schema converts here, and ground rule 4's wiring lands here too — the swap
and its surviving code are inseparable (see the revision note up top). It is
the largest phase; its coherence is the point. If it must split across
sessions, split WITHIN the phase (verbs first, audience/execution second)
without wiring the swap or claiming the boundary until all of it is green.*

**Frozen tests first** (design §10 tests 1–6, 8, 10, plus the verb contracts
and resolution rules — e.g. FBN per-filing — the design pins outside §10's
numbering):
determinism (two independent fresh DBs, identical contacts ids-aside);
resolve-then-insert (N rows one phone → N intake rows 1 contact; pick rule
incl. a tuple-tie fixture; email whole-group coalesce; untargetable row → no
intake row, counted invalid; unknown source → `ValidationError` before any
row); attach-without-re-pick (+ `do_not_mail` OR-merge on attach); phone
uniqueness (second phone-bearing contact fails; nulls don't collide; seeds
unaffected); FBN per-filing (phone-bearing FBN row → contact with null phone,
row `is_primary`); `retire_seed` (design §10 test 10: `is_seed` cleared +
`do_not_mail` set atomically, absent from every audience path, config-entry
removal doesn't revive); `update_contact_address` stamps `addr_validated_at`;
trade-exists via `trades` (C20|C36 matches both audiences, once each; export
`hvac|plumber`); delivery-point dedupe (primary-row key; deterministic
keeper; unverified primary → no dedupe; non-primary sharing a DP dedupes
nothing; seeds exempt; preview count == executed count; dropped count
reported); undeliverable exclusion (before dedupe — the undeliverable twin
never wins the keeper pick; no-delivery-point NOT excluded; count reported);
resume idempotency on `mailer_code` (killed drop re-runs clean; per-piece
lookup resolves by `mailer_code` on a merged-history fixture where
(contact, wave) is ambiguous); the ground-rule-4 re-run guard (post-swap →
no-op; pre-swap with data → loud halt; pre-swap empty → swap applies).

- **`service/contacts.py`**: `load_list` → parse/validate → in-memory
  resolution by `SOURCE_REGISTRY` (cslb → phone rule; fbn → per-filing) →
  insert intake rows with resolved `contact_id`/`is_primary` (design §4, one
  transaction per file); `ensure_seed_contacts` conflicts on `seed_key`;
  new verbs `retire_seed`, `update_contact_address`.
- **`web/api.py`**: routes for the two new verbs (FR-11: one verb per route);
  intake route unchanged except the registry now validates `source`.
- **`service/queries.py`**: `search_contacts` over contacts + intake lateral
  (trade / `list_key` hits; trades pipe-delimited in the summary).
- **`service/waves.py`**: `_audience_where` trade filter → intake `exists`
  over `trades` (unioned per intake table); `resolve_audience` gains
  undeliverable exclusion **then** delivery-point dedupe; `AudiencePreview`
  gains both counts.
- **`service/execution.py`**: `execute_wave` insert `on conflict (mailer_code)
  do nothing`; per-piece lookup re-keyed on `mailer_code`.
- **Ground rule 4 wiring**: `migrate_grain` gains the re-run guard;
  `make migrate` + test-DB setup invoke it after migrations. From this phase
  on, every fresh environment is post-swap.

**Suite schema this phase: POST-swap** (migrations 0001–0008 +
`migrate_grain`'s swap, auto-applied on the empty test DB by the guard).

**Accept when:** every frozen test above is green against the post-swap
schema, the e2e journey passes end-to-end on the new intake path, and a full
wave lifecycle (draft → preview → approve → execute with FakePrintApi) runs
with the counts matching preview.

## Phase 3 — Verification job (🟡)

**Frozen tests first** (design §10 test 7): stamp phase (verdict — including
undeliverable/no-DP — stamps `std_verified_at` + stores verdict, never
re-called; vendor *error* stamps nothing, next run retries); inherit phase
(deliverable-with-components → contact gets `std_*` + `addr_validated_at`;
any other verdict → raw address untouched, guard stays null; re-run no-op;
`update_contact_address`-edited contact never overwritten).

- **`seams/`**: Lob `AddressVerifier` implementation per Phase 0's verified
  response fields; verdict-value mapping pinned from Phase 0.
- **`jobs/`**: `verify_addresses` (stamp + inherit phases), wired into the
  nightly (no-op when nothing unverified); manual invocation documented for
  the backfill (`--help` per the standing CLI rule).

**Accept when:** frozen tests green with `FakeVerifier`; the Lob impl is
exercised against Lob's test environment for at least one address of each of
the **three semantic classes the code branches on** — deliverable-with-
components (inherit runs), verified-without-usable-components (no-DP or
missing `std_*`; inherit skips), undeliverable (excluded) — plus one vendor
*error* if producible (a forced timeout/bad-key counts). Producibility of
each class in Lob's test env is an unverified vendor fact: any class the test
env cannot deterministically produce stays covered by `FakeVerifier` alone,
noted in the phase's acceptance record. The nightly runs it.

## Phase 4 — The prod merge (🔴 — dry-run report → operator reads → `--execute`)

**Frozen test first** (design §10 test 9, on a fixture DB). **Fixture
mechanism, pinned:** the test builds its own scratch database — apply
migrations 0001–0008 directly (bypassing the standard test setup, whose
`migrate_grain` wiring would leave every suite DB already post-swap with the
old columns gone), seed old-schema rows, then run `migrate_grain`
dry-run/`--execute` against it. The dry-run report
matches hand-computed expectations (Andersen-shaped 12-pack, tuple-tie group,
two-member next-action group → earliest wins, notes merged, report lists it);
post-migration counts, FK integrity, OR-merged suppression, `is_primary`
exactly-one, pooled-stage recompute, all report sections present; preflight
halts on an `approved`/`executing` wave and on a non-seed prefix/source
mismatch.

- **`jobs/migrate_grain.py`** completed per design §7: preflight (source
  distribution measured and reported first; seed exemption; `--fix-source`
  remedy mode), steps 1–6 in one transaction (constraint drop before repoint;
  post-merge DDL last), dry-run = run-and-rollback, post-commit
  `recompute_state()`, report per §8 (restatement, merge audit,
  actionable-state changes, merged next-actions).
- **Prod run order (design §7 cutover, stop-the-world):** `pg_dump` → deploy
  the release checkout → apply `0008` → `migrate_grain` dry-run → **operator
  reads the report — this is the 🔴 gate** → `--execute` → script-emitted
  post-checks → repo gate (frozen + full suite green) → nightly
  `verify_addresses` begins the backfill.
- No ingests, no wave verbs between `0008` and `--execute`.

**Accept when:** prod deltas match the dry-run (list-sourced contacts
102,431 → dry-run's measured survivor count; pieces/events unchanged), the
post-checks and repo gate are green, and the before/after report is filed
alongside this doc.

## Cross-cutting

- **Wave-1 responses in flight:** `resolve_orphans`' phone lookup hits the
  merged contact post-migration (phone-unique makes `contact_by_phone`
  deterministic — design §6); mailer-code matching is unaffected by repoint.
  No special handling needed; noted so nobody builds any.
- **Follow-on work, not this feature:** `partner-lead-assignment.md` revision 7
  (twin-row stratum deletion) + its implementation-plan update; the Phase 0
  radius script, Q6 counsel hour, Q10 — all queued behind this per
  `to-fix-ingest-and-contact.md`.
