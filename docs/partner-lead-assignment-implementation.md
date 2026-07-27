# Partner Lead Assignment — Implementation Plan

*Execution brief for `partner-lead-assignment.md` (revision 6). Read that document
first; this one sequences it. Where this plan and the design conflict, escalate — do
not resolve silently. Companions: `direct-mail-ai-data.md` (schema),
`direct-mail-ai-code-layout.md` (dependency rule), `technical-debt.md` (TD-2, TD-10),
`decisions.md`.*

*Status: **awaiting approval alongside the design doc.** Phase 2 is 🔴 (compliance +
the suppression invariant) and requires its own explicit approval before code, per
`CLAUDE.md` § MOST IMPORTANT RULE. The other phases are 🟡: the frozen acceptance
tests written at the top of each phase are the approval gate — show them, get the
nod, green them.*

---

## Executor ground rules

1. **The design document is decided (once approved).** Tables, verbs, event types,
   and the "deliberately absent" list (no partner CRM, no disposition capture, no
   holdings ceiling, no partner auth) are settled. A genuine flaw found mid-build is
   an escalation, not a patch.
2. **The dependency rule is law.** `web`/`jobs` → `service` → `derivation`/`resolution`
   → `domain`; `seams` imported only by `jobs` and `service/execution`. The DNC
   registry client is a seam; `assign_batch` never touches it.
3. **Test-first, two tiers, as before.** Frozen acceptance tests in
   `tests/acceptance/` written from this plan's criteria through public verbs only;
   disposable unit tests below them. Modifying a frozen test is an escalation.
4. **Escalation triggers:** any schema change beyond the two migrations named here;
   any event type beyond the six named; any verb signature change **this plan does not
   itself specify** (Phase 2 changes `suppress()` deliberately); anything that makes
   a test in this plan unwritable as specified.
5. **One phase per session.** Run `make test` + `ruff` + `pyright` clean at every
   phase boundary. ⚠️ `make test` and `make e2e` **truncate `mailengine_dev`** —
   re-ingest per `current-state.md` before any manual verification against dev data.
6. **Events are append-only and the taxonomy is closed.** All six new types enter
   `EVENT_TYPES` deliberately: `contact.assigned`, `contact.assignment_expired`,
   `contact.reclaimed` (Phase 1); `contact.dnc_checked`, `contact.suppressed`,
   `contact.suppression_cleared` (Phase 2).

---

## Phase 0 — Decisions and operational prerequisites (no code)

Everything code depends on but cannot produce.

- **John's inputs:** nudge channel (SMS or email — a build dependency for Phase 3,
  not a preference), weekly dial-hours (sizes his batch, §5), agreed radius (§11 Q8).
  Ask the channel question knowing the cost asymmetry: email rides the existing SMTP
  credentials (repo-root `/home/young/Desktop/Code/nvermisscall/PRD.md` § Shared
  Credentials Reference — not the mail-engine PRD); **no arbitrary-send NMC SMS API
  exists** —
  booking-system sends only inside Twilio conversations — so "SMS" means new
  integration work (Twilio creds in mail-engine, or a new NMC endpoint).
- **Q10 decided:** Medusa correlation vs founder close-stamp (design §S-10). Gates
  Phase 4's close-visibility inflow. Must land before the first partner close.
- **SAN registration started** at `telemarketing.donotcall.gov` (NMC EIN; lead time
  unknown — start now). No SAN, no Phase 2 live scrub (the fake unblocks dev). The
  SAN runs **12 months and must be renewed** — renewal opens **30 days before
  expiry** (email notice; there is no September window — calendar it from the
  purchase date); an expired SAN stops `dnc_refresh` and drains the pool
  exactly like a dead job (design §6).
- **Area-code set re-derived with a recorded script** before subscribing: the design's
  Chatsworth free-five is disputed by an independent re-measurement (661 likely
  belongs, not 747 — design §6, revision 4). Deliverable: a re-runnable script
  (pinned seed coordinates, geocode source, distance formula) committed alongside the
  docs, whose output is the subscription list. The wrong set silently strands ~450
  in-radius contacts for $0 of savings.
- **Counsel hour scheduled** (Q6: B2B exemption, cellular CSLB numbers,
  seller-of-record on the SAN). Gates *John dialing*, not code.
- **Paper prongs drafted:** the one-page written dialing procedure and the partner
  agreement additions (procedure acknowledgment; re-pull-before-each-session covering
  suppression *and* expiry/reclaim; the mail-channel commission residual, §8).
