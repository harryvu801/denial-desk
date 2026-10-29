import json
from collections import Counter
from pathlib import Path

import pytest

from denial_desk.domain.models import Lane, ResolutionPath
from denial_desk.ingest.generator import generate
from denial_desk.ingest.join import join
from denial_desk.ingest.x12.parser_835 import parse_835
from denial_desk.ingest.x12.parser_837p import parse_837p
from denial_desk.triage.rules import load_playbook, triage


def _read(directory: Path) -> dict[str, str]:
    return {p.name: p.read_text() for p in sorted(directory.iterdir())}


def test_generator_is_deterministic(tmp_path: Path) -> None:
    generate(tmp_path / "a", 60, seed=7)
    generate(tmp_path / "b", 60, seed=7)
    generate(tmp_path / "c", 60, seed=8)
    assert _read(tmp_path / "a") == _read(tmp_path / "b")
    assert _read(tmp_path / "a") != _read(tmp_path / "c")


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("gen")
    generate(out, 400, seed=42)
    return out


def test_round_trip_matches_manifest(generated: Path) -> None:
    claims = [c for f in sorted(generated.glob("*.837")) for c in parse_837p(f.read_text())]
    remits = [parse_835(f.read_text()) for f in sorted(generated.glob("*.835"))]
    denials, issues = join(claims, remits)
    labels = [json.loads(line) for line in (generated / "labels.jsonl").open()]
    denied = {
        (r["patient_control_number"], r["line_control_number"]): r for r in labels if r["denied"]
    }

    assert issues == []
    assert {(d.patient_control_number, d.line_control_number) for d in denials} == set(denied)
    for d in denials:
        assert d.primary_carc == denied[(d.patient_control_number, d.line_control_number)]["carc"]


def test_labels_are_root_causes_not_carcs(generated: Path) -> None:
    labels = [json.loads(line) for line in (generated / "labels.jsonl").open()]
    causes_per_carc = Counter(
        r["carc"] for r in {(r["carc"], r["root_cause"]): r for r in labels if r["denied"]}.values()
    )
    assert causes_per_carc["16"] >= 2  # one CARC, several root causes


EXPECTED = {
    "timely_filing": (Lane.DETERMINISTIC, ResolutionPath.WRITE_OFF),
    "duplicate_submission": (Lane.DETERMINISTIC, ResolutionPath.NO_ACTION),
    "missing_prior_auth": (Lane.DETERMINISTIC, ResolutionPath.CORRECTED_CLAIM),
    "missing_rendering_npi": (Lane.DETERMINISTIC, ResolutionPath.CORRECTED_CLAIM),
    "invalid_procedure_code": (Lane.DETERMINISTIC, ResolutionPath.CORRECTED_CLAIM),
    "missing_modifier": (Lane.DETERMINISTIC, ResolutionPath.CORRECTED_CLAIM),
    "other_insurance_primary": (Lane.DETERMINISTIC, ResolutionPath.CORRECTED_CLAIM),
    "member_id_mismatch": (Lane.DETERMINISTIC, ResolutionPath.CORRECTED_CLAIM),
    "frequency_limit": (Lane.DETERMINISTIC, ResolutionPath.WRITE_OFF),
    "coverage_terminated": (Lane.HUMAN, ResolutionPath.NEEDS_HUMAN),
    "units_exceed_auth": (Lane.HUMAN, ResolutionPath.NEEDS_HUMAN),
    "medical_necessity": (Lane.HUMAN, ResolutionPath.NEEDS_HUMAN),
    "bundled_service": (Lane.HUMAN, ResolutionPath.NEEDS_HUMAN),
    "missing_information_unspecified": (Lane.HUMAN, ResolutionPath.NEEDS_HUMAN),
}


def test_rules_lane_against_ground_truth(generated: Path) -> None:
    claims = [c for f in sorted(generated.glob("*.837")) for c in parse_837p(f.read_text())]
    remits = [parse_835(f.read_text()) for f in sorted(generated.glob("*.835"))]
    denials, _ = join(claims, remits)
    labels = {
        (r["patient_control_number"], r["line_control_number"]): r["root_cause"]
        for r in map(json.loads, (generated / "labels.jsonl").open())
    }
    for d in denials:
        res = triage(d, as_of=d.adjudication_date)
        cause = labels[(d.patient_control_number, d.line_control_number)]
        assert (res.lane, res.path) == EXPECTED[cause], cause
        if res.path is ResolutionPath.CORRECTED_CLAIM:
            assert res.filing_deadline is not None


def test_every_rule_cites_something() -> None:
    assert all(rule.citations for rule in load_playbook().rules)
    assert 12 <= len(load_playbook().rules) <= 20
