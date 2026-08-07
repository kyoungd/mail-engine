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

## Sales partners are created manually; no self-serve signup (decided 2026-07-29)

**Decision:** partner records are created **by hand, by the operator, in both systems**.
There is no partner self-signup flow and none is planned. "I can create sales-partner
anywhere" — the operator's words — so neither system needs to provision the other.

**Context.** The question arose from a real asymmetry: partner identity already exists on
the **main NeverMissCall app** (`nmc_sales_rep` in the Medusa DB — `id, email, name,
status, created_at`, admin-only CRUD, its own code calling it *"the single source of truth
for who can sell"*), while `partner-lead-assignment.md` introduces a **separate `partners`
table in mail-engine** (migration `0009`: name, status, channel, channel_address, address,
radius_miles, weekly_hours). Same human, two databases, no key between them. The natural
worry is a provisioning gap — someone signs up on the site and is never created in
mail-engine.

**What manual creation settles.** That worry is retired. With no self-serve path there is
no signup event to propagate, so there is **no sync mechanism, no webhook, no outbox and
no reconciliation job** to build between the main app and mail-engine for partner
identity. The two tables stay independent by design, each owning what it is actually for:
`nmc_sales_rep` owns *who may sell and who gets paid*; mail-engine's `partners` owns *who
may be handed which contacts, within what radius, for how many hours*. Those are different
concerns and a shared table would serve neither well. The insert-path hole the
implementation plan flags for partner #2 drops from a systemic risk to an operator
checklist item.

**What manual creation does NOT settle — two things, deliberately separated.**

1. **A correlation key is still needed.** Commission attribution correlates closes in
   `nmc_sales_attribution` (Medusa) against mail-engine's spine *at app level, never as a
   join* (design §8). Manual creation does not remove that correlation; it only means a
   human sets the key instead of a machine. Without a stored key the correlation falls
   back to matching on partner **name**, which is fuzzy matching on a human-entered string
   — precisely the class of thing this codebase refuses everywhere else.

   **Recommendation (cheap now, expensive later):** carry the main app's rep identity on
   the mail-engine `partners` row — a nullable `sales_rep_id` (or `sales_rep_email`),
   stamped by the operator at creation. Migration `0009` **has not been written yet**
   (partner Phase 1, unbuilt), so this is a free column today and a migration `0011`
   after Phase 1 ships. It is an input to **revision 7**, which is already being written,
   rather than an amendment to approved revision 6.

2. **Close visibility (Q10) is untouched and still binding.** Manual partner creation does
   nothing to tell the spine that a partner closed someone. `won` derives from
   `signup.completed`, which today arrives only via the PostHog coded-landing funnel; a
   contractor who signs up with a typed partner code and **no mailer code** produces no
   inflow, so `won` never derives, the assignment expires, and **partner #2 is handed a
   paying customer to cold-call**. The design calls that the worst outcome the feature can
   produce short of a compliance claim, and marks it *"must be decided before the first
   partner close."* Options remain Medusa correlation or a founder close-stamp. If
   correlation is chosen, match **all** closes by phone rather than only partner-coded
   ones — the same blindness hides organic and demo-line closes — with the double-count
   guard against funnel closes that already emit.

**Net:** the interface between the main app and marketing is **narrower than it first
appears** — one direction only. Nothing needs to flow *main app → mail-engine* for
identity (manual creation covers it). Something still must flow *main app → mail-engine*
for **closes**, and that is Q10, unchanged and still ahead of the first partner close.

## Partners are kept informed by a periodic emailed report, not a portal (decided 2026-07-29)

**Decision:** partners receive a **simple periodic report by email**. No partner login, no
portal, no partner-facing auth — the approved design's non-goal (*"Partners do not log into
the mail engine… No partner-facing auth, ever, at this scale"*) stands unchanged.

**This needs almost no new mechanism, which is why it is the right call.** Partner Phase 3
already builds every piece:

- `partners.channel` + `channel_address` already exist in migration `0009` and already
  mean *how to reach this partner* — the house row is seeded `email,
  young@nevermisscall.com` precisely so Phase 3 has a real address to prove delivery
  against.
- Phase 3 is *"a real `Sender` implementation: recipient → channel resolved from the
  `partners` row; transports per Phase 0's answers (**email via the existing SMTP
  credentials is the cheap path**)"*, and it wires `jobs/nightly_cli.py` to pass the
  sender — which is also how **TD-10** gets fixed.
- Phase 3's loud-failure rule (an unmapped or inactive recipient fails the digest rather
  than dropping silently) applies to the report unchanged.

So the net-new work is a **report composer and a schedule**, not a delivery mechanism. The
report is a new *message type* riding Phase 3's transport, not a new channel.

**Three constraints, all learned from things already in this repo.**

1. **Do not ship the report before Phase 3.** TD-10's exact failure is content that is
   assembled, recorded as sent, and never leaves the machine — with an event named
   `nudge.sent` telling you otherwise. A partner report built on an unwired `Sender`
   reproduces that bug with a third party as the victim.
2. **The report must NOT write `nudge.sent` or stamp `next_action_at`.** Those belong to
   the judgment machinery: `nudge.sent` is `hot_response`'s "no nudge ever" predicate and
   feeds FR-10's monthly self-grading, and `next_action_at` drives the founder's own
   queue. A report that reuses `record_nudge` to get delivery would silently arm cooldowns
   and corrupt the grading. It sends without recording a nudge.
3. **The report splits along the Q10 line, so ship it in two halves — and the first half
   is HOLDINGS, not activity.** Everything about what a partner *holds* is mail-engine-side
   and available today: batch size, rows remaining, days to expiry, shortfall by cause.
   Everything about *earnings* — closes credited, commission, co-op balance — lives in
   `nmc_sales_attribution` on the Medusa side and needs the **Q10 correlation** first.

   **Do not call the first half an activity or performance report.**
   `partnership-program.md` names the reason: *"Activity is one bit. A partner who worked
   200 contacts and closed nothing looks identical to one who did nothing."* §3 keeps
   dispositions out of the spine on purpose — effort lives in the partner's own sheet, so
   the system cannot report it and must not imply it can. What this report honestly
   carries is **what you hold and when the clock runs out**, which is the thing a partner
   most needs to see coming. Ship holdings with Phase 3; add earnings when Q10 lands.

