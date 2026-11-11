"""The model lane, as the pipeline runs it: only for denials the rules hand to a human.

Order matters and is the whole design (ADR-006): rules first; the model only sees what the
rules could not settle; a model proposal that is a handoff, a failure, or below the
confidence floor stays a human-lane item. Every outcome is still reviewed (ADR-007).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from denial_desk.agent.input import build_request
from denial_desk.agent.prompts import Prompt, load_prompt
from denial_desk.agent.proposer import (
    AnthropicProposer,
    ProposalOutcome,
    Proposer,
    RecordingProposer,
    ReplayProposer,
)
from denial_desk.config import Settings
from denial_desk.domain.case_file import CaseFile
from denial_desk.domain.models import DenialRecord, Lane, Resolution, ResolutionPath
from denial_desk.reference import payer_rules
from denial_desk.routing.confidence import apply_confidence_floor


@dataclass(frozen=True)
class ModelLane:
    proposer: Proposer
    prompt: Prompt
    confidence_floor: float
    prices_usd_per_mtok: dict[str, tuple[float, float]]

    def usd(self, outcome: ProposalOutcome) -> float:
        price_in, price_out = self.prices_usd_per_mtok.get(outcome.model, (0.0, 0.0))
        u = outcome.usage
        return (u.input_tokens * price_in + u.output_tokens * price_out) / 1e6

    def propose(
        self, record: DenialRecord, case_file: CaseFile, handed_off: Resolution, *, as_of: date
    ) -> tuple[Resolution, dict[str, Any]]:
        """Return the resolution to store, plus metadata about the model call for the row.

        `as_of` is the working date, the same one the rules lane triages with: a corrected
        claim whose correction window has already closed on that date is handed to a human,
        because late filing is a good-cause judgment (the rules lane does the same)."""
        outcome = self.proposer.propose(build_request(record, case_file, self.prompt))
        meta: dict[str, Any] = {
            "model": outcome.model,
            "prompt": outcome.prompt_id,
            "failure": outcome.failure.value if outcome.failure else None,
            "usd": round(self.usd(outcome), 5),
            "confidence_floor": self.confidence_floor,
        }
        proposal = outcome.proposal
        if proposal is None:
            return handed_off, meta
        meta |= {
            "action": proposal.action.value,
            "root_cause": proposal.root_cause.value,
            "confidence": proposal.confidence,
            "evidence": proposal.evidence,
            "rationale": proposal.rationale,
        }
        action = apply_confidence_floor(proposal.action, proposal.confidence, self.confidence_floor)
        if action is ResolutionPath.NEEDS_HUMAN:
            # The model's view still helps the reviewer, so it rides along in the rationale.
            note = (
                f"{handed_off.rationale} Model ({outcome.model}) handed off: {proposal.rationale}"
            )
            return handed_off.model_copy(update={"rationale": note}), meta

        deadline = None
        if action is ResolutionPath.CORRECTED_CLAIM:
            # Deadlines are arithmetic, so code computes them, never the model (ADR-010).
            rules = payer_rules()[record.payer.value]
            deadline = rules.correction_deadline(record.submitted.service_date)
            if deadline < as_of:
                note = (
                    f"{handed_off.rationale} Model ({outcome.model}) proposed a corrected"
                    f" claim, but the {rules.name} correction window closed on {deadline}"
                    f" (working date {as_of}). Late filing needs a good-cause decision."
                    f" Model rationale: {proposal.rationale}"
                )
                meta["expired_correction_window"] = True
                return (
                    handed_off.model_copy(update={"rationale": note, "filing_deadline": deadline}),
                    meta,
                )
        return (
            Resolution(
                patient_control_number=record.patient_control_number,
                line_control_number=record.line_control_number,
                lane=Lane.MODEL,
                path=action,
                rationale=proposal.rationale,
                filing_deadline=deadline,
                prompt_version=outcome.prompt_id,
                model_version=outcome.model,
            ),
            meta,
        )


def recording_path(settings: Settings, model: str, prompt_version: str) -> Path:
    return Path(settings.recordings_dir) / f"classify-{prompt_version}-{model}.jsonl"


def build_model_lane(settings: Settings, *, record: bool = False) -> ModelLane | None:
    """The model lane the config asks for. Replay needs no key and spends nothing."""
    if settings.model_lane == "off":
        return None
    model, version = settings.model_resolution, settings.classify_prompt_version
    path = recording_path(settings, model, version)
    proposer: Proposer
    if settings.model_lane == "replay":
        proposer = ReplayProposer(path, model)
    else:
        import anthropic  # only a live lane needs the SDK client and credentials

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key or None)
        effort = None if model in settings.models_without_effort else settings.model_effort
        live = AnthropicProposer(client, model, effort, settings.model_max_tokens)
        proposer = RecordingProposer(live, path) if record else live
    return ModelLane(
        proposer=proposer,
        prompt=load_prompt("classify", version),
        confidence_floor=settings.model_confidence_floor,
        prices_usd_per_mtok=settings.model_prices_usd_per_mtok,
    )
