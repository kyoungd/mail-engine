# Interface contract — NMC close feed (main app → mail engine)

*Status: **proposed**, 2026-07-29. The contract both sides implement against so neither
waits on the other. Companions: `partner-lead-assignment.md` §8 and §11 Q10 (why the spine
needs this), `../../../docs/partnership-program.md` (the main-app program and its
"unverified dependency"), `decisions.md` (the four partner decisions of 2026-07-29).*

**Why this exists.** Both sides are blocked on the same question from opposite ends —
mail-engine asks *"how does the spine learn of a partner-driven close?"* (Q10), the main
app asks *"can `nmc_sales_attribution` count trial-to-paid per partner?"*. Neither needs
the other's answer to build. A pinned interface lets each side ship against the contract
and meet in the middle.

---

## 1. Shape: a pull feed, not a push API

**The main app exposes a read endpoint. mail-engine polls it.** Not the reverse, for four
reasons that are properties of the systems rather than preferences:

1. mail-engine has **no public inbound surface** — `web/api.py` is an operator UI bound to
   `127.0.0.1`. A push would require exposing it to the internet and inventing auth for it.
   A pull requires neither.
2. `seams/response_feed.py` **already is this contract**, and already says so: *"NMC is
   consumed through this same contract as any third party: no special access."* This
   feed is a `ResponseFeed` implementation and nothing else.
3. A feed error must **halt the nightly before recompute** — the "never judge stale state"
   guarantee (`jobs/nightly.py`). A pull propagates that error naturally; a push cannot,
   because the failure happens on the far side, hours earlier.
4. Retry is free. A missed poll is corrected by the next one; a missed push needs delivery
   guarantees, which is a whole outbox.

The main app already runs a transactional outbox (Plan 16, `nmc_event_outbox`) for
cross-DB propagation. **This contract deliberately does not use it.** The outbox exists to
guarantee delivery to something that must be told; a feed the consumer re-reads at will
needs no such guarantee, and adding one would couple mail-engine's uptime to Medusa's
dispatcher.

---

## 2. The endpoint (main app implements)

```
GET /api/nmc/closes?since=<ISO-8601>&limit=<int>
X-API-KEY: <key>
```

`X-API-KEY` matches the existing NMC service-to-service convention (PRD § Service-to-Service
Communication). Read-only; no other verb on this route.

**Response**

```json
{
  "closes": [
    {
      "id": "nmcclose_01J8...",
      "recorded_at": "2026-07-29T18:04:11.412Z",
      "occurred_at": "2026-07-29T17:58:02.000Z",
      "kind": "signup_completed",
      "phone_e164": "+18186793565",
      "partner_code": "JK-01",
      "mailer_code": null,
      "subscriber_ref": "cus_QxyZ..."
    }
  ],
  "next_since": "2026-07-29T18:04:11.412Z",
  "has_more": false
}
```

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | **Stable and immutable forever.** This is the idempotency key — see §4. |
| `recorded_at` | yes | When the main app durably recorded the close. **The watermark field** — see §5. |
| `occurred_at` | yes | When the close actually happened. Reported, never used for paging. |
| `kind` | yes | `signup_completed` \| `trial_to_paid`. See §6 — this is what unblocks the main app. |
| `phone_e164` | yes, nullable | The correlation key. E.164, normalized by the main app. Null is permitted and means "unattributable" — see §3. |
| `partner_code` | yes, nullable | The typed partner code, when the subscriber gave one. **Null is normal** and does not mean "not a close". |
| `mailer_code` | yes, nullable | The postcard `?r=` code, when the signup carried one. Present for funnel closes; null otherwise. Used only for the double-count question in §7. |
| `subscriber_ref` | yes | Opaque main-app identifier, for audit and back-reference. mail-engine stores it and never interprets it. |