**Why not a portal.** The design's own strongest argument for a partner-facing view is
that an exported sheet cannot be recalled when a contact opts out or a batch expires
(S-6). That argument is untouched by this decision and remains the graduation path — but
it is about the **dial list**, not about the partner knowing how they are doing. An email
report answers the second without taking on 🔴 partner-facing auth, contractor PII in a
web UI, or a second system a commission-only rep has to remember to open (§8: *"asking a
commission-only rep to maintain a second system is how the data goes stale"* — a report
that arrives needs no remembering).

**Open, for revision 7:** cadence (weekly is the obvious default; the expiry clock is the
thing a partner most needs to see coming) and whether the `Sender` Protocol's
`send(founder, message)` signature generalizes its first parameter to a recipient, since
it is now addressing partners as well as founders.

## Partner report design APPROVED as written (decided 2026-07-29)

**Decision:** `partner-report-design.md` is approved — same day it was drafted, recorded
immediately (the partner-lead-assignment approval went unrecorded for two days; not
repeating that). Operator's words: *"This is fine. We don't need anything fancy at this
time."* That steer is part of the approval: the plain-text two-section report as
specified, nothing added. Ships with/after partner Phase 3, holdings first, earnings
after the close feed.

## Partner report: design + plan + close-feed contract RATIFIED (decided 2026-07-29)

**Decision:** all three documents are ratified as corrected —
`partner-report-design.md`, `partner-report-implementation.md`, and
`nmc-close-feed-contract.md`. Recorded same-day (the partner-lead-assignment approval sat
unwritten for two days and earned its own entry about that; not repeating it).

**What ratification covers.** The report is a plain weekly email per active partner
**except the house account**, on a weekly floor with event triggers collapsed into the
nightly, composed in `judgment/partner_report.py` and delivered through partner Phase 3's
injected `Sender`. Section 1 is **holdings** — one line per live batch, earliest expiry as
the headline, removals since the last report, and the re-pull prompt that turns S-6's
procedural mitigation into a data-triggered one. Section 2 is **closes only** — which
businesses, and when. Build order: R1 (columns, riding revision 7 into migration `0009`),
then RA (R2), then RB (R3 + R4).

**Ratified with the corrections, not before them.** A fresh-context review found two
blockers, and both were report lines whose data source did not exist:

- the *"your last export was generated DATE"* line — S-2 puts a timestamp in a **column of
  the emitted CSV**, which persists nothing, and the six new event types include none for
  export. Fixed by `partners.last_export_at`.
- the earnings section could not attribute a **single close** — the inflow carries
  `partner_code`, while `sales_rep_id` had been named "the earnings correlation key"
  despite appearing in no data that ever reaches mail-engine. Fixed by
  `partners.partner_code` (unique); `sales_rep_id` stays as the roster back-reference.

Both landed inside the one cheap window the plan itself had identified — *"columns are free
until 0009 ships"* — so the review cost two column names instead of a future migration.
**This is the second time in two days that a fresh-context review of a document its own
author had just declared finished found defects that would have shipped.** The lesson is
now twice-evidenced and belongs in the method, not in a postmortem.

**Two lines cut rather than deferred:** bonus vesting and co-op balance. Both are main-side
*ledger* facts, and the report will not reconstruct money it cannot see — a partner reading
"vested" and not being paid is a trust problem, not a display bug. Money questions belong
to whoever owns the money.

**Operator decisions taken during the review, both against my recommendation on the
first:**

1. **The close inflow is a read-only connection to the Medusa DB**, not an HTTP endpoint.
   My objection rested on an error — I claimed it breached the 🔴 two-database invariant,
   when the PRD says *"Code touching both must open two connections."* Two connections is
   the sanctioned pattern; sharing a database and writing joins are what stay forbidden.
   The main app now writes no code. Accepted cost is **TD-12**, with the real debt named:
   no version boundary, and no test on the main-app side that would catch a rename, because
   the breakage surfaces in a different repo from its cause.
2. **One line per live batch, earliest expiry as the headline** — latest-batch-only would
   have hidden precisely the clock the design says a partner most needs to see coming.

**Hard prerequisite, not yet met:** a `select`-only role on the Medusa database. It does not
exist — only the owner `medusajs_nmc_user` — and shipping that credential to marketing
would hand the mail engine write access to the subscriber database, which is a worse trade
than the one accepted. 🔴 credential work, tracked in
`../../../docs/active/to-do-partner-report-support.md` Deliverable 1.

**Still open, and still ahead of the first partner close:** §7 double-counting (a funnel
close already reaches the spine via PostHog under a different source, so
`(source, external_id)` will not dedupe the same close read from Medusa). Now entirely
marketing-side.

## Address verification: pay-as-you-go, verify-what-you-mail; no AV plan (decided 2026-07-30)

First waves are sub-1K by intent — the operator wants confidence before scale. At that
volume the §5 plan math is the wrong shape: Lob Developer pay-as-you-go is **$0.05/lookup
with no plan and no base fee**, so verifying a 1K-wave audience costs ~$50 against the
$920–$1,468 (TD-11) of a full-list Growth-month backfill.

