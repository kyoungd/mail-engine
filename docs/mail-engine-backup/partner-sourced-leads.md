# Design — Partner-Sourced Numbers

*Revision 5, 2026-08-06. Extends `partner-lead-assignment.md` (rev 7).
Rev 3's open question is closed by §8's 30-day release.
Rev 1 bundled in a territory rethink and a permission gate-waiver — both cut
(§7). Rev 2 was reviewed and failed on three counts now fixed: the marker had no
reset path (solved by making it an attribution, §4), the new intake table had no
reader (dropped, §3), and the "already in our list" case was treated as an edge
when it is the common one (operator decision, §3).*

---

> ## 🚫 DEFERRED — not built, not shipped. This is a future-upgrade spec.
>
> **Operator decision, 2026-08-06: cut from this version.** The feature was built
> to rev 5 (`f3ce10c`) and then **fully backed out** the same day — the import
> verb, migration `0011`, the export's personal-window waiver, the assignment
> attribution gate, the holdings splits, and the console front door are all gone
> (`0012.drop-sourced-attribution.sql`). Production never received any of it.
> Nothing was ever imported and nothing was ever dialed under it.
>
> **Why it was cut:** the design bundled three separable things — *acquisition*
> (new inventory), *permission* (a legal basis to call), and *custody* (90-day
> exclusivity). Only permission was hard, and it did not hold up. What the CSV
> collects is **oral, relayed permission**; our reading of
> 16 CFR § 310.4(b)(1)(iii)(B)(1) is that only a **signed writing** exempts a
> registry-listed number, so a referral supplies no basis at all. §2's
> oral-vs-written reasoning, which the waiver rested on, was wrong and is
> corrected in place below.
>
> The decisive argument was not that one, though — it was **safe-harbor
> contagion**. § 310.4(b)(3) forgives an *isolated error despite procedures*; a
> category-wide carve-out is not an isolated error, so waiving the scrub for
> referrals put the posture for the **whole program** at risk, including the
> scrubbed CSLB calls. Open as **counsel question 8(e)** in
> `nvermisscall/docs/counsel-memo-dnc-b2b.md`.
>
> **What partners do instead (no system involvement):** a referral is not
> dialable. Rule 1 of the dialing procedure stands absolute — you call what is on
> your current export, and nothing else, however you came by the number. A
> partner offered an introduction either gives out the demo line and lets the
> contractor call in (an inbound inquiry creates an EBR, which clears the
> registry on its own, and the demo line already carries per-partner
> attribution), or sends the number to the operator for a future scrubbed batch.
>
> **If this is ever revived**, the shape to build is the *inverse* of §4: scrub
> first, then 90 days of custody on the survivors, with unsubscribed area codes
> never reaching a sheet. That keeps acquisition and custody and drops the
> permission waiver entirely. Sections 4, 5 and 9 below describe the ORIGINAL
> waiver design — read them as the rejected option, kept for the reasoning.

---

## 1. What this is

Partners collect numbers of their own — a referral, a supply-house
conversation, someone who said "have him call me." Today there is nowhere to put
them, and the dialing procedure forbids calling anything not on the current
export (rule 1), so the honest partner drops the lead.

**We give a partner 100 numbers; they may add as many of their own as they
like.** Three requirements:

1. **Import** — a CSV of numbers they collected, carrying who gave permission,
   when, and where.
2. **Theirs, uncounted** — their own numbers do not come out of the 100 and are
   never reassigned to another partner. The registry-free window lasts 90 days;
   custody and attribution outlast it (§4).
3. **One sheet** — their export shows both, marked so they can tell which is which.

**The number is usually already ours, and that is fine.** The spine holds the
full CA CSLB list (100,444 contacts, 81,988 with phones, six trades), so a
licensed contractor a partner meets is probably already a row. **Operator
decision, 2026-08-06: give it to them anyway — they worked for it.** The import
therefore *takes custody* of an unowned existing contact rather than merely
annotating it. The genuinely new rows are the businesses our purchased lists
never covered: locksmiths (no CSLB data at all), handymen, unlicensed
operators, out-of-trade and out-of-state businesses.

**One gate does change, narrowly.** A number in a partner's personal list is on
their sheet for 90 days **without an FTC-registry check** — the recorded
permission is the basis for the call, which is the whole point of collecting it.
It never waives **our own** do-not-call list or a suppression tombstone: a
person who told *us* not to call them is never callable, and that is the one
exemption the law does not offer. See §4 for the rule and §5 for where it lives
in code.

**This rests on one legal premise** — that permission given to a partner is
permission for NMC, the seller. It is on the **Q6 counsel agenda**; the design
is shaped so that if counsel narrows it, the change is the export's predicate,
not the schema.

## 2. The CSV

