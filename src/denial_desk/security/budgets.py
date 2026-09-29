"""Step, token, dollar and time budgets, plus the circuit breaker.

These are the defense against denial-of-wallet: a crafted document that induces an
unbounded retrieve-and-reason loop. Budgets that are never tested are decoration, so the
red-team suite includes cases that deliberately trip each one. See ADR-018.

TODO(stage-4).
"""

from __future__ import annotations


class BudgetExceededError(Exception):
    """Raised to end a run and hand off to human review. Not an HTTP 500."""


class BudgetTracker:
    def __init__(self, max_steps: int, max_tokens: int, max_usd: float) -> None:
        raise NotImplementedError
