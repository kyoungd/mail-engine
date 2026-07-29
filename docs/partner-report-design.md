# Partner report — design

*Status: **APPROVED 2026-07-29, then RATIFIED the same day after review** — the approval
came first, a fresh-context review then found two blockers and two lines that could never
honestly render, and the corrected document is what stands ratified. Operator steer,
binding: "we don't need anything fancy at this time" — build the plain version, resist
additions. Implements the 2026-07-29
decisions (`decisions.md`): partners are informed by a periodic emailed report, not a
portal; the first half is HOLDINGS, not activity. **Split 2026-07-29 (operator): this
doc is the MARKETING half — composer, sender, content, cadence. The core site's half
(close-feed endpoint, trial-to-paid observability, roster) lives in
`../../../docs/active/to-do-partner-report-support.md`.** Companions:
`partner-lead-assignment.md` (S-2 export, S-6 staleness, §8 performance),
`nmc-close-feed-contract.md` (the earnings data's inflow),
`../../../docs/partnership-program.md` (bonus and co-op structure).*

## What this is

One email per active partner **except the house account**, on a weekly floor with event
triggers (§ Cadence), composed by
mail-engine and delivered
through partner Phase 3's `Sender` (channel + address from the `partners` row). Plain
text. No links requiring login — there is nothing to log into, by decision.

**The house account is excluded, and that exclusion is load-bearing** (review correction,
2026-07-29). `contacts.owner_id` defaults to `HOUSE_PARTNER_ID`, so the house row "holds"
every unassigned contact — ~100,444 of them — and its channel is seeded to
`young@nevermisscall.com`. Without the exclusion the operator receives a weekly email
reading *"Contacts currently yours: 100444"* with no batch and no expiry: pure noise, and
the kind of noise that trains someone to ignore the channel the real reports arrive on.
The house id is a **planned** pinned constant (`HOUSE_PARTNER_ID`, seeded by partner
Phase 1 — it is not in `config/params.py` today; an earlier draft of this paragraph
asserted it was). Once it exists this is a filter, not a heuristic.

Two sections that ship at different times:

| Section | Data lives in | Available |
|---|---|---|
| **1. Your list** (holdings) | mail-engine spine | with partner Phases 1–4 (`partners`, `assignment_batches`, `contacts.owner_id`) |
| **2. Your closes** (earnings) | Medusa (`nmc_sales_attribution`) via the close feed | after Q10 / `nmc-close-feed-contract.md` is built |

Until the close feed exists, the email simply has no section 2. No placeholder, no
"coming soon" — a section appears when its data is real.

## Section 1 — Your list

All fields are spine queries; sources named so the composer is mechanical.

| Line | Source |
|---|---|
| **Headline: earliest expiry across all live batches** — *N days left* | min(`expires_at`) over the partner's unexpired batches (O2, 2026-07-29: a partner routinely holds two or three, and latest-batch-only would hide the clock that matters) |
| One line per live batch: assigned N contacts on DATE, expires DATE | `assignment_batches` (0009) |

| Contacts currently yours: N | `contacts` where `owner_id = partner` and not suppressed/reclaimed/expired |
| Removed since last report: N opted out, N reclaimed, N expired | ownership events + suppression flags since last report date |
| Your last export was generated DATE (N days ago) | `partners.last_export_at`, stamped by `export_batch` — **new column, see R1** (review 2026-07-29: S-2 puts the timestamp in a *column of the emitted CSV*, which persists nothing, so this line had no readable source) |
| **→ If any removals: "Re-pull your sheet before your next calling session."** | derived from the removal counts |

The re-pull line is the point of the whole section. S-6's residual risk — a suppressed or
reclaimed contact stranded in an exported sheet — is mitigated only *procedurally* (the
partner agreement says re-pull). This report turns that promise into a recurring,
data-triggered prompt: the email arrives *because* something changed, and says so. It is
not a live view and must not claim to be one; it is a nudge toward the fresh export,
which is the designed mechanism.

**Deliberately absent: dials, contact attempts, conversations.** §3 keeps dispositions
out of the spine; effort lives in the partner's own sheet. The report must not imply the
system can see work it cannot ("Activity is one bit" — `partnership-program.md`).
Nothing in section 1 is a performance judgment.

## Section 2 — Your closes (after the close feed)

| Line | Source |
|---|---|
| Closes credited since the last report: N (names of businesses) — *"since last report", never a calendar week; event-triggered sends make the two diverge* | ingested `signup.completed` events carrying this partner's `partner_code`, correlated to spine contacts |
| Total closes to date: N | same, cumulative |

**Two lines cut in review (2026-07-29, operator-approved): bonus vesting and co-op
balance.** Both were main-side *ledger* facts — "vested" (the two-halves three-month gate),
"paid" (a payout ran), and an accrued credit balance — and nothing mail-engine reads
carries them. The co-op line additionally cited a *"mail-engine spend ledger"* that does
not exist: `pieces.cost_cents` is per-piece spend, not an accrual, and the co-op programme
is defined main-side in `partnership-program.md` § Co-op Mail Credit.
The close data answers *did this partner close someone*, not *what have they been paid*.
Reporting a guessed vesting state would be worse than omitting it: a partner reading
"vested" and not being paid is a trust problem, not a display bug.

So Section 2 is deliberately narrow: **which businesses this partner closed, and when.**
Money questions belong to whoever owns the money — the main site — and if a partner should
see a balance, it should arrive from there, not be reconstructed here.

Same honesty rule as section 1: no line appears unless its data is real.

## Cadence

**Weekly, plus event-triggered — and the event-triggered send collapses into the nightly**
(option closed in review, 2026-07-29, by the "nothing fancy" steer). Weekly is the
heartbeat, because the expiry clock is the thing a partner most needs to see coming. A
newly assigned batch, or a suppression removal, brings the next report forward to the next
nightly run — the S-6 case where waiting up to six days for the re-pull prompt is itself
the risk. No scheduler, one piece of state; the rule is written out in
`partner-report-implementation.md` § Cadence.

## Rules carried over from existing decisions (binding on the implementation)

1. **Ships with/after partner Phase 3, never before** — a report on an unwired `Sender`
   reproduces TD-10 with a third party as the victim.
2. **Never writes `nudge.sent`, never stamps `next_action_at`** — those belong to the
   judgment machinery and feed FR-10's self-grading.
3. **Loud failure**: a partner with a null/invalid channel fails the run visibly
   (Phase 3's rule), never a silent skip.
4. **No PII beyond the partner's own holdings**: the report names businesses the partner
   already holds or closed — never other partners' contacts, never counts of the wider
   pool.

## The core site's half

Everything the report needs from the main app — the close-feed endpoint (earnings
inflow), trial-to-paid observability, and partner registration via the existing roster —
is specified in `../../../docs/active/to-do-partner-report-support.md`. One operator
runbook stays on this side for revision 7: create the roster row on the main site, note
its `id`, insert the mail-engine `partners` row stamped with that `sales_rep_id`.
