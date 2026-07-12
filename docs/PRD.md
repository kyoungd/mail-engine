# PRD — Direct Mail AI (Mail Engine)

*Internal tooling for NeverMissCall. Version 1.0, July 2026.*
*Companion documents: product description, architecture overview, data document (`direct-mail-ai-data.md`), service contract, judgment job, code layout, implementation plan. This PRD is the consolidated statement of what and why; the companions carry the how.*

---

## 1. Problem

NeverMissCall is in a 60-day information-buying marketing phase. The direct mail channel (CSLB-list postcards, 3-drop cadence, ~500-piece waves) generates data across disconnected systems — print/delivery at Lob, web response in PostHog, phone response in NeverMissCall itself — with no spine joining them. Without that join: response rates have no reliable denominator, creative experiments produce no readable signal, responders slip through follow-up gaps, and new customers churn silently between signup and activation. The scarce resource is founder hours; the current alternative is manual tracking that consumes them or a CRM whose complexity solves coordination problems a two-person operation doesn't have.

## 2. Product thesis

A campaign operating system where a contact database is the spine, mail executes out of it via print API, response signals feed back into it automatically, and AI operates on top as analyst and briefing officer. Facts flow in once at the source; what flows out is judgments — rendered views, push nudges, prose answers. No CRM: state writes itself from instrumented channels, and software watches the pipeline and taps the right founder on the shoulder ("AI instead of CRM").

## 3. Goals

1. **Attribution**: every response — web or phone — joins to a specific piece, variant, wave, and cost. Response rate, cost-per-response, and cost-per-customer are queries, not spreadsheets.
2. **Experiment legibility**: every creative variant carries a hypothesis; every wave produces a plain-language readout grading it. The 60-day phase's success metric is learning-per-hour.
3. **Zero dropped responders**: a contact who responds enters a watched pipeline; going quiet triggers a founder nudge, never silence.
4. **Activation completion**: signed-up customers are tracked to first-captured-lead; stalls surface as the highest-priority alarm.
5. **Founder-hour efficiency**: no manual data entry beyond 30-second voice notes; no dashboard patrol; total system interaction measured in minutes per day.

## 4. Non-goals

