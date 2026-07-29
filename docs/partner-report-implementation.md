# Partner report — implementation plan

*Execution brief for `partner-report-design.md` (APPROVED 2026-07-29, "nothing fancy").
Status: **draft — awaiting operator confirmation.** Where this plan and the design
conflict, escalate. Companions: `partner-lead-assignment-implementation.md` (the host
phases), `nmc-close-feed-contract.md` (the earnings inflow),
`../../../docs/active/to-do-partner-report-support.md` (the core site's half — not
sequenced here).*

## Honest total, up front

**R1 is contributed *during* revision 7** (it is a column list, not code). Everything
else — R2 onward — starts only after **grain Phase 4** (🔴 prod merge), revision 7, and
**partner Phases 1–4** land, because the report reads tables and rides transport those
build. (An earlier draft said "nothing in this plan starts until … revision 7 … lands",
which contradicted R1 by construction.)
This plan adds **one schema contribution and two coding batches** on top of that
sequence. It does not shorten it.

## Executor ground rules (inherited + report-specific)

1. The approved artifacts are decided: the report design (content, cadence resolution
   below), the close-feed contract, the partner plan's phases. Flaws are escalations.
2. **Never before Phase 3's `Sender` is real** — assembling reports nothing delivers
   reproduces TD-10 with a third party as the victim.
3. **The report never writes `nudge.sent` and never stamps `next_action_at`.** It has its
   own state (`last_report_at`) and its own send path.
