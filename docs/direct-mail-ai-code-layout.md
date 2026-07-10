# Direct Mail AI — Code Layout

*Module structure and the interface signatures not already fixed by the service contract document. Python-flavored; translates 1:1 to TypeScript if that matches the NMC stack better.*

---

## Repo shape

```
mail-engine/
├── domain/
│   ├── types.py          # dataclasses: Contact, Wave, Piece, Event, Nudge, previews/reports
│   ├── enums.py          # contact_stage, wave_status, piece_status, event_source (mirrors DDL)
│   └── taxonomy.py       # EVENT_TYPES: the closed set; is_valid_type()
├── db/
│   ├── migrations/       # the DDL, versioned
│   ├── session.py        # transaction-per-verb helper
│   └── readonly.py       # read-only role connection (the analysis bypass)
├── service/              # THE contract — the only writers
│   ├── ingestion.py      # ingest_event, resolve_orphans, record_note
│   ├── contacts.py       # load_list, suppress, record_outcome, set_next_action
│   ├── waves.py          # create_variant, draft_wave, preview_audience, approve_wave, cancel_wave
│   ├── execution.py      # execute_wave, recompute_state  (jobs-only; not routed in HTTP layer)
│   └── queries.py        # get_wave_dashboard, get_pipeline, get_contact_timeline, ...
├── derivation/
│   └── rules.py          # pure functions; RULESET_VERSION
├── resolution/
│   └── matcher.py        # precedence chain; never fuzzy
├── seams/                # anti-corruption layer — nothing above imports vendor SDKs
│   ├── print_api.py      # PrintApi interface
│   ├── lob.py            # LobClient(PrintApi)
│   ├── response_feed.py  # ResponseFeed interface
│   ├── posthog.py        # PostHogFeed(ResponseFeed)
│   └── nmc.py            # NmcFeed(ResponseFeed)  — own product, same discipline
├── judgment/
│   ├── rules/            # one file per rule; auto-registered
│   ├── protocol.py       # Rule interface
│   ├── composer.py       # AI briefing (+ template fallback)
│   └── digest.py         # budget, cooldown, expiry, send
├── ai/
│   └── client.py         # single model-call wrapper: composer + note structuring share it
├── jobs/
│   ├── nightly.py        # orchestrator: sync → recompute → judgment (order matters)
│   ├── sync.py           # runs each ResponseFeed through ingestion
│   └── drop.py           # picks up approved+due waves → execution.execute_wave
├── web/
│   ├── api.py            # thin HTTP over service/ (FastAPI); no logic
│   └── ui/               # the window + approval button
└── config/
    └── params.py         # judgment parameters; reads config table
```

Dependency rule (enforced by imports, checkable in review): `web` and `jobs` → `service` → `derivation`/`resolution` → `domain`. `seams` is imported only by `jobs` and `service/execution`. Nothing imports upward. `db.readonly` is importable from anywhere (it can't write).

---

## Signatures not yet fixed elsewhere

### derivation/rules.py — pure functions, no I/O

```python
RULESET_VERSION: str  # bump on any definition change; recorded on snapshots

def derive_stage(events: list[Event], flags: ContactFlags) -> contact_stage: ...
def is_responded(events: list[Event]) -> bool: ...
def quiet_days(events: list[Event], as_of: date) -> int | None: ...
def is_suppressed(events: list[Event], flags: ContactFlags) -> bool: ...
```

Pure `events -> judgment`, no database access. This is what makes full-history
recomputation trivial and the definitions unit-testable with fixture lists.
`recompute_state` in the service layer does the I/O and calls these.

### seams/print_api.py

```python
class PrintApi(Protocol):
    def verify_address(self, addr: Address) -> AddressVerdict: ...
    def submit_piece(self, piece: Piece, creative: Creative) -> SubmissionResult: ...
    def parse_webhook(self, raw: bytes, headers: dict) -> Event: ...
        # vendor payload -> canonical taxonomy event; vendor names never leak upward
    def cost_estimate(self, spec: PieceSpec, qty: int) -> Money: ...
```

`LobClient` implements it; a `PostGridClient` later is a new file, zero changes above.

### seams/response_feed.py

```python
class ResponseFeed(Protocol):
    source: event_source
    def pull_events(self, since: datetime) -> Iterator[Event]: ...
        # yields canonical events with external_id set (idempotency key);
        # attribution fields best-effort (mailer code if present, else null)
```

`PostHogFeed` and `NmcFeed` both implement it. NMC gets no special access
despite being our own product — same contract, same discipline.

### judgment/protocol.py

```python
class Rule(Protocol):
    name: str            # 'quiet_reengage' — appears in nudge payloads verbatim
    priority: int        # digest ranking; lower = first
    recipient: Recipient # DEAL_OWNER | YOUNG

    def evaluate(self, ro: ReadOnlyDB, params: Params, as_of: date) -> list[Hit]: ...

@dataclass
class Hit:
    contact_id: UUID | None   # None for roll-ups (orphan_events, wave_anomaly)
    wave_id: UUID | None
    facts: dict               # what matched — becomes the audit answer to "why?"
```

One rule per file in `judgment/rules/`; the job discovers and runs all of them.
Adding a rule = adding a file. No registry to update.

### judgment/composer.py

```python
def compose_brief(hit: Hit, timeline: list[Event], rule: Rule) -> str: ...
    # AI call; MUST return within timeout or raise — caller falls back:
def template_brief(hit: Hit, rule: Rule) -> str: ...
    # always succeeds; delivery never depends on the model
```

### jobs/nightly.py — the one orchestration

```python
def run_nightly() -> None:
    for feed in feeds: sync(feed)          # facts in
    service.execution.recompute_state()    # judgments refreshed
    judgment.run(as_of=today)              # nudges out
    # strict order; a sync failure halts before recompute — never judge stale state
```

---

## What deliberately has no class

No `Campaign` aggregate object, no repository pattern, no domain-event bus. The
database rows plus the verb modules ARE the model; adding an object layer between
them at this scale is ceremony. The three interfaces above exist only where a
real substitution or a real fallback exists (vendor swap, feed addition, model
outage) — the encapsulation standard applied honestly: seams where variation is
real, none where it's speculative.
