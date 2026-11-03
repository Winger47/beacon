# Kata developer tasks. Run from the repo root.
.DEFAULT_GOAL := help

COMPOSE := docker compose -f deploy/compose/docker-compose.yml
PROFILE ?= core

# Detect optional toolchains so local runs degrade gracefully (CI installs them).
HAVE_GO  := $(shell command -v go 2>/dev/null)
HAVE_BUF := $(shell command -v buf 2>/dev/null)
HAVE_LINT := $(shell command -v golangci-lint 2>/dev/null)

.PHONY: help up down logs ps test lint migrate migrate-down seed proto api-run openapi \
        test-py test-go test-web lint-py lint-go lint-web clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  Compose profile: PROFILE=$(PROFILE)  (core | ingest | observability | full)"

# ----------------------------------------------------------------- stack
up: ## Start the local stack (PROFILE=core by default; use PROFILE=full for everything)
	$(COMPOSE) --profile $(PROFILE) up -d

down: ## Stop the local stack and remove containers
	$(COMPOSE) --profile full down

logs: ## Tail logs for the running stack
	$(COMPOSE) --profile full logs -f

ps: ## Show stack status
	$(COMPOSE) --profile full ps

# ------------------------------------------------------------------ test
test: test-py test-go test-web ## Run unit tests across all languages

test-py: ## Python tests
	uv run pytest

test-go: ## Go tests (skipped if go is not installed)
ifeq ($(HAVE_GO),)
	@echo "[skip] go not installed; skipping Go tests"
else
	go test ./...
endif

test-web: ## Web tests
	cd web && npm run -s test

# ------------------------------------------------------------------ lint
lint: lint-py lint-go lint-web ## Lint across all languages

lint-py: ## Python lint + types
	uv run ruff check .
	uv run mypy packages/kata-domain/src packages/kata-parsers/src services/core-api/src

lint-go: ## Go lint (skipped if golangci-lint is not installed)
ifeq ($(HAVE_LINT),)
	@echo "[skip] golangci-lint not installed; skipping Go lint"
else
	golangci-lint run
endif

lint-web: ## Web lint + typecheck + format check
	cd web && npm run -s lint && npm run -s typecheck && npm run -s format:check

# ------------------------------------------------------------------ proto
proto: ## Lint protobuf (and generate code once the real contract lands)
ifeq ($(HAVE_BUF),)
	@echo "[skip] buf not installed; skipping proto lint"
else
	buf lint
endif

# ---------------------------------------------------------------------- db
# src-layout packages need to be importable by Alembic; set PYTHONPATH explicitly.
PYSRC := $(CURDIR)/packages/kata-domain/src:$(CURDIR)/packages/kata-parsers/src:$(CURDIR)/services/core-api/src

migrate: ## Apply core-api DB migrations (alembic upgrade head)
	cd services/core-api && PYTHONPATH="$(PYSRC)" uv run --project "$(CURDIR)" alembic upgrade head

migrate-down: ## Roll back the last migration (alembic downgrade -1)
	cd services/core-api && PYTHONPATH="$(PYSRC)" uv run --project "$(CURDIR)" alembic downgrade -1

FINDINGS ?= 1000000
PRODUCTS ?= 50
api-run: ## Run core-api locally with dev auth (http://localhost:8001)
	cd services/core-api && PYTHONPATH="$(PYSRC)" KATA_DEV_AUTH=true \
		uv run --project "$(CURDIR)" uvicorn kata_core_api.app:app --port 8001 --reload

openapi: ## Dump the core-api OpenAPI schema to web/openapi.json
	PYTHONPATH="$(PYSRC)" uv run --project "$(CURDIR)" python -c \
		"import json; from kata_core_api.app import app; open('web/openapi.json','w').write(json.dumps(app.openapi(), indent=2))"
	@echo "wrote web/openapi.json"

seed: ## Seed synthetic data (FINDINGS=1000000 PRODUCTS=50 via COPY)
	cd services/core-api && PYTHONPATH="$(PYSRC)" uv run --project "$(CURDIR)" \
		python -m kata_core_api.seed --products $(PRODUCTS) --findings $(FINDINGS)

clean: ## Remove caches and local build artifacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache web/node_modules/.vite
