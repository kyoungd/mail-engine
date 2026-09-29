# Feature Overview — Partner Lead Assignment

*Mail Engine. Revision 7, 2026-08-01 (twin-row stratum deletion — the fold revision 6's
own header scheduled, executed under the project plan
`../../../docs/active/to-do-partner-report-project-implementation.md` A1-0).
Status: **APPROVED** — operator approval given at the end of the revision-6 session,
recorded 2026-07-28 (it was not written down at the time). Per revision 3's note,
decisions taken by review recommendation are ratified with this approval. Provenance
of revision 7's changes, stated explicitly: the twin-row DELETIONS were pre-scheduled
by the approved revision 6's own header; the R1 column/`feed_watermarks` ADDITIONS to
migration `0009` are directed by the operator-reviewed project plan (its A0–A1
sequence) — neither rides in silently under the 2026-07-28 stamp.*

*⚠️ The grain prerequisite has LANDED. `ingest-contact-migration.md`'s merge is applied
(dev-verified 2026-08-01: migration `0008` + `migrate_grain.py`; **100,444** contacts,
**zero** shared phones, and the storage guarantee is `contacts_phone_unique` — a partial
unique index on `phone_e164` where phone is non-null and `is_seed = false`). Migration
numbering holds: grain took `0008`, this feature takes `0009`/`0010`. The build is
unblocked; Phase 0's non-code lead times (SAN, counsel) still apply.*
*Companions: `PRD.md` (FR-6 attribution, FR-7 derived state, FR-8 suppression),
`../../../docs/partnership-program.md` (Steps 11–14, Ground Rules),
`direct-mail-ai-data.md` (contact table), `decisions.md`, `technical-debt.md`,
`partner-lead-assignment-implementation.md` (the execution brief for this design).*

*Revision 2 closes six open questions, adds the DNC compliance section (§6) that
revision 1 lacked entirely, and corrects S-7, which rested on a premise that turned out
to be false. Batch size and area-code scope are now derived from partner inputs (hours,
base address) rather than asserted; suppression splits per channel because a single
boolean would have let a compliance flag silently delete the mail audience; and partner
commission is earned by a **typed** code, which is what keeps custody from paying like
work. Scope is unchanged: one partner signed today, 3–5 expected within the 60-day
phase.*

*Revision 3 (same day) hardens revision 2 against an end-to-end review. The assignable
pool now excludes mid-funnel contacts — revision 2 excluded only `won`, leaving a
contractor mid-conversation on the demo line assignable as a cold call (S-1, §11 Q11).
The custody data model is pinned instead of implied (§7: `partners` /
`assignment_batches` / where expiry lives / what "assigned" means). S-2's export
degrades like S-1 instead of hard-failing on one stale row. The single-writer invariant
now names all six owner-writing stories, not four. The safe harbor's paper prongs
(written procedures, training) and the SAN registration prerequisite get named owners
(§6, §10). The stale-sheet mitigation extends to expired and reclaimed rows, not just
suppressions (S-6). And S-8 pins custody intervals to the expiry stamped in the
assignment event, not the expiry job's clock. A code-verification pass then confirmed
the design against the implementation: the nudge budget is per-recipient in code as
assumed; the S-7 routing split maps onto an existing `Recipient` enum (two inactivity
rules must flip, S-7); and the historical `contact.opt_out` stream is ambiguous in a
way the suppression split must handle (S-6). Decisions taken by review recommendation
are ratified with this document's approval. The implementation plan
(`partner-lead-assignment-implementation.md`) sequences all of it.*

*Revision 4 (same day) incorporates a second independent review, whose findings were
second-order — how correct-looking rules compose. The largest: **voice facts are now
phone facts** — `do_not_call`, `dnc_registry`, and won-termination gated per phone
rather than per row, because the measured 1,785 shared numbers let every one of those
protections be honored on one row of twelve while a twin walked back into the pool
(S-1, S-6, S-9, S-10). The Q10 double-count guard is now bidirectional (the reviewer
noted the unguarded ordering is today's production default, PostHog keys being
unconfigured). The Chatsworth free-five is **disputed by an independent
re-measurement** (661 likely belongs in it, not 747) and must be re-derived with a
pinned method before subscribing (§6, Q7). Custody derivation is split into two named
functions (current vs at-time, S-8). CCPA hard-delete vs `do_not_call` permanence is
resolved with a phone-keyed tombstone (S-6). Plus the delisting writer, the house-row
identity, the trial-batch path, and three legal wording precisions (§6).*

*Revision 5 (same day) incorporates a third independent review. The tombstone added in
revision 4 had **no writer** — the exact dead-writer shape this feature keeps finding —
and covered voice only; it is now written by `suppress()` itself, carries a channel,
keys on both phone and `list_key`, and intake consults it (S-6). The Q10 anti-double-
count guard moves from the PostHog mapping (where it was unimplementable — PostHog
events are ingested contact-less) to the consumers (S-10). Exclusivity gains a
storage-level enforcement mechanism — a partial unique index — because SELECT-gates
alone do not survive concurrency (S-1, §7). A third radius measurement agrees with the
second (661 in, 747 out), and the dispute now propagates to Q7/Q8 instead of living
only in §6's warning. Plus: the migration default that keeps intake working, the scrub
event-volume accounting, the per-recipient digest abort that stops the compliance
alarm from silencing itself, a `partners` writer, the intake flag-event exemption
closed, and the stage-race window stated honestly (nightly latency, the unconfigured
PostHog feed, and TD-1's phone blindness — not "same-day").*

*Revision 6 (same day) incorporates a fourth independent review, aimed at revision
5's own patches — where seven of its ten findings landed. The honest ones: the
consumer-side signup dedupe named consumers that don't exist (TD-3 — no signup
counting exists to deduplicate; the requirement narrows to what is real, S-10); the
correlation's pinned nightly placement ran *before* `resolve_orphans` and so defeated
its own guard (now after it); "enforced by storage" overclaimed — the index stops
double-assignment but not the suppress-vs-assign race, so both verbs now lock the
full twin-row set in canonical order (S-1); the suppression-clear rejection had no
verb to live in (now `clear_suppression`, S-6); the tombstone's shape for all-channel
`opt_out` and intake re-application events are pinned (S-6); the digest banner could
silence itself on a zero-hit night (synthesized house delivery, plan Phase 3); and
the `partners` CLI couldn't create partner #2 (upsert). Plus FR-11 joins the PRD
amendment list and the explicit-count override is pinned to bypass cap as well as
floor — expiry, not the cap, carries the anti-hoarding load (§5, S-3).*