**Decision: no AV plan purchase. The 102k full-list backfill is deferred indefinitely.
Verification runs pay-as-you-go over what is about to be mailed** — the fallback §5 itself
named ("scope the backfill to mailed audiences only; the schema doesn't change either
way"), promoted to the standing posture. Nothing in the schema or the §5/§6 semantics
changes: stamps are still once-per-row forever, unverified rows are still never excluded.

**Vendor stays Lob**, surveyed 2026-07-30:

- **USPS-direct closed this month**: 60 requests/hour since the Jan 2026 platform change,
  and a signed license agreement + tier fees required as of 2026-07-12. Batch-unusable.
- **Google Address Validation** (~$0.017/lookup) is cheaper per lookup, but its
  caching/retention terms conflict with §5's snapshot-forever semantics — the license,
  not just the enum, is the misfit. At current volume the delta is ~$33/wave.
- **Smarty** (reportedly ~$0.60–$4/1k) is the cheapest at scale, but a swap re-pins the
  `deliverability` enum + `delivery_point_barcode` semantics that §5/§6 readers depend on
  verbatim — a mapping layer plus a design amendment to save less than it costs today.

**Enabling work (small, unblocked):** an audience-scoped mode on `verify_addresses` —
verify exactly the contacts a wave rule resolves, instead of `--limit N` over arbitrary
unverified rows. Until it exists, a bounded pre-wave sweep cannot be targeted at the wave.

**Consequence for TD-11:** still open, no longer time-sensitive — its base-fee question
only matters if a full-list backfill ever becomes worth doing as one shot.

**Revisit trigger:** the list outgrowing per-wave verification (multi-state scale, or a
full-list dedupe/exclusion pass becoming operationally necessary). That reopens both
TD-11's checkout questions and the Smarty comparison together.

## The NMC close feed MAY emit signup.completed — S-10's consumer-side dedupe supersedes the 2026-07-12 note (recorded 2026-08-01)

The 2026-07-12 PostHog feed-mapping entry pinned *"the future NMC feed must NOT
also emit `signup.completed`"* (repeated verbatim in `seams/posthog.py`'s
docstring). The partner-lead-assignment design's S-10 refined this into a
consumer-side rule, and Phase 4 built that refinement: the Q10 close correlation
DOES ingest `signup.completed` under `source='nmc'`, guarded per contact — it
ingests only when the contact has no existing `signup.completed` from any source.

Why the guard moved to the consumer: PostHog events are ingested contact-less
(attribution happens downstream in `resolve_orphans`), so a mapping-time "has the
other source already told us?" check is unimplementable at the PostHog end. Both
events may therefore exist for one close under the reverse ordering (correlation
first, funnel replay later), **and that is correct**: `won` derivation is
idempotent, the won-termination step fires once, wave attribution prefers the
PostHog event (which alone carries the mailer-code → piece → wave linkage), and
anything that COUNTS signups deduplicates per contact.

Also stale in the 2026-07-12 entry: its "fixed 7-day lookback" — the code and the
implementation plan say 30 days.

## §7 dedupe: (2) sequenced + (3) regardless (decided 2026-08-01, the B-GATE)

The close-feed/PostHog double-count question (contract §7, design §11 Q10) is
decided per the recommendation: **(2) retire PostHog's `signup.completed` once the
close feed is proven against real closes** — one writer per fact, sequenced so the
spine's most important inflow never depends on an unproven route — **and (3)
adopted regardless: every readout and accrual counts DISTINCT CONTACTS reaching
`won`, never `signup.completed` rows.** (3) binds now on anything that counts
signups (cost-per-customer, co-op accrual, the readout); the PostHog retirement is
a follow-up gated on the feed's first proven real closes, not a build item today.
Until then both events may coexist per the S-10 refinement (2026-08-01 entry above).

## Priority shift: the sales-partner system is PRIMARY; direct mail waits (decided 2026-08-01)

The program's order of effort inverts: fulfilling support for sales partners is now
the primary product; the direct-mail campaign (wave 1, address verification's
audience-scoped mode, the ghost wave, the live Lob key, creative) PARKS. Parked mail
machinery consumes nothing (dark seams, unset keys, the AV gate shipped closed).

**mail-engine itself does not park** — the partner system's spine (contacts,
custody, DNC compliance, exports, the report) IS mail-engine; only the
mail-specific half waits.

The new critical path: the compliance chain (SAN → counsel → area-code
re-derivation → real FTC client → paper prongs) · C3 go-live (prod release, env,
nightly cron, operator-as-partner first report) · B2 deploy ·
`partnership-program.md` amendment · first partner activation via the cutover
runbook.

**Named consequence:** partners dial COLD lists until mail resumes — the designed
postcard-then-call warm-up does not exist yet. A sales-motion fact for partner
expectations, not a technical gap.

## Nationwide program, grow-per-partner DNC subscription; partner-held SANs REJECTED (decided 2026-08-01)

The sales-partner program is **nationwide with no area restriction in principle**:
any region unlocks the day a partner appears in it. The DNC subscription model is
**grow-per-partner** — run `jobs/derive_area_codes.py` on each new partner's base
ZIP, subscribe their derived set (the org's first five codes are free — five TOTAL
per organization, not per partner — then $82/code/year, FY2026, verified against
the FTC 2025-08-27 Federal Register notice), and record it via
`subscribe_area_codes`. Contacts in unsubscribed codes stay unassignable until
their code is priced in — a visible $82 decision per code, never a silent gap. The
full-registry cap ($22,626/yr) was considered and rejected at this scale:
pre-paying for geography with no partner standing in it.

**Partner-held DNC subscriptions REJECTED** (operator floated, resolved same day):
16 CFR §310.8 attaches the access fee to the SELLER — "a violation for any seller
to initiate, or cause any telemarketer to initiate … unless SUCH SELLER … has paid,"
with the mirror provision binding the telemarketer to THAT SELLER's payment. NMC is
the seller; a partner dialing under only their own SAN violates for both parties at
once. Also: it would kill recruiting (FTC registration before first dial), destroy
the §310.4(b)(3) safe harbor (NMC's procedures + the versioned dnc_checked audit
trail ARE the proof), and save ~$400/yr at 3 partners. NMC holds the one SAN, runs
the one scrub, partners receive pre-scrubbed exports — "we handle compliance" stays
a program feature. Seller-of-record mechanics on the SAN remain on the Q6 counsel
agenda.

**Nationwide consequences now on the build queue:** per-contact timezone +
calling-window enforcement on exports (the §6 CA-only waiver dies with CA-only),
state DNC registries + telemarketer registration/bonding added to the Q6 agenda,
and per-state intake sources when list acquisition starts (timing: separate
decision).

## DNC subscription policy: trial-1 / activation-2 / expand-on-shortfall (decided 2026-08-01)

Refines the same-day grow-per-partner decision into the per-partner ladder:

1. **Trial (Step 11):** subscribe ONE code — the partner's densest from
   `derive_area_codes` — free while the org's five last.
2. **Activation (Step 12 pass):** the partner's top-2 codes (≤$164/yr, often $0).
   Data basis: top-2 covered 72% of the Chatsworth radius, and capacity binds
   first anyway — one dense code (818: 4,387 contacts) exceeds a full-timer's
   ~2,000/yr.
