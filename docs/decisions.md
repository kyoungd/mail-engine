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
