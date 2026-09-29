"""Delimiting and provenance-tagging of untrusted content.

Retrieved policy text and 835 remark free-text are authored by third parties. They are
wrapped in explicit delimiters with a provenance tag, and the system prompt states that
content inside those delimiters is data and never instruction.

This is a mitigation, not a solution — prompt-level defenses are probabilistic and the
red-team suite exists precisely to measure how well it actually holds. The architectural
defenses in tools.py and budgets.py are the ones that hold deterministically. See ADR-020.

TODO(stage-4).
"""

from __future__ import annotations

from denial_desk.domain.models import Evidence


def wrap_untrusted(evidence: Evidence) -> str:
    """Render a passage for prompt inclusion with provenance and delimiters."""
    raise NotImplementedError