4. Loud failure on a null/invalid channel (Phase 3's rule). No PII beyond the partner's
   own holdings. Frozen tests in `tests/acceptance/`, gate per batch.
5. "Nothing fancy" is binding: plain text, no templating engine, no HTML, no
   per-partner customization beyond the data itself.

## Cadence (closed in the design; restated here as the rule to build)

The design **closed** this option in review — event-triggered sends collapse into the
nightly, per the "nothing fancy" steer. This section is not a second gate; it writes the
resolved rule out in buildable form. (`decisions.md` still records cadence as "open, for
revision 7" from approval time — stale, superseded by the design's § Cadence.) The report is a **nightly
decision, not a scheduler**: each nightly run, per active partner —

    send if  (a) last_report_at is null or ≥7 days ago            [heartbeat]
         or  (b) a batch was assigned since last_report_at         [trigger]
         or  (c) a removal (opt-out/reclaim/expiry) since last_report_at   [trigger]

One piece of state (`last_report_at`), no cron beyond the nightly that already runs, and
"within a day" honored by construction.

## Phase R1 — schema contribution (no code; rides revision 7 → migration 0009)

Two columns on `partners`, contributed to revision 7's rewrite of migration 0009 —
**not** a separate migration, because 0009 is unwritten and columns are free until it
ships:

- `sales_rep_id bigint null` — the main-site roster id; the earnings correlation key
  (decision 2026-07-29). Null permitted: the house row has no roster entry.
- `last_report_at timestamptz null` — the report watermark. Null = never reported =
  heartbeat fires on the first nightly after the partner activates.
- **`partner_code text null unique`** — *added by review, 2026-07-29 (blocker).* The close
  feed carries `partner_code` (`"JK-01"`); nothing in mail-engine mapped that string to a
  partner, so the earnings section could not attribute a single close. `sales_rep_id` was
  named "the earnings correlation key" but appears in no data that ever reaches
  mail-engine — the feed has no such field. This is the failure `decisions.md`
  (2026-07-29) predicted in writing — *"without a stored key the correlation falls back to
  matching on partner name … precisely the class of thing this codebase refuses"* — and
  then walked into with a different key. The operator stamps this at partner creation,
  alongside `sales_rep_id` (which stays: it is the roster back-reference, not the close
  key).
- **`last_export_at timestamptz null`** — *added by review, 2026-07-29 (blocker).* Stamped
  by `export_batch` (partner Phase 4). S-2 puts a generation timestamp in a **column of
  the emitted CSV**, which persists nothing, and the event taxonomy adds six types, none
  export-related — so the design's "your last export was generated DATE" line had no
  readable source anywhere in the system. Phase 4 must stamp it; noted here because that
  is a one-line addition to a verb Phase 4 already builds.

Also contributed to revision 7: the close feed's phase home (R3 below) and the
registration runbook. **Gate: revision 7's own approval — this plan adds no gate.**

## Phase R2 — composer + holdings report 🟡 (after partner Phase 4)

*After Phase 4, not Phase 3: the "your last export" line reads S-2's generation
timestamp, which Phase 4 builds. One batch.*

- **`judgment/partner_report.py`** — not "executor's call" (the first draft left this
  open, which is the one thing a plan must not do). The precedent is unambiguous:
  `judgment/digest.py` **never imports the `Sender` Protocol**, it receives a sender
  injected and duck-types it, which is how it honors the dependency rule while calling a
  seam. The composer follows that exactly — pure compose here, injection at the `jobs/`
  edge, no `seams` import anywhere in `judgment/`.
  `compose_holdings(cur, partner) -> str | None`. Pure query + format;
  returns `None` when no line qualifies (a partner with no batch and no removals gets no
  email). Sources per line exactly as the design's table.
- **`jobs/` wiring**: the report runs **LAST in the nightly — after partner Phase 4's
  expiry job**, and this ordering is binding, not stylistic (found in review, 2026-07-29).
  Expiry is *"silent and automatic"*: a nightly job returns every past-expiry assignment to
  the house and *"the contact becomes assignable again immediately."* A report composed
  before that job tells a partner they hold contacts that are already gone and may already
  be partner #2's — which is precisely the double-dial failure the re-pull line exists to
  prevent, reintroduced by the report meant to prevent it. So: after
  `verify_addresses`/`resolve_orphans`/`recompute_state` **and after expiry**, per active
  partner **excluding `HOUSE_PARTNER_ID`**, apply the cadence rule; compose → `sender.send`
  → stamp `last_report_at`. **Stamp only after a successful send** — a failed send
  leaves the watermark, so the next nightly retries; one partner's failure must not
  block another's send (per-partner try/except, loud in the report line, run continues,
  nightly exits nonzero).
- **Frozen acceptance tests (the R2 gate, shown before greening):**
  1. Heartbeat: a partner **with holdings**, `last_report_at` 8 days ago → sent; 2 days
     ago → not sent; null → sent.
  1b. **Empty partner** (active, no batch, no removals): cadence says send, composer
      returns `None` → **no email, and `last_report_at` is NOT stamped** (nothing was
      sent; "stamp only after a successful send" governs). The heartbeat therefore stays
      true for an empty partner, which is harmless and deliberate — the first real batch
      produces the first report.
  2. Trigger: batch assigned yesterday, report 3 days ago → sent, names the batch.
  3. Trigger + re-pull line: a suppression removal since last report → sent, contains
     the re-pull sentence and the removal count.
  4. Content: fixture with known batch/holdings/expiry → exact expected lines; **no**
     effort/dial language anywhere in the output.
  5. Isolation: two partners, one's contact suppressed → only that partner's report
     carries the removal; neither report names the other's contacts.
  6. State discipline: a full send writes **zero** `nudge.sent` events and stamps no
     `next_action_at`.
  7. Failure: sender raises for partner A → A's `last_report_at` unstamped (next run
     retries), partner B still sent and stamped; the run fails loud.
  8. Null channel → the Phase 3 loud-failure path, not a skip.
  9. **House exclusion**: the house partner holds contacts and has a valid channel → no
     report composed, no send attempted, `last_report_at` untouched.
  10. **Ordering**: a contact whose batch expired today → the expiry job reclaims it
      first, and the report counts it under *expired*, never under *currently yours*.
      Constructed by running the nightly end-to-end, not by calling the composer directly
      — the ordering is the thing under test.

  On test 4's "no effort/dial language": implemented as an absence assertion over a small
  word list (`dial`, `attempt`, `call`, `worked`). That is a **smoke check, not a
  guarantee** — it catches a careless line, not a paraphrase. Named as weak so nobody
  reads it as proof.

## Phase R3 — close feed consumer 🟡 (contract §8's mail-engine half)

*Sequenced with R2 or after — independent of it. **Gated on the operator's §7
double-count decision**, which is required "before the first partner close" anyway.*

- **`seams/nmc_closes.py`**: `NmcCloseFeed` implementing `ResponseFeed`, `source="nmc"`,
  paging on `recorded_at`/`has_more` per the contract; yields
  `Event(type="signup.completed", external_id=close.id, payload={...})`.
