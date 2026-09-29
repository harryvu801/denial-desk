"""Rules-first triage.

If a denial's primary CARC (plus any required RARCs and condition) matches a playbook entry,
the proposed resolution is determined without a model call. Everything else is proposed as
NEEDS_HUMAN in the human lane. Every proposal goes to the review queue either way (ADR-007).
See ADR-006, ADR-026.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel

from denial_desk.domain.models import DenialRecord, Lane, Resolution, ResolutionPath
from denial_desk.reference import payer_rules

PLAYBOOK_PATH = Path(__file__).parent / "playbook.yaml"


def _initial_deadline_passed(r: DenialRecord) -> bool:
    rules = payer_rules()[r.payer.value]
    return r.submission_date > rules.initial_deadline(r.submitted.service_date)


# Conditions are named in YAML and implemented here, so the playbook stays data while the
# logic stays typed and tested. A typo in a condition name fails at load time.
CONDITIONS: dict[str, Callable[[DenialRecord], bool]] = {
    "submitted_after_initial_deadline": _initial_deadline_passed,
    "submitted_within_initial_deadline": lambda r: not _initial_deadline_passed(r),
    "prior_auth_absent": lambda r: r.prior_auth_number is None,
}


class Match(BaseModel, frozen=True):
    carc: str
    rarcs: tuple[str, ...] = ()
    condition: str | None = None

    def matches(self, record: DenialRecord) -> bool:
        if record.primary_carc != self.carc:
            return False
        if not set(self.rarcs) <= set(record.remark_codes):
            return False
        return self.condition is None or CONDITIONS[self.condition](record)


class Rule(BaseModel, frozen=True):
    id: str
    match: Match
    action: ResolutionPath
    rationale: str
    citations: tuple[str, ...]


class Playbook(BaseModel, frozen=True):
    version: int
    rules: tuple[Rule, ...]


@cache
def load_playbook(path: Path = PLAYBOOK_PATH) -> Playbook:
    playbook = Playbook.model_validate(yaml.safe_load(path.read_text()))
    for rule in playbook.rules:
        if rule.match.condition is not None and rule.match.condition not in CONDITIONS:
            raise ValueError(f"rule {rule.id}: unknown condition {rule.match.condition!r}")
        if not rule.citations:
            raise ValueError(f"rule {rule.id}: every rule needs at least one citation")
    return playbook


def triage(record: DenialRecord, playbook: Playbook | None = None) -> Resolution:
    """Propose a resolution. First matching rule wins; no match means a human decides."""
    playbook = playbook or load_playbook()
    for rule in playbook.rules:
        if rule.match.matches(record):
            rules = payer_rules()[record.payer.value]
            deadline = None
            citations = rule.citations
            if rule.action is ResolutionPath.CORRECTED_CLAIM:
                deadline = rules.correction_deadline(record.submitted.service_date)
                citations = (*citations, *rules.citations)
            return Resolution(
                patient_control_number=record.patient_control_number,
                line_control_number=record.line_control_number,
                lane=Lane.DETERMINISTIC,
                path=rule.action,
                rule_id=rule.id,
                rationale=rule.rationale.strip(),
                citations=citations,
                filing_deadline=deadline,
            )
    return Resolution(
        patient_control_number=record.patient_control_number,
        line_control_number=record.line_control_number,
        lane=Lane.HUMAN,
        path=ResolutionPath.NEEDS_HUMAN,
        rationale=(
            f"No playbook rule covers CARC {record.primary_carc}"
            f"{' with ' + ', '.join(record.remark_codes) if record.remark_codes else ''}."
            " This needs a reviewer's judgment."
        ),
    )
