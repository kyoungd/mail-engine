.DEFAULT_GOAL := help
.PHONY: help up down migrate console test e2e lint fmt nuke

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

lint: ## Lint (ruff) and type-check (pyright)
	uv run ruff check .
	pyright

fmt: ## Auto-format with ruff
	uv run ruff format .

nuke: ## Stop Postgres and destroy the data volume
	docker compose down -v
