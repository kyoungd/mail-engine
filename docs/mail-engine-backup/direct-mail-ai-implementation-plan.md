# Direct Mail AI — Implementation Plan

*Authored by the architecture layer (Fable 5) as the execution brief for implementation (Opus 4.8 in Claude Code). Read alongside: product description, data document, service contract, judgment job, code layout. Where this document and those conflict, escalate — do not resolve silently.*

---

## Executor ground rules (read first, apply always)

1. **The design documents are decided.** Schema, contract verbs, taxonomy, dependency rule, and the "deliberately absent" lists are settled. Do not add tables, verbs, event types, abstractions, or dependencies beyond what these documents name. If implementation reveals a genuine flaw, STOP and flag for architectural review — do not patch around it.
2. **The dependency rule is law.** `web`/`jobs` → `service` → `derivation`/`resolution` → `domain`; `seams` imported only by `jobs` and `service/execution`; nothing imports upward. Run the architecture-review pass at every phase boundary.
3. **No speculative flexibility.** No repository pattern, no config options nobody asked for, no "while I'm here" generalizations. Seams exist where the code layout says they exist, nowhere else.
4. **Escalation triggers** (stop, summarize, request review): any schema change; any new event type; any new external dependency; any verb signature change; anything that makes a test in this plan unwritable as specified.
5. **One phase per session.** Each phase below is scoped to fit a focused Claude Code session with the relevant design docs in context. Complete the phase's acceptance checks before moving on; don't interleave phases.
6. **Test-first, two tiers.** At each phase, FIRST write the acceptance tests directly from this plan's criteria — through public contract verbs only, never asserting table internals or call structure — before any implementation. These live in `tests/acceptance/` and are FROZEN once written: modifying or deleting one is an escalation trigger, same as a schema change. Unit tests below them (`tests/unit/`) are disposable scaffolding — write, rewrite, and delete them freely as internals evolve; they carry no authority. Use property-based tests (Hypothesis) for the derivation module's invariants: recompute determinism for any event sequence, suppression as an absorbing state, legal stage transitions only. Keep phase suites fast — the executor runs them in-loop; slow tests go to a nightly marker.

---

## Phase 0 — Skeleton and ground truth

Repo scaffold per code layout; Docker Compose with Postgres 15; migration tooling; the full DDL as migration 001; `domain/` complete (types, enums mirroring the DDL exactly, closed taxonomy with `is_valid_type`); `db/session.py` transaction helper; `db/readonly.py` role and connection.

**Accept when:** migrations apply cleanly to an empty database twice (idempotent tooling); enums in code and DDL are generated-from or tested-against each other so they cannot drift; a taxonomy test rejects an unknown event type; read-only role provably cannot write (a test asserts the failure).

## Phase 1 — Truth machinery (no external world yet)

`service/ingestion.py` (ingest_event, record_note, resolve_orphans), `resolution/matcher.py`, `derivation/rules.py`, and `service/execution.recompute_state`. Everything here is testable with fixture data — no seams, no network.

**Accept when:** ingest is idempotent under replay (same `(source, external_id)` twice → one row); unknown types rejected loudly; the resolution chain is covered by table-driven tests including the "never fuzzy-match" negative cases; every derivation function has fixture-list unit tests including the boundary days (QUIET_DAYS exactly, STALL_DAYS exactly); full recompute over a synthetic 5,000-contact / 50,000-event history runs in bounded time and is deterministic (two runs, identical snapshots); human-authored flags survive recompute. Close the phase with one mutation-testing pass (mutmut) over `derivation/` and `resolution/` — surviving mutants mean the tests accompany the code rather than constrain it; kill them before proceeding.

## Phase 2 — Contract verbs and the wave lifecycle

`service/contacts.py`, `service/waves.py`, `service/queries.py`. Audience-rule evaluation (the JSON filter → SQL) lives here; it is the one piece of nontrivial interpretation — keep the supported rule grammar minimal (segment, trade, stage, wave non-response, do_not_mail exclusion) and reject unknown keys rather than ignoring them.

**Accept when:** the lifecycle draft → preview → approve → cancel is covered end-to-end in tests; preview and a subsequent hypothetical execution over unchanged state resolve identically; approve validates all documented preconditions and records approver; suppress is verifiably one-way (no code path un-sets it); create_variant with empty hypothesis fails; every query verb returns in one round trip (no N+1 — assert query counts in tests).

## Phase 3 — Seams and jobs (the external world, faked first)

`seams/` interfaces with **fake implementations first** (FakePrintApi, FakeResponseFeed with scripted events), then `LobClient` against Lob's test environment, `PostHogFeed`, `NmcFeed`. Then `jobs/sync.py`, `jobs/drop.py`, `jobs/nightly.py` orchestration.

