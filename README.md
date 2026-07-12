# mail-engine

NeverMissCall's direct-mail campaign operating system: a contact database as the
spine, waves of postcards executed out of it through a print API, response signals
(web + phone) flowing back in automatically, and AI on top as analyst and briefing
officer. Not a CRM — state writes itself from instrumented channels.

Design docs live in [`docs/`](docs/): PRD, current state, dress-rehearsal runbook,
vendor decisions, install guide.

## Technology

| Layer | Choice |
|-------|--------|
| Language / runtime | Python 3.12, [uv](https://docs.astral.sh/uv/) for deps & venv |
| Database | PostgreSQL 15+ — single spine DB, append-only `events` table, derived state recomputable from history |
| DB access | psycopg 3 (transaction-per-verb); separate read-only role for analysis |
| Migrations | yoyo-migrations (plain SQL files in `db/migrations/`) |
| Web | FastAPI + Uvicorn — a thin server-rendered window (Jinja2 + classless Pico.css); no JS framework, no build step |
| Jobs | Plain Python entry points (`jobs/`) run by cron: daily drops, nightly sync → recompute → judgment |
| Tests | pytest (+ hypothesis, mutmut available); acceptance suite doubles as the phase gates |
| Lint / types | ruff, pyright — both clean is the merge bar |

## Third-party integrations

All vendors sit behind seam modules (`seams/`) — one file per vendor, injected
transport, unit-testable without network. Nothing outside a seam imports a vendor.

| Vendor | Role | Seam |
|--------|------|------|
| **[Lob](https://lob.com)** | Postcard print & mail. One API call per piece with the mailer code as idempotency key; delivery status back via HMAC-verified webhooks (fail-closed). PostGrid is the named one-file fallback. | `seams/lob.py` |
| **[PostHog](https://posthog.com)** | Web-response feed. The landing page (separate repo) captures `?r=<mailer-code>` visits/checkouts cookielessly; the nightly job pulls them via the HogQL Query API and lands them as canonical events. | `seams/posthog.py` |
| **NeverMissCall** | Phone-response feed (planned): the campaign line is NMC's own SMS-first sales AI — the product demoing itself. Consumed through the same `ResponseFeed` contract as any third party. | `seams/nmc.py` (planned) |
| **Anthropic Claude** | Optional: composes the 30-second nudge briefs (template fallback — delivery never depends on the model) and answers ad-hoc analysis questions over the read-only SQL role. | `ai/` |

Related but separate: the landing pages themselves (`getnevermisscall.com`) live in
their own repo — static HTML on Netlify with PostHog capture and a Stripe/Medusa
checkout. This repo only consumes their PostHog events.

## Layout

```
domain/      value types, enums (mirror the DDL), closed event taxonomy
db/          migrations (yoyo), transaction-per-verb session, read-only connection
service/     the ONLY write path — contract verbs (waves, contacts, ingestion, queries)
derivation/  versioned pure functions: event stream -> contact stage
resolution/  identity resolution (mailer code -> thread -> exact phone; never fuzzy)
seams/       vendor clients + fakes (Lob, PostHog, print/feed/sender contracts)
jobs/        cron entry points: run_drops, sync, run_nightly
judgment/    nightly rules -> nudges -> morning digest (budget, cooldown, expiry)
intake/      per-source list adapters (CSLB, CA FBN) -> canonical intake CSV
web/         FastAPI window over service verbs (no logic in routes)
ai/          AI brief composition (optional, template fallback)
config/      tunable parameters (judgment thresholds, budgets)
tests/       acceptance/ (frozen, the phase gates) + unit/ (disposable)
```

## Quick start

```bash
cp .env.example .env      # then set real local passwords
uv sync                   # install deps into .venv
make up                   # start Postgres 15 (docker) — or point .env at a local one
make migrate              # apply the schema
make test                 # run the suite  (⚠ truncates the configured DB)
make run                  # web window on http://127.0.0.1:8001
```

`make help` lists every target. See [`docs/INSTALL.md`](docs/INSTALL.md) for the
full variable reference and production notes.
