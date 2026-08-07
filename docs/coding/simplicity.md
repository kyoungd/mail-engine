# Simplicity — the simple solution wins

*Distilled from rules already in force (`marketing/CLAUDE.md` § LIST OF DON'T,
the TDD workflow, `architecture-review.md`'s optimization statement, and the
PRD's non-goals). Nothing here is new policy; this is the scattered policy in
one place.*

## The optimization target

This is a small, bootstrapped codebase where founder hours are the scarce
resource. **YAGNI outranks principle-completeness.** A "correct" abstraction
that doesn't pay for itself is a net loss. Every piece of structure must
justify itself against a cost being paid *today* — a change that's hard to
make, a bug that recurred — never against a principle being incompletely
satisfied.

## The rules

- **Minimum code to green.** The approved test defines done; write the least
  code that satisfies it. Generality the test doesn't demand is speculation.
- **No unasked additions.** No refactors as a side-effect of another change, no
  error handling that wasn't asked for, no new dependencies, no library swaps,
  no comments explaining what code does. The diff should be the task.
- **Don't design for hypothetical futures.** The simplest thing that works
  wins. A data layer for a database migration that will never happen, a
  generality for a second vendor that doesn't exist — premature, flag it,
  don't build it.
- **Deliberate absence is design.** The repo's missing abstractions (no
  `Campaign` aggregate, no repository pattern, no domain-event bus, no generic
  `update_contact`) are decisions, not omissions — read `decisions.md` before
  "completing" one.
- **Structure earns its place by recurrence.** The PRD's rule for UI panels
  generalizes: build the fixed thing when the need recurs, not the first time
  it appears. Three repetitions is a signal; two is often coincidence.
- **Simple ≠ loose.** Fail-loud beats gracefully-vague (see
  `debugging.md`); a short function with a strict contract is simpler than a
  long one that tolerates everything.
