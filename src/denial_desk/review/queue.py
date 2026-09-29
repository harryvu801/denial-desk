"""The review queue.

Deliberately plain: a table and three actions. This is not a frontend project, and time
spent styling it is time not spent on evals.

Its second job is the one that matters long term: every approve / edit / reject is a label.
Edits are the richest signal in the system because they show what a human changed and why.
See ADR-013.

TODO(stage-3).
"""

from __future__ import annotations

from enum import StrEnum


class ReviewAction(StrEnum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"
