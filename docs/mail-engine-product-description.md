# Mail Engine — Product Description (v2)

*Internal tooling for NeverMissCall's direct mail channel. Working name placeholder.*

## What it is

A campaign operating system that sits between the prospect database and the print API, and runs the full 3-drop direct mail lifecycle per contact — from list intake through drop execution to response attribution and wave analysis. It is an execution and measurement layer for a strategy the operator already owns; it does not set strategy, offer, or creative direction.

## Architecture in one sentence

A contact database is the spine; Lob/PostGrid executes mail out of it; PostHog (web) and NeverMissCall (phone) feed response signals back into it; AI operates on top of it as the analyst and drafter.

## Core components

**Contact spine.** The CSLB list, cleaned at intake (dedupe, NCOA address validation) and segmented by trade, license class, and geography. Every contact carries state: segment, creative variant assigned, drops sent and delivered, response events (web visit, call, booking), and current stage (in-sequence, responded, handed to sales, suppressed).

**Drop execution.** Drops are triggered through the print API (Lob or PostGrid) with variable data per piece — each card carries a unique mailer code driving the QR/URL (`?r=` parameter) and the campaign phone number. Because mail is API-driven rather than batch-scheduled, drops 2 and 3 are conditional: responders are automatically suppressed from subsequent drops; non-responders proceed, optionally with different creative.

**Response capture.** Two feeds, both pulled nightly via API and joined to contacts by mailer code:
web response from PostHog (landing page visits, funnel behavior), and phone response from NeverMissCall itself — the campaign line runs through our own product under a dedicated "nevermisscall" vertical config, so every call (answered or missed) is a logged event, and missed calls trigger the SMS-back flow that books demos directly onto our calendar. The product is its own demo at the moment of first contact.

**Analysis layer.** Raw events are retained permanently in our database; PostHog and NMC are feeds, not the system of record. Analysis is conversational: plain-language questions ("cost per response by segment in wave 2, and does drop timing correlate?") are translated by AI into queries against the database, executed, and answered as prose with numbers. No BI tool, no dashboards — the database plus a query-capable AI is the analytics layer.

## Where AI does the work

1. **Intake:** list cleanup, dedupe, and segmentation of the CSLB data.
2. **Creative variation:** copy and design variants per segment, generated cheaply for experimentation within the operator's creative direction.
3. **Wave readout:** after each wave, a plain-language learnings memo — which segments, creatives, and timings produced response, at what cost per response.
4. **Sequencing drafts:** proposed branching rules for the next drop (who gets what), drafted for approval, never executed autonomously.

## Boundaries and control

**Scope ends at handoff.** When a contact responds and books, they exit the mail sequence and are handed to the sales pipeline (CRM). Follow-up sequences, call scripts, and pipeline automation are the sales system's job, not this tool's. (Revisit after the 60-day phase if the handoff seam proves awkward.)

**Human sign-off per wave.** Nothing prints without approval. The AI drafts the wave — audience, variants, timing — and the operator releases it. At current volumes (~500 pieces per wave) the cost of a sign-off step is minutes; the cost of a bad autonomous batch is real money and a burned list segment. Automation of routine suppression logic can come later, once the rules have proven themselves over several waves.

**Information-buying posture.** The tool's success metric during the 60-day phase is learning-per-hour, not response rate. Every wave must produce a readable answer to a question we deliberately asked. The design bias throughout is toward experiment legibility: clean attribution, retained raw data, one-variable-at-a-time discipline in wave composition.

## What it explicitly is not

Not a growth-hacking system, not an autonomous marketer, not a CRM, not a replacement for judgment on offer, pricing, or creative. It is disciplined plumbing for a traditional 3-drop campaign, with AI removing the labor from list hygiene, variation, and analysis.