- **`jobs/nightly_cli.py`**: registered behind `NMC_CLOSE_FEED_URL` / `NMC_CLOSE_FEED_KEY`,
  skipped-and-reported when unset (existing pattern). Per-feed watermark persisted
  (a small `feed_watermarks` table — revision 7 decides if it joins 0009 or is 0011).
  **Writer named, per the standing rule** (review 2026-07-29 — this repo's recurring defect
  class is the writerless declaration, TD-2): `jobs/sync.py` writes it, after the ingesting
  transaction commits, from the feed's own `next_since`. Advancing before the commit loses
  closes on a crash; advancing after re-reads a window at worst, which §4 of the contract
  makes free. The `Event` payload therefore carries `recorded_at` so the value is available
  to the writer.
- **§7 dedupe implemented per the operator's decision** — this plan does not presume it.
- **Frozen tests:** contract-shape mapping (a canned response → expected Events);
  watermark advances on `recorded_at` not `occurred_at`; re-poll of the same window
  ingests nothing new (rides `(source, external_id)`); unmatched phone stays orphaned
  (never fuzzy); the §7 behavior as decided.

## Phase R4 — earnings section 🟡 (after R3 has ingested real closes)

- Extend the composer: closes credited (this period / total, business names); vesting
  line **only when** `trial_to_paid` is
  observable (feed `kind`), else "close recorded DATE".
- **Co-op balance is NOT in scope** — cut from the design in review (no mail-engine spend
  ledger exists; the programme is main-side).
- **Frozen tests:** section absent when no close events exist (no placeholder); appears
  with correct counts when they do; a close without vesting data shows no vesting claim;
  the composer opens no connection outside the spine.

## Batching (per `/batch-build`: cut where something becomes fixed)

| Batch | Phases | What is fixed at the cut |
|---|---|---|
| — | R1 | rides revision 7's approval; no batch of its own |
| **RA** | R2 | the report's content contract (frozen tests **1–10**, the two review-correction tests included) + the cadence rule |
| **RB** | R3 + R4 | the feed consumer per the already-pinned contract + the earnings content |

RB after RA is the natural order but they share no code path except the composer file;
if the §7 decision arrives first, RB may run first without cost.

## Open — operator decisions this plan will not make (review 2026-07-29)

**O1 — RESOLVED (operator, 2026-07-29): the read-only Medusa connection wins.** Not the
HTTP endpoint. `partner-lead-assignment-implementation.md` Phase 4's Medusa-seam paragraph
therefore **stands as written** and nothing needs striking; `nmc-close-feed-contract.md`
was revised to describe the DB read, keeping its transport-independent rules (idempotency
on a stable `id`, watermark on the recorded-at column, all-closes-not-just-coded, `kind`,
§7 double-counting). Accepted cost recorded as **TD-12**.

*My recommendation had been the opposite, and it rested on an error: I claimed the
cross-database connection breached the 🔴 two-database invariant. The PRD says the reverse
— "Code touching both must open two connections" — so two connections is the sanctioned
pattern and the invariant forbids sharing a database and writing joins, neither of which
this does. The stricter rule was one I had written into my own contract draft and then
cited as if it were the PRD's.*

**Two prerequisites this pulls into R3** (contract §1): a **read-only role on the Medusa
DB, which does not exist today** — only the owner `medusajs_nmc_user`, and shipping *that*
to marketing would hand the mail engine write access to the subscriber database — and a
third connection helper `db/medusa.py` on `MEDUSA_READONLY_URL`, never a reuse of the two
existing helpers, which both point at mail-engine's own database.

**O2 — RESOLVED (operator, 2026-07-29): one line per live batch, earliest expiry as the
headline.** Section 1 renders every unexpired batch the partner holds — one to three in
practice, since §5 makes refill-before-expiry the intended pattern — and the section's
headline clock is the **earliest** expiry across them. Latest-batch-only was rejected: it
hides exactly the clock the design says the partner most needs to see coming. R2's tests 2
and 4 extend to a two-batch fixture, and a third test pins that the headline follows the
earliest expiry rather than the newest batch.

## Out of scope, restated

Anything the core site implements (`to-do-partner-report-support.md`); any portal or
partner auth; HTML mail; per-partner preferences; dispositions/effort of any kind.
