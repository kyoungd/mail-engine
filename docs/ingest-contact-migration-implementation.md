# Ingest / Contact Migration — Implementation Plan

*Execution brief for `ingest-contact-migration.md` (revision 7, operator-approved
2026-07-27). Read that document first; this one sequences it. Where this plan and
the design conflict, escalate — do not resolve silently. Companions:
`to-fix-ingest-and-contact.md` (evidence), `direct-mail-ai-code-layout.md`
(dependency rule), `technical-debt.md`, `decisions.md`,
`partner-lead-assignment-implementation.md` (renumbered by Phase 0).*

*Status: design approved; phase gates as marked. Phases 1–4 are 🟡 — the frozen
acceptance tests at the top of each phase are the approval gate (show them, get
the nod, green them; they are the design's §10 tests mapped to phases). Phase 5 —
the prod merge itself — is 🔴 and gated on the dry-run report per the design.*

---

## Executor ground rules

1. **The design document is decided.** The merge rule (same phone ⇒ same
   contact, CSLB only), the pick rule (max-frequency-tuple candidate set →
   lowest `list_key`), the pinned answers to all five original open questions,
   and every revision-2..7 pin are settled. A genuine flaw found mid-build is an
   escalation, not a patch.
2. **The dependency rule is law.** `web`/`jobs` → `service` → `derivation`/
   `resolution` → `domain`; `seams` imported only by `jobs` and
   `service/execution`. `AddressVerifier` is a seam; `load_list` never touches
   it — verification is the `verify_addresses` job, nightly-run.
3. **Test-first, two tiers.** Frozen acceptance tests in `tests/acceptance/`
   written from the design's §10 criteria through public verbs only; disposable
   unit tests below. Modifying a frozen test is an escalation. The three
   inherited frozen tests (`tests/acceptance/test_recompute.py:86`,
   `test_contacts.py:102-120`, `test_human_set_next_action_survives_recompute`)
   follow design §10 test 11: fixture helpers may mechanically follow the
   schema; assertions and scenario semantics change by zero characters.
4. **Schema truth after this feature = migrations 0001–0008 + `migrate_grain`'s
   in-script swap.** The order-dependent DDL (pieces-constraint drop,
   phone-unique index, contact column drops) deliberately lives in the script,
   not a migration file (design §7). Consequence for every fresh environment
   (dev, CI, `make test`): after applying migrations, run
   `migrate_grain --execute` — on an empty/fresh DB it is a no-op merge plus
   the swap DDL. Wire this into `make migrate` and the test-DB setup in
   Phase 1, or every schema-dependent test after Phase 2 fails on a
   half-migrated schema.
5. **Escalation triggers:** any schema change beyond migration `0008` + the
   script's pinned swap; any change to the five operator-decided answers or the
   brand-merge judgment; any verb signature this plan does not itself specify;
   anything that makes a §10 test unwritable as specified; any Lob
   verification fact that contradicts Phase 0's findings.
6. **One phase per session.** `make test` + `ruff` + `pyright` clean at every
   phase boundary. ⚠️ `make test` / `make e2e` **truncate `mailengine_dev`** —
   re-ingest per `current-state.md` before manual verification against dev
   data.
7. **Renumbering (design §12):** this feature owns migration `0008`. The
   partner plan's "Migration 0008 (partners…)" becomes `0009`+; update
   `partner-lead-assignment-implementation.md`'s numbering in Phase 0 here, and
   `partner-lead-assignment.md` revision 7 follows this feature's completion.

---

## Phase 0 — Facts, amendments, decisions (no code)

- **Lob verification facts (⚠ design §5)** — verify against Lob's current
  primary docs, per the verify-external-facts rule, and record findings in the
  design doc's §5 before Phase 4 code: (a) US Verification pricing/volume terms
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
- **Partner-plan renumbering** (ground rule 7).
- **`current-state.md`** rewrite at end of each session, as usual.

**Accept when:** Lob findings are recorded in the design §5 (or the fallback
decision is made), the decisions.md entries exist, both PRD FRs are amended,
and the partner plan's migration numbers no longer collide.

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
  undeliverable, error). The Lob implementation lands in Phase 4 after
  Phase 0's fact check.
