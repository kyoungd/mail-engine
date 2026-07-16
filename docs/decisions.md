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