```csv
business_name,contact_name,phone,addr_line1,city,state,zip,permission_by,permission_at,permission_where,sourced_by
"Smith Plumbing","Bob Smith",8185551234,"123 Main St","Van Nuys",CA,91401,"Bob Smith (owner)",2026-08-05,"in person at Ferguson supply counter",John
```

**Required — no provenance, no number:** `phone`, `permission_by` (who said it),
`permission_at` (`YYYY-MM-DD`), `permission_where` (channel and context, in the
partner's words), `sourced_by` (the partner; `partners.name` is `unique` in the
schema, so the name is a legitimate key — an unmatched or inactive partner
rejects the row). Everything else optional. A row missing any required field is
**rejected and named in the report**, never silently imported.

Address column names match the **export's** header (`city,state,zip`), so a
partner can edit their own sheet into an import file without renaming anything.

`permission_at` is the only field the system computes with — it opens the 90-day
window in which the number is callable without a registry check. The other three
are recorded, not interpreted: they exist so "why did we call this number?" has
a stored answer, and they are the evidence behind the window. This is why the
required fields fail closed: no provenance, no window.

**No `permission_kind` field.** Rev 5 justified this by treating oral and written
permission as one thing with two lifespans (~3 months vs. until revoked), and
picking 90 days as "the shorter of the two, so it is safe for both."
**That reasoning is withdrawn as legally wrong (2026-08-06).** The ~3-month
figure is the **EBR-from-inquiry** window (16 CFR § 310.4(b)(1)(iii)(B)(2)) — a
different exemption, not the life of an oral permission. For the registry
exemption itself, both the TSR (§ 310.4(b)(1)(iii)(B)(1)) and the FCC rule
(47 CFR § 64.1200(c)(2)(ii)) require permission **in writing and signed**. So 90
days was never the conservative choice between two valid bases; for oral
permission there is no basis to be conservative about.

The field still does not ship, for the unchanged practical reason — a partner
should not be making a legal classification in a spreadsheet cell. But the
consequence is material and is flagged in the header: what this CSV collects is
**oral, relayed permission**, which is exactly what cannot carry § 4's waiver.

## 3. What import does

Resolution is by phone, and the four cases differ:

| The number is… | What happens |
|---|---|
| **not in our database** | new contact, owned by and attributed to the partner |
| **in our database, unowned** | custody moves to the partner, attributed to them *(operator decision — they worked for it)* |
| **already theirs** | permission recorded; attribution set; custody unchanged |
| **held by another partner** | **conflict — nothing moves.** Reported with evidence (§6) |

Every case records a **`contact.permission_recorded`** event carrying the
who/when/where payload — one addition to the closed taxonomy. That event *is*
the legal record; there is no referral intake table (rev 2 specified one, then
excluded it from every reader that would have used it — a table with a writer
and no reader). The CSV file itself is the raw archive, as FR-1 already says of
source CSVs.

**Two consults the import must perform**, because it is a contact-creating path:

- **Suppression tombstones**, exactly as `load_list` does
  (`service/contacts.py:152-169`). A person who once told us "don't call me"
  and whose contact was later hard-deleted must re-acquire their suppression,
  not return as a fresh mailable row. This is the one hole that would make
  "passes the ordinary checks" a lie.
- **`source`** must be set for the new-contact case; `contacts.source` defaults
  to `'cslb'`, which would mislabel referrals in a live assignment-rule key.

**The report states, per row, what happened** — created / took custody /
already theirs / conflict / rejected-with-reason. Every accepted row **reaches
the sheet immediately**: the personal-list window needs no scrub, so there is no
"wait for tonight's cycle" and no "unsubscribed area code" blocker while it is
open. Only our own `do_not_call` or a tombstone withholds one, and that is
reported as a refusal, not a delay.

**What the report must flag instead is the cliff**: for any row that would
*fail* ordinary rules — registry-listed, or in an area code we do not subscribe
to — say when it drops off. *"+13105551234 — registry-free until 2026-11-04;
after that it needs DNC clearance, and 310 is not subscribed."* The partner has
90 days to convert it, and the operator knows the deadline at import rather than
discovering the absence three months later.

**No self-serve upload.** Partners send the CSV; the operator imports it and
stays the compliance chokepoint.

## 4. The marker: attribution, not a status

**`contacts.sourced_by_partner_id`** — nullable FK to `partners`, set by the
import, **never cleared automatically**. One column, three jobs:

- **Custody kind is derived, not stored**: a holding is *sourced* when
  `sourced_by_partner_id = owner_id`, *issued* otherwise. No second column, and
  no reset path to get wrong — a value that persists after the contact returns
  to the pool is the intent, not a leak.
- **"Not reassigned" (requirement 2)**: the assignment audience excludes any
  contact attributed to a *different* partner. If John's sourced contact returns
  to the pool — won, suppressed, DNC-hit and later delisted — it comes back to
  John, never into partner #2's batch.
