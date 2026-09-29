# To fix — ingest vs. contact: one row per business

*2026-07-26. Status: **direction decided by operator** ("one row per business"); design
doc not yet written — that is the next session's work. This file is the decision
record and the evidence, written so tomorrow starts with zero re-derivation.
Supersedes the interim `phone_facts` proposal (rejected in favor of fixing the grain
itself). Companions: `partner-lead-assignment.md` (rev 6 — parts of it exist only to
compensate for the wrong grain and will be deleted by this fix),
`partner-lead-assignment-implementation.md`, `technical-debt.md`, `decisions.md`.*

## The diagnosis (why this file exists)

The partner-lead-assignment design went through six revisions and four independent
reviews. Every round found real defects — and the churn was not random. Mapping all
~50 findings, most patch-begets-patch cycles traced to three structural causes:

1. **The schema's unit of record is not the unit of meaning.** A `contacts` row is a
   CSLB *license record*; every rule in the codebase (stage, suppression, owner,
   nudges) and every rule in the partner design (assignment, DNC, won) is about *the
   business behind a phone number*. The design compensated per-verb — "also check
   all twin rows sharing the phone" — and every review found the next place the
   ritual was forgotten (exclusivity → suppression scope → won-release → attribution
   tie-break → concurrency twin-locks → tombstone). A principle enforced by
   vigilance in N places wants to be a structure enforced in one.
2. **The half-event-sourced architecture forces a per-fact authority question** the
   docs answered ad hoc (owner column vs event stream, stamped vs batch expiry,
   `nudge.sent` meaning composed-not-delivered — TD-10 *is* this disease). Fix:
   an **authority map** — half a page; every fact names its source of truth, its
   writers, its projections. Adopt as a standing design-doc section.
3. **The dead-writer disease is procedural** (`owner`, `activation`, sender,
   `dnc_subscriptions`, tombstone, `dnc_registry`-clear, `partners`-create — seven
   instances, two introduced by review patches this very session). Fix: a standing
   rule — **no stored fact may be declared without naming, in the same paragraph,
   its writer, its readers, and its clear/delete path.**

Causes 2 and 3 are process rules to write into the design conventions. Cause 1 is
this file.

**Are 2 and 3 just cause 1 in disguise? No — verified by counterfactual** (asked and
answered 2026-07-26, end of session): fix the grain perfectly and every #2 instance
survives (`owner_id`-vs-events, double-stored expiry, `nudge.sent`-means-composed,
the signup double-emission), and every #3 instance survives (`activation`, the
sender seam, `partners`-create are untouched by identity or authority). Three
distinct axes: **#1 identity** (what a row denotes), **#2 authority** (which
representation of a fact is truth), **#3 lifecycle completeness** (every declared
thing has its create/write/clear/implement operations). One partial subsumption:
for *stored facts*, #3 falls out of #2 — an authority-map row with an empty writers
cell IS a dead writer, visible at a glance — but #3 is broader (a Protocol with no
implementation is a dead *callee*; `partners`-create was a missing verb), so keep
the one-sentence rule alongside the map. Their common ancestor, which is why they
co-occurred: **declaration without obligation** — the design language lets you
declare a table/fact/seam without discharging what the declaration implies. This
feature was simply the first to stress all three axes at once (it mutates ownership
over time, crosses a system boundary, and works the voice channel where the
human-behind-the-phone matters); the mail-only spine could run with all three
latent. The fixes are non-interchangeable — migration / map / rule — which is why
they stay three named things in tomorrow's design doc rather than one.

## The evidence (measured 2026-07-26 against `../ingestion-app-1/cslb-all.csv`)

- **1,785 phone numbers are shared across 3,772 contact rows** (max: 12 rows on one
  number). 84,072 CSLB rows; 83,975 with phones; FBN 18,359 rows with zero phones.
