.DEFAULT_GOAL := help
.PHONY: help up down migrate run test lint fmt nuke

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

up: ## Start Postgres and wait until healthy
	docker compose up -d --wait

down: ## Stop Postgres (keeps data volume)
	docker compose down

migrate: ## Apply migrations as the owner role
	@set -a && . ./.env && set +a && \
		uv run yoyo apply --batch --database "$$OWNER_DATABASE_URL" db/migrations

run: ## Start the web window (sources .env)
	@set -a && . ./.env && set +a && \
		uv run uvicorn web.api:app --host 127.0.0.1 --port 8000

test: ## Run the test suite
	uv run pytest

lint: ## Lint (ruff) and type-check (pyright)
	uv run ruff check .
	pyright

fmt: ## Auto-format with ruff
	uv run ruff format .

nuke: ## Stop Postgres and destroy the data volume
	docker compose down -v