- **Counting**: holdings split by comparing the two columns.

Clearing it is an explicit operator act (the partnership-ends case, §8).

| | **Issued** | **Sourced (their personal list)** |
|---|---|---|
| Origin | our purchased lists | the partner's own collecting |
| Count | sized from weekly hours (the 100) | unlimited, uncounted |
| **FTC registry** | **must clear it** — registry, subscribed code, fresh scrub | **not required** — the recorded permission is the basis |
| **Our own do-not-call / tombstone** | always applies | **always applies** — permission never overrides the entity-specific list |
| Window | 90 days → house pool | 90 days from `permission_at`, then ordinary rules resume |
| Reclaim | yes (S-5) | only on explicit operator request |
| Won | terminates custody | terminates custody |

**The rule in one line (operator, 2026-08-06):** *a number is on the partner's
sheet if it is in their personal list (≤90 days), or if it came off the main
list and clears DNC.* Everything else follows.

> ⚠️ **That line is the one under review** (header). The proposed replacement is
> *a number is on the partner's sheet if it clears DNC — whatever its origin —
> and a sourced number then gets 90 days.* Under it the **FTC registry** row of
> the table above reads "must clear it" for **both** columns, and the
> unsubscribed-area-code case stops being a future cliff (§3) and becomes an
> import-time refusal. The rest of the table is unaffected: attribution,
> uncounted-against-the-100, never-reassigned, and the won/reclaim rules all
> stand either way.

**Dedup needs no code.** `contacts` is phone-unique since the grain migration,
so a number reachable from both sources is one row; it cannot appear twice. What
changes is which rules apply to it — personal wins while its window is open.

**After 90 days** the entry falls back to ordinary rules: DNC-clear and it is a
normal lead; registry-listed or in an unsubscribed code and it is dead
inventory. No expiry job is needed for this — the export simply stops treating
it as personal.

Both live in the same `contacts` spine: phone-uniqueness is the invariant the
grain migration exists to enforce, and a separate table would reintroduce the
duplicate-dialing bug — two partners, two rows, one plumber's phone.

## 5. Code changes