3. **Expansion:** buy code #3+ ONLY when a refill request reports a meaningful
   `dnc_unsubscribed` shortfall — the partner demonstrably drank the subscribed
   pool dry. $82 the day the data says it buys leads, never on a calendar.

Supersedes the operator's floated "2 per year" cap: same cost discipline, but the
trigger is the shortfall signal instead of the calendar, so a productive partner
is never stranded behind an arbitrary annual limit. **Overlay-market caveat**
(watch at onboarding): where codes overlay one footprint (Dallas 214/469/972/945;
LA's 213/323, 310/424, 818/747), the script's ranked list is the tell — a #3
nearly the size of #2 is an overlay market saying buy it at activation.

## Amendment: partner-requested area codes join the expansion triggers (decided 2026-08-01, same day)

The ladder's step 3 gains a second trigger: code #3+ unlocks on EITHER a
`dnc_unsubscribed` refill shortfall (system evidence) OR an explicit partner
request (partner evidence) — operator approval gates both. The request arrives
through the human channel like a refill request (no portal, standing decision);
approval practice: run `derive_area_codes` on the partner's base first — a
requested code ranking low in their radius is usually overlay confusion, and the
script names the code that actually buys contacts. Purchase at the SAN portal →
`subscribe_area_codes add` → the nightly scrub sweeps the new code automatically
(unscrubbed contacts stay unassignable by the freshness gate — nobody jumps the
scrub). No code change required; the pipeline already behaves this way.

## SUPERSEDING: one code to start, unlimited on performance (decided 2026-08-01, third refinement same day)

Supersedes the trial-1/activation-2 ladder (above, same day): **every partner
starts with ONE area code** — their densest, from `derive_area_codes` — and gets
more **on request, when they are doing good, with NO cap for performers.** The
request is the qualifying event, exactly like the refill: one principle for leads
and geography both. "Doing good," in observables the system actually has (dials
are invisible by design): the batch worked down (the request itself), closes
credited (report §2), demo-line activity (report §3). Operator approves each
request; $82/code past the org's free five.

Retained from the ladder: the overlay caveat and **thin-#1 discretion** — the
derivation script prints code #1's size at onboarding; when it is thin (a few
hundred contacts in rural/overlay-fragmented metros), seed with 2 on day one
rather than starving a good partner in week three. Unlimited-on-performance
mirrors the dropped holdings ceiling: expiry carries anti-hoarding, the $82 is
spent only against proof.

## DNC registry lives in FILES, never a database table (decided 2026-08-03)

The scrub reads the portal's downloads as **streamed files**; the registry is
never loaded into `mailengine_*`. S-9 said "downloads the current registry
files" and was silent on where they land, and the seam's
`numbers(area_code) -> frozenset` implied holding an area code in memory —
neither was a decision. This is the decision.

**The inversion that settles it.** We never ask "what is on the registry?"; we
ask "which of MY 6,023 numbers in 818 are on it?" So the set held in memory is
**ours** — ~1 MB — and the registry file streams past it line by line and is
discarded. Peak memory is flat in the registry's size. A naive
parse-into-a-set was the only thing that made size look frightening: `818,5551234`
is 12 bytes on disk but ~120 as a Python string in a set, a tenfold expansion
that streaming never pays. Files are tens of MB; five codes stream in seconds.

**Why not a table.** The registry is an **input, not a record** — we already
persist the only part that matters, the per-contact verdict (`dnc_registry`,
`dnc_checked_at`) plus the version-stamped `contact.dnc_checked` event, which is
what answers "were we clear to call on the day we called?" Keeping the other ten
million numbers is keeping the ore after the smelting. Performance decides
nothing here (seconds of streaming vs. a monthly `COPY` — both fine for a
nightly job); what decides it is (a) **backup propagation** — a table of ten
million consumers' phone numbers is copied into every DB backup forever, a
categorically worse breach than our 82k business contacts, for zero gain — and
(b) moving parts: a table needs a migration, load job, staging table, atomic
swap, version tracking, and a bloat strategy for ~10M rows replaced monthly;
a file needs a parser.

**Layout** (the folder is gitignored, so the convention lives here):
`marketing/dnc-lists/<YYYY-MM-DD>/` — sibling to both checkouts, reached as
`../dnc-lists/`, same pattern as `ingestion-app-1/`. **The directory name IS the
registry version** stamped on every check event; ISO so it sorts and so the
31-day limit is eyeballable off the folder name. **Keep the portal's `.zip`
unopened** — the parser streams through `zipfile`, the bytes stay identical to
what the FTC served, and the CRC is a free completeness check: a truncated
plain-text list looks valid and would silently under-block, marking listed
numbers clear and putting registered consumers into a partner's sheet. Retain
13+ months. Never committed, never exported to partners (the SAN lets us *use*
the list, not redistribute it).

**What would flip this:** change lists. Applying `A`/`D` deltas needs a snapshot
to apply them to, and a table would then earn its keep. Full-list re-download is
the ratified v1, a re-scan costs seconds, and the portal serves full lists per
area code — so that day may never come.

### Addendum (2026-08-03, same day): the portal has a documented download API

Found while asking whether our sample fixtures were format-authoritative (they
are not — see below). `https://telemarketing.donotcall.gov/DownloadSvc/DownloadSvc.asmx`
is a PUBLIC SOAP discovery endpoint on the FTC's own host; the operations and
schemas below are primary-source facts, not inference:

- `Login(strCoID, strCoPwd, userType, enumCertify)` — `userType` is an enum of
  `Unknown|Representative|Downloader`, `enumCertify` of `Unknown|Agree|Disagree`.
  Our Organization ID + **Downloader** password map straight onto the first two.
- `GetURLS(fileFormat, strSessionToken, strCoID)` — `fileFormat` is `"Xml or
  Flat"`; returns an array of download URLs. **This confirms `Flat` is a real
  option** (it does NOT confirm the byte layout of a flat line).
- `GetDNCFileByUrl`, `CanGetFullFile` — the full-list path.
- `SubmitDeltaFileRequest` → `GetDeltaFileRequestStatus` → `GetDeltaFileUrl` —
  change lists are an async request/poll/fetch flow, not a plain download.
