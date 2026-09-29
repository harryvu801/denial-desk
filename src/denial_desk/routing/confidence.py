"""Route on confidence AND dollars at risk, not confidence alone.

A 0.9-confidence resolution on a $40 line and a 0.9-confidence resolution on a $12,000 line
do not deserve the same review depth. Expected cost of being wrong is the routing variable.
See ADR-024.

TODO(stage-3).
"""

from __future__ import annotations

from enum import StrEnum

from denial_desk.domain.models import Resolution


class ReviewDepth(StrEnum):
    SPOT_CHECK = "spot_check"
    STANDARD = "standard"
    FULL = "full"


def route(resolution: Resolution) -> ReviewDepth:
    raise NotImplementedError
