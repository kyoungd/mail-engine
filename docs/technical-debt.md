# Technical debt — Mail Engine

*Opened 2026-07-26 from the v3 product-description pass. Nothing here is fixed; this is the
register. Companions: `decisions.md` (the calls and their reasoning), `current-state.md`
(where the build stands), `PRD.md` (the contract these are measured against).*

**Nothing in this file is a bug report against a failing test.** Every item below coexists
with a green suite — that is what makes them worth writing down. Where an item is a
deliberate accepted trade, it says so and points at the decision; where it is an accident,
it says that too.

**Highest value first: TD-10** (nothing delivers a nudge) and **TD-2** (columns read by live
logic with no writer). They are the same failure shape at opposite ends of the system — a
complete pipeline missing its last inch, with tests that supply the missing piece themselves.

**Time-sensitive: TD-11** — it prices the Lob AV purchase that Phase 4/5 depends on, and the
recorded estimate may be ~60% low. Cheap to settle (one look at the checkout screen).

---

## TD-1 — Phone response has no transport

**Status:** accepted trade, decided 2026-07-15 (`decisions.md`). Not a defect; listed so it
is not mistaken for working coverage.

No `NmcFeed` implements the `ResponseFeed` protocol — `seams/` has `posthog.py` and a test
fake. No call or text to any NMC line reaches the spine. Phone responders are hand-matched
from Twilio after each wave.

**Why it matters more than its size suggests:** wave 1's card makes the demo line the
primary CTA and the URL secondary, so the invisible channel is the *stronger* one by design.
The resulting error is directional — URL-only numbers understate response and overstate
cost-per-response, and a working card that was only called looks identical to a failed card.

**Revisit trigger:** wave-1's hand-match hit rate. High → the feed automates a working manual
step and is worth building. Low (he called from his cell, not the listed business line) → the
feed would not have saved us either, and the real fix is a per-piece-coded response path.

---

## TD-2 — The dead-writer class: columns read by live logic, written by nothing

**Status:** two confirmed members, one leaning fix, **no audit performed**. This is the
highest-value item in the file.

| Member | Read by | Written by | Consequence |
|---|---|---|---|
| `activation` table | `get_activation_board`, `judgment/rules/activation_stalled.py`, `activation_partial.py`, `/activation` | nothing outside four test files | Board permanently empty; the rule whose own docstring calls it *"the churn cliff, the single most valuable nudge in the system"* can never fire. PRD Goal 4 unmeetable. |
| `contacts.owner` | `judgment/digest.py:69-71`, to pick the receiving founder | nothing in `service/` | All 102,431 rows are `owner='young'`; the partner branch of nudge routing has never executed. |

**Why the suite is blind to both:** every test fabricates the writer's output before
exercising the reader. The seam between "the thing happened" and "the row exists" is the one
place no test crosses. `activation` was found only by driving a real sale; `owner` only by
designing the feature that would have used it.

**The trap in the obvious fix for `activation`:** of the four columns, only `signed_up_at` is
derivable from `signup.completed`. `first_lead_at` — which *is* the definition of activated —
describes behavior inside NeverMissCall, and that is TD-1. Shipping the cheap half alone is
worse than shipping nothing: every signup opens a row whose `first_lead_at` never arrives, and
`activation_stalled` fires forever on the best outcomes the business has, against a stated
success metric that the nudge channel stays trusted. Leaning hand-stamped (auto-insert on
`signup.completed` + a UI action to stamp `first_lead_at`), consistent with TD-1's posture.

**The unpaid part: no one has looked for a third member.** Both were found by accident, and
`partner-lead-assignment.md` §9 says explicitly to assume the class exists elsewhere and audit
for it. The audit is cheap and has not been run: enumerate every column and table read by
`derivation/`, `judgment/`, `service/queries.py`, and `web/`, then cross-reference against
`insert`/`update` sites outside `tests/`. Anything with readers and no writer is a member.

**2026-07-27 — prevention adopted, members unchanged.** The **authority map** and
**writer-named-at-declaration** conventions (`ingest-contact-migration.md` §11,
`decisions.md` 2026-07-27) are now standing design-doc requirements — an empty writers
cell is this class, visible at declaration time. That prevents new members; it neither
fixes the two above nor substitutes for the audit, which remains unrun. The ingest/contact
grain migration neither fixes nor worsens either member (`activation` is preflight-asserted
untouched; `owner` merges are asserted-uniform).

---

## TD-3 — Cost-per-customer is not computable

**Status:** structural; no fix proposed.

