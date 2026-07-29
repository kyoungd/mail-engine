# Partner report — design

*Status: **APPROVED** by the operator, 2026-07-29, as written — with the explicit steer
"we don't need anything fancy at this time": build the plain version, resist additions. Implements the 2026-07-29
decisions (`decisions.md`): partners are informed by a periodic emailed report, not a
portal; the first half is HOLDINGS, not activity. Companions:
`partner-lead-assignment.md` (S-2 export, S-6 staleness, §8 performance),
`nmc-close-feed-contract.md` (the earnings data's inflow),
`../../../docs/partnership-program.md` (bonus and co-op structure).*

## What this is

One email per active partner, on a fixed cadence, composed by mail-engine and delivered
through partner Phase 3's `Sender` (channel + address from the `partners` row). Plain
text. No links requiring login — there is nothing to log into, by decision.

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
| Batch assigned N contacts on DATE | `assignment_batches` (0009) |
| **Expires on DATE — N days left** | batch expiry (90 days, pinned) |
| Contacts currently yours: N | `contacts` where `owner_id = partner` and not suppressed/reclaimed/expired |
| Removed since last report: N opted out, N reclaimed, N expired | ownership events + suppression flags since last report date |
| Your last export was generated DATE (N days ago) | export generation timestamp (S-2) |
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
| Closes credited this period: N (names of businesses) | ingested `signup.completed` events carrying this partner's `partner_code`, correlated to spine contacts |
| Total closes to date: N | same, cumulative |
| Bonus status per close: vesting / vested / paid | Medusa-side per `partnership-program.md` (1.5× monthly, two halves, 3-month gate) — **included only when countable**; until trial-to-paid is observable per partner (`kind` in the feed contract), the line reads "close recorded DATE" with no vesting claim |
| Co-op mail credit balance | correlation of closes against mail-engine's spend ledger — app-level, never a join |

Same honesty rule as section 1: no line appears unless its data is real. A close with an
unverifiable vesting state shows the close, not a guessed state.

## Cadence

**Weekly, plus event-triggered.** Weekly is the heartbeat (the expiry clock is the thing
a partner most needs to see coming). Additionally, send within a day when a batch is
newly assigned, or when suppression removes a contact — the S-6 case where waiting up to
six days for the re-pull prompt is the risk itself. Open for the operator: collapse the
event-triggered send into "next morning" batching to avoid multiple emails in a day.

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

## Registration (the other half of "next"), for the record

- **Main site — exists.** `nmc_sales_rep` roster, admin-only CRUD
  (`/store/nmc/admin/sales-reps`), admin-page pattern already in the storefront. Creating
  a partner = adding a roster row there. If a roster management *page* (vs API) is
  missing, it is a small clone of the existing admin-page pattern — verify before
  building.
- **mail-engine — manual by decision** (2026-07-29): the operator inserts the `partners`
  row (migration 0009, unbuilt) with channel=email, the report address, radius, weekly
  hours — and stamps `sales_rep_id` from the main-site roster row, which is the
  correlation key the earnings section depends on. This runbook belongs in revision 7.
