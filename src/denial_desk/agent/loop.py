"""The bounded agent loop.

Bounds, all enforced rather than suggested: step count, token spend, dollar spend, and
wall-clock. Exceeding any of them is not an error the user sees — it is a hand-off to human
review with the partial trace attached. See ADR-018.

The loop degrades to the deterministic lane when the model API is unavailable, rather than
failing the request. A denial that cannot be resolved is queued, not lost. See ADR-015.

TODO(stage-3).
"""

from __future__ import annotations

from denial_desk.domain.models import DenialRecord, Resolution


def resolve(record: DenialRecord) -> Resolution:
    raise NotImplementedError