PRD Goal 1 promises response rate, cost-per-response, **and cost-per-customer** as queries
rather than spreadsheets. The first two hold. The third does not: the mail-engine spine ends
at `signup.completed`, while subscription revenue and lifetime live in the Medusa DB across
the 🔴 two-database separation. Correlating them is app-level work that nothing does today.

**Why it matters now rather than later:** the partner economics recorded on 2026-07-25 put
commission + bonus + co-op credit at 47–53% of year-1 gross. Judging a mail wave against that
number requires knowing what a mailed customer is worth, and the system cannot say.

---

## TD-4 — The approval screen understates wave cost by ~36%

**Status:** accident. Cheapest item here to fix.

`service/waves.py:41` hardcodes `_ESTIMATED_PIECE_COST_CENTS = 73` and `waves.py:338` uses it
for the preview total. The configured live rate is `LOB_COST_CENTS=99` in **both** dev and
prod `.env`, correct per the 6×9 First Class decision of 2026-07-12 — the estimate constant
simply never moved with it. Execution records real per-piece cost from the seam, so only the
number the founder approves against is wrong.

On campaign 1's ~1,450 pieces: **$1,058 previewed vs. ~$1,436 charged.** FR-3's claim is that
approval renders exactly what will fire, and cost is part of the artifact being approved.

Note also `web/api.py:506` and `seams/lob.py:76` both default to `87` — harmless while `.env`
sets 99 in both environments, but three separate places hold an opinion about piece cost and
only one of them is right.

---

## TD-5 — Re-mailing a responder is one forgotten rule key away

**Status:** accident of defaults; a design call, not just a patch.

The always-on audience clauses are `do_not_mail = false`, `stage_snapshot <> 'suppressed'`,
and `is_seed = false` (`service/waves.py:58-64`). Excluding people who already responded is
the **opt-in** `not_responded_to_wave` key (`waves.py:35`). Compose drop 2 or 3 without
remembering it and responders get mailed again — wasted spend, and a worse impression on the
one segment that already raised a hand.

Nothing in preview warns you. The v2 product description asserted this suppression was
automatic, which is where the belief came from; v3 no longer claims it.

**Open question before fixing:** default-on with an explicit override, or a preview warning
that names the count of already-responded contacts in the audience? The second preserves the
"audience rule is exactly what you wrote" property that makes preview trustworthy.

---

## TD-6 — `do_not_call` does not exist

**Status:** unbuilt, 🔴 tier, blocks partner lead assignment S-6.

Suppression covers mail and text (`domain/types.py:35-36`); `service/contacts.py:151` accepts
only `do_not_mail` and `opt_out` as reasons. There is no voice suppression flag, because until
partner assignment there was no voice channel to suppress.

FR-8 requires opt-outs honored instantly, permanently, irreversibly. The moment a partner
dials an assigned list, that guarantee has a hole in it. The known residual — a row already
pasted into a partner's spreadsheet cannot be recalled by software — is documented in
`partner-lead-assignment.md` S-6 and is procedural, not solvable at v1. The flag itself is
solvable and is a prerequisite for that feature shipping at all.

**Wider than first recorded.** `do_not_call` is not merely an internal convenience flag: it
is the **entity-specific do-not-call list** that the TSR safe harbor (16 CFR § 310.4(b)(3))
requires a caller to maintain, and it sits alongside a second, external flag for national
registry hits. The full compliance design — scrub at assignment, 31-day freshness as a
precondition, area-code-scoped subscription — is `partner-lead-assignment.md` § 6. Nothing
of it is built.

---

## TD-7 — Nothing enforces that a wave produces a readout

**Status:** by design, but the metric that depends on it has no mechanism.

FR-13's wave readout has no code artifact — no `readout`/`learnings` module exists outside
tests. It is a conversational act performed through FR-12 (Claude Code over the read-only
role), which is consistent and deliberate. But PRD §8 lists "every wave produces a readout
answering its stated hypotheses; zero waves fired without one" as a success metric, and
nothing in the system notices a wave that never got one.

A judgment rule would be the natural home: wave sent, N days elapsed, no readout event
recorded → nudge. That would require the readout to be recorded as an event, which it is not.

---

## TD-8 — Documentation duplicated between two directories

**Status:** minor, but it will bite silently.

Six documents exist byte-identical in both `marketing/` and `marketing/mail-engine/docs/`
(`mail-engine-product-description.md`, `direct-mail-ai-*.md`, `PRD.md`). They are in sync
today only because someone copies them. `mail-engine/docs/` is canonical; the root copies
should either become symlinks or be deleted, and until then any edit needs to be applied
twice.

---

## TD-10 — No nudge is delivered to anyone

**Status:** deferred by design (Phase 5), but the deferral is invisible from inside the
system and the event name actively misleads. Highest-value item in this file alongside TD-2.

