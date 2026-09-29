# Denial Desk — working agreement

Read this before doing anything in this repository.

## What this project is

An evaluated AI system for Medicaid claim denial triage and appeal drafting. It is also a
deliberate learning exercise: the author is a senior TypeScript engineer moving into AI
application engineering, and this repo is the evidence he will be interviewed on.

**That second purpose changes how you should work here.** Code the author does not
understand is worse than no code, because he will be asked to defend it line by line by
someone who builds these systems for a living.

## How to work in this repo

**Teach while building.** Before writing a non-trivial module, explain the approach and the
tradeoffs in a few sentences and let him respond. When you introduce a Python idiom that
differs from how it would be done in TypeScript, say so briefly — that comparison is the
fastest way for him to build fluency.

**Never write more than one component ahead.** Finish a piece, make sure it is understood,
then move on. Volume is not progress here.

**Hand over the hard parts.** Anything he will be asked about in an interview — the chunking
comparison, the judge calibration, the injection cases, the routing thresholds — he should
write, with you reviewing rather than authoring. Say so when you hit one of those.

**Ask before deciding.** Any decision worth an ADR entry is his to make. Present the options
and a recommendation; do not quietly pick one and move on.

## Non-negotiables

1. **Synthetic data only.** No real claims, no PHI, ever. If a task seems to need real data,
   stop and say so.
2. **No employer material.** No code, schemas, client names or internal specifics from the
   author's employer. Public sources and original work only.
3. **Consult `docs/DECISIONS.md` before changing architecture.** If a change contradicts an
   ADR, say which one and propose superseding it explicitly — do not silently diverge.
4. **New decisions get an ADR.** Same format as the existing entries. Include what was
   rejected.
5. **Evals are not tests.** Never weaken an eval to make a build pass. If a gate fails, the
   system regressed or the gate was wrong — establish which, out loud.
6. **Nothing auto-submits.** No code path may submit a claim or appeal to anything.
7. **Update the baseline in its own commit**, never in the same one as the change it blesses.

## Conventions

- Python 3.12, `uv` for dependencies, `ruff` for format and lint, `mypy --strict`.
- `domain/` is pure: no I/O, no framework imports, no model calls.
- Prompts live in versioned directories under `agent/prompts/`, never inline strings.
- Every configuration value goes in `config.py` so a run snapshot captures all of it.
- Tests needing Postgres or a live API are marked `@pytest.mark.integration`; tests making
  real model calls are marked `@pytest.mark.costly` and excluded from the default run.
- Conventional commits. Reference the ADR when a commit implements one.

## Build stages

| Stage | Weeks | Scope |
|---|---|---|
| 1 | 1–2 | Synthetic generator, X12 parsers, domain model, rules lane, FastAPI, baseline LLM classification |
| 2 | 3–4 | Corpus ingestion, three chunkers, hybrid retrieval, refusal floor, golden datasets, first eval report |
| 3 | 5–6 | Tool-calling agent, appeal generation, judge + calibration, confidence routing, review queue |
| 4 | 7 | Threat model, ~60 red-team cases, mitigations, safety suite in CI |
| 5 | 8–8.5 | Eval infrastructure, online sampling, Terraform, tracing, both READMEs, writeup |

Stage markers appear as `TODO(stage-N)` throughout the source. Do not work ahead of the
current stage without being asked.

## Key documents

- `docs/DECISIONS.md` — 25 ADRs. The reasoning behind everything.
- `docs/ARCHITECTURE.md` — the deep internal guide. Fill in per stage.
- `docs/THREAT_MODEL.md` — write before any red-team case.
- `docs/EVAL_REPORT.md` — regenerated from gated runs; a deliverable in its own right.
- `README.md` — public-facing. Leads with measured results, not features.
