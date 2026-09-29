# Interface contract — NMC close feed (main app → mail engine)

> ⚠️ **The TRANSPORT below is superseded (operator decision 2026-08-06).** The
> direct read-only Medusa connection is reversed in favour of an **HTTP endpoint
> served by the main app**, `X-API-KEY`, on B2's pattern — see `decisions.md`
> 2026-08-06 and **TD-12**, now the highest-priority item in the technical-debt
> register. Not yet scheduled; the current implementation stays live until the
> migration is taken, and this contract is amended *first* when it is.
>
> **What survives the change unaltered:** §2's field table (it becomes the
> serializer spec), §3's binding rule about tag-less closes, §4 re-serving, §5 the
> watermark, §6 kinds, §7 double-counting. Only *how the bytes arrive* changes.

**Revised 2026-07-31 (verification pass against the REAL schema — operator-approved
project restart; corrected same day by fresh-context review):** §2 is rewritten. The
first draft's column claims were never verified and were wrong
(`nmc_sales_attribution` has `attributed_at`, no `status`, no phone, no kind, no
partner_code column), and — more fundamentally — **an attribution-table feed cannot
satisfy §3's own binding rule**: a row is written only when the order carried a rep
or a `?r=` source (`nmc-order-subscription.ts:570`), so **tag-less** closes produce
NO row. Which closes carry a source is path-dependent (review correction — the first
revision got this wrong): a postcard/QR pointing at the MAIN site (`/us?r=…`) stamps
`source` and DOES write a row (the inline-checkout code comments say so verbatim);
the LANDING-page guest checkout (`getnevermisscall.com`) stamps only
`order.metadata.mailer_code` — no `source`, no row; organic no-code signups write no
row. The feed's spine is therefore the **`customer` table**, with attribution as a
LEFT-JOIN decoration (a same-DB join — legal; the cross-DB prohibition is between
the two *databases*).

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
   today** (re-verified 2026-07-31: PRD § Production connection strings still lists only
   `medusajs_nmc_user`, the **owner**; zero grant DDL exists anywhere in the repo).
   Handing mail-engine that credential would give the marketing app *write* access to
   the subscriber database, which is a materially worse trade than the one being
   accepted here. `grant connect` + `grant select` on the named tables only —
   **and the named tables are THREE** (2026-07-31, from the real query + reads in §2):
   `customer`, `nmc_sales_attribution`, `nmc_partner_code`. A grant
   worded "the close tables only" omits `customer` and silently breaks both the feed's
   spine and the status column; `nmc_sales_rep` is deliberately NOT granted — nothing
   reads it (`sold_by` maps directly to mail-engine's own `partners.sales_rep_id`). Record the credential in PRD § Production connection
   strings when minted (the mail-engine side's own `me_user_ro` +
   `0002.readonly-grants.sql` is the working precedent for the pattern).
2. **Mail-engine gets a third connection helper.** `db/session.py` (`OWNER_DATABASE_URL`)
   and `db/readonly.py` (`READONLY_DATABASE_URL`) both point at the mail-engine database.
   A new `db/medusa.py` reading `MEDUSA_READONLY_URL` keeps the boundary legible and keeps
   the existing helpers single-purpose. **Never** reuse either existing helper for this.

## 2. The query (mail-engine implements, over the read-only role) — REWRITTEN 2026-07-31 against the verified schema

**The spine is `customer`, not `nmc_sales_attribution`.** Verified reality
(`website/src/modules/nmc-sales/migrations/Migration20260602000000.ts:35-45` +
`nmc-order-subscription.ts:569`): the attribution table carries
`id BIGSERIAL, customer_id UNIQUE, sold_by, source, referral_code, signed_up_via,
order_id, attributed_at` — and a row exists **only** when the close carried a rep or
a `?r=` source. **Tag-less** closes write no row (organic self-serve, and the
landing-page guest checkout whose code rides `order.metadata` instead — see the
header note for the path-dependence; main-site `?r=` closes DO write rows). A feed
on that table alone can never satisfy §3. The `customer` row exists for every
signup, so:

```sql
SELECT c.id, c.created_at, c.email,
       c.metadata->>'business_phone'        AS raw_phone,
       c.metadata->>'nmc_subscription_status' AS subscription_status,
       a.sold_by,
       UPPER(COALESCE(a.referral_code, a.source)) AS raw_code,
       a.signed_up_via
FROM customer c
LEFT JOIN nmc_sales_attribution a ON a.customer_id = c.id
WHERE c.created_at > %s
  AND c.email NOT LIKE 'smoke-test+%%'      -- prod smoke-test convention
  AND c.email NOT LIKE 'e2e-%%'             -- e2e convention
ORDER BY c.created_at, c.id
LIMIT %s
```

(Both tables are in the Medusa DB — this join does NOT cross the two-database
boundary; the prohibition in §8 is about joining ACROSS the two databases.)

**Grant scope: THREE tables — `customer`, `nmc_sales_attribution`,
`nmc_partner_code`** (review correction: the first revision granted `nmc_sales_rep`
too, but nothing reads it — `sold_by` IS the roster id, and mail-engine maps it
directly to its own `partners.sales_rep_id`, which the operator runbook stamps for
exactly this purpose. Never grant a 🔴 credential a table without a documented
reader.)

**`raw_code` is classified by mail-engine on read — one value, three outcomes:**
match in `nmc_partner_code` (uppercased) → `partner_code`; match against
mail-engine's OWN piece codes (its `pieces` table — no grant needed) →
`mailer_code`; neither → page-default noise (`SMS_SALES` etc.), both fields null.
A close is credited to a partner when `partner_code` matches **OR** `sold_by`
matches `partners.sales_rep_id` — rep-entered closes carry `sold_by` but often no
typed code.

The field mapping, now against real sources — pinned in `seams/nmc_closes.py`, the
one place a Medusa rename must be repaired:

| Field | Source (real) | Notes |
|---|---|---|
| `id` | `customer.id` (`cus_…`) | Stable/immutable ✓ — the idempotency key (§4) |
| `recorded_at` | `customer.created_at` | The watermark (§5). Assigned at durable write, never backdated ✓. ⚠️ No index on it in the Medusa schema was verified — check before relying at scale; table is small today |
| `occurred_at` | `:= recorded_at` | Signup IS the close event; the two are the same instant for kind `signup_completed` |
| `kind` | constant `signup_completed` | Not a column. `trial_to_paid` stays never-emitted until the main app can observe it (§6; verified 2026-07-31: it cannot today — no conversion timestamp exists anywhere) |
| `phone_e164` | `customer.metadata->>'business_phone'`, normalized by mail-engine on read | ⚠️ **Late-arriving by design**: checkout collects NO phone; it first exists when the wizard saves it (possibly days after `created_at`, i.e. after the watermark has passed). See the backfill rule below |
| `partner_code` | `raw_code` classified against `nmc_partner_code` (see classification rule above) | There is no partner_code column. Null when no attribution row, or the code isn't in the registry |
| `mailer_code` | `raw_code` classified against mail-engine's own piece codes | Present for MAIN-site postcard/QR closes (`/us?r=…` → `source`). ⚠️ LANDING-page postcard closes carry the code only on `order.metadata` (no attribution row) — those reach the spine via PostHog, not this feed. See §7 |
| `sold_by` | `a.sold_by` (nullable) | The roster rep id for rep-entered closes; mail-engine maps it to `partners.sales_rep_id` for crediting (review fix — previously fetched and dropped) |
| `signed_up_via` | `a.signed_up_via` (nullable) | Path taken (`self_serve` / rep flows); stored in the event payload for audit — no branching on it (final-review fix: previously selected with no declared reader) |
| `subscription_status` | `customer.metadata->>'nmc_subscription_status'` (nullable) | Current-state scalar, stored in the payload for audit/spine context; NEVER a conversion signal (Deliverable 2) and never branched on in v1 |
| `subscriber_ref` | `customer.id` | Same as `id` — kept as a separate field so the contract shape survives if the spine ever changes |

**The phone-backfill rule (new, binding on mail-engine):** because `phone_e164` can be
null at first read and real later, the effective query bound is
**`since = min(stored_watermark, now − 45 days)`** (final-review fix 2026-07-31 —
the watermark and the trailing window need ONE combining rule): the trailing 45 days
are always re-covered (re-serving is safe by §4; the UPDATE half is the second pass
below), and a watermark older than 45 days — post-downtime — wins, so nothing is
missed. The consumer re-polls that window each nightly and, for events it previously ingested with a
null phone, updates the orphaned event's payload phone when it appears — orphan
resolution is the designed resting place (§3), and this is the designed *un*-resting
mechanism. An event whose phone never arrives simply stays orphaned.

**Ordering and batching.** `where created_at > %s order by created_at, id limit %s` —
mail-engine owns the loop and keeps reading until a short page comes back. No
`next_since`/`has_more` protocol: the watermark is the last row's `created_at`, held by
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

**Reframed 2026-07-31 by the §2 rewrite (and corrected by review):** every close now
reaches the spine from this feed (customer spine), and funnel closes ALSO arrive via
PostHog — `landing_purchase_completed` for landing-page closes (whose mailer code
this feed cannot see) and the `?r=` capture for main-site closes (whose mailer code
this feed CAN see, in `raw_code`). Note the source text this section's options rest
on already binds the direction: `partner-lead-assignment.md` §11 Q10 continues
"…deduplicating against existing `signup.completed` events from any source first
(S-10's double-count guard)". The dedupe question is unchanged in structure, sharper
in scope.

A close through the landing funnel **already** reaches the spine as
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

**Main app** *(corrected 2026-07-31 — the HTTP-route line below was stale from the
pre-revision draft; under the read-only transport the main app builds NOTHING)*
- Keep `customer.id` / `customer.created_at` stable and monotonic (they already are),
  and don't rename the §2 columns without telling the marketing side (TD-12's sharp end).
- The 🔴 operator action: mint the read-only role with the THREE-table grant (§1) and
  record it in PRD § Production connection strings.
- `trial_to_paid`: never emitted until observable. The verified cheapest path, if ever
  wanted: stamp `nmc_first_paid_at` once in `handleInvoicePaid` when the pre-patch
  status was `trialing` (a 🟡 main-app change, deliberately NOT part of this feed's v1).

**mail-engine**
- `db/medusa.py` — the read-only connection helper (§1 prerequisite 2).
- `seams/nmc_closes.py` — an `NmcCloseFeed` implementing `ResponseFeed`, `source = "nmc"`,
  querying over that connection and yielding `Event(type="signup.completed", external_id=<close.id>, occurred_at=…,
  payload={phone_e164, partner_code, mailer_code, sold_by, subscriber_ref, kind, signed_up_via, subscription_status}, contact_id=None)`.
- Registration in `jobs/nightly_cli.py::_build_feeds` behind `MEDUSA_READONLY_URL`,
  skipped-and-reported when unset, exactly like the Lob and PostHog feeds.
- A persisted watermark per feed. ⚠️ **`jobs/nightly_cli.py` currently passes a single
  `since` for all feeds with a 30-day default lookback — 30 violates §2's binding
  45-day backfill window** (under-polling loses late phones; over-polling is the safe
  direction). This feed's lookback MUST be ≥45 days from day one; a per-feed
  watermark is the correct end state; the effective bound is
  `min(stored_watermark, now − 45d)` per §2.
- **The phone-backfill update path (new build item, required by §2):**
  `ingest_event`'s `ON CONFLICT DO NOTHING` cannot update an already-ingested
  event's payload. mail-engine adds an explicit second pass: for orphaned nmc-source
  events whose stored payload phone is null, re-read the row and update the payload
  (and hand the event back to orphan resolution) when the phone has appeared.
- No new inbound surface on either side.
- **The test suite must never hold a Medusa credential that can write.** `tests/guard.py`
  refuses to run against a non-disposable mail-engine DB; the same fail-closed thinking
  applies here — tests use a fake feed, not a live Medusa connection.

**Neither side**
- **No join across the boundary, ever, and no shared database.** Two connections, two
  queries, correlated by phone in app code — which is precisely what the PRD prescribes.
  A `join` written across these two connections is impossible in Postgres and must not be
  simulated by pulling one side into a temp table.