- `LoginResult.code` includes `AlreadyDownloadedToday`, `NoFullDownloadPerformed`,
  `CertificationNotAgreed`, `SessionExpired`.

Two consequences. **The download can be automated** — the operator need not
hand-drop files monthly. And `AlreadyDownloadedToday` means a nightly job must
NOT re-fetch blindly: it reuses the cached file, which is exactly the
`dnc-lists/<version>/` folder above. The folder survives as a *cache the job
fills*, not merely a drop box — and it becomes load-bearing rather than
convenient.

The WSDL adds the transport detail: `GetDNCFileByUrl` returns
`FileDownloadResponse{code, value: base64Binary}` — the file arrives base64'd
INSIDE the SOAP envelope, not as a plain HTTP download. So the flow is
Login → CanGetFullFile → GetURLS → GetDNCFileByUrl per URL → base64-decode → zip.

**Still unverified: the flat file's line layout — and secondary sources actively
CONTRADICT each other**, which is why we will not guess:

| | Claim A | Claim B |
|---|---|---|
| Full list | `8185551234` (10 digits/line) | `818,5551234` (code, comma, 7 digits) |
| Change list | comma-delimited w/ ISO timestamp | **fixed-width fields** |

`tests/fixtures/dnc/` assumed B-then-A — plausibly the worst mix of two
disagreeing sources. Pin the parser against the portal's Data Demo sample or the
first real download, never against our guess.

### Addendum 2 (2026-08-04): the API was exercised live — auth works, no files yet

Ran the real SOAP flow against `DownloadSvc.asmx` with the org's Downloader
credential. Verified facts for whoever builds the client:

- Endpoint `https://telemarketing.donotcall.gov/DownloadSvc/DownloadSvc.asmx`,
  target namespace **and** SOAPAction prefix are the same string:
  `https://telemarketing.donotcall.gov/DownloadSvc/` (SOAPAction = prefix + op).
- `Login(strCoID, strCoPwd, userType=Downloader, enumCertify=Agree)` →
  `code=LoginOK`, `value=` a 36-char GUID session token. **Certifying
  programmatically works** — no web click needed for the API path.
- `CanGetFullFile(token, coID)` → `code=InvalidRequest`.
- `GetURLS(Flat|Xml, token, coID)` → `<string>Invalid request.</string>`.

Both data calls fail identically with a FRESH token and in either file format,
so it is not token handling and not format: **the account has no area-code
subscription yet**, so there is nothing to serve. Registration alone does not
provision files — codes must be purchased/selected on the Representative side
first. Expect `GetURLS` to return real URLs once ≥1 code is subscribed.

Consequence for the build: the auth half of the client is proven and cheap; the
parser still waits on a real file, which now waits on the first area-code
purchase. The Data Demo sample (portal web UI) remains the faster path to
pinning the parser.

## The 30/90 custody clock + partner-ops CLI decisions (decided 2026-08-05)

Operator session, following the first real scrub (24,212 checked / 11,551 hits —
~48% of contractor phones on the consumer DNC; partner pool math is post-scrub
math from now on).

**The clock: 90-day custody, day-30 activity checkpoint — visibility, never
auto-reclaim.** `ASSIGNMENT_EXPIRY_DAYS = 90` stays the single expiry (deal-
registration norm; a 200-lead batch at ~10 hrs/week needs 4–8 weeks of working
time). The new element is the day-30 checkpoint: a batch older than 30 days with
NO spine-observable activity (inbound events, notes, `signup.completed`) on its
contacts surfaces in the operator digest and the partner report — the operator
decides coach / reclaim / wait. Rejected: hard auto-reclaim at day 30. The spine
observes callers and closes, never the partner's dialing effort (the S-7
principle); auto-reclaiming on invisible effort punishes a partner working a
slow segment. Crediting needs no attribution tail: the Medusa attribution row
(`sold_by`/partner code) decides at close time, independent of custody state.
Conflict rule when partner #2 exists: first credit wins, operator adjudicates —
not built until it happens.

**Entity-specific do-not-contact: confirmed already built, no new machinery.**
The operator asked for "our own do-not-call list" — that is `do_not_call` via
`suppress(contact_id, "voice", ...)`: human-authored, permanent (not in
`_CLEARABLE_CHANNELS`), tombstone-backed across re-ingest, gates assignment
ahead of the registry flag, and is the TSR §310.4(b)(1)(iii)(A) entity-specific
prong the dialing procedure already names. Workflow burden is human: partners
must report opt-outs same day (procedure §, onboarding drill).

**Daily download + scrub, cron-shaped, CLI-first.** The subscription allows one
fetch per file per day; downloading daily keeps every check ≤1-day-old version
and every dial ≤22 days (21-day recheck + 1), comfortably inside the 31-day
safe harbor. `scripts/dnc-daily.sh` chains `dnc-download.py` → `dnc_refresh
--snapshot <newest>`; manual runs stay first-class. Storage ~10 GB/year of
zips; retention pruning is a later knob, not a blocker.

**Partner-cycle visibility = `partners_cli status`, pulled FORWARD of the
rehearsal** (operator instruction 2026-08-05, superseding the 2026-08-03
"after the rehearsal" sequencing for this piece; the umbrella
`partner_onboard.py` stays queued post-rehearsal). Per partner: holdings,
live batches with day-N-of-90 and checkpoint status, last export, last report.
CLI, not web — "we already have a text based UI, so we can expand that."

**Identity: Medusa-keyed status quo made explicit.** Partners exist manually in
both systems, joined by `sales_rep_id`/`partner_code` (decided 2026-07-29,
unchanged). No provisioning sync; mail-engine keeps its own operational columns
(channel, hours, radius, report stamps).

**Area codes: partner-REQUESTED on the existing subscription ladder.** The
partner picks/requests codes; `derive_area_codes` demotes from default to
recommendation engine. Everything else holds: one code to start, operator
approves each $82 purchase, growth on demonstrated performance. Rejected:
"assign from the entire CA list" — the unit of dial-legality is the subscribed
area code (~25 CA codes ≈ $2k/yr + full-state scrub surface), and the 31-day
freshness gate structurally blocks unsubscribed codes anyway.