- **Ground rule 4 wiring**: `make migrate` / test-DB setup runs
  `migrate_grain --execute` after migrations. The script itself is Phase 5
  work — for this phase a stub that applies only the swap DDL on an empty DB
  is acceptable IF built as the real script's skeleton (same file, same
  transaction shape), not a throwaway.

**Accept when:** the frozen tests above are green, `0008` is idempotent, the
full suite (279 + new) passes, and nothing about live behavior changed
(old `load_list` still works against the pre-swap dev schema — the cutover
only happens with the swap).

## Phase 2 — Spine verbs on the new grain (🟡)

**Frozen tests first** (design §10 tests 1–4 + seed/address verbs):
determinism (two independent fresh DBs, identical contacts ids-aside);
resolve-then-insert (N rows one phone → N intake rows 1 contact; pick rule
incl. a tuple-tie fixture; email whole-group coalesce; untargetable row → no
intake row, counted invalid; unknown source → `ValidationError` before any
row); attach-without-re-pick (+ `do_not_mail` OR-merge on attach); phone
uniqueness (second phone-bearing contact fails; nulls don't collide; seeds
unaffected); FBN per-filing (phone-bearing FBN row → contact with null phone,
row `is_primary`); `retire_seed` (design §10 test 10: `is_seed` cleared +
`do_not_mail` set atomically, absent from every audience path, config-entry
removal doesn't revive); `update_contact_address` stamps `addr_validated_at`.

- **`service/contacts.py`**: `load_list` → parse/validate → in-memory
  resolution by `SOURCE_REGISTRY` (cslb → phone rule; fbn → per-filing) →
  insert intake rows with resolved `contact_id`/`is_primary` (design §4, one
  transaction per file); `ensure_seed_contacts` conflicts on `seed_key`;
  new verbs `retire_seed`, `update_contact_address`.
- **`web/api.py`**: routes for the two new verbs (FR-11: one verb per route);
  intake route unchanged except the registry now validates `source`.
- **`service/queries.py`**: `search_contacts` over contacts + intake lateral
  (trade / `list_key` hits; trades pipe-delimited in the summary).

**Accept when:** every frozen test above is green and the e2e journey still
passes end-to-end on the new intake path.

## Phase 3 — Audience + execution on the new grain (🟡)

**Frozen tests first** (design §10 tests 5–6, 8): trade-exists via `trades`
(C20|C36 matches both audiences, once each; export `hvac|plumber`);
delivery-point dedupe (primary-row key; deterministic keeper; unverified
primary → no dedupe; non-primary sharing a DP dedupes nothing; seeds exempt;
preview count == executed count; dropped count reported); undeliverable
exclusion (before dedupe — the undeliverable twin never wins the keeper pick;
no-delivery-point NOT excluded; count reported); resume idempotency on
`mailer_code` (killed drop re-runs clean; per-piece lookup resolves by
`mailer_code` on a merged-history fixture where (contact, wave) is ambiguous).

- **`service/waves.py`**: `_audience_where` trade filter → intake `exists`
  over `trades` (unioned per intake table); `resolve_audience` gains
  undeliverable exclusion **then** delivery-point dedupe; `AudiencePreview`
  gains both counts.
- **`service/execution.py`**: `execute_wave` insert `on conflict (mailer_code)
  do nothing`; per-piece lookup re-keyed on `mailer_code`.

**Accept when:** the frozen tests are green and a full wave lifecycle
(draft → preview → approve → execute with FakePrintApi) runs with the counts
matching preview.

## Phase 4 — Verification job (🟡)

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
exercised against Lob's test environment for at least one address of each
verdict class; the nightly runs it.

## Phase 5 — The prod merge (🔴 — dry-run report → operator reads → `--execute`)

**Frozen test first** (design §10 test 9, on a fixture DB): dry-run report
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