- **The worst group is one business wearing twelve brand names.** 909-599-5950 ×12:
  Andersen Commercial Plumbing LLC, DC Drains, ASAP Drain Guys, Superior Plumbing,
  Kirman Plumbing, Power Plumbing, Canyon Air Systems (C20|C36), … — all C36, all at
  706 Arrow Grand Circle, 91722. A plumbing roll-up: one back office, one phone,
  **one buyer**. The current model hallucinates 12 prospects where 1 exists.
- **Merge-key agreement is decisive about the rule.** Within dup-phone groups:
  all-rows-same-address **39.7%**; all-rows-same-business-name **3.1%**; either
  **41.2%**. Name-based merging is dead on arrival; phone+address merges under half.
  The only rule that closes the class is **same phone ⇒ same contact**.
- **The wrong grain already costs mail money.** 1,422 duplicate-address groups; a
  full-list wave wastes **~1,597 pieces ≈ $1,580** (at LOB_COST_CENTS=99) mailing
  the same shop multiple postcards. Business-grain pays for itself before any
  partner ever dials.

## The decided direction

**Split the table into what it actually is:**

- **`intake_cslb_ca` / `intake_fbn_ca`** — the current `contacts` table's true
  identity: raw source rows, immutable, all source fields (`list_key`,
  `license_class`, per-license detail), **FK → contacts.id**. Re-ingest lands here;
  contact resolution happens at this boundary. (Naming note: per-source tables, not
  "ingest_california" — FR-1 anticipates other states/sources.)
- **`contacts`** — **one row per business**, the subset of fields actually used:
  business/contact name, `phone_e164`, primary mailing address, email, segment,
  suppression columns, stage, owner. For phone-bearing rows the table becomes
  **phone-unique by construction**.

**Merge rule (recommended; ratify at design approval):**

- CSLB: **same phone ⇒ same contact**, full stop. Deterministic pick of primary
  business name and mailing address (rule TBD in the design — e.g., most-frequent
  address in the group, then lowest list_key; must be pinned, not discovered).
  The embedded judgment, stated for ratification: *differently-named brands on one
  number merge into one contact* (Andersen says commercially correct). The rare
  answering-service-shared number also merges — for voice that is definitionally
  right (you cannot dial one of them without dialing all); for mail it costs one
  postcard.
- FBN: **no phone, no safe key → one contact per filing, unchanged.**
- Trade: a business spans classes (C20|C36) — audience/trade filtering becomes
  `exists` against the intake rows, not a column test on contacts.