- Not a CRM, not sales-stage machinery, not multi-seat pipeline management.
- Not a marketing automation platform, BI tool, or dashboard suite.
- Not autonomous: nothing prints without human approval; AI drafts and briefs, never decides.
- Does not extend into post-handoff sales conversations or customer-lifecycle communication (covered by NeverMissCall's own push-based architecture).
- No cold outbound SMS to the purchased list, ever (compliance bright line: mail is the cold channel, SMS is the warm reply channel).

## 5. Users

Two founders. Young (technical, owns mail channel) — primary operator: composes waves, approves drops, reads analyses, receives mail/activation nudges. Sales partner (non-technical, owns affiliate referrals) — receives pipeline nudges for owned contacts, uses pipeline and timeline views. No other users; no auth machinery beyond audit attribution.

## 6. Functional requirements

**FR-1 List intake.** Bulk-load purchased lists through one intake adapter per source format (CSLB contractor list; county FBN feeds, starting with CA — other states will arrive in other formats): filter to live records, dedupe on an adapter-prefixed per-list key, E.164 phone normalization, NCOA/CASS address validation, segment assignment. The spine never learns a vendor's columns. Intake report with counts.

**FR-2 Creative variants.** Variants stored with required one-line hypothesis and creative payload. A variant without a hypothesis cannot exist.

**FR-3 Wave lifecycle.** Draft (audience as stored, reviewable rule) → preview (resolved count, breakdown, cost estimate, sample) → human approval (recorded who/when) → scheduled execution → sent. Cancel valid until execution. Approval renders exactly what will fire; execution halts on drift from the approved preview.

**FR-4 Drop execution.** Approved waves fire through print API (Lob; PostGrid-swappable seam): one piece per contact per wave (hard constraint), unique per-piece mailer code driving QR/`?r=` tracking and campaign phone attribution, cost recorded per piece, delivery status from webhooks. Resumable and idempotent.

**FR-5 Response capture.** Nightly sync of web response (PostHog) and phone response (NeverMissCall campaign line under dedicated "nevermisscall" vertical config — the product dogfooding itself as first-contact demo). Real-time Lob delivery webhooks. All inflows land as append-only canonical events (closed taxonomy); idempotent under replay.

**FR-6 Attribution.** Identity resolution by strict precedence (mailer code → thread continuity → exact phone); never fuzzy-matched; unmatched events stored and surfaced weekly rather than guessed.

**FR-7 Derived state.** Contact stage, response status, and suppression derived from the event stream by versioned pure functions; recomputable over full history after definition changes. Human-authored facts (do_not_mail, do_not_text, founder-set next actions) survive recomputation.

**FR-8 Suppression & compliance.** Opt-outs honored instantly, permanently, irreversibly. STOP handling on SMS. CCPA deletion = contact hard-delete + event anonymization (identity severed, aggregates preserved).

**FR-9 Human residue capture.** Voice note / text → AI-structured event on the right contact. The only manual inflow; friction ceiling 30 seconds.

**FR-10 Judgment job.** Nightly, after sync and recompute: deterministic rules detect conditions (quiet responder, hot response, demo no-show, activation stall/partial, returned mail, wave anomaly, pending approval, orphan events, aging-out), AI composes 30-second action briefs (template fallback — delivery never depends on the model). Discipline: 5-nudge daily budget with priority overflow, per-contact cooldown, expiry not escalation, one morning digest per founder via NMC's own sending, silence as valid output. Nudges logged as events; the job grades itself monthly.

**FR-11 Web UI.** Thin window over service verbs (v1: every founder-initiated verb is fronted; one verb per route, no logic in the web layer): wave index + composer (draft, preview, cancel), approval queue (preview + approve button — approval remains the gate before any drop), variant catalog (create requires hypothesis), contact search + timeline with founder actions (note, next action, lost, suppress-with-confirm), list intake (CSV upload + report), orphan queue (view + resolve pass), pipeline view, activation board, due nudges. No analysis features. Execution stays job-only: `execute_wave`, `sync`, `recompute`, and the nightly are never routed — dropping mail is a job, not an HTTP call.

**FR-12 Conversational analysis.** Ad-hoc questions answered by AI (Claude Code) via SQL through a read-only role against retained raw history. Post-wave learnings memo quoting variant hypotheses against results. Recurring questions graduate to fixed UI panels; novel ones never require new UI.

**FR-13 Wave readout.** After each wave: segments, variants, timing vs. response and cost-per-response, in prose, grading the stated hypotheses.

## 7. System requirements

- **SR-1** Postgres 15+ spine; six tables per the data document; events append-only, retained indefinitely.
- **SR-2** Single typed service layer is the only write path (UI, jobs, AI, founders included); reads may bypass via read-only role.
- **SR-3** Dependency rule: `web`/`jobs` → `service` → `derivation`/`resolution` → `domain`; vendor SDKs confined to seam modules; NMC consumed through the same feed contract as third parties.
- **SR-4** All writes idempotent; sync jobs replay-safe via `(source, external_id)`.
- **SR-5** Runs on existing Docker/VPS infrastructure; nightly cadence sufficient for all non-webhook flows.
- **SR-6** Nightly offsite backups; restore tested before wave 1.

## 8. Success metrics (60-day phase)

- 100% of pieces carry working attribution; ≥95% of response events auto-attributed (orphans < 5%).
- Every wave produces a readout answering its stated hypotheses; zero waves fired without one.
- Zero responders aged out without a nudge having fired; median founder response to hot_response nudge < 1 business day.
- Zero activation stalls undetected past STALL_DAYS.
- Founder system-admin time (excluding actual selling) < 15 min/day; manual data entry limited to voice notes.
- Nudge channel stays trusted: budget rarely binding, no muting behavior; ≥ half of nudges lead to founder action within expiry (else rules get re-graded).

## 9. Risks

- **Attribution leakage** (calls from unlisted numbers, shared devices) → orphan-event queue makes leakage visible and bounded rather than silent; accept imperfection, measure it.
- **Nudge fatigue** → discipline mechanics (budget, cooldown, expiry) are requirements, not options; monthly self-grading catches drift.
- **Voice-note discipline decay** → the one human dependency; if notes stop, AI reasons over gaps. Mitigation: 30-second friction ceiling and nudge-visible gaps ("demo held yesterday, no note").
- **Compliance misstep on SMS** → structural mitigation: no code path exists for cold outbound SMS to list contacts.
- **Scope creep toward CRM/BI** → non-goals section is the contract; UI adds a panel only when a question recurs every wave.
- **Single-vendor print dependency** → PrintApi seam; PostGrid is a one-file fallback.

## 10. Dependencies

Lob account + test environment; PostHog project with `?r=` capture live; NMC campaign line with "nevermisscall" vertical config (script variant for ad-responders, booking to founders' calendar); CSLB list in hand; NMC SMS/email sending path reusable for digests.

## 11. Milestones

Per the implementation plan: Phase 0 skeleton → 1 truth machinery → 2 contract verbs → 3 seams & jobs → 4 judgment → 5 surfaces → 6 ghost wave (~10 real pieces to founder addresses; end-to-end pass is the go/no-go for wave 1). Build sized at roughly two weeks part-time via Claude Code (Fable 5 review at phase boundaries, Opus 4.8 execution). Hard deadline: operational before wave 1 drops; the ghost wave is the immovable quality gate.

## 12. Open questions

1. ~~Lob vs. PostGrid final call~~ — **DECIDED 2026-07-11: Lob** (see docs/decisions.md; chosen on API fit at price parity after verified quotes from Stannp/Poplar; PostGrid remains the named fallback, re-quote at >5k pieces/month).
2. `hot_response` same-day delivery vs. morning digest only — start digest-only; promote if wave-1 response latency data says hours matter.
3. Partner's nudge channel (SMS vs. email) — his preference, ask him.
4. Whether affiliate-referred prospects enter this system's pipeline view from day one or only post-response — leaning day-one with `owner=partner`, confirm with him before wave 1.
