"""837P (professional claim) parser — the claim as submitted.

Scope is deliberately narrow (ADR-003): the billing provider and subscriber hierarchy
(2000A/2000B), the payer (2010BB), the claim (2300) and its service lines (2400). Every other
segment is skipped without error, so real files with extra loops still parse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from denial_desk.domain.models import Payer, SubmittedClaim, SubmittedLine
from denial_desk.ingest.x12.segments import Segment, X12Error, tokenize


def parse_date(value: str) -> date:
    """X12 dates are CCYYMMDD."""
    return datetime.strptime(value, "%Y%m%d").date()


@dataclass
class _LineBuilder:
    line_number: int
    procedure_code: str = ""
    modifiers: tuple[str, ...] = ()
    charge: Decimal = Decimal(0)
    units: Decimal = Decimal(0)
    service_date: date | None = None
    line_control_number: str = ""

    def build(self) -> SubmittedLine:
        if self.service_date is None:
            raise X12Error(f"service line {self.line_number} has no DTP*472 service date")
        return SubmittedLine(
            line_number=self.line_number,
            line_control_number=self.line_control_number,
            procedure_code=self.procedure_code,
            modifiers=self.modifiers,
            charge=self.charge,
            units=self.units,
            service_date=self.service_date,
        )


@dataclass
class _ClaimBuilder:
    patient_control_number: str
    total_charge: Decimal
    frequency_code: str
    payer: Payer
    member_id: str
    submission_date: date
    prior_auth_number: str | None = None
    lines: list[_LineBuilder] = field(default_factory=list)

    def build(self) -> SubmittedClaim:
        return SubmittedClaim(
            patient_control_number=self.patient_control_number,
            payer=self.payer,
            member_id=self.member_id,
            total_charge=self.total_charge,
            submission_date=self.submission_date,
            frequency_code=self.frequency_code,
            prior_auth_number=self.prior_auth_number,
            lines=tuple(ln.build() for ln in self.lines),
        )


def parse_837p(raw: str) -> list[SubmittedClaim]:
    """Return every claim in the interchange, in file order."""
    submission_date: date | None = None
    payer: Payer | None = None
    member_id = ""
    claims: list[_ClaimBuilder] = []
    claim: _ClaimBuilder | None = None
    line: _LineBuilder | None = None

    seg: Segment
    for seg in tokenize(raw):
        match seg.tag:
            case "BHT":
                submission_date = parse_date(seg.el(4))
            case "HL":
                # A new hierarchical level closes any open claim and line.
                claim, line = None, None
            case "NM1" if seg.el(1) == "IL":
                member_id = seg.el(9)
            case "NM1" if seg.el(1) == "PR":
                try:
                    payer = Payer(seg.el(9))
                except ValueError as exc:
                    raise X12Error(f"unsupported payer id {seg.el(9)!r}") from exc
            case "CLM":
                if payer is None or submission_date is None:
                    raise X12Error("CLM before BHT and payer NM1*PR")
                frequency = seg.composite(5)
                claim = _ClaimBuilder(
                    patient_control_number=seg.el(1),
                    total_charge=Decimal(seg.el(2)),
                    frequency_code=frequency[2] if len(frequency) > 2 else "1",
                    payer=payer,
                    member_id=member_id,
                    submission_date=submission_date,
                )
                claims.append(claim)
                line = None
            case "REF" if claim is not None and line is None and seg.el(1) == "G1":
                claim.prior_auth_number = seg.el(2)
            case "LX" if claim is not None:
                line = _LineBuilder(line_number=int(seg.el(1)))
                claim.lines.append(line)
            case "SV1" if line is not None:
                procedure = seg.composite(1)
                line.procedure_code = procedure[1]
                line.modifiers = tuple(m for m in procedure[2:] if m)
                line.charge = Decimal(seg.el(2))
                line.units = Decimal(seg.el(4))
            case "DTP" if line is not None and seg.el(1) == "472":
                line.service_date = parse_date(seg.el(3))
            case "REF" if line is not None and seg.el(1) == "6R":
                line.line_control_number = seg.el(2)
            case _:
                pass

    return [c.build() for c in claims]
