"""The model lane inside ingest: only human-lane denials reach it, a handoff or a
low-confidence answer stays with a human, and a model action is stored with provenance."""

from pathlib import Path
from string import Template

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from denial_desk.agent.input import ProposalRequest
from denial_desk.agent.lane import ModelLane
from denial_desk.agent.prompts import Prompt
from denial_desk.agent.proposer import StubProposer
from denial_desk.agent.schemas import ModelProposal
from denial_desk.api.main import create_app
from denial_desk.domain.models import ResolutionPath, RootCause
from denial_desk.ingest.generator import generate
from denial_desk.ingest.pipeline import ingest_directory
from denial_desk.persistence.models import DecisionAudit, DenialRow
from denial_desk.persistence.store import make_engine, session_scope
from denial_desk.triage.rules import triage

PROMPT = Prompt("classify", "vtest", "Decide.", Template("$denial $case_file $care_note"), "t1")


def _lane(
    confidence: float, action: ResolutionPath = ResolutionPath.APPEAL
) -> tuple[ModelLane, list[str]]:
    """A stub model lane, plus the list of lines it was asked about."""
    seen: list[str] = []

    def decide(request: ProposalRequest) -> ModelProposal:
        seen.append(request.line_control_number)
        return ModelProposal(
            action=action,
            root_cause=RootCause.MEDICAL_NECESSITY,
            confidence=confidence,
            evidence=["care_note"],
            rationale="stub",
        )

    return ModelLane(StubProposer(decide, "stub-model"), PROMPT, 0.7, {}), seen


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("syn")
    generate(out, 300, seed=42)
    return out


def _ingest(tmp_path: Path, synthetic: Path, lane: ModelLane) -> str:
    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    with session_scope(make_engine(url)) as s:
        ingest_directory(s, synthetic, as_of=None, model_lane=lane)
    return url


def test_only_human_lane_denials_reach_the_model(tmp_path: Path, synthetic: Path) -> None:
    lane, seen = _lane(0.9)
    url = _ingest(tmp_path, synthetic, lane)
    with session_scope(make_engine(url)) as s:
        rows = list(s.scalars(select(DenialRow)))
        model_rows = [r for r in rows if r.lane == "model"]
        assert model_rows and len(model_rows) == len(seen)
        assert not any(r.lane == "deterministic" and r.model_meta for r in rows)
        row = model_rows[0]
        assert row.proposed_path == "appeal" and row.case_file is not None
        assert row.model_meta and row.model_meta["evidence"] == ["care_note"]
        audit = s.scalar(select(DecisionAudit).where(DecisionAudit.denial_id == row.id))
        assert audit is not None and audit.actor == "model:stub-model"


def test_low_confidence_stays_with_a_human(tmp_path: Path, synthetic: Path) -> None:
    url = _ingest(tmp_path, synthetic, _lane(0.5)[0])
    with session_scope(make_engine(url)) as s:
        rows = list(s.scalars(select(DenialRow).where(DenialRow.model_meta.is_not(None))))
        assert rows and all(r.lane == "human" and r.proposed_path == "needs_human" for r in rows)
        assert "handed off" in rows[0].rationale


def test_review_screen_shows_the_model_lane(tmp_path: Path, synthetic: Path) -> None:
    url = _ingest(tmp_path, synthetic, _lane(0.9, ResolutionPath.CORRECTED_CLAIM)[0])
    client = TestClient(create_app(url))
    assert "badge model" in client.get("/?lane=model").text
    with session_scope(make_engine(url)) as s:
        row = s.scalar(select(DenialRow).where(DenialRow.lane == "model"))
        assert row is not None and row.filing_deadline is not None  # code computed it
        page = client.get(f"/denials/{row.id}").text
    assert "Case file" in page and "untrusted" in page and "Model said" in page


def test_expired_correction_window_goes_to_a_human(synthetic: Path) -> None:
    """The rules lane refuses to propose a corrected claim whose window has closed; the
    model lane must do the same, keeping the model's view for the reviewer."""
    from datetime import date

    from evals.cases import build_eval_set

    case = build_eval_set(42, 300, synthetic.parent).cases[0]
    lane, _ = _lane(0.95, ResolutionPath.CORRECTED_CLAIM)
    handed_off = triage(case.record, as_of=case.record.adjudication_date)

    fresh, meta = lane.propose(
        case.record, case.case_file, handed_off, as_of=case.record.adjudication_date
    )
    assert fresh.lane.value == "model" and fresh.path is ResolutionPath.CORRECTED_CLAIM
    assert fresh.filing_deadline is not None and "expired_window" not in meta

    late, meta = lane.propose(case.record, case.case_file, handed_off, as_of=date(2040, 1, 1))
    assert late.lane.value == "human" and late.path is ResolutionPath.NEEDS_HUMAN
    assert late.filing_deadline == fresh.filing_deadline
    assert "correction window closed" in late.rationale and "stub" in late.rationale
    assert meta["expired_window"] == "correction" and meta["action"] == "corrected_claim"


def test_model_appeal_gets_a_deadline_from_the_payer_clocks(synthetic: Path) -> None:
    from datetime import date

    from evals.cases import build_eval_set

    cases = build_eval_set(42, 300, synthetic.parent).cases
    lane, _ = _lane(0.95, ResolutionPath.APPEAL)
    known = next(c for c in cases if c.record.payer.value == "NV")
    unknown = next(c for c in cases if c.record.payer.value == "ID")

    res, _ = lane.propose(
        known.record,
        known.case_file,
        triage(known.record, as_of=date(2026, 1, 1)),
        as_of=known.record.adjudication_date,
    )
    assert res.path is ResolutionPath.APPEAL and res.filing_deadline is not None
    assert any("Claim Appeals" in c for c in res.citations)
    late, meta = lane.propose(
        known.record,
        known.case_file,
        triage(known.record, as_of=date(2026, 1, 1)),
        as_of=date(2040, 1, 1),
    )
    assert late.path is ResolutionPath.NEEDS_HUMAN and meta["expired_window"] == "appeal"

    # Idaho's window is unknown: an appeal is still proposed, with no deadline invented.
    res, meta = lane.propose(
        unknown.record,
        unknown.case_file,
        triage(unknown.record, as_of=date(2026, 1, 1)),
        as_of=date(2040, 1, 1),
    )
    assert res.path is ResolutionPath.APPEAL and res.filing_deadline is None
    assert "expired_window" not in meta
