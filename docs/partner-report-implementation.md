# Partner report — implementation plan

*Execution brief for `partner-report-design.md` (APPROVED 2026-07-29, "nothing fancy").
Status: **draft — awaiting operator confirmation.** Where this plan and the design
conflict, escalate. Companions: `partner-lead-assignment-implementation.md` (the host
phases), `nmc-close-feed-contract.md` (the earnings inflow),
`../../../docs/active/to-do-partner-report-support.md` (the core site's half — not
sequenced here).*

## Honest total, up front

Nothing in this plan starts until **grain Phase 4** (🔴 prod merge), **revision 7**, and
**partner Phases 1–4** land — the report reads tables and rides transport those build.
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

## Cadence, resolved (design's one open option)

The design left open whether event-triggered sends collapse into next-morning batching.
**Resolved by the "nothing fancy" steer: they collapse.** The report is a **nightly
decision, not a scheduler**: each nightly run, per active partner —

    send if  (a) last_report_at is null or ≥7 days ago            [heartbeat]
         or  (b) a batch was assigned since last_report_at         [trigger]
         or  (c) a removal (opt-out/reclaim/expiry) since last_report_at   [trigger]

One piece of state (`last_report_at`), no cron beyond the nightly that already runs, and
"within a day" honored by construction. *Flagged for confirmation at plan approval since
it resolves a design-doc option.*

## Phase R1 — schema contribution (no code; rides revision 7 → migration 0009)

Two columns on `partners`, contributed to revision 7's rewrite of migration 0009 —
**not** a separate migration, because 0009 is unwritten and columns are free until it
ships:

- `sales_rep_id bigint null` — the main-site roster id; the earnings correlation key
  (decision 2026-07-29). Null permitted: the house row has no roster entry.
- `last_report_at timestamptz null` — the report watermark. Null = never reported =
  heartbeat fires on the first nightly after the partner activates.

Also contributed to revision 7: the close feed's phase home (R3 below) and the
registration runbook. **Gate: revision 7's own approval — this plan adds no gate.**

## Phase R2 — composer + holdings report 🟡 (after partner Phase 4)

*After Phase 4, not Phase 3: the "your last export" line reads S-2's generation
timestamp, which Phase 4 builds. One batch.*

- **`judgment/partner_report.py`** (or `service/` — executor's call, dependency rule
  permitting): `compose_holdings(cur, partner) -> str | None`. Pure query + format;
  returns `None` when no line qualifies (a partner with no batch and no removals gets no
  email). Sources per line exactly as the design's table.
- **`jobs/` wiring**: in the nightly, after `verify_addresses`/`resolve_orphans`/
  `recompute_state`, per active partner apply the cadence rule; compose → `sender.send`
  → stamp `last_report_at`. **Stamp only after a successful send** — a failed send
  leaves the watermark, so the next nightly retries; one partner's failure must not
  block another's send (per-partner try/except, loud in the report line, run continues,
  nightly exits nonzero).
- **Frozen acceptance tests (the R2 gate, shown before greening):**
  1. Heartbeat: `last_report_at` 8 days ago → sent; 2 days ago → not sent; null → sent.
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

## Phase R3 — close feed consumer 🟡 (contract §8's mail-engine half)

*Sequenced with R2 or after — independent of it. **Gated on the operator's §7
double-count decision**, which is required "before the first partner close" anyway.*

- **`seams/nmc_closes.py`**: `NmcCloseFeed` implementing `ResponseFeed`, `source="nmc"`,
  paging on `recorded_at`/`has_more` per the contract; yields
  `Event(type="signup.completed", external_id=close.id, payload={...})`.
- **`jobs/nightly_cli.py`**: registered behind `NMC_CLOSE_FEED_URL` / `NMC_CLOSE_FEED_KEY`,
  skipped-and-reported when unset (existing pattern). Per-feed watermark persisted
  (a small `feed_watermarks` table — revision 7 decides if it joins 0009 or is 0011).
- **§7 dedupe implemented per the operator's decision** — this plan does not presume it.
- **Frozen tests:** contract-shape mapping (a canned response → expected Events);
  watermark advances on `recorded_at` not `occurred_at`; re-poll of the same window
  ingests nothing new (rides `(source, external_id)`); unmatched phone stays orphaned
  (never fuzzy); the §7 behavior as decided.

## Phase R4 — earnings section 🟡 (after R3 has ingested real closes)

- Extend the composer: closes credited (this period / total, business names), co-op
  balance via the app-level correlation; vesting line **only when** `trial_to_paid` is
  observable (feed `kind`), else "close recorded DATE".
- **Frozen tests:** section absent when no close events exist (no placeholder); appears
  with correct counts when they do; a close without vesting data shows no vesting claim;
  correlation never queries outside the spine (no cross-DB connection in the composer).

## Batching (per `/batch-build`: cut where something becomes fixed)

| Batch | Phases | What is fixed at the cut |
|---|---|---|
| — | R1 | rides revision 7's approval; no batch of its own |
| **RA** | R2 | the report's content contract (frozen tests 1–8) + the cadence rule |
| **RB** | R3 + R4 | the feed consumer per the already-pinned contract + the earnings content |

RB after RA is the natural order but they share no code path except the composer file;
if the §7 decision arrives first, RB may run first without cost.

## Out of scope, restated

Anything the core site implements (`to-do-partner-report-support.md`); any portal or
partner auth; HTML mail; per-partner preferences; dispositions/effort of any kind.
