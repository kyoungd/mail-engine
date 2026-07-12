# Mail Engine — Fake-Driven Test Plan

*Authored by the architecture layer (Fable 5) for an executor (Opus 4.8) who was not present
for this analysis. This document is the spec for the next test build-out: a fake-driven
end-to-end harness plus an exhaustive scenario suite that closes the lifecycle and
attribution gaps the per-phase acceptance suite leaves open. Read alongside
`direct-mail-ai-implementation-plan.md` (§ Cross-cutting, test posture),
`direct-mail-ai-data.md`, `direct-mail-ai-service-contract.md`,
`direct-mail-ai-judgment-job.md`. This plan grows the suite; it deletes and weakens
nothing — the suite is scar tissue, it only grows.*

---

## 1. Purpose and scope

**What this is.** The existing suite is per-phase: each acceptance file gates one phase's
verbs, and most set up state with raw SQL (`insert into contacts ... stage_snapshot =
'responded'`). No test walks one contact through the whole machine, and — the central gap —
**the mailer-code attribution join is never exercised end to end**: `execute_wave` generates
deterministic codes (`service/execution.py::_mailer_code`) and `resolve_orphans` matches
events by code, but the only test of code-matching (`test_resolve_orphans.py`) seeds a piece
by SQL with a hand-typed `'MC-100'`. The code that generates and the code that consumes
have never met in a test.

The plan's real integration test (Phase 6 ghost wave) needs live Lob, live PostHog, a live
campaign line — deferred. Everything short of the vendors is testable **today** with the
three fakes in `seams/fakes.py`:

- `FakePrintApi` — idempotent on `mailer_code`, `fail_after=N` crash switch, `parse_webhook`
  that translates `{"status": "delivered"|"returned", "mailer_code": ..., "id": ...}` into
  canonical `piece.delivered`/`piece.returned` events carrying the mailer code in payload.
- `FakeResponseFeed` — scripted canonical events filtered by `occurred_at >= since`,
  `fail=True` raises before yielding.
- `FakeSender` — records `(founder, message)` tuples.

**What this covers:** every mechanic between "CSV file" and "digest text handed to a
sender" — intake, wave lifecycle, execution, attribution, derivation, judgment discipline,
delivery assembly, the HTTP window — including replay, crash-resume, ordering races, and
threshold boundaries the real world will not reliably or repeatably produce.

**What this cannot cover** (the honest boundary, expanded in §5): real Lob rendering,
postage, and webhook signatures; real PostHog `?r=` capture; the real NMC vertical and
booking flow; deliverability; the AI composer against a real model. Green here means "the
machine is internally correct against faithful fakes," not "production-ready." The ghost
wave remains the go/no-go for wave 1.

---

## 2. Current coverage inventory

Every existing test file, what it actually covers, its setup style, and the gap it leaves.
"SQL-seed" means the test writes tables directly (bypassing verbs) to arrange state;
"verb-driven" means state is arranged through the public contract.

### Acceptance (`tests/acceptance/`, frozen)

| File | Covers | Setup style | Gaps left |
|---|---|---|---|
| `test_migrations_idempotent.py` | Migrations apply twice cleanly; six tables exist | n/a | — |
| `test_enum_ddl_parity.py` | Python enums == DDL enum labels (parsed from migration 0001) | n/a | — |
| `test_taxonomy_closed.py` | `is_valid_type` accepts the closed set, rejects unknown/empty | n/a | — |
| `test_readonly_cannot_write.py` | Read-only role can select, insert denied at role level | n/a | — |
| `test_ingest_idempotent.py` | `(source, external_id)` dedupe; unknown type/source rejected; keyless events always append | verb-driven | — |
| `test_resolve_orphans.py` | Precedence chain per level (code / phone / thread), name-only orphan, idempotent re-run | **SQL-seed** (piece with hand-typed `'MC-100'`) | Never uses a code `execute_wave` generated; `since` parameter untested |
| `test_recompute.py` | Stage derivation via events; determinism; `do_not_mail` and human `next_action` survive; 5k/50k scale (nightly marker) | mixed (contacts by SQL, events by verb) | Only reaches `responded`/`in_conversation`; no full stage walk |
| `test_contacts.py` | `load_list` counts/E.164/segment/dedupe; `suppress` one-way + event + derived stage; `record_outcome` lost; `set_next_action` | verb-driven | Loaded contacts never continue into a wave |
| `test_wave_lifecycle.py` | draft→preview→approve→cancel; every approval precondition; `do_not_mail` exclusion; `not_responded_to_wave`; unknown-key rejection; cancel guards | **SQL-seed** (stage hand-set to `'responded'` for the non-responder test) | Responder exclusion never produced by an actual response + recompute |
| `test_execute_wave.py` | Piece creation/submission/`piece.submitted`; crash-resume exact with zero duplicates; drift halt at +30%; −10% exactly proceeds; draft/sent rejected | verb-driven (contacts by SQL) | Generated mailer codes never consumed downstream; no growth-direction boundary; no cancelled-wave rejection |
| `test_jobs.py` | `sync` idempotent; nightly sync→recompute order; **halt-before-recompute on feed failure**; `run_drops` due-only | verb-driven | Nightly's judgment/digest tail unasserted on failure; no unknown-type feed; no multi-feed partial failure |
| `test_judgment_rules.py` | All 10 rules: one fire + one near-miss each, evaluated directly against read-only cursor | **SQL-seed** (stages, events, activation, pieces all raw) | States never derived; thresholds tested at one point, not at the boundary; wave_anomaly's zero-response half absent (see §6 divergences) |
| `test_judgment_discipline.py` | Budget 5 + deferral in priority order; cooldown + re-fire; inbound breaks cooldown; human `next_action` respected; expiry stale-vs-future; composer fallback/model; zero-hit night; nudge.sent logged | **SQL-seed** | **Everything routes to `young`** — deal-owner/partner routing entirely untested; no per-founder budget independence; no rollup cooldown; no converted-contact drop-out; no boundary days |
| `test_approval_hash.py` | Preview returns hash; matching hash approves; drifted hash rejected (`stale_preview`); hash optional | verb-driven (contacts by SQL) | Drift only via added contacts, not suppression |
| `test_digest_delivery.py` | One digest per founder via `FakeSender`; no sender delivers nothing; zero-hit sends nothing | SQL-seed | Only one founder ever; digest never produced by `run_nightly` |
| `test_web_api.py` | One-view-one-verb; execution verbs 404; preview→approve hash flow over HTTP incl. 409 | verb-driven | HTTP never shown a post-drop world (dashboard/timeline with real pieces) |
| `test_queries.py` | Each query verb correct + exactly one round trip (counting cursor) | **SQL-seed** | Dashboard never fed by an executed wave |

