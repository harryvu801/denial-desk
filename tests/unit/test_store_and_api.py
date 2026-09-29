from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DatabaseError

from denial_desk.api.main import create_app
from denial_desk.ingest.pipeline import ingest_directory
from denial_desk.persistence.store import make_engine, queue_stats, session_scope

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return make_engine(f"sqlite:///{tmp_path / 'test.db'}")


def test_ingest_is_idempotent(engine: Engine) -> None:
    with session_scope(engine) as s:
        first = ingest_directory(s, FIXTURES)
    with session_scope(engine) as s:
        second = ingest_directory(s, FIXTURES)
        stats = queue_stats(s)
    assert first.denials_new == 2
    assert second.remittances_skipped == 1 and second.denials_new == 0
    assert stats.total == 2


def test_decision_audit_is_append_only(engine: Engine) -> None:
    with session_scope(engine) as s:
        ingest_directory(s, FIXTURES)
    for statement in ("UPDATE decision_audit SET note = 'x'", "DELETE FROM decision_audit"):
        with pytest.raises(DatabaseError, match="append-only"), engine.begin() as conn:
            conn.execute(text(statement))


def test_review_flow(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'api.db'}"
    with session_scope(make_engine(url)) as s:
        ingest_directory(s, FIXTURES)
    client = TestClient(create_app(url))

    assert client.get("/healthz").json() == {"status": "ok"}
    queue = client.get("/")
    assert queue.status_code == 200 and "PCN-A-2" in queue.text

    # Denial 1 (CARC 4, modifier) is a rules-lane proposal; approving records the decision.
    resp = client.post("/denials/1/review", data={"action": "approve"}, follow_redirects=False)
    assert resp.status_code == 303
    detail = client.get("/denials/1").text
    assert "approved" in detail and "corrected claim" in detail

    # Overriding to NEEDS_HUMAN is not a decision.
    bad = client.post(
        "/denials/2/review", data={"action": "override", "override_path": "needs_human"}
    )
    assert bad.status_code == 422
    assert client.get("/audit").status_code == 200
