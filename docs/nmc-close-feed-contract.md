# Interface contract — NMC close feed (main app → mail engine)

**Revised 2026-07-29 (operator decision): the transport is a READ-ONLY connection to the
Medusa database, not an HTTP endpoint.** §1 records the decision and corrects an error in
the original draft. Everything from §3 onward — idempotency, watermark, all-closes,
`kind`, double-counting — is transport-independent and stands unchanged.

*Status: **RATIFIED** 2026-07-29 (operator), transport revised to the read-only Medusa
read. The contract both sides implement against so neither waits on the other. Companions: `partner-lead-assignment.md` §8 and §11 Q10 (why the spine
needs this), `../../../docs/partnership-program.md` (the main-app program and its
"unverified dependency"), `decisions.md` (the four partner decisions of 2026-07-29).*

**Why this exists.** Both sides are blocked on the same question from opposite ends —
mail-engine asks *"how does the spine learn of a partner-driven close?"* (Q10), the main
app asks *"can `nmc_sales_attribution` count trial-to-paid per partner?"*. Neither needs
the other's answer to build. A pinned interface lets each side ship against the contract
and meet in the middle.

---

## 1. Shape: mail-engine reads the Medusa DB read-only

**Decision (operator, 2026-07-29): mail-engine opens its own read-only connection to the
Medusa database and queries closes directly. No HTTP endpoint is built.** The accepted
cost is recorded as **TD-12**.

**Correction to this document's first draft.** The original §1 argued for an HTTP feed and
claimed a cross-database connection would breach the 🔴 two-database invariant. **That was
wrong, and the error was mine.** The PRD says the opposite in as many words: *"Code
touching both must open two connections… Cross-DB access = two connections, two queries,
correlate in app code — never a join."* Two connections **is** the sanctioned pattern; the
invariant forbids sharing one *database* and forbids *joins*, neither of which a read-only
query does. The draft's "never a shared connection" was a stricter rule I introduced and
then cited as though the PRD required it.

**What the decision buys:** the main app builds nothing. No route, no auth, no paging, no
serializer — the endpoint, its tests, and its maintenance all disappear. At one-to-three
partners that is the difference between this shipping and not.

**What it costs (TD-12, accepted):** schema coupling with no version boundary — a Medusa
migration that renames a column breaks mail-engine's nightly with no contract in between,
where an endpoint would have insulated it. Plus one more credential to hold and rotate.

**Two prerequisites, neither optional:**

1. **A read-only Postgres role on the Medusa DB must be created — it does not exist
   today.** PRD § Production connection strings lists only `medusajs_nmc_user`, the
   **owner**. Handing mail-engine that credential would give the marketing app *write*
   access to the subscriber database, which is a materially worse trade than the one being
   accepted here. `grant connect` + `grant select` on the named tables only.
2. **Mail-engine gets a third connection helper.** `db/session.py` (`OWNER_DATABASE_URL`)
   and `db/readonly.py` (`READONLY_DATABASE_URL`) both point at the mail-engine database.
   A new `db/medusa.py` reading `MEDUSA_READONLY_URL` keeps the boundary legible and keeps
   the existing helpers single-purpose. **Never** reuse either existing helper for this.

## 2. The query (mail-engine implements, over the read-only role)

Read `nmc_sales_attribution` (verified to carry `id`, `created_at`, `status`), joined in
**mail-engine's** app code to whatever the main app uses to record the typed code — see
`website/src/lib/nmc-partner-codes.ts`. `select` only; mail-engine never writes here.

The field list below is now a **column contract**: these are the values mail-engine reads,
whatever they are named on the Medusa side. The mapping (column → field) is pinned in
`seams/nmc_closes.py` and is the one place a Medusa rename must be repaired.

One row, as mail-engine sees it after mapping:

```
id            "nmcclose_01J8..." / 4711      -- whatever nmc_sales_attribution.id is
recorded_at   2026-07-29T18:04:11.412Z
occurred_at   2026-07-29T17:58:02.000Z
kind          signup_completed
phone_e164    +18186793565
partner_code  JK-01          (nullable)
mailer_code   null           (nullable)
subscriber_ref cus_QxyZ...
```

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | **Stable and immutable forever.** The idempotency key — see §4. `nmc_sales_attribution.id` satisfies this. |
| `recorded_at` | yes | The watermark — see §5. `created_at` is the candidate; **verify it is never backdated** before relying on it, since a backdated row is a permanently missed close. |
| `occurred_at` | yes | When the close actually happened. Reported, never used for paging. |
| `kind` | yes | `signup_completed` \| `trial_to_paid`. See §6 — this is what unblocks the main app. |
| `phone_e164` | yes, nullable | The correlation key. **Normalized to E.164 by mail-engine on read** (`domain/phone.to_e164`) — nothing serves the row, so the main app cannot do it. Null is permitted and means "unattributable" — see §3. |
| `partner_code` | yes, nullable | The typed partner code, when the subscriber gave one. **Null is normal** and does not mean "not a close". |
| `mailer_code` | yes, nullable | The postcard `?r=` code, when the signup carried one. Present for funnel closes; null otherwise. Used only for the double-count question in §7. |
| `subscriber_ref` | yes | Opaque main-app identifier, for audit and back-reference. mail-engine stores it and never interprets it. |

**Ordering and batching.** `where <recorded_at> > %s order by <recorded_at>, id limit %s`
— mail-engine owns the loop and keeps reading until a short page comes back. No
`next_since`/`has_more` protocol: the watermark is the last row's `recorded_at`, held by
mail-engine (§ R3's `feed_watermarks`), and the main app is not involved.

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

Therefore, binding on the main app — now as a **schema promise** rather than an API contract:

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
- `db/medusa.py` — the read-only connection helper (§1 prerequisite 2).
- `seams/nmc_closes.py` — an `NmcCloseFeed` implementing `ResponseFeed`, `source = "nmc"`,
  querying over that connection and yielding `Event(type="signup.completed", external_id=<close.id>, occurred_at=…,
  payload={phone_e164, partner_code, mailer_code, subscriber_ref, kind}, contact_id=None)`.
- Registration in `jobs/nightly_cli.py::_build_feeds` behind `MEDUSA_READONLY_URL`,
  skipped-and-reported when unset, exactly like the Lob and PostHog feeds.
- A persisted watermark per feed. **`jobs/nightly_cli.py` currently passes a single
  `since` for all feeds** (a 30-day lookback by default) — acceptable at first, since
  over-polling is safe by §4, but a per-feed watermark is the correct end state.
- No new inbound surface on either side.
- **The test suite must never hold a Medusa credential that can write.** `tests/guard.py`
  refuses to run against a non-disposable mail-engine DB; the same fail-closed thinking
  applies here — tests use a fake feed, not a live Medusa connection.

**Neither side**
- **No join across the boundary, ever, and no shared database.** Two connections, two
  queries, correlated by phone in app code — which is precisely what the PRD prescribes.
  A `join` written across these two connections is impossible in Postgres and must not be
  simulated by pulling one side into a temp table.
