"""SQLAlchemy models.

  - `denials` has a natural unique key on (patient_control_number, line_control_number):
    re-ingesting the same files converges to the same rows. See ADR-028.
  - `remittances` records each 835 by its TRN02 trace number, so a re-sent file is a no-op.
  - `decision_audit` is append-only, enforced by database triggers rather than by
    convention: an UPDATE or DELETE fails at the database. See ADR-007.

Runs on SQLite (local default) and Postgres; the trigger DDL is emitted per dialect.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Connection,
    ForeignKey,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class RemittanceRow(Base):
    __tablename__ = "remittances"

    id: Mapped[int] = mapped_column(primary_key=True)
    trace_number: Mapped[str] = mapped_column(String(50), unique=True)
    payer: Mapped[str] = mapped_column(String(2))
    payment_date: Mapped[date]
    ingested_at: Mapped[datetime] = mapped_column(default=_now)


class DenialRow(Base):
    __tablename__ = "denials"
    __table_args__ = (UniqueConstraint("patient_control_number", "line_control_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_control_number: Mapped[str] = mapped_column(String(38))
    line_control_number: Mapped[str] = mapped_column(String(50))
    payer: Mapped[str] = mapped_column(String(2), index=True)
    procedure_code: Mapped[str] = mapped_column(String(5))
    primary_carc: Mapped[str] = mapped_column(String(5), index=True)
    remark_codes: Mapped[str] = mapped_column(String(100), default="")
    denied_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    service_date: Mapped[date]
    adjudication_date: Mapped[date]
    record: Mapped[dict[str, Any]] = mapped_column(JSON)

    # The system's proposal — written once at ingest.
    lane: Mapped[str] = mapped_column(String(20), index=True)
    proposed_path: Mapped[str] = mapped_column(String(20))
    rule_id: Mapped[str | None] = mapped_column(String(60))
    rationale: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[str]] = mapped_column(JSON)
    filing_deadline: Mapped[date | None]

    # The human decision — the only mutable part, and every change is also audited.
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    final_path: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(default=_now)

    audit: Mapped[list[DecisionAudit]] = relationship(
        back_populates="denial", order_by="DecisionAudit.id"
    )


class DecisionAudit(Base):
    __tablename__ = "decision_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    denial_id: Mapped[int] = mapped_column(ForeignKey("denials.id"), index=True)
    event: Mapped[str] = mapped_column(String(20))  # proposed | approved | overridden | rejected
    actor: Mapped[str] = mapped_column(String(60))  # "system" or the reviewer
    lane: Mapped[str | None] = mapped_column(String(20))
    path: Mapped[str | None] = mapped_column(String(20))
    rule_id: Mapped[str | None] = mapped_column(String(60))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=_now)

    denial: Mapped[DenialRow] = relationship(back_populates="audit")


_APPEND_ONLY = "decision_audit is append-only"

_TRIGGERS = {
    "sqlite": [
        f"CREATE TRIGGER decision_audit_no_{op.lower()} BEFORE {op} ON decision_audit "
        f"BEGIN SELECT RAISE(ABORT, '{_APPEND_ONLY}'); END"
        for op in ("UPDATE", "DELETE")
    ],
    "postgresql": [
        "CREATE FUNCTION decision_audit_append_only() RETURNS trigger AS $$ "
        f"BEGIN RAISE EXCEPTION '{_APPEND_ONLY}'; END; $$ LANGUAGE plpgsql",
        "CREATE TRIGGER decision_audit_append_only BEFORE UPDATE OR DELETE ON decision_audit "
        "FOR EACH ROW EXECUTE FUNCTION decision_audit_append_only()",
    ],
}


@event.listens_for(DecisionAudit.__table__, "after_create")
def _install_append_only_triggers(_target: Table, connection: Connection, **_: Any) -> None:
    """Runs once, right after CREATE TABLE decision_audit, in the same transaction."""
    for statement in _TRIGGERS.get(connection.dialect.name, []):
        connection.execute(text(statement))
