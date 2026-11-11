"""Action-classification metrics: accuracy, per-slice accuracy, abstention.

Always report per slice, never only the aggregate. An 88% average concealing 46% on one
cause is the failure aggregates are built to hide. See ADR-013.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from denial_desk.domain.models import ResolutionPath


@dataclass(frozen=True)
class Score:
    n: int
    correct: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.n if self.n else 0.0


def score(expected: Sequence[ResolutionPath], predicted: Sequence[ResolutionPath]) -> Score:
    assert len(expected) == len(predicted)
    return Score(len(expected), sum(e is p for e, p in zip(expected, predicted, strict=True)))


def by_slice[T](
    items: Sequence[T],
    expected: Sequence[ResolutionPath],
    predicted: Sequence[ResolutionPath],
    key: Callable[[T], str],
) -> dict[str, Score]:
    groups: dict[str, list[int]] = defaultdict(list)
    for i, item in enumerate(items):
        groups[key(item)].append(i)
    return {
        name: score([expected[i] for i in idx], [predicted[i] for i in idx])
        for name, idx in sorted(groups.items())
    }


@dataclass(frozen=True)
class Abstention:
    """How well the system knows when to hand off.

    precision: of the cases it sent to a human, how many should have gone.
    recall:    of the cases that should have gone to a human, how many did.
    Low recall is the dangerous one — a confident answer where a person should decide."""

    precision: float
    recall: float
    abstained: int
    should_abstain: int


def abstention(
    expected: Sequence[ResolutionPath], predicted: Sequence[ResolutionPath]
) -> Abstention:
    human = ResolutionPath.NEEDS_HUMAN
    predicted_h = [i for i, p in enumerate(predicted) if p is human]
    expected_h = [i for i, e in enumerate(expected) if e is human]
    both = len(set(predicted_h) & set(expected_h))
    return Abstention(
        precision=both / len(predicted_h) if predicted_h else 0.0,
        recall=both / len(expected_h) if expected_h else 0.0,
        abstained=len(predicted_h),
        should_abstain=len(expected_h),
    )


@dataclass(frozen=True)
class ErrorTypes:
    """Not all misses cost the same. Accuracy alone ranked run 2's models backwards.

    correct           right action, or a correct handoff
    needless_handoff  sent to a human when the evidence settled it — costs reviewer time
    missed_handoff    asserted an action where a person should decide — skips a judgment
    wrong_action      asserted the wrong action — the error that loses money or files
                      a bad appeal; the one to drive toward zero
    """

    correct: int
    needless_handoff: int
    missed_handoff: int
    wrong_action: int


def error_types(
    expected: Sequence[ResolutionPath], predicted: Sequence[ResolutionPath]
) -> ErrorTypes:
    human = ResolutionPath.NEEDS_HUMAN
    counts = {"correct": 0, "needless_handoff": 0, "missed_handoff": 0, "wrong_action": 0}
    for e, p in zip(expected, predicted, strict=True):
        if e is p:
            counts["correct"] += 1
        elif p is human:
            counts["needless_handoff"] += 1
        elif e is human:
            counts["missed_handoff"] += 1
        else:
            counts["wrong_action"] += 1
    return ErrorTypes(**counts)


# How each action tends to be named in a rationale. Deliberately short: this is a lexical
# heuristic for a reported-only number, not a judge (ADR-031, "revisit when").
ACTION_PHRASES: dict[ResolutionPath, tuple[str, ...]] = {
    ResolutionPath.CORRECTED_CLAIM: ("corrected claim", "correct the claim", "resubmit", "rebill"),
    ResolutionPath.APPEAL: ("appeal",),
    ResolutionPath.WRITE_OFF: ("write off", "write-off", "written off"),
    ResolutionPath.NO_ACTION: ("no action",),
}


def handoffs_naming_the_action(
    expected: Sequence[ResolutionPath],
    predicted: Sequence[ResolutionPath],
    rationales: Sequence[str],
) -> int:
    """Of the needless handoffs, how many named the expected action in their rationale.

    A handoff that says "next step is a corrected claim" costs the reviewer less than one
    that says nothing, so this credits them separately. It matches phrases, so a rationale
    that argues *against* the action also counts; treat it as an upper bound and never gate
    on it. A judge or human label would replace it."""
    human = ResolutionPath.NEEDS_HUMAN
    named = 0
    for e, p, text in zip(expected, predicted, rationales, strict=True):
        if p is human and e is not human:
            lowered = text.lower()
            named += any(phrase in lowered for phrase in ACTION_PHRASES.get(e, ()))
    return named
