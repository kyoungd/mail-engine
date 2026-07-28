# Decision record

## 2026-07-11 — Print/mail vendor: Lob

**Decision:** Lob is the print seam's primary vendor. Campaign 1 runs on the Developer
(free) tier; move to Startup ($260/mo) at sustained >~1,000 pieces/month (where it pays
for itself), Growth at >3,000/month (tier cap). This closes PRD open question #1.

**Chosen on API fit at price parity.** Four rounds of verified pricing (Lob help-center
rates + written/calculator Stannp quotes) showed all credible vendors within ±5% at
every volume measured — postage is the floor under everyone. With price a wash, the
durable differentiators decided:

- Native idempotency key on submission — FR-4's resumable drop is free (the ambiguous
  re-submit happens ~monthly at scale: transient HTTP failures, not just crashes).
- CASS/NCOA/**RDI** endpoints — one vendor also covers the deferred address-hygiene job
  and the residential/business segmentation flag.
- Signed webhooks, best-in-category docs, real test mode (rendered proofs), invoice
  billing (no prepaid-credit balance to babysit).
- 4×6 is First-Class-only at Lob (2–5 day delivery): keeps the 3-drop cadence and
  RESP_CHECK_DAYS=10 semantics intact.

**Verified prices (2026-07-11, 4×6 FC postage-inclusive):** Developer $0.872 / Startup
$0.612 / Growth $0.582 per piece; 6×9 FC Startup $0.673. Subscription-inclusive
effective cost at 3k/mo: $0.699 (Startup). Campaign 1 (~1,450 pieces, Developer):
~$1,264 at $0 fixed.

**Runner-up (verified):** Stannp — flat $0.73/piece 6×9 FC at 3k and 6k/mo, no
subscription, delivery webhooks, but: no idempotency key (client-managed dedupe), no
RDI/NCOA API (second vendor needed), prepaid credits, unverified webhook signing.
Quotes kept as negotiating leverage.

**Rejected:** Poplar — no idempotency key AND no mailing-search API (a crashed drop
cannot reconcile → FR-4 unresumable); creative is platform-resident (breaks FR-3's
approve-what-fires guarantee); postage inclusion unverifiable from public pricing.

**Re-evaluation trigger:** sustained >5,000 pieces/month or >15% price movement →
collect PostGrid + Lob Enterprise + Stannp quotes with real volume history. The
`PrintApi` seam keeps any switch a one-file adapter.

---

## PostHog feed mapping (decided 2026-07-12)

- `$pageview` → `page.visit`; `checkout_started` → `page.cta_click`;
  `landing_purchase_completed` → **`signup.completed`** — a landing purchase IS the
  signup. Consequence: the future NMC feed must NOT also emit `signup.completed`
  (one source of truth per fact, else signups double-count).
- Nightly `since` watermark: **fixed 7-day lookback**. Overlap is free — ingestion
  dedupes on `(source, external_id)`; external_id = PostHog event uuid.
- Client uses the **Query endpoint (HogQL)**, not the deprecated `/events` API
  (verified against posthog.com/docs 2026-07-12: events API deprecated, OFFSET
  rejected for programmatic queries → keyset pagination on (timestamp, uuid)).
- Live-verify at first real pull (no keys in .env yet): the timestamp-literal
  format PostHog returns vs. what the keyset WHERE clause parses.

---

## Postcard size: 6x9 First Class (decided 2026-07-12)

4x6 judged too small for the audience (50yo trades: big phone number, readable
type, larger QR) and too easy to lose in the mail stack. Verified Lob rates
(help.lob.com pricing-details, effective 2025-07-13, postage-inclusive):
4x6 FC Dev $0.872 / 6x9 FC Dev **$0.993** / 6x9 Std Dev $0.966. Delta = $0.121/pc
(+$60 per 500-piece wave); break-even ≈ +14% response — oversize lift usually
clears that, and it's re-testable as a wave-level size A/B if wave-1 economics
say otherwise. **Stay First Class** (Std saves 2.7c and breaks the 2-5-day
delivery predictability the 3-drop cadence + RESP_CHECK_DAYS depend on).
LOB_COST_CENTS 87 → 99. Geometry: 9.25in x 6.25in full-bleed (0.125in/edge).

---

## Creative style: typographic, no image backgrounds (decided 2026-07-13)

All postcards are text-only on solid color — no photo/image backgrounds. Operator
preference, explicitly NOT data-backed: the deep-research run (docs/research-postcard-
design.md) looked for a typographic-vs-photo-led answer and found none in primary
sources. Rationale that IS true (just not "lifts response" true): (1) text-only is
differentiated in a mailstream of glossy photo cards — reads as a notice, not an ad;
(2) no photo = no contrast tax on the big-type message, protecting the one CONFIRMED
design finding (14pt+ legibility for 50+ eyes); (3) self-contained HTML, no image-
hosting step. Reversible: if wave-1 response is soft, a photo-led card is a cheap
4th A/B variant. Until then, default = typographic. Don't re-add image backgrounds
without a fresh decision.

---

## Phone response: hand-matched, undercount accepted (decided 2026-07-15)

Wave 1's card makes the **demo line (424-407-1682) the primary CTA** and the landing URL
secondary. There is no `NmcFeed` implementing the `ResponseFeed` protocol (seams/ has
`posthog.py` and a test fake only), so **no call or text to any NMC line reaches the
spine**. Web response is captured; phone response is not.

**Decision: ship anyway. Hand-match phone responders from Twilio against the contact list
after each wave; accept the undercount.** At ~500 pieces and single-digit response (~15
responses), fifteen lookups costs less than building the feed, and it measures the
caller-ID hit rate — which is the number that should decide whether the feed is worth
building at all. Building it now would be sizing an unbuilt thing by guesswork.
FR-6 already resolves by exact phone, and CSLB is 99.9% E.164, so the matching side works;
only the transport is missing. This is PRD §9's stated posture ("accept imperfection,
measure it") executed manually instead of automatically.

**⚠️ The readout MUST account for this, because the error is directional.** The funnel is
deliberately built so the *demo* carries conversion and the URL is the afterthought — so
the channel we can see is the weaker one BY DESIGN. URL-only numbers understate response
and overstate cost-per-response, and "the card worked, we couldn't see it" looks identical
to "the card failed." **Do not retire a creative on URL-only evidence.** Hand-match first,
then read.

Revisit trigger: wave-1's hit rate. High hit rate → the feed mostly automates a working
manual step (worth building). Low hit rate (he calls from his cell, not the listed
business line) → the feed would not have saved us either, and the real fix is a
per-piece-coded response path, not a feed.

## Activation tracking has NO WRITER (found 2026-07-16 — decision OPEN)

**Finding, not a decision — recorded so it is not rediscovered by a churned customer.**

A real test sale (Lob-free drop → localhost landing page → real Stripe test checkout →
`landing_purchase_completed`) proved the responder path end to end: the contact resolved
by mailer code and derived to `won`. Then the activation board was **empty**.

**Nothing in the codebase writes the `activation` table.** The only `insert into
activation` statements anywhere are in four TEST files
(`test_queries.py:152`, `test_digest_delivery.py:22`, `test_judgment_rules.py:60`,
`test_judgment_discipline.py:37`) — each inserts the row it then asserts on. Everything
*around* the writer is built: the table (migration 0001), the reader
(`get_activation_board`), the UI (`/activation`, `/api/activation`), and both judgment
rules (`activation_stalled`, `activation_partial`).

**Consequences:** FR-4 is unimplemented; Goal #4 ("Zero activation stalls undetected past
STALL_DAYS") cannot be met; `activation_stalled` — whose own docstring calls it *"the
churn cliff, the single most valuable nudge in the system"* — can never fire; `/activation`
is permanently empty. All with **262 tests green**.

**Why the suite is blind to it:** every activation test fabricates the writer's output
before exercising the reader. The seam between "a signup happened" and "an activation row
exists" is the one thing no test crosses. Only driving a real sale crosses it.

### The trap in the obvious fix

Columns are `signed_up_at, forwarding_at, calendar_at, first_lead_at`. Only `signed_up_at`
is derivable from `signup.completed`. The other three — above all `first_lead_at`, which
*is* the definition of activated — describe what the customer does inside NeverMissCall,
and **no `NmcFeed` exists** (see the phone-response decision above: hand-matched).

So shipping only the cheap half is **worse than shipping nothing**: every signup would
open an activation row whose `first_lead_at` never arrives, and `activation_stalled` would
fire forever on every customer — the nudge channel crying wolf about the best outcomes the
business has. "Nudge channel stays trusted" is a stated success metric (PRD §8).

### Options (UNDECIDED)

1. **Hand-stamped** — auto-insert on `signup.completed`, plus a UI action to stamp
   `first_lead_at`. Consistent with the phone-response posture already chosen; at
   single-digit customers the manual step is cheaper than the feed, and it measures how
   often activation actually stalls — the number that should decide whether to automate.
2. **Build the NmcFeed** — the honest automation, but it is the same feed already deferred
   once on the grounds that its value is unknown until wave-1 data exists.
3. **Leave it** — accept that activation is untracked pre-launch, and delete or disable the
   two rules so they are not mistaken for working coverage.

**Leaning (1)**, for the same reason (1) won for phone. **Do not** ship the `signed_up_at`
insert on its own — see the trap.

Revisit trigger: the first real signup. Until then the board being empty is *correct* and
must not be read as "no stalls".

---

## Partner-assigned contacts stay in the mail cadence, flagged (decided 2026-07-25)

**Decision:** Assigning a contact to a sales partner does **not** remove it from wave
audiences. Mail and partner voice run concurrently on the same contact. Responses from
partner-owned contacts are reported separately in the wave readout (FR-13) rather than
credited to mail outright. This closes open question 1 in
`partner-lead-assignment.md`.

**Why.** The multi-touch combination (postcard + a human voice call) is the
higher-converting play and is standard direct-marketing practice; removing assigned
contacts from the cadence would forfeit that lift and shrink the wave denominator,
making response rates across waves non-comparable. Attribution honesty is recoverable
by segmenting the readout; the mail lift is not recoverable once forfeited.

**The consequence that decided the implementation shape.** `contacts.owner` is
*mutable current state* — assignments expire (S-4) and are reclaimed (S-5). If the
readout joins responses to `contacts.owner` as it stands at report time, a contact
assigned to a partner in March whose assignment expired in June has its March response
retroactively re-credited to Young. The same wave's readout would then answer
differently depending on when it is run — a silently drifting historical number, which
is exactly the failure mode the append-only event spine exists to prevent.

**Therefore: owner-at-response-time is derived from the assignment event stream**
(`contact.assigned` / `contact.assignment_expired` / `contact.reclaimed`), never read
from `contacts.owner`. This sits squarely in FR-7's grain — versioned pure functions
over full history, recomputable after definition changes — and keeps wave readouts
stable and reproducible.

**Rejected: stamp `owner` onto the response event at capture time.** Simpler to query,
but it would denormalize derived state into the canonical event taxonomy (which FR-5
keeps closed), and it would require threading owner through all three independent
capture paths — PostHog sync, the NMC feed, and Lob webhooks. Derivation touches none
of them.

**Rejected: remove assigned contacts from wave audiences.** Clean attribution by
construction, but forfeits the multi-touch lift and breaks cross-wave denominator
comparability. Attribution is fixable by reporting; lost lift is not.

**Residual risk:** the segmentation is only as good as the completeness of the
assignment event stream. Any assignment path that writes `contacts.owner` without
emitting an event silently corrupts historical readouts. `owner` must have exactly
one writer, and it must emit.

**Re-evaluation trigger:** the first wave whose readout shows partner-owned and
mail-only response rates diverging enough to change a creative decision — at that
point the segmentation is carrying real weight and deserves a validation pass.

---

## Partner mail: company channel, funded by earned co-op credit (decided 2026-07-25)

**Decision:** Sales partners do not send their own cold mail to assigned leads. Mail
fires through the mail engine — coded, approved, cost-tracked. Volume is **earned** via
co-op credit accrued from closes, never purchased. Recorded as Ground Rule 7 +
§ Co-op Mail Credit in `../../../docs/partnership-program.md`.

**Compliance is not the reason.** TCPA governs calls and texts; CAN-SPAM governs email.
B2B postal mail has essentially no consent regime, and Ground Rule 1's logic ("our
messaging reputation IS the product," per-number carrier verification) is specific to
SMS and does not transfer to paper. On legal risk alone the answer would be yes.

**Experiment contamination is the reason.** Every wave carries a hypothesis and produces
a readout grading it (FR-2, FR-13); the 60-day phase's metric is learning-per-hour.
Uncoded partner mail into the same audience makes variant A vs. variant B unreadable —
you cannot tell whether the creative won or whether a partner mailed that week. And
unlike a partner *call*, which is a different channel and can be segmented by ownership
(`partner-lead-assignment.md` S-8), **a partner postcard is indistinguishable from an
NMC postcard at the response end.** Secondary: it breaks one-piece-per-contact-per-wave
in fact, and bypasses FR-3's approve-what-fires gate, which is also the only review
Ground Rules 2–3 (no income claims, no same-day-activation claims) get on a printed —
permanent, archivable — claim surface.

**Permitted exception:** warm follow-up mail to a contact the partner has actually
spoken with. Not a cold-mail problem, and already covered by S-8's ownership
segmentation. Bounded to non-NMC-branded pieces making no barred claim.

**Funding — co-op, not MDF, not cost-share.** Cost-share (50/50) is rejected outright:
`partnership-program.md` already promises "no fees of any kind to the partner," and
charging a commission-only rep for lead gen is the canonical MLM signal the recruiting
funnel is explicitly built to pre-empt. MDF (discretionary starter allocation) is
rejected because it answers a non-question — the job is calling, and a partner with a
batch and a phone is equipped from day one; mail is an unlock, not a prerequisite.
Co-op remains: budget accrues from proven production, no cash from the partner.

**Denominated in pieces.** Standard co-op rates (1–5% of partner revenue) assume
distributor volume; 3% of a Solo close is ~$28. Rates set at 250 / 500 / 1,000 pieces
for Solo / Growth / Power, tier-weighted so partners have a reason to pitch up.

**Ledger stays manual.** Closes are in `nmc_sales_attribution` (Medusa DB), mail budget
in the mail-engine DB — the two-database separation is a 🔴 invariant, so a balance is
an app-level correlation, never a join. At 1–3 partners it is the operator entering a
number. Do not build a ledger service.

**Re-evaluation trigger:** wave-1 response rate and cost-per-response. Credit sizes are
calibrated against *gross* revenue with per-subscriber COGS unverified; if a 500-piece
drop does not plausibly yield a close, the credits shrink.

---

## New-customer bonus: 1.5× monthly, two halves, 3-month gate (decided 2026-07-25)

**Decision:** On top of 20%×12 recurring, a one-time bonus of **1.5× the customer's
monthly subscription** — $150 Solo / $420 Growth / $825 Power — paid in two equal
halves. First half vests at the customer's **2nd** completed billing month, second at
the **3rd**. Vesting evaluated at billing-cycle close, not a rolling day count. Unvested
halves forfeit on cancellation; paid halves are not clawed back. This fires lever (a) of
the 2026-07-19 compensation decision.

**Why:** 20%×12 alone read as uncompetitive against other remote-closer gigs — $237.60
of first-year earnings on a Solo close, paid out $19.80 at a time, is a weak answer to
"why this gig." The bonus roughly doubles first-year Solo earnings ($237.60 → $387.60)
and, more importantly, front-loads a visible early win, which is the documented
retention mechanic for commission-only reps.

**Why 1.5× monthly rather than a flat figure.** Scales to every tier and any future one
from a single sentence in the partner agreement, and keeps the bonus proportional to the
revenue that funds it. The originally-floated $50–100 flat bounty would have inverted
under-scaling on Power.

**Why halves, and why the gate is really three months.** The pitch says "two months" and
that is true of the first half — but the second needs a third successful billing month,
so retention exposure is three months while the offer stays simple to explain. The
original single-payment-at-2-months design was **cash-flow negative at the moment of
payout**: $198 collected, commission already owed, $150 out the door. Two $75 halves in
months 3 and 4 never go underwater. Gating on retention rather than trial-to-paid (the
2026-07-19 framing) also stops full bounty being paid on a customer who cancels in
week 2. Every half clears the $50 minimum payout on its own.

**Knock-on — the three partner costs now stack to ~half of gross revenue.** Commission +
bonus + co-op mail credit = $636 / $1,587 / $3,136 per Solo / Growth / Power close,
against $1,188 / $3,348 / $6,588 of year-1 subscription revenue — 53% / 47% / 48%. Each
component is defensible alone; nobody had looked at them together before this entry. CAC
payback ~6–7 months on Solo *before* COGS, which is respectable for SaaS, and year 2 is
near-clean since commission stops at 12 months. Co-op credit figures in
`partnership-program.md` were re-based to net-of-bonus gross.

**Re-evaluation trigger:** Solo carries the heaviest load (53%) and is the likeliest to
churn. If early churn or wave-1 economics squeeze this, **Solo's mail credit drops to
200 pieces first** — it is the only one of the three not promised to the partner up
front, so it can move without touching the offer or an agreement.

---

## Two programs only: Referral (credit) + Sales Partner (cash). "Affiliate" retired (decided 2026-07-25)

**Decision:** NeverMissCall runs exactly two partner-adjacent programs and no others.
**Referral** — existing customers naming people they know, paid in account credit, no
contract, no cash, no payout machinery (`../../../docs/referral-program.md`).
**Sales Partner** — independent contractors cold-calling B2B for commission + bonus +
co-op mail credit, under a signed agreement (`../../../docs/partnership-program.md`).
The name "affiliate" is retired, and `/us/affiliates` is removed. **Reseller is
explicitly not a category** — it implies organizations with their own sales motions, and
there is no plan for one.

**Why the old affiliate program failed:** it applied *affiliate* economics (20% × 12 in
cash) to a *referral* audience — one plumber telling another. That is expensive enough
to require paperwork (W-9, ACH, 1099, net-30 payout runs) but too small to motivate a
professional promoter. It fell between two stools, which is why it read as
uncompetitive. The three models are genuinely distinct: customer referral (credit, zero
friction), affiliate (publishers, cash, tracking links), sales partner (active selling,
contract, support). Conflating the first two was the error.

**Nothing was lost.** The registry appendix confirms **no partner code was ever issued**
under the old program — only channel tags (`sms_sales`, mailer piece codes). Zero live
referral partners, no commission obligations, no attribution history to preserve.

**The separation principle survives, re-based.** `partnership-program.md`'s "two
programs, two pages — do not merge them" guardrail was right in substance; only the
referral side was mis-designed. The doc's stated reason for separation was compliance
(the referral terms ban cold outreach). The **better** reason is that the two are
economic complements: referrals are ~3× cheaper per close ($198 foregone revenue vs.
$636 cash) and warmer, but do not scale on demand — you cannot tell customers to refer
harder. Sales Partners scale on demand but cost real money. Neither substitutes for the
other.

**Credit rather than cash is the load-bearing choice.** It removes the entire payout
apparatus for the casual path: no W-9, no ACH, no 1099, no monthly run — one Stripe
operation on a customer already in Stripe. It also costs margin rather than revenue and
retains the referrer.

**Knock-on cleanups:** the Sales Partner offer bullet claimed its cash-payout terms were
"same structure as the referral program" — no longer true, corrected. The registry's
`Program` column keeps `referral` as a valid value (now meaning credit-based); no
migration needed. The retired page leaves references in `footer/index.tsx` and
`sales-partners/page.tsx` that will dead-link until removed.

**Contact address:** `partners@nevermisscall.com` — one shared **support** mailbox for
both programs (questions, payout issues, W-9s), replacing `affiliates@`. Deliberately
not an intake path: Sales Partner applications go through the form, referrals have no
application. The bare word "partners" is a documented carve-out from naming guardrail
(1), since the mailbox names a destination rather than either program.

**Re-evaluation trigger:** a single customer producing referral volume that looks like a
business rather than a favor — at which point the honest conversation is whether they
should become a Sales Partner, not whether to raise referral rewards.

---

## Contact grain: one row per business; same phone ⇒ same contact (decided 2026-07-27)

**Decision:** the `contacts` table's grain changes from CSLB *license record* to
**business** — immutable per-source intake tables (`intake_cslb_ca`, `intake_fbn_ca`)
hold the raw rows; a slim `contacts` becomes phone-unique by construction. Merge rule:
**CSLB same phone ⇒ same contact, full stop**; FBN one contact per filing (no phone, no
safe key); never fuzzy-match. Design: `ingest-contact-migration.md` (revision 7,
approved 2026-07-27 after six independent fresh-context reviews); evidence:
`to-fix-ingest-and-contact.md`.

**Why:** 1,785 phone numbers span 3,772 contact rows (worst: one plumbing roll-up
wearing 12 brand names on 909-599-5950). Every rule in the codebase and the partner
design is about the business behind a phone; the rev-4–6 partner design compensated
per-verb ("check all twin rows") and every review found the next forgotten spot. A
principle enforced by vigilance in N places became a structure enforced in one. Merge-key
measurement was decisive: name-merge 3.1% viable, phone+address 39.7% — only phone
closes the class.

**Ratified explicitly with the approval:** (a) the **brand-merge judgment** —
differently-named brands on one number become one contact (commercially correct per the
Andersen roll-up; an answering-service-shared number also merges, definitionally right
for voice, costs one postcard for mail); (b) the **one-time readout restatement** —
merging shrinks denominators, so historical response rates shift honestly; delivered as
a before/after report; the one sanctioned break in readout reproducibility, which holds
from the migration forward; (c) relaxing `unique (contact_id, wave_id)` on pieces —
merged history genuinely holds two wave-1 pieces on one business; enforcement moves to
audience resolution + mailer-code idempotency.

**Address standardization rides along, identity does not change:** every intake row is
standardized once (Lob US Address Verification; USPS-canonical + delivery point),
snapshot persisted on the immutable row; audience resolution dedupes to one piece per
delivery point per wave and excludes undeliverable primary addresses. **Same address
never merges contacts** — business parks, shared suites, registered agents make
address⇒buyer false; over-merge loses leads, while the phone-grain error only wasted
postcards (~$1,580/wave).

**Sequencing:** this is a spine migration (🔴, own design + implementation plan,
`ingest-contact-migration-implementation.md`), executed **before** all partner phases;
partner migrations renumbered 0009/0010; `partner-lead-assignment.md` revision 7
(deleting the twin-row compensation stratum) follows completion. `phone_facts` is not
built — it was a workaround for this table not existing.

---

## Standing design-doc conventions: authority map + writer-named-at-declaration (decided 2026-07-27)

**Decision:** two conventions from the partner-design post-mortem
(`to-fix-ingest-and-contact.md` diagnosis, causes 2–3) are now **standing requirements
for every design doc**, first instantiated in `ingest-contact-migration.md` §11:

1. **Authority map** — every design doc carries a table: per fact, its source of truth,
   its writers, its projections/readers. Closes the per-fact authority ambiguity a
   half-event-sourced architecture forces (owner column vs event stream, stamped vs
   batch expiry, `nudge.sent` meaning composed-not-delivered — TD-10 is this disease).
   An empty writers cell is a dead fact, visible at a glance.
2. **Writer-named-at-declaration** — no stored fact, table, column, seam, or event may
   be declared without naming, in the same paragraph, its writer, its readers, and its
   clear/delete path. Broader than the map: a Protocol with no implementation is a dead
   callee; a lifecycle verb nobody calls is a missing verb (seven instances found in the
   partner-design churn, two introduced by review patches themselves).

**Why both, not one:** verified by counterfactual (2026-07-26) — identity, authority,
and lifecycle completeness are three distinct axes; fixing the grain perfectly leaves
every authority and lifecycle instance standing. For stored facts the map subsumes the
rule; seams and missing verbs need the rule. Common ancestor: **declaration without
obligation**. The six-review hardening of the grain design validated both — several
findings were exactly "declared without writer/reader/clear-path," caught by the
conventions the doc itself adopted.

## Partner Lead Assignment design + implementation plan APPROVED (decided 2026-07-26, recorded 2026-07-28)

**Decision:** `partner-lead-assignment.md` **revision 6** and its execution brief
`partner-lead-assignment-implementation.md` are **approved**. Approval was given by the
operator at the end of the revision-6 session and simply never written down — the
documents carried "design, not approved" / "awaiting approval" for two days while
already being decided. Recorded here so ground rule 1 ("the design document is decided
once approved") has something to point at.

**Ratified with the approval** (per the design's revision-3 note, decisions taken by
review recommendation are ratified on approval): assignment as a **loan of a batch, not
a grant of territory**; batch = 12 × weekly dial-hours, rounded to 50, floor 100, cap
500, with the floor and cap applying only to *derived* batches — an explicit founder
count bypasses both; **expiry fixed at 90 days for everyone** as the sole anti-hoarding
mechanism (the holdings ceiling was rejected, not deferred); the **per-channel
suppression model** — `dnc_registry` (external scrub result, clearable) and
`do_not_call` (human-authored, permanent, the safe harbor's entity-specific list) are
separate columns and **neither may reach contact-level `SUPPRESSED`**, which gates mail;
`assign_batch` does **no network I/O**; scrub freshness comes from `dnc_refresh` at 21
days, so a dead job drains the assignable pool rather than staling it; commission is
earned by a **typed** code, never auto-applied, so credit follows evidence of contact
rather than custody; and the Step 11 trial batch runs through `assign_batch` rather than
recreating the unrecorded-sheet problem.

**Approved ≠ start building.** Three things bound what happens next:

1. **Sequenced after the grain migration.** Revisions 4–6 spent most of their effort on
   twin rows (1,785 phones across 3,772 contact rows); `ingest-contact-migration.md`
   deletes that class outright. **Revision 7 — twin-row stratum deletion — lands after
   the migration completes**, and building revision 6 first would mean writing
   twin-handling machinery in order to delete it. Migration numbers already encode the
   order: grain `0008`, this feature `0009`/`0010`.
2. **Phase 2 keeps its own 🔴 gate.** Compliance plus the suppression invariant require
   explicit approval before code. This approval does not carry it.
3. **Phase 0 is unblocked now, and is the reason recording this matters.** It is
   entirely non-code and the long poles do not overlap with the grain build unless
   started: **SAN registration** at `telemarketing.donotcall.gov` (needs NMC's EIN
   39-3518688; 12-month term, renewal opens 30 days before expiry; no SAN, no scrub),
   the **counsel hour** (Q6 — B2B exemption, plainly-cellular CSLB numbers,
   seller-of-record on the SAN; gates John dialing, not code), the **area-code script**
   (the Chatsworth free-five is disputed by two independent re-measurements that both
   put 661 in and 747 out; the original method was never recorded, so the subscription
   list ships from a re-runnable script, not from §6's table), the **paper prongs**
   (written dialing procedure + signed acknowledgment in the partner agreement), **John's
   nudge channel** (a build dependency, not a preference — email rides existing SMTP,
   while "SMS" is new integration work because no arbitrary-send NMC SMS API exists),
   and **Q10 close-visibility**, which must be decided before the first partner close or
   a closed customer expires back into the pool and NeverMissCall cold-calls its own
   subscriber.

**Still open, and unchanged by this approval:** Q6 (counsel), Q7/Q8 (the specific
area-code set and per-partner radius, pending Phase 0's script), Q9 (partner code
discount size — a pricing decision), Q10 (close-visibility inflow).

**Doc amendments this approval triggers** (implementation plan, Phase 0): the mail-engine
PRD in five places (§5's "affiliate" second user, §12 Q4's day-one `owner=partner`
leaning, §10's non-existent NMC send path, FR-10's founder-only digest, FR-11's
every-verb-is-fronted rule vs CLI-first assignment verbs); `partnership-program.md`,
which still prescribes the dropped holdings ceiling and pre-derivation 250–500 batches
and is the document partners actually read; and a superseding entry for the 2026-07-12
`signup.completed` note, refined by S-10's consumer-side dedupe.
