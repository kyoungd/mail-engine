# Mail Engine — Product Description (v3)

*Internal tooling for NeverMissCall's direct mail channel. 2026-07-26. Supersedes v2.*

*This is the orientation piece: what the thing is and how the parts fit. `PRD.md` is the
consolidated statement of what and why; `decisions.md` carries the vendor and design calls
with their reasoning; `current-state.md` is where the build actually stands;
`technical-debt.md` is the honest list of what is read but never written. Where this
document and the PRD disagree, the PRD wins.*

## What it is

A campaign operating system that sits between the prospect database and the print API and
runs the full 3-drop direct mail lifecycle per contact — list intake, wave composition,
approval, drop execution, response attribution, and the nightly pass that decides which of
it deserves a founder's attention today. It is an execution and measurement layer for a
strategy the operator already owns; it does not set strategy, offer, or creative direction.

It replaces a CRM, and not by being a smaller CRM. There is no pipeline to groom and no
stage to drag. State derives itself from instrumented channels, and software watches the
result and taps the right founder on the shoulder.

## Architecture in one sentence

A contact database is the spine; Lob executes mail out of it; PostHog and NeverMissCall
feed response back into it; contact state derives itself from an append-only event log; AI
sits on top as analyst, drafter, and briefing officer.

## The four parts

### 1. The spine — contacts, and an append-only event log

Purchased lists load through one intake adapter per source format, so the spine never
learns a vendor's columns: filter to live records, dedupe on an adapter-prefixed key,
normalize phones to E.164, validate addresses, assign a segment. Today that is the CSLB
contractor list and CA county FBN filings — **102,431 contacts** (84,072 `cslb-ca`,
18,359 `fbn-ca-2026`), of which **83,975 carry a phone**; every FBN record has none, which
is a fact the callable-universe math has to respect.

Everything that happens to a contact lands as an **append-only event** in a closed
taxonomy, retained indefinitely. PostHog, Lob, and NeverMissCall are feeds, not systems of
record. Contact stage, response status, and suppression are then **derived** from that
stream by versioned pure functions, recomputable over full history after a definition
changes. Human-authored facts — `do_not_mail`, `do_not_text`, founder-set next actions —
survive recomputation.

That grain is load-bearing rather than decorative: it is why a wave readout run in December
returns the same numbers it returned in July, even after ownership, definitions, and
segments have all moved underneath it.

### 2. Execution — a gated wave lifecycle

**Draft → preview → proof → approve → drop.** An audience rule is stored as a reviewable
rule, and one function resolves it for both preview and execution, so what is approved
cannot diverge from what fires. Preview renders the resolved count, a breakdown, a cost
estimate, and a sample.

Approval is gated on the **print vendor's own final rendering** — a Lob test-environment
proof per variant, embedded in the approval screen. The founder approves the file that will
actually print, not the composer's HTML idea of it. No proof, no approval: it fails closed.
The proof's creative checksum folds into the approved artifact's state hash, so creative
edited after approval halts execution as drift rather than printing quietly.

Drops fire through the print seam (Lob; PostGrid is a one-file fallback), one piece per
contact per wave as a hard constraint, each carrying a unique mailer code that drives the
QR/`?r=` tracking and the campaign phone attribution. Cost is recorded per piece; delivery
status arrives by webhook. The whole thing is idempotent and resumable — the mailer code is
the vendor's idempotency key.

Every wave also carries a **seed piece** to each founder address. It is the only check on
physical print quality that exists, since delivery timing is already covered per piece.
Seeds appear in the approval breakdown because they really fire, and are excluded from
every response metric, from the pipeline, and from the judgment layer.

Nothing prints without a human. Execution stays job-first: `execute_wave` is reachable only
through the batch `run_drops` job, by cron, CLI, or a password-gated page.

Current format: 6×9 First Class, typographic on solid color, no image backgrounds.

### 3. Response capture and attribution

Three inflows, all idempotent under replay:

- **Web** — PostHog, pulled nightly over the HogQL query API on a fixed lookback; visits,
  CTA clicks, and landing purchases, deduped on `(source, external_id)`.
- **Delivery** — Lob webhooks, real-time and signature-verified.
- **Phone** — **not wired.** There is no `NmcFeed` yet, so no call or text to an NMC line
  reaches the spine. Phone responders are hand-matched from Twilio after each wave and the
  undercount is accepted deliberately (`decisions.md`, 2026-07-15).

That last gap has a direction, and the direction is the dangerous part. The funnel is built
so the **demo line carries conversion and the URL is the afterthought** — so the channel the
system can see is the weaker one by design. URL-only numbers understate response and
overstate cost-per-response, and "the card worked and we couldn't see it" looks exactly like
"the card failed." Do not retire a creative on URL-only evidence; hand-match first, then
read.