- **Mail-engine PRD amendment** — four places contradict the approved design and must
  be updated with it: §5's second user ("Sales partner… **affiliate** referrals, uses
  pipeline and timeline views" — partners have no login, and "affiliate" is the
  banned program conflation); §12 Q4's "day-one `owner=partner` at intake" leaning
  (superseded — ownership moves only through `set_owner`; migration 0004's comment
  says the same stale thing); §10's "NMC SMS/email sending path reusable for digests"
  dependency (no such API exists — see above); FR-10's "one morning digest per
  founder" (recipients now include partners); and **FR-11's "every founder-initiated
  verb is fronted; one verb per route"** (revision 6) — the assignment verbs ship
  CLI-first with no web routes at v1; amend FR-11 to exempt job/CLI verbs, or a
  later phase adds the routes deliberately.
- **`partnership-program.md` amendment** (same trigger): its "How It Works" arc 6
  still prescribes the holdings ceiling the design dropped ("Refill is refused above
  a holding ceiling"), arc 4's fixed "250–500 contacts" predates the hours-derived
  batch (floor 100), and Step 11/12's framing is superseded by the design's
  trial-batch path (§5, revision 4). This is the document partners actually read.
- **`decisions.md` superseding entry + `seams/posthog.py` docstring retext** (revision
  5): the 2026-07-12 entry — "the future NMC feed must NOT also emit
  `signup.completed`" (repeated verbatim in the posthog docstring) — is refined by
  S-10's consumer-side dedupe design; without a superseding entry the executor hits a
  flat design-vs-decision-log contradiction under ground rule 1. (Same entry's
  "fixed 7-day lookback" is also stale — the code and this plan say 30 days.)
- **`current-state.md`** is stale (calls the design "revision 2", states the disputed
  Chatsworth set as settled) — rewrite at end of session as usual, listed here so the
  hand-off doc doesn't re-teach superseded facts.

**Accept when:** each input above is recorded (decisions.md once the design doc is
approved), the SAN application is in flight, and the agreement draft exists. Nothing
here blocks Phases 1–2 except John's channel (Phase 3) and Q10 (part of Phase 4).

## Phase 1 — Custody foundation 🟡

**Migration 0009** *(renumbered 2026-07-27: `0008` is owned by the ingest/contact
grain migration, which is sequenced before all partner phases — see
`ingest-contact-migration-implementation.md`)*: `partners` (id, name, status active|inactive, channel,
channel_address, base address fields, radius_miles, weekly_hours, created_at);
seed rows for the house account (Young) and John (channel fields may stay null until
Phase 0 answers; Phase 3's sender fails loudly on a null channel rather than
guessing — but the **house row's channel is seeded now**: email,
`young@nevermisscall.com`, so Phase 3's "a real nudge reaches Young" has an address);
`contacts.owner` → `owner_id uuid
not null **default '<HOUSE_PARTNER_ID>'** references partners(id)` with 0004's
`'young'` backfilled to the house row's id — **the default is load-bearing (revision
5)**: `load_list` and `ensure_seed_contacts` INSERT without any owner column
(`service/contacts.py:69-92`, `:117-126`) and the required post-`make test`
re-ingest would otherwise fail on the first not-null violation; intake inserts are
intentionally untouched. `assignment_batches` (id, partner_id, idempotency_key
unique, requested_count,
delivered_count, expires_at, actor, created_at, **request verbatim + hash** — the
rule or id-list as data, for the retry receipt and the key-mismatch check);
`contacts.assignment_batch_id uuid
null references assignment_batches(id)`; and the **exclusivity index**: `create
unique index ... on contacts (phone_e164) where assignment_batch_id is not null` —
one assigned row per phone, enforced by storage (design S-1 revision 5; SELECT-gates
alone do not survive concurrency). Update `judgment/digest.py`'s recipient
resolution for the id type. A small **`partners` CLI** — **upsert by name** (`add`
is `set` on a name that doesn't exist yet — revision 6: a mutate-only CLI cannot
create partner #2, the same insert-path hole as TD-2's activation table) — covering
channel / hours / radius / status, `--help` per house rule. The table needs a writer
beyond its migration
seed: the Phase 0 answers land through it, S-3's batch resizing actuates through
`weekly_hours`, and Step 12's "remove lead access" flips `status` (revision 5).

**Code:** the three ownership event types in the taxonomy; the single internal
`set_owner(contact_id, new_owner_id, reason, actor)` in `service/` — writes the
column, clears/sets the batch pointer, appends the event, one transaction. No public
verb yet; nothing else may touch `owner_id`. **Event-type mapping, pinned:**
assignment emits `contact.assigned`; the nightly expiry step alone emits
`contact.assignment_expired`; every other return to the house — reclaim, voice
suppression, `dnc_registry` hit, won-termination — emits `contact.reclaimed` with the
reason in the payload. S-8's derivation closes a custody interval on any of the
three. `judgment/digest.py:_resolve_recipient` currently reads `contacts.owner` with
an `or "young"` fallback — update it for the id column; the fallback dies with the
not-null FK. **The house row's identity is pinned, not discovered:** a fixed,
migration-seeded uuid recorded as `HOUSE_PARTNER_ID` in `config/params.py` — it is
what `_resolve_recipient`'s `Recipient.YOUNG` branch returns (that branch's `"young"`
literal at `digest.py:67-68` is distinct from the `or "young"` fallback at `:71` —
the fallback dies with the FK, the branch literal would match no row after this
migration), what every return-to-house `set_owner` call targets, and what S-8's
genesis rule resolves to. Every phase touches this value; nobody invents it.
`record_nudge`'s `nudge.sent` payload gains the recipient's partner id;
keep the human-readable name alongside it so historical payloads stay greppable.

**Accept when:** migration applies cleanly twice; every historical contact resolves
to the house row; the **single-writer invariant test** passes — after exercising every
ownership-changing path in the suite, each contact's `owner_id` equals
**`current_owner(events)`** — the event-confirmed derivation, which closes custody
only on end events, per design S-8's two-derivations rule (the stamped-expiry-bounded
`owner_at` is Phase 5's function and *intentionally disagrees* with the column in the
late-expiry window — a fixture pins that disagreement in Phase 5, not here) — with
the genesis rule (no event ⇒ house);
an owner write without an event is unconstructible through the public surface (the
test proves it by deriving, not by grepping).

