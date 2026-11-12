"""Axis two — robustness. Built so far: run-to-run variance.

    python -m evals.suites.robustness                          # replay committed runs (free)
    python -m evals.suites.robustness --model claude-haiku-4-5
    python -m evals.suites.robustness --proposer live --record # real calls; costs money

The same fixed sample of cases (seeded from the eval set) is answered several times at
production settings. Run 1 is the committed classification recording; later runs live in
data/recordings/variance/. Reported: accuracy and error types per run, their spread, how
many cases ever change their answer, and the accuracy of the majority vote. A system whose
answer moves between runs cannot be gated on a single run, so this is what turns "a few
points is noise" into a number.

Not built: prompt sensitivity, degraded retrieval, the adversarial set (need stage 2).
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from denial_desk.agent.input import build_request
from denial_desk.agent.lane import recording_path
from denial_desk.agent.prompts import load_prompt
from denial_desk.agent.proposer import ProposalOutcome, Proposer, ReplayProposer
from denial_desk.config import settings
from denial_desk.domain.models import ResolutionPath
from denial_desk.security.budgets import BudgetExceededError
from evals.cases import EvalCase, EvalSet, build_eval_set
from evals.metrics.classification import error_types, score
from evals.suites.accuracy import RESULTS_DIR, _git_sha, decide, make_proposer, usd

VARIANCE_DIR = Path(settings.recordings_dir) / "variance"


def sample_cases(eval_set: EvalSet, n: int, seed: int) -> list[EvalCase]:
    """A fixed subset: the same seed always picks the same cases, in key order."""
    chosen = random.Random(seed).sample(list(eval_set.cases), n)
    return sorted(chosen, key=lambda c: c.key)


def run_path(model: str, prompt_version: str, run: int) -> Path:
    if run == 1:
        return recording_path(settings, model, prompt_version)
    return VARIANCE_DIR / f"classify-{prompt_version}-{model}-run{run}.jsonl"


def proposer_for(kind: str, model: str, record: bool, prompt_version: str, run: int) -> Proposer:
    if run == 1 or kind != "live":
        return ReplayProposer(run_path(model, prompt_version, run), model)
    live = make_proposer("live", model, False, prompt_version)
    if record:
        from denial_desk.agent.proposer import RecordingProposer

        return RecordingProposer(live, run_path(model, prompt_version, run))
    return live


def run(
    kind: str,
    model: str,
    record: bool,
    runs: int = settings.variance_runs,
    n_cases: int = settings.variance_cases,
    concurrency: int = 8,
    prompt_version: str = settings.classify_prompt_version,
    floor: float = settings.model_confidence_floor,
    max_usd: float = settings.variance_max_usd,
) -> dict[str, Any]:
    eval_set = build_eval_set(settings.eval_seed, settings.eval_claims)
    cases = sample_cases(eval_set, n_cases, settings.variance_seed)
    prompt = load_prompt("classify", prompt_version)
    requests = [build_request(c.record, c.case_file, prompt) for c in cases]
    expected = [c.expected_action for c in cases]

    per_run: list[list[ProposalOutcome]] = []
    spent = 0.0
    try:
        for r in range(1, runs + 1):
            proposer = proposer_for(kind, model, record, prompt_version, r)
            live = kind == "live" and r > 1
            batch = concurrency if live else len(requests) or 1
            outcomes: list[ProposalOutcome] = []
            with ThreadPoolExecutor(max_workers=batch) as pool:
                for start in range(0, len(requests), batch):
                    done = list(pool.map(proposer.propose, requests[start : start + batch]))
                    outcomes.extend(done)
                    if live:
                        spent += sum(usd(o) for o in done)
                        print(
                            f"  run {r} [{len(outcomes)}/{len(requests)}] ${spent:.3f}", flush=True
                        )
                        if spent >= max_usd:
                            raise BudgetExceededError(f"stopped at ${spent:.2f} in run {r}")
            per_run.append(outcomes)
    except BudgetExceededError as exc:
        print(f"BUDGET: {exc}. Scoring the {len(per_run)} complete runs.")

    decisions = [decide(outcomes, floor) for outcomes in per_run]
    accuracies = [score(expected, d).accuracy for d in decisions]
    # Per case: the set of actions seen across runs, and the majority answer.
    by_case = [[d[i] for d in decisions] for i in range(len(cases))]
    unanimous = sum(len(set(actions)) == 1 for actions in by_case)
    majority = [Counter(actions).most_common(1)[0][0] for actions in by_case]
    flips = [
        {
            "line": c.key,
            "variant": c.variant,
            "expected": c.expected_action.value,
            "runs": [a.value for a in actions],
        }
        for c, actions in zip(cases, by_case, strict=True)
        if len(set(actions)) > 1
    ]
    wrong_any = sum(
        any(a is not ResolutionPath.NEEDS_HUMAN and a is not e for a in actions)
        for e, actions in zip(expected, by_case, strict=True)
    )
    return {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "suite": "robustness.variance",
        "proposer": kind,
        "model": model,
        "prompt": prompt.id,
        "effort": None if model in settings.models_without_effort else settings.model_effort,
        "dataset": {
            "seed": eval_set.seed,
            "n_claims": eval_set.n_claims,
            "generator_version": eval_set.generator_version,
            "n_cases": len(cases),
            "variance_seed": settings.variance_seed,
            "case_keys": [c.key for c in cases],
        },
        "runs_completed": len(per_run),
        "per_run": [
            {
                "accuracy": acc,
                **asdict(error_types(expected, d)),
                "failures": dict(Counter(o.failure.value for o in outs if o.failure)),
            }
            for acc, d, outs in zip(accuracies, decisions, per_run, strict=True)
        ],
        "accuracy": {
            "mean": statistics.mean(accuracies) if accuracies else 0.0,
            "min": min(accuracies, default=0.0),
            "max": max(accuracies, default=0.0),
            "stdev": statistics.stdev(accuracies) if len(accuracies) > 1 else 0.0,
        },
        "agreement": {
            "unanimous_cases": unanimous,
            "cases_with_a_flip": len(flips),
            "cases_wrong_in_any_run": wrong_any,
            "majority_vote_accuracy": score(expected, majority).accuracy,
            "majority_vote_error_types": asdict(error_types(expected, majority)),
        },
        "flips": flips,
        "cost": {"spent_usd_this_run": round(spent, 4)},
        "settings": settings.model_dump(
            exclude={"anthropic_api_key", "langfuse_secret_key", "langfuse_public_key"}
        ),
    }


def print_report(r: dict[str, Any]) -> None:
    print(f"\nRun-to-run variance — {r['model']} · prompt {r['prompt']} · {r['proposer']}")
    print(f"  {r['dataset']['n_cases']} cases x {r['runs_completed']} runs\n")
    print(f"  {'run':<6}{'accuracy':>10}{'needless':>10}{'missed':>8}{'WRONG':>7}  failures")
    for i, row in enumerate(r["per_run"], 1):
        failures = row["failures"] or "-"
        print(f"  {i:<6}{row['accuracy']:>10.1%}{row['needless_handoff']:>10}"
              f"{row['missed_handoff']:>8}{row['wrong_action']:>7}  {failures}")  # fmt: skip
    a, g = r["accuracy"], r["agreement"]
    print(f"\n  accuracy mean {a['mean']:.1%}, min {a['min']:.1%}, max {a['max']:.1%},"
          f" stdev {a['stdev']:.1%}")  # fmt: skip
    print(f"  unanimous cases {g['unanimous_cases']}/{r['dataset']['n_cases']};"
          f" {g['cases_with_a_flip']} changed answer at least once;"
          f" {g['cases_wrong_in_any_run']} wrong in at least one run")  # fmt: skip
    print(f"  majority vote: {g['majority_vote_accuracy']:.1%} accuracy,"
          f" {g['majority_vote_error_types']['wrong_action']} wrong")  # fmt: skip
    for f in r["flips"]:
        print(f"    {f['line']:<14}{f['variant']:<22}expected {f['expected']:<16}{f['runs']}")
    print(f"\n  spent this run: ${r['cost']['spent_usd_this_run']:.4f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run-to-run variance of the model lane.")
    parser.add_argument("--proposer", choices=["replay", "live"], default="replay")
    parser.add_argument("--model", default=settings.model_resolution)
    parser.add_argument("--record", action="store_true", help="with --proposer live")
    parser.add_argument("--runs", type=int, default=settings.variance_runs)
    parser.add_argument("--cases", type=int, default=settings.variance_cases)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--prompt", default=settings.classify_prompt_version)
    parser.add_argument("--max-usd", type=float, default=settings.variance_max_usd)
    args = parser.parse_args()
    result = run(
        args.proposer, args.model, args.record, args.runs, args.cases, args.concurrency,
        args.prompt, max_usd=args.max_usd,
    )  # fmt: skip
    print_report(result)
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"variance-{result['run_at'].replace(':', '')}-{args.proposer}.json"
    out.write_text(json.dumps(result, indent=2, default=str) + "\n")
    print(f"  run record: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
