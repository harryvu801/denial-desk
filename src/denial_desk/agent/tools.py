"""Tools the agent may call.

Two rules govern everything in this module:

1. Arguments are scoped server-side to the claim in context. The agent does not get to
   name a patient; it gets to ask about *this* claim. A prompt-injected instruction to
   look up someone else has nothing to attack, because the parameter does not exist.
   See ADR-021.
2. Anything that is arithmetic is arithmetic. Filing deadlines are computed in Python from
   dates and a payer rule table. The model is never asked to do date math. See ADR-010.

TODO(stage-3).
"""

from __future__ import annotations

from datetime import date

from denial_desk.domain.models import Evidence


class ToolContext:
    """Server-side execution context. Holds the claim the agent is allowed to touch."""

    claim_control_number: str
    payer: str
    calls_remaining: int


def search_policy(ctx: ToolContext, query: str, k: int = 5) -> list[Evidence]:
    """Retrieve policy passages. Returns provenance-tagged, untrusted content."""
    raise NotImplementedError


def check_ncci_edit(ctx: ToolContext, code_a: str, code_b: str) -> dict[str, object]:
    """Look up a procedure-to-procedure edit in the committed NCCI tables. Deterministic."""
    raise NotImplementedError


def get_claim_history(ctx: ToolContext) -> list[dict[str, object]]:
    """Prior adjudications for THIS claim only. No patient parameter exists by design."""
    raise NotImplementedError


def days_until_filing_deadline(ctx: ToolContext, service_date: date) -> int:
    """Pure Python. Never delegated to the model. See ADR-010."""
    raise NotImplementedError
