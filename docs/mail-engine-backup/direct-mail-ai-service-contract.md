# Direct Mail AI — Service Layer Contract

*The single contract through which anything changes state. Companion to the data document.*

---

## 1. Shape and ground rules

The service layer is a typed module (Python or TypeScript, matching the NMC stack), not a network service. The web UI consumes it through a thin HTTP wrapper; jobs and Claude Code import it directly. One codebase, one contract, three consumers.

**Rule 1 — writes never bypass.** Every state change in the system goes through a verb below. No consumer — UI, job, Claude Code, or a founder in `psql` — writes tables directly. This is the encapsulation standard: the module is impossible to misuse from outside because the tables aren't reachable from outside.

**Rule 2 — reads may bypass.** Ad-hoc analysis is direct SQL against a read-only role. Wrapping every conceivable question in a contract verb would rebuild the BI tool we excluded; the read-only role makes bypass safe. The UI's fixed panels use the query verbs below only because they recur.

**Rule 3 — every fact is an event first.** Verbs that record a new fact append to `events`, then update snapshots. The event is the truth; the snapshot update is a courtesy to readers. A new fact that changed a snapshot without leaving an event is a bug by definition. Re-derivation is not a write in this sense: `recompute_state` (and `execute_wave` where it refreshes derived snapshots) recomputes the courtesy cache from events already appended, and correctly emits nothing — no new fact, no new event. A recompute that logged an event per contact would fill the stream with derivation noise, not truth.

**Rule 4 — all writes are idempotent.** Callers supply idempotency keys (or the verb derives one, e.g. `(source, external_id)` on ingestion). Jobs re-run safely; the UI can double-submit harmlessly.

**Rule 5 — verbs validate, never interpret.** `approve_wave` checks the wave is approvable; it doesn't decide whether approving is wise. Judgment lives in the judgment job and the humans. The contract is deliberately dumb muscle.

---

## 2. The verbs

### Ingestion (used by sync jobs, webhooks, and the voice-note pipeline)

```
ingest_event(source, type, occurred_at, payload,
             external_id=None, contact_id=None, piece_id=None) -> EventId
    Appends a fact. Rejects unknown `type` (taxonomy is closed).
    Idempotent on (source, external_id). Attribution optional at write time.

resolve_orphans(since=None) -> ResolutionReport
    Runs the identity-resolution precedence chain over unmatched events.
    Never fuzzy-matches. Returns what it matched and what remains orphaned.

record_note(contact_id, note_type, text) -> EventId
    Human residue capture. Wraps ingest_event(source='human').
    AI-structuring of raw voice notes happens before this call.
```

### List and contacts

```
load_list(csv_path, source='cslb') -> IntakeReport
    Bulk intake of a canonical intake CSV (produced by a per-format adapter
    in intake/ — e.g. intake/fbn_ca.py). Dedupe on list_key, normalize phones
    to E.164, NCOA/CASS validation. A row must be targetable (trade or
    segment) or it is invalid. Returns counts: loaded, deduped, invalid,
    suppressed.

suppress(contact_id, reason: 'do_not_mail'|'opt_out') -> None
    Sets the human-authored flag AND appends contact.opt_out event.
    Irreversible by design; no unsuppress verb exists.

record_outcome(contact_id, outcome: 'lost', reason) -> EventId
    Human judgment that a conversation is over. ('won' is never declared
    manually — it derives from signup.completed.)

set_next_action(contact_id, date, note) -> None
    Founder override of the judgment job's slot. The job won't overwrite
    a human-set action until it passes.
```

### Creative and waves

```
create_variant(name, hypothesis, creative) -> VariantId
    Hypothesis is required and non-empty. This is the schema enforcing
    the information-buying posture; no exceptions parameter exists.

draft_wave(name, drop_number, audience_rule, variant_split,
           scheduled_for) -> WaveId
    Persists the rule as data. Does not resolve the audience.

preview_audience(wave_id) -> AudiencePreview
    Resolves audience_rule NOW against current state: count, breakdown
    by segment/stage, estimated cost, and a sample of 10 contacts.
    This is what the approval screen renders — you approve what you saw.

approve_wave(wave_id, approved_by) -> None
    Validates: status='draft', variants exist, audience resolves to >0,
    scheduled_for is future. Records who and when. Does NOT execute.

cancel_wave(wave_id) -> None
    Valid until status='executing'. After that, mail is physical.
```

### Execution (called by jobs only; not exposed to UI)

```
execute_wave(wave_id) -> ExecutionReport
    Drop job's verb. Re-resolves the audience at execution time, creates
    piece rows (the permanent record), assigns mailer codes, submits to
    the print API. Halts and alerts on any variant/audience drift beyond
    tolerance vs. the approved preview. Idempotent: re-run continues,
    never duplicates (unique contact_id+wave_id does the enforcement).

recompute_state(contact_id=None) -> RecomputeReport
    Reruns derivations from the event stream. Called nightly for
    incremental updates; callable over all history after a definition
    change. do_not_mail and human-set next_action survive recomputation.
    Emits no events — it introduces no facts, only refreshes the
    derived snapshots (Rule 3).
```

### Queries (the recurring reads the UI panels are built on)

```
get_wave_dashboard(wave_id) -> WaveDashboard
    Pieces by status, response counts by variant, cost-per-response.

get_approval_queue() -> [WaveSummary]

get_contact_timeline(contact_id) -> [Event]
    The full story of one contact, human-readable. The single most used
    view when a prospect calls back.

get_pipeline() -> [ContactCard]
    Contacts in responded/in_conversation, with last inbound, next
    action, and days quiet. The "CRM" in its entirety.

get_activation_board() -> [ActivationCard]
    Won customers with checklist status; stalled ones flagged.

list_due_nudges(as_of=today) -> [Nudge]
    What the push system sends this morning. Also renderable in UI
    for the same-page view of what the system is thinking.
```

---

## 3. What is deliberately not in the contract

- **No analytics verbs.** "Cost per response by segment across waves" is SQL through the read-only role, composed conversationally. The moment a question recurs every wave, it earns a query verb — not before.
- **No edit/delete verbs for events.** Append-only means append-only. Corrections are new events (`type='correction'`, payload pointing at the mistaken event id).
- **No auth machinery.** `approved_by` is a name string. Two founders; the audit trail matters, the access control theater doesn't. The HTTP wrapper sits behind a private network / basic auth.
- **No generic `update_contact`.** Every legitimate mutation has a named verb with semantics. A generic setter is how derived fields get hand-edited and truth forks.

---

## 4. Error philosophy

Verbs fail loudly and completely — no partial writes (each verb is one transaction). Validation failures return structured reasons the UI can render and Claude Code can read. The one verb allowed to partially succeed is `execute_wave` (physical mail submits piece-by-piece); it is therefore the one verb with a resumable report and the idempotency to be re-run until clean.

---

*Next: the judgment job rule set — the nightly evaluation that fills `next_action_at` and emits nudges.*
