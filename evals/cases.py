"""The model-lane eval set: the denials the rules hand to a human, with their case files and
planted expected actions (ADR-029).

Built from the generator rather than loaded from a committed blob: (seed, claim count,
generator version) reproduces it exactly. The cases are the ones the real pipeline routes
to the human lane — parse, join, triage — not a hand-picked list, so the eval measures the
lane as it actually runs.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from denial_desk.domain.case_file import CaseFile
from denial_desk.domain.models import DenialRecord, Lane, ResolutionPath, RootCause
from denial_desk.ingest.generator import GENERATOR_VERSION, generate
from denial_desk.ingest.join import join
from denial_desk.ingest.x12.parser_835 import parse_835
from denial_desk.ingest.x12.parser_837p import parse_837p
from denial_desk.triage.rules import triage

EVAL_ROOT = Path(__file__).parent.parent / "data" / "eval"


@dataclass(frozen=True)
class EvalCase:
    record: DenialRecord
    case_file: CaseFile
    expected_action: ResolutionPath
    root_cause: RootCause
    variant: str
    suggestion: str | None

    @property
    def key(self) -> str:
        return self.record.line_control_number


@dataclass(frozen=True)
class EvalSet:
    seed: int
    n_claims: int
    generator_version: str
    cases: tuple[EvalCase, ...]


def build_eval_set(seed: int, n_claims: int, root: Path = EVAL_ROOT) -> EvalSet:
    directory = root / f"seed{seed}-n{n_claims}"
    generate(directory, n_claims, seed)
    claims = [c for f in sorted(directory.glob("*.837")) for c in parse_837p(f.read_text())]
    remits = [parse_835(f.read_text()) for f in sorted(directory.glob("*.835"))]
    denials, _ = join(claims, remits)

    labels = {
        row["line_control_number"]: row
        for row in map(json.loads, (directory / "labels.jsonl").read_text().splitlines())
    }
    files = {
        cf.line_control_number: cf
        for cf in map(
            CaseFile.model_validate_json, (directory / "case_files.jsonl").read_text().splitlines()
        )
    }
    cases = []
    for record in denials:
        if triage(record, as_of=record.adjudication_date).lane is not Lane.HUMAN:
            continue
        label = labels[record.line_control_number]
        cases.append(
            EvalCase(
                record=record,
                case_file=files[record.line_control_number],
                expected_action=ResolutionPath(label["expected_action"]),
                root_cause=RootCause(label["root_cause"]),
                variant=label["variant"],
                suggestion=label["suggestion"],
            )
        )
    return EvalSet(seed, n_claims, GENERATOR_VERSION, tuple(cases))


def fit_carc_majority(train: EvalSet) -> dict[str, ResolutionPath]:
    """Baseline: the most common expected action per primary CARC, fit on a *different*
    seed than the one it is scored on. It answers: does reading the case file beat knowing
    the CARC? Ties break toward needs_human, the safe answer."""
    by_carc: dict[str, Counter[ResolutionPath]] = {}
    for case in train.cases:
        by_carc.setdefault(case.record.primary_carc, Counter())[case.expected_action] += 1
    return {
        carc: max(counts, key=lambda a: (counts[a], a is ResolutionPath.NEEDS_HUMAN))
        for carc, counts in by_carc.items()
    }
