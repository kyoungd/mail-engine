# Lessons from NeverMissCall — principles the parent project paid for

*Extracted 2026-08-07 from the parent repo: its root `CLAUDE.md`, the
fable5-tune triage (`docs/fable5-tune/04-report.md` meta-patterns), and its
recorded incidents. Each entry is a principle NMC learned at real cost, stated
so mail-engine doesn't pay the tuition twice. Where a principle is already in
this folder's topic docs, it isn't repeated here.*

## 1. When uncertain, refuse — never act wrongly

NMC's core philosophy: *"better to fail gracefully than to make wrong
appointments or give wrong quotes."* The generalization: when the system cannot
be sure an action is right, the correct output is a refusal, a shortfall, or
silence — not a best guess. mail-engine already lives this (a stale DNC check
is a shortfall, not an exported row; the judgment job treats silence as valid
output; nothing prints without approval). Keep it true for every new verb.

## 2. Natural language is AI's job; deterministic code acts on structure

Never interpret natural language with word lists, regex, or string matching —
they break on synonyms, typos, and phrasing, and NMC banned them after real
breakage (booking-confirmation regex, farewell word lists). The AI extracts
structured data; deterministic code acts on the structure. For mail-engine this
binds the voice-note pipeline (FR-9), the composer, and any future classifier:
if a fix involves matching specific words in caller/founder text, stop — that's
an extractor's job.

## 3. Pass identities, not positions

NMC's slot-index bug: the AI offered "Monday 9 AM" and booked "Tuesday 9 AM"
because a slot was referenced by index and re-derived later. The rule became
datetime-first: pass the value itself, never an ordinal into a list that can
shift. mail-engine's equivalents are already right — mailer codes per
`(wave, contact)`, exact-phone resolution, ids in files — keep new interfaces
on identities, never "the third one."

## 4. A bug-prone domain gets ONE owner, enforced mechanically

Timezone math produced a whole bug class (§3.1 off-by-one days) until NMC gave
the domain a single owner library — fail-loud, the only place allowed to import
Luxon — and **enforced the ban with ESLint plus a dependency-free CI script**.
The principle: when a domain keeps generating bugs, centralize it AND make the
old way mechanically impossible, not just documented. mail-engine's precedents:
`domain/phone` for E.164, `resolution/pick.py` for the pick rule. If a third
bug ever comes from the same domain, that domain has earned an owner module and
a lint rule.

## 5. Interlocks, not warnings

Every hazard NMC neutralized with documentation recurred; the ones neutralized
with code stayed fixed. The committed `.env` shipped localhost to prod **four
times** before it was untracked and gitignored; a broken page shipped to prod
before the pre-deploy e2e became a gate; the emergency-before-quota guard is
code, not a review rule. mail-engine already builds this way (`tests/guard.py`
fail-closed, the AV gate armed only by its dedicated key, the source registry
failing loud) — the principle is: when a mistake is found, the fix is a
mechanism that makes it unmakeable, and a doc note is only the interim.

## 6. Fix the class, not the file

The triage's strongest finding: NMC's recurring bugs (CLARIFY clobber,
double-booking, lunch propagation) shared ONE root — branch logic accreting in
a single method everyone edits, because no per-case abstraction existed. Point
fixes kept the class alive. When the same file breaks twice, ask what
*abstraction* is missing, and fix that. Two corollaries from the same report:

- **No junk drawers.** A module of 57 exports with 63 importers is a coupling
  hotspot that forces ripple changes; give exports a bounded home before the
  drawer forms.
- **Error handling is designed in on risk paths, not sprinkled at incident
  sites.** NMC's riskiest files had the *least* handling because try-blocks
  were added reactively where things had already blown up. (This coexists with
  "no unasked error handling": the point is placement by risk analysis, not
  volume.)

## 7. Safety net before refactor; leave-alone is a decision

The triage sequenced tests-first onto untested hot spots *before* any
refactoring, and kept an explicit leave-alone list — "important + already
fine → touching it is negative EV." Both halves matter: never restructure
what has no characterization tests, and record what you deliberately did not
touch so it isn't "improved" later by accident.

## 8. Verify external-system facts against primary sources

NMC based an architecture document on a hallucinated vendor capability (the
A2P ISV memo) and had to walk it back; the rule became: never write an
unverified claim about a third party into docs or build on one — verify
against the primary source first. mail-engine already practices the strong
form (the DNC fixtures were marked UNVERIFIED until real portal bytes settled
the format; the seam docstring says pin to real bytes, never to a guess).
Every vendor claim gets this treatment.

## 9. Separate owners keep separate stores

NMC twice attempted database consolidation and twice abandoned it; the
standing rule is two physically separate databases, correlated in app code,
never joined. mail-engine inherits the posture: its spine, the Medusa
read-only mirror, and NMC's service DB are three connections with three
owners. Convenience joins across ownership boundaries are how independence
dies.

## 10. Small conventions that keep paying

- **Every CLI wires `--help`** with usage and examples — and the front door
  carries the procedure (`subscribe_area_codes --help` documents the whole
  SAN workflow, not just its flags).
- **Product docs become decision-complete before implementation plans** —
  data model, state machines, contracts, failure modes. "Decision-complete
  notes" are not a spec; harden the canonical doc, not the working to-do.
- **Archive before pruning.** Retention exports first and deletes second,
  except pure noise. An append-only event stream makes this cheap — keep it
  that way.