| Change | Why |
|---|---|
| Migration `0011`: `contacts.sourced_by_partner_id` + `contacts.permission_at` (see `migration-0011-plan.md` rev 3) | two columns — no new table. Both are written by the import and read by the export in the same batch. |
| Taxonomy `contact.permission_recorded` — one line in `domain/taxonomy.py`, no DDL (`events.type` is plain text). Lands **with the import verb**, the first thing that emits it. | the legal record |
| **Nightly release step** — `partners.deactivated_at` (its column, its `partners_cli` writer, **and a clear-on-reactivate rule**, together in one batch) plus a step clearing attribution for partners inactive longer than `SOURCED_RELEASE_DAYS` (30); slots beside the existing expiry step (§8) | the reversal window |
| **Import verb** — CSV parse, provenance validation, phone normalization (`to_e164`, spine-side as today), tombstone + `source` consults, per-row resolution (§3), custody via `set_owner` with **no batch id and no expiry**, plus the report. `load_list` cannot be reused: it rejects rows lacking trade/segment, dedupes on a `list_key` referrals do not have, and inserts a fixed 17-column intake tuple. | the feature |
| **Export** — currently an INNER join to `assignment_batches` (`assignment.py:328-329`), so a batchless contact is silently absent. LEFT join + an `origin` column. **And the DNC predicates become conditional**: `dnc_registry = false` and the freshness test apply only to issued rows; a personal row inside its 90-day window skips them. `do_not_call = false` and the tombstone check apply to **both**, unconditionally. | requirements 1 and 3 — this is where the rule actually lives |
| **Won-termination** — filters `assignment_batch_id is not null` (`assignment.py:414-416`), so a sourced contact who becomes a customer is never terminated and stays on the sheet (the base design's worst case, S-10). Replace the predicate with `owner_id <> HOUSE_PARTNER_ID` — **not** a plain removal, which would re-select every won pool contact nightly forever. | safety |
| **Reclaim** — selects on `owner_id` alone (`assignment.py:373-377`), so it would seize a partner's own numbers. Restrict to issued; explicit flag for partnership-ends. | §4 |
| **Assignment audience** — exclude contacts attributed to another partner. | requirement 2 |
| **Holdings counts** — `partners_cli status` (`jobs/partners_cli.py:169`) and the emailed partner report (`judgment/partner_report.py:77-80`) count differently; today the report would say "100" while the sheet shows 123. Both split issued/sourced. | consistency |
| **Single-contact custody move** — no operator verb exists (assignment_cli has assign/export/reclaim only); §6 needs one. | conflict resolution |
| Console item 11, "import collected numbers" | the front door |

**Expiry needs no change** — the nightly joins contacts *through* their batch
(`assignment.py:393-397`), so a batchless contact is never touched.

**Not changing:** `_INTAKE_TABLES`, `is_primary`, `verify_addresses`. A sourced
contact has no intake row at all, so it carries no trade and no segment and is
invisible to trade- and segment-filtered audiences, and its hand-typed address
is never CASS-standardized. Acceptable — these contacts are assigned by import,
never drawn by a rule — but stated, not discovered.

## 6. Conflict: the number is already another partner's

Nothing moves automatically. **Operator decision, 2026-08-06: adjudicate on
evidence of who has actually been working the contact.** The import report puts
that evidence in front of the operator at import time rather than sending them
hunting:

- who holds it, and since when;
- **activity on the contact** — inbound calls, notes, and signups, reusing the
  definition the day-30 checkpoint already owns
  (`judgment/rules/batch_checkpoint.ACTIVITY_TYPES`);
- **demo-line calls** attributable to each partner's number, via the existing
  per-partner aggregates (`seams/nmc_demos.py` → the booking-system endpoint).

The operator then either leaves it or moves it with the single-contact custody
verb (§5), which records a reason like any other custody event. Both partners'
reports reflect the move on their next send.

## 7. Out of scope (parked)

Real, none blocking:

- **Territory vs. area code.** Area code partitions work today; it should be
  geography, with area code demoted to a coverage question. Rev 1's coverage
  numbers were **pre-scrub and wrong** (3,964 "dialable" was really 2,227) and
  the method was not reproducible — any revival starts with a recorded script,
  and must treat unsubscribed-code unlock counts as *estimates* (~52% of raw at
  the measured listing rate; we cannot scrub what we do not own).
- ~~**Permission as a gate waiver**~~ — **now in scope** (operator rule,
  2026-08-06, §4): the 90-day personal-list window *is* the waiver, scoped to
  the FTC registry only and to the partner holding it. What stays parked is the
  *longer* written-permission window, which would need a permission kind and a
  revocation verb. The seller-attachment premise is on the **Q6 counsel agenda**.
- **Storage of the written permission artifact** (screenshot, email) — v1 stores
  the partner's description of it, not the thing itself.

## 8. When a partnership ends — the 30-day release

**Decided 2026-08-06 (operator).** The numbers return to the general pool — the
permission was given to NMC, not to the individual — but **not immediately**, so
an ending that turns out to be temporary can be reversed:

| Day | State |
|---|---|
| 0 | Partnership deactivated. **Custody returns to house at once** (no export can go out to an inactive partner). Attribution is **retained**. |
| 0–30 | The contacts sit in the house pool but are **not assignable to anyone else** — §4's audience exclusion does that for free. Reversible: reactivate the partner and re-assign their attributed contacts. |
| 30 | A nightly step **clears `sourced_by_partner_id`**. They become ordinary pool contacts. |

**Mechanism:** `partners.deactivated_at`, stamped when status flips to
`inactive` **and cleared when it flips back to `active`** — without that clear,
a partner deactivated → reactivated → deactivated again carries a stale
timestamp and the release fires immediately, destroying attribution with no
reversal window at all (review finding, 2026-08-06; it is the same
stranded-stored-state defect this design rejected `custody_kind` for). A nightly
step then clears attribution for partners inactive longer than
`SOURCED_RELEASE_DAYS` (30). Column, writer, reader, and clear rule ship in one
batch — never the column alone.

**No special DNC sync is needed, and the timing is why.** A released contact
must be freshly scrubbed before anyone else can be assigned it — and it already
will be. `dnc_refresh` sweeps **every** contact in a subscribed area code whose
check is older than `DNC_RECHECK_DAYS` (21), house-owned included
(`jobs/dnc_refresh.py:56-68` — ownership only sets the *order*, assigned first).
So within the 30-day quarantine the daily cycle re-scrubs the whole set, and by
the time attribution clears the check is ~9 days old against a 31-day wall.
**30 > 21 is what makes this work**; a shorter release window would hand out
contacts whose scrub had not yet been refreshed, and the `dnc_stale` gate would
then refuse them anyway.

**One honest exception:** a contact in an area code we do *not* subscribe to is
never scrubbed at all, so on release it stays permanently unassignable
(`dnc_unsubscribed`). It is dead inventory until that code is bought — correct,
but it means a departing partner's out-of-code numbers do not return as usable
leads.

## 9. Partner-facing follow-up

The export gains an `origin` column and blank `expires_at` cells for sourced
rows. The dialing procedure (**parent repo**,
`nvermisscall/docs/partner-dialing-procedure.md:39-40`) currently tells partners
*"Every batch is protected to you for 90 days from assignment (the date is
printed on your sheet)"* — a blank date needs one sentence of explanation there,
or partners will ask.
