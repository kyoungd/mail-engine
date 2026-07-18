# E2E Journey Test — Plan and Implementation

*Status: planned (approved in session 2026-07-17). The full-funnel rehearsal: wipe →
intake → creative → wave → proof → approve → drop → verify against real Lob (test
environment). One command answers "did my change break the funnel?"*

---

## 1. Why

The unit/acceptance suite is green because every vendor call is faked and every test
builds its own tiny state. The failures that actually bite (duplicate wave name from
real form state, Lob 422s on real creative, stale dev-DB state) live in the seams the
fakes skip. The journey test walks the entire funnel through the same HTTP window the
founder clicks, against the **real Lob test environment** — no fakes anywhere.

It is also the software half of the Phase-6 ghost wave: rehearse the whole pipeline
free in Lob test mode, so the paid ghost wave (~10 real pieces) validates only paper
and delivery, not code.

## 2. Decisions

| Decision | Choice | Why |
|---|---|---|
| Harness | pytest module, `e2e` marker | Inherits `tests/guard.py` for free: the session refuses to start unless the DB is `mailengine_dev`/`mailengine_test` AND the Lob key is `test_`. Step 1 wipes the DB — that guard must be fail-closed, not hand-rolled in bash. |
| Driver | `TestClient` against the real `web.api:app` | Exercises the same thin-window routes the founder uses, including `/drops/run` with `DROP_PASSWORD` — the one routed execution trigger. No parallel path that could diverge from the UI. |
| Vendor | Real Lob **test** key (`LOB_TEST_API_KEY` == dev `LOB_API_KEY`) | Proofs and postcards render for real; nothing prints, no money moves. Catches the 422 class (name >40 chars, bad HTML) that injected transports cannot. |
| Default suite | `make test` skips e2e (network, ~30s+) | `addopts = -m "not e2e"`; `make e2e` overrides with `-m e2e`. Same registered-marker pattern as `nightly`. |
| Creative | A real one: `creative/w1-6x9-loss-math` | The journey should push what wave 1 will actually push, not `{"front": "f"}`. |
| Scope | Happy path + idempotent replay only | Error paths (duplicate name, stale hash, drift halt) are owned by the acceptance tests. The journey proves the funnel, twice — the second run proving resumability against the real vendor. |

## 3. The journey (the contract — asserts at every step)

1. **Wipe** — truncate all six tables (`clean_db`-style; guard already proved the DB
   is disposable).
2. **Intake** — POST a fixture CSV (~6 contacts, raw CSLB columns: `LicenseNo`,
   `BusinessName`, `MailingAddress`, `City`, `State`, `ZIPCode`, `BusinessPhone`,
   `PrimaryStatus=CLEAR`, `Classifications(s)`, …) to `/intake`, `source=cslb` →
   IntakeReport counts match the fixture (loaded / deduped / invalid rows are all
   deliberately present in it).
3. **Creative** — `POST /variants` with `w1-6x9-loss-math`'s real front/back HTML,
   size 6x9, its hypothesis → variant appears in the catalog.
4. **Wave** — `POST /waves/new` (form route) → 303 to the approve screen.
5. **Preview + proof** — GET the approve screen → **real Lob test render**: proof PDF
   URL embedded, `state_hash` in the form. Then GET the PDF itself with retry
   (Lob renders async; poll a few seconds) → body starts `%PDF`.
6. **Approve** — POST with the carried `state_hash` → wave `approved`.
7. **Drop** — `POST /drops/run` with `DROP_PASSWORD` (from env) and `as_of` = the
   scheduled date → ExecutionReport: `halted=False`, all pieces submitted.
8. **Verify against Lob itself** — for each piece row: `lob_id` set, `status=
   'submitted'`, mailer codes unique; GET `https://api.lob.com/v1/postcards/{lob_id}`
   with the test key → the postcard exists in Lob's test environment.
9. **Idempotency replay** — `POST /drops/run` again → zero new pieces, zero new
   Lob postcards (piece count and lob_ids unchanged). The resumability guarantee,
   proven against the real vendor.
