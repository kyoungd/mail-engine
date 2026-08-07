# docs/coding/ — how we write and verify code

The home for coding-preference documents: philosophy and conventions that
outlive any single feature. Product/design docs (PRD, data document, service
contract, design companions) stay in `docs/`; session history stays in
`current-state.md`; decisions stay in `decisions.md`. What belongs here is the
durable "how": testing philosophy, style conventions, review practices.

- [`testing.md`](testing.md) — the test philosophy: tiers and their authority,
  the release gate, the risk rule, standing invariants, the owed list.
- [`simplicity.md`](simplicity.md) — the simple solution wins: YAGNI over
  principle-completeness, minimum code to green, no unasked additions,
  deliberate absence is design.
- [`boundaries.md`](boundaries.md) — uncoupled code and limited blast radius:
  contracts never internals, the one-directional dependency rule, care scaled
  to fan-in, cut where contracts get fixed.
- [`debugging.md`](debugging.md) — understand before fixing, evidence not
  assumption, instance-vs-class, run the thing; the fail-loud observability
  stance (events as the record, anomalies raise, jobs report).
- [`nmc-lessons.md`](nmc-lessons.md) — principles the parent project paid for,
  extracted with their scars: refuse over wrong action, AI-first for natural
  language, identities not positions, one owner per bug-prone domain
  (mechanically enforced), interlocks not warnings, fix the class not the
  file, safety net before refactor, verify external facts, separate stores.
- [`architecture-review.md`](architecture-review.md) — the architecture-review
  standard, mail-engine-adapted: three standards (no duplicated knowledge,
  encapsulation both ways, cohesion without coupling), "the design is already
  decided" conformance rule, findings ranked by real cost.
- [`interface-extraction.md`](interface-extraction.md) — the companion
  standard: extract each layer's intended contract plus where code diverges;
  feeds the architecture review.

**Canonical-copy rule for the two review standards:** the files HERE are
canonical. The runnable skills in `marketing/.claude/commands/` (parent repo)
are deployment copies — a cross-repo symlink would break other checkouts, so
duplication is accepted and managed: whoever edits either review doc re-syncs
the command copy in the same session.