## Phase 2 — Suppression split + DNC scrub 🔴 (plan → explicit approval → code)

The compliance floor, and the one phase that changes existing behavior. Present the
approved acceptance tests AND this phase's plan before writing implementation.

**Frozen-test authorization (resolve the collision up front):** existing acceptance
tests pin v2 suppression — `tests/acceptance/test_recompute.py:86` asserts
`stage == "suppressed"` for the old reach, `test_contacts.py:102-120` asserts
`suppress` derives `suppressed` — and ground rule 3 makes modifying them an
escalation. This phase's 🔴 approval **is** that escalation, resolved in advance: the
design re-specifies the behavior, so the approval explicitly covers rewriting the
named suppression-pinning acceptance tests to the S-6 matrix. This is
re-specification under an approved design change, not loosening to go green; every
replaced assertion must have a stricter v3 counterpart in the matrix.

**Migration 0010** *(renumbered 2026-07-27, same shift as Phase 1)*:
`contacts.do_not_call`, `contacts.dnc_registry`,
`contacts.dnc_checked_at`, `contacts.address_undeliverable`; `dnc_subscriptions`
(area_code pk, subscribed_at) — org-level, per design §7; and the **suppression
tombstone** (design S-6, revisions 4–5: survives FR-8's CCPA hard-delete — which is
itself unbuilt, noted honestly — columns `phone_e164` *and* `list_key` (either
nullable), `channel`, `reason`, `created_at`). **Its writer is `suppress()`**: every
permanent suppression inserts its tombstone in the same transaction as flag + event
(write-at-suppress-time, not delete-time — if the named row is later deleted, the
tombstone is the only protection its phone twins inherit). Consulted by the
assignment and export gates (by phone) and by **`load_list` at intake** (by
`list_key` and phone), which re-applies suppression columns to re-ingested rows;
`load_list` also now emits `contact.suppressed {channel: mail, source: intake}` per
`do_not_mail` CSV row (design S-6 writer discipline, revision 5).

**Voice facts are phone facts (design S-6, revision 4):** `do_not_call` is written on
the named row but every gate reads *any row sharing the phone*; setting it removes
every assigned row sharing the phone (each removal emits); `dnc_registry` fans out at
write to all rows sharing the phone. Twin fixtures are part of this phase's matrix:
suppress one of two rows sharing a phone ⇒ both unassignable, both out of exports,
the assigned twin's assignment ended.

