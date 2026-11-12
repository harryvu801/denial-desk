"""Run the eval suites, record provenance, compare against the committed baseline, gate.

    python -m evals.runner --suites accuracy                   # run, record, report
    python -m evals.runner --suites accuracy --gate            # also exit 1 on a regression
    python -m evals.runner --suites accuracy --write-baseline  # bless this run (own commit)

The gate reads `evals/baseline.json`. A metric that has a tolerance is gated; one without
is recorded so two runs can be diffed. Updating the baseline is its own commit, never the
one that changed the numbers — that separation is what stops a gate from being edited away
in the commit that broke it (ADR-019).

The accuracy suite replays committed recordings, so the gate needs no API key and spends
nothing (ADR-030). A prompt or input change without a new recording shows up as
`missing_recording` failures, which fail the gate on their own and again through the
accuracy drop they cause. That is the intended outcome: re-record, then bless.

Only the accuracy suite exists. Robustness and safety are stages 3 and 4; cost is reported
inside the accuracy record. Asking for a suite that is not built is an error, not a pass.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from denial_desk.config import settings
from evals.suites import accuracy

BASELINE_PATH = Path(__file__).parent / "baseline.json"
RESULTS_DIR = Path(__file__).parent / "results"

BUILT_SUITES = {"accuracy"}
DEFAULT_TOLERANCES: dict[str, float] = {
    "accuracy_drop_pct": 2.0,
    "wrong_action_max": 0,
    "missed_handoff_max": 0,
    "failures_max": 0,
    "usd_per_claim_rise_pct": 15.0,
    "deterministic_share_drop_pct": 1.0,
}
PLANNED_SUITES = {"robustness": "stage 3", "safety": "stage 4", "cost": "inside accuracy"}


@dataclass(frozen=True)
class Gate:
    """How a metric may move before the build fails.

    floor_points   current >= baseline - tolerance/100   (rates such as accuracy, share)
    ceiling_abs    current <= tolerance                  (counts that must stay at zero)
    ceiling_pct    current <= baseline * (1 + tolerance/100)   (cost)
    """

    kind: Literal["floor_points", "ceiling_abs", "ceiling_pct"]
    tolerance_key: str

    def limit(self, baseline: float, tolerance: float) -> float:
        if self.kind == "floor_points":
            return baseline - tolerance / 100
        if self.kind == "ceiling_abs":
            return tolerance
        return baseline * (1 + tolerance / 100)

    def passes(self, current: float, limit: float) -> bool:
        return current >= limit if self.kind == "floor_points" else current <= limit


# Which metrics are gated, and how. The *values* live in baseline.json; the *rules* live
# here so a baseline edit can only move a number, never silence a check.
GATES: dict[str, Gate] = {
    "model.accuracy": Gate("floor_points", "accuracy_drop_pct"),
    "model.wrong_action": Gate("ceiling_abs", "wrong_action_max"),
    # A missed handoff asserts an action where a person should decide. It is the other
    # safety-relevant miss, and the README claims zero, so the gate holds it there.
    "model.missed_handoff": Gate("ceiling_abs", "missed_handoff_max"),
    "model.failures": Gate("ceiling_abs", "failures_max"),
    "cost.usd_per_claim": Gate("ceiling_pct", "usd_per_claim_rise_pct"),
    "cost.deterministic_share": Gate("floor_points", "deterministic_share_drop_pct"),
}


def metrics_from(record: dict[str, Any]) -> dict[str, float]:
    """Flatten the accuracy run record into the gated / diffed metric names."""
    acc = record["accuracy"]["model"]
    et = record["error_types"]["model"]
    return {
        "model.accuracy": round(acc["correct"] / acc["n"], 4) if acc["n"] else 0.0,
        "model.wrong_action": et["wrong_action"],
        "model.missed_handoff": et["missed_handoff"],
        "model.needless_handoff": et["needless_handoff"],
        "model.failures": sum(record["failures"].values()),
        "cost.usd_per_claim": record["cost"]["recorded_usd_per_claim"],
        "cost.deterministic_share": record["dataset"]["deterministic_share"],
    }


@dataclass(frozen=True)
class Check:
    metric: str
    baseline: float
    current: float
    limit: float
    passed: bool


def compare(current: dict[str, float], baseline: dict[str, Any]) -> list[Check]:
    """One check per gated metric present in the baseline. A metric the baseline does not
    carry a tolerance for is not checked; it is still in the run record for diffing."""
    tolerances: dict[str, float] = baseline["tolerances"]
    checks = []
    for name, gate in GATES.items():
        base = baseline["metrics"].get(name)
        tol = tolerances.get(gate.tolerance_key)
        if base is None or tol is None:
            continue
        limit = gate.limit(base, tol)
        cur = current[name]
        checks.append(Check(name, base, cur, limit, gate.passes(cur, limit)))
    return checks


def print_checks(checks: list[Check]) -> None:
    print(f"\n  {'metric':<28}{'baseline':>10}{'current':>10}{'limit':>10}   result")
    for c in checks:
        print(
            f"  {c.metric:<28}{c.baseline:>10.4g}{c.current:>10.4g}{c.limit:>10.4g}"
            f"   {'ok' if c.passed else 'FAIL'}"
        )


def baseline_from(record: dict[str, Any], metrics: dict[str, float]) -> dict[str, Any]:
    existing = json.loads(BASELINE_PATH.read_text()) if BASELINE_PATH.exists() else {}
    return {
        "_comment": (
            "Committed baseline the CI gate compares against. Update deliberately, in its own"
            " commit, with the run that justifies it. Metrics with a matching tolerance are"
            " gated; the rest are recorded for diffing. See ADR-019."
        ),
        "git_sha": record["git_sha"],
        "run_at": record["run_at"],
        "model": record["model"],
        "prompt": record["prompt"],
        "generator_version": record["dataset"]["generator_version"],
        "n_cases": record["dataset"]["n_cases"],
        "metrics": metrics,
        # Keep tolerances already chosen, add any a newer gate needs. Writing a baseline
        # never loosens a tolerance; that is a hand edit in its own commit.
        "tolerances": DEFAULT_TOLERANCES | existing.get("tolerances", {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run eval suites and gate on the baseline.")
    parser.add_argument("--suites", nargs="+", default=["accuracy"])
    parser.add_argument("--gate", action="store_true", help="exit 1 on any failed check")
    parser.add_argument("--write-baseline", action="store_true", help="bless this run")
    args = parser.parse_args()

    for suite in args.suites:
        if suite not in BUILT_SUITES:
            where = PLANNED_SUITES.get(suite, "unknown")
            print(f"suite {suite!r} is not built ({where}); refusing to report a pass")
            return 2

    record = accuracy.run("replay", settings.model_resolution, False, None)
    accuracy.print_report(record)
    metrics = metrics_from(record)

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%S+0000")
    out = RESULTS_DIR / f"runner-{stamp}.json"
    summary: dict[str, Any] = {"metrics": metrics, "accuracy": record}

    if args.write_baseline:
        BASELINE_PATH.write_text(json.dumps(baseline_from(record, metrics), indent=2) + "\n")
        print(f"\n  baseline written: {BASELINE_PATH} (commit it on its own, ADR-019)")

    failed = False
    if BASELINE_PATH.exists() and not args.write_baseline:
        baseline = json.loads(BASELINE_PATH.read_text())
        if baseline.get("metrics", {}).get("model.accuracy") is None:
            print("\n  baseline is a placeholder; nothing to gate on")
        else:
            checks = compare(metrics, baseline)
            print_checks(checks)
            failed = any(not c.passed for c in checks)
            summary["gate"] = {
                "baseline_sha": baseline.get("git_sha"),
                "checks": [c.__dict__ for c in checks],
                "passed": not failed,
            }
    out.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(f"\n  run record: {out}")

    if args.gate and failed:
        print("\n  GATE FAILED: a gated metric regressed beyond its tolerance (ADR-019).")
        print("  Either the change regressed the system, or the gate is wrong — decide which,")
        print("  out loud, before touching evals/baseline.json.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
