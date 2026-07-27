# Direct Marketing 101 — the mail-engine end-to-end runbook

*How a name on a purchased list becomes a tracked, attributed, followed-up response —
every step, in order, as this system actually does it. Written as a teaching document:
read it top-to-bottom once to understand the whole funnel, then use the per-step
sections as a checklist when you run a real wave. Companions: `../PRD.md` (what/why),
`decisions.md` (vendor + open questions), `e2e-journey.md` (the automated rehearsal),
`list-shapes.md` (raw list formats), `INSTALL.md`.*

*Every step below carries a **🔧 Manual today** line — the founder work the system does
**not** yet do for you, as of 2026-07-18. The outbound half (steps 1–8) is code-complete
and proven end-to-end against Lob's test env; the response half (9, 10, 13) is built
structurally but partly unwired, so it leans on manual operation until the phone feed,
the nightly cron, and a digest `Sender` land. See "Build status" below.*

---

## 0. The mental model (read this first)

Direct mail is a **loop with a long delay in the middle**. You spend money to put a
physical card in a stranger's hand, then wait days-to-weeks for a fraction of them to
respond through a *different* channel (web or phone) than the one you spent on (paper).
Everything hard about the discipline is bridging that gap: knowing which card produced
which response, at what cost, and never letting a responder fall through the wait.

This system bridges it with four ideas:

1. **A contact database is the spine.** Every fact — a name loaded, a card mailed, a
   page visited, a call taken, a signup — is an **append-only event** hung on a contact.
   Nothing is ever edited in place; state is *derived* from the event stream by pure
   functions (`derivation/rules.py`). This is what makes "recompute the whole history
   after we change a definition" a one-liner instead of a migration.

2. **The mailer code is the thread that survives the gap.** Every physical piece carries
   a unique per-piece code. That code rides the QR/URL on the card and the campaign
   phone attribution, so when a response lands weeks later it points back to the exact
   piece, variant, wave, and cost. No code, no clean attribution.

3. **Approval is a hard gate; execution is job-only.** Nothing prints without a human
   approving the *exact* thing that will fire (audience + creative, fingerprinted). The
   founder-facing web UI can *compose and approve*; it cannot *fire*. Firing happens
   through one batch job, triggered by cron/CLI or a password-gated page.

4. **AI briefs, never decides ("AI instead of CRM").** A nightly job watches the pipeline
   and taps you on the shoulder — quiet responder, hot lead, activation stall — inside a
   strict nudge budget. You do the selling; the software refuses to let a responder go
   silent.

**The pipeline at a glance** (each row is a step below). **Status:** ✅ system handles it ·
⚠️ built but partly manual · 🖐 manual by design.