`seams/sender.py` contains a `Sender` **Protocol and nothing else** — the only implementation
anywhere is `FakeSender` in `seams/fakes.py`, used by two tests. `judgment/digest.py:79`
delivers only `if sender is not None`, and `jobs/nightly_cli.py` calls
`run_nightly(feeds, since)` with no sender argument at all. So in every real run the digest is
assembled, the briefs are composed, `nudge.sent` events are written, and `next_action_at` is
stamped on the contact — and nothing leaves the machine.

**Why it is worse than a missing feature:** the event is named `nudge.sent`. Query the spine
and it will tell you nudges were sent. The monthly self-grading (PRD FR-10) grades a channel
that has never carried a message, and the success metric "≥ half of nudges lead to founder
action within expiry" is measuring nothing. TD-2's members are silent because a writer is
missing; this one is silent while *claiming* the opposite.

**Same blindness as TD-2:** `test_digest_delivery.py` injects `FakeSender`, so the suite
exercises delivery through a seam that production never fills.

**Blocks:** `partner-lead-assignment.md` S-7. (The design's revision 1 claimed routing
"becomes live the moment S-1 ships"; revision 3 already corrects this itself — it becomes
correctly *computed*, not delivered — and carries this finding as its own. The fix is
sequenced as Phase 3 of `partner-lead-assignment-implementation.md`.) Note also that
`digest.py:_resolve_recipient` returns the raw `contacts.owner` value and `Sender.send` takes
it as an opaque key, so whatever implements the sender needs a recipient → channel map, and an
unmapped partner is a silent drop of precisely the nudges that feature exists to route.
PRD §12 open question 3 (partner's channel — SMS or email) is therefore a build dependency,
not a preference to collect later.

---

## TD-9 — Live Lob key hygiene

**Status:** contained, rotation advised (carried over from `current-state.md`).

The real live Lob key had been hardcoded in `test_environment_guard.py` in both checkouts,
uncommitted and never pushed — GitHub push protection blocked it. Scrubbed in git and removed
from prod by the 2026-07-18 reconciliation. Rotating the live key remains sensible
defense-in-depth; it belongs only in `.env`.

---

## TD-11 — The AV backfill estimate may omit the plan base fee

**Status:** open, blocks nothing today, but it prices a decision that is coming. Opened
2026-07-29 while sanity-checking the per-lookup rate quoted in `verify_addresses` work.

The design's §5 backfill math is `$450 + 52k × $0.009 ≈ **$920** one-time` for ~102k
addresses — one Growth month, then drop the plan. **The per-lookup rates in §5 are
correct**: re-checked against lob.com/pricing on 2026-07-29 and every tier matched the
Phase 0 record (2026-07-27) to the cent — Developer `$0.05/additional` with no base,
Startup `1,000 for $25/mo` then `$0.025`, Growth `50,000 for $450/mo` then `$0.009`.

What §5 does **not** account for is that the same page advertises a plan **base** price
alongside those figures: Startup *"Starting at $260/month"*, Growth *"Starting at
$550/month"*. The page does not say whether the `$450/mo` address-verification line is
**inclusive of** that base or an **add-on to** it. On the additive reading the backfill is
`$550 + $450 + $468 ≈ **$1,468**` — roughly 60% over the recorded figure.

**Two things to settle at the checkout screen, before paying:**

1. Is the `$450/mo` AV allowance inclusive of the Growth base, or additional to it? That is
   the ~$920-vs-~$1,468 question.
2. Does buying AV require sitting on Growth at all? `decisions.md` (2026-07-11) keeps the
   **print** plan on Developer, and it is not obvious you can hold two tiers at once. If AV
   forces the whole account onto Growth, the print side inherits that plan for the month.

**Why this is here and not a design amendment.** §5 is operator-approved and ground rule 1
makes it decided; a possibly-understated cost is an escalation, not a patch. §5 already
names this exact residual — *"confirm in the dashboard at purchase (plan names/rates can
drift)"* — and the interesting part is which half drifted: the **rates did not**, the
**plan structure** is what needs a human at checkout. Public pricing pages cannot resolve
it; an authenticated dashboard can.

**Cheap mitigation already available.** The rate that matters for a *probe* is Developer's
`$0.05` with no base fee, so a bounded `verify_addresses --limit N` costs `N × $0.05` and
nothing else — ~$2.50 for 50 real addresses. That buys the real deliverable/undeliverable
mix for the CSLB list before committing to any plan, and is the sane first spend.

**Fallback if the terms moved materially** (unchanged from §5): scope the backfill to
mailed audiences only. The schema does not change either way.