- Never fuzzy-match (the matcher's own rule): no name-similarity, no
  address-normalization heuristics. Phone is exact or rows stay separate.

## What it costs (chosen, not discovered)

This is a **spine migration, not a partner-feature change** — 🔴, its own design doc
and approval gate, sequenced **before** the partner phases:

- Merge 3,772 prod rows into ~1,785 survivors; repoint `pieces` and `events` FKs.
- **Relax `unique (contact_id, wave_id)`** for merged history — two brands really
  did receive two wave-1 pieces; going forward, one-piece-per-contact-per-wave is
  enforced at audience resolution.
- **One-time restatement of historical readout denominators** (fewer contacts, same
  pieces — response rates tick up honestly). Delivered with a before/after report,
  same pattern as the Phase-2 stage-migration report. S-8's reproducibility promise
  holds *from the migration forward*; the restatement is the one sanctioned break.
- `list_key` dedupe moves to the intake tables; contact-level dedupe becomes phone.
- `load_list` becomes a two-step: upsert intake row → resolve/attach contact.

## What it deletes from the partner design (the payoff)

The entire twin-row stratum of revisions 4–6 collapses back to single-row semantics
and comes **out** of `partner-lead-assignment.md` (→ revision 7, written after the
migration design):

- phone-scoped exists-gates across twin rows (S-1, S-6, S-9, S-10)
- `dnc_registry` fan-out writes and per-twin event bookkeeping
- twin-row-set locking in canonical order (the concurrency apparatus narrows to
  ordinary single-row `for update`)
- the partial-unique-index workaround (phone-uniqueness is now the table's shape)
- the attribution tie-break's *twin* problem (a shared phone matches one contact;
  the assigned-row preference logic simplifies or disappears)
- most of the tombstone apparatus (a suppression survives on the surviving business
  row; the deletion-tombstone question narrows to FR-8 hard-delete only)

`phone_facts` is **not built** — it was a workaround for this table not existing.

## Next session (in order)

1. Write the **ingest/contact migration design doc** (data model, merge rule +
   primary-pick rule, prod migration steps, readout restatement, rollback story,
   acceptance tests). Include the **authority map** section and the
   **writer-named-at-declaration** rule as standing conventions (causes 2–3 above).
2. Get operator approval (🔴) — including explicit ratification of the brand-merge
   judgment and the one-time readout restatement.
3. Rewrite `partner-lead-assignment.md` → revision 7 on the new grain (mostly
   deletions) + implementation plan update (migration renumbering: the ingest split
   becomes the new first migration; partner phases follow).
4. Then the already-queued items: Phase 0 radius script (661-vs-747 dispute), Q6
   counsel hour, Q10 decision, `decisions.md` entries at approval.

## Open questions — answered (operator, 2026-07-27)

Decided in session; the design doc writes these up as pinned rules, it does not
reopen them.

1. **Primary name/address pick rule:** most-frequent address within the phone
   group, tie-broken by lowest `list_key`; business name taken from the row that
   won the address pick. Re-runnable: same input CSV → same survivors,
   byte-for-byte.
2. **`email`/`contact_name` on disagreement:** `contact_name` winner-row-only
   (same row as the name pick). `email` coalesces — winner's value if present,
   else first non-null in group order (lowest `list_key`). Emails are too scarce
   to discard on a tie rule.
3. **Same-address-no-phone merging: NO — but address standardization YES.**
   Contact identity stays phone-only. Instead:
   - **Standardize every address at ingest** via Lob's US Address Verification
     API (USPS-canonical string, ZIP+4, delivery point). This is not the banned
     fuzzy matching — no homegrown similarity heuristics; the postal authority
     returns the canonical form and we exact-match on it ("Circle" vs "Cir"
     collapse to one string).
   - **Persist the standardized address + delivery point on the immutable intake
     row** at ingest; re-runs read the stored value, never re-call the API
     (USPS data shifts over time — the snapshot preserves S-8 reproducibility).
   - **Dedupe at audience resolution, not identity:** one piece per delivery
     point per wave. Captures the full ~$1,580/wave duplicate-address waste —
     which is an address problem, not an identity problem.
   - Why not merge contacts on address, even standardized: same phone ⇒ same
     buyer holds; same address ⇒ same buyer does not (business parks, shared
     suites — CSLB is spotty on secondary units — registered agents, UPS-store
     boxes). Over-merge loses leads; the Andersen error only wastes postcards.
   - Bonus: Lob flags undeliverable addresses at verification — trim before a
     piece is composed.
   - ⚠️ **Verify before ratification** (do not treat as fact until checked
     against Lob's current docs): verification pricing/volume terms for the
     ~84k backfill + per-ingest increments, and exact response fields
     (deliverability, delivery point) — per the verify-external-facts rule.
4. **Export for multi-trade businesses:** show all trades, pipe-delimited
   (e.g. `C20|C36`), derived from the contact's intake rows.
5. **`stage_snapshot` recompute post-merge:** recompute is mandatory; the
   before/after report gets a dedicated section flagging contacts whose
   *actionable* state changed (newly nudgeable, newly silenced) for operator
   eyeball before the migration is blessed. Frozen tests (`test_recompute.py:86`,
   `test_contacts.py:102-120`) pin v2 suppression semantics — the recompute must
   not disturb that contract.
