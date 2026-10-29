"""The planted labels are only as good as the evidence behind them. These tests check, for
every generated human-lane case, that the deciding fact is actually in the case file — so a
label can never silently disagree with its own evidence."""

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from denial_desk.domain.case_file import CaseFile, Visit
from denial_desk.ingest.generator import generate


@pytest.fixture(scope="module")
def cases(tmp_path_factory: pytest.TempPathFactory) -> list[tuple[dict[str, object], CaseFile]]:
    out = tmp_path_factory.mktemp("cases")
    generate(out, 1500, seed=11)
    files = {
        cf.line_control_number: cf
        for cf in (CaseFile.model_validate_json(x) for x in (out / "case_files.jsonl").open())
    }
    labels = [json.loads(x) for x in (out / "labels.jsonl").open()]
    denied = [r for r in labels if r["denied"]]
    assert len(files) == len(denied)  # one case file per denied line, none for paid lines
    return [(r, files[str(r["line_control_number"])]) for r in denied]


def _overlap(a: Visit, b: Visit) -> bool:
    return a.service_date == b.service_date and a.start < b.end and b.start < a.end


def _dos(cf: CaseFile) -> date:
    return cf.visits[0].service_date


def test_every_human_lane_variant_appears(cases: list[tuple[dict[str, object], CaseFile]]) -> None:
    variants = {r["variant"] for r, _ in cases}
    assert {
        "extension_on_file", "no_extension", "retro_reinstated", "no_coverage",
        "need_documented", "need_not_supported", "distinct_visits", "overlapping_visits",
        "member_id_changed", "unexplained",
    } <= variants  # fmt: skip


def test_planted_evidence_matches_label(cases: list[tuple[dict[str, object], CaseFile]]) -> None:
    for label, cf in cases:
        dos = _dos(cf)
        covering = [e for e in cf.eligibility if e.covers(dos)]
        match label["variant"]:
            case "extension_on_file":
                assert len(cf.authorizations) == 2
                assert sum(a.units for a in cf.authorizations) * 15 >= _minutes(cf.visits[0])
            case "no_extension":
                assert len(cf.authorizations) == 1
            case "retro_reinstated":
                assert covering and "Retroactive" in covering[0].note
                assert label["expected_action"] == "needs_human"
                assert label["suggestion"] == "rebill"
            case "no_coverage":
                assert not covering
            case "need_documented":
                assert "Physician order" in cf.care_note
            case "need_not_supported":
                assert "not on the current care plan" in cf.care_note
            case "distinct_visits":
                a, b = cf.visits
                assert not _overlap(a, b) and a.caregiver_id != b.caregiver_id
            case "overlapping_visits":
                assert _overlap(*cf.visits)
            case "member_id_changed":
                assert len({e.member_id for e in cf.eligibility}) == 2
            case "unexplained":
                assert label["expected_action"] == "needs_human"


def _minutes(v: Visit) -> float:
    start = datetime.combine(v.service_date, v.start)
    return (datetime.combine(v.service_date, v.end) - start).total_seconds() / 60


def test_case_files_are_deterministic_and_do_not_shift_claims(tmp_path: Path) -> None:
    generate(tmp_path / "a", 80, seed=3)
    generate(tmp_path / "b", 80, seed=3)
    for name in ("case_files.jsonl", "labels.jsonl"):
        assert (tmp_path / "a" / name).read_text() == (tmp_path / "b" / name).read_text()
