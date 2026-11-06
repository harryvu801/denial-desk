"""Model-lane accuracy: does reading the case file beat knowing the CARC?

    python -m evals.suites.accuracy                    # replay committed recordings (free)
    python -m evals.suites.accuracy --proposer stub    # plumbing check, always abstains
    python -m evals.suites.accuracy --proposer live --record   # real calls; costs money

Scores three systems on the same human-lane cases: the model, a CARC-majority baseline fit
on another seed, and always-abstain. Every model failure (invalid output, refusal,
truncation, missing recording) is scored as needs_human, because that is what the system
does with it. A live run stops before total spend passes `eval_max_usd` (ADR-018).
Writes a run record with everything needed to reproduce it (ADR-017).
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from denial_desk.agent.input import build_request
from denial_desk.agent.lane import recording_path
from denial_desk.agent.prompts import load_prompt
from denial_desk.agent.proposer import (
    AnthropicProposer,
    ProposalOutcome,
    Proposer,
    RecordingProposer,
    ReplayProposer,
    StubProposer,
)
from denial_desk.agent.schemas import ModelProposal
from denial_desk.config import settings
from denial_desk.domain.models import ResolutionPath, RootCause
from denial_desk.routing.confidence import apply_confidence_floor
from denial_desk.security.budgets import BudgetExceededError
from evals.cases import EvalCase, build_eval_set, fit_carc_majority
from evals.metrics.classification import Score, abstention, by_slice, error_types, score

RESULTS_DIR = Path(__file__).parent.parent / "results"


def usd(outcome: ProposalOutcome) -> float:
    price_in, price_out = settings.model_prices_usd_per_mtok.get(outcome.model, (0.0, 0.0))
    return (outcome.usage.input_tokens * price_in + outcome.usage.output_tokens * price_out) / 1e6


SWEEP = (0.0, 0.5, 0.6, 0.7, 0.8, 0.9)


def make_proposer(kind: str, model: str, record: bool, prompt_version: str) -> Proposer:
    path = recording_path(settings, model, prompt_version)
    if kind == "replay":
        return ReplayProposer(path, model)
    if kind == "stub":
        return StubProposer(
            lambda _: ModelProposal(
                action=ResolutionPath.NEEDS_HUMAN,
                root_cause=RootCause.UNKNOWN,
                confidence=0.0,
                evidence=[],
                rationale="stub",
            )
        )
    import anthropic  # only a live run needs the SDK client and credentials

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key or None)
    effort = None if model in settings.models_without_effort else settings.model_effort
    live = AnthropicProposer(client, model, effort, settings.model_max_tokens)
    return RecordingProposer(live, path) if record else live


def decide(outcomes: list[ProposalOutcome], floor: float) -> list[ResolutionPath]:
    """What the system does with each outcome: a failure is a handoff, and so is an action
    stated with less confidence than the floor."""
    return [
        apply_confidence_floor(o.proposal.action, o.proposal.confidence, floor)
        if o.proposal
        else ResolutionPath.NEEDS_HUMAN
        for o in outcomes
    ]


def _git_sha() -> str:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()

    sha = git("rev-parse", "--short", "HEAD") or "unknown"
    return sha + ("-dirty" if git("status", "--porcelain") else "")


def _fmt(s: Score) -> str:
    return f"{s.accuracy:6.1%} ({s.correct}/{s.n})"


def run(
    kind: str,
    model: str,
    record: bool,
    limit: int | None,
    concurrency: int = 8,
    prompt_version: str = settings.classify_prompt_version,
    floor: float = settings.model_confidence_floor,
) -> dict[str, Any]:
    eval_set = build_eval_set(settings.eval_seed, settings.eval_claims)
    baseline = fit_carc_majority(build_eval_set(settings.baseline_fit_seed, settings.eval_claims))
    cases: list[EvalCase] = list(eval_set.cases[:limit] if limit else eval_set.cases)
    prompt = load_prompt("classify", prompt_version)
    proposer = make_proposer(kind, model, record, prompt_version)

    requests = [build_request(c.record, c.case_file, prompt) for c in cases]
    outcomes: list[ProposalOutcome] = []
    spent = 0.0
    # Batches of `concurrency` calls run in parallel threads (the SDK client is thread-safe);
    # the budget is checked between batches, so it can overshoot by at most one batch.
    batch = concurrency if kind == "live" else len(requests) or 1
    try:
        with ThreadPoolExecutor(max_workers=batch) as pool:
            for start in range(0, len(requests), batch):
                done = list(pool.map(proposer.propose, requests[start : start + batch]))
                outcomes.extend(done)
                if kind == "live":
                    spent += sum(usd(o) for o in done)
                    print(f"  [{len(outcomes)}/{len(requests)}] ${spent:.3f}", flush=True)
                    if spent >= settings.eval_max_usd:
                        raise BudgetExceededError(
                            f"stopped at ${spent:.2f} after {len(outcomes)} cases"
                        )
    except BudgetExceededError as exc:
        print(f"BUDGET: {exc}. Scoring the {len(outcomes)} cases completed.")
        cases = cases[: len(outcomes)]

    expected = [c.expected_action for c in cases]
    predicted = {
        "model": decide(outcomes, floor),
        "carc_majority": [
            baseline.get(c.record.primary_carc, ResolutionPath.NEEDS_HUMAN) for c in cases
        ],
        "always_abstain": [ResolutionPath.NEEDS_HUMAN] * len(cases),
    }
    model_pred = predicted["model"]
    latencies = sorted(o.latency_ms for o in outcomes if o.proposal or o.failure)
    recorded_cost = sum(usd(o) for o in outcomes)

    record_out: dict[str, Any] = {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "proposer": kind,
        "model": proposer.model,
        "prompt": prompt.id,
        "prompt_is_placeholder": prompt.is_placeholder,
        "effort": None if model in settings.models_without_effort else settings.model_effort,
        "dataset": {
            "seed": eval_set.seed,
            "n_claims": eval_set.n_claims,
            "generator_version": eval_set.generator_version,
            "n_cases": len(cases),
            "baseline_fit_seed": settings.baseline_fit_seed,
        },
        "accuracy": {name: asdict(score(expected, p)) for name, p in predicted.items()},
        "abstention": {name: asdict(abstention(expected, p)) for name, p in predicted.items()},
        "error_types": {name: asdict(error_types(expected, p)) for name, p in predicted.items()},
        "model_by_variant": {
            k: asdict(v)
            for k, v in by_slice(cases, expected, model_pred, lambda c: c.variant).items()
        },
        "model_by_root_cause": {
            k: asdict(v)
            for k, v in by_slice(cases, expected, model_pred, lambda c: c.root_cause.value).items()
        },
        "model_by_payer": {
            k: asdict(v)
            for k, v in by_slice(
                cases, expected, model_pred, lambda c: c.record.payer.value
            ).items()
        },
        "confidence_floor": floor,
        # Free: the same recorded outcomes re-scored at each floor (ADR-024).
        "floor_sweep": {
            str(f): {
                "accuracy": score(expected, decide(outcomes, f)).accuracy,
                **asdict(error_types(expected, decide(outcomes, f))),
            }
            for f in SWEEP
        },
        "failures": dict(Counter(o.failure.value for o in outcomes if o.failure)),
        "cost": {
            "spent_usd_this_run": round(spent, 4),
            "recorded_usd_total": round(recorded_cost, 4),
            "recorded_usd_per_claim": round(recorded_cost / len(cases), 5) if cases else 0.0,
            "input_tokens": sum(o.usage.input_tokens for o in outcomes),
            "output_tokens": sum(o.usage.output_tokens for o in outcomes),
        },
        "latency_ms": {
            "p50": statistics.median(latencies) if latencies else 0.0,
            "p95": statistics.quantiles(latencies, n=20)[-1] if len(latencies) > 1 else 0.0,
        },
        "settings": settings.model_dump(
            exclude={"anthropic_api_key", "langfuse_secret_key", "langfuse_public_key"}
        ),
    }
    return record_out


def print_report(r: dict[str, Any]) -> None:
    print(f"\nModel-lane accuracy — {r['model']} · prompt {r['prompt']} · {r['proposer']}")
    if r["prompt_is_placeholder"]:
        print("  NOTE: prompt is still the placeholder; live calls are refused.")
    print(f"  {r['dataset']['n_cases']} human-lane cases, seed {r['dataset']['seed']}\n")
    print(f"  {'system':<16}{'accuracy':<20}{'abstain P / R'}")
    for name, acc in r["accuracy"].items():
        ab = r["abstention"][name]
        s = Score(acc["n"], acc["correct"])
        print(f"  {name:<16}{_fmt(s):<20}{ab['precision']:.0%} / {ab['recall']:.0%}")
    print(f"\n  {'system':<16}{'correct':>8}{'needless':>10}{'missed':>8}{'WRONG':>7}")
    for name, et in r["error_types"].items():
        print(f"  {name:<16}{et['correct']:>8}{et['needless_handoff']:>10}"
              f"{et['missed_handoff']:>8}{et['wrong_action']:>7}")  # fmt: skip
    print(f"\n  confidence floor sweep (in code; this run scored at {r['confidence_floor']}):")
    print(f"  {'floor':<16}{'accuracy':>9}{'needless':>10}{'missed':>8}{'WRONG':>7}")
    for f, row in r["floor_sweep"].items():
        print(
            f"  {f:<16}{row['accuracy']:>9.1%}{row['needless_handoff']:>10}"
            f"{row['missed_handoff']:>8}{row['wrong_action']:>7}"
        )
    for title, key in (("variant", "model_by_variant"), ("payer", "model_by_payer")):
        print(f"\n  model by {title}:")
        for name, v in r[key].items():
            print(f"    {name:<34}{_fmt(Score(v['n'], v['correct']))}")
    c = r["cost"]
    print(f"\n  failures: {r['failures'] or 'none'}")
    print(f"  cost: ${c['recorded_usd_total']:.4f} recorded, ${c['recorded_usd_per_claim']:.5f}"
          f"/claim, ${c['spent_usd_this_run']:.4f} spent this run")  # fmt: skip
    print(f"  latency: p50 {r['latency_ms']['p50']:.0f} ms, p95 {r['latency_ms']['p95']:.0f} ms")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    parser.add_argument("--proposer", choices=["replay", "stub", "live"], default="replay")
    parser.add_argument("--model", default=settings.model_resolution)
    parser.add_argument("--record", action="store_true", help="with --proposer live")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--prompt", default=settings.classify_prompt_version)
    parser.add_argument("--floor", type=float, default=settings.model_confidence_floor)
    args = parser.parse_args()

    result = run(
        args.proposer,
        args.model,
        args.record,
        args.limit,
        args.concurrency,
        args.prompt,
        args.floor,
    )
    print_report(result)
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"accuracy-{result['run_at'].replace(':', '')}-{args.proposer}.json"
    out.write_text(json.dumps(result, indent=2, default=str) + "\n")
    print(f"\n  run record: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
