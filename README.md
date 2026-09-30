# contact-engine

NeverMissCall's contact services for the sales-partner dialer: it holds every
business a rep might call and answers one question for the dialer — **who may this
rep call right now, and what do we know about them?** Intake, DNC filtering, time
zone, assignment, the calling rule, and answering the dialer and the website.

This is the `contact-engine` branch. It was mail-engine, a direct-mail campaign
system; the mail code, the web pages, and the messages were removed here (part 0 of
the upgrade). Production still runs mail-engine from `main` until contact-engine is
complete and hosted. The folders, the repository, and the databases keep their old
names.

Design docs live in [`docs/`](docs/): the [PRD](docs/PRD.md), the
[current state](docs/current-state.md), and the upgrade's parts in
[`docs/contact-engine/`](docs/contact-engine/). mail-engine's documents are kept
in [`docs/mail-engine-backup/`](docs/mail-engine-backup/).

## Technology

| Layer | Choice |
|-------|--------|
| Language / runtime | Python 3.12, [uv](https://docs.astral.sh/uv/) for deps & venv |
| Database | PostgreSQL 15+ — single spine DB, append-only `events` table, derived state recomputable from history |
| DB access | psycopg 3 (transaction-per-verb); separate read-only role for analysis |
| Migrations | yoyo-migrations (plain SQL files in `db/migrations/`) |
| Jobs | Plain Python entry points (`jobs/`): the DNC pull and scrub, the nightly, the operator CLIs |
| Tests | pytest (+ hypothesis, mutmut available); acceptance suite doubles as the phase gates |
| Lint / types | ruff, pyright — both clean is the merge bar |

## Layout

```
domain/      value types, enums (mirror the DDL), closed event taxonomy
db/          migrations (yoyo), transaction-per-verb session, read-only connection
service/     the ONLY write path — contract verbs (contacts, assignment, custody, ingestion)
derivation/  versioned pure functions: event stream -> contact stage
resolution/  identity resolution (mailer code -> thread -> exact phone; never fuzzy)
seams/       external clients + fakes (DNC registry, snapshot inbox, close feed, main site)
jobs/        cron entry points and operator CLIs (intake, DNC, assignment, nightly, console)
intake/      per-source list adapters (CSLB, CA FBN) -> canonical intake CSV
config/      tunable parameters
tests/       acceptance/ (frozen, the phase gates) + unit/ (disposable) + e2e/
```

## Quick start

```bash
cp .env.example .env      # then set real local passwords
uv sync                   # install deps into .venv
make up                   # start Postgres 15 (docker) — or point .env at a local one
make migrate              # apply the schema
make test                 # run the suite (truncates mailengine_test, never dev)
python -m jobs.intake_cli <file> --source cslb-ca   # load a list
```

`make help` lists every target.
