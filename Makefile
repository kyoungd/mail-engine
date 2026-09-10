.DEFAULT_GOAL := help
.PHONY: help up down migrate run console test e2e e2e-mail integration seed-contacts lint fmt nuke

help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

up: ## Start Postgres and wait until healthy
	docker compose up -d --wait

down: ## Stop Postgres (keeps data volume)
	docker compose down

migrate: ## Apply migrations as the owner role, then the grain swap (ground rule 4)
	@set -a && . ./.env && set +a && \
		uv run yoyo apply --batch --database "$$OWNER_DATABASE_URL" db/migrations && \
		uv run python -m jobs.migrate_grain --ensure-swapped

client: ## Build ONE rep's uploader (PARTNER="Jane Doe") — issues a token, then bakes it in
	@set -a && . ./.env && set +a && \
		[ -n "$(PARTNER)" ] || { echo 'usage: make client PARTNER="Jane Doe"'; exit 2; } && \
		[ -n "$$SNAPSHOT_INBOX_URL" ] || { echo 'SNAPSHOT_INBOX_URL is unset — deploy the Worker first (Phase 5d)'; exit 2; } && \
		echo "issuing a token for $(PARTNER) — this ROTATES it; any previous copy stops working" && \
		TOKEN=$$(PYTHONPATH=. uv run python -m jobs.partners_cli issue-token "$(PARTNER)" \
			| awk '/^  nmcdnc_/ {print $$1}') && \
		[ -n "$$TOKEN" ] || { echo 'no token was issued — nothing built'; exit 1; } && \
		uv run python scripts/build_client.py --partner "$(PARTNER)" \
			--token "$$TOKEN" --url "$$SNAPSHOT_INBOX_URL"

run: ## Start the web window (sources .env)
	@set -a && . ./.env && set +a && \
		uv run uvicorn web.api:app --host 127.0.0.1 --port $${WEB_PORT:?WEB_PORT not set in .env}

console: ## Operator menu over the partner/DNC CLIs (sources .env)
	@set -a && . ./.env && set +a && PYTHONPATH=. uv run python -m jobs.console

test: ## Run the test suite (fast, offline; e2e+integration deselected; truncates mailengine_test, never dev)
	@set -a && . ./.env && set +a && \
		uv run python scripts/ensure-test-db.py && \
		export OWNER_DATABASE_URL="$${OWNER_DATABASE_URL%/*}/mailengine_test" \
		       READONLY_DATABASE_URL="$${READONLY_DATABASE_URL%/*}/mailengine_test" && \
		uv run pytest

e2e: ## Partner-lifecycle journey (the live product; truncates mailengine_test, never dev)
	@set -a && . ./.env && set +a && \
		uv run python scripts/ensure-test-db.py && \
		export OWNER_DATABASE_URL="$${OWNER_DATABASE_URL%/*}/mailengine_test" \
		       READONLY_DATABASE_URL="$${READONLY_DATABASE_URL%/*}/mailengine_test" && \
		uv run pytest -m e2e tests/e2e/test_partner_journey.py -v

e2e-mail: ## PARKED to v1.1 — mail funnel vs the REAL Lob test env; rejoins `e2e` at un-park
	@set -a && . ./.env && set +a && \
		uv run python scripts/ensure-test-db.py && \
		export OWNER_DATABASE_URL="$${OWNER_DATABASE_URL%/*}/mailengine_test" \
		       READONLY_DATABASE_URL="$${READONLY_DATABASE_URL%/*}/mailengine_test" && \
		uv run pytest -m e2e tests/e2e/test_journey.py -v

integration: ## Read-only pins vs live cross-repo seams (skips what isn't running; STRICT=1 fails on skips)
	@set -a && . ./.env && set +a && \
		uv run pytest -m integration tests/integration -v $${STRICT:+--integration-strict}

seed-contacts: ## Upsert founder seed addresses from config/seeds.json (idempotent)
	@set -a && . ./.env && set +a && uv run python -m jobs.seed_cli

lint: ## Lint (ruff) and type-check (pyright)
	uv run ruff check .
	pyright

fmt: ## Auto-format with ruff
	uv run ruff format .

nuke: ## Stop Postgres and destroy the data volume
	docker compose down -v