*Revision 7 (2026-08-01) deletes the twin-row stratum — the fold revisions 4–6
scheduled for themselves. The grain merge made `phone_e164` unique across non-seed
contacts (dev-verified: zero shared phones), so one row IS one phone and the machinery
that defended against twins is **unconstructible — its fixtures cannot even be
inserted**. Deleted: S-1's shared-phone exclusivity gate and its `shared phone held
elsewhere` shortfall cause; the twin-row-set locking discipline (plain candidate-row
locking remains); S-6/S-9's write fan-out to rows sharing a phone (writes land on the
one row and the gates read it); S-8's `contact_by_phone` assigned-row tie-break (the
lookup now returns one row or none); S-10's phone-twin won gate. What SURVIVES,
deliberately: the **suppression tombstone** — it defends against
CCPA-delete-then-re-ingest resurrection, which phone-uniqueness does not touch — the
**exclusivity index on assigned rows** (one line of DDL, now belt-and-suspenders under
the grain index), and the *rationale* that voice facts attach to the number and the
human behind it — now satisfied by construction rather than by fan-out. One honest
carve-out: the grain index exempts seed rows (`is_seed = false`), so a seed could in
principle share a phone with a real row — today seeds are 0 on dev and hold no real
phones, they are excluded from the assignable pool by their own gate, and if seeds
ever gain real phones `contact_by_phone` needs a seed filter; recorded here so that
author finds it. Counts refreshed throughout (102,431 → **100,444**; callable 83,975 →
**81,988**). Also folded in per the partner-report plan (its R1): four columns on
`partners` — `sales_rep_id`, `partner_code`, `last_report_at`, `last_export_at` — and
the `feed_watermarks` table ride migration `0009` (§7), and the partner registration
runbook is carried in the implementation plan's Phase 1.*

---

## 1. Problem

The Sales Partner Program already hands leads to partners — Step 11 gives each new
partner **25 leads** from the contact database, Step 14 has "Friday: assign leads,"
and Step 12 sorts partners into *more leads* / *coach* / *remove lead access*. All of
it runs by hand: a founder exports rows into a per-partner Google Sheet.

That stopgap fails in five specific ways once more than one partner exists:

1. **No record of who holds what.** The spine has no idea a contact is being worked.
   Two partners can be given the same contractor; the same contractor can be called
   twice by two people from the same company.
2. **Suppression cannot reach an exported sheet.** FR-8 requires opt-outs to be honored
   instantly, permanently, irreversibly. A contact who opts out after export keeps
   getting called, and nothing in the system knows.
3. **Assignments never expire.** A partner who goes quiet in week 3 — the statistically
   likely outcome — keeps their rows forever. Contacts rot in a spreadsheet nobody
   opens, invisible and unreclaimable.
4. **The nudge routing it was built for is dead.** `contacts.owner` exists and
   `judgment/digest.py` routes owner-addressed nudges (`Recipient.DEAL_OWNER` rules)
   to it, but nothing writes it.
5. **Nothing scrubs a Do Not Call registry.** 81,988 phone numbers pulled from a state
   licensing database, dialed cold by a commission-only contractor, with no scrub step
   anywhere in the design and no internal do-not-call list. §6.

**The dead-writer finding (verified 2026-07-25).** Migration
`0004.add-contact-owner.sql` added `contacts.owner text not null default 'young'`.
`judgment/digest.py:69-71` reads it to decide which founder receives a nudge. No verb
in `service/` sets it. Every one of the 100,444 contacts is `owner='young'` and always
will be, so the partner branch of nudge routing has never executed. The test suite is
green. **This is the same shape as the activation-writer hole** recorded in
`decisions.md` and `technical-debt.md` TD-2: a column read by live logic, one value
forever, no test failing. Assume the class exists elsewhere and audit for it rather than
treating this as a one-off. (It did exist elsewhere: TD-10, found during this review —
no nudge is delivered to anyone, by anyone, today.)

## 2. Thesis

Assignment is a **loan of a small batch, not a grant of a territory.** The spine
records who holds which contacts and until when; batches are sized to what a person can
actually dial; unworked batches return to the pool automatically. Refill is the reward
for working the list, and asking for a refill is the activity signal — so the system
learns who is working without building an activity-reporting inflow.

A proven partner graduates to a rule-based territory. That is a later feature, and it
should not be built before a partner has earned one.

## 3. Non-goals

- **Not a partner CRM.** Call outcomes, dispositions, and notes stay in the partner's
  own sheet at v1. The spine records *custody*, not activity. Partner performance is
  measured at the sale (§8), not by reported effort.
- **Not commission tracking.** That lives in `nmc_sales_attribution` on the Medusa side
  and is a separate system with its own referral-code registry.
- **Not territory management.** No geographic carve-outs, no exclusivity, no rule-based
  auto-claiming of new intake. Named as the graduation path (§9), deliberately unbuilt.
- **Not self-serve.** Partners do not log into the mail engine. A founder assigns;
  the partner receives an export. No partner-facing auth, ever, at this scale.
- **Not a new outreach channel.** This feature moves *custody* of contacts. It sends
  nothing. Cold SMS to list contacts remains structurally impossible (PRD §4).

## 4. Actors

**Young** — owns the mail channel and the database. Assigns batches, reclaims, watches
for hoarding. Wants this to cost him minutes on a Friday.

**John (Sales Partner)** — signed. Independent contractor, commission-only, manually
dialing B2B voice from his own phone. Wants a list he can work without wondering whether
someone else is calling the same contractor. Has no login and never sees the system.

**Partners 2–5** — expected within the 60-day phase. This count is what justifies
building the feature rather than continuing with spreadsheets: at one partner the manual
path is cheaper, at five it is not, and the machinery has to exist before the fourth
arrives rather than during.

Note the program boundary: this feature belongs to the **Sales Partner Program**
(`/us/sales-partners`, cold B2B voice). It does **not** apply to the Referral Partner
Program, whose terms ban cold outreach outright. `partnership-program.md` is explicit
that the two programs must never share rules or a terms document — a contact assigned
under this feature must never be described as affiliate-referred.

## 5. Sizing — why batches, not 10,000

Ground Rule 4 mandates manual dialing: no autodialers, no prerecorded messages, no
texting. That fixes the throughput ceiling.

| Input | Figure |
|---|---|
| Manual dials/day, full-time cold caller | 40–60 |
| Attempts before retiring a B2B contact (industry standard) | 4–6 |
| Unique contacts worked/day, full-time | ~10–15 |
| 6 months of working days | ~125 |
| **Contacts a full-time partner can work in 6 months** | **~1,250–1,875** |
| **Same, for a commission-only part-timer (realistic)** | **~600–900** |

Step 11's own number agrees: 25 leads/week × 26 weeks ≈ 650.

A 10,000-contact / 6-month assignment is therefore **many times what one partner can
touch — 5–8× the full-time figure, 11–17× the realistic part-timer.** Measured against the database (prod, read-only, 2026-07-25):

| Source | Contacts | With phone |
|---|---:|---:|
| `cslb-ca` | 84,072 | 83,975 |
| `fbn-ca-2026` | 18,359 | **0** |
| **Total** | **102,431** | **83,975** |

*(Pre-grain figures, kept as the measurement of record. Post-grain — the merge folded
3,772 twin rows into 1,785 phone-unique survivors — the totals are **100,444**
contacts / **81,988** callable, dev-verified 2026-08-01. The sizing argument is
unchanged.)*

FBN records carry no phone numbers at all, so the *callable* universe is 81,988.
A 10,000 grant locks **~12% of every callable contact NeverMissCall owns** behind one
unproven commission rep for half a year.

That is the classic failure mode of oversized territory grants: **hoarding**. The rep
cherry-picks the easy few hundred, the remaining ~9,600 rot untouched, and no one else
can be given them. The marketing spend that bought that data sits frozen in a
spreadsheet.

### Batch size is a function of the partner's hours

Rather than picking 250 or 500 by feel, ask one question at onboarding — **how many
hours a week will you dial?** — and derive the batch from it. The table above gives the
conversion: 10–15 unique contacts worked per 8-hour day is **~1.5 contacts per hour**.

**Batch ≈ 12 × weekly hours** (that is, eight weeks of capacity at 1.5/hour), rounded to
the nearest 50, floor 100, cap 500:

| Weekly hours | Contacts/week | 8-week capacity | **Batch** |
|---:|---:|---:|---:|
| 10 | ~15 | 120 | **100** |
| 20 | ~30 | 240 | **250** |
| 30 | ~45 | 360 | **350** |
| 40 | ~60 | 480 | **500** |

Eight weeks of capacity against a 90-day expiry leaves roughly five weeks of margin: the
partner works the batch down and requests a refill well before anything expires, and a
batch that *does* expire is unambiguously unworked rather than merely slow. This is also
where revision 1's 250–500 recommendation came from — it is the 20-to-40-hour band, now
derived instead of asserted.

**Expiry stays fixed at 90 days for everyone.** Batch size is the only per-partner knob;
expiry is a single global constant. That preserves S-3's one-lever property — two
per-partner dials would recreate the tuning problem the ceiling was dropped to avoid.

**Self-correcting.** The stated hours are a claim, and the refill request (S-3) is the
measurement: refills arriving early mean capacity was underestimated and the next batch
grows; a batch expiring unworked means it was overestimated and the next one shrinks. No
activity reporting required — the thesis in §2 doing its job.

**Recommended parameters (v1):** batch per the table above, protected **90 days**,
refilled on request when worked down. Both belong in `config/params.py` alongside the
judgment parameters, not in prose. Expiry — not a holdings ceiling — carries the
anti-hoarding load; see S-3.

### Amendment (2026-08-05): the day-30 activity checkpoint

Ratified with the operator (decisions.md 2026-08-05). The 90-day expiry stays the
single clock; the checkpoint adds **visibility at day 30, never an auto-reclaim**.
A batch older than `batch_checkpoint_days` (30, in `config/params.py`) whose
contacts show **no spine-observable activity since assignment** — no inbound
events, no notes, no `signup.completed` — surfaces as a judgment-rule hit in the
operator digest and as a line in the partner report. The operator decides:
coach, reclaim, or wait. The S-7 principle is why this is soft: the spine
observes callers and closes, never the partner's dialing effort, and absence of
evidence is not proof of neglect. Crediting is unaffected by the checkpoint or
by expiry — the Medusa attribution row decides at close time (first credit wins
if partners ever conflict; operator adjudicates). Area codes are
partner-**requested** on the existing subscription ladder (`derive_area_codes`
is the recommendation engine, no longer the default assignment); everything else
in this section stands.

**The Step 11 trial batch goes through the system too (revision 4).** A new partner's
25-lead trial is a first-class `assign_batch` call with an explicit count — the floor
of 100 **and the cap of 500** apply to *derived* batches, not to explicit founder
overrides (revision 6: the cap is a sizing default, not the anti-hoarding control —
expiry carries that load per S-3, and an oversized explicit grant is a founder
judgment made with eyes open) — so trial
custody is recorded from day one rather than recreating §1's unrecorded-sheet problem
for every partner after John. Step 12's day-7 sort is then a manual judgment over the
partner's own sheet, outside the spine, by design (§3): at day 7 there are no sales
and no refill signal yet, and the spine has nothing to say. `partnership-program.md`
still describes the older mechanics (a holdings ceiling, 250–500 fixed batches) and
is amended alongside this design's approval — the amendment list is in the
implementation plan's Phase 0.

## 6. Do Not Call compliance

Revision 1 omitted this entirely. It is the only part of the feature whose failure mode
is not a bad metric.

### What applies

**The FTC's business-to-business exemption is real.** 16 CFR § 310.6(b)(7) exempts
"telephone calls between a telemarketer and any business to induce the purchase of goods
or services… by the business" from the Telemarketing Sales Rule, including its
do-not-call provisions. Calling a plumbing company's business line to sell it software
is squarely inside it.

**The exemption does not travel to the other regime.** The FCC's rules
(47 CFR § 64.1200) protect *residential telephone subscribers* under the TCPA, and the
FCC **presumes wireless subscribers who register on the national registry to be
residential**. The TCPA carries an accessible private right of action; the TSR's is
practically out of reach (15 U.S.C. § 6104 requires ≥ $50,000 in actual damages). The
realistic exposure is therefore not an FTC action but a private TCPA claim — and note
the DNC private action (47 U.S.C. § 227(c)(5)) requires **more than one** call within
12 months by or on behalf of the same seller, a threshold §5's own playbook of 4–6
attempts per contact guarantees is met. The design's process arms the claim; only the
scrub disarms it.

**That is precisely the shape of this list.** CSLB licensees are heavily sole
proprietors whose listed "business" number is a personal cell. A registered cell, dialed
cold, is a call the FTC exemption arguably permits and the TCPA arguably does not — and
the answer turns on facts about *that number*, which no list discloses.

**California adds no second registry — but it adds a second enforcer.** CA retired its
state list and merged into the national registry, so a federal scrub is sufficient for
state compliance; the list is CA-only today, so there is exactly one registry to scrub.
Note that California enforces against the *national* list under its own law: B&P Code
§ 17592 prohibits soliciting registered numbers, and **§ 17593** supplies the remedies
— AG/DA/city-attorney civil actions at FTC-level penalties, while the called party's
own remedy is small-claims injunctive relief (up to $1,000 for further solicitations
received **within 30 days after service** of the initial injunction). CA also defines list currency as three months —
the federal 31-day rule is stricter, so one scrub cadence satisfies both regimes,
which is one more reason the scrub is structural rather than optional.

**Access and safe harbor.** Registration at `telemarketing.donotcall.gov` yields a
Subscription Account Number (requires an EIN). The portal serves per-area-code **full
lists and change lists** for download, and an organization accessing the registry *on
behalf of a client* may need to identify that client — directly relevant to the
seller-of-record question parked for counsel (Q6). The first **5 area codes are free**;
beyond that the FY2026 fee is **$82 per area code per year**, capped at $22,626 for all
area codes. The § 310.4(b)(3) safe harbor requires calling against a registry version
**no more than 31 days old**, plus written procedures, training, and an internal
entity-specific do-not-call list.

**The paper prongs have owners too.** The scrub (S-9) and the internal list (S-6)
satisfy the mechanical prongs, but the safe harbor also expects **written procedures
and trained callers**, and neither falls out of code. Deliverables, named in §10
step 2: a one-page written dialing procedure (scrub cadence, the internal do-not-call
list, what a caller does the moment a contact asks to be removed, calling hours) and a
signed acknowledgment of it in the partner agreement — which is the training record at
this scale. Registration itself is an operational prerequisite with lead time: a
Subscription Account Number at `telemarketing.donotcall.gov` requires NMC's EIN and
must exist before the first scrub can run. Whether NMC or the dialing contractor is the
seller/telemarketer of record on that registration belongs in the Q6 counsel hour.
And the SAN is not a one-time act: **subscriptions run 12 months and must be renewed**
(renewal opens **30 days before expiry** with an email notice — there is no
September window; that was a conflation with the October 1 fee year. Calendar it
from the SAN purchase date). An expired SAN stops
`dnc_refresh` cold — the same drain-not-stale failure mode as a dead job, caught by
the same staleness nudge (S-9), but worth a calendar entry rather than a discovery.

### The number that decides the design

Area-code distribution over the canonical CSLB list (83,975 phones, measured
2026-07-26 — pre-grain; the merge trimmed the universe to 81,988 without moving any
percentage materially, and Phase 0's recorded script re-derives the set regardless):

| Scope | Area codes | Contacts covered | Annual fee |
|---|---:|---:|---:|
| Free tier | 5 | 24,824 (29.6%) | **$0** |
| Top 10 | 10 | 42,304 (50.4%) | $410 |
| Top 20 | 20 | 69,293 (82.5%) | $1,230 |
| Top 25 | 25 | 78,516 (93.5%) | $1,640 |
| **Everything** | **334** | 83,975 | **$22,626** (capped) |

**334 distinct area codes**, not California's ~38 — licensees list out-of-state and
mobile numbers from everywhere. Scrubbing the whole database is a $22,626/year decision.
Scrubbing only the subscribed area codes is a $0–$410 one, and it falls directly out
of the batch model: **the subscription — not the assignment — bounds the scrub.**
(Precision, revision 5: the scrub covers every contact in subscribed codes, assigned
or not, because the 31-day freshness gate demands a warm assignable pool — roughly
15.8–17.7k contacts on a 21-day cycle (re-measured on dev, revision 7 — 15,825 on
the 747 set, 17,744 on the 661 set), ~750–850 checks/day, on the order of **300k
`contact.dnc_checked` events/year**. That dwarfs every other event type, so the
recompute and timeline readers exclude the type — see the implementation plan.)

### Area codes follow the partner, not the list

Subscribing the five *most numerous* area codes would buy 818, 714, 916, 760 and 805 —
the Valley, Orange County, Sacramento, the desert and Ventura. Four disconnected regions,
and no cold caller works four regions. **The free five are chosen by where the partner
calls**, which means a base address and a radius.

Measured against the list (2026-07-26), a ~20-mile radius around the existing Chatsworth
seed address:

| | |
|---|---:|
| Callable contacts in radius | **6,168** |
| Distinct area codes among them | 81 |
| Covered by the top 5 (818, 805, 310, 323, 747) | **5,593 — 90.7%** |
| Annual fee | **$0** |

⚠️ **These figures are disputed and must be re-derived before subscribing (revisions
4–5).** Two independent re-measurements — both Census ZCTA-centroid methods with the
method pinned — now agree against this table: **661** (Santa Clarita, directly north
of Chatsworth) belongs in the top five at roughly 3× the volume of **747**, at every
radius from 10 to 25 miles, and neither reproduces the 6,168 in-radius total nor the
90.7% coverage (both get ~7,200 / ~89% at 20 mi; caveat: ~5,400 statewide rows have
ZIPs absent from the ZCTA gazetteer). The original method was never recorded, so the
table's numbers cannot be re-derived as they stand. The *principle* (area codes
follow the partner's radius; the free tier suffices) survives under all three
measurements; the *specific set* decides which contacts are silently unassignable —
statewide, 661 puts ~2,000 more contacts in scope than 747 — so the subscription
list is produced by a **recorded, re-runnable script** at Phase 0, not taken from
this table.

The free tier holds with room to spare: ~5,600–6,400 covered contacts (whichever
measurement prevails) is roughly 3× what a full-time partner works in six months
(§5's table), and 8× a realistic part-timer's ~700 — so a 10-mile radius would still
cover a part-time partner comfortably. The
81-code
long tail is the cell-phone-registered-elsewhere effect; those ~575 contacts are simply
not assignable until someone pays $82 to reach them, which is the visible priced
decision this design wants rather than a silent gap.

### Design

1. **Assignment does no network I/O.** `assign_batch` is a pure database filter:
   subscribed area code, `dnc_registry = false`, and `dnc_checked_at` within 31 days.
   Fast, transactional, and safe to retry.
2. **Freshness comes from a maintenance job, not from assignment.** A scheduled
   `dnc_refresh` re-scrubs contacts in subscribed area codes whose check is older than
   **21 days** — a 10-day margin under the 31-day safe-harbor limit. The FTC publishes
   downloadable per-area-code files, so this is a bulk file diff, not per-number API
   calls. Details in S-9.
3. **The job failing drains the pool rather than staling it.** Because assignment filters
   on freshness, a `dnc_refresh` that stops running makes contacts progressively
   *unassignable* — assignment reports the shortfall and names the cause. The 31-day rule
   cannot be broken by forgetting to run something; it can only stop work, loudly.
4. **Two distinct facts, two distinct columns.** `dnc_registry` is a **scrub result** —
   external, refreshed, and legitimately cleared when a number leaves the registry.
   `do_not_call` is a **suppression** — human-authored, permanent, and the
   entity-specific list the safe harbor requires. Neither may reach the contact-level
   `SUPPRESSED` stage, because that stage gates mail. Full model in S-6.
5. **Record the scrub.** A `contact.dnc_checked` event carrying the registry version, so
   "were we compliant on the day of that call?" is answerable from history rather than
   asserted.

### Amendment (2026-09-13): freshness is the list's age, not the check's

Item 3's guarantee — "the 31-day rule cannot be broken by forgetting to run
something" — held while every scrub used a same-day download. Architecture B
(partner-supplied snapshots, 2026-09-10) broke it: the scrub judges each code
against its newest accepted snapshot of any age and stamps `dnc_checked_at` with
the time of the check, so a code whose uploads stopped kept passing item 1's
filter on an ever-older list, and S-9's staleness nudge (which read check age)
never fired.

The safe harbor counts the list: a registry version "obtained from the Commission
no more than thirty-one (31) days prior to the date any call is made"
(§ 310.4(b)(3)(iv)). So, from `d440dae`:

1. Item 1's filter adds: the verdict's snapshot — `contacts.dnc_snapshot_id` →
   `dnc_snapshots.version_date`, written by `record_snapshot` from the FTC's own
   filename, never from the uploader — is ≤ 31 days old, counted on the UTC date
   (ahead of every US zone, so an error is strict). Export applies the same test.
   A contact with no linked snapshot (the legacy single-registry path) keeps the
   check-age rule.
2. S-9's staleness nudge reads, per code, the older of the newest check and the
   newest accepted snapshot.

Item 3 holds again, now for uploads as well as the scrub: a code whose uploads
stop drains once its list passes 31 days, loudly. Under Architecture B, S-9's
"downloads the current registry files" reads "consumes the snapshots uploaded to
the Worker" (`scripts/daily-run.sh` since `6579cc0`).

### Calling hours

The TSR restricts outbound telemarketing calls to **8:00 a.m.–9:00 p.m. in the called
party's local time**, and several states impose narrower windows. This is moot today —
the list is CA-only, the partners are CA-based, and one timezone covers both ends of the
call — so no code enforces it and none needs to.

It stops being moot the moment intake adds another state, which FR-1 explicitly
anticipates ("other states will arrive in other formats"). At that point the calling
window becomes a real constraint on a partner-facing export, the contact's timezone must
be derived from its address rather than assumed, and this section needs revisiting
alongside whatever the second state's own telemarketing statute requires. Noted here so
the first out-of-state batch does not go out on the assumption that CA rules travelled
with it.

### The open legal question

Whether these specific calls qualify for the B2B exemption, and how to treat CSLB
numbers that are plainly cells, is a question for a lawyer — worth an hour of one before
John dials. The design above is deliberately built to be correct either way, since it
scrubs regardless of whether the exemption applies.

## 7. User stories

Written from the actor's situation. Acceptance criteria are concrete enough to become
tests; each carries its risk tier per `CLAUDE.md` § MOST IMPORTANT RULE.

**Two invariants govern every story that touches ownership:**

- **Data invariant — a contact has at most one owner at any instant.** Assignment is
  exclusive. The derived owner-at-time function (S-8) is therefore a step function over
  the event stream, never a set.
- **Code invariant — `owner` has exactly one writer, and that writer emits.** Six
  stories change ownership — S-1 (assign), S-4 (expire), S-5 (reclaim), S-6
  (suppression removal), S-9 (registry hit removal), S-10 (won termination) — and all
  six route through a single internal
  `set_owner(contact_id, new_owner, reason, actor)` that writes the column and appends
  the event in one transaction. Any path that updates `owner` without an event silently
  corrupts every historical readout spanning it (§12). Worth a test asserting it
  directly.

**Taxonomy extension.** `domain/taxonomy.py` is a closed frozenset. This feature adds
six types — `contact.assigned`, `contact.assignment_expired`, `contact.reclaimed`,
`contact.dnc_checked`, `contact.suppressed`, `contact.suppression_cleared` — all
deliberate additions to `EVENT_TYPES`, which the module supports by design. S-8's
acceptance test depends on the first three existing and S-6's on the last two. The
existing `contact.opt_out` stays as the all-channel case. Note that `note.partner`
**already exists** in the taxonomy and is currently unused.

**The custody data model (pinned in revision 3).** Four structural facts the stories
below assume, stated once so implementation does not resolve them ad hoc:

- **`partners` is where partner facts live.** `id` (surrogate), `name`, `status`
  (`active`/`inactive` — Step 12's "remove lead access" needs a way to retire a row
  without deleting its history), **nudge channel and address** (`channel` +
  `channel_address` — S-7's recipient → channel map is a column here, not a config
  file), base address, radius, and stated weekly hours (§5). The house account is a
  row like any other. **`status = inactive` gates assignment (pinned revision 7,
  review finding):** `assign_batch` errors loudly on an inactive partner — Step 12's
  "remove lead access" means exactly that — while `reclaim` and the expiry job still
  operate on an inactive partner's holdings (you reclaim FROM the retired, never
  assign TO them). **Four report/feed columns ride the same migration (revision 7,
  from the partner-report plan's R1):** `sales_rep_id bigint null` (the main-site
  roster back-reference; null for the house row), `partner_code text null unique`
  (the close feed's correlation key — the operator stamps it at partner creation),
  `last_report_at timestamptz null` (the report watermark; null = heartbeat fires on
  the first nightly), `last_export_at timestamptz null` (stamped by `export_batch`,
  S-2's "your last export" source). **`feed_watermarks` also lands in `0009`** (per-feed
  watermark row; the close feed's `since` bound reads it — the contract's §2/§8).
- **Expiry lives on the batch, in exactly one place.** `assignment_batches` — S-1's
  idempotency anchor — carries `partner_id`, the client key, requested and delivered
  counts, `expires_at`, actor, and created-at. A contact points at its batch
  (`contacts.assignment_batch_id`, nullable). S-4's nightly job is a join against
  batches past expiry; no second *mutable* copy of the date exists. (S-8 stamps the
  expiry into each `contact.assigned` payload — an immutable snapshot, safe today
  because no verb extends an expiry; the day an extend-expiry verb is proposed, it
  must reconcile the batch date with the stamped events or S-8's `owner_at` and the
  expiry job will disagree. Revision 5, stated so that verb's author finds it.)
- **"Assigned" means the batch pointer is set.** Every contact has an owner — all
  100,444 rows say the house account — so ownership alone cannot define assignment.
  Unassigned = owned by the house row with a null batch pointer. Assignment sets both;
  expiry, reclaim, suppression removal and won-termination clear the pointer and
  return the owner to the house row, through `set_owner` like everything else.
  **Event-type mapping, pinned:** assignment emits `contact.assigned`; the nightly
  expiry step alone emits `contact.assignment_expired`; every other return to the
  house — reclaim, voice suppression, `dnc_registry` hit, won-termination — emits
  `contact.reclaimed` with the reason in the payload. `contact.assigned` opens a
  custody interval; `contact.assignment_expired` and `contact.reclaimed` close one —
  and the stamped expiry closes the *attribution* interval even before either
  arrives (S-8's two derivations).
- **`contacts.owner` becomes `owner_id`,** a foreign key to `partners` (S-11);
  the migration backfills 0004's `'young'` default to the house row's id. The new
  compliance columns from S-6/S-9 — `do_not_call`, `dnc_registry`, `dnc_checked_at`,
  `address_undeliverable` — land on `contacts`. Subscribed area codes are org-level
  facts (the SAN account is NMC's, not a partner's) and get their own small table,
  not a column on `partners`.

---

**S-1 — Assign a batch** 🟡
*It's Friday. John has worked his list down and wants more. Young wants this done before
coffee, without opening a SQL client.*

- Given an audience rule and a count, `assign_batch` transfers exactly that many
  unassigned, callable, unsuppressed contacts to a named partner. Batch size comes from
  the partner's stated hours (§5), not from a number typed each time.
- **The audience rule is the selection; the gates are the floor; the order is
  deterministic.** Which contacts fill a batch is decided by the rule (trade,
  geography — the same grammar waves use), never by the database's whim: within the
  eligible pool, selection follows a stable deterministic order, because "whatever
  the cursor returns first" is the same arbitrary-`fetchone()` shape S-8 bans in
  attribution. The partner's base address and radius inform *which area codes are
  subscribed* (§6) and *what rule Young writes* — they are not themselves gates; the
  org-level subscription set is the compliance floor. With one partner the two are
  identical; the day a second partner's radius is disjoint, Q7 reopens and
  per-partner scoping is decided there.
- The verb also accepts an **explicit contact-id list** instead of a rule, which is what
  makes the one-time cutover in §10 possible without hand-editing rows.
- Contacts with `phone_e164 is null` are never assigned (excludes all 18,359 FBN rows).
- Contacts already assigned to anyone — including the same partner — are never
  double-assigned (the data invariant above).
- **Assignment exclusivity per phone is now given by storage** (revision 7): the grain
  merge made `phone_e164` unique across non-seed contacts (`contacts_phone_unique`),
  so one row is one phone and the revision-4–6 shared-phone gate — with its
  `shared phone held elsewhere` shortfall cause — is deleted as unconstructible.
  Two partners can no longer be handed the same human through different rows, by
  construction rather than by gate.
- Contacts suppressed on the voice channel are never assigned: the row's own
  `do_not_call` bars it (one row per phone — S-6).
- Contacts with `dnc_registry` set are never assigned (§6) — the scrub writes the
  flag on the row (S-9).
- Contacts in an unsubscribed area code are never assigned, and the shortfall says so
  rather than silently narrowing the pool (§6).
- Contacts whose `dnc_checked_at` is older than 31 days are not assignable. Assignment
  does not scrub them — that is S-9's job — it simply passes over them, so the verb makes
  no network call and stays transactional.
- Contacts already converted are never assigned (S-10): the row's own `won` stage
  bars it permanently. (The revision-4 phone-twin variant of this gate is deleted —
  a customer's number no longer exists under a second row id.)
- **Contacts in a live response thread are never assigned.** The assignable pool is
  stage `prospect`, `in_sequence`, or `lost`; `responded` and `in_conversation` are
  excluded — a contractor who hit the card's coded URL yesterday and is
  mid-conversation on the demo line must not be handed to a partner as a cold call
  tonight (the S-10 failure in miniature). A declared-lost conversation is honest
  phone work and stays in the pool. The gate reads `stage_snapshot`, and the honest
  width of the race window is three things stacked (revision 5), not "same-day":
  **nightly recompute latency** (≥ 24h); **the PostHog feed being unconfigured
  today** (keys uncollected — web responses reach the spine only when that changes);
  and **TD-1's phone blindness** (a demo-line call is invisible until hand-stamped —
  unbounded). `hot_response` routing to the owner (S-7) narrows only the slice the
  spine actually saw, and only for never-before-nudged contacts. The procedural
  mitigation is therefore part of the Friday ritual: **hand-stamp any known-hot
  contacts before running `assign_batch`.** (Revision 3; §11 Q11; honest width
  revision 5.)
- The verb is idempotent under retry. Because "N unassigned contacts" is inherently
  non-deterministic in *which* contacts, idempotency is anchored on a client-supplied
  key written to an `assignment_batch` row before any contact moves — **one
  transaction; "before" is statement order, not a separate commit** (a crash between
  two commits would leave an empty batch whose retry forever returns an empty
  receipt). The batch row stores the **request verbatim** (rule or id-list, count —
  as a hash for the mismatch check and as data for the receipt); a retry with
  the same key returns the original batch rather than selecting a fresh one.
- **Exclusivity is enforced by storage, not by SELECT-gates (revision 5; simplified
  revision 7).** Gates are filters; two concurrent calls can both pass one. The grain
  index (`contacts_phone_unique`) already gives one row per phone in the assignable
  domain; the feature's own partial unique index — one *assigned* row per
  `phone_e164` — is retained as one line of belt-and-suspenders DDL. The
  suppress-vs-assign race collapses to a single-row story: `suppress()` and
  `assign_batch` now touch the SAME row, so **both verbs `select … for update` the
  candidate rows (in id order) before evaluating gates** — ordinary row locking
  serializes them; the twin-row-set locking discipline of revision 6 is deleted with
  the twins. The race remains a named test fixture, and a concurrent index collision
  aborts the verb loudly (retry-able) rather than degrading into partial assignment.
- Assignment writes an append-only event (`contact.assigned`) per contact, carrying
  partner, expiry, actor, **and the batch id** — the link that survives the pointer
  being cleared at release, without which neither the retry receipt nor S-8's
  batch-aware queries can be reconstructed. **Every** owner change emits — see the
  code invariant.
- Requesting more contacts than the pool holds assigns what exists and reports the
  shortfall, broken down by cause (no phone, suppressed, converted, unsubscribed area code,
  already assigned, mid-funnel, stale DNC check). It does not silently under-deliver.
- **Assignment does not alter wave audiences.** `resolve_audience` is unchanged, and an
  assigned contact keeps receiving drops 2 and 3 (decided 2026-07-25, §11 Q1). This is a
  deliberate choice, not an oversight — a future change that filters partner-owned
  contacts out of audiences must go back through that decision first.

---

**S-2 — Receive the list** 🟡
*John needs 300 rows in the sheet he already works from. He has no login and will not
get one.*

- Export produces one row per assigned contact with name, business, phone, address,
  trade, and expiry date.
- Export is **generated fresh on every pull and is stale the instant it lands** in the
  partner's sheet. It is not a live view and must not be described as one; the residual
  risk that follows is S-6's.
- The export carries the expiry date and the generation timestamp in visible columns, so
  the partner can see both the clock and the file's age without being told.
- Rows whose DNC check is older than 31 days are **excluded from the export and
  reported as shortfall by cause** — the same degradation pattern as S-1, not an
  all-or-nothing refusal. Revision 2 had the export refuse entirely if *any* row was
  stale, which meant one row a partial `dnc_refresh` missed would lock John out of 299
  compliant ones. A holding gone entirely stale renders an empty export that names the
  dead `dnc_refresh` job. What the export never does is render a stale number as
  dialable. (Revision 3.)

---

**S-3 — Refill** 🟡
*John has called through most of his 300 and asks for more. That request is the only
activity signal the system gets, and it should be treated as one.*

- Refill is `assign_batch` again — no separate verb.
- The `assignment_batch` row (S-1's idempotency anchor) **is** the record of the
  request — partner, timestamp, requested count, delivered count. "Partners who asked
  for more, and when" is a query over those rows; no new event type is needed for it.
- **There is no holdings ceiling.** Revision 1 proposed one (1,000 unexpired) as the
  anti-hoarding mechanism; it is dropped. §3 deliberately refuses to track activity, so
  a ceiling can only count *unexpired holdings* — a proxy that punishes the productive
  partner. Someone working 300 contacts in six weeks and refilling on schedule
  accumulates holdings faster than the hoarder who asks once and goes quiet, whose batch
  expires and returns itself. Expiry is the better mechanism because it self-clears and
  needs no number anyone has to guess. If hoarding shows up anyway, shorten expiry —
  one lever, not two.

---

**S-4 — Expiry returns contacts to the pool** 🟡
*John went quiet in week 3, as most commission-only reps do. Nobody remembers he was
holding 300 plumbers.*

- A nightly job returns every assignment past its expiry to `owner='young'`.
- Return writes a `contact.assignment_expired` event; the contact becomes assignable
  again immediately.
- Expiry is silent and automatic — it produces no nudge and requires no founder
  decision. Reclaim is the default, not the exception.
- Expiry now carries the anti-hoarding load alone (S-3), which makes the 90-day
  parameter the one number worth revisiting after the first partner cycle.

---

**S-5 — Reclaim early** 🟡
*Step 12 sorts a partner as Inactive: "remove lead access." Today that means nothing —
the sheet is already in their hands.*

- `reclaim` returns a named partner's entire holding to the pool in one call.
- Reclaim is recorded with actor and reason.
- Reclaimed contacts are immediately assignable to someone else.
- Reclaim targets a partner **id**, not a name string (S-11).

---

**S-6 — Suppression crosses the boundary** 🔴
*A contractor tells John to lose his number. Under FR-8 that must be instant,
permanent, and irreversible — but it currently lands in a Google Sheet, if anywhere.*

- A `do_not_call` suppression exists alongside `do_not_mail` / `do_not_text`, is
  human-authored, permanent, and survives recompute (FR-7 — §11 Q4, closed yes). This
  is the entity-specific internal do-not-call list the safe harbor requires (§6).
- Setting it immediately removes the contact from its assignment and bars future
  assignment. That removal is an owner change and emits like any other.
- The partner-facing export excludes voice-suppressed contacts on every regeneration.
- **Known limit, stated plainly:** a row already pasted into a partner's sheet cannot
  be recalled by software. The mitigation is procedural — the partner agreement
  requires re-pulling the export before each calling session, and export freshness is
  visible in the file (S-2). This is a real residual risk, not a solved problem, and it
  is the strongest argument for eventually replacing sheet-export with a
  partner-facing view. The same re-pull rule is also what retires **expired and
  reclaimed** rows — a fresh export contains only current holdings, so without it §1's
  double-dial failure recurs through a retained sheet the moment a batch expires and
  its contacts are reassigned to partner #2. The partner agreement states both cases,
  not just suppression. (Revision 3.)

**The per-channel model.** Suppression is not one verdict but one per channel, because
the channels are not interchangeable — and the current code collapses them.

A single contact-level "suppressed" verdict cannot answer the question that matters —
*suppressed from what?* Today
`suppress()` (`service/contacts.py:340`) appends `contact.opt_out` **for every reason**,
putting the actual reason in a payload nobody reads; `is_suppressed()`
(`derivation/rules.py:64`) then returns true on the event type alone, on
`flags.do_not_mail`, or on two returned pieces; and `_audience_where` excludes that stage
from every wave unconditionally.

So adding `"do_not_call"` to the accepted-reasons tuple — the shortest path to shipping
S-6, one tiny tuple edit — would drop the contact out of **all future mail**. A contractor
who tells John to stop calling stops receiving postcards, with no error, no failing test,
and no symptom beyond a wave denominator quietly shrinking. The same collapse runs the
other way once assignment ships: a contact suppressed for mail, or whose postcard bounced
twice, becomes unassignable to a partner whose phone number is perfectly good.

**One flag per channel, plus one that is not a flag at all:**

| Column | Channel blocked | Authored by | Permanence |
|---|---|---|---|
| `do_not_mail` | mail | human | permanent, irreversible |
| `do_not_text` | sms | caller (STOP) | permanent, irreversible |
| `do_not_call` | voice | human — the entity-specific DNC list (§6) | permanent, irreversible — **new** |
| `dnc_registry` | voice | external registry scrub | **clearable** by a later scrub — **new** |
| `address_undeliverable` | mail | derived (2+ returned pieces) | until the address is corrected |

`dnc_registry` is deliberately outside the `do_not_*` family. It records what the registry
said, not what a person asked for, so folding it in would force a choice between breaking
FR-8's irreversibility and being unable to honor a delisting.

`address_undeliverable`'s "until the address is corrected" is honest about intent, not
about tooling: no address-correction verb exists and none ships with this feature. Until
one does, the flag is permanent in practice, and a bare `contact.suppression_cleared`
against it is rejected like the other non-clearable columns — the clear path is an
address change, not an eraser.

**Voice facts are phone facts — now true by construction (revision 4; simplified
revision 7).** The do-not-call request, the registry listing, and the customer
relationship all attach to the *number and the human behind it*, not to a CSLB row.
Revisions 4–6 honored that with write fan-out and phone-scoped gates because the list
was not phone-unique; the grain merge made it so (one non-seed row per phone), and the
fan-out machinery is deleted. What remains:

- `do_not_call` is written on the row the human named (one authored fact, one event) —
  and that row is the phone. Setting it removes the row from its assignment if it
  holds one, and the removal emits.
- `dnc_registry` is written on the row — the registry lists numbers, and the row IS
  the number. The gate stays a simple column test (S-9).
- The won/converted gate reads the row's own stage (S-1) — a customer's number no
  longer has twins to leak back into the pool.
- **CCPA deletion does not delete the suppression obligation — on any channel.**
  FR-8's hard-delete removes the row — and with it row-scoped suppressions, which a
  later CSLB re-ingest would resurrect as a clean, contactable contact (`list_key`
  dedupe checks only *existing* rows). The resurrection defeats `do_not_call` and
  `do_not_mail`/`opt_out` alike, so the **suppression tombstone** covers every
  permanent channel: keyed on `phone_e164` *and* `list_key` (either may be null),
  carrying the channel and reason — a fact retained solely in order to keep honoring
  the request, the standard and permitted resolution. **Its writer is `suppress()`
  itself (revision 5** — revision 4 specified the table and, in the document that
  keeps finding dead writers, no writer): every permanent suppression inserts its
  tombstone row in the same transaction as the flag and event. The assignment and
  export gates consult it by phone; **`load_list` consults it by `list_key` and
  phone at intake** and re-applies the suppression columns to any re-ingested row.
  Tombstone rows are **per channel** — an all-channel `opt_out` writes three (mail,
  sms, voice) — and intake re-application **emits** `contact.suppressed
  {source: intake, reason: tombstone}` per re-applied channel, keeping the writer
  discipline intact (revision 6).
  Honestly noted: FR-8's delete verb is itself unbuilt today — the tombstone defends
  against a path that does not yet exist, which is the right time to build the
  defense.

**Four rules follow, all load-bearing:**

- **`SUPPRESSED` keeps its name and loses its reach.** The derived stage means *dead on
  every channel*, which is `opt_out` and nothing else. It stays useful to the pipeline
  view and the judgment rules; it stops being a channel gate. Nothing else feeds it.
- **Each channel gates on its own column — and the narrowed stage stays as backstop.**
  Mail already does the right thing — `_audience_where` filters `c.do_not_mail =
  false`, and that clause is correct; today's `stage_snapshot <> 'suppressed'` beside
  it leaks because the stage over-reaches. Once the stage narrows to `opt_out`, that
  clause stops leaking and is **kept**: an opt-out *event* can exist without its
  columns (verified — `record_note` accepts any taxonomy type, so a human note of
  type `contact.opt_out` writes the event and no flags), and the stage clause is the
  only thing that would still exclude such a contact from mail. Columns are the gate;
  the stage is the belt-and-suspenders against event-only opt-outs. Assignment gates
  on `do_not_call = false and dnc_registry = false` plus its stage gate (S-1).
- **Returned mail moves out of the stage.** Two bounced pieces is an address problem, so
  it sets `address_undeliverable` and blocks mail only. This is wrong today; voice merely
  makes it visible. A knock-on to state, not hide: contacts leaving `SUPPRESSED` return
  to their real stages, where the stage-filtered judgment rules (`hot_response` on
  `responded`, `quiet_reengage` on `in_conversation`, `lost_aging` on both) can see
  them again. That is intended — their phones were never the problem — but it is a
  behavior change the migration report quantifies.
- **Clearing is permitted only where the table says clearable — and the rejection
  has a verb to live in (revision 6).** `clear_suppression(contact_id, channel)` is
  the single public write path for `contact.suppression_cleared`: it rejects the
  permanent channels and is what the scrub's delisting path calls internally for
  `dnc_registry`. Without a named verb, "rejected at the write" was enforced by
  nothing — a bare `ingest_event` of the type would succeed, since ingestion
  validates taxonomy, not column semantics. FR-8's irreversibility physically lives
  in this verb.

**Writer discipline, same as `owner`.** Each suppression is a stored authored fact *and*
an event (`contact.suppressed` carrying `{channel, reason, source}`), written atomically
by one verb. `suppress()` must stop hardcoding `contact.opt_out` as the type, or the
derivation can never tell the reasons apart no matter what the payload says. A flag set
without its event is the same corruption as an owner change without one. That rule
reaches intake too (revision 5): `load_list` sets `do_not_mail` from the CSV with no
event today — going forward it emits `contact.suppressed {channel: mail, source:
intake}` per flagged row (row-dedupe on `list_key` keeps it idempotent); rows loaded
before the split are flag-only and stay legal because mail gates on the column, not
the event.

**And the historical stream is already ambiguous.** Every `suppress()` call to date —
do-not-mail requests included — emitted `contact.opt_out` with the real reason only in
the payload. Events are append-only, so the narrowed derivation must disambiguate on
`payload.reason` for historical `contact.opt_out` events: reason `do_not_mail` means
mail-only, not dead-on-every-channel. Keying on the event type alone would keep every
past do-not-mail request fully `SUPPRESSED` — silently defeating the split for exactly
the contacts it exists to fix. (Verified in code during the revision 3 review; the
implementation plan carries the fixture test.)

---

**S-7 — Nudges reach the right founder** 🟡
*A contact John owns responds to a postcard. The nudge should go to John, not Young.*

Revision 1 marked this 🟢 with "no new code," on the premise that the dead branch goes
live the moment S-1 ships. **That premise is false.** It becomes correctly *computed*,
not delivered:

- **Nothing delivers a nudge to anyone today** (`technical-debt.md` TD-10).
  `seams/sender.py` holds a Protocol and no implementation; the only implementation
  anywhere is `FakeSender` (`seams/fakes.py`, imported only by tests);
  `jobs/nightly_cli.py` calls `run_nightly(feeds,
  since)` with no sender argument. A sender must exist before this story means anything.
- `digest.py:_resolve_recipient` returns the raw owner value and `Sender.send` takes it
  as an opaque key, so the sender needs a **recipient → channel map**. An unmapped
  partner is a silent drop of exactly the nudges this feature exists to route — it must
  fail loudly instead.
- PRD §12 open question 3 (partner's channel — SMS or email) is therefore a **build
  dependency**, not a preference to collect later. Ask John before this ships.
- The nudge budget is already per-recipient (`counts[founder] < params.nudge_budget`,
  `digest.py:101`), so a partner gets their own five. **Confirmed in code**
  (revision 3 verification pass); the acceptance test asserts the behavior anyway.
- A branch nothing has ever executed going live is not a 🟢 change. Retiered 🟡, and
  the verification is the deliverable.

**Which nudges may route to a partner.** §3 keeps partner activity out of the spine and
§8 attributes performance at the sale, so the system cannot tell whether John is already
working a contact. Therefore:

- **Event-driven nudges route to the partner** — `hot_response` and anything else
  triggered by something the spine *observed* (a coded-URL visit, a page visit, a
  delivery failure). These are sound: the fact is real and the owner is the right
  recipient.
- **Inactivity-driven nudges do not** — `quiet_reengage`, `lost_aging` and their kin
  infer from *absence* of evidence, and for a partner-owned contact absence of evidence
  in the spine is not absence of activity. Routing them to John means telling him his
  own contacts are neglected on the strength of data the system admits it doesn't have,
  on a channel whose stated success metric is staying trusted (PRD §8).

**The split is a reclassification, not new machinery** (verified in code, revision 3).
Every rule already declares `Recipient.YOUNG` or `Recipient.DEAL_OWNER`
(`judgment/protocol.py`), and two inactivity rules are misclassified for a world with
partners: `quiet_reengage` and `lost_aging` are `DEAL_OWNER` today and must flip to
`YOUNG`. `hot_response` and `demo_no_show` stay `DEAL_OWNER` — both fire on observed
events. The flip is a no-op while every contact is house-owned. *(Ordering amended
2026-08-01, operator decision: the flip now lands at the project plan's Stage C1,
AFTER S-1 goes live — safe only because Phase 4 ships the sender-None recording
guard, under which no partner-recipient nudge is recorded while the sender is
unreal, so the un-flipped classification cannot misroute a recorded nudge. The flip
lands with the real sender. SECOND amendment, operator decision at the Stage C
gate 2026-08-01: the guard is KEPT permanently, not removed — after C1 a
senderless nightly means misconfigured SMTP, which is exactly the state where
burning a partner's hot_response would hurt; the guard costs nothing when a
sender is present.)*

---

**S-8 — The wave readout tells the truth about who earned the response** 🟡
*A contractor gets drop 2 on Tuesday and a call from John on Wednesday, then books a
demo. The readout must not quietly hand mail the credit.*

- FR-6 attribution precedence is **unchanged** (mailer code → thread → exact phone).
  This story adds reporting segmentation, not a new matching rule.
- **The exact-phone step is deterministic by construction (revision 7).** The
  revision-4 tie-break requirement is deleted: `contact_by_phone`
  (`service/ingestion.py:152`) now resolves to exactly one non-seed row or none —
  the grain index guarantees it — so a bare lookup no longer attributes to an
  arbitrary row, and no `order by` machinery is needed. (Seed carve-out: if seeds
  ever gain real phones, this lookup needs a seed filter — revision-7 header note.)
- The wave readout reports partner-owned and mail-only responses as separate lines,
  each with its own response rate and cost-per-response.
- **Owner-at-response-time is derived from the assignment event stream**
  (`contact.assigned` / `contact.assignment_expired` / `contact.reclaimed`) — never
  read from `contacts.owner`.
- **Genesis rule:** absent any assignment event for a contact, the derived owner is
  `young`. 100,444 contacts have no assignment events and every historical response
  predates the first one, so this clause is what makes the derivation total. Without it
  stated, the first implementation either fails on the empty stream or quietly falls
  back to `contacts.owner` — the exact thing this story forbids.
- **Custody intervals close on the stamped expiry, not the expiry job's clock.** The
  interval opens at `contact.assigned` and closes at the *earliest* of the expiry
  carried in that event or an explicit end event (`contact.reclaimed`, suppression
  removal, won-termination). The `contact.assignment_expired` event confirms the
  return; its own timestamp trails real expiry by however late the nightly job ran,
  and a job down for a week must not credit the partner a week of responses.
  (Revision 3.)
- **Two derivations, named, deliberately unequal in one window (revision 4).**
  `current_owner(events)` closes only on *end events* and is what the `owner_id`
  column must always equal — the single-writer invariant. `owner_at(t, events)` is
  bounded additionally by the stamped expiry and is what readouts and this story use.
  Between a stamped expiry and the late job run that confirms it, they *disagree by
  design*: the column still says partner, attribution already says house. A test pins
  that disagreement as intended; without the two names, the first implementation
  collapses them and one invariant silently breaks.
- Re-running an old wave's readout after an assignment has expired produces the
  **same numbers it produced originally.** This is the acceptance test that matters;
  everything else in this story is in service of it.

> **Why this is the non-obvious part.** `contacts.owner` is mutable current state —
> assignments expire (S-4) and get reclaimed (S-5). Joining responses to `owner` as it
> stands at *report* time means a contact assigned to John in March, expired back to
> Young in June, has its March response silently re-credited to Young. The wave's
> readout would answer differently depending on when you run it. Deriving from the
> event stream sits in FR-7's grain (versioned pure functions over full history,
> recomputable) and makes readouts reproducible. Full reasoning, and the two rejected
> alternatives, in `decisions.md` (2026-07-25).

---

**S-9 — The DNC scrub is a maintenance programme** 🔴
*Before John dials anyone, the numbers he holds have been checked against the registry
within the last 31 days — without anyone having remembered to do it.*

- Area codes are subscribed explicitly, chosen by the partner's base address and radius
  (§6); only subscribed area codes are assignable.
- A scheduled `dnc_refresh` job downloads the current registry files for every subscribed
  area code, records the **registry version**, and re-scrubs any contact in those area
  codes whose `dnc_checked_at` is older than **21 days**. The 10-day margin under the
  31-day limit means a couple of missed runs cost nothing.
- Priority order within a run: **assigned contacts first** (those are the numbers
  actually being dialed), then the assignable pool. A run that cannot finish leaves the
  pool stale rather than the live batches.
- Each scrub emits `contact.dnc_checked` with the registry version, making "were we
  compliant on the day of that call?" answerable from history rather than asserted.
- A registry hit sets `dnc_registry` on the row (one row per phone — S-6), removes it
  from its assignment if it holds one, and is clearable by a later scrub (S-6's
  channel table) — it is a scrub result, not a request.
- **The clearing has a writer too** (revision 4 — this was the dead-writer shape,
  found in the very feature that keeps finding it): a scrub of a contact whose number
  is *absent* from the current registry version clears `dnc_registry` on the row and
  emits `contact.suppression_cleared`, idempotency-keyed on contact + registry
  version like the check event. Without this, "clearable by a later scrub" was a
  claim with no code path.
- **Staleness is visible, not silent.** Because assignment and export both filter on the
  31-day window, a job that stops running drains the assignable pool instead of quietly
  serving stale numbers. A judgment rule nudges when the newest registry version ages
  past a threshold, so the drain is noticed before it bites.
- Job-first, like every other job in this system: cron/CLI, never a web route.
- 🔴 because it is a compliance gate, not because it is complex — plan first, approve
  explicitly, per `CLAUDE.md` § MOST IMPORTANT RULE.

---

**S-10 — Assignment ends when the contact converts** 🟡
*John closes a contractor. That contact must not expire back into the pool for the next
partner to cold-call as a prospect.*

- A contact reaching the `won` derived stage leaves its assignment permanently and
  never re-enters the assignable pool.
- Termination is an owner change like any other and emits accordingly.
- The close is what attributes the partner's performance — via
  `nmc_sales_attribution` on the Medusa side (§3, §8), correlated at app level across
  the two-database boundary, never joined.

**The gap this story cannot close by itself: the spine may never see a partner-driven
close.** `won` derives from `signup.completed`, which today arrives only through the
PostHog feed on the coded landing funnel. A contractor John closes may sign up carrying
his typed partner code and **no mailer code** — a path the spine has no inflow for. And
the manual fallback is barred by existing code: `record_outcome`'s own contract says
*"'won' is never declared manually."* Left as-is, the exact conversions this story exists
for are invisible: John closes a contractor, no `signup.completed` reaches the spine,
`won` never derives, the assignment expires on schedule — **and partner #2 is handed a
paying customer to cold-call.** That is the worst outcome this feature can produce short
of a compliance claim.

The close-visibility inflow is therefore part of this story's acceptance, not an
afterthought. Two honest options, decision open (§11 Q10):

1. **Correlate from Medusa** — a periodic app-level pass matches partner-coded closes in
   `nmc_sales_attribution` to spine contacts (exact phone / explicit pick), ingesting a
   `signup.completed` with the correlation as source. Same correlation the co-op credit
   ledger already needs (§9); two databases, never a join. **Double-count guard,
   binding:** a close through the coded landing funnel *already* emits
   `signup.completed` from the PostHog feed, and `decisions.md` (2026-07-12) rules
   that no second source may emit the same fact — the `(source, external_id)` key
   cannot collapse events from different sources. The correlation pass therefore
   ingests only when the contact has **no existing `signup.completed` from any
   source**; otherwise every signup-count, cost-per-customer denominator, and the
   leaning activation auto-insert would see the same close twice, silently.
   **The guard must cover both orderings — and the PostHog side cannot carry it
   (revision 5):** the contact-side check protects only the PostHog-first ordering,
   and the *reverse* ordering is today's production default — PostHog keys are not
   configured, so the feed is skipped every night, and the day they are added its
   30-day lookback replays closes the correlation already ingested. Revision 4 put a
   symmetric check in the PostHog mapping, which is unimplementable: PostHog events
   are ingested **contact-less** (attribution deliberately happens downstream in
   `resolve_orphans`), so at mapping time there is no contact to check. The fix moves
   to the consumers — stated honestly (revision 6): **no signup-counting consumer
   exists today** (TD-3 — cost-per-customer is not computable; the activation
   auto-insert is an unbuilt leaning), so there is nothing to deduplicate yet. The
   binding requirements within this feature's scope are the ones that are real:
   `won` derivation is idempotent (any `signup.completed` — already true), S-10's
   termination fires once, and **wave attribution prefers the PostHog event**, which
   alone carries the mailer-code → piece → wave linkage — the correlation event is
   phone-matched and attributes no piece. Whenever a signup-counting consumer *is*
   built (TD-3's fix, the activation writer), it must deduplicate per contact —
   recorded here so its author inherits the rule. And the correlation
   resolves its phone match through `contact_by_phone`, which since the grain merge
   returns exactly one non-seed row or none (S-8, revision 7) — the
   wrong-twin failure mode revision 4 guarded here is unconstructible.
2. **A founder close-stamp** — relax "never declared manually" for this one case: a UI
   action recording the close as a sourced human event. Consistent with the hand-stamped
   posture already chosen for phone response and leaning for activation
   (`decisions.md`), and honest at 3–5 partners' volume.

Either way, the acceptance test is the scenario above: a close that arrives with no
mailer code must still end the assignment before expiry would have.

---

**S-11 — Partners are rows, not strings** 🟡
*"Reclaim everything from John" should not be a string match.*

- A `partners` table with a surrogate id; `contacts.owner` and every assignment event
  reference the id.
- Closes §11 Q5 in the affirmative. Revision 1 framed free text as a convenience
  question; it is a data-integrity one. Once S-8 derives historical attribution from an
  event stream keyed by owner, "John" / "john" / "John S." silently splits a partner's
  history and corrupts the very readouts S-8 exists to protect. Cheap now, unfixable
  cheaply later.
- The founders are rows too, so `young` stops being a magic string. Where S-4 and S-8
  say ownership returns to or defaults to `young`, read it as *Young's partner row* —
  the house account — not the literal string. Migration 0004's `default 'young'` is
  backfilled to that id.

## 8. Where partner performance is measured

Not here. §3 keeps dispositions out of the spine, and no partner-facing inflow exists or
is planned — John has no login, and asking a commission-only rep to maintain a second
system is how the data goes stale.

Performance is measured at **the sale**: a close carries the partner's referral code
into `nmc_sales_attribution` (Medusa DB), and that is the number that decides refills,
coaching, and Step 12's sort. Between assignment and close, the only signal the spine
gets is the refill request (S-3).

**Every partner has a code, and the code — not the assignment — is what pays.**
Assignment confers custody, not commission. If John converts a contact he was assigned,
his code goes on the sale and he is credited normally.

### The typed code is the evidence

The subscriber enters the partner's code at checkout, and it carries a discount so there
is a reason to bother. That discount is not only an incentive: **a code can only be typed
by someone who heard it, so the typed code is proof the partner made contact.**

That matters more than it looks. Crediting a partner for any conversion of a contact they
merely *hold* would pay for hoarding — the failure mode §5 exists to prevent — and
distinguishing "worked it" from "sat on it" is exactly what §3 refuses to collect. The
typed code supplies that evidence from the buyer instead of from the partner's own
self-report, which is strictly more trustworthy and costs no new inflow. It resolves the
fairness problem without building disposition capture.

### Therefore the postcard's response path stays partner-uncoded

The card's response path — the printed per-piece **mailer code and its coded URL**
(wave-1 creatives print **no QR**, and the pipeline has no per-piece QR generation;
`creative/w1-6x9-plumber-loss-demo/variant.json`) — carries the mailer code and **not**
the owning partner's code, even when the contact is partner-owned. Pre-filling it would
convert an earned credit into an automatic one: a partner holding 500 contacts would get
their code onto 500 cards and collect on whatever mail converts, having made no calls.
It would also destroy the signal above — an auto-applied code proves nothing.

Partner-*generated* collateral is a narrower matter than revision 3 stated. What
`decisions.md` (2026-07-25) actually carves out is **warm follow-up mail to a contact
the partner has actually spoken with** — non-NMC-branded, no barred claims; it does not
mention leave-behinds, business cards, or a coded-URL facility. **No partner coded-URL
generator exists in the mail engine** and none is scheduled; if partner collateral is
wanted, that facility is a new, deliberately-unbuilt item to be decided on its own.
What stays barred is partner-originated *cold* mail (Ground Rule 7).

### Two ledgers, both true

A contact who receives a postcard, talks to John, and types his code at checkout is
simultaneously a **mail-driven response** in the wave readout and a **partner-credited
sale** in the commission ledger. These are different questions and both answers are
correct.

- **Marketing attribution** — unchanged. FR-6 precedence (mailer code → thread → exact
  phone) decides which piece, variant and wave earned the response. S-8 segments it by
  owner-at-response-time.
- **Commission attribution** — an explicitly typed partner code **wins**, because it is
  an affirmative human act naming the partner. Absent one, no partner is credited.

The only real failure mode here is trying to make one number answer both questions.

### What it costs, and one thing to watch

The discount stacks onto partner costs that already stack. `decisions.md` puts commission
plus bonus plus co-op mail credit at **53% of year-one gross on Solo**; one month free
adds ~$99 and takes it to ~62%, a 10% year-one discount to ~63.5%. Solo is already the
tier flagged as carrying the heaviest load and the likeliest to churn, so keep the
discount modest or first-month-only — and if the goal is purely to get the code typed, a
non-margin incentive (priority onboarding, a setup call) may buy the same behavior for
nothing.

**Watch for code leakage.** If the attribution code and the discount code are one string,
it eventually reaches a coupon aggregator, and strangers' signups start crediting a
partner and draining margin. At 3–5 partners in a niche B2B product the risk is small but
real; the cheap guard is a non-obvious code plus an alert on anomalous redemption volume
per partner, rather than a second code nobody will remember.

### The residual, stated up front rather than discovered

A contact John holds can still convert without him: follow the card's coded URL, or call the demo
line — the card's *primary* CTA — and sign up carrying a mailer code and no partner code.
John made four calls and earns nothing. That is the correct outcome, since the response
came through the company channel, but it is exactly the surprise that sours a commission
relationship in month two. It belongs in the partner agreement, not in a discovery.

It also makes S-7 economically load-bearing rather than a convenience. The `hot_response`
nudge routed to John is what lets him phone a contact who has just raised a hand and get
his code onto the deal before the self-serve path closes it. Routing that nudge to Young
instead does not merely misfile a notification; it moves the commission. Note that this
mitigation is **inoperative until TD-10 is fixed** — no nudge reaches anyone today
(and under the sender-None recording guard, a partner's `hot_response` is held and
re-fires nightly rather than burned — delayed until Stage C1, not lost).

**The consequence is deliberate and worth stating:** the system is blind to partner
activity for the entire pre-sale period. That blindness is affordable for reporting —
custody plus closes answers the questions that matter — but it is *not* affordable for
nudges, which is why S-7 routes only event-driven nudges to partners and keeps
inactivity-driven ones with Young.

## 9. Earned expansions (not v1)

Both of these unlock on proven production. Neither should be built before a partner has
earned one — machinery for zero proven partners is speculative complexity, and the batch
model is the honest test of whether anyone works the list at all.

**Territory.** A **rule** (trade + county) rather than a list, so it auto-claims new
contacts as intake adds them; 6–12 months; held against an activity floor that reverts
it. This is where the original 6-month instinct belongs — earned, and defined as a
predicate. Note that a territory rule makes DNC subscription scope a standing cost
rather than a per-batch one (§6).

**Co-op mail credit.** Partners never send their own cold mail (Ground Rule 7); mail
stays a company channel because an uncoded partner postcard is indistinguishable from
an NMC postcard at the response end and would contaminate the variant test running in
the same mailboxes. Instead a partner accrues piece-credit from closes — 250 / 500 /
1,000 for Solo / Growth / Power — and spends it on drops **into contacts they already
own**, through the normal wave approval gate. Two dependencies on this feature: the
audience for such a drop is exactly the partner's assignment (S-1), and the balance
requires correlating closes in `nmc_sales_attribution` (Medusa DB) with the mail-engine
DB — separate databases, so app-level correlation, never a join. Full reasoning and the
rejected alternatives (MDF, 50/50 cost-share) in `decisions.md` and
`partnership-program.md` § Co-op Mail Credit.

## 10. Build sequence

Ordered so the compliance and integrity floor lands before the batching convenience.
The first group is worth shipping even if the rest slips.

**Cutover — supersede John's sheet, do not migrate it.** John holds 25 leads in a Google
Sheet with no record in the spine. The instinct is to backfill them as assignments, and
it is the wrong one: their custody history was never recorded, so any events written now
would be invented, and S-8's genesis rule ("no assignment events → the house account")
would be reading a fiction for every wave that spans them.

Instead, on the day S-1 goes live, Young issues John a proper first batch using
`assign_batch`'s explicit id-list form (S-1), pinning in whichever of the 25 are still
live and unsuppressed, and the sheet is void from that date. The id-list form passes
through every S-1 gate — any of the 25 outside the subscribed area codes or failing the
scrub simply fall out, reported as shortfall, which is correct: those numbers were about
to become legally undialable anyway. The first `contact.assigned` events then mark the
true start of custody, and every readout before them is correct rather than
approximately correct. One manual act, once, and no migration code.

1. **`set_owner` + the three ownership event types + the `partners` table** (S-11, the
   code invariant). `contact.assigned` / `contact.assignment_expired` /
   `contact.reclaimed`; `contact.dnc_checked` arrives with step 2. Nothing else is safe
   until `owner` has exactly one emitting writer.
2. **The per-channel suppression split + `do_not_call` + the DNC scrub + area-code
   subscription** (S-6, S-9). Compliance floor. Note this is larger than "add a column":
   it narrows `SUPPRESSED` to `opt_out`, moves returned-mail to
   `address_undeliverable`, stops `suppress()` hardcoding `contact.opt_out`, and needs a
   test per row of S-6's table. Doing it *before* step 4 is what keeps a compliance flag
   from silently deleting the mail audience. Two non-code deliverables gate this step:
   the **SAN registration** at `telemarketing.donotcall.gov` (needs NMC's EIN; has lead
   time; no SAN, no scrub) and the **safe harbor's paper prongs** — the written dialing
   procedure and its signed acknowledgment in the partner agreement (§6). 🔴 — plan and
   approve before code.
3. **A sender implementation with a recipient → channel map** (TD-10). Until this
   exists, S-7 is unobservable and the nudge channel is fiction. Ask John his channel
   first — knowing the cost asymmetry: email rides existing SMTP credentials; no
   arbitrary-send NMC SMS API exists today, so "SMS" is new integration work
   (implementation plan, Phase 0). *(Sequencing amended 2026-08-01, operator
   decision: the sender is DEFERRED to the project plan's Stage C1 — the report
   composer and the sender ship together so neither reproduces TD-10 with a partner
   as the victim. Step 4 may therefore land first, made safe by its sender-None
   recording guard: with no real sender, `digest.run` records nothing for non-house
   recipients, so partner nudges are held and re-fire nightly rather than burned.
   This inverts this list's original 3-before-4 order deliberately.)*
4. **`assign_batch` / export / refill / expiry / reclaim** (S-1 … S-5, S-10) — plus
   the sender-None recording guard above. The
   feature proper.
5. **Owner-at-response-time derivation and readout segmentation** (S-8). Last because
   it reads the event stream the earlier steps produce, and its acceptance test needs
   real assignment history to be meaningful.

## 11. Open questions

1. ~~**Does an assigned contact stay in the mail cadence?**~~ — **DECIDED 2026-07-25:
   stays in, flagged** (see `decisions.md`). Mail and partner voice run concurrently;
   the readout segments partner-owned responses rather than crediting mail outright.
   Rejected: removing assigned contacts from audiences (forfeits the multi-touch lift
   and breaks cross-wave denominator comparability — attribution is fixable by
   reporting, lost lift is not).
2. ~~**Attribution integrity.**~~ — **RESOLVED by Q1.** FR-6 precedence is unchanged;
   the fix is reporting segmentation (S-8), and it requires owner-at-response-time to
   be derived from the assignment event stream rather than read from `contacts.owner`.
   The residual risk moves to event-stream completeness (§12).
3. ~~**Batch ceiling per partner.**~~ — **DROPPED 2026-07-26.** No ceiling; expiry is
   the sole anti-hoarding mechanism. Reasoning in S-3.
4. ~~**Does `do_not_call` belong in the same recompute-surviving set as
   `do_not_mail`/`do_not_text`?**~~ — **YES, closed 2026-07-26.** It is human-authored
   and permanent, and it is the entity-specific list the DNC safe harbor requires (§6).
5. ~~**Partner identity — free text or a `partners` table?**~~ — **`partners` table,
   closed 2026-07-26.** S-11.
6. **Does the B2B exemption cover these calls, and how should plainly-cellular CSLB
   numbers be treated?** Open, and the one question here needing outside counsel (§6).
   The design is built to be correct either way. Also in that hour: who is the
   seller/telemarketer of record on the SAN registration — NMC, or the independent
   contractor dialing on its behalf (§6, revision 3).
7. **Which area codes to subscribe.** — **Closed in principle** (2026-07-26: driven
   by the partner's base address and radius, not by list volume), **reopened on the
   specific set (revision 5)**: the table's free five (818/805/310/323/747) is
   disputed by two independent re-measurements that both put **661** in and **747**
   out (§6). The set ships from Phase 0's recorded script, not from this document.
   Revisit the free-tier fit when a second partner's radius is disjoint from the
   first and the union exceeds five.
8. **What radius, per partner?** ~20 miles looks comfortable on every measurement to
   date (final figures await Phase 0's script — §6); 10 would also clear a part-time
   partner's six-month capacity. Set it with the partner, and let
   coverage-within-the-free-five be the constraint that decides.
9. **How large a discount does the partner code carry, and does it stack?** Decided in
   principle (§8): the code carries a discount so the subscriber has a reason to type it,
   which is what makes it evidence of contact. The size is a pricing decision, not a
   design one, and it lands on Solo's margin where partner costs already reach 53% of
   year-one gross. First-month-only is the cheap default; a non-margin incentive may buy
   the same behavior for nothing.
10. **How does the spine learn of a partner-driven close?** (S-10.) A close carrying a
    typed partner code and no mailer code has no inflow today, and `record_outcome`
    forbids manual `won` — so without a decision here, closed customers expire back into
    the assignable pool. Options: Medusa correlation or a founder close-stamp; both in
    S-10. Must be decided before the first partner close, which is sooner than wave 2.
    Note the same blindness covers a *code-less* close (organic signup, demo line with
    no mailer code) — if Medusa correlation is chosen, it should match all closes by
    phone, not only partner-coded ones, **deduplicating against existing
    `signup.completed` events from any source first** (S-10's double-count guard;
    `decisions.md` 2026-07-12).
11. ~~**Are mid-funnel contacts assignable?**~~ — **CLOSED revision 3: no.** The
    assignable pool is `prospect` / `in_sequence` / `lost`; `responded` and
    `in_conversation` are excluded (S-1). Revision 2 excluded only `won`, which left a
    contractor mid-conversation on the demo line assignable to a partner as a cold
    call.

## 12. Risks

- **DNC exposure** → the sharpest legal risk in this document, because its downside is a
  claim rather than a bad number. Mitigated structurally: the scheduled `dnc_refresh`
  scrub (S-9), 31-day freshness as a precondition of assignment *and* export, the
  internal do-not-call list, and a recorded scrub event per contact (§6). Residual: the
  exemption question itself, which needs counsel.
- **Hoarding** → expiry is a requirement, not an option (S-3, S-4). The holdings
  ceiling was rejected as a worse instrument, not deferred.
- **Suppression latency in exported sheets** → structurally unsolvable at v1; mitigated
  procedurally and disclosed (S-2, S-6). Revisit if partner count grows.
- **Attribution bias toward mail** → settled by the 2026-07-25 decision: segmented
  reporting (S-8), not audience exclusion. The risk that remains is narrower and
  sharper — **the segmentation is only as good as the assignment event stream is
  complete.** Any code path that writes `contacts.owner` without emitting an event
  silently corrupts every historical readout that spans it. Hence the single emitting
  writer (§7) and a test that asserts it directly.
- **Nudges to a partner about contacts he has already worked** → the spine is blind to
  partner activity by design (§8). Mitigated by routing only event-driven nudges to
  partners (S-7). If partners report noise anyway, the answer is to narrow further, not
  to build disposition capture.
- **A channel suppression silently stopping the mail programme** → the sharpest
  engineering risk here, because the wrong implementation is the *cheapest* one: adding `do_not_call`
  to the accepted reasons in `suppress()` is one tiny tuple edit and would remove the
  contact from every future wave. The failure is invisible — no error, no failing test,
  just a shrinking denominator, and rates look normal because numerator and population
  shrink together. **The severe case is `dnc_registry`:** a single `dnc_refresh` run
  could set it on a large fraction of 81,988 contacts in one night, so a registry with no
  authority over postal mail would gut the mail programme overnight. Mitigated
  structurally by the per-channel column model in S-6 — only `opt_out` reaches
  `SUPPRESSED`, and each channel gates on its own column. Needs a test per row of that
  table, not one test: the matrix is the specification.
- **A partner losing a commission to the mail channel** → a contact John is working can
  convert through the card's own funnel — the coded URL or the demo line, which is the *primary*
  CTA — carrying a mailer code and no partner code (§8). Structurally unavoidable while
  both channels run on the same contact, which was the 2026-07-25 decision, and the
  incentive inverts at the margin: John's calls raise the salience of the postcard on the
  desk, so the harder he works, the more mail-attributed conversions he generates and is
  not paid for. Magnitude is real — a Solo close is **$387.60 cash** to the partner
  first-year (commission + bonus, `partnership-program.md`), **$636 counting co-op
  mail credit**; a Growth close ~$1,090 cash / ~$1,587 all-in — one basis per
  comparison, and the cash figure is what the partner feels.
  Mitigated by the typed discount code (§8), which converts a call into a
  credited sale whenever the contact acts on the conversation; by disclosure in the
  partner agreement; and by routing `hot_response` to the owner — which is why S-7 is a
  commission mechanism rather than a notification preference, and why TD-10 blocking it
  is not a cosmetic gap.
- **Paying for hoarding** → any rule that credits a partner for merely *holding* a
  contact — an auto-applied code on the card, a blanket look-back at signup — pays a
  partner who never dialed and re-creates the failure §5 was written to prevent.
  Structurally avoided by requiring the code to be typed: the credit follows evidence of
  contact, not custody. Any future change to auto-apply a partner code must come back
  through this decision.
- **A closed customer expiring back into the pool** → a partner-driven close can be
  invisible to the spine (no mailer code, no inflow, manual `won` barred), in which case
  S-10 never fires and the customer is reassigned to the next partner as a cold
  prospect (§11 Q10). Worse than a lost commission — it is NeverMissCall cold-calling
  its own subscriber. Mitigated by deciding the close-visibility inflow (S-10) before
  the first partner close, not after.
- **An engaged contact assigned as a cold prospect** → structurally avoided by S-1's
  stage gate (revision 3): `responded` and `in_conversation` never enter the assignable
  pool. The residual is snapshot staleness — the gate reads `stage_snapshot`, which is
  only as fresh as the last nightly recompute, so a response can race the gate — and
  the window's honest width (nightly latency + the unconfigured PostHog feed + TD-1's
  phone blindness), plus the Friday hand-stamp mitigation, are stated in S-1
  (revision 5).
- **A nudge channel that does not exist** → S-7 depends on TD-10 being fixed. Shipping
  assignment without a sender would produce correct routing to nobody, which reads as
  working in every test and in the database — for a partner-owned contact that means a
  recorded `nudge.sent` that permanently silences `hot_response`. Mitigated (decision
  2026-08-01) by the **sender-None recording guard** shipped with `assign_batch`:
  while no real sender exists, partner-recipient hits are neither composed nor
  recorded — they re-fire nightly until Stage C1 wires the sender. The residual is
  honest and bounded: partner nudges are DELAYED until C1, not lost; house nudges
  keep burning as today (the known TD-10 cost).
- **Program conflation** → describing this as an "affiliate" feature would import the
  wrong terms document. The word is **Sales Partner**, always compound (§4).
- **Dead-writer class** → `owner`, `activation`, and the sender seam are all read or
  called by live logic with no implementation behind them, each with a green suite.
  Three is a pattern. The deliberate audit pass in TD-2 is overdue.
