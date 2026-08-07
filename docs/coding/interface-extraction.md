---
description: Extract the intended contracts of the mail-engine layers (service verbs, seam Protocols, Rule protocol) plus where code diverges — read-only reference doc that feeds the architecture review
model: claude-fable-5
effort: high
mode: plan
---

# Contract Extraction

For $ARGUMENTS (default: the whole mail-engine app), produce a per-layer contract
reference. This is a **read-only** pass. Do not edit files. The output is the reference
document that a later architecture review — and Opus 4.8 executing its findings — will
measure the code against.

## Why this exists

The architecture review checks whether each layer depends on another's *contract*
rather than its *internals*, and whether the dependency rule holds. That check is only
meaningful if the contracts are written down. Your job is to write them down — and to
record honestly where the code already diverges from them. That divergence list is the
raw material for the dependency-rule review; produce it carefully.

## The one distinction that matters

There are two different things and you must not blur them:

- **The intended contract** — the minimal, true surface a layer means to expose to its
  callers *today*. What capability it owns; what other layers can legitimately ask of it.
- **What currently leaks** — internals reachable from outside that shouldn't be, callers
  reaching into implementation, logic that belongs here but lives elsewhere, an upward
  import that the dependency rule forbids.

Document the first as the contract. Document the second as **divergence** — never fold a
leak into the contract to make the code look conformant. A photograph of everything
currently reachable from outside is *not* a contract; it's a picture of the coupling.
The gap between the two is the point of this exercise.

## The contracts in this app (a small, enumerable set)

- **Service layer** (`service/*`) — THE write contract. The verbs: `ingest_event`,
  `resolve_orphans`, `record_note`, `load_list`, `suppress`, `record_outcome`,
  `set_next_action`, `create_variant`, `draft_wave`, `preview_audience`, `approve_wave`,
  `cancel_wave`, `execute_wave`, `recompute_state`, and the query verbs
  (`get_wave_dashboard`, `get_pipeline`, `get_contact_timeline`, …). Callers: `web`,
  `jobs`, Claude Code. Honor the service-contract doc's *deliberately not in the
  contract* list (no analytics verbs, no event edit/delete, no generic `update_contact`,
  no auth machinery) — a verb that adds such is a divergence, not a contract entry.
- **Seam Protocols** (`seams/*`) — `PrintApi` and `ResponseFeed`: the clean
  internal-facing surface that is the anti-corruption boundary against Lob/PostGrid and
  PostHog/NMC.
- **Rule protocol** (`judgment/protocol.py`) — the `Rule` interface the nightly job
  discovers and runs; one rule per file, no registry.
- **Pure surfaces** — `derivation/rules.py` (`events → judgment`, no I/O) and
  `resolution/matcher.py` (the precedence chain, never fuzzy). Their contract is their
  function signatures plus the invariant that they never touch the database.

Extract only the layers that actually exist in what you're reviewing; note which of the
above are not yet built rather than inventing their surface.

## Guardrails — this pass over-abstracts if you let it

Told to "define an interface," a high-effort model will design an aspirational API.
Do not. Specifically:

- Document the contract each layer **actually fulfills for real callers now**. No
  versioning, no extension points, no methods that might be wanted someday, no
  speculative generality.
- The contract is as small as it can be while still covering what callers truly depend
  on. If a currently-public function has no legitimate external caller, that's a
  divergence finding (over-exposure), not a contract entry.
- Do not redesign the surface. Describe the intended contract as it should minimally be,
  and flag reality against it — do not propose a new API shape.

## Integration seams — special case

The seams owning Lob/PostGrid/PostHog/NMC each exist to keep the vendor's data model
from leaking into the rest of the app. For those, the contract is the clean
internal-facing surface (`PrintApi`, `ResponseFeed`); the divergence list should call
out anywhere the vendor's data shapes, error types, or API details have escaped past the
owning seam. **NMC gets no special access despite being our own product** — same
`ResponseFeed` contract as third parties; note it if the code gives it a side door.

## Output format

One reference document, a section per layer/surface. For each:

**Owns** — one line: the capability this layer is responsible for.

**Contract** — the intended surface callers depend on. For each operation: its name,
what it does, and its inputs/outputs at the contract level (not full signatures unless
needed for clarity). Keep it minimal and true to today.

**Divergence** — a list, each entry being one of:
  - *Over-exposure* — reachable from outside with no legitimate external caller.
  - *Internal dependency* — a caller depending on this layer's implementation rather
    than its contract (name the caller) — including dependency-rule violations (an
    upward import, a layer skipping through to another's internals).
  - *Misplaced capability* — logic that belongs to this layer but currently lives in
    another (name where).
  - *Leak* (seams) — vendor data model / error types / API details escaping the boundary.

Each divergence entry: the location, one concrete sentence on the problem, and — for
seam and internal-dependency cases — which side is wrong (the exposer or the caller).

## Stop condition

Produce the contract-plus-divergence document and stop. Do not fix anything, do not
redesign interfaces, and do not extend beyond documenting what is and what should
minimally be.