**Derivation change (RULESET_VERSION → 3):** `is_suppressed` narrows to `opt_out`
only. Returned-pieces ≥ 2 stops feeding the stage and instead derives
`address_undeliverable`. **The historical-event trap (verified in code):** today's
`suppress()` has emitted `contact.opt_out` for *both* reasons since day one —
`do_not_mail` requests included — with the real reason only in the payload
(`service/contacts.py:148`). Keying v3 on the event type alone would keep every
historical do-not-mail request fully `SUPPRESSED`, silently defeating the split for
exactly the contacts it exists to fix. `Event.payload` is already available to the
pure rules, so v3 must read `payload.reason` on `contact.opt_out`: reason
`do_not_mail` ⇒ mail-only, anything else ⇒ suppressed. Count the affected events
(`payload->>'reason'` group-by) as part of the before/after report.

**The derived flag needs its writer named** (this feature's own dead-writer rule):
`address_undeliverable` is written by `recompute_state`, which today refreshes only
`stage_snapshot` — it gains the column write, derived from the `piece.returned`
events already in the stream. Note what does **not** change: the new columns are
channel gates read by assignment and audiences, not derivation inputs, so
`ContactFlags` does not widen — v3 `derive_stage` in fact *stops* reading
`flags.do_not_mail` (mail-only now), and the flag's stage role ends there. Recompute
still never touches the human-authored `do_not_*` columns (FR-7).

**`_audience_where` (`service/waves.py:58-65`), concretely:** add
`c.address_undeliverable = false`; **keep** `c.stage_snapshot <> 'suppressed'` —
after the narrowing it stops leaking (the stage means `opt_out`-only) and becomes the
backstop against **event-only opt-outs**: `record_note`
(`service/ingestion.py:117-126`) validates against the *full* taxonomy, so a human
note of type `contact.opt_out` writes the event with no column writes, and without
the stage clause that contact keeps receiving mail despite an opt-out on file.
Columns are the gate; the stage is the belt-and-suspenders (design S-6). Also in
this phase: **restrict `record_note` to `note.*` types** — opt-outs go through
`suppress()`, which writes flags and event atomically. That restriction ripples to
the two note web routes that accept caller-supplied types (`web/api.py:225-227` and
`:426-428`), not only the suppress routes. Acceptance: a contact with an
opt-out *event only* (fixture bypassing `suppress()`) is excluded from every wave
audience. `c.do_not_mail = false` and `c.is_seed = false` stay.

**Consequence to surface, not hide:** contacts currently `suppressed` via
`do_not_mail`-on-load or returned mail move stage on the first recompute — the
before/after count report is a phase deliverable, and the `_audience_where` change
lands **before** that recompute runs. The report also covers the judgment-rule
knock-on (verified in code): `hot_response`, `quiet_reengage` and `lost_aging` filter
on `stage_snapshot` (`'responded'` / `'in_conversation'`), so formerly-suppressed
contacts re-entering those stages become visible to the rules again — intended, their
phones were never the problem, but quantify it before the first post-migration
nightly rather than discovering it in the digest. And `returned_mail.py`'s wording
("auto-suppressed by derivation", its `nudge` string) becomes false — its SQL
survives untouched (it counts `piece.returned` events); retext it to
`address_undeliverable`.

**`suppress()` rewrite:** per-channel — validates channel against S-6's table, sets
the column, emits `contact.suppressed {channel, reason, source}`; `opt_out` remains
the all-channel case emitting `contact.opt_out` (and setting `do_not_mail` +
`do_not_text` + `do_not_call`; its tombstone is three per-channel rows).
**Atomicity is a composition constraint, not a slogan (revision 6):** today's
`suppress()` is *two* transactions — `ingest_event` commits its own
(`ingestion.py:110`), then the flag update opens another. The rewrite composes
flag + event + tombstone + twin-set `set_owner` removals **on one caller-owned
cursor** via `append_event` (`ingestion.py:48`), and `set_owner` must accept that
cursor — otherwise the "same transaction" language stays aspirational and untestable.
A **`clear_suppression(contact_id, channel)`** verb is the single public write path
for `contact.suppression_cleared` — rejects permanent channels, called internally by
the scrub's delisting path — giving the S-6 matrix's reject-side tests a public verb
to go through (a bare `ingest_event` of the type would otherwise succeed; ingestion
validates taxonomy, not column semantics). **A voice-blocking suppression (`do_not_call`, or
all-channel `opt_out`) also ends any live assignment** via `set_owner` — S-6:
"setting it immediately removes the contact from its assignment." Testable in this
phase: `set_owner` and `assignment_batches` exist from Phase 1, even though the
public assignment verbs land in Phase 4. `contact.suppression_cleared` accepted
**only** for `dnc_registry` (and, later, `address_undeliverable` via an address
correction that does not exist yet) — rejected at the write for the permanent
columns. **Call sites ripple:** `suppress()` is called from two web routes —
`web/api.py:242` (JSON) and `web/api.py:445` (UI form) — both update for the new
signature, and the UI form's reason field becomes channel + reason.

**Seam + job:** `seams/dnc_registry.py` Protocol (fetch per-area-code registry file +
version) with `FakeDncRegistry` first; the real FTC client behind it (needs the SAN;
the portal serves per-area-code **full lists and change lists** — full-list diff is
the correct v1, change lists an optimization). `dnc_subscriptions` **needs a writer
too** — a small `subscribe_area_codes` CLI (with `--help`, house rule); a table with
no writer is the exact TD-2 shape this feature keeps finding.
`jobs/dnc_refresh` (cron/CLI, never a route): **runs daily** — a cheap no-op when
nothing has crossed the 21-day threshold, which is what makes "a couple of missed
runs cost nothing" true — re-scrubbing contacts in
subscribed area codes with `dnc_checked_at` older than 21 days, **assigned contacts
first**; each scrub stamps `dnc_checked_at` and emits `contact.dnc_checked` with the
registry version — **idempotency mechanism, pinned:** `external_id =
"dnc:<contact_id>:<registry_version>"` under source `system`; `ingest_event` already
accepts `external_id` (verified), and the events table's `unique (source,
external_id)` is what makes "same version twice ⇒ no duplicate events" true rather
than hoped. A hit sets `dnc_registry` **on every row sharing the phone** — stamping
each twin's `dnc_checked_at` and emitting per-row events (staleness accounting is
per row; revision 5) — and calls
`set_owner` (house, reason=`dnc_registry`) for each assigned one. **The clear path
has a writer** (design S-9, revision 4): a scrub finding a previously-hit number
*absent* from the current version clears `dnc_registry` on every row sharing the
phone and emits `contact.suppression_cleared` **per row**, keyed contact + version
like the check
event — matrix test for the job path, not only the event-write path. **Volume is a
design fact, not a surprise (revision 5):** subscribed-code scope is ~16–18k
contacts on a 21-day cycle ≈ **300k `contact.dnc_checked` events/year** — more than
every other type combined — so `recompute_state`'s rehydration and
`get_contact_timeline` **exclude the type** (it is compliance audit trail, not
judgment signal; "were we compliant that day" queries hit it directly). A judgment rule
nudges when the newest registry version ages past `dnc_version_alert_days` (default
**24** — a week before the 31-day wall; in `config/params.py`), recipient YOUNG,
high priority.

**Accept when:** one test per row of S-6's table — five columns × (set, gate,
clear-allowed-or-rejected) — plus: a `do_not_call` suppression does **not** remove
the contact from a wave audience (the three-character-fix regression, asserted
directly); a historical-style `contact.opt_out` with `payload.reason = 'do_not_mail'`
derives mail-only, not `SUPPRESSED` (the historical-event trap above, as a fixture);
a `do_not_call` suppression on an assigned contact ends the assignment with an event
(assignment constructed via `set_owner` — the verbs are Phase 4);
a `dnc_registry` hit on an assigned contact ends the assignment with an event; the
refresh against the fake is idempotent (same registry version twice ⇒ no duplicate
events); recompute writes `address_undeliverable` from returned pieces and two runs
are deterministic; the before/after stage-migration report exists and was reviewed.
(The "stale check ⇒ unassignable" gate itself is Phase 4 code; its test lands there.)

## Phase 3 — Sender + nudge routing 🟡 (TD-10)

A real `Sender` implementation: recipient → channel resolved from the `partners` row
(`channel` + `channel_address`); transports per Phase 0's answers (email via the
existing SMTP credentials is the cheap path; SMS is new integration — see Phase 0).
An unmapped or inactive recipient **fails the digest loudly** — never a silent
drop. Wire `jobs/nightly_cli.py` to pass the sender.

**Loud failure must precede the record, or it becomes the silent drop it forbids
(revision 4):** `digest.run` records first and sends last — `record_nudge` (appends
`nudge.sent`, stamps `next_action_at`) runs inside the selection loop
(`digest.py:100-108`), `sender.send` after it (`digest.py:117-119`). A delivery
failure after recording arms the cooldown against its own retry, and permanently
silences `hot_response` for that contact (its predicate is "no `nudge.sent` ever").
One partner row with a null channel — explicitly permitted until Phase 0 answers —
would swallow exactly the commission-bearing nudges this feature routes. Therefore:
**pre-flight the recipient → channel map for every resolved recipient before the
record loop**; an unresolvable recipient aborts **that recipient's hits** before any
of their `nudge.sent` rows are written, while deliverable recipients' digests go out
with a **loud banner naming the failed recipient** prepended to Young's. Per-recipient
abort, not whole-digest (revision 5): the DNC staleness alarm — the compliance
design's named catch for a dead scrub or expired SAN — is itself delivered by this
digest to Young, and a whole-digest abort on one partner's null channel would
silence the alarm nightly until someone noticed. The failure domain of a partner's
channel must not contain Young's compliance signal (the house channel is seeded in
Phase 1, so Young is always deliverable). Acceptance: failed pre-flight for one
recipient ⇒ zero `nudge.sent` rows for them (their hits re-fire the next night),
other recipients delivered, Young's digest carries the banner — **and on a zero-hit
night for Young, the failure synthesizes a house-channel delivery anyway** (revision
6: `digest.run` sends only to recipients with sent nudges and "silence is a valid
output," so without synthesis the banner has no carrier exactly on quiet nights —
the alarm must not depend on Young happening to have his own nudges). One honest
residual, stated: the DNC staleness alarm rides this digest, so a dead nightly cron
kills the watchdog and its reporter together — the calendar entry and
`nightly.log` monitoring remain the out-of-band floor.

**The S-7 routing split is a reclassification, not new machinery** (verified in
code): every rule already declares `Recipient.YOUNG` or `Recipient.DEAL_OWNER`
(`judgment/protocol.py`), and two inactivity rules are misclassified for a world with
partners — **`quiet_reengage` and `lost_aging` flip from `DEAL_OWNER` to `YOUNG`**
(S-7: inactivity inferred from spine-absence must not nag a partner about contacts
the spine can't see him working). `hot_response` and `demo_no_show` stay
`DEAL_OWNER` — both fire on observed events. Today the flip is a no-op (every contact
is house-owned), which is exactly why it must land before Phase 4 makes it not one.
Budget is confirmed per-recipient in code (`counts[founder]`, `digest.py:101`) — the
test asserts the behavior anyway.

**Accept when:** a real nudge reaches Young end-to-end (the first ever); FakeSender
remains the test impl; unmapped recipient ⇒ loud failure test; fixture proves a
partner-owned contact's `hot_response` addresses the partner while its
`quiet_reengage` addresses the house; 6 hits across two recipients with budget 5 ⇒
each recipient capped independently; `nudge.sent` events now mean what they say.

## Phase 4 — Assignment verbs and jobs 🟡 (the feature proper)

`assign_batch(partner_id, idempotency_key, actor, audience_rule=None, count=None,
contact_ids=None)` — the **audience rule is the selection** (design S-1: "given an
audience rule and a count"), reusing the wave grammar's relevant keys (trade,
segment, geography) with unknown keys rejected; the gates below are the floor, not
the selection. Within the eligible pool, selection follows a **stable deterministic
order** — never the cursor's whim (the same arbitrary-`fetchone()` shape banned in
attribution). `count` **defaults to the batch derived from the partner's
`weekly_hours`** (§5's formula, in `config/params.py`); an explicit count is the
founder override (sub-floor counts allowed — the 100 floor applies to *derived*
batches; the Step 11 trial batch is exactly such an override, design §5), the
id-list is the cutover form. The deterministic selection order **is `order by id`**
after gates and rule — named here because the acceptance tests need the actual key.
Retry semantics: a same-key retry returns the batch's **original membership** (the
rows pointing at that batch, plus those since released from it, reported as such) —
it is a receipt for what was assigned, not a live view — reconstructable because
`contact.assigned` events carry the **batch id** and the batch row stores the request
verbatim (Phase 1's schema; release paths clear the pointer, so the pointer alone
cannot answer "what was in this batch"). Batch creation and contact moves are **one
transaction**. Locking, scoped honestly (revision 6): the Phase 1 index stops
double-assignment, but the phone-scoped voice/won gates are still SELECT-reads, so
**both `assign_batch` and `suppress()` lock the full twin-row set** — every row
sharing each affected `phone_e164`, `select … for update` in canonical id order —
before evaluating gates; that ordering discipline is what closes the
suppress-vs-assign race rather than the index alone. A concurrent index collision
(two verbs racing past each other anyway) **aborts the verb loudly and is retried
with the same key** — never caught-and-degraded into partial assignment; the
graceful per-cause shortfall describes sequential outcomes only. The
`audience_rule` allowed keys are `segment`, `trade`, `source`, and the geographic
keys (`city`, `zip_prefix`) — **not** `stage` (the pool gates own stage), **not**
`limit` (`count` owns it), **not** `not_responded_to_wave` (defer until a real need);
unknown or excluded keys are rejected. A null
`weekly_hours` with no explicit `count` errors loudly. Explicit counts bypass floor
**and cap** (design §5 revision 6 — expiry carries anti-hoarding, not the cap). Every S-1
gate (phone, unassigned, stage ∈ {prospect, in_sequence, lost}; not voice-suppressed,
`dnc_registry` clear, and not won — all three **tested per phone across twin rows**
plus the deletion tombstone, design S-6 revision 4; subscribed area code;
`dnc_checked_at` ≤ 31 days;
**phone-exclusive** — no other contact sharing the `phone_e164` holds an assignment,
and one batch never selects the same phone twice; the table is not phone-unique,
1,785 shared numbers across 3,772 CSLB contacts, design S-1), batch row written
before contacts move, per-contact `contact.assigned` via `set_owner`, shortfall
report by cause; `is_seed = false` is an explicit pool gate (seeds are excluded only
incidentally by the phone gate today — say it, don't rely on it), and the export
renders null `contact_name`/`business_name` with the same `"Business Owner"`
fallback `execute_wave` uses (`service/execution.py:184`).
**Idempotency-key mismatch is rejected:** a reused key with a
different partner, count, or id-list errors loudly — it is a retry contract, not a
lookup API. `export_batch(partner_id)` — CSV, fresh every
pull, expiry + generation timestamp columns, excludes stale-DNC rows as shortfall
(S-2 revision 3). Nightly **expiry step** (join through batches past `expires_at` ⇒
`set_owner` house, `contact.assignment_expired`) and **won-termination step** (stage
`won` with a batch pointer ⇒ `set_owner` house, permanent exclusion). **Ordering in
`run_nightly` is load-bearing:** both steps slot **after `recompute_state`** (won
derives from fresh state) and **before `digest.run`** (nudges must route on
post-return ownership) — the documented sync → orphans → recompute → digest order
gains its two steps in that gap. `reclaim(partner_id, reason, actor)`. The **Q10
close-visibility inflow** per Phase 0's decision — if Medusa correlation: a new seam
(the Medusa DB is an external system here) over a read-only `MEDUSA_DATABASE_URL`
connection, matching **all** closes by phone (not only partner-coded ones — design
§11 Q10), ingesting `signup.completed` under **`EventSource.NMC`** — the enum value
exists and no feed has ever used it (the planned `NmcFeed` was never built); do
**not** add an enum value, that is a schema change. **Double-count guard (binding —
`decisions.md` 2026-07-12):** the PostHog feed already emits `signup.completed` for
coded-funnel closes, and no second source may emit the same fact — the
`(source, external_id)` key cannot collapse across sources. The correlation ingests
only when the contact has no existing `signup.completed` from any source — **and the
reverse ordering is guarded at the consumers, not the PostHog mapping (revision
5)**: the reverse ordering is today's production
default (PostHog keys unconfigured, feed skipped nightly per `nightly_cli.py:10-17`;
when keys land, the 30-day lookback replays closes the correlation already
ingested), but PostHog events are ingested **contact-less** (attribution happens
downstream in `resolve_orphans` — `seams/posthog.py:11`), so a mapping-time contact
check is unimplementable there. Instead: both events may exist; everything that
*counts* signups (metrics, cost-per-customer, the activation auto-insert)
deduplicates per contact; `won` derivation is already idempotent; and wave
attribution prefers the PostHog event, which alone carries the mailer-code → piece →
wave linkage. The correlation resolves its phone match through
the **tie-broken `contact_by_phone`** (assigned row preferred — a bare lookup lands
the signup on an unassigned twin and the assigned row expires back into the pool).
**Nightly placement, pinned (corrected revision 6): after `resolve_orphans`, before
`recompute_state`.** Revision 5 pinned it before `resolve_orphans` — which defeats
the guard by construction: PostHog signups are contact-less until orphan resolution,
so the contact-side check would see nothing on exactly the both-inlets night it
exists for. After resolution, `won` still derives the same night and the termination
step (below) acts on it. Acceptance tests, both orderings, in consumer terms
(revision 6 — no signup-counting consumer exists to assert against, TD-3): a
coded-funnel close resolved by orphans, then the correlation ⇒ exactly one
`signup.completed` (the guard sees the attributed event and skips); the correlation
first, then a replayed PostHog close ⇒ **two events exist and that is correct** —
`won` derived once, S-10's termination fired once, wave attribution prefers the
PostHog event. If close-stamp
instead: the sourced human event (`source='human'`) and its UI action, under the
same guard. Two databases, correlate in app code,
never a join. CLI wrappers get `--help` per house rule.

**Attribution tie-break (design S-8):** `contact_by_phone`
(`service/ingestion.py:152`) is a bare `fetchone()` with no `order by` — on the 1,785
shared numbers it attributes to an arbitrary row, which after this phase silently
picks the owner a response credits and where `hot_response` routes. Change it to
prefer a currently-assigned row on ties, deterministic tie-break otherwise
(`order by (assignment_batch_id is not null) desc, id`). Not a precedence change;
FR-6's chain is untouched.

**Cutover, same day S-1 goes live:** Young issues John's first real batch with the
explicit id-list form pinning the surviving sheet rows; rows failing any gate fall
out as reported shortfall; the sheet is void from that date. One manual act, no
migration code.

**Accept when:** idempotent retry returns the original batch (same key ⇒ same
contacts, no new events); a mid-conversation contact is never assigned (fixture:
responded + engaged ⇒ excluded, cause `mid-funnel`); double-assignment is
unconstructible — **including by phone** (fixture: two contacts sharing a
`phone_e164`, assign to two partners ⇒ the second is excluded with cause
`shared phone held elsewhere`); a reused idempotency key with different parameters
is rejected; the **suppress-vs-assign race** is a fixture (a `do_not_call` landing
between gate-check and commit ⇒ the storage layer, not luck, decides — no
voice-suppressed contact ever holds an assignment); expiry returns and re-assignability is immediate; a won contact
never re-enters the pool even after its batch would have expired — **nor do its phone
twins** (fixture: two rows one phone, one reaches `won` and its assignment
terminates ⇒ the twin is still excluded, cause `converted`); **the Q10
acceptance**: a close arriving with no mailer code ends the assignment before expiry
would have; export shortfall names causes; a phone response on a shared number
attributes to the assigned row, not an arbitrary twin (fixture: two rows, one phone,
one assigned); the single-writer derivation test from
Phase 1 still passes with all new paths exercised.

## Phase 5 — Owner-at-response-time and the readout 🟡

Pure derivation: custody intervals from the assignment event stream — open at
`contact.assigned`, close at the earliest of the **stamped expiry in that event** or
an explicit end event; genesis rule (no events ⇒ house). Readout segmentation:
partner-owned vs mail-only response lines, each with response rate and
cost-per-response; FR-6 precedence untouched.

**Accept when:** the reproducibility test — run a readout, then expire/reclaim the
assignments, run it again ⇒ **identical numbers**; a response landing after real
expiry but before a late `assignment_expired` event credits the house (the stamped
expiry decides); the **two-derivations fixture** (design S-8, revision 4): an
`assigned` event with a past stamped expiry and no end event ⇒ `owner_at(now)` =
house while `current_owner` = partner = the column — their disagreement in that
window is asserted as intended, not fixed; property test: derived owner is a total
step function for any event
sequence (Hypothesis); segmentation totals reconcile to the unsegmented readout.

---

## Cross-cutting

- **Batch/expiry constants** (`batch ≈ 12 × weekly_hours`, floor 100 / cap 500 /
  round 50, expiry 90 days, DNC refresh 21 days, freshness bound 31 days,
  `dnc_version_alert_days` 24, `HOUSE_PARTNER_ID`) live in
  `config/params.py`, not in prose or verb bodies.
- **Shortfall-cause vocabulary is a pinned enum**, not ad-hoc strings — the full set:
  `no_phone`, `already_assigned`, `shared_phone_held_elsewhere`, `mid_funnel`,
  `voice_suppressed`, `dnc_registry_hit`, `deletion_tombstone`,
  `unsubscribed_area_code`, `stale_dnc_check`, `converted`. Assignment and export report from this one set;
  the acceptance tests name causes from it, so it must exist before they are written.
- **Dead-writer audit (TD-2) closes here:** Phases 1 and 3 revive two of the three
  known members (`owner`, sender). Before calling the feature done, run the explicit
  audit for a fourth — every column read by live logic must have a writer, every seam
  called in production must have an implementation. Leave the audit as a standing
  data assertion if practical.
- **What is deliberately not built:** partner auth, disposition capture, holdings
  ceiling, territory rules, co-op credit, the address-correction verb, calling-hours
  enforcement (moot while CA-only). Building any of them is scope change, not
  initiative.
- **Definition of done:** John works from a system-issued batch; his sheet is void;
  the DNC scrub runs on schedule with the staleness rule armed; a nudge has actually
  been delivered; the wave readout segments by owner-at-response-time and reproduces
  itself; `make test` green, ruff + pyright clean, frozen suite grown by every
  criterion above.
