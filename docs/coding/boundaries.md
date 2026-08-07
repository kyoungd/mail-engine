# Boundaries — uncoupled code, limited blast radius

*Distilled from the architecture already enforced (PRD SR-2/SR-3, the layer
rules in `marketing/CLAUDE.md`, the Rule Zero mutate/consume split, and the
parent repo's coupling-vs-tests investigation,
`nvermisscall/docs/fable5-tune/05-coupling-vs-tests.md`).*

## Coupling: contracts, never internals

- **The dependency rule is one-directional:** `web`/`jobs` → `service` →
  `derivation`/`resolution` → `domain`. Vendor SDKs live only in `seams/`.
  `service/` never imports `jobs/` — shared logic moves to its own module
  (`resolution/pick.py` is the precedent).
- **`service/` is the only write path.** Routes and jobs call verbs; nothing
  else writes. A capability lives whole in one owner; consolidation that
  widens what modules know about each other's internals is a trade down.
- **Seams are Protocols with fakes, 1:1.** A module knows *what* a vendor
  offers, never *how*. Vendor field names stop at the seam (anti-corruption);
  an unrecognized vendor value is an error, not a pass-through.
- **Across repos, the same rule harder:** consume NMC only through published
  seams (GET an endpoint, SELECT a granted role) — never its code, never its
  tables' internals. Two docstrings agreeing is not a contract; a test in
  `tests/integration/` is.
- **Closed sets stay closed.** The event taxonomy admits a new type only as a
  deliberate act with a reader. Identity resolution is never fuzzy. Openness
  in a boundary type is coupling to everything that might someday cross it.

## Blast radius: scale care with fan-in

- **Approval already scales with blast radius** — that is what the 🟢/🟡/🔴
  tiers are. The same logic applies inside the code: the more callers a module
  has, the more a change to it deserves tests, review, and hesitation.
- **The measured warning:** in the parent codebase, test investment rose with
  fan-in and then *collapsed* on the most-imported files — the widest blast
  radius had the least protection. Watch for that inversion here; the
  highest-fan-in modules (`db/session`, `domain/`, `service/` verbs) must not
  become the least-tested.
- **Cut work where contracts get fixed.** When batching phases, the boundary
  is a migration's DDL, a verb signature, a Protocol — the points after which
  change is expensive. Fix those deliberately; keep everything behind them
  cheap to change.
- **Migrations are maximum blast radius** — additive is still 🔴 here. A
  column populated by nothing that a future reader might trust is damage
  (TD-2); drop what has no reader.
