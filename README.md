# mail-engine

NeverMissCall's direct-mail campaign operating system. Design docs live one level
up (`../PRD.md`, `../direct-mail-ai-*.md`, `../mail-engine-product-description.md`).

## Layout (Phase 0)

```
domain/   value types, enums (mirror the DDL), closed event taxonomy
db/       migrations (yoyo), transaction-per-verb session, read-only connection
tests/    acceptance/ (frozen, the phase gates) + unit/ (disposable)
```

## Quick start

```bash
cp .env.example .env      # then set real local passwords
uv sync                   # install deps into .venv
make up                   # start Postgres 15 (port 5433)
make migrate              # apply the schema
make test                 # run the acceptance suite
```

`make help` lists every target.
