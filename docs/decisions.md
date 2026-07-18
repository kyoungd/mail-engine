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
