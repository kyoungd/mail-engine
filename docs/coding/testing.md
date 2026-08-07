# Testing — the philosophy (canonical)

*This is the living statement of how mail-engine is verified: the tiers, their
authority, the release gate, and the risk rule. Build plans (`test-plan.md`) and
session logs (`current-state.md`) go stale by design; this document does not.
When practice and this document diverge, one of them is wrong — fix that in the
open, not silently.*

---

## The tiers

| Tier | Where | Authority | Network | Database effect | Run |
|---|---|---|---|---|---|
| Unit | `tests/unit/` | **Disposable** — rewrite freely | none | none (a few use the test DB) | `make test` |
| Acceptance | `tests/acceptance/`, `tests/e2e/test_*journey*` | **Frozen phase gates** — they pin decided behavior; editing one is an escalation, not a refactor | none | truncates `mailengine_test` (never dev) | `make test` |
| E2E | `tests/e2e/` | Frozen | real `api.lob.com` (test key) | truncates `mailengine_test` (never dev) | `make e2e` |
| Integration | `tests/integration/` | Frozen | live cross-repo seams, **GET/SELECT only** | **none** — truncates nothing | `make integration` (`STRICT=1` = a skip is a failure) |

- **No red tests, ever.** A test that fails for any reason — even an "expected"
  one — is fixed, deleted, or skipped-with-reason the same day.
- **Never weaken production to green a test.** If a test fails because the
  system lacks a real requirement, add the requirement.
- **Tests validate code, not the reverse.** Loosening an assertion to pass is
  the cardinal sin; a genuinely wrong test is a discussion, not an edit.
- **TDD for 🟡 and up** — the approved test is the gate and the plan
  (CLAUDE.md § Workflow: TDD). Coverage over existing behavior is 🟢.
- **New DB-backed tests arrange state through service verbs**, not raw SQL —
  unless the raw write *is* the adversarial point (e.g. the compliance
  invariant's post-assignment flips), in which case say so in the test. The
  legacy SQL-seed style in older acceptance files is grandfathered, not a
  precedent.
- **Integration tier discipline:** read-only across every boundary,
  skip-if-unconfigured with a printed reason, fail-on-drift. The runner prints
  `covered / skipped` so an all-skip run can never impersonate coverage.

## The risk rule

**Rigor scales with the red-tier list, not with what is easiest to test.**
The compliance predicates (`service/assignment.py`), suppression + tombstones,
and anything touching real contact rows get the strongest available treatment:
per-gate tests AND standing invariants AND (owed, below) mutation coverage.
Pure layers (`derivation/`, `resolution/`) keep their mutation + property
testing, but they are not where the scars are.

### Standing invariants (the "always true after any scenario" tests)

- **Export compliance** — `tests/acceptance/test_export_compliance_invariant.py`:
  no export ever contains a number the program may not dial. Built as a
  reconciliation: the violating set is re-derived with independent SQL and
  intersected with the actual CSV — so a mutant dropping one predicate from
  assignment or export goes red even though every per-gate test still passes.
- (Pattern for future ones: derive the forbidden set independently of the code
  under test; assert empty intersection; run it over adversarial state.)

## The release gate (decided 2026-08-07)

A prod release is a `git pull` in `mail-engine-production/` — there is no CI to
stop a bad one, so the gate is procedural and non-optional:

> **Before any prod release, same day:** `make test` green · `make e2e` green ·
> `STRICT=1 make integration` green (booking-system up) · pending migrations
> read and their prod plan stated (e.g. the 0011/0012 cancel-out question) ·
> after the pull, tag it: `git tag prod-YYYY-MM-DD` — every release stays
> identifiable and diffable.

A release without all four is the 2026-07-02 parent-repo incident waiting to
recur here.

## Databases

`make test` and `make e2e` run against **`mailengine_test`** — a scratch DB
auto-created from `template template0` by `scripts/ensure-test-db.py` (this
cluster's `template1` is broken) — so the canonical dev ingest in
`mailengine_dev` survives every test run. `tests/guard.py` fail-closed
allowlists only those two databases; everything else is treated as production
and refuses to run. Invoking pytest directly (outside make) still uses
whatever `.env` points at — export the `mailengine_test` URLs first if you're
running DB suites by hand.

## Owed (recorded so they cannot silently rot)

1. **Mutation coverage over `service/assignment.py`** — extend `mutmut` beyond
   the pure layers to the highest-risk module. Constraint to solve first: its
   tests are DB-backed acceptance tests, and the mutmut sandbox currently
   assumes DB-free unit suites. Needs its own pass; do not bolt on casually.
2. **Fake-fidelity contract tests** — one shared assertion module per seam,
   parametrized over `{fake, real-if-reachable}`, so a fake can never drift
   from the client it stands in for (the `NmcDemosClient` gap class).
3. **`TZ=UTC` pinning on `make test`** — specified in test-plan.md §6, never
   wired. Before flipping it, run the full suite once under `TZ=UTC` and fix
   what surfaces; do not flip blind (no-red-tests).
4. **`PostHogFeed` and `NmcCloseFeed` integration tests** — the remaining two
   seams from the 2026-08-07 decision, each its own 🟡 gate.
5. ~~**CI**~~ — **DECIDED and built 2026-08-07**: `.github/workflows/ci.yml`
   runs ruff + the offline suite (service-container Postgres, no vendor
   secrets) on every push/PR. Deliberately offline-only — `e2e` and
   `integration` stay operator-run, so CI green does NOT satisfy the release
   gate by itself.

## The standing rule

Every production failure, rehearsal surprise, flake, and founder suspicion ends
by leaving a test behind at the appropriate tier. The suite is the system's
accumulated scar tissue: it **grows by default**, and a test is retired only as
a deliberate, recorded act — the behavior it pinned was removed or the pin was
superseded — never as a convenience to go green (precedent: the
partner-sourced revert deleted its two acceptance suites *with* the feature).