Attribution resolves by strict precedence — **mailer code → thread continuity → exact
phone** — and never fuzzy-matches. What does not resolve is stored as an orphan and surfaced
weekly rather than guessed at. Orphan rate is a published number, not an embarrassment to
hide: leakage is expected, and the queue is what keeps it visible and bounded.

Opt-outs are honored instantly, permanently, and irreversibly. A CCPA deletion hard-deletes
the contact and anonymizes its events — identity severed, aggregates preserved.

### 4. Judgment — the layer that replaces the CRM

Nightly, after sync and recompute, deterministic rules look for conditions worth a founder's
attention: quiet responder, hot response, demo no-show, activation stall, activation
partial, returned mail, wave anomaly, pending approval, orphan backlog, aging-out. AI then
composes each into a 30-second action brief; a template fallback means delivery never
depends on the model being available.

The discipline mechanics are requirements, not options, because an ignored nudge channel is
worse than no channel: a **five-nudge daily budget** per recipient with priority overflow, a
per-contact cooldown, **expiry rather than escalation**, one morning digest per founder, and
**silence as a valid output**. Nudges are logged as events, and the job grades itself monthly
against whether its nudges led to action.

The last inch is not connected: the digest is assembled and logged, but **no sender
implementation exists**, so nothing is delivered today (TD-10).

Nudges route to the contact's owner, which is how a partner-owned contact's response reaches
the partner rather than the founder who ran the wave. (`contacts.owner` currently has no
writer — see `technical-debt.md` TD-2.)

## Where AI does the work

1. **Intake** — cleanup, dedupe, and segmentation of purchased list data.
2. **Creative variation** — copy variants per segment within the operator's direction. A
   variant cannot exist without a one-line hypothesis; the schema enforces it.
3. **Nightly briefs** — the judgment layer above.
4. **Conversational analysis** — plain-language questions ("cost per response by segment in
   wave 2, and does drop timing correlate?") answered by AI writing SQL against retained raw
   history through a read-only role, returned as prose with numbers. No BI tool. Recurring
   questions graduate into fixed UI panels; novel ones never require new UI.
5. **Wave readout** — a learnings memo after each wave quoting each variant's stated
   hypothesis against its result, with denominators that exclude seed pieces.

## The human surface

A thin server-rendered web UI, one verb per route, no logic in the web layer: wave index and
composer, approval queue with the proof embedded, variant catalog, contact search and
timeline with founder actions (note, next action, lost, suppress), list intake, orphan queue,
pipeline view, activation board, due nudges, and the password-gated drops page. No analysis
features live here.

Two users, both founders, no auth machinery beyond audit attribution. The only manual inflow
is a voice note or text, AI-structured onto the right contact, with a 30-second friction
ceiling. If those notes stop, the AI is reasoning over gaps — and the nudges will say so.

## Boundaries and control

**Human sign-off per wave.** The AI drafts audience, variants, and timing; the operator
releases it. At current volumes the cost of a sign-off step is minutes and the cost of a bad
autonomous batch is real money and a burned list segment.

**Scope ends at handoff.** When a contact responds and books, they leave the mail sequence
and enter NeverMissCall's own push-based flow. There is no downstream CRM in this
architecture, and adding one is not the plan.

**No cold outbound SMS to list contacts, ever.** Mail is the cold channel; SMS is the warm
reply channel. This is structural, not a policy: no code path exists for it.

**Information-buying posture.** The success metric for the 60-day phase is learning-per-hour,
not response rate. Every wave answers a question someone deliberately asked, which is why the
hypothesis is a schema constraint rather than a convention.

## What is not built

Stated here because a product description that only describes what works is a sales
document. Full detail, with evidence, in `technical-debt.md`:

- **No nudge is delivered to anyone** (TD-10) — the judgment layer computes, composes, and
  logs `nudge.sent`; the sender seam has no implementation and the nightly never passes one.
- **Phone response has no transport** (TD-1) — hand-matched, by decision.
- **Two columns are read by live logic and written by nothing** — `activation` and
  `contacts.owner` (TD-2). The activation board is permanently empty and the partner nudge
  branch has never executed, with the suite green.
- **Cost-per-customer is not computable** (TD-3) — the spine ends at signup; revenue lives
  across the two-database boundary.
- **The preview's cost estimate is hardcoded** and understates real spend (TD-4).
- **Responder exclusion from later drops is opt-in**, one forgotten rule key from mailing a
  responder again (TD-5).
- **`do_not_call` does not exist** (TD-6) — suppression covers mail and text only.

## What it explicitly is not

Not a CRM, and specifically not a partner CRM — the spine records custody and facts, never
call dispositions. Not a growth-hacking system, not an autonomous marketer, not a BI tool,
not a marketing automation platform, not a replacement for judgment on offer, pricing, or
creative. It is disciplined plumbing for a traditional 3-drop campaign, with AI removing the
labor from list hygiene, variation, analysis, and remembering who to call back.
