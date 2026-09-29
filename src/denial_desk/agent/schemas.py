"""Structured output contracts for the agent.

The model returns validated structures, never free-form text that is parsed afterward.
A validation failure is a retry with the error fed back, bounded by MAX_AGENT_STEPS, and
then a hand-off to human review. Failing closed is the whole point. See ADR-010.

TODO(stage-3).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from denial_desk.domain.models import ResolutionPath


class RootCauseAnalysis(BaseModel):
    root_cause: str = Field(max_length=500)
    carc_addressed: str
    path: ResolutionPath
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(
        description="Must reference passages actually returned by the retriever. Verified "
        "by the citation checker, not trusted. See ADR-012."
    )


class AppealDraft(BaseModel):
    body: str
    cited_sections: list[str]