### Addendum (2026-08-05, same day): the console — "no TUI" amended to "no TUI framework"

The queued follow-up's "no new app, no TUI" wording (C3 ceremony doc §
Queued follow-up) is amended by operator instruction: `jobs/console.py` is a
plain-input() MENU over the existing front doors — `make console`. Still no
TUI framework, no new dependencies, zero business logic in the console (the
web window's one-verb-per-route thinness, applied to a terminal). It also
delivers the umbrella's onboarding walk ahead of the rehearsal: derive →
STRUCTURAL SAN-purchase pause → subscribe → scrub → assign → export, with the
pause pinned by test so nothing downstream can run undeclined. The separate
`partner_onboard.py` module is superseded — the walk lives in the console.

### Addendum 2 (2026-08-06): the walk consumes; the daily cycle syncs

Operator correction after driving the walk live: downloading and scrubbing DNC
files is a SEPARATE operation (the daily cycle — cron or menu 7), and the
onboarding walk had no business running it inline (it produced five "already
downloaded today" NOTEs mid-workflow). The walk is now consumption-only:
pick → pause-if-unowned → register → subscribe → assign → export. Guard rails
instead of inline sync: an owned code with zero assignable inventory stops at
the pick pointing at menu 7; a just-purchased code ends after subscribe with
the same guidance (its file is not provisioned yet anyway). Safety is
unchanged — the assign gates refuse unscrubbed contacts regardless; the stops
just say so up front. Also this session: register step gained select-or-create
(numbered roster pick), missing weekly_hours prompts once at pick, and the
console boundary translates SystemExit AND domain exceptions into printed
step results (two live crashes: unknown partner, no-hours ValidationError).

## Partner-sourced numbers: give them the lead, attribute it, release after 30 days (decided 2026-08-06)

Partners collect numbers of their own; there was nowhere to put them, and the
dialing procedure forbids calling anything off the current export. Design:
`partner-sourced-leads.md` rev 4. Three operator decisions:

**The number is usually already ours — give it to them anyway.** The spine holds
the full CA CSLB list (100,444 contacts / 81,988 with phones / six trades), so a
licensed contractor a partner meets is probably already a row. The import takes
custody of an unowned existing contact rather than merely annotating it: "he
worked for it." The genuinely new rows are what our purchased lists never
covered — locksmiths (no CSLB data), handymen, unlicensed, out-of-trade,
out-of-state.

**The marker is an ATTRIBUTION, not a status:** `contacts.sourced_by_partner_id`,
set by the import, never cleared automatically. One column, three jobs — custody
kind is derived (`sourced_by = owner` ⇒ sourced, uncounted, unexpiring), "never
reassigned to another partner" is an audience exclusion, and holdings split by
comparing the two columns. This replaced a `custody_kind` enum whose fatal flaw
(review finding) was having no reset path: a stranded 'sourced' value would have
made a later *issued* assignment never expire. Persistence is the intent, so the
bug cannot exist. Also dropped from rev 2: a referral intake table that was
excluded from every reader — the `contact.permission_recorded` event is the legal
record, the CSV file is the archive.

**Partnership ends ⇒ custody returns at once, attribution holds 30 days, then
clears** (`partners.deactivated_at` + a nightly release step). The window makes a
temporary ending reversible. **No special DNC sync is needed and the number 30 is
why:** `dnc_refresh` already sweeps every contact in a subscribed code past the
21-day recheck, house-owned included, so the quarantine (30) outlasts the recheck
cycle (21) and released contacts are always freshly scrubbed against the 31-day
wall. Exception: contacts in unsubscribed codes are never scrubbed, so they
return as dead inventory until that code is bought.

**Conflict (the number is another partner's): nothing moves automatically.** The
operator adjudicates on evidence of who has been working it, and the import report
assembles that evidence in place — holder and since-when, contact activity
(reusing `batch_checkpoint.ACTIVITY_TYPES`), and per-partner demo-line calls via
`seams/nmc_demos.py`. Needs a single-contact custody-move verb, which does not
exist today.

Parked: the territory-vs-area-code rethink (rev 1's coverage numbers were
pre-scrub and wrong — 3,964 "dialable" was really 2,227) and permission as a
DNC gate waiver (needs the seller-attachment premise blessed — **added to the Q6
counsel agenda**).

### Addendum (2026-08-06): the personal-list rule, stated by the operator

Supersedes the "record permission but act on nothing" posture in
`partner-sourced-leads.md` rev 4. **A number is on the partner's sheet if it is
in their personal list (≤90 days from `permission_at`), or if it came off the
main list and clears DNC.** Consequences:

- The personal list skips the **FTC registry** checks only (registry hit,
  unsubscribed area code, stale scrub). It never skips **our own** do_not_call
  or a suppression tombstone — the entity-specific list has no exemption in law.
- **Dedup needs no code**: `contacts` is phone-unique since the grain migration,
  so a number reachable from both sources is one row. Personal rules win while
  the window is open.
- **90 days flat, no `permission_kind`.** Oral permission is good ~3 months and
  written until revoked; 90 days is the shorter, so it is safe for both and
  spares a partner from making a legal classification in a spreadsheet cell.
- This corrects rev 4's "sourced custody never expires" — it expires at 90 days,
  after which ordinary rules resume (DNC-clear ⇒ normal lead; listed or
  out-of-code ⇒ dead inventory).
- Rests on the seller-attachment premise (permission to a partner = permission
  to NMC), **on the Q6 counsel agenda**. If counsel narrows it, the change is
  the export predicate, not the schema.

## REVERSED: partner-sourced numbers are CUT; a referral is a targeting signal, not a lead-capture path (decided 2026-08-06, same day)

Reverses the entry directly above, hours after it. The feature was built to
rev 5 (`f3ce10c`) and **fully backed out the same day** (migration `0012`,
`service/referrals.py` deleted, the export's personal-window waiver removed).
Production never received it; nothing was imported and nothing was dialed.

**Why cut.** The design bundled three separable things — *acquisition* (new
inventory), *permission* (a legal basis to call), and *custody* (90-day
exclusivity). Only permission was hard, and it did not survive scrutiny:

- What the CSV collected was **oral, relayed permission**. Both
  16 CFR § 310.4(b)(1)(iii)(B)(1) and 47 CFR § 64.1200(c)(2)(ii) require a
  **signed writing** to exempt a registry-listed number, so a referral supplies
  no basis at all. Rev 5's oral-vs-written reasoning (the "~3 months vs. until
  revoked" line) confused permission with the **EBR-from-inquiry** window and is
  withdrawn.
- The decisive argument was **safe-harbor contagion**: § 310.4(b)(3) forgives an
  *isolated error despite procedures*. A category-wide carve-out is not an
  isolated error, so waiving the scrub for referrals risked the posture for the
  **whole program**, including the scrubbed CSLB calls. Now counsel **Q8(e)**.

**What replaces it — no code, and it was already possible.** A referral is a
*targeting* request that takes no shortcut through the DNC gates:

1. The partner sends a **name and town**, never a number.
2. The contractor is almost certainly already ours — CSLB is the whole state
   (84,072 rows), so a licensed referral is a row we hold, not new data.
3. Operator looks them up (`search_contacts`, web `/contacts`) and assigns by id
   (`assignment_cli assign --ids-file`). **The explicit-id path runs the identical
   `_gate`** — a hand-picked referral is refused exactly like any other candidate.
4. Clears ⇒ next sheet, dialed normally with the referrer named in the opener.
   `dnc_registry` ⇒ **not callable** (~48% of contractors, measured 11,551/24,212);
   in-person or the demo line is the only route. `dnc_unsubscribed` ⇒ the
   area-code purchase decision. `dnc_stale` ⇒ tonight's cycle handles it.

**The real value of a referral is territory evidence, not the contact.** A
partner who keeps being introduced to people in an unsubscribed code is telling
us where their social density is — which is already an approved expansion
trigger ("partner-requested area codes join the expansion triggers", 2026-08-01).
At the measured listing rate a mid-tier code (619, 951, 310 ≈ 2,100–2,300 core
contractors) yields ~1,100 dialable for $82 — about 7¢ each, worked warm.

**Known gap, accepted:** `move_contact` was deleted with the feature, so when a
referral hits `already_assigned` (another partner holds it) there is no verb to
adjudicate — the answer today is "leave it." At two partners over 100,444
contacts the collision odds do not justify the code; it is in git history at
`f3ce10c` if it is ever wanted.

**Partner-facing consequence:** `nvermisscall/docs/partner-dialing-procedure.md`
gains **rule 2** ("Referrals: get the name, not the number"), which also sets the
~50% expectation before a partner discovers it, and invites the area-code request
explicitly. If revived, the shape to build is the *inverse* of rev 5: scrub
first, then 90 days of custody on the survivors, unsubscribed codes never
reaching a sheet.

## REVERSED: the close inflow becomes an HTTP endpoint, not a direct Medusa read (decided 2026-08-06)

**Decision:** the Q10 close feed's transport moves from a read-only Postgres
connection against the Medusa database to an **HTTP endpoint served by the main
app**, `X-API-KEY`, on B2's pattern. This reverses the operator decision of
2026-07-29 (§ *Partner report: design + plan + close-feed contract RATIFIED*,
item 1). **TD-12 is elevated to the highest-priority item in the technical-debt
register.** Not scheduled — the operator takes it when there is time; the current
direct-DB implementation stays in place and working until then.

**The operator's grounds:** direct database access to the main app's data is an
exception to how every other seam in the system works, and the fact that this
particular case is well isolated does not make the pattern acceptable.

**Why this is not the same argument re-run.** The objection raised at the original
review was withdrawn as mistaken — it claimed a 🔴 two-database invariant breach,
when two connections is the *sanctioned* pattern. The decision stood on its own
merit. Three things are new since:

1. **The architecture says so explicitly.** Root `CLAUDE.md` anti-pattern #1 is
   *"Cross-schema direct DB access → use service APIs"*; § Service Communication
   is *"HTTP APIs with `X-API-KEY`. No cross-schema direct DB access."* Every other
   cross-system seam obeys it.
2. **The benefit that carried 2026-07-29 was given up three days later.** That call
   turned on *"the main app now writes no code."* On 2026-08-01 the main app wrote
   B2 — `GET /api/partner-demo-calls/summary`, 792 tests green — serving the
   demo-line half of the *same partner report*. The endpoint cost is now measured,
   not hypothetical, and it was small. Closes over SQL + demo stats over HTTP is an
   inconsistency inside one feature.
3. **The transport is what makes the feed untestable** (found 2026-08-06 while
   auditing what the suite fakes). Fixtures for a database owned by another app
   require a *writable* Medusa credential — the exact accident class `tests/guard.py`
   is fail-closed against, with a truncate-the-subscriber-table failure mode one
   `.env` typo away. Over HTTP the client tests like `NmcDemosClient` and
   `PostHogFeed` already do: injected transport, offline, no credential.

**Not a security finding.** `medusa_nmc_ro` is genuinely `select`-only on exactly
three tables (verified: `create table` → *permission denied for schema public*).
The objection is coupling and consistency.

**Shape of the migration.** `CloseFeed` is a Protocol, so `jobs/close_correlation.py`,
the `Close` dataclass, the 45-day watermark rule, the double-count guard and every
consumer test are untouched. NMC side: one additive Medusa route, no migration,
`nmc-close-feed-contract.md` §2's column table is already the serializer spec.
mail-engine side: `NmcCloseFeed` becomes an HTTP client shaped like
`seams/nmc_demos.py`; `db/medusa.py`, `MEDUSA_READONLY_URL` and the guard's Medusa
clause fall away. Two things relocate and should be decided rather than drifted
into — `raw_code` classification against `nmc_partner_code` moves server-side, and
paging becomes the endpoint's job (carrying with it the keyset-boundary question in
`NmcCloseFeed.closes()`, where the cursor advances on `created_at` alone while the
sort is `(created_at, id)`).

**Sequence:** amend `nmc-close-feed-contract.md` → build the route against the agreed
shape → swap the client. The endpoint should not be reverse-engineered from
`_CLOSES_SQL`.

**Consequence for A0's work:** `medusa_nmc_ro` becomes unnecessary once the inflow is
an endpoint. Recorded so the discard is deliberate rather than a surprise.

## Testing philosophy gets a canonical home; the release gate exists; rigor follows risk (decided 2026-08-07)

**Context.** A best-practices review found the philosophy scattered: `test-plan.md`
was read as the philosophy document but is a partially-executed build spec predating
the partner pivot (its `World` harness was never built); no document defined which
suites must be green before a prod release (`make e2e` had drifted un-run); and the
strictest machinery (mutation testing) covered the pure layers while the red-tier
compliance predicates had only per-gate tests.

**Decided:**

1. **`docs/coding/testing.md` is the canonical philosophy document** — tiers, authority,
   release gate, risk rule, owed list. `test-plan.md` carries a status banner and
   stays as backlog for the mail funnel.
2. **The release gate:** before any prod release, same day — `make test` green,
   `make e2e` green, `STRICT=1 make integration` green, pending migrations read
   with the prod plan stated. Procedural because there is no CI; whether CI should
   exist is an open operator question recorded in testing.md.
3. **Rigor follows risk.** First installment: the standing export-compliance
   invariant (`tests/acceptance/test_export_compliance_invariant.py`) —
   the violating set re-derived with independent SQL, intersected with the actual
   export CSV over an adversarial pool including post-assignment flips. Verified by
   manual mutant: deleting `dnc_registry = false` from export's WHERE turns both
   tests red. Owed next: mutmut over `service/assignment.py`, fake-fidelity
   contract tests, TZ=UTC pinning (testing.md § Owed).
4. **`mailengine_test` is the sanctioned scratch DB** (guard already allowlisted
   it; from `template template0`). Running DB suites against it via env override
   preserves the canonical dev ingest — the invariant tests ran there and
   `mailengine_dev` kept its 100,444 untouched.

## SR-6 backups exist; test suites move to mailengine_test; releases get tags (decided 2026-08-07)

The best-practices review of `docs/coding/` found six violations; the operator
approved fixing them in order. What changed:

1. **Backups (SR-6, was implemented nowhere):** `scripts/backup.sh` — nightly
   custom-format `pg_dump` of `mailengine_prod`, tmp-file + `pg_restore --list`
   verification before rename, 14-day rotation, always targets prod regardless
   of checkout. First run taken 2026-08-07 (16M); **restore tested** into a
   template0 scratch DB — five table counts identical to prod — then dropped.
   Cron entry at 02:10 (operator installs; the session's crontab write was
   permission-blocked). **Still open: an OFFSITE destination** — the local
   `~/db-backups/` satisfies "nightly + tested", not "offsite"; picking a
   destination is an operator decision.
2. **`make test` / `make e2e` now run on `mailengine_test`** (auto-created from
   template0 by `scripts/ensure-test-db.py`), so the canonical dev ingest
   survives every run — the re-ingest ritual dies. Full suite verified: 520
   green in 29s with `mailengine_dev` untouched at 100,444. Bare pytest runs
   still follow `.env`.
3. **Release tagging:** the release gate ends with `git tag prod-YYYY-MM-DD`.
4. **Suite-growth rule amended:** grows by default; retirement is a deliberate,
   recorded act (the absolutist "only grows" was already contradicted by the
   `138ee8b` suite deletions).
5. **Arrangement rule for new DB tests:** through service verbs unless the raw
   write IS the adversarial point; legacy SQL-seed is grandfathered, not
   precedent.
6. **Review-standard duplication managed:** `docs/coding/` copies are
   canonical; `.claude/commands/` copies are deployment copies re-synced by
   whoever edits (cross-repo symlinks would break other checkouts).

**Found during verification: Lob test-env asset rendering is broken today.**
`make e2e`'s mail-funnel journey is legitimately red — today's postcard
(psc_77c40e71914fb2bd, status `processed`) has NO assets (PDF + both thumbnails
404 after 15+ min) while a 2026-08-02 postcard's PDF serves fine. Vendor-side;
the frozen test is correct and unchanged. Re-run `make e2e` before relying on
the release gate. CI remains the open question in `docs/coding/testing.md`.

## CI exists: the offline tier runs on every push (decided 2026-08-07)

`.github/workflows/ci.yml` — ubuntu runner, Postgres 15 service container,
roles + `mailengine_test` created before migrations (migration 0002 grants to a
pre-existing `me_user_ro`; the swap-guard tests need `me_user` CREATEDB), `uv
sync`, `ruff check`, `uv run pytest` (e2e + integration deselected by addopts).
Scope is deliberately offline-only: no vendor secrets live in CI, so `make e2e`
and `make integration` remain operator-run and the release gate is unchanged —
CI green alone does not clear it.

Two facts the workflow encodes, found by running the suite under the exact CI
environment (all other env blanked; 520 green in 31s):

- `web/api.py` builds Lob clients with hard `os.environ[...]` reads on routes
  the suite exercises (`/drops/run`, the approval proof screen) — CI sets seven
  dummy `LOB_*` vars; offline tests never place a call, and the guard rejects
  `live_` keys.
- `DROP_PASSWORD` must be present (the web tests read it).

pyright stays local-only (`make lint`) — its node-binary download is the flaky
part CI doesn't need. First real run happens on the next push to
`github.com/kyoungd/mail-engine`.

## Direct marketing is VERSION 1.1; the Lob path leaves the gates (decided 2026-08-07)

Sharpens the 2026-08-01 "mail parks" decision with a version label: direct
marketing — waves, drops, Lob, the mail-funnel e2e — is v1.1 scope, not
current work. Consequences applied now:

- **`make e2e` runs the partner journey only** (the live product; it fakes its
  three seams and never touches Lob — green in ~1.5s). The mail funnel moves
  to **`make e2e-mail`**, PARKED: it re-enters `make e2e` and the release gate
  when mail un-parks, and no wave ships without it.
- **The Lob test-env asset outage found 2026-08-07 stops being an owed item.**
  The vendor-side 404s (recorded in the entry above) matter at v1.1, not now;
  the "re-run e2e when Lob recovers" chase is closed as out-of-scope.
- Unchanged by this entry: everything the 2026-08-01 parking already covered
  (live Lob key dark, AV gate closed, ghost wave deferred, TD-9 rotation
  advised), and the "no red tests" rule — the parked journey is out of the
  default run, not sitting red in it.