### Unit (`tests/unit/`, disposable)

| File | Covers |
|---|---|
| `test_derivation.py` | Fixture-list boundaries: response strictly after first piece (equal instant excluded), quiet_days, suppression (flag / opt_out / 2 returns), full stage precedence, lost + revival + latest-lost + same-instant non-revival, won-over-lost, suppressed-over-lost |
| `test_derivation_properties.py` | Hypothesis: `derive_stage` order-independent; suppression absorbing; stage only moves forward over a growing event stream |
| `test_matcher.py` | Table-driven precedence incl. unresolved-code fall-through, normalization, never-fuzzy, code-beats-phone |
| `test_execution_helpers.py` | `_mailer_code` deterministic / distinct / 10 lowercase chars; `_assign_variant` deterministic + distributes |
| `test_composer.py` | Template shape; no-client / failing-client / empty-completion fallbacks; real completion verbatim |
| `test_phone.py` | E.164 table (valid + unnormalizable) |
| `test_seams.py` | `FakePrintApi` idempotency; `parse_webhook` delivered/returned translation |

### The summary of what is missing

1. **No cross-phase test at all.** Longest existing chain is two phases (`test_jobs.py`:
   sync → recompute).
2. **The mailer-code loop is open** — generated codes are never fed back through a feed.
3. **Judgment states are asserted against hand-set snapshots**, never against snapshots the
   derivation actually produced.
4. **Deal-owner routing (`contacts.owner` → partner digest) has zero coverage.**
5. Thresholds are tested at one convenient point, never *exactly at* the boundary.
6. The data document's "continuous data assertions" (§3, cost completeness, liveness,
   distribution) exist nowhere — neither as judgment rules (`judgment/rules/assertions/`
   was planned in Phase 4 and not built) nor as tests.

---

## 3. The harness: `tests/e2e/harness.py`

One class, `World`, that wires the three fakes plus a `TestClient`, and exposes the system
as story verbs so a scenario reads as 5–15 lines of narrative instead of 60 lines of SQL.

### Ground rules

- **Writes only through public verbs and jobs.** `World` methods call `service/*`,
  `jobs/*`, `judgment/digest.run`, and `web/api` — never `insert`/`update` (one documented
  exception below). If a scenario cannot be arranged through the contract, that is a
  finding, not a reason to reach into tables.
- **Reads may bypass** (service contract Rule 2 — the read-only role is the sanctioned
  analysis path). Inspectors use query verbs where one exists and read-only SQL where the
  contract deliberately has no verb (e.g. fetching a piece's `mailer_code` — codes live on
  pieces and there is no "list codes" verb; reading them via `READONLY_DATABASE_URL` is
  exactly the contract's read-bypass, not an internals reach).
- **The one write exception:** the `activation` table has **no service verb** — nothing in
  `service/` writes it (production presumably gets it from the NMC side; existing tests
  seed it raw). `World.activate(...)` therefore seeds `activation` by SQL, and the harness
  docstring must say so and why. This is also a standing divergence to flag (§6).
- **No fixed sleeps, no wall-clock races.** Time is moved by passing `as_of` forward into
  `run_drops` / `digest.run` / `run_nightly`, never by waiting.

### Mechanics the harness must get exactly right

- **The mailer-code loop.** `execute_wave` computes
  `base64.b32encode(sha256(f"{wave_id}:{contact_id}")).lower().rstrip("=")[:10]`
  per `(wave, contact)` — deterministic so a resumed drop regenerates the same code — and
  emits a `piece.submitted` event (`source='system'`,
  `external_id=f"submitted:{piece_id}"`, `contact_id` + `piece_id` set). After
  `World.drop()`, the harness reads each created piece's real `mailer_code` (read-only
  SQL) and caches it per `(wave, contact)`. `World.web_visit(contact)` then builds a
  canonical `page.visit` event whose payload carries **that** code
  (`{"mailer_code": <the code execute_wave generated>}`), appends it to the posthog
  `FakeResponseFeed`, and the next `nightly()` runs it through
  `sync → resolve_orphans → recompute` — the same path a real Lob QR scan takes through
  PostHog. The join is now closed by tests: generator and consumer meet on a code neither
  test hand-typed.
- **Delivery/return events go through `parse_webhook`.** `World.deliver(contact, wave)` /
  `World.return_mail(contact, wave)` build the fake vendor payload bytes
  (`{"status": "delivered", "mailer_code": <real code>, "id": <ext id>}`), pass them
  through `FakePrintApi.parse_webhook`, and enqueue the resulting canonical event on the
  lob feed — so webhook translation and code attribution are exercised together.
- **Time model.** `occurred_at` on feed events is caller-supplied, but
  `execute_wave` stamps `piece.submitted` with `now(UTC)`. So the anchor is
  `T0 = now(UTC)` at `World` creation; `World.at(days, hours=12)` returns `T0 + delta`;
  response events are dated at `at(n)` with n ≥ 0 (never before T0 — derivation's
  "response strictly after first `piece.submitted`" would silently drop backdated
  inbounds); judgment runs at `nightly(as_of=world.day(n))`. Scenarios that need "N days
  of silence" advance `as_of`, not the events. One consequence to respect:
  `get_pipeline().days_quiet` and `get_activation_board().stalled` compute against the
  *real* today (`datetime.now(UTC)` inside `service/queries.py`), so scenarios assert
  their presence/nullability, never exact day counts.

### The `World` API (sketch — the executor finalizes signatures)

