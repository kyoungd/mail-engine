# Partner report — design

*Status: **APPROVED 2026-07-29, then RATIFIED the same day after review** — the approval
came first, a fresh-context review then found two blockers and two lines that could never
honestly render, and the corrected document is what stands ratified. Operator steer,
binding: "we don't need anything fancy at this time" — build the plain version, resist
additions.*

*Revision 2026-07-31 (operator-approved project restart, after the Sales Partner
Toolkit shipped): (1) a THIRD section, "Your demos," is added — the toolkit's
demo-contact log made partner demo activity system-observable, which the ratified
activity-exclusion could not have foreseen; the exclusion of DIALS stands unchanged
(the sheet is still invisible). (2) The close feed's §2 was rewritten against the
verified schema (`nmc-close-feed-contract.md`, same date) — customer-table spine,
three-table grant. (3) Project staging decided: FOUNDATION (partner Phases 1–4 +
read-only role + corrected contract — needed for the first active partner regardless
of this report) → FEEDS (close feed + demos feed) → REPORT (sender + composer + this
design). The report composer remains the LAST brick, deliberately. Implements the 2026-07-29
decisions (`decisions.md`): partners are informed by a periodic emailed report, not a
portal; the first half is HOLDINGS, not activity. **Split 2026-07-29 (operator): this
doc is the MARKETING half — composer, sender, content, cadence. The core site's half
(close-feed read-only role, trial-to-paid observability, roster, demos feed) lives in
`../../../docs/active/to-do-partner-report-support.md`.** Companions:
`partner-lead-assignment.md` (S-2 export, S-6 staleness, §8 performance),
`nmc-close-feed-contract.md` (the earnings data's inflow),
`../../../docs/partnership-program.md` (bonus and co-op structure), `../../../docs/active/to-do-partner-report-project-implementation.md` (the staged build plan, 2026-07-31).*

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

Three sections that ship at different times:

| Section | Data lives in | Available |
|---|---|---|
| **1. Your list** (holdings) | mail-engine spine | with partner Phases 1–4 (`partners`, `assignment_batches`, `contacts.owner_id`) |
| **2. Your closes** (earnings) | Medusa (customer-spine query, contract §2) via the close feed | after Q10 / `nmc-close-feed-contract.md` is built |
| **3. Your demo line** (revision 2026-07-31; retitled 2026-08-01 — covers all contact with the partner number, not only demo requests) | Service DB via booking-system's partner-keyed HTTP feed | after the demos feed (support doc Deliverable 4) is built |

Until a section's feed exists, the email simply has no such section. No placeholder,
no "coming soon" — a section appears when its data is real.

## Section 1 — Your list

All fields are spine queries; sources named so the composer is mechanical.

| Line | Source |
|---|---|
| **Headline: earliest expiry across all live batches** — *N days left* | min(`expires_at`) over the partner's unexpired batches (O2, 2026-07-29: a partner routinely holds two or three, and latest-batch-only would hide the clock that matters) |
| One line per live batch: assigned N contacts on DATE, expires DATE | `assignment_batches` (0009) |
| Contacts currently yours: N | `contacts` where `owner_id = partner` and not suppressed/reclaimed/expired |
| Removed since last report: N opted out, N reclaimed, N expired — shown only when one is non-zero; registry listings are not counted here | ownership events + suppression flags since last report date |
| **Now on the national Do Not Call registry — removed from your list, do not call:** one line per number, `- COMPANY, (AAA) NNN-NNNN`, then "These numbers are still on any sheet you exported before DATE." (operator decision 2026-09-10: "give them a list to exclude — name the numbers and company") | `contact.reclaimed` events with reason `dnc_registry` since the last report; DATE is the latest one |
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
| Closes credited since the last report: N (names of businesses) — *"since last report", never a calendar week; event-triggered sends make the two diverge* | ingested `signup.completed` events credited to this partner — by `partner_code` match **OR** `sold_by` = the partner's `sales_rep_id` (revision 2026-07-31; rep-entered closes often carry no typed code) — correlated to spine contacts |
| Total closes to date: N | same, cumulative |

**Orphaned-but-credited closes (revision 2026-07-31):** a coded close whose phone is
null or unmatched sits orphaned in the spine (contract §3), possibly for days —
business names come from the correlated contact, so an orphaned close has none. Rule:
it is **counted** in N immediately (crediting keys on the code/`sold_by`, not the
correlation) and listed as *"new close — details pending"* until correlation lands.
Never dropped, never guessed.

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

## Section 3 — Your demo line (added by revision 2026-07-31; retitled 2026-08-01)

*(Retitle, operator-approved 2026-08-01: the feed covers ALL prospect contact with
the partner's demo-forwarding number — calls the rep personally answers and texts
relayed to the rep, not only demo requests; `textsForwarded` is one of its five
aggregates. "Your demos" undersold the data and would read oddly next to a texts
count. The underlying route name `/api/partner-demo-calls` is shipped-prod legacy
from the toolkit and stays.)*

| Line | Source |
|---|---|
| On your demo line since your last report: N calls (M unique prospects, K from blocked numbers), T texts forwarded to you — *same "since last report" convention as Section 2 (final-review fix 2026-07-31: a calendar week would diverge from the report's own span on event-triggered sends, double- or never-reporting contacts)* | booking-system's demo-contact feed (below), window `[last_report_at, compose time)` |

The Sales Partner Toolkit gave every active partner a demo-forwarding number whose
calls and texts hit NMC's own webhook and land in `scheduling.partner_demo_contacts`
(Service DB). That is system-observed partner-funnel activity — it satisfies the
ratified honesty rule in a way dial counts never could, and **the dials exclusion
stands unchanged** (§1's "Deliberately absent" paragraph is not weakened by this
section; effort in the sheet remains invisible and unreported).

**Data path (decided with the toolkit design, `to-do-sales-partner-toolkit.md`
§ open item 3 → resolved here): a partner-keyed HTTP feed served by booking-system**,
`ApiKeyGuard`-authenticated, consumed by mail-engine at compose time — NOT a second
read-only role on the Service DB (one cross-system credential is the accepted TD-12
cost; two is a pattern). The existing capture-time endpoint cannot serve this (it is
prospect-phone-keyed, mandatory param, unaggregated); the report needs a variant keyed
on `partner_number` with a `[from, to)` window. **The window is
`[partners.last_report_at, compose time)`** — computed by MAIL-ENGINE (the caller,
who owns cadence); the endpoint does no calendar math (final-review fix 2026-07-31:
no calendar weeks anywhere — the earlier "calendar week via tz-handler" wording is
retired; `America/Los_Angeles` matters only for DISPLAYED dates in the email, via
Python `zoneinfo`).

**Honesty caveats, binding on the composer:**
- Blocked-ID contacts share one `anonymous` key → K counts **calls, not callers**, and
  `anonymous` must be excluded from the unique-prospect count M.
- Demo-contact writes are fail-soft (a DB failure never blocks the prospect's call) →
  all counts are **floors**, not a ledger. The report never claims exactness.
- Rows with a null rep snapshot (mapping outage at write time) are keyed by
  `partner_number`, which is always present — never dropped.
- Same as every section: if the feed is unreachable at compose time, the section is
  omitted — no placeholder, no stale numbers.

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

Everything the report needs from the main app — the close-feed read-only role (earnings
inflow), trial-to-paid observability, and partner registration via the existing roster —
is specified in `../../../docs/active/to-do-partner-report-support.md`. One operator
runbook stays on this side for revision 7: create the roster row on the main site, note
its `id`, insert the mail-engine `partners` row stamped with that `sales_rep_id`.
