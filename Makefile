.PHONY: help demo install db-up db-down fmt lint typecheck test eval-accuracy eval-safety eval-all gen-data ingest-corpus serve

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install:  ## Create the venv and install everything including dev + eval extras
	uv sync --all-extras

db-up:  ## Start Postgres + pgvector
	docker compose up -d db

db-down:  ## Stop containers
	docker compose down

fmt:  ## Format
	uv run ruff format src evals tests

lint:  ## Lint
	uv run ruff check src evals tests

typecheck:  ## Type check
	uv run mypy

test:  ## Unit tests (no model calls)
	uv run pytest

demo:  ## Generate 500 synthetic claims, ingest them, and serve the review screen
	uv run dd demo
	uv run uvicorn denial_desk.api.main:create_app --factory

gen-data:  ## Generate the synthetic 837P/835 corpus into data/synthetic
	uv run dd generate --claims 500 --seed 42

ingest-corpus:  ## Download and index the public policy corpus into pgvector
	uv run dd ingest-corpus

eval-accuracy:  ## Offline accuracy suite against the golden sets
	uv run python -m evals.suites.accuracy

eval-safety:  ## Red-team + adversarial suite
	uv run python -m evals.suites.safety

eval-all:  ## Everything the CI gate runs
	uv run python -m evals.runner --suites accuracy robustness cost safety

serve:  ## Run the API locally
	uv run uvicorn denial_desk.api.main:create_app --factory --reload
