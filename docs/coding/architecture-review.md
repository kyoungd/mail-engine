---
description: Architecture review of the mail-engine app — read-only, produces a hand-off doc for Opus 4.8 to execute
model: claude-fable-5
effort: high
mode: plan
---

# Architecture Review

Review the architecture of $ARGUMENTS (default: the whole mail-engine app — every
layer built so far).

This is a **read-only review**. Do not edit files. Your output is a document that a
different model (Opus 4.8), with no memory of this analysis, will execute later.

## What I'm optimizing for

This is a small, bootstrapped, two-person codebase. Founder hours are the scarce
resource, not architectural purity. **YAGNI outranks principle-completeness.** A
"correct" refactor that doesn't pay for itself is a net loss. Every recommendation
must justify itself against a real cost I am paying *today* — a change that's hard to
make, a bug that recurred, a place I'm afraid to touch — not against a principle being
incompletely satisfied. "This violates the pattern" is not a reason to act;
demonstrated friction is.

## The design is already decided

Schema, the service-layer contract verbs, the closed event taxonomy, the dependency
rule, and the *deliberately absent* lists (no `Campaign` aggregate, no repository
pattern, no domain-event bus, no analytics verbs, no generic `update_contact`) are
settled in the design docs (`../direct-mail-ai-*.md`,
`../mail-engine-product-description.md`). Review the code's **conformance** to them; do
not propose additions beyond them. If you find a genuine flaw in a decided document,
flag it as an **escalation** — do not design around it silently.

## The standards to review against

These are three scales of one idea: knowledge lives in exactly one place, and modules
expose contracts rather than internals. Apply nothing beyond them.

**1. No duplicated knowledge (within the app).**
Real duplication = a single conceptual change would force edits in multiple places to
stay correct. Flag that. **Ignore incidental resemblance** — do not merge code that
merely looks similar but answers to different callers or different business reasons;
collapsing it is the wrong-abstraction trap. Three repetitions is a signal; two is
often coincidence. The derivation definitions (`responded`, `went_quiet`, `suppressed`)
are the canonical single-source case: flag any copy of that logic living outside
`derivation/rules.py`.

**2. Encapsulation (within a module).**
Flag classes or modules whose invariants can be violated from outside, or data
manipulated by external code that should own its own state. The service layer's
encapsulation standard is explicit: the tables are unreachable except through a verb
(Rule 1, writes never bypass), and verbs validate, never interpret (Rule 5). Flag any
state change that sidesteps a verb, and any snapshot written without a corresponding
event (Rule 3). **Also flag over-encapsulation as its own finding** — the docs already
forbid the repository pattern, unit-of-work scaffolding, a domain-event bus, and
single-value wrapper classes; flag such ceremony if it has crept in. The goal is a
module that can't be misused, not one with more accessors.

**3. The dependency rule (the app's coupling law).**
The rule, from the code layout: `web`/`jobs` → `service` → `derivation`/`resolution` →
`domain`; `seams` imported only by `jobs` and `service/execution`; nothing imports
upward; `db.readonly` importable from anywhere (it cannot write). This is **checkable —
verify the actual import directions**, do not take it on faith. Flag: any upward
import; any layer reaching past its permitted dependencies (e.g. `web` importing
`derivation` directly instead of going through a `service` verb); any `seams` import
outside `jobs`/`service.execution`; any capability smeared across layers that should
live whole in its owner (audience-rule interpretation belongs in `service/waves`;
`events → judgment` logic belongs in `derivation/rules` as pure functions with no I/O).
**But consolidation must never violate the dependency rule or widen what one layer
knows about another's internals.** If you'd "fix" fragmentation by adding an upward
import or reaching into internals, stop — that trades one problem for a worse one.

## Integration boundaries — the seams, treat separately

Lob/PostGrid (print) and PostHog/NMC (response feeds) are a *different* boundary than
the app's own database. Each vendor is owned by exactly one seam module behind a
Protocol (`PrintApi`, `ResponseFeed`) whose whole job is to keep the vendor's data
model, error types, and API details from leaking upward. **NMC is consumed through the
same `ResponseFeed` contract as third parties — no special access.** This is an
anti-corruption seam, not a DAL — do not conflate the two, and do not generalize across
the seams: `PrintApi` and `ResponseFeed` answer different needs, and a `PostGrid`
client is a new file, not a reshape of the interface. Flag any vendor vocabulary
(Lob/PostHog/NMC field names, error classes, payload shapes) appearing above a seam.

## Data access

Flag raw SQL or direct table access living in `web` or `jobs` — writes must go through
a `service` verb, reads through the read-only role. **Also flag any data abstraction
more general than actual usage** — generic repositories, database-agnostic machinery,
unit-of-work scaffolding — as premature; the docs exclude these by name. `db/session.py`
(transaction-per-verb) and `db/readonly.py` are the sanctioned surface; anything more
general than the access actually performed does not pay rent.

## Guardrails on your own behavior

- Do not propose features, refactors, or abstractions beyond what the standards above flag.
- Do not design for hypothetical future requirements. The simplest thing that works wins.
- Rank every finding by real cost-benefit. A flat list of violations is not useful.
- Where applying any of these standards would be premature or create the wrong
  abstraction, say so explicitly rather than recommending it.

## Output format — write for an implementer who was not present for this review

Produce a single document. For **each finding**:

- **File / module** — the exact location.
- **Problem** — one or two concrete sentences.
- **Change** — the minimal fix. **Describe the change; do not write the full
  implementation.** Diff-level specificity, not finished patches — Opus writes the code
  against the live files.
- **Rationale** — one line, enough for Opus to make judgment calls mid-edit.
- **Leave alone** — an explicit boundary of what NOT to touch while making this change.

Make each finding **independently executable** so I can hand Opus a subset and drop the
rest. If two findings genuinely depend on each other, say so; otherwise default to
self-contained. **Rank the whole list by payoff.**

## Stop condition

Report the findings and stop. Do not begin implementing, do not tidy adjacent code, and
do not expand the review beyond the three standards and the dependency rule above.
