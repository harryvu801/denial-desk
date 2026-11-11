"""The CI gate: metric extraction, tolerance arithmetic, and the fifth handoff category."""

from denial_desk.domain.models import ResolutionPath
from evals.metrics.classification import handoffs_naming_the_action
from evals.runner import GATES, Gate, compare, metrics_from

RECORD = {
    "accuracy": {"model": {"n": 200, "correct": 134}},
    "error_types": {
        "model": {"correct": 134, "needless_handoff": 60, "missed_handoff": 0, "wrong_action": 0}
    },
    "failures": {},
    "cost": {"recorded_usd_per_claim": 0.0063},
    "dataset": {"deterministic_share": 0.856},
}


def _baseline(**metrics: float) -> dict[str, object]:
    base = {
        "model.accuracy": 0.67,
        "model.wrong_action": 0,
        "model.failures": 0,
        "cost.usd_per_claim": 0.0063,
        "cost.deterministic_share": 0.856,
    }
    return {
        "metrics": base | metrics,
        "tolerances": {
            "accuracy_drop_pct": 2.0,
            "wrong_action_max": 0,
            "failures_max": 0,
            "usd_per_claim_rise_pct": 15.0,
            "deterministic_share_drop_pct": 1.0,
        },
    }


def test_metrics_flatten_the_run_record() -> None:
    m = metrics_from(RECORD)
    assert m["model.accuracy"] == 0.67 and m["model.wrong_action"] == 0
    assert m["model.failures"] == 0 and m["cost.deterministic_share"] == 0.856


def test_gate_passes_at_baseline_and_within_tolerance() -> None:
    assert all(c.passed for c in compare(metrics_from(RECORD), _baseline()))
    within = metrics_from(RECORD) | {"model.accuracy": 0.655, "cost.usd_per_claim": 0.007}
    assert all(c.passed for c in compare(within, _baseline()))


def test_gate_fails_on_each_kind_of_regression() -> None:
    good = metrics_from(RECORD)
    for metric, value in (
        ("model.accuracy", 0.64),  # more than 2 points down
        ("model.wrong_action", 1),  # zero tolerance
        ("model.failures", 3),  # e.g. a prompt edit without a re-recording
        ("cost.usd_per_claim", 0.0063 * 1.2),  # 20% dearer
        ("cost.deterministic_share", 0.84),  # rules lane shrank
    ):
        failed = [c.metric for c in compare(good | {metric: value}, _baseline()) if not c.passed]
        assert failed == [metric], (metric, failed)


def test_metrics_without_a_tolerance_are_not_gated() -> None:
    baseline = _baseline()
    del baseline["tolerances"]["usd_per_claim_rise_pct"]  # type: ignore[index]
    checked = {c.metric for c in compare(metrics_from(RECORD), baseline)}
    assert "cost.usd_per_claim" not in checked and "model.accuracy" in checked
    assert set(GATES) >= checked


def test_gate_arithmetic() -> None:
    assert Gate("floor_points", "x").limit(0.672, 2.0) == 0.652
    assert Gate("ceiling_pct", "x").limit(0.01, 15.0) == 0.0115
    assert Gate("ceiling_abs", "x").limit(5, 0) == 0


def test_handoffs_naming_the_action_counts_only_needless_handoffs() -> None:
    h, c, a = ResolutionPath.NEEDS_HUMAN, ResolutionPath.CORRECTED_CLAIM, ResolutionPath.APPEAL
    n = handoffs_naming_the_action(
        expected=[c, c, a, h, a],
        predicted=[h, h, h, h, a],
        rationales=[
            "Next step is a corrected claim with the extension number.",
            "Cannot tell what is missing.",
            "An appeal would be premature.",  # counted: lexical, an upper bound
            "Retroactive reinstatement; suggest a rebill.",  # expected human: not a handoff
            "appeal",  # asserted, not a handoff
        ],
    )
    assert n == 2