**Ordering and paging.** Rows sorted by `recorded_at` ascending, then `id`. `next_since`
is the `recorded_at` of the last row returned (or the request's `since` when empty).
`has_more` tells the consumer to poll again immediately rather than wait for the next
nightly.

---

## 3. Match every close, not only partner-coded ones

`partner_code` being null is not a filter — the feed reports **all** closes.

This is the design's own instruction (§11 Q10): *"if Medusa correlation is chosen, it
should match all closes by phone, not only partner-coded ones"*, because the same
blindness hides organic signups and demo-line closes. A feed restricted to coded closes
would fix partner attribution and leave the spine still unable to see that a contact it is
mailing has already become a customer.

**Correlation is by phone, and is deterministic now.** `contacts.phone_e164` carries a
partial unique index as of the grain migration (Batch B, 2026-07-29), so
`resolution/matcher`'s phone lookup resolves to exactly one contact or none. Before that
migration this interface could not have been specified honestly — a phone matched an
arbitrary one of 1,785 duplicate rows. **Never fuzzy-match**: a null or unmatched phone
leaves the event orphaned for `resolve_orphans`, which is the designed resting place, not
a failure.

---

## 4. Idempotency is already solved — but only if `id` is stable

`service/ingestion.ingest_event` is idempotent on **`(source, external_id)`**
(`on conflict do nothing`). mail-engine stamps `source = "nmc"` and
`external_id = <close.id>`, so re-polling the same window is a no-op at any overlap.

Therefore, binding on the main app:

- **`id` must never change for a given close.** Not on re-processing, not on a Stripe
  webhook replay, not if the row is rebuilt. A regenerated id is a duplicate close in the
  spine, and nothing downstream can tell.
- **`id` must be unique across kinds.** If one subscriber produces both a
  `signup_completed` and a later `trial_to_paid`, those are two rows with two ids.
- Re-serving an already-served row is **expected and safe**. The consumer over-polls on
  purpose.

---

## 5. Watermark on `recorded_at`, never on `occurred_at`

A consumer that pages on `occurred_at` silently loses late arrivals: a close that happened
at 09:00 but was recorded at 14:00, after the consumer's watermark had already passed
09:00, is never seen again. This is the classic feed bug and it fails silently — exactly
the failure mode this codebase keeps writing down (`nudge.sent` claiming delivery, TD-2's
dead writers).

So: `recorded_at` is **monotonic and assigned by the main app at durable write time**, and
it is the only field `since` is compared against. `occurred_at` is carried for reporting
and for the spine's event timeline, never for paging.

---

## 6. `kind` is what unblocks the main app

The main app's open risk is *"nobody has confirmed `nmc_sales_attribution` can count
trial-to-paid conversions per partner."* **That question does not block this feed.**

The feed reports what the main app can observe, labelled honestly:

- `signup_completed` — a subscriber account was created. Observable today.
- `trial_to_paid` — the trial converted to a paying subscription. Emit when the main app
  can observe it; until then, simply never emitted.

mail-engine decides which kinds derive `won`; the main app decides which it can produce.
Neither waits. If `trial_to_paid` turns out to be uncountable per partner, that constrains
**bonus vesting** (a 3-month-gated commission question, `decisions.md` 2026-07-25) — it
does not constrain the spine, which needs to know a contact became a customer at all so it
stops being mailed and stops being assignable.

---

## 7. The one binding open question: double counting

A close through the coded landing funnel **already** reaches the spine as
`signup.completed` from the **PostHog** feed. The same close arriving from this feed
carries a different `source`, so `(source, external_id)` will not dedupe it. Two events,
one close.

This is not fatal to correctness — `won` is a *derived* stage, so two events still yield
one `won` — but it double-counts in readouts and in anything that accrues per close, which
includes co-op mail credit.

Three options, **decision required before the first partner close**:

1. **Consumer-side skip.** mail-engine ignores NMC-feed rows whose `mailer_code` is
   non-null, trusting PostHog for those. Simple, but wrong if PostHog is down or the
   funnel event is missed — the close then reaches the spine from neither feed.
2. **Retire PostHog for closes.** This feed becomes the single source of
   `signup.completed`; PostHog keeps the rest. Cleanest semantics, one writer per fact,
   but it makes the spine's most important inflow depend on a route that does not exist
   yet — sequence it so PostHog is retired only after this feed is proven.
3. **Count distinct contacts, not events.** Leave both inflows, and make every readout and
   accrual count contacts reaching `won` rather than `signup.completed` rows. Most robust,
   and it fixes a latent class of bug rather than this one instance — but it is a change to
   existing readout code, not to this interface.

**Recommendation: (2), sequenced — build the feed, prove it against real closes, then
retire PostHog's `signup.completed`, with (3) adopted regardless because counting distinct
contacts is correct independently of which feed exists.** Recorded as a recommendation, not
a decision: this is `partner-lead-assignment.md` §11 Q10 and belongs to the operator.

---

## 8. What each side implements

**Main app**
- The `GET /api/nmc/closes` route above, `X-API-KEY` authenticated, read-only.
- A stable, immutable `id` per close and a monotonic `recorded_at`.
- Phone normalized to E.164 before serving.
- Emit `signup_completed` now; add `trial_to_paid` when observable.

**mail-engine**
- `seams/nmc_closes.py` — an `NmcCloseFeed` implementing `ResponseFeed`, `source = "nmc"`,
  yielding `Event(type="signup.completed", external_id=<close.id>, occurred_at=…,
  payload={phone_e164, partner_code, mailer_code, subscriber_ref, kind}, contact_id=None)`.
- Registration in `jobs/nightly_cli.py::_build_feeds` behind its own env vars
  (`NMC_CLOSE_FEED_URL`, `NMC_CLOSE_FEED_KEY`), skipped-and-reported when unset, exactly
  like the Lob and PostHog feeds.
- A persisted watermark per feed. **`jobs/nightly_cli.py` currently passes a single
  `since` for all feeds** (a 30-day lookback by default) — acceptable at first, since
  over-polling is safe by §4, but a per-feed watermark is the correct end state.
- No new inbound surface, no new auth on the mail-engine side.

**Neither side**
- No shared database, no join, no foreign key across the boundary. Correlation is by
  phone in app code, per the two-database rule both documents already state.
