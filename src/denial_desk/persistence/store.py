"""Database access: engine, idempotent writes, the review action, and queue queries."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from denial_desk.domain.models import DenialRecord, Lane, Resolution, ResolutionPath
from denial_desk.persistence.models import Base, DecisionAudit, DenialRow, RemittanceRow


class ReviewAction(StrEnum):
    APPROVE = "approve"
    OVERRIDE = "override"
    REJECT = "reject"


_STATUS = {
    ReviewAction.APPROVE: "approved",
    ReviewAction.OVERRIDE: "overridden",
    ReviewAction.REJECT: "rejected",
}


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    return engine


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Commit on success, roll back on any exception. Like a transaction-scoped `using`."""
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session, session.begin():
        yield session


def remittance_seen(session: Session, trace_number: str) -> bool:
    return (
        session.scalar(select(RemittanceRow.id).where(RemittanceRow.trace_number == trace_number))
        is not None
    )


def record_remittance(session: Session, trace_number: str, payer: str, payment_date: date) -> None:
    session.add(RemittanceRow(trace_number=trace_number, payer=payer, payment_date=payment_date))


def save_denial(session: Session, record: DenialRecord, resolution: Resolution) -> bool:
    """Insert a denial and its proposal. Returns False (and writes nothing) if this
    (patient control number, line control number) already exists — re-ingest is a no-op."""
    exists = session.scalar(
        select(DenialRow.id).where(
            DenialRow.patient_control_number == record.patient_control_number,
            DenialRow.line_control_number == record.line_control_number,
        )
    )
    if exists is not None:
        return False
    row = DenialRow(
        patient_control_number=record.patient_control_number,
        line_control_number=record.line_control_number,
        payer=record.payer.value,
        procedure_code=record.submitted.procedure_code,
        primary_carc=record.primary_carc,
        remark_codes=",".join(record.remark_codes),
        denied_amount=record.denied_amount,
        service_date=record.submitted.service_date,
        adjudication_date=record.adjudication_date,
        record=record.model_dump(mode="json"),
        lane=resolution.lane.value,
        proposed_path=resolution.path.value,
        rule_id=resolution.rule_id,
        rationale=resolution.rationale,
        citations=list(resolution.citations),
        filing_deadline=resolution.filing_deadline,
    )
    session.add(row)
    session.flush()  # assigns row.id
    session.add(
        DecisionAudit(
            denial_id=row.id,
            event="proposed",
            actor="system",
            lane=resolution.lane.value,
            path=resolution.path.value,
            rule_id=resolution.rule_id,
            note=resolution.rationale,
        )
    )
    return True


def review(
    session: Session,
    denial_id: int,
    action: ReviewAction,
    reviewer: str,
    note: str = "",
    override_path: ResolutionPath | None = None,
) -> DenialRow:
    """Record a human decision. Nothing is submitted anywhere — see ADR-007."""
    row = session.get(DenialRow, denial_id)
    if row is None:
        raise LookupError(f"denial {denial_id} not found")
    if action is ReviewAction.OVERRIDE:
        if override_path is None or override_path is ResolutionPath.NEEDS_HUMAN:
            raise ValueError("an override needs a concrete resolution path")
        final = override_path.value
    elif action is ReviewAction.APPROVE:
        if row.proposed_path == ResolutionPath.NEEDS_HUMAN.value:
            raise ValueError("nothing to approve: choose a path with override")
        final = row.proposed_path
    else:
        final = None
    row.status = _STATUS[action]
    row.final_path = final
    session.add(
        DecisionAudit(denial_id=row.id, event=row.status, actor=reviewer, path=final, note=note)
    )
    return row


def list_denials(
    session: Session, status: str | None = None, lane: str | None = None, payer: str | None = None
) -> list[DenialRow]:
    stmt = select(DenialRow).order_by(DenialRow.denied_amount.desc(), DenialRow.id)
    if status:
        stmt = stmt.where(DenialRow.status == status)
    if lane:
        stmt = stmt.where(DenialRow.lane == lane)
    if payer:
        stmt = stmt.where(DenialRow.payer == payer)
    return list(session.scalars(stmt))


def get_denial(session: Session, denial_id: int) -> DenialRow | None:
    return session.scalar(
        select(DenialRow).where(DenialRow.id == denial_id).options(selectinload(DenialRow.audit))
    )


def recent_audit(session: Session, limit: int = 100) -> list[DecisionAudit]:
    return list(
        session.scalars(select(DecisionAudit).order_by(DecisionAudit.id.desc()).limit(limit))
    )


@dataclass(frozen=True)
class QueueStats:
    total: int
    deterministic: int
    pending: int
    dollars_at_risk: Decimal

    @property
    def deterministic_share(self) -> float:
        return self.deterministic / self.total if self.total else 0.0


def queue_stats(session: Session) -> QueueStats:
    total = session.scalar(select(func.count(DenialRow.id))) or 0
    deterministic = (
        session.scalar(
            select(func.count(DenialRow.id)).where(DenialRow.lane == Lane.DETERMINISTIC.value)
        )
        or 0
    )
    pending = (
        session.scalar(select(func.count(DenialRow.id)).where(DenialRow.status == "pending")) or 0
    )
    dollars = session.scalar(
        select(func.coalesce(func.sum(DenialRow.denied_amount), 0)).where(
            DenialRow.status == "pending"
        )
    )
    return QueueStats(total, deterministic, pending, Decimal(dollars or 0))