```python
class World:
    # construction: wires FakePrintApi, FakeSender, one FakeResponseFeed per
    # source ("posthog", "nmc", "lob"), a TestClient over web.api.app, T0 anchor.
    # Assumes the clean_db fixture has run.

    # -- arrange (writes through verbs/jobs only) --
    def load(self, rows: list[dict]) -> IntakeReport            # temp CSV -> load_list
    def variant(self, name, hypothesis="h", creative={}) -> UUID  # create_variant
    def draft(self, name, rule, split=None, drop_number=1,
              scheduled_days=1) -> UUID                          # draft_wave
    def draft_and_approve(self, ...) -> UUID    # draft -> preview_audience -> approve_wave
                                                # WITH the preview's state_hash (the UI path)
    def drop(self, as_of=None) -> list[ExecutionReport]          # jobs.drop.run_drops
                                                # then caches real mailer codes per (wave, contact)
    def web_visit(self, contact, wave=None, at=None, code=None)  # page.visit w/ REAL code -> posthog feed
    def phone_call(self, contact, at=None, thread=None)          # call.inbound w/ phone payload -> nmc feed
    def sms_in(self, contact, at=None, thread=None)              # sms.inbound -> nmc feed
    def sms_out(self, contact, at=None)                          # sms.outbound (our reply) -> nmc feed
    def signup(self, contact, at=None)                           # signup.completed -> nmc feed
    def deliver(self, contact, wave, at=None)                    # vendor payload -> parse_webhook -> lob feed
    def return_mail(self, contact, wave, at=None)                # same, status=returned
    def note(self, contact, text, type="note.general")           # record_note
    def opt_out(self, contact, reason="do_not_mail")             # suppress
    def mark_lost(self, contact, reason="gone")                  # record_outcome
    def plan(self, contact, date, note)                          # set_next_action
    def activate(self, contact, signed_days_ago, **cols)         # SQL — no verb exists; documented exception
    def orphan_event(self, payload, at=None, source="nmc")       # unattributable event -> feed

    # -- act --
    def nightly(self, as_of=None) -> JudgmentResult | None       # jobs.nightly.run_nightly(feeds, since=watermark,
                                                                 #   as_of, sender=self.sender); advances watermark
    def judge(self, as_of, params=DEFAULT_PARAMS, ai=None) -> JudgmentResult  # digest.run only

    # -- inspect (query verbs + read-only SQL; never owner writes) --
    def stage(self, contact) -> str            # read-only: contacts.stage_snapshot
    def code(self, contact, wave) -> str       # the cached real mailer code
    def pipeline(self) -> list[ContactCard]    # get_pipeline
    def timeline(self, contact) -> list[Event] # get_contact_timeline
    def dashboard(self, wave) -> WaveDashboard # get_wave_dashboard
    def digest_for(self, founder) -> list[str] # FakeSender.sent filtered by founder
    def orphans(self) -> int                   # read-only: events where contact_id is null
    def pieces(self, wave=None) -> list[...]   # read-only piece rows (status, cost, lob_id)
    def events_of(self, type) -> list[...]     # read-only events by type (loss/dup checks)
    def http(self) -> TestClient               # the FastAPI window
```

Feed queueing detail: each `web_visit`/`phone_call`/... appends to the matching
`FakeResponseFeed.events` with an auto-generated unique `external_id` (accepting an
explicit one for replay tests). `nightly()` passes `since = watermark` and moves the
watermark to `max(occurred_at)+ε` after a clean run — replay tests override `since` to
re-deliver deliberately.

Location: `tests/e2e/harness.py` + `tests/e2e/test_*.py`, using the existing `clean_db` /
`owner_url` / `readonly_url` fixtures from `tests/conftest.py`. The e2e files are
**frozen-acceptance tier** unless a scenario below says otherwise.

---

## 4. The test suite

For each scenario: **id**, **intent** (the invariant pinned), **setup** (harness verbs, high
level), **key assertions**, **tier** (`e2e` = new harness-driven frozen acceptance;
`accept` = conventional frozen acceptance; `data` = data-assertion-expressed-as-test;
`unit` = disposable). Where a scenario duplicates an existing test that is noted — existing
frozen tests are never modified or deleted; "upgrade" means *add* the verb-driven twin.

Ground the assertions in these real values: `DRIFT_TOLERANCE = 0.10` (halt strictly `>`);
`_state_hash` = sha256 over `{"audience": sorted ids, "variants": variant_split}`
truncated to 16 hex chars; `INBOUND_TYPES = {page.visit, call.inbound, sms.inbound}`;
`ENGAGE_TYPES = {sms.outbound, call.answered}`; `RETURNED_SUPPRESSION_COUNT = 2`; stage
precedence `suppressed > won > lost > in_conversation > responded > in_sequence >
prospect`; params `quiet_days=4, stall_days=14, partial_days=4, fail_pct=0.08,
lead_days=3, age_out_days=30, nudge_budget=5, cooldown_days=3, expire_days=5,
orphan_max=20`.

### A. Golden-path full lifecycle

| id | intent | setup | key assertions | tier |
|---|---|---|---|---|
| `e2e_golden_web` | The whole machine works end to end on the web-response path — the plan's central missing test | `load` 3 contacts → `variant` → `draft_and_approve` (hash carried) → `drop` → `web_visit(c1)` with the real code → `nightly` | `stage(c1)=='responded'`; the `page.visit` event has `contact_id==c1` **and** `piece_id==` c1's piece (code join held); `dashboard(wave).responses==1`; digest to `young` contains a `hot_response` line; `timeline(c1)` reads `piece.submitted → page.visit → nudge.sent` in order | e2e |
| `e2e_golden_phone_to_won` | Full stage walk prospect→in_sequence→responded→in_conversation→won, every hop produced by verbs + recompute, never hand-set | `load` → `draft_and_approve` → `drop` → `phone_call(c)` → `nightly` → `sms_out(c)` → `nightly` → `signup(c)` → `nightly` | `stage` after each nightly: `in_sequence` (others) / `responded` / `in_conversation` / `won`; `pipeline()` contains c only during responded/in_conversation; timeline complete | e2e |
| `e2e_golden_mixed_cohort` | One drop, divergent fates coexist without cross-talk | 4 contacts; c1 web-responds, c2's piece `return_mail` once, c3 silent, c4 loaded with `do_not_mail=true` | c4 got no piece; stages: `responded` / `in_sequence` / `in_sequence` / `suppressed`; `dashboard.pieces_by_status` shows 1 returned; `responses==1` | e2e |
| `e2e_golden_over_http` | The UI window shows the post-drop world — approval by HTTP hash, then dashboard/timeline routes render real execution data | drive approve via `POST /api/waves/{id}/approve` with the hash from `GET .../preview`; `drop`; respond; `nightly`; read `GET /api/waves/{id}/dashboard` and `GET /api/contacts/{id}/timeline` | 200s; dashboard JSON matches `get_wave_dashboard`; timeline JSON lists the journey; (existing `test_web_api.py` covers the pre-drop half — this adds the post-drop half) | e2e |

### B. The attribution join