Order matters within the phase: jobs are built and tested against fakes; vendor clients are then contract-tested against recorded real payloads (capture Lob webhook and PostHog/NMC response fixtures once, replay in tests forever).

**Accept when:** `execute_wave` against FakePrintApi is resumable — kill it mid-wave, re-run, piece count is exact with zero duplicates; drift-halt fires when audience at execution differs from approved preview beyond tolerance; `parse_webhook` translates every recorded Lob payload to a canonical taxonomy event with vendor vocabulary appearing nowhere above the seam; nightly orchestration halts before recompute on any sync failure (test this — it is the "never judge stale state" guarantee); a full nightly run against fakes is one command.

## Phase 4 — Judgment

`judgment/protocol.py`, all ten rules as individual files with auto-discovery, `config/params.py`, `composer.py` with template fallback, `digest.py` with budget/cooldown/expiry, nudge emission as events. Also in this phase: the **data assertion rules** (data document §3, "Continuous data assertions") — reconciliation, liveness, integrity, and distribution checks implemented as rules in `judgment/rules/assertions/`, following the same Rule protocol, firing into the digest at high priority.

**Accept when:** each rule has a fixture scenario that fires it and a near-miss that doesn't; discipline mechanics are tested as behaviors (11 hits + budget 5 → 5 sent and 6 deferred in priority order; nudged contact stays quiet through cooldown unless a new inbound arrives; expiry re-evaluates fresh); human-set next_action is never overwritten before it passes; composer timeout falls back to template with the digest still sending (simulate model failure in test); a zero-hit night sends nothing; every sent nudge exists as a `nudge.sent` event with rule name and facts in payload; each data assertion fires against a deliberately corrupted fixture database (dead feed, missing costs, drifted variant split, post-suppression piece) and stays silent against a clean one.

## Phase 5 — Surfaces

`web/api.py` as a thin FastAPI layer over service verbs (no logic — a review check, not just a guideline), the UI panels (wave dashboard, approval queue with preview rendering, contact timeline, pipeline view, activation board), digest delivery wired to real SMS/email through NMC's own sending path.

**Accept when:** the approval screen renders exactly `preview_audience` output and the approve action carries the previewed state's hash so a drifted wave cannot be approved stale; every UI view maps to exactly one query verb; `execution.py` verbs have no HTTP route; the app runs in the same Docker/VPS pattern as existing NMC infrastructure.

## Phase 6 — The ghost wave (integration test with reality)

Before wave 1: a real wave of ~10 pieces to the founders' own addresses and friendly volunteers, through the real Lob production path, with real QR scans, real calls to the campaign line (exercising the "nevermisscall" vertical config), a real booking, a deliberate opt-out, and a deliberate ignore (to age into quiet_reengage).

**Accept when:** every piece's journey is visible in the contact timeline end to end; attribution joins hold for both web and phone response; the nightly run produces correct nudges from the ghost cohort; the wave dashboard's cost-per-response matches hand arithmetic; one backup is restored onto a scratch database and the timeline still reads. This phase's output is not code — it is the go/no-go for wave 1.

---

## Cross-cutting

**Test posture — three tiers, each answering a different question:**
1. *Was it built to spec?* Frozen acceptance tests in `tests/acceptance/`, written first from this plan's criteria, through public contract verbs only. Authoritative; modification is an escalation.
2. *Do the internals hold while changing?* Disposable unit tests in `tests/unit/` — fast, in-loop, freely rewritten, no authority. Property-based (Hypothesis) where logic is pure; recorded-fixture contract tests on seams; mutation pass at phase 1 keeps them honest.
3. *Is the world still flowing through it correctly?* Data assertions running nightly against **production** (built in phase 4 as judgment rules) — reconciliation, liveness, integrity, distribution. Code tests end at deploy; these run forever.

No coverage targets — the acceptance checks and assertions above are the coverage that matters.

**Suite growth is permanent and expected.** Test cost has collapsed; the correct response is more tests at the speed scenarios occur. Standing rule for all future work on this system: every e2e or production failure, every debugging session, and every founder suspicion ("could the sync die silently?") ends by leaving a test or data assertion behind at the appropriate tier. The suite is the system's accumulated scar tissue; it only grows. The ghost wave and wave 1 will surface failures the fixtures didn't imagine — that is their job; backfill coverage from each and move.

**Sequencing rationale:** phases follow the dependency rule, so every phase is testable the day it's built with nothing mocked above it and only fakes below. External vendors enter at phase 3 behind already-tested interfaces, which contains integration pain to the seam files where it belongs.

**Definition of done for the whole build:** the ghost wave passes, the architecture-review command reports clean at the final boundary, and wave 1's audience can be drafted, previewed, and approved by a founder using only the UI and Claude Code — no psql, no manual steps.
