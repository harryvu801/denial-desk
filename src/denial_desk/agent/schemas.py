"""Structured output contracts for the model lane.

The model returns a validated structure, never free text that is parsed afterward. The API
constrains the response to `strict_json_schema(ModelProposal)` (structured outputs), and
Pydantic validates it again on arrival — the API guarantees shape, Pydantic enforces the
constraints the schema can't express (ranges, lengths). A failure gets one retry with the
error fed back, then the denial goes to a human. Failing closed is the point. See ADR-010.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from denial_desk.domain.models import ResolutionPath, RootCause


class ModelProposal(BaseModel, frozen=True):
    """What the model proposes for one denial. Always reviewed by a person (ADR-007)."""

    action: ResolutionPath = Field(
        description="The next step. Use needs_human when the case file does not settle it."
    )
    root_cause: RootCause = Field(description="Why the line was denied; unknown if unclear.")
    confidence: float = Field(ge=0.0, le=1.0, description="0 to 1.")
    evidence: list[str] = Field(
        max_length=8,
        description=(
            "Case-file items the decision rests on, by path:"
            " 'authorizations[1]', 'eligibility[0]', 'visits[1]', 'care_note', 'denial'."
        ),
    )
    rationale: str = Field(max_length=600, description="At most two sentences.")


class AppealDraft(BaseModel):
    """Stage 3."""

    body: str
    cited_sections: list[str]


# Keywords structured outputs accept. Everything else (minimum, maxLength, title, ...) is
# stripped from the schema sent to the API and enforced by Pydantic on the way back.
_ALLOWED = {"type", "properties", "required", "additionalProperties", "items", "enum",
            "description"}  # fmt: skip


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """A self-contained, strict JSON schema for structured outputs: $refs inlined, every
    property required, no additional properties, unsupported keywords removed."""
    raw = model.model_json_schema()
    defs: dict[str, Any] = raw.pop("$defs", {})

    def clean(node: Any) -> Any:
        if isinstance(node, list):
            return [clean(n) for n in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            resolved = dict(defs[node["$ref"].rsplit("/", 1)[1]])
            if "description" in node:
                resolved["description"] = node["description"]
            return clean(resolved)
        out = {k: clean(v) for k, v in node.items() if k in _ALLOWED and k != "properties"}
        if "properties" in node:  # property *names* are data, not keywords: keep them all
            out["properties"] = {name: clean(sub) for name, sub in node["properties"].items()}
        if out.get("type") == "object":
            out["required"] = list(out.get("properties", {}))
            out["additionalProperties"] = False
        return out

    result: dict[str, Any] = clean(raw)
    return result
