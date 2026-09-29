# Ingest / contact migration — one row per business

*2026-07-27. Status: **APPROVED (🔴 operator approval, 2026-07-27, at revision
7 after six independent fresh-context reviews).** This is the design
doc `to-fix-ingest-and-contact.md` § Next session calls for. Direction ("one row
per business") and the five open questions were decided by the operator
(2026-07-26 / 2026-07-27); this doc turns those decisions into a buildable spec.
It does not reopen them. Sequenced **before** all partner-lead-assignment phases;
`partner-lead-assignment.md` revision 7 is written after this is approved.*

*Approval ratifies, explicitly: (a) the brand-merge judgment — differently-named
brands on one phone number become one contact; (b) the one-time readout-denominator
restatement; (c) the schema changes in §2 including relaxing
`unique (contact_id, wave_id)`.*

*Revision 2 (2026-07-27): all 12 findings from an independent fresh-context
review applied — std-address inherit got a named writer (`is_primary` +
`verify_addresses` second phase), multi-trade got a real mechanism (`trades`
array), intake regained `do_not_mail`, dedupe pinned to the primary row's
delivery point, preflight gained the wave-quiesce assertion, transaction scope
corrected, FBN-phone rule pinned, plus the minors.*

*Revision 3 (2026-07-27): second fresh-context review, 10 findings applied —
artifact split pinned (additive DDL in `0008`, order-dependent constraint swap
inside the script's transaction), intake becomes resolve-then-insert
(NOT-NULL `contact_id` preserved; identity rule is per-source, so FBN never
phone-groups), `deliverability` gained its reader (undeliverable exclusion at
audience resolution — operator-decided), operator address edits gained a real
verb (`update_contact_address` — operator-decided), plus the minors.*

*Revision 4 (2026-07-27): third fresh-context review, 11 findings applied —
next-action merge rule pinned (earliest-wins, notes carried, reported), pick
tie-break pinned to one selection (lowest `list_key` over max-frequency-tuple
rows), undeliverable exclusion ordered before dedupe, seed retirement
re-specified as `is_seed=false` (FK-safe), preflight cross-checks `list_key`
prefix vs `source`, equivalence claim scoped, FBN primary marking stated,
plus the nits. Review series: 12 → 10 → 11 findings; gating 5 → 5 → 1.*

*Revision 5 (2026-07-27): fourth fresh-context review (1 blocker, 2 major, 6
minor/nit) applied — the pieces-constraint drop moved BEFORE the repoint
(step 4; the old order violated its own §2.3 premise and rolled back on every
`--execute`), frozen-test criterion restated (assertions unmodified; fixture
helpers may follow the schema), ingest-time source registry pinned
(unknown source → fail loud), `retire_seed` verb named, vendor-failure
semantics pinned for `verify_addresses`, intake's verification stamp renamed
`std_verified_at` (vs contacts' `addr_validated_at`), email-coalesce scoped to
the whole group, suppression map row split by fact.*

*Revision 6 (2026-07-27): fifth fresh-context review (2 major, 3 minor, 2 nit)
applied — `retire_seed` now suppresses in the same write (clearing `is_seed`
alone made the founder address rule-mailable), the preflight's source-fact
gap closed (dry run measures and reports the prod source distribution;
mis-source remedy named: `--fix-source`), seeds exempted from the prefix
cross-check explicitly, `verify_addresses` got a named runner (nightly),
determinism test pinned to two-fresh-DBs, §9 gates split by producer, writer
lists completed. Both majors were defects in revision-4/5 additions, not in
the core design.*

*Revision 7 (2026-07-27): sixth review's verdict was "fix finding 1, patch 2
and 3, and approve" — applied: inherit pinned to deliverable-with-components
rows only (a component-less verdict leaves the raw address in place, never
clobbered, never guard-locked), authority map gained `retire_seed` + a seed
row, code-cutover ordering pinned (stop-the-world: `0008` → `--execute` → new
code only, nothing in between), plus the nits (`is_primary` partial unique
index declared, dry-run = run-and-rollback, exact frozen-test anchors).*

---

## 1. What this is (one paragraph)

A `contacts` row today is a CSLB *license record*; every rule in the system is
about *the business behind a phone number* (evidence and diagnosis:
`to-fix-ingest-and-contact.md`). This migration splits the table into what it
actually is: immutable per-source **intake tables** holding raw list rows, and a
slim business-grain **`contacts`** table that is **phone-unique by construction**.
Prod merges 3,772 rows into ~1,785 survivors. As part of the same design, every
address is **standardized at ingest** (postal-authority canonical form via the
print vendor), and wave audience resolution dedupes to **one piece per delivery
point per wave** — capturing the ~$1,580/wave duplicate-address waste without
letting address into contact identity.

## 2. Data model

### 2.1 New: per-source intake tables

One table per intake adapter (FR-1 anticipates more states/sources; each new
adapter brings its table). Both v1 tables share the canonical-CSV core
(`intake/fbn_ca.py CANONICAL_FIELDS`, which gains a **`trades`** column in this
change — pipe-joined in the CSV, ALL NMC trades matching the row's license
classes, emitted by the adapter so the spine never learns vendor columns);
a future source may add columns without touching the spine.

```sql
create table intake_cslb_ca (
  id             uuid primary key default gen_random_uuid(),
  list_key       text not null unique,          -- 'cslb-<license>'
  contact_id     uuid not null references contacts(id),
  business_name  text,
  contact_name   text,
  trade          text,                          -- primary trade (adapter first-match; feeds segment)
  trades         text[] not null default '{}', -- ALL matching NMC trades for the row's classes
  license_class  text,                          -- 'C36' / 'C20|C36'
  phone_e164     text,                          -- normalized at load
  email          text,
  addr_line1     text,
  addr_line2     text,
  addr_city      text,
  addr_state     text,
  addr_zip       text,
  segment        text,
  do_not_mail    boolean not null default false, -- canonical-CSV flag, preserved raw
  is_primary     boolean not null default false, -- the winner row (§3): exactly one true per contact
  -- address standardization (written ONLY by the verify_addresses job, §5)
  std_addr_line1 text,
  std_addr_line2 text,
  std_addr_city  text,
  std_addr_state text,
  std_addr_zip   text,                          -- ZIP+4
  delivery_point text,                          -- stable per-mailbox identifier
  deliverability text,                          -- vendor verdict, stored verbatim; read by §6's undeliverable exclusion
  std_verified_at timestamptz,                  -- named apart from contacts.addr_validated_at on purpose (§5)
  ingested_at    timestamptz not null default now()
);
create index intake_cslb_ca_contact_idx on intake_cslb_ca (contact_id);
create unique index intake_cslb_ca_primary_key on intake_cslb_ca (contact_id)
  where is_primary;  -- DB-enforces §3's exactly-one-primary-per-contact
                     -- (inherit + dedupe both key on it; corruption would misroute mail)
create index intake_cslb_ca_phone_idx   on intake_cslb_ca (phone_e164);
create index intake_cslb_ca_dp_idx      on intake_cslb_ca (delivery_point);

create table intake_fbn_ca ( -- same shape; list_key 'fbn-ca-<filing>'; phone_e164 always null in practice
  ...identical columns...
);
```

**Immutability:** source columns are written once — by `load_list`, or by the
§7 migration backfill for pre-existing rows — and never updated
(`on conflict (list_key) do nothing`). The only post-insert writes are
the `std_*`/`delivery_point`/`deliverability`/`std_verified_at` columns
(writer: `verify_addresses` job, §5), `is_primary` (writer: contact resolution
at creation / the prod migration, once), and `contact_id` (writer: the prod
migration's repoint, once; thereafter set at insert and never changed).

### 2.2 Changed: `contacts` becomes business-grain

Kept columns: `id`, `business_name`, `contact_name`, `phone_e164`, `email`,
`addr_line1..addr_zip` (the **picked, standardized-when-available** mailing
address), `addr_validated_at`, `segment`, `source`, `stage_snapshot`,
`stage_computed_at`, `next_action_at`, `next_action_note`, `do_not_mail`,
`do_not_text`, `owner`, `is_seed`, `created_at`, `updated_at`.

Dropped / moved:

- **`list_key`** → intake tables. Seeds (the one non-list user of `list_key`,
  `ensure_seed_contacts` upserts on it) get a dedicated nullable
  **`seed_key text unique`** column (`seed-<slug>`); the seed upsert conflicts on
  that. Seeds get no intake rows. Clear path: the **`retire_seed(contact_id)`**
  verb (ships with this gate; `ensure_seed_contacts` only ever writes
  `is_seed = true`, so without the verb the clear path has no writer) sets
  `is_seed = false` **and `do_not_mail = true` in the same write** — clearing
  the flag alone would drop the contact out of the audience rule's always-on
  `is_seed = false` exclusion and make the founder's address rule-mailable
  (it has no intake rows, so delivery-point dedupe can't catch it either).
  Retired means mailed by no path. The operator also removes the
  `config/seeds.json` entry so the upsert doesn't revive it. Row deletion is
  only possible for a seed that never rode a wave — a mailed seed's
  `pieces`/`events` FKs block it, by design (history is kept).
- **`trade`, `license_class`** → intake tables, plus the derived
  **`trades text[]`** (all NMC trades matching the row's license classes,
  adapter-emitted; a C20|C36 row carries `{hvac,plumber}` while single-valued
  `trade` stays the adapter's first-match and keeps feeding segment
  derivation). Trade filtering becomes `exists` against intake rows' `trades`
  (§6): a business spanning classes is one contact with two answers to "what
  trades?".

New constraint — the point of the whole migration:

```sql
create unique index contacts_phone_unique on contacts (phone_e164)
  where phone_e164 is not null;
```

### 2.3 Changed: `pieces` loses `unique (contact_id, wave_id)`

Two merged brands really did each receive a wave-1 piece; after repoint those
are two pieces on one (contact, wave). The constraint is **dropped**, replaced
by a plain index. Its two former jobs move:

- **Drop-resume idempotency** moves to `mailer_code` (already `unique`, already
  deterministic per (wave, contact) — `execution._mailer_code`).
  `execute_wave`'s insert changes to `on conflict (mailer_code) do nothing`,
  and its per-piece follow-up lookup (today
  `where contact_id = … and wave_id = …` + `fetchone()`) re-keys on
  `mailer_code` too — on merged history that pair is no longer unique and an
  unordered `fetchone()` would pick an arbitrary piece.
- **One-piece-per-contact-per-wave** going forward is enforced at audience
  resolution: `resolve_audience` returns each contact at most once (it already
  does — one row per contact), and the new delivery-point dedupe (§6) further
  drops same-mailbox duplicates *across* contacts.

### 2.4 New: `contact_merge_map`

Permanent audit of the one-time merge. Writer: the prod migration, once.
Readers: forensics, the restatement report. Never read by live logic.

```sql
create table contact_merge_map (
  old_contact_id uuid primary key,
  new_contact_id uuid not null,
  merged_at      timestamptz not null default now()
);
```

## 3. Merge rule and primary-pick rule (pinned — operator-decided)

- **CSLB: same `phone_e164` ⇒ same contact.** No name similarity, no address
  heuristics, ever. Phone is exact or rows stay separate. Rows with no phone:
  one contact per row.
- **FBN: one contact per filing** (no phone, no safe key). Unchanged. Pinned
  for the day an FBN row carries a phone: the phone stays on the intake row
  only — the contact is created with `phone_e164` null. Phone never enters FBN
  identity, so no collision with the unique index and no cross-filing merge.
- **Primary pick, within a phone group — one selection, fully pinned:**
  compute each row's `(addr_line1, addr_city, addr_state, addr_zip)` tuple
  frequency within the group; the candidate set is every row bearing a tuple
  of **maximum** frequency (all tied tuples' rows together); the **winner row**
  is the lowest `list_key` in that set. One rule resolves both the tuple tie
  and the row-within-tuple choice. (`addr_line2` is deliberately outside the
  tuple: suite-only variants count as one address for frequency; the winner
  row's own `addr_line2` rides along into the mailing address.) `business_name`, `contact_name`, `segment`, `source`, and the mailing
  address come from the winner row. **`email` coalesces**: winner's if present,
  else first non-null by ascending `list_key` over the **whole phone group** —
  not just the max-frequency candidate set (emails are too scarce to discard).
- **Pick timing:** the pick runs over a group **once, when the contact is
  created** — at migration time over the full group, and at `load_list` time
  over the group *within the file being loaded* (§4). A later intake row whose
  phone matches an existing contact **attaches without re-picking**: contact
  fields stay stable across ingests. (Re-pick is a deliberate non-feature; if a
  better address ever matters, that's an operator edit.)
- Determinism gate: same input CSV → same contacts — ids aside,
  field-for-field — on every re-run (acceptance test 1).

## 4. `load_list` becomes resolve-then-insert (per-file batch)

Current: one INSERT per CSV row into `contacts`. New — one transaction per
file, resolution computed **in memory before any intake insert**, which is
what keeps `contact_id` NOT NULL and set-at-insert (§2.1):

1. **Parse + validate** — dedupe on `list_key` against DB and file (unchanged
   semantics, now per-intake-table); normalize `phone_e164`; apply the
   targetability rule (trade-or-segment) to the canonical row. An invalid row
   gets **no intake row** (counted `invalid` in the report — the intake table
   holds the accepted list; the source CSV remains the byte-level archive).
2. **Contact resolution, in memory, by the source's identity rule** — the
   rule is a property of the adapter, not a universal: **CSLB = phone**
   (group the file's accepted rows by `phone_e164`; a group whose phone
   matches an existing contact attaches; otherwise apply the pick rule, create
   one contact, mark the winner row primary; no-phone rows each create their
   own contact, their single row primary). **FBN = per-filing** (§3: every
   row creates its own contact with `phone_e164` null on the contact, and is
   marked `is_primary` — the exactly-one-per-contact invariant holds on every
   load path; no phone grouping — a phone-bearing FBN row never attaches by
   phone).
3. **Insert intake rows**, each carrying its resolved `contact_id` and
   `is_primary`. `do_not_mail=true` on any row suppresses its contact —
   **including on attach**: a later file's `do_not_mail` row OR-merges the
   flag onto the existing contact (suppression is absorbing; this flag is the
   one contact write an attach performs — all other contact fields stay
   untouched per §3's no-re-pick rule).

Per-file batching (not row-at-a-time) means resolution semantics cannot depend
on row order within a file. Scope of the equivalence claim: a fresh-DB ingest
of **one file** applies exactly the pick the migration applies to the same
rows (true of the actual prod history — one CSLB file). A phone group *split
across files* picks over the first file's rows only, later rows attaching
without re-pick (§3) — a known, accepted asymmetry, not a bug: pick-at-creation
stability is the chosen rule.

**Source routing is a pinned registry, not a free string.** `load_list` gains
a `SOURCE_REGISTRY`: known source value → (intake table, identity rule) —
v1: `cslb`/`cslb-ca` → (`intake_cslb_ca`, phone), `fbn-ca-*` → (`intake_fbn_ca`,
per-filing). An unrecognized source raises `ValidationError` before any row is
read — a new adapter registers its source when it lands, so a typo or a stale
UI default can never route rows into the wrong table silently. `source` on the
contact = the `load_list` call's source parameter as carried by the winner row's
load (intake tables themselves carry no source column — the table IS the
source; prod's legacy rows carry the old default `cslb`, which the registry and
the §7 preflight globs both cover).

## 5. Address standardization at ingest (decided 2026-07-27)

- **Seam:** a new `AddressVerifier` Protocol in `seams/` (Lob US Address
  Verification implementation + a Fake). Per the standing dependency rule,
  `seams` is imported only by `jobs` and `service/execution`
  (`direct-mail-ai-code-layout.md`) — `load_list` cannot call the verifier
  (the reason NCOA/CASS was never in it), so verification is a **job**:
  `verify_addresses` sweeps intake
  rows where `std_verified_at is null`, calls the seam, stamps
  `std_*`/`delivery_point`/`deliverability`/`std_verified_at`. **Runner,
  named: the nightly job** — the sweep is a no-op when nothing is unverified —
  plus a manual invocation for the one-time backfill (and optionally right
  after a large ingest). Verification may therefore lag an ingest by up to a
  day, which is safe: an unverified row is never excluded (§6), merely not yet
  deduplicable. (Naming: the intake stamp is
  `std_verified_at`, deliberately not a near-twin of contacts'
  `addr_validated_at` — the two guard different things and must never be
  confused in the inherit logic.)
- **Per-row vendor-failure semantics, pinned:** a vendor *verdict* — including
  "undeliverable" or "no delivery point" — is a result: stamp
  `std_verified_at`, store the verdict verbatim in `deliverability`, never
  re-call. A vendor *error* (timeout, 5xx, rate limit) stamps nothing: the row
  stays `std_verified_at is null` and the **next job run** retries it — no
  per-call retry loop inside a run, no permanent consumption of the "once" by
  a transient failure. A row that errors forever is visible as
  ever-unverified, and unverified rows are never excluded (§6).
- **Snapshot semantics:** the vendor is called **once per intake row**; re-runs
  read the stored result and never re-call (USPS data shifts; the snapshot is
  what keeps resolution reproducible). This is not the banned fuzzy matching —
  the postal authority returns the canonical form, we exact-match on it.
- **The inherit step has a named writer.** Contacts are created with the raw
  picked address (verification hasn't run yet at pick time). After stamping
  intake rows, `verify_addresses` runs a **second phase**: for every contact
  whose primary (`is_primary`) intake row is verified and whose
  `addr_validated_at` is still null, copy the primary row's `std_*` address
  onto `contacts.addr_*` and stamp `addr_validated_at`. **"Verified" here
  means deliverable-with-components:** the inherit runs only over rows whose
  verdict is deliverable AND whose `std_*` components are present. Any other
  verified outcome — undeliverable, no delivery point, missing components —
  leaves the contact's raw picked address untouched and `addr_validated_at`
  null: the raw address is the better fact when standardization failed, and
  the null guard must only ever lock in a real standardized address or a
  human edit, never a clobber. Idempotent — the null
  guard makes re-runs no-ops. Operator edits go through
  `update_contact_address` (next bullet), which stamps `addr_validated_at`, so
  the job never overwrites a human correction — enforced by code, not
  convention. Pieces then mail the standardized address with no change to
  `execute_wave`'s recipient read.
- **Operator address edits get a real verb** (decided 2026-07-27):
  `update_contact_address(contact_id, addr…)` — a new service verb, fronted on
  the contact page per FR-11 — is the one sanctioned operator write of
  `contacts.addr_*`. It stamps `addr_validated_at`; that stamp is what makes
  the inherit guard safe. Raw SQL edits of contact addresses are out of
  contract.
- **Identity is untouched:** same address ≠ same buyer (business parks, shared
  suites, registered agents). Address never merges contacts — it only dedupes
  mail (§6).
- **Vendor facts — VERIFIED 2026-07-27** (Phase 0 of the implementation plan;
  sources: lob.com pricing page, Lob SDK `DeliverabilityAnalysis` docs, Lob
  DPV/AV articles):
  - **Verdict enum (`deliverability`):** `deliverable`,
    `deliverable_missing_unit`, `deliverable_incorrect_unit`,
    `deliverable_unnecessary_unit`, `undeliverable`. **Pin for §6:** only
    `undeliverable` excludes; the three `deliverable_*_unit` variants are
    deliverable-family — mailable (CSLB data is spotty on units, §3's
    rationale). Store the enum verbatim in `deliverability`.
  - **Delivery-point key:** the response carries `delivery_point_barcode`
    (11-digit USPS delivery point) plus a `deliverability_analysis` block
    (`dpv_confirmation` `Y`/`S`/`D`/`N`/`''`, `dpv_cmra`, `dpv_vacant`,
    `dpv_active`, footnotes). **Pin:** `delivery_point` column stores
    `delivery_point_barcode`; empty/absent barcode = the "no delivery point"
    case (§5 inherit skips, §6 doesn't dedupe, not excluded).
  - **Pricing (US verifications, per lob.com pricing page 2026-07-27):**
    Developer $0.05/lookup (pay-as-you-go); Startup $25/mo incl. 1,000 then
    $0.025; Growth $450/mo incl. 50,000 then $0.009. **Backfill math:** ~102k
    on one Growth month ≈ $450 + 52k × $0.009 ≈ **$920 one-time**, then drop
    the plan (per-ingest increments fit Developer/Startup). Roughly half of
    one wave's duplicate-address waste (~$1,580) — the economics clear.
    Residual to confirm in the dashboard at purchase (plan names/rates can
    drift; AV plans are separate from the print plan, which stays Developer
    per decisions.md 2026-07-11): the exact current tier prices and that
    overage billing works as listed. If terms moved materially, fallback:
    scope the backfill to mailed audiences only; the schema doesn't change
    either way.

## 6. Audience resolution and reader changes

- **Ordering, pinned: undeliverable exclusion runs BEFORE delivery-point
  dedupe.** Snapshot semantics allow two primary rows verified at different
  times to share a delivery point with different verdicts; exclusion-first
  means an undeliverable contact can never win the dedupe and silently drop a
  deliverable duplicate — deliverable mail is never lost to an undeliverable
  twin.
- **Signature, pinned (operator-decided 2026-07-29):** `resolve_audience` returns a
  `ResolvedAudience(ids, excluded_undeliverable, deduped_delivery_point)`; all three
  callers — `preview_audience`, `approve_wave`, `execute_wave` — read `.ids`, and only
  preview reads the counts. **Rejected: a second `resolve_audience_with_counts` for
  preview.** Two resolution paths would reintroduce exactly the preview/execution
  divergence that unifying on this function fixed (`14a58ae`), and that this section's
  own guarantee — "preview and execution share `resolve_audience`, so the approval screen
  shows exactly what fires" — depends on. Recorded here because ground rule 5 makes the
  design the signature authority: without it the next executor re-escalates the question.
- **`resolve_audience` gains delivery-point dedupe:** after the rule resolves
  and the undeliverable exclusion applies, at most one contact per delivery
  point per wave. A contact's delivery point
  is its **primary intake row's** `delivery_point` — the address actually
  mailed; non-primary rows' addresses never dedupe anything. Keeper is
  deterministic: phone-bearing contact first, then lowest `id`. A contact
  whose primary row is unverified or has no delivery point doesn't dedupe (no
  homegrown normalization fallback). Seeds are exempt (founder samples, FR-4;
  they also have no intake rows). Because preview and execution share
  `resolve_audience`, the approval screen shows exactly what fires;
  `AudiencePreview` reports the dropped count (no silent caps).
- **Undeliverable primary addresses are excluded** (decided 2026-07-27): a
  contact whose primary row's `deliverability` verdict is undeliverable (the
  vendor values are pinned in §5's verified vendor facts, 2026-07-27) is dropped at
  audience resolution — the decision record's "trim before a piece is
  composed", realized. The exclusion count is reported in `AudiencePreview`
  alongside the dedupe count (no silent caps). This is `deliverability`'s
  reader; unverified rows are not excluded (no verdict yet ≠ undeliverable),
  and a **no-delivery-point verdict is not excluded either** — such a contact
  stays mailable at its raw picked address (which §5's inherit never
  overwrote); only an explicit undeliverable verdict excludes.
- **`trade` filter** in `_audience_where` becomes
  `exists (select 1 from intake_cslb_ca i where i.contact_id = c.id and i.trades && %s)`
  (unioned per intake table) — against the `trades` array, not single-valued
  `trade`, so a C20|C36 business matches both `hvac` and `plumber` audiences.
  The **`source` filter stays a contacts-column test** (`c.source`, the winner
  row's source): source is one value per business, and keeping the filter
  there is what gives the retained `contacts.source` column its reader.
  `segment`, `city`, `zip_prefix`, `stage` stay contact-column tests too.
- **`search_contacts`** searches contacts plus a lateral over intake rows for
  trade/`list_key` hits; the summary shows trades pipe-delimited.
- **Exports / UI for multi-trade businesses** (decided): show **all** trades,
  pipe-delimited (`C20|C36` / `hvac|plumber`) — the sorted distinct union over
  the contact's intake rows (`license_class` for classes, `trades` for trades).
- **`contact_by_phone`** (`resolution/matcher` lookups): with phone-unique
  contacts the bare `fetchone()` is no longer arbitrary — the S-8 twin
  ambiguity dissolves structurally. (S-8's owner-at-time derivation is partner
  scope and unaffected.)

## 7. Prod migration plan

Two artifacts with a **pinned split**. `0008.intake-split.sql` carries the
*additive* DDL only — create `intake_cslb_ca` / `intake_fbn_ca` /
`contact_merge_map`, add `contacts.seed_key`, add the plain
`pieces (contact_id, wave_id)` index — idempotent per the
`test_migrations_idempotent` convention, applied **before** the script runs.
`jobs/migrate_grain.py` (with `--help`; dry-run default, which **runs steps
1–6 in the transaction, computes the full report, then rolls back** — the
same code path `--execute` commits, not a parallel simulation; `--execute` to
commit) owns everything order-dependent: the data steps AND the constraint swap, all
inside its transaction (Postgres DDL is transactional). The swap cannot live
in `0008`, and it is **split around the data steps** because its pieces point
in opposite directions: the `pieces` unique-constraint **drop must precede the
repoint** (step 4 — §2.3's own premise, two wave-1 pieces landing on one
(contact, wave), would violate the live constraint and roll back every
`--execute`), while the phone-unique index **cannot exist before the merge**
(1,785 duplicated phones) and `list_key` cannot be dropped before the backfill
reads it (step 6). Steps 1–6 run in **one transaction**; 7–9 follow it:

1. **Preflight, fail-loud.** First, the dry run **measures and reports the
   full `(source, list_key-prefix)` distribution of prod** as the report's
   opening section — the preflight's outcome hinges on this fact and no
   document records it (loads *should* have used `cslb` and `fbn-ca-2026`,
   but should is not a measurement). Then: every **non-seed** row's
   `contacts.source` must map to an intake table (`cslb*` → `intake_cslb_ca`,
   `fbn*` → `intake_fbn_ca`), **cross-checked against the `list_key` prefix**
   (`cslb-` / `fbn-ca-`); seeds (`is_seed`) are **exempt from the
   cross-check** — their `seed-` keys ride with `source`'s column default. A
   non-seed row whose prefix disagrees with its source (the intake UI defaults
   `source='cslb'`, so a mis-sourced FBN upload is a real class) → halt. The
   **named remedy** for a genuine mis-source: the script's
   `--fix-source <list_key-prefix>=<correct-source>` mode — scripted, logged,
   operator-invoked after reading the distribution report; never raw SQL
   (§5's out-of-contract rule), never silent routing on the prefix. Any other
   source → halt. Any
   `activation` rows whose contacts would merge → halt (expected: zero rows,
   TD-2). **No wave in `approved` or `executing`** — a drop resumed across the merge would
   mint new mailer codes for survivor contacts (codes hash contact ids) and
   double-mail merged businesses with the constraint gone; halt and let the
   operator finish or cancel the wave first.
2. **Backfill intake tables** from today's `contacts` rows (each current row IS
   an intake row): copy source fields verbatim (including `do_not_mail`);
   derive `trades` from the stored `license_class` via the adapter's
   class→trade map; `contact_id` = the old contact id. Seeds get `seed_key` =
   old `list_key`, no intake row.
3. **Compute merge groups** by `phone_e164` — **over CSLB-sourced rows only**
   (identity is per-source, §3; FBN never phone-groups even if a phone-bearing
   row ever appears); apply the pick rule (§3); the
   survivor contact is the winner row's old contact (so its id, events, pieces
   need no self-repoint). Mark each group's winner row `is_primary` (ungrouped
   rows: their own row). Record every loser → survivor pair in
   `contact_merge_map`.
4. **Drop `pieces` unique `(contact_id, wave_id)`** (in-script DDL — must
   precede the repoint, see the artifact split above; the plain index from
   `0008` remains). Then **repoint** losers' `intake_*.contact_id`,
   `pieces.contact_id`, `events.contact_id` to the survivor. OR-merge `do_not_mail`/`do_not_text`
   onto the survivor (suppression is absorbing — a suppressed loser suppresses
   the merged business). **Next-action merge (founder-authored state must
   survive — the same contract `test_human_set_next_action_survives_recompute`
   pins for recompute):** among the group's non-null `next_action_at`, the
   survivor gets the **earliest** date; its note = that date's note, with any
   other members' notes appended (`" | merged: …"`). Every merged next-action
   is listed in the §8 report. `owner` is uniformly `'young'` today — assert,
   don't assume.
5. **Apply survivor field updates** (email coalesce; nothing else changes on
   the winner row by construction). **Delete** loser rows.
6. **Post-merge DDL (in-script, see the artifact split above):** create the
   partial unique index on `contacts.phone_e164` (possible only now — the
   merge just eliminated the duplicates); drop
   `list_key`/`trade`/`license_class` from `contacts` (`seed_key` was added by
   `0008`, before step 2 wrote it; the pieces-constraint drop already ran in
   step 4).
7. **After commit: `recompute_state()`** over all contacts — the standard verb,
   which owns its own transaction (that is why it sits outside the
   migration's). Merged businesses pool their events; stages re-derive from
   the pooled stream. Idempotent: a failure here means stale snapshots until
   the re-run, never a partial merge.
8. **Before/after report** (§8) — generated by the script, both halves from
   the same run.
9. **Then, as ordinary jobs (not part of the migration):** the
   `verify_addresses` backfill over all intake rows, followed by its inherit
   phase (§5) — contacts pick up standardized addresses as snapshots land.

Expected prod deltas: list-sourced contacts 102,431 → ~100,444 (3,772 merged
into ~1,785; seed contacts sit outside these figures). Provenance: these
figures were measured against the canonical source CSV
(`to-fix-ingest-and-contact.md`, 2026-07-26), not the prod DB — the dry-run
report is the prod-measured truth and the gate. Pieces and events counts
**unchanged** (repointed, never deleted).

**Cutover ordering, pinned (stop-the-world):** everything ships in one
checkout; the run order is pull the release → apply `0008` → `migrate_grain
--execute` → only then use any verb. Old code must never run after the
migration (it inserts `contacts.list_key`, which step 6 drops — it crashes);
new code must never run before it (phone-attach against the pre-merge table
would attach to an arbitrary one of 1,785 duplicated-phone contacts). The
preflight's no-active-waves halt plus the single-operator reality make the
freeze practical: no ingests, no wave verbs between `0008` and `--execute`.

Code changes shipping in the same gate: `load_list` resolve-then-insert,
`execute_wave` re-keyed on `mailer_code` (both the insert conflict and the
per-piece lookup), `_audience_where` trade-exists over `trades`,
delivery-point dedupe + undeliverable exclusion, `search_contacts`,
`ensure_seed_contacts` on `seed_key`, the `update_contact_address` and
`retire_seed` verbs + routes, the `SOURCE_REGISTRY` in `load_list`, adapters
emit the `trades` canonical column, `AddressVerifier` seam +
`verify_addresses` job (stamp + inherit phases, pinned failure semantics).

## 8. Readout restatement (one-time, sanctioned)

Merging shrinks denominators (fewer contacts, same pieces) — historical
response rates generally tick up; a wave where two *responding* brands merged
can tick down, and the report shows actuals either way. Delivered as a
before/after report:

- the measured `(source, list_key-prefix)` distribution (§7 step 1's input
  fact — the report opens with it);
- per wave: audience count, response count, response rate, cost-per-response —
  before and after;
- the merge itself: groups, sizes, worst offenders (the Andersen 12), fields
  chosen per survivor;
- **actionable-state changes** (decided): every contact whose *actionable*
  state changed under pooled events — newly nudgeable, newly silenced, stage
  moved — listed for operator eyeball **before** the migration is blessed (the
  dry run produces the full report; `--execute` is run only after it's read);
- **merged next-actions** (§7 step 4): every loser next-action folded into a
  survivor — old date/note, surviving date/note — so no founder-authored
  follow-up disappears unseen.

S-8's reproducibility promise holds *from the migration forward*; this
restatement is the one sanctioned break, and `contact_merge_map` plus immutable
intake rows keep the old world reconstructible.

## 9. Rollback story

- Steps 1–6 run **inside one transaction**: any halt (preflight, assertion,
  FK error) rolls back to the untouched state. There is no partial merge. The
  post-commit recompute (step 7) is the standard idempotent verb — a failure
  there means stale snapshots until re-run, never an inconsistent merge.
- Before `--execute` against prod: `pg_dump` of the prod DB (the checked
  restore path). A post-commit regret is a restore, not an un-merge script —
  un-merging after new events have landed on merged contacts is not
  reconstructible, which is why the dry-run + report + dump ordering is the
  gate.
- Post-commit verification, split by producer: **script-emitted** (part of the
  report, prod-DB facts) — zero dangling FKs, pieces/events counts unchanged,
  survivor count matches dry-run; **repo gate** (run by the developer against
  the codebase, not by the script) — frozen suites + full offline suite green.

## 10. Acceptance tests

The 🟡 artifacts for the code changes; the migration itself is 🔴 and gated on
the dry-run report + this doc's approval.

1. **Merge determinism** — loading the same canonical CSV into **two
   independent fresh DBs** yields identical contacts (ids aside): same
   survivors, same picked names/addresses/emails. (Not load-twice-into-one-DB
   — `list_key` dedupe makes that comparison trivially pass without
   exercising the pick rule.)
2. **Resolve-then-insert intake** — a file with N rows sharing one phone →
   N intake rows, 1 contact; most-frequent address wins; tie → lowest
   `list_key`; email coalesces over the whole group; an untargetable row gets
   no intake row and is counted `invalid`; an unrecognized `source` raises
   `ValidationError` before any row is read. Re-ingest: 0 new rows, 0 new
   contacts.
3. **Attach without re-pick** — a second file adds a row matching an existing
   contact's phone → attaches; contact fields unchanged.
4. **Phone uniqueness** — inserting a second phone-bearing contact with a
   taken phone fails; null phones don't collide; seeds unaffected.
5. **Trade via exists** — a C20|C36 intake row carries
   `trades = {hvac,plumber}`; the business matches both `trade:["hvac"]` and
   `trade:["plumber"]` audiences, once each; export shows `hvac|plumber`.
6. **Delivery-point dedupe** — two contacts whose *primary* rows share one
   verified delivery point, one wave → one piece to the deterministic keeper;
   preview count equals executed count and reports the drop; a contact whose
   primary row is unverified doesn't dedupe; a *non-primary* row sharing the
   delivery point dedupes nothing; seeds exempt. A contact whose primary row
   is undeliverable is excluded and the exclusion count reported; an
   unverified row is not excluded. **Order:** an undeliverable contact sharing
   a delivery point with a deliverable one → the deliverable contact is
   mailed (exclusion before dedupe; the undeliverable twin never wins the
   keeper pick).
7. **Address inherit** — after `verify_addresses`, a contact whose primary row
   verified **deliverable-with-components** carries the `std_*` address and
   `addr_validated_at`; a no-delivery-point or undeliverable verdict leaves
   the raw address and a null `addr_validated_at` (never clobbered, never
   guard-locked); a re-run is a
   no-op; an address edited via `update_contact_address` (which stamps
   `addr_validated_at`) is never overwritten. Failure semantics: a vendor
   *verdict* stamps `std_verified_at` and is never re-called; a vendor *error*
   leaves it null and the next run retries.
8. **Resume idempotency on mailer_code** — a killed drop re-runs clean with
   the `(contact_id, wave_id)` constraint gone; no duplicate pieces, no
   duplicate `piece.submitted`; the per-piece lookup resolves by `mailer_code`
   even on merged history where (contact, wave) is ambiguous.
9. **Migration on a prod copy** — dry-run report matches hand-computed
   expectations on a fixture (known groups incl. an Andersen-shaped 12-pack, a
   tuple-tie group pinning the §3 candidate-set rule, and a group with
   next-actions on two members → earliest date wins, notes merged, report
   lists it); post-migration: counts, FK integrity, OR-merged suppression,
   `is_primary` exactly-one-per-contact, pooled-stage recompute,
   actionable-changes + merged-next-actions sections present. Preflight halts
   on an `approved`/`executing` wave AND on a `list_key`-prefix/source
   mismatch.
10. **Seed retirement** — `retire_seed` clears `is_seed` and sets
    `do_not_mail` atomically; a retired seed appears in no audience under any
    rule (including a rule-less full-list wave) and rides no wave's seed
    append; `ensure_seed_contacts` without the config entry does not revive
    it.
11. **Frozen tests: assertions untouched** — the frozen tests' fixture
    *helpers* insert `trade`/`list_key` into `contacts` and must follow the
    schema (mechanical setup edits, nothing more); the tests' **assertions and
    scenario semantics** — `tests/acceptance/test_recompute.py:86` (v2
    suppression assertion), `tests/acceptance/test_contacts.py:102-120`
    (suppress verb), `test_human_set_next_action_survives_recompute`
    (`test_recompute.py:89`) — change by **zero characters**. That is the actual guard: the contract stays
    pinned; only plumbing follows the schema. The full offline suite (279) +
    e2e stay green.

## 11. Standing conventions (adopted here, apply to all future design docs)

### 11.1 Authority map

*Every design doc carries one: per fact — its source of truth, its writers, its
projections/readers.* The post-migration map for this system:

| Fact | Source of truth | Writers | Projections / readers |
|---|---|---|---|
| Raw list row | `intake_*` row (immutable) | `load_list` step 1 (insert only); migration backfill (once) | contact resolution; trade filter (`trades`); search; export |
| Primary intake row | `intake_*.is_primary` (exactly one true per contact) | contact resolution at creation; migration (once) | address inherit; delivery-point dedupe |
| Standardized address / delivery point / deliverability | `intake_*.std_*` snapshot | `verify_addresses` job, stamp phase (once per row) | delivery-point dedupe (via primary row); undeliverable exclusion; address inherit |
| Business identity | `contacts` row (phone-unique) | `load_list` step 2 (create/attach); migration (once) | everything |
| Contact fields (name, email, address, `source`, `segment`) | `contacts` columns (picked at creation) | pick rule at creation; migration survivor updates (email coalesce + next-action merge, once); `verify_addresses` inherit phase (once, `addr_validated_at` guard); `update_contact_address` (stamps `addr_validated_at`) | piece recipient; UI; source/segment filters |
| Stage | event stream (`derive_stage`, RULESET v2) | events via `ingest_event`/`append_event` | `stage_snapshot` cache — writer `recompute_state`, readers audience + UI |
| Suppression flags | `do_not_mail`/`do_not_text` columns | `suppress` (one-way); `load_list` resolution (creation + attach OR-merge, §4 — flags only, no event); `retire_seed` (`do_not_mail`, with the flag clear); migration OR-merge (once) | audience always-on exclusion; derivation (`ContactFlags`) |
| Seed identity | `contacts.is_seed` + `seed_key` | `ensure_seed_contacts` (sets true, upsert on `seed_key`); `retire_seed` (clears, with `do_not_mail`); migration backfill (`seed_key`, once) | wave seed append; audience always-on exclusion; the upsert's conflict key |
| Opt-out fact | `contact.opt_out` events | `suppress` only | suppressed derivation; future DNC derivations (`payload.reason`) |
| Piece status | event stream (delivery events) | `execute_wave` (`'submitted'`); `resolve_orphans` derives delivery states → `pieces.status` | wave dashboard |
| Next action | `contacts.next_action_at`/`_note` | `set_next_action` (founder); judgment job (Phase 4, yields to human-set); migration earliest-wins merge (once, reported) | due-nudges view; pipeline |
| Owner | `contacts.owner` today; event-derived under partner design (S-8) | genesis `'young'`; partner verbs later | nudge routing; readouts (derived, never the column) |
| Merge audit | `contact_merge_map` | migration (once) | forensics, restatement report only |

An empty writers cell is a dead fact (TD-2's disease) — visible at a glance.

### 11.2 Writer-named-at-declaration

*No stored fact, table, column, seam, or event may be declared without naming,
in the same paragraph: its writer, its readers, and its clear/delete path.*
Broader than the map: a Protocol with no implementation is a dead callee; a
lifecycle verb nobody calls is a missing verb. This doc complies — every
declaration above names all three.

## 12. Companion amendments (queued with approval)

- `PRD.md` FR-1: resolve-then-insert intake + per-source tables + verification
  job.
- `PRD.md` FR-4: "one piece per contact per wave (**hard constraint**)" — the
  DB constraint is gone; enforcement moves to audience resolution +
  `mailer_code` idempotency. Reword.
- `partner-lead-assignment.md` → revision 7 (twin-row stratum deleted) +
  implementation-plan renumbering (this migration becomes the first phase).
- `decisions.md`: entries for the grain decision, brand-merge ratification,
  restatement, the two standing conventions (written at approval, per the
  standing rule).
- `technical-debt.md`: TD-2 note (authority map adopted); this migration
  neither fixes nor worsens TD-2's dead columns.
- `current-state.md` rewrite after the session.
