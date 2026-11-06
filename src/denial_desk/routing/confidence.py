"""Route on confidence AND dollars at risk, not confidence alone.

A 0.9-confidence resolution on a $40 line and a 0.9-confidence resolution on a $12,000 line
do not deserve the same review depth. Expected cost of being wrong is the routing variable.
See ADR-024.

The confidence floor lives here, in code, not in the prompt: a model's stated confidence is
not calibrated, and a threshold in code can be tuned against recorded runs for free, where a
threshold in the prompt costs a new recording per value. Dollar-aware depth: TODO(stage-3).
"""

from __future__ import annotations

from enum import StrEnum

from denial_desk.domain.models import Resolution, ResolutionPath


class ReviewDepth(StrEnum):
    SPOT_CHECK = "spot_check"
    STANDARD = "standard"
    FULL = "full"


def route(resolution: Resolution) -> ReviewDepth:
    raise NotImplementedError


def apply_confidence_floor(
    action: ResolutionPath, confidence: float, floor: float
) -> ResolutionPath:
    """Below the floor, a proposed action becomes a handoff. A handoff stays a handoff."""
    return ResolutionPath.NEEDS_HUMAN if confidence < floor else action
