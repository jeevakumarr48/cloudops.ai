# Common tasks. Run `make help` for the list.
PYTHON ?= python3
VENV ?= .venv
BIN = $(abspath $(VENV))/bin
PY = $(BIN)/python
DB ?= sqlite:///./dev.sqlite3

.DEFAULT_GOAL := help
.PHONY: help install dev api web up down logs test test-backend test-frontend e2e lint typecheck check eval smoke clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Create the virtualenv and install backend and frontend dependencies
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install -r backend/requirements-dev.txt "uvicorn[standard]"
	cd frontend && npm ci

api: ## Run the API with reload on :8000 (SQLite)
	cd backend && DATABASE_URL=$(DB) CLOUDOPS_COOKIE_SECURE=false $(PY) -m alembic upgrade head
	cd backend && DATABASE_URL=$(DB) CLOUDOPS_COOKIE_SECURE=false $(PY) -m uvicorn main:app --reload --port 8000

web: ## Run the Vite dev server on :5173 (proxies /api to :8000)
	cd frontend && npm run dev

dev: ## Run API and frontend together (Ctrl+C stops both)
	@trap 'kill 0' INT TERM; $(MAKE) --no-print-directory api & $(MAKE) --no-print-directory web & wait

up: ## Start Postgres, API and frontend in Docker (http://localhost:8080)
	docker compose up --build -d
	@echo "Open http://localhost:8080 (demo: http://localhost:8080/?demo=1)"

down: ## Stop the Docker stack
	docker compose down

logs: ## Follow the Docker stack's logs
	docker compose logs -f

lint: ## Ruff and ESLint
	cd backend && $(BIN)/ruff check . ../scripts
	cd frontend && npm run lint

typecheck: ## mypy
	cd backend && $(BIN)/mypy .

test-backend: ## Backend tests with the coverage floor
	cd backend && $(PY) -m pytest tests -q --cov=.

test-frontend: ## Vitest unit and component tests
	cd frontend && npm test

eval: ## Offline recommendation evaluation
	cd backend && $(PY) -m evals.run_eval

e2e: ## Playwright end-to-end tests (starts its own API and frontend)
	cd frontend && PYTHON=$(PY) npm run test:e2e

test: test-backend test-frontend eval ## All unit tests and the evaluation

check: lint typecheck test ## Everything CI runs except e2e and audits

smoke: ## Read-only smoke test against URL=... (default: local Docker stack)
	$(PY) scripts/smoke_test.py $(or $(URL),http://localhost:8080)

clean: ## Remove local build and test output
	rm -rf frontend/dist frontend/coverage frontend/playwright-report frontend/test-results backend/.coverage backend/dev.sqlite3