| id | intent | setup | key assertions | tier |
|---|---|---|---|---|
| `e2e_attr_qr_code` | A `?r=`-style visit with the generated code attributes event → piece → contact | golden-web core, isolated | `via` effect visible: event's `contact_id` and `piece_id` both set; upgrades `test_mailer_code_attributes_event_and_piece` (SQL-seeded `'MC-100'`) to the real generated code | e2e |
| `e2e_attr_phone_fallback` | A call with no code attributes by exact E.164 only — contact set, piece stays null | contact loaded **with a phone** via CSV; drop; `phone_call` payload `{"phone": "(818) 555-0100"}` | event `contact_id` set, `piece_id is null`; contact `responded` | e2e |
| `e2e_attr_thread_continuity` | The second message of a known conversation attributes by `thread_id` even with no code and no phone | `phone_call(c, thread="T1")` (attributed by phone) → `nightly` → `sms_in` carrying only `{"thread_id": "T1"}` → `nightly` | second event lands on the same contact; matcher key is `THREAD_KEY = "thread_id"` | e2e |
| `e2e_attr_orphan_surfaces` | Name-only events never guess; they accumulate and surface as the weekly `orphan_events` roll-up | 21 `orphan_event({"name": "Bob"})` (threshold is strictly `> orphan_max=20`) → `nightly` | all 21 still `contact_id is null`; digest to young contains `orphan_events` roll-up with `facts["count"]==21`; contacts' stages untouched | e2e |
| `e2e_attr_per_piece` | Per-piece codes distinguish "drop 2 worked" from "drop 1 landed late" — the reason codes live on pieces, not contacts | c receives wave-1 and wave-2 pieces (two drops); `web_visit(c, wave=w2)` then later `web_visit(c, wave=w1)`; `nightly` | first event's `piece_id` == w2 piece, second's == w1 piece; the two codes differ (deterministic per `(wave, contact)`) | e2e |
| `e2e_attr_bad_code_falls_through` | A mistyped/unknown code is not fatal — resolution falls through to phone; a present-but-unresolved key never blocks the chain | `web_visit(c, code="nosuchcode1")` with phone also in payload | attributed via phone: `contact_id` set, `piece_id is null` (unit twin exists in `test_matcher.py`; this pins the DB-backed chain) | e2e |
| `e2e_attr_webhook_loop` | Lob-shaped webhooks translate and attribute: `parse_webhook` → canonical event → code join | `drop` → `deliver(c, w)` → `nightly` | a `piece.delivered` event with `source='lob'`, attributed to c and c's piece; no vendor field names in payload beyond `mailer_code` | e2e |
| `accept_resolve_since_window` | `resolve_orphans(since=...)` only scans the window — currently untested parameter | ingest two orphans at T0 and T0+2d; `resolve_orphans(since=T0+1d)` | only the later one examined/matched; earlier remains orphaned until a full pass | accept |
| — | re-run idempotency of `resolve_orphans` | — | already covered by `test_resolve_is_idempotent`; **skip** | — |

### C. Three-drop cadence

| id | intent | setup | key assertions | tier |
|---|---|---|---|---|
| `e2e_cadence_drop2_nonresponders` | `not_responded_to_wave` targets exactly: wave-1 recipients still in `prospect`/`in_sequence` (`_NON_RESPONSE_STAGES`) | 3 contacts; drop 1; c1 responds; `nightly` (recompute moves c1 to `responded`); draft drop 2 with `{"not_responded_to_wave": str(w1)}`; preview + drop | drop-2 audience == {c2, c3}; c1 has no wave-2 piece; upgrades the SQL-seeded `test_not_responded_to_wave_targets_only_non_responders` to a derived stage | e2e |
| `e2e_cadence_recompute_ordering` | Audience resolution reads `stage_snapshot` — a response not yet recomputed does NOT exclude. Pins the nightly-before-preview ordering requirement as system truth | as above but preview drop 2 **before** running `nightly` | responder still in the preview (count 3); after `nightly`, re-preview shows 2 — and the stale first hash now rejects approval (`stale_preview`) | e2e |
| `e2e_cadence_three_drops` | A full 3-drop journey: distinct per-drop codes, exclusion begins the drop after the response lands | c in drops 1–3 (drop 2/3 audiences via `not_responded_to_wave` of the prior wave); c responds after drop 2; nightly; drop 3 | c has exactly 2 pieces (w1, w2), codes differ; drop-3 audience excludes c; non-responders have 3 pieces each | e2e |
| `e2e_cadence_new_prospect_joins_late` | A contact loaded between drops is never accidentally swept into a `not_responded_to_wave` audience (they have no wave-1 piece — the `exists` clause requires one) | drop 1 over 10 contacts; `load` 1 new contact; draft drop 2 keyed on wave 1 | new contact absent from drop-2 preview and pieces | e2e |
| — | one-piece-per-contact-per-wave under re-execution | — | enforced by `unique (contact_id, wave_id)` and already pinned by `test_execute_is_resumable_without_duplicates`; re-asserted incidentally by `e2e_replay_drop_resume`; **skip as standalone** | — |

### D. Idempotency / replay

| id | intent | setup | key assertions | tier |
|---|---|---|---|---|
| `e2e_replay_nightly_twice` | Running the whole nightly twice for the same night changes nothing: no duplicate events, no duplicate nudges, empty second digest | golden-web through first `nightly(as_of=D)`; snapshot events count + digest; `nightly(as_of=D)` again with `since` rewound (deliberate full replay) | events count unchanged (feed events dedupe on `(source, external_id)`); exactly one `nudge.sent` for the contact (second run suppressed by cooldown: `last.date() <= as_of - cooldown_days` is false same-day); `FakeSender` got no second message | e2e |
| `e2e_replay_drop_resume` | A drop killed mid-wave resumes exact through the **job** path | 5 contacts; `FakePrintApi(fail_after=2)`; `drop()` raises; clear `fail_after`; `drop()` again | 5 pieces, 5 distinct codes, `submit_calls==5`, 5 `piece.submitted` events, wave `sent`. Near-dup of `test_execute_is_resumable_without_duplicates` but drives `run_drops` (which re-selects — the halted wave is `executing`, not `approved`, so run_drops must be shown to skip it — see divergence note §6.5, assert actual behavior) | e2e |
| `e2e_replay_feed_resync` | Re-pulling a feed from epoch after a successful sync inserts nothing | respond once; `nightly`; `nightly` with `since=T0` | one row per external_id (`select count(*) group by external_id` all 1) | e2e |
| `e2e_replay_recompute_fixpoint` | Recompute is a fixpoint over any real lifecycle history, not just synthetic ones | after `e2e_golden_phone_to_won` history exists, run `recompute_state()` twice | both runs report same count; all `stage_snapshot` values identical between runs (complements the synthetic 5k nightly-marker test) | e2e |
| `e2e_replay_resume_after_drift` | The rare double-failure: crash mid-drop, audience then drifts beyond 10%, resume re-resolves and re-checks drift | 10 contacts; `fail_after=3`; crash; `load` 2 more matching contacts (+20% vs `approved_audience_count=10`); resume `execute_wave` | resume **halts** (`halted=True`, 3 pieces remain, wave still `executing`) — drift guard applies on every run, resumed or not; pins that a halted resume never strands duplicates | e2e |
| `e2e_replay_webhook_duplicate` | The same vendor webhook delivered twice (Lob retries) is one event | `deliver(c, w)` twice with the same vendor `id` | one `piece.delivered` row | e2e |

