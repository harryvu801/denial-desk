"""Ingest a directory of 837P/835 files: parse, join, triage, persist.

Idempotent at two levels: an 835 whose TRN02 trace number was already ingested is skipped,
and a denial whose (patient control number, line control number) already exists is not
rewritten. Running ingest twice on the same directory changes nothing the second time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from denial_desk.domain.models import Lane
from denial_desk.ingest.join import JoinIssue, join
from denial_desk.ingest.x12.parser_835 import parse_835
from denial_desk.ingest.x12.parser_837p import parse_837p
from denial_desk.persistence.store import record_remittance, remittance_seen, save_denial
from denial_desk.triage.rules import triage


@dataclass
class IngestSummary:
    files_837: int = 0
    files_835: int = 0
    remittances_skipped: int = 0
    denials_new: int = 0
    denials_existing: int = 0
    deterministic: int = 0
    issues: list[JoinIssue] = field(default_factory=list)


def ingest_directory(session: Session, directory: Path, *, as_of: date | None) -> IngestSummary:
    """Triage every new denial as of `as_of` (production: today). With `as_of=None` each
    denial is triaged as of its own 835 payment date — replaying history as if every file
    had been ingested the day it arrived, which is what makes synthetic runs reproducible."""
    summary = IngestSummary()
    claims = []
    for path in sorted(directory.glob("*.837")):
        claims.extend(parse_837p(path.read_text()))
        summary.files_837 += 1

    remittances = []
    for path in sorted(directory.glob("*.835")):
        remit = parse_835(path.read_text())
        summary.files_835 += 1
        if remittance_seen(session, remit.trace_number):
            summary.remittances_skipped += 1
            continue
        record_remittance(session, remit.trace_number, remit.payer.value, remit.payment_date)
        remittances.append(remit)

    denials, summary.issues = join(claims, remittances)
    for record in denials:
        resolution = triage(record, as_of=as_of or record.adjudication_date)
        if save_denial(session, record, resolution):
            summary.denials_new += 1
            summary.deterministic += resolution.lane is Lane.DETERMINISTIC
        else:
            summary.denials_existing += 1
    return summary
