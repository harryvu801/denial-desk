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