### E. Compliance / suppression

| id | intent | setup | key assertions | tier |
|---|---|---|---|---|
| `e2e_supp_dnm_everywhere` | `do_not_mail` is excluded from **every** audience unconditionally (the always-on WHERE clauses), from intake onward | CSV row with `do_not_mail: "true"`; also a mid-life `opt_out(c2, "do_not_mail")` | neither appears in any preview or drop of any rule shape ({}, trade, segment, not_responded); zero pieces ever | e2e |
| `e2e_supp_optout_mid_conversation` | STOP mid-conversation: opt-out → suppressed → leaves pipeline → excluded from the next wave | walk c to `in_conversation`; `opt_out(c, "opt_out")`; `nightly`; draft+drop wave 2 | `stage=='suppressed'`; `pipeline()` no longer lists c; no wave-2 piece; `contact.opt_out` event on timeline | e2e |
| `e2e_supp_optout_before_recompute_window` | **Pins a real window**: `suppress(reason='opt_out')` sets only `do_not_text` + the event; the audience WHERE (`do_not_mail=false and stage<>'suppressed'`) doesn't see it until recompute. A drop between opt-out and nightly still mails them | `opt_out(c, "opt_out")`; immediately `drop` wave 2 (no nightly between) | **assert current behavior**: c gets a wave-2 piece. This is a candidate architectural escalation (§6.4) — the test documents the window so the fix, if ordered, flips one assertion | e2e |
| `e2e_supp_two_returns` | Two returned pieces auto-suppress + one `returned_mail` FYI roll-up to young | two waves to c; `return_mail(c, w1)`, `return_mail(c, w2)`; `nightly` | `stage=='suppressed'` (`RETURNED_SUPPRESSION_COUNT=2`); digest to young has the roll-up with c listed in `facts["contacts"]`; c out of all future audiences | e2e |
| `e2e_supp_one_return_not_suppressed` | Near-miss: a single return is data, not suppression | one `return_mail`; `nightly` | stage unchanged (`in_sequence`); no `returned_mail` roll-up | e2e |
| `e2e_supp_absorbing` | Suppression is absorbing: an inbound after opt-out does NOT revive (unlike `lost`) | `opt_out`; `nightly`; `sms_in(c)`; `nightly` | still `suppressed` (property-based twin exists; this is the DB-backed pin) | e2e |
| `e2e_supp_no_nudges` | A suppressed contact never generates contact-level nudges again | suppress a previously-responded contact; several `nightly` runs at advancing `as_of` | no `nudge.sent` for c after suppression (hot_response requires stage `responded`; quiet_reengage requires `in_conversation`) | e2e |
| — | no-unsuppress-verb | — | covered by `test_suppress_is_one_way_no_unsuppress_verb`; **skip** | — |

### F. Stage journeys through recompute

