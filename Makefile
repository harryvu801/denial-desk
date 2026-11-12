.PHONY: help demo install db-up db-down fmt lint typecheck test eval-accuracy eval-gate eval-variance eval-safety eval-all gen-data fetch-corpus ingest-corpus serve

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

demo:  ## Rebuild the demo (2,000 synthetic claims, model lane replayed) and serve it
	uv run dd demo
	uv run uvicorn denial_desk.api.main:create_app --factory

gen-data:  ## Generate the synthetic 837P/835 corpus into data/synthetic
	uv run dd generate --claims 2000 --seed 42

fetch-corpus:  ## Download the public payer manuals into data/corpus and extract their text
	uv run dd fetch-corpus

ingest-corpus:  ## Index the corpus (stage 2, not built yet)
	uv run dd ingest-corpus

eval-accuracy:  ## Model-lane accuracy, replayed from committed recordings (no API key)
	uv run python -m evals.suites.accuracy

eval-variance:  ## Run-to-run variance of the model lane, replayed from recordings (no API key)
	uv run python -m evals.suites.robustness

eval-safety:  ## Red-team + adversarial suite
	uv run python -m evals.suites.safety

eval-gate:  ## What CI runs: replay the model lane and gate on evals/baseline.json (no API key)
	uv run python -m evals.runner --suites accuracy --gate

eval-all:  ## Every built suite through the runner (robustness and safety are not built yet)
	uv run python -m evals.runner --suites accuracy

serve:  ## Run the API locally
	uv run uvicorn denial_desk.api.main:create_app --factory --reload