| # | Step | Verb / trigger | Status | What's still on you |
|---|------|----------------|--------|---------------------|
| 1 | Intake a list | `load_list` / `POST /intake` | ✅ | acquire the list; run the adapter + load |
| 2 | Seed the founders in | `make seed-contacts` | ✅ | maintain `config/seeds.json` (rare) |
| 3 | Write creative + variant | `create_variant` / `POST /variants` | ✅ | **write the card + hypothesis** (human craft) |
| 4 | Compose a wave | `draft_wave` / `POST /waves/new` | ✅ | choose audience rule + split + date |
| 5 | Preview | `preview_audience` / approve screen | ✅ | read + sanity-check it |
| 6 | Proof | `wave_proofs` (Lob test render) | ✅ | **eyeball the PDF** (that's the point) |
| 7 | Approve | `approve_wave` / approve button | ✅ | **click approve** (the deliberate gate) |
| 8 | Drop | `run_drops` (cron/CLI or `/drops/run`) | ✅* | trigger it; *live drop never fired yet* |
| 9 | Land + track | `?r=` + QR + campaign phone | ⚠️ | **hand-enter phone response** (no NMC feed) |
| 10 | Sync response | `run_nightly` → `sync` | ⚠️ | **run the nightly** (no confirmed cron) |
| 11 | Attribute | `resolve_orphans` (precedence chain) | ✅ | work the `/orphans` queue weekly |
| 12 | Derive state | `recompute_state` | ✅ | nothing (runs inside the nightly) |
| 13 | Judge + nudge | `digest.run` (nightly) | ⚠️ | **read `/nudges`** (no push); track activation |
| 14 | Read out | conversational SQL / wave readout | 🖐 | **ask Claude Code** to write it |

Steps 1–8 are you pushing mail *out*. Steps 9–14 are signal coming back *in* and being
turned into action. The whole thing runs on Postgres 15+ with a single typed service
layer as the only write path; reads may bypass it through a read-only role.

> **Build status in one breath (2026-07-18).** The *outbound* pipeline (1–8) is real,
> tested, and ready — you could compose→proof→approve→drop wave 1 today (after the
> physical ghost wave). The *response* pipeline (9–13) is built but has **three unwired
> seams** that make it manual: **(a)** no NeverMissCall phone feed, so calls/texts to the
> campaign line aren't captured automatically; **(b)** no confirmed nightly cron, so sync +
> recompute + judgment run only when you launch them; **(c)** no digest `Sender`, so
> nudges are computed and logged but not delivered — you pull them from `/nudges`. Plus the
> `activation` table has no writer (step 13). None of these block a wave at 500-piece
> scale; each has the manual fallback spelled out in its step.

---

## 1. Intake — turn a purchased list into contacts

**What it is.** A bulk one-time load of a purchased list (CSLB contractor list; county
FBN feeds) into the `contacts` spine.

**Why it's shaped this way.** The spine must never learn a vendor's columns. Each source
format gets its own **intake adapter** (`intake/cslb_ca.py`, `intake/fbn_ca.py`) that
maps that vendor's raw columns into one *canonical* CSV shape. The generic `load_list`
verb only ever sees canonical columns, so adding a new list format is a new adapter, not
a change to the core.

**How to run it.**

```bash
# 1. Adapter: raw vendor export -> canonical CSV (filters to live/targetable rows)
uv run python -m intake.cslb_ca ../ingestion-app-1/MasterLicenseData.csv \
    --classes C36 -o /tmp/cslb.csv
# 2. Load the canonical CSV (dedupe, E.164, segment) — or upload it at POST /intake
uv run python -c "from service.contacts import load_list; \
    print(load_list('/tmp/cslb.csv', source='cslb-ca'))"
```

**What `load_list` does** (`service/contacts.py`):
- **Dedupe** on the adapter-prefixed `list_key` — both against rows already in the DB and
  within the file. Re-running the same list is safe (idempotent); duplicates are counted,
  not inserted.
- **E.164 normalize** every phone (`domain/phone.py` → `to_e164`). A number that can't be
  normalized is stored null, not guessed.
- **Segment assignment** — a deterministic default (`trade` narrowed by state, e.g.
  `c36-ca`), which you refine later. Segments are free text by design.
- **Targetability filter** — a row with neither trade nor segment is *invalid* and
  skipped (source-specific junk rules like CSLB's "no trade = junk" live in the adapter).
- **Suppression on load** — a `do_not_mail` row loads already suppressed.
- Returns an **IntakeReport**: `loaded / deduped / invalid / suppressed` counts. In the
  UI (`/intake`) the report renders after upload.

**Gotchas.** NCOA/CASS address validation is *not* done here (it needs the print seam,
which the dependency rule bars from the service layer) — it's a deferred job that stamps
`addr_validated_at`. FBN rows have no phones, so their responses can only match by mailer
code (expect orphans — see step 11).

> 🔧 **Manual today.** You acquire the raw list (purchase/export) and run the two commands
> (adapter → `load_list`), or upload the canonical CSV at `/intake`. The system does all
> parsing/dedupe/normalization. **Address hygiene is manual/deferred:** NCOA/CASS isn't
> wired, so bad addresses are only caught by Lob at submit time (a returned piece), not
> pre-flight.

---

## 2. Seed data — put the founders' own addresses in every wave

**What it is.** One or more founder addresses loaded as special `is_seed` contacts that
ride *every* wave as one extra physical piece.

**Why.** IMb/Lob tracking already tells you *when* pieces are delivered, but nothing tells
you the card **printed correctly** — right bleed, right colors, a scannable QR, legible
text. A seed piece is the only check on production print quality: the card lands in the
founder's own mailbox. Scanning your own seed's QR is also a live end-to-end attribution
test (the scan attaches to the seed contact, never counted as a real response).

**How to run it.**

```bash
# config/seeds.json (gitignored — holds real addresses; template is seeds.example.json)
make seed-contacts       # idempotent upsert; safe to re-run every deploy
```

`config/seeds.json` is **config, not a UI** — a JSON array of `{name, line1, line2, city,
state, zip}`. `ensure_seed_contacts` (`service/contacts.py`) upserts each on a derived
`list_key` (`seed-<slug>`), so a deploy/cron never duplicates a seed. Current prod seed:
NeverMissCall, 22015 Lemarsh St, Chatsworth CA.

**How seeds behave everywhere else.** `resolve_audience` appends every seed to every
wave's audience *independent of the audience rule and any `limit`* — the limit caps the
purchased list, not your own samples. Seeds are **excluded** from every response-rate
denominator, the pipeline, and the judgment job (they never respond; counting them would
deflate the rate). They *do* appear in the preview's count and cost breakdown (they fire,
so approval must show them) and their cost is real spend.

> 🔧 **Manual today.** Edit `config/seeds.json` and run `make seed-contacts` — a rare,
> one-line action (done once in prod already). Fully automated otherwise.

---

## 3. Creative & variants — the card, with its hypothesis

**What it is.** A `variant` = creative payload (front/back HTML + size) **plus a required
one-line hypothesis**. A variant without a hypothesis literally cannot be created
(`create_variant` raises `empty_hypothesis`).

**Why the hypothesis is mandatory.** The 60-day phase's success metric is
*learning-per-hour*. A card mailed without a stated bet ("pain-led beats benefit-led for
plumbers") produces a number nobody can read. The schema enforces the information-buying
posture: every card is an experiment with a written prediction you later grade (step 14).

**How to write creative.** Front/back are HTML documents rendered by Lob to a 6×9 (or
4×6) postcard. Real examples live in `creative/` (e.g. `w1-6x9-loss-math/front.html` +
`back.html`). Three tokens matter — all keyed on `{{mailer_code}}`, substituted per piece
at drop time:

```html
<!-- from creative/w1-6x9-loss-math/back.html -->
<p><strong>See it work on your own phone:</strong><br>getnevermisscall.com/?r={{mailer_code}}</p>
<p><strong>Call or text (888) 853-8575</strong></p>       <!-- the campaign phone line -->
<p>Code: {{mailer_code}}</p>                                <!-- human-readable fallback -->
```

- `getnevermisscall.com/?r={{mailer_code}}` — the **landing URL**; the `?r=` param is the
  mailer code PostHog captures (step 9). A QR encoding this same URL goes on the card.
- **(888) 853-8575** — the NMC campaign phone line (dedicated "nevermisscall" vertical:
  the product dogfooding itself as the first-contact demo). Calls/texts here become phone
  response events.
- `Code: {{mailer_code}}` — printed so a caller can read it aloud if the QR/URL is missed.

**Creating and freezing.** `POST /variants` (or `/variants` form) with `name`,
`hypothesis`, `creative` JSON. A variant is **editable only until the first wave carrying
it is approved** — after that it's *frozen* (`_is_frozen`): approval is the promise that
*this exact card* is what fires, so a revision means minting a new variant, never editing
history. (The drift guard in step 5–7 enforces the same thing within a single wave.)

> 🔧 **Manual today.** This is inherently human craft: **you write the front/back HTML and
> the one-line hypothesis.** The system stores, renders, checksums, and freezes it — it
> won't design the card for you. Author the HTML in `creative/<name>/` and paste it (or
> the JSON) into `POST /variants`.

---

## 4. Compose a wave — audience as data, not a query you run

**What it is.** A `draft` wave = a **name**, a **drop number** (which of the 3-drop
cadence), an **audience rule** (JSON filter), a **variant split** (weights), and a
**scheduled date**.

**Why the audience is stored as a rule, not a frozen list.** `draft_wave` persists the
rule as data and does *not* resolve it. Resolution happens later at preview and again at
execution, through the **same** function (`_audience_where` / `resolve_audience`), so what
you approve is exactly what fires — the two can never diverge over unchanged state.

**The audience rule grammar** (`service/waves.py`; unknown keys are *rejected*, not
ignored):

| Key | Meaning |
|-----|---------|
| `segment` | list of segments (e.g. `["c36-ca"]`) |
| `trade` | list of trades |
| `source` | list of list-sources (e.g. `["cslb-ca"]`) |
| `stage` | list of contact stages |
| `city` | case-insensitive city match |
| `zip_prefix` | ZIP bands (e.g. `["913","914"]` = SFV) |
| `not_responded_to_wave` | contacts who got a given wave's piece but haven't responded (drop-2/3 targeting) |
| `limit` | cap to a deterministic pseudo-random sample (stable between preview and drop) |

Always-on, non-negotiable clauses: `do_not_mail = false`, not `suppressed`, and
`is_seed = false` (seeds are appended separately). So a rule can never mail a suppressed
contact, even by mistake.

**How.** `POST /waves/new` (the composer form) → 303 redirect to the approve screen. The
variant split is a JSON object of `{variant_id: weight}`; weights are relative
(`{"A": 1, "B": 1}` is a 50/50 split). Assignment is deterministic per contact, so a
re-run never reshuffles who saw what. Drafts are editable (`/waves/{id}/edit`); anything
past draft is immutable — cancel and redraft.

> 🔧 **Manual today.** You make the strategic calls — **which audience rule, which variant
> split, which drop number, what date** — and submit the composer form. The system resolves
> and executes exactly what you specify; it does not choose targeting for you.

---

## 5. Preview — see the resolved reality before you commit

**What it is.** `preview_audience` resolves the rule *right now* and renders: the **total
count that will fire** (seeds included), a **breakdown** by segment and stage, an
**estimated cost**, a **10-contact sample**, the **seed line item**, and a **`state_hash`**.

**Why the `state_hash` matters.** It's a SHA-256 fingerprint of *exactly what the preview
showed* — the resolved contact-id set, the variant split, **and each variant's creative
checksum**. It rides forward to approval. If the audience *or* the creative drifts between
preview and approval, the hashes won't match and approval is refused (`stale_preview`).
This is the mechanism behind "you approve the exact thing you saw."

**Gotchas.** Seeds count toward the firing total but are held out of the segment/stage
breakdown and the sample (they're your pieces, not the audience under review). The
preview cost is an *estimate* (73¢/piece placeholder); the real per-piece cost is recorded
at drop time from Lob.

> 🔧 **Manual today.** Nothing to run — the preview generates itself on the approve screen.
> Your only job is to **read it**: does the count, the segment mix, and the cost look right
> before you commit money?

---

## 6. Proof — approve the vendor's actual print file, not your HTML

**What it is.** Before the approve button renders, the system calls Lob's **test
environment** to render one real **proof PDF per variant** in the wave (`wave_proofs`),
and embeds it inline on the approval screen.

**Why.** Your HTML preview is not what prints — Lob's renderer is. The proof is the
vendor's own final rendering of the card. You approve *that file*. It also catches the
class of failure fakes can't: a `to.name` over 40 chars (Lob 422s), malformed HTML, a
bleed problem.

**Fail-closed.** If Lob can't render, `wave_proofs` raises and **the approve button never
appears** — "no proof, nothing to approve" (FR-3). The proof runs on `LOB_TEST_API_KEY`,
so nothing prints and no money moves. (Proof PDFs render *asynchronously* — the Lob asset
URL 500s for a few seconds; the browser embed just needs a refresh.)

> 🔧 **Manual today.** The render is automatic; the **judgment is yours** — actually look
> at each variant's PDF (bleed, colors, legibility, a scannable QR). This is the human
> print-quality check the whole proof step exists for.

---

## 7. Approval — the one human gate

**What it is.** `approve_wave` records **who** approved and **when**, and flips the wave
`draft → approved`. It does **not** execute.

**What it checks** (all must pass):
- wave is still `draft`;
- variant split is non-empty and every referenced variant exists;
- `scheduled_for` is a **future** date;
- the audience resolves to **≥ 1 contact**;
- the carried `state_hash` still matches (no drift since preview — step 5).

It also stamps `approved_audience_count` — the number the drop-time drift guard compares
against (step 8).

**Where.** The `/approvals` queue, or the approve button on `/waves/{id}/approve`. This is
the *only* gate before mail becomes physical. Cancel stays valid right up until the wave
starts executing.

> 🔧 **Manual today.** By design, **a human clicks approve** — this is the deliberate gate,
> never automated. The system enforces every precondition around your click; it never
> approves on your behalf.

---

## 8. Drop — fire the wave through the print API

**What it is.** The batch job that picks up approved waves whose scheduled date has
arrived and submits each piece to Lob.

**Why execution is job-only.** `execute_wave` is deliberately **not** a routed web verb.
The web UI composes and approves; firing goes through the `run_drops` job — via cron/CLI,
or the **password-gated `/drops/run` page** (`DROP_PASSWORD`, fail-closed when unset; a
deliberate-action password beats SSH for a two-founder team). `sync`, `recompute`, and the
nightly are likewise never routed.

**How to fire.**

```bash
# CLI/cron path (as_of defaults to "today"): picks up every due approved wave
uv run python -c "from jobs.drop import run_drops; ..."   # (wire the Lob live client + date)
# or: the /drops page — enter DROP_PASSWORD + the as_of date, click Run drops
```

**What `execute_wave` guarantees** (`service/execution.py`):
- **Drift halt.** It re-resolves the audience and compares to `approved_audience_count`.
  If it drifted more than **10%**, it **halts** the wave (no pieces) and reports why —
  the list changed too much since you approved; re-preview and re-approve.
- **Per-piece mailer code.** Deterministic base32 of `sha256("{wave}:{contact}")[:10]`, so
  a resumed drop regenerates the *same* code — no orphaned codes.
- **One piece per contact per wave** — enforced by a unique `(contact_id, wave_id)`
  constraint (the hard FR-4 constraint).
- **Idempotent + resumable.** The mailer code is Lob's `Idempotency-Key`, and each piece
  row + its `piece.submitted` event are written atomically. A killed drop is just re-run
  until clean; a replay creates zero new pieces and zero new Lob postcards.
- **Real cost recorded** per piece (`LOB_COST_CENTS`, default 87¢).
- Seeds fire alongside the audience; the wave flips `executing → sent`.

> 🔧 **Manual today.** You **trigger** the drop — enter `DROP_PASSWORD` + the date on
> `/drops` and click Run (or run the job from cron/CLI). The execution itself is fully
> automated and idempotent. **Caveat (the `*`):** a real *live* drop against Lob with real
> money has **never fired** — only the Lob **test** env, via `make e2e`. The physical ghost
> wave (step 16) is the first live exercise and the go/no-go for wave 1.

---

## 9. Landing page & tracking — the code comes home

This is the far side of the delay. A recipient responds through one of **three** paths,
all carrying the mailer code:

1. **Web (QR or typed URL).** The card's QR and printed URL both point at
   `getnevermisscall.com/?r=<mailer_code>`. The landing page (a NeverMissCall demo page,
   instrumented with **PostHog**) reads the `?r=` param and stamps `mailer_code` onto every
   PostHog event. Three PostHog events map into the spine (`seams/posthog.py`):
   - `$pageview` → `page.visit`
   - `checkout_started` → `page.cta_click`
   - `landing_purchase_completed` → `signup.completed` *(a landing purchase **is** the
     signup)*
   Only events carrying a real `mailer_code` are pulled; the landing page's `unknown`
   sentinel (organic traffic) stays in PostHog to measure uncoded lift but never reaches
   the spine (it would flood the orphan queue).

2. **Phone (call or text the campaign line).** (888) 853-8575 is a dedicated NMC line under
   the "nevermisscall" vertical. Inbound calls/texts become `call.inbound` / `sms.inbound`
   events; NMC's own conversation carries thread identity for attribution.

3. **Delivery signal (Lob → us).** Real-time Lob **webhooks** (`POST /webhooks/lob`,
   HMAC-verified, fail-closed) report physical status: `postcard.processed_for_delivery` →
   `piece.delivered` (USPS never scans a card *into* the mailbox, so this is the delivery
   proxy) and `postcard.returned_to_sender` → `piece.returned`. Tracking fires in the
   **live** environment only.

**The QR is just the URL.** There's no separate QR tracking system — the QR encodes the
same `?r=<mailer_code>` URL, so a scan and a typed visit are the same event.

> 🔧 **Manual today — this is the biggest gap.** Of the three response paths, only Lob
> delivery is fully automatic:
> - **Delivery/returns (Lob):** ✅ automatic — `POST /webhooks/lob` (real-time) and the
>   nightly `LobStatusFeed` poll both land `piece.delivered` / `piece.returned`.
> - **Web (PostHog):** ⚠️ *plumbed, verify live.* `seams/posthog.py` is built and the prod
>   env has `POSTHOG_API_KEY` + `POSTHOG_PROJECT_ID` set — **but** it only works if the
>   external landing page at `getnevermisscall.com` actually reads `?r=` and stamps
>   `mailer_code` onto its PostHog events. **Confirm the landing page emits `?r=` before
>   trusting web attribution** (that page lives outside this repo).
> - **Phone (call/text the 888 line):** ❌ **not automated at all.** There is **no NMC
>   response feed** — nothing turns a call or text into a `call.inbound` / `sms.inbound` /
>   `demo.*` event. **You must hand-enter phone responders** (add a contact note, or
>   ingest the event) so they enter the pipeline. At a few-percent response on a ~500-piece
>   wave that's a handful of entries; at scale it needs the feed built.

---

## 10. Response capture & sync — nightly facts-in

**What it is.** `run_nightly` (`jobs/nightly.py`) pulls every response feed and lands each
signal as an **append-only canonical event**, idempotent under replay via
`(source, external_id)`.

**Strict order — this is a guarantee, not a convenience:**

```
sync(every feed)  ->  resolve_orphans()  ->  recompute_state()  ->  digest.run()
```

A feed failure **raises before** recompute, so the system never judges stale state ("never
recompute on a half-synced night"). Lob delivery is the exception — it arrives real-time
by webhook, not in the nightly pull. Nightly cadence is sufficient for everything
non-webhook (SR-5). The job is `jobs.nightly_cli`; it **skips a feed whose env is absent
(and says so)** and **refuses to run with zero feeds** (a nightly over nothing-new would
still mail nudges).

> 🔧 **Manual today.** The nightly exists as a CLI but **there's no confirmed cron**, so in
> practice **you run it by hand** when you want fresh state:
> ```bash
> uv run python -m jobs.nightly_cli            # 30-day lookback; --dry-run to just list feeds
> ```
> To make it automatic, install the cron line from `nightly_cli --help` on the VPS. Note it
> only pulls the feeds it has env for — today that's **Lob + PostHog, never phone** (step 9).

---

## 11. Attribution — join the response to the piece, never guess

**What it is.** `resolve_orphans` runs each unattributed event through a **strict
precedence chain** (`resolution/matcher.py`), stopping at the first success:

1. **mailer code → piece → contact** (strongest; also attributes the *piece*)
2. **thread continuity** (same conversation as an already-matched event)
3. **exact normalized phone**

**Never name, never address, never fuzzy.** A wrong attribution silently poisons response
data; an unmatched event is instead stored as an **orphan** — visible and fixable. Orphans
surface in the `/orphans` queue and are reviewed weekly (`orphan_max` = 20 is the alarm
threshold). Accept imperfection, *measure* it — that's the whole posture (calls from
unlisted numbers, shared devices, FBN's phoneless rows all land here).

> 🔧 **Manual today.** Matching is automatic (runs inside the nightly). What's on you is
> **working the `/orphans` queue** — a weekly human pass over the events that couldn't be
> matched, to attach the salvageable ones by hand.

---

## 12. Derived state — the pipeline computes itself

**What it is.** `recompute_state` rehydrates each contact's events and runs the pure
`derive_stage`, refreshing the `stage_snapshot` cache. It introduces no new fact, so it
writes no event.

**The stages** (precedence, first match wins — `derivation/rules.py`):

```
suppressed  >  won  >  lost  >  in_conversation  >  responded  >  in_sequence  >  prospect
```

- **prospect** — loaded, no piece yet.
- **in_sequence** — at least one piece mailed, no response yet.
- **responded** — an inbound signal landed *after* the first piece.
- **in_conversation** — we engaged back on a live thread.
- **won** — `signup.completed` (never declared by hand; it *derives* from the signup).
- **lost** — a human `contact.lost`; *revivable* (an inbound after the lost mark un-loses).
- **suppressed** — absorbing: `do_not_mail`, an `opt_out`, or ≥2 returned pieces.

Human-authored facts (`do_not_mail`, founder-set `next_action`) are **never** touched by
recompute — they survive it. `RULESET_VERSION` is stamped on snapshots so a recompute
under a changed definition is distinguishable from the old.

> 🔧 **Manual today.** Nothing — this is fully automatic. Its *only* dependency is that the
> nightly actually ran (step 10), since recompute rides inside it.

---

## 13. Judgment & nudges — the software taps you on the shoulder

**What it is.** The nightly judgment job (`digest.run`) runs deterministic rules over
fresh state, and where a condition fires, AI composes a **30-second action brief**
(template fallback if the model is down — delivery never depends on the model).

### What *is* a nudge?

A nudge is the system's one and only output **to you**. Everything else — intake, waves,
drops, attribution — is machinery; the nudge is the moment all that state becomes a single
sentence: *"here's a person who needs you right now, and here's what to do."* It's the "AI
instead of CRM" idea made concrete — instead of you patrolling a dashboard, the software
watches the pipeline and taps you on the shoulder.

Concretely a nudge is **three things at once** (`service/nudges.py`):
1. **An event** — `nudge.sent` in the append-only log (auditable: which rule, when, to
   whom).
2. **A `next_action` on the contact** — `record_nudge` stamps `next_action_at` +
   `next_action_note`, so the nudge *becomes* that contact's pending to-do.
3. **A line in the morning digest** — the assembled list a founder reads.

**Two tiers, deliberately split** (so a model outage can never lose a nudge):
- **Tier 1 — a Rule finds WHO/WHEN.** Pure SQL over derived state. E.g. the entire
  `hot_response` rule = *"every contact at stage `responded` with no `nudge.sent` yet."* A
  rule never decides *whether to bother you* beyond its condition.
- **Tier 2 — the composer writes WHAT.** It feeds the contact's timeline to the AI:
  *"Rule fired. Write a two-sentence brief a founder can act on in 30 seconds — who, what
  happened, what they said last, suggested move."* No AI / a failure → a deterministic
  **template brief** (`[hot_response] New responder — reply while warm — contact abc…`),
  and the digest still sends.

So a finished nudge reads like: *"Miguel at Sunrise Plumbing scanned his card and texted
the demo line twice yesterday — warm and unanswered. Call him back this morning."*

**Why "nudge," not "notification" — the discipline is the point.** A nudge channel only
works while it stays *trusted*; the instant you start ignoring it the whole system is dead
weight. So restraint is built in as a **requirement**: a **5/day budget** (overflow defers,
never piles up), **priority order** (a live lead beats a stat), a **3-day per-contact
cooldown** (broken only by a fresh inbound), **expiry not escalation** (`expire_stale_actions`
*clears* an un-acted nudge after 5 days — the list is always "true today," never a guilt
stack), **a human `next_action` wins** (the job won't overwrite your slot), and **silence
is valid** (a quiet night sends nothing).

**The rules** (`judgment/rules/`, thresholds in `config/params.py`): quiet responder
(`quiet_days`=4), hot response, demo no-show, activation stall (`stall_days`=14) /
partial, returned mail, wave anomaly (`fail_pct`=8%), pending approval, orphan events,
aging-out (`age_out_days`=30).

The discipline params live in `config/params.py` (`nudge_budget`=5, `cooldown_days`=3,
`expire_days`=5). Each nudge is delivered as **one morning digest per founder** through
NMC's own sending path; the job **grades itself monthly** (was the budget binding? did
founders act before expiry?) to catch drift.

> ⚠️ **Known gap (see `decisions.md` / `current-state.md`):** the `activation` table has
> **no writer** today, so `activation_stalled` — "the churn cliff, the single most
> valuable nudge" — can't fire yet even though the suite is green. Leaning hand-stamped
> (insert on `signup.completed` + a UI action to stamp `first_lead_at`). Don't ship the
> `signed_up_at` half alone.

> 🔧 **Manual today — two gaps.** The rules, discipline, briefs, and `nudge.sent` logging
> all run. But: **(a) no digest is delivered** — no `Sender` is wired, so `digest.run`
> computes and logs nudges but doesn't push them. **Read them yourself on `/nudges`** each
> morning instead of getting a text. **(b) `activation_stalled` can't fire** (no writer,
> above) — **track new signups → first-lead by hand** until it's built. The judgment engine
> is real; only its *delivery* and the *activation input* are manual.

---

## 14. Wave readout & analysis — grade the bet you wrote down

**What it is.** After a wave, a plain-language **readout**: segments × variants × timing
vs. response rate and cost-per-response, **quoting each variant's stated hypothesis and
grading it**. Denominators exclude seed pieces; seed cost stays in wave spend.

**How.** Ad-hoc questions are answered by AI (Claude Code) writing **SQL through a
read-only role** against the retained raw history — no new UI per question. A question
that recurs *every* wave graduates to a fixed panel; a novel one never requires new code.
This is the "no dashboard patrol" half of the founder-hour-efficiency goal.

**Why it closes the loop.** Step 3 forced you to write a prediction. Step 14 reads it back
against reality. That's the learning-per-hour engine — the entire point of the 60-day
information-buying phase.

> 🔧 **Manual today — by design.** There's no auto-generated readout; **you ask Claude Code
> a question**, it writes SQL through the read-only role and answers in prose. That's the
> intended model (no dashboard patrol), not a gap — but it *is* operator-initiated: nothing
> lands a memo in your inbox unprompted.

---

## 15. Compliance & suppression — the bright lines

- **Mail is the cold channel; SMS is the warm reply channel.** There is **no code path**
  for cold outbound SMS to the purchased list — ever. That's structural, not a policy you
  could fat-finger around.
- **Suppression is instant, permanent, one-way.** `suppress` sets the human flag *and*
  appends `contact.opt_out`; there is no unsuppress verb, and recompute preserves it. A
  `do_not_mail` request stops mail; an `opt_out` stops both channels.
- **CCPA deletion** = contact hard-delete + event anonymization (identity severed,
  aggregates preserved).
- **STOP** on SMS is honored as an opt-out.

> 🔧 **Manual today.** `suppress` (the verb behind `/contacts/{id}/suppress`) works and is
> irreversible — but **the triggers into it are manual**: a `do_not_mail` request or an SMS
> **STOP** has no automatic ingestion (STOP would arrive on the phone channel, which has no
> feed — step 9), so **you run `suppress` by hand** when one comes in. **CCPA hard-delete
> has no verb yet** — it's a manual SQL operation. The *structural* protection (no cold-SMS
> code path) needs nothing; the *reactive* suppressions are on you.

---

## 16. The ghost wave — the go/no-go before real spend

Before wave 1 mails to strangers, the whole pipeline is rehearsed twice:

1. **Automated, free:** `make e2e` walks wipe → intake → creative → wave → **real Lob test
   proof** → approve → drop → verify each postcard against Lob's API → idempotent replay.
   This is the software half — "did my change break the funnel?" (⚠️ it **wipes**
   `mailengine_dev`; re-ingest after — see `current-state.md`).
2. **Physical, ~10 real pieces to founder addresses:** the paid ghost wave. Because the
   e2e already proved the code, this validates only *paper and delivery*. An end-to-end
   pass here is the **immovable quality gate** for wave 1.

---

## 17. The manual cadence — your actual routine today

Because of the unwired seams (steps 9, 10, 13), running a live wave today means these
human touches. All are light at ~500-piece scale; each disappears when the noted seam
is built.

**Per wave (a few times over the 60 days):**
1. Acquire the list → adapter → `load_list` (step 1).
2. Write the card + hypothesis (step 3); compose the wave (step 4).
3. Read the preview (step 5); **eyeball the proof PDF** (step 6); **click approve** (step 7).
4. **Trigger the drop** on `/drops` with `DROP_PASSWORD` (step 8).

**Daily (while a wave is live):**
5. **Run the nightly** by hand — `uv run python -m jobs.nightly_cli` — unless a cron is
   installed (step 10).
6. **Read `/nudges`** for the morning's action briefs (no push yet — step 13).
7. **Hand-enter phone responders** who called/texted the 888 line (no NMC feed — step 9).
8. Act on hot responders / suppress on request (`suppress` by hand — steps 13, 15).

**Weekly:**
9. **Work the `/orphans` queue** — attach salvageable unmatched events (step 11).
10. Track new signups → first lead by hand (activation has no writer — step 13).

**Ask anytime:** "grade wave N's variants against their hypotheses" → Claude Code writes
the readout (step 14).

**Build these three to erase most of the above** (in leverage order): a **NeverMissCall
response feed** (kills #7 and auto-STOP), a **digest `Sender`** (kills #6's manual pull),
and the **nightly cron + activation writer** (kills #5 and #10).

---

## Appendix — the operator's quick reference

**Make targets** (`make help`): `up` / `down` (Postgres) · `migrate` (apply migrations as
owner) · `run` (web UI on **:8001**) · `test` (fast, offline) · `e2e` (⚠️ wipes dev DB) ·
`seed-contacts` · `lint` · `fmt` · `nuke`.

**Key web routes** (`web/api.py`, thin — one verb each): `/waves` · `/waves/new` ·
`/waves/{id}/approve` · `/approvals` · `/variants` · `/creatives` · `/contacts` ·
`/intake` · `/orphans` (+ `/orphans/resolve`) · `/pipeline` · `/activation` · `/nudges` ·
`/drops` (+ password-gated `/drops/run`) · `/webhooks/lob`.

**Judgment thresholds** (`config/params.py`): `quiet_days`=4 · `stall_days`=14 ·
`partial_days`=4 · `fail_pct`=0.08 · `resp_check_days`=10 · `lead_days`=3 ·
`age_out_days`=30 · `nudge_budget`=5 · `cooldown_days`=3 · `expire_days`=5 ·
`orphan_max`=20.

**Event taxonomy** — the full closed set (`domain/taxonomy.py`; unknown types are
*rejected*, extended only by editing `EVENT_TYPES`): `piece.submitted` · `piece.delivered`
· `piece.returned` · `page.visit` · `page.cta_click` · `call.inbound` · `call.missed` ·
`call.answered` · `sms.inbound` · `sms.outbound` · `demo.booked` · `demo.held` ·
`demo.no_show` · `signup.completed` · `note.demo_call` · `note.partner` · `note.general` ·
`contact.opt_out` · `contact.lost` · `nudge.sent`.

**Dependency rule** (SR-3): `web`/`jobs` → `service` → `derivation`/`resolution` →
`domain`. Vendor SDKs live only in `seams/`. NMC is consumed through the same feed
contract as any third party.

**Environment knobs** (`.env`): `OWNER_DATABASE_URL` / `READONLY_DATABASE_URL` ·
`WEB_PORT` · `LOB_API_KEY` (live) / `LOB_TEST_API_KEY` (proofs + e2e) · `LOB_FROM_*` ·
`LOB_COST_CENTS` · `LOB_WEBHOOK_SECRET` · `DROP_PASSWORD` · PostHog key + project id. The
test guard refuses to run against anything but `mailengine_dev`/`mailengine_test` with a
non-`live_` key — the wipe can never touch prod.