| id | intent | setup | key assertions | tier |
|---|---|---|---|---|
| `e2e_stage_full_walk` | (== `e2e_golden_phone_to_won`; listed for the category's completeness — **one test, cross-referenced, not duplicated**) | — | — | e2e |
| `e2e_stage_lost_roundtrip` | Revivable lost: `contact.lost` removes from pipeline; a later inbound revives to the pipeline | walk to `in_conversation`; `mark_lost(c)`; `nightly` → `lost`, out of `pipeline()`; `sms_in(c)`; `nightly` | back to `in_conversation` (prior `sms.outbound` after first response keeps `engaged` true); reappears in `pipeline()` | e2e |
| `e2e_stage_lost_again` | Only the latest `contact.lost` governs — lose, revive, lose again sticks | lost → revived → `mark_lost` again; `nightly` | `lost` (unit twin `test_only_the_latest_lost_governs_revival`; this pins it through verbs + recompute) | e2e |
| `e2e_stage_won_over_lost` | `signup.completed` outranks a lost mark | `mark_lost`; `signup`; `nightly` | `won` | e2e |
| `e2e_stage_suppressed_over_won` | Suppression absorbs even a won customer (returned mail post-signup) | `signup`; two `return_mail`; `nightly` | `suppressed` | e2e |
| `e2e_stage_responded_needs_piece_first` | An inbound from someone never mailed is attributed but yields no `responded` — response is defined strictly after first `piece.submitted` | load c, **no drop**; `phone_call(c)`; `nightly` | event attributed; stage stays `prospect` (the "responded = after first piece" definition, data doc §3) | e2e |

### G. Judgment under load / routing

| id | intent | setup | key assertions | tier |
|---|---|---|---|---|
| `e2e_judg_owner_routing` | **Deal-owner routing — currently zero coverage.** A partner-owned contact's `hot_response` lands in the partner's digest, not young's | contact with `owner='partner'` (via CSV `owner` column if `load_list` supports it — it does **not** today, see §6.6; otherwise seed owner via the documented SQL exception and flag), walk to `responded`; `nightly` | `digest_for('partner')` has the nudge; `digest_for('young')` does not; `nudge.sent` payload `recipient=='partner'` | e2e |
| `e2e_judg_rollups_route_young` | Roll-ups and wave-level rules go to young regardless of contact owner (`Recipient.YOUNG`, and `_resolve_recipient` falls back to young when `contact_id is None`) | partner-owned contact triggers `returned_mail` roll-up | roll-up in young's digest only | e2e |
| `accept_judg_owner_null_default` | A null/empty `owner` resolves to young (`owner or "young"`) | contact with owner cleared | nudge routed young | accept |
| `e2e_judg_budget_per_founder` | The budget is per founder per day: 6 young-owned + 6 partner-owned hits → 5+5 sent, 1+1 deferred | 12 hot responders split by owner; `nightly` | `len(sent['young'])==5`, `len(sent['partner'])==5`, `len(deferred)==2`; each founder got exactly one digest message | e2e |
| `e2e_judg_deferred_fire_next_day` | Deferral is not loss: overflow hits (never recorded as `nudge.sent`, so no cooldown) fire the next night | 8 stalled activations; night 1 sends 5, defers 3; `nightly(as_of=D+1)` | night 2 sends the 3 deferred (the 5 sent are in cooldown); by night 2 all 8 have exactly one `nudge.sent` | e2e |
| `e2e_judg_cooldown_inbound_break` | Cooldown broken only by a **new inbound** (`INBOUND_TYPES` after the last `nudge.sent`) | nudge c night 1; `sms_in(c)` next day; `nightly(D+1)` | re-nudged inside the 3-day window (upgrades the SQL-seeded discipline test to feed-driven) | e2e |
| `e2e_judg_converted_drops_out` | A nudged contact that converts stops generating nudges — stage `won` matches no contact rule | hot-response nudge night 1; `signup`; `nightly` nights 2–5 | no further `nudge.sent` for c | e2e |
| `e2e_judg_rollup_cooldown_per_wave` | Wave-level cooldown keys on `(rule, wave_id)`: two anomalous waves nudge independently; the same wave stays silent within cooldown | two waves each >8% failed pieces (via `return_mail`); `nightly(D)`, `nightly(D+1)` | night 1: two `wave_anomaly` nudges; night 2: zero (both in cooldown); night `D+3`: both again | e2e |
| `e2e_judg_hot_response_once_ever` | Pins the actual `hot_response` semantics: it fires only for a contact with **no `nudge.sent` of any kind, ever** — any prior nudge (even another rule's) permanently disqualifies | contact nudged once by `quiet_reengage` path, later becomes `responded` again | `hot_response` never fires for them (rare-case semantics worth pinning deliberately — if this surprises the founders, it is a rule change, not a test change) | e2e |
| `e2e_judg_human_plan_respected_then_passes` | A human `next_action` blocks nudges until it passes, then rules re-engage | `plan(c, D+2, "call thursday")`; stalled condition true throughout; `nightly(D)`, `nightly(D+1)`, `nightly(D+3)` | D and D+1: silent for c, note untouched; D+3 (date passed, `next_action_at > as_of` now false): fires | e2e |
| `e2e_judg_partial_to_stalled_handoff` | `activation_partial` (window `(as_of−stall_days, as_of−partial_days)`) hands off to `activation_stalled` at day 14 — mutually exclusive by construction, never both in one night | `activate(c, signed_days_ago=7)` then re-judge at advancing `as_of` past day 14 | day 7: partial fires, stalled doesn't; day 15+: stalled fires, partial doesn't; no night with both | e2e |
| `e2e_judg_digest_priority_order` | The digest message lists nudges in rule-priority order (prepared list sorted by `rule.priority`; hot_response=1 … lost_aging=9, orphan_events=10) | mixed hits across ≥3 rules under budget | `digest_for('young')[0]` line order matches priority order; `_format_digest` header `Today's nudges (N):` correct | e2e |

### H. Drift / approval races

| id | intent | setup | key assertions | tier |
|---|---|---|---|---|
| `e2e_race_suppress_after_preview` | The hash catches shrinkage, not just growth: preview → a contact opts out → old hash rejected → re-preview approves | preview; `opt_out` one audience member; approve with old hash; re-preview; approve with new | first approve raises `stale_preview` (409 over HTTP); second succeeds; `approved_audience_count` == post-suppression count | e2e |
| `e2e_race_variant_split_in_hash` | The hash covers the variant split too (`{"audience": ..., "variants": variant_split}`) — same audience, different split ⇒ different hash | two waves, same audience, splits `{v:1.0}` vs `{v:0.5, v2:0.5}` | `preview.state_hash` values differ | accept |
| `e2e_race_cancel_then_execute` | A cancelled wave can never fire — `execute_wave` requires status in `('approved','executing')` | draft → approve → `cancel_wave` → `drop()` and direct `execute_wave` | `run_drops` doesn't select it (status `cancelled`); direct call raises `ValidationError("not_executable")`; zero pieces | e2e |
| `e2e_drift_growth_at_exact_tolerance` | Boundary in the growth direction: 10 approved → 11 resolved is exactly 10%, `drift > DRIFT_TOLERANCE` is **false**, proceeds | approve at 10; `load` 1 more matching contact; drop | `halted is False`, 11 pieces (complements existing −10% shrink test) | e2e |
| `e2e_drift_shrink_beyond` | 10 approved → 8 resolved = 20% shrink halts | suppress 2 of 10 after approval | `halted is True`, reason quotes both counts, wave still `approved`, zero pieces | e2e |
| `e2e_drift_halt_then_reapprove_path` | After a halt, the recovery path is re-preview → (no re-approve possible: wave not `draft`) — pin what the operator can actually do | halted wave from above | `approve_wave` on it raises `not_draft`; `cancel_wave` still allowed (status `approved`); documents the real recovery = cancel + redraft | e2e |
| — | stale-hash growth direction / hash optional / draft & sent not executable | — | existing `test_approval_hash.py`, `test_execute_wave.py`; **skip** | — |

### I. Failure injection / graceful degradation

| id | intent | setup | key assertions | tier |
|---|---|---|---|---|
| `e2e_fail_sync_halts_everything` | A feed failure halts the nightly **before recompute and before judgment** — never judge stale state, never nudge off it either (existing test checks stage only; this adds the judgment tail) | stage a would-fire scenario; `FakeResponseFeed(fail=True)` among the feeds; `nightly` raises | stage un-recomputed; **zero** `nudge.sent` rows; `FakeSender.sent == []` | e2e |
| `e2e_fail_second_feed` | Multi-feed partial failure: feed A synced, feed B raises — A's facts persisted (safe under replay), recompute still never ran | feed A with 1 event, feed B `fail=True` | A's event ingested; stage stale; next clean `nightly` replays A harmlessly (idempotent) and completes | e2e |
| `e2e_fail_unknown_type_from_feed` | A feed yielding a type outside the closed taxonomy is a loud halt (`UnknownEventType`), not a silent skip | feed event with `type="piece.exploded"` | `nightly` raises `UnknownEventType`; nothing recomputed | e2e |
| `e2e_fail_composer_down_digest_sends` | Model outage degrades to templates, digest still delivered — through the full nightly, not just `digest.run` | firing scenario; `judge(as_of, ai=FailingAi)` with sender | brief starts `[<rule.name>]` (template shape); `FakeSender` got the digest (upgrades existing to include delivery) | e2e |
| `e2e_fail_zero_state_paths` | Zero-everything is silent everywhere: empty DB nightly, zero-hit digest, empty feeds | fresh world; `nightly` | no events, no nudges, `sender.sent==[]`, no exceptions | e2e |
| — | print-API mid-drop crash; empty-audience approve; zero-hit night | — | existing (`test_execute_is_resumable...`, `test_approve_rejects_empty_audience`, `test_a_zero_hit_night...`); **skip** | — |

### J. Date/threshold boundaries (run under `TZ=UTC`)

All rule comparisons are `timestamptz` against `as_of::date ± make_interval(days => N)` —
i.e. against **midnight UTC** of the boundary date, with **strict** inequality except where
noted. Each scenario is a fire/near-miss pair at the exact edge, driven through
`judge(as_of=...)` with feed events at controlled `occurred_at` (use `world.at(n, hour)` to
place events just before/after midnight).

| id | boundary pinned | exact semantics to assert | tier |
|---|---|---|---|
| `accept_bound_quiet_exact` | `quiet_reengage` at QUIET_DAYS=4 | fires iff `max(inbound occurred_at) < as_of − 4 days` (midnight, strict): an inbound at exactly midnight of `as_of−4` is a near-miss; one second earlier fires | accept |
| `accept_bound_day_edge` | day-boundary event timing | inbound at 23:59:59 of day `as_of−5` fires; at 00:00:00 of day `as_of−4` does not — one second flips the nudge | accept |
| `accept_bound_stall_exact` | `activation_stalled` at STALL_DAYS=14 | `signed_up_at < as_of − 14 days` strict: signup at exactly midnight `as_of−14` is a near-miss | accept |
| `accept_bound_partial_window` | `activation_partial` window edges (4 and 14) | fires iff `as_of−14 ≤ signed_up_at < as_of−4` (upper edge strict, lower edge inclusive `>=`); test all four sides | accept |
| `accept_bound_age_out_exact` | `lost_aging` at AGE_OUT_DAYS=30 | strict `<` on last inbound, **and** requires a prior `nudge.sent`; the never-nudged 40-day-quiet contact stays silent (near-miss exists; add the exact-day pair) | accept |
| `accept_bound_lead_days` | `approval_pending` at LEAD_DAYS=3 | **inclusive**: `scheduled_for <= as_of + 3` fires at exactly +3; +4 silent | accept |
| `accept_bound_cooldown_refire` | cooldown re-fire day (COOLDOWN_DAYS=3) | in `_in_cooldown`, not-in-cooldown iff `last.date() <= as_of − 3 days` — nudged on D, silent D+1/D+2, **fires again on exactly D+3** (existing test only checks D+1 and D+4) | accept |
| `accept_bound_expiry_exact` | expiry at EXPIRE_DAYS=5 | `expire_stale_actions` clears iff `next_action_at < as_of − 5 days` strict: a slot exactly 5 days old survives; 6 days clears | accept |
| `accept_bound_orphan_max` | `orphan_events` at ORPHAN_MAX=20 | strictly `>`: 20 silent, 21 fires (existing tests use 5 and 21; add the 20 near-miss) | accept |
| `accept_bound_fail_pct` | `wave_anomaly` at FAIL_PCT=0.08 | strictly `>`: 2/25 = 8% exactly is silent; 3/25 = 12% fires | accept |
| — | "after first piece" strictness (equal instant excluded); engagement strictness | — covered by `test_inbound_at_the_same_instant_as_the_piece_is_not_a_response` and `test_reply_at_the_same_instant...`; **skip** | unit |

### K. Data-integrity invariants (the data doc's deferred "continuous assertions", expressed as tests)

These are the reconciliation/liveness/integrity/distribution checks from data doc §3 and
implementation plan Phase 4 (`judgment/rules/assertions/` — **not yet built**, see §6.3).
Until they exist as production rules, pin them as tests over harness-produced worlds. Do
NOT build the production assertion rules as part of this work — that is a Phase 4 item
needing its own review; these tests are the interim scar tissue.

| id | invariant | setup + assertion | tier |
|---|---|---|---|
| `data_cost_completeness` | Every `submitted` piece has `cost_cents` and `lob_id` non-null and `submitted_at` set — "partial cost data makes every efficiency metric a lie" | after any multi-wave harness run: `select count(*) from pieces where status='submitted' and (cost_cents is null or lob_id is null or submitted_at is null)` == 0; also holds after a crash-resume drop | data |
| `data_piece_event_liveness` | No silent piece loss: every piece row has exactly one `piece.submitted` event (`external_id = 'submitted:<piece_id>'`) and vice versa | set-equality between piece ids and the events' `piece_id`s after golden + resume runs | data |
| `data_no_event_loss` | Every feed event ends up as exactly one row: per `(source, external_id)` count == 1, and total ingested == distinct external ids offered, even after deliberate replays | after `e2e_replay_*` histories | data |
| `data_variant_split_sanity` | A 50/50 split lands within tolerance and is stable: over 200 contacts, each variant gets 35–65% of pieces; re-running assignment reshuffles nobody (`_assign_variant` is deterministic per contact) | one 200-contact wave, two variants at 0.5/0.5; distribution bounds + per-contact variant identical on re-resolution | data |
| `data_no_piece_post_suppression` | No piece is ever created for a contact suppressed at execution time (flag or snapshot) | after the suppression scenarios: join pieces × contacts where `do_not_mail` or stage `suppressed`, filter to pieces created after the suppressing event — expect only the §E.3 known-window case (`e2e_supp_optout_before_recompute_window`), which this test cross-references explicitly | data |
| `data_nudge_payload_complete` | Every `nudge.sent` event carries `rule`, `brief`, `recipient` keys (wave-level ones also `wave_id`) — the audit answer to "why did I get this?" | after judgment-heavy runs: scan all `nudge.sent` payloads | data |
| `data_snapshot_fixpoint` | The snapshot cache is consistent with the stream: one extra `recompute_state()` after any harness scenario changes zero rows | run at the end of the golden scenarios (can be a shared post-condition helper rather than N copies) | data |
| `data_orphans_visible` | No fact dropped for want of a join: every feed event either has `contact_id` set or appears in the orphan count — none vanished | reconcile ingested external_ids vs (attributed ∪ orphaned) | data |

**Scenario count:** ~55 new tests specified (A:4, B:8, C:4, D:6, E:7, F:5, G:12, H:6, I:5,
J:10, K:8), plus ~10 explicit skips where existing frozen tests already pin the behavior.

---

## 5. What the fakes cannot prove (the ghost-wave boundary)

Hand this list to Phase 6 unmodified. A fully green fake suite still leaves ALL of the
following unproven — nobody may read green fakes as production-ready:

1. **Real Lob**: address verification, rendering, actual `?r=` QR encoding on the physical
   card, postage/cost truth (`FakePrintApi` returns a flat 73¢), Lob's real webhook
   payload shapes and **signature verification** (the fake's `parse_webhook` accepts
   unsigned JSON; the real `LobClient` contract tests against recorded payloads are a
   separate Phase 3 item, also not written yet).
2. **Real PostHog**: that the landing page actually captures `?r=` into the event payload
   under the key the matcher reads (`mailer_code`), pull-API pagination/latency, and
   `external_id` stability across pulls.
3. **Real NMC**: the "nevermisscall" vertical config, a real inbound call → SMS flow →
   booking, thread-id semantics of real conversations, and the real digest **sender**
   (SMS/email through NMC's sending path — `FakeSender` proves assembly, not delivery).
4. **Deliverability and time**: mail that takes days, returns that take weeks, the
   response tail RESP_CHECK_DAYS was invented for — wall-clock behavior of cron, `since`
   watermarks across real restarts.
5. **The AI composer against a real model**: brief quality, latency/timeout behavior
   (`ai/client.py` wiring). Fakes prove only the fallback discipline.
6. **Operational reality**: backup/restore of the events table (impl plan Phase 6 requires
   one restored backup with a readable timeline), Docker/VPS parity, real basic-auth on
   the HTTP window.

---

## 6. Executor notes

### Determinism and environment

- Run the suite under `TZ=UTC` (add to the make target / CI env). All harness datetimes
  are `UTC`-aware; naive datetimes are a bug in the test, not the system.
- Anchor `T0 = datetime.now(UTC)` per `World`; never a hardcoded date for anything
  compared against `now()` (approve requires `scheduled_for` strictly future; `drop`/
  `judge` take explicit `as_of`). Fixed dates are fine for pure-`as_of` judgment scenarios
  (existing `test_judgment_rules.py` uses `AS_OF = date(2026, 7, 1)` — same pattern).
- Seed data through verbs (`load` via temp CSV, events via feeds). The **only** SQL writes
  allowed in `tests/e2e/` are `World.activate()` (no verb exists) and, if `load_list`
  cannot set it, the contact `owner` column (see divergences) — both documented in the
  harness with the reason.
- Keep e2e scenarios fast: they share the session-scoped migrations fixture and the
  function-scoped `clean_db` truncate; the 200-contact distribution test is the largest —
  if it drags, mark it `@pytest.mark.nightly` like the existing 5k recompute test.

### Tier placement

- `tests/e2e/` — the harness scenarios (§4 A–I plus the boundary pairs that need the
  harness). **Frozen acceptance authority** once written: modifying or deleting one is an
  escalation, same as `tests/acceptance/`.
- `tests/acceptance/` — the pure-boundary pairs (§J) and small verb-level additions
  (`accept_*` ids) fit the existing per-phase files' style; add new files, never edit
  frozen ones.
- `tests/e2e/test_data_assertions.py` — the §K invariants. They are the interim stand-in
  for the Phase 4 production assertion rules; when those rules are eventually built, these
  tests become their fixtures — do not delete them then either.
- New unit tests only where you find internals worth scaffolding while building the
  harness; they remain disposable, no authority.

### Divergences found during this analysis — TRIAGED

The analysis surfaced six divergences. They were triaged; three were fixed (with tests),
three remain deferred. Any §-scenario above that assumed the old behavior asserts the
*new* behavior below.

**Resolved (fixed with a test):**

1. **The opt-out window — FIXED.** `suppress('opt_out')` now sets `do_not_mail = true` as
   well as `do_not_text`, so the audience resolver excludes an opted-out contact
   immediately, before the next recompute (matches the suppressed derivation:
   opt_out ⇒ suppressed ⇒ no mail). Test:
   `test_contacts.py::test_opt_out_halts_mail_immediately_without_a_recompute`.
2. **`run_drops` couldn't resume a crashed drop — FIXED.** It now selects
   `status in ('approved','executing')`, so the job resumes a wave left `executing` by a
   mid-drop crash (`execute_wave` is idempotent). Test:
   `test_jobs.py::test_run_drops_resumes_a_crashed_executing_wave`.
3. **`wave_anomaly` was half-built — FIXED.** The rule now also fires on a *dead* wave —
   out past `RESP_CHECK_DAYS` with zero response — not just on high failure rate. Tests:
   `test_judgment_rules.py::test_wave_anomaly_fires_on_a_dead_wave` (+ two near-misses).

**Deferred (recorded; the tests pin current behavior):**

4. **`load_list` has no `owner` mapping** (migration 0004 added `contacts.owner`, default
   `'young'`). Not needed yet — the CSLB list is entirely Young's; partner-owned contacts
   arrive via a not-yet-built affiliate-intake path. Routing tests use the documented SQL
   exception. When affiliate intake is built, `load_list` can honor an `owner` CSV column.
5. **`RULESET_VERSION`** (`derivation/rules.py`) is documented as "stamped on snapshots"
   but no column/write exists. Auditability, not function — deferred (needs a schema column).
6. **`judgment/rules/assertions/`** (the data doc's "continuous data assertions") was
   planned in Phase 4 and not built; it needs the missing `data.md §3` spec written first.
   §K pins those invariants as tests meanwhile.

### The standing rule (restated from the implementation plan, § Cross-cutting)

Every future production failure, ghost-wave surprise, e2e flake, and founder suspicion
("could the sync die silently?") ends by leaving a test behind at the appropriate tier —
usually a ~10-line harness scenario now that the `World` exists. The suite is the system's
accumulated scar tissue; it only grows.