10. *(webhook — out of scope: Lob cannot call localhost; signature/parse is
    unit-covered by `test_lob.py`.)*

## 4. Implementation

### New files

**`tests/e2e/__init__.py`** — empty.

**`tests/e2e/fixtures/cslb-journey.csv`** — ~8 rows of raw CSLB format:
6 CLEAR C36/C20 rows with Lob-deliverable test addresses (Lob's SF example block),
1 non-CLEAR row (must be filtered), 1 duplicate LicenseNo (must dedupe). Fake
businesses, fake phones in valid E.164-able shapes — never real people.

**`tests/e2e/test_journey.py`** — one module, `pytestmark = pytest.mark.e2e`, steps
1–9 as ONE test function (the journey is sequential state; separate tests would
re-run earlier stages or hide ordering). Helper structure:

```python
pytestmark = pytest.mark.e2e

def test_full_funnel_journey(owner_url, applied_migrations):
    _wipe(owner_url)                                   # step 1
    report = _intake(client, FIXTURE_CSV)              # step 2  asserts counts
    variant_id = _create_variant(client)               # step 3  real creative
    wave_id, approve_url = _draft_wave(client, ...)    # step 4
    proof_url, state_hash = _approve_screen(client, approve_url)   # step 5
    _fetch_pdf_with_retry(proof_url)                   # step 5b  %PDF
    _approve(client, wave_id, state_hash)              # step 6
    report1 = _run_drops(client, password, as_of)      # step 7
    pieces = _verify_pieces_in_db_and_lob(owner_url)   # step 8
    report2 = _run_drops(client, password, as_of)      # step 9  replay: no deltas
```

No `dependency_overrides` — the app's real `_proof_client` runs (dev `.env` has
`LOB_TEST_API_KEY`). `_fetch_pdf_with_retry`: GET up to ~6 × 4s until body starts
`%PDF` (observed: Lob's asset URL 500s for a few seconds while rendering).

### Modified files

**`pyproject.toml`**
```toml
[tool.pytest.ini_options]
addopts = "-m 'not e2e'"          # default suite stays fast and offline
markers = [
    "nightly: ...",
    "e2e: full-funnel journey against real Lob test env (make e2e)",
]
```

**`Makefile`**
```make
e2e: ## Full-funnel journey vs real Lob test env (wipes mailengine_dev!)
	@set -a && . ./.env && set +a && uv run pytest -m e2e tests/e2e -v
```
(`make test` keeps its exact current behavior minus e2e; `-m e2e` on the CLI
overrides the addopts deselection.)

**`../test-mail-engine.sh`** — mention `make -C mail-engine e2e` in `--help`.

### Safety (unchanged machinery, no new code)

- `tests/guard.py` halts the whole session unless DB ∈ {mailengine_dev,
  mailengine_test} and `LOB_API_KEY` is not `live_` — so the journey **cannot** run
  in `mail-engine-production/` or against prod data. The wipe inherits this.
- `DROP_PASSWORD` comes from the dev `.env`; the journey never embeds a password.
- Real Lob test mode: renders are free, nothing prints, no money moves.

## 5. How to run

```bash
cd mail-engine
make up          # if Postgres isn't running
make e2e         # ⚠️ wipes mailengine_dev, then walks the funnel (~30–60s, network)
make test        # unchanged: fast suite, no network, no e2e
```

After a run, mailengine_dev contains the journey's wave/pieces — same caveat as
`make test`: re-ingest real dev data if you need it (docs/current-state.md).

## 6. Definition of done

- `make e2e` green from a cold DB, twice in a row (second run re-wipes; proves the
  journey is self-contained).
- `make test` still green, still offline, count unchanged (± the deselected e2e).
- A deliberately broken creative (e.g. recipient name >40 chars in the fixture, or
  malformed HTML) makes the journey fail at the step that owns it — verified once
  manually during build, not kept as a permanent test.
