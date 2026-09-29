"""835 (remittance advice) parser — what the payer paid and why it didn't.

Scope (ADR-003): BPR/TRN for the payment, N1*PR for the payer, and per claim the CLP,
claim-level CAS and MOA, then per service line SVC, CAS, REF*6R and LQ*HE.

CAS handling, the part that matters most:
  - CAS01 is the group code; then up to six (reason, amount, quantity) triplets follow in
    CAS02-04, 05-07, ... 17-19. One CAS segment can therefore carry several CARCs.
  - A CAS before the first SVC of a claim is claim-level; after an SVC it belongs to that line.
  - Every line must balance: charge - paid == sum of its adjustments. The domain model
    enforces this, so an unbalanced 835 fails here rather than producing a wrong denial.
  - Reversals (CLP02 = 22) are parsed and returned; deciding what to do with them is the
    caller's job, not the parser's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from denial_desk.domain.models import (
    AdjudicatedClaim,
    AdjudicatedLine,
    Adjustment,
    GroupCode,
    Payer,
    Remittance,
)
from denial_desk.ingest.x12.parser_837p import parse_date
from denial_desk.ingest.x12.segments import Segment, X12Error, tokenize

CAS_MAX_TRIPLETS = 6


def parse_cas(seg: Segment) -> list[Adjustment]:
    """Explode one CAS segment into one Adjustment per reason code."""
    try:
        group = GroupCode(seg.el(1))
    except ValueError as exc:
        raise X12Error(f"unknown CAS group code {seg.el(1)!r}") from exc
    adjustments: list[Adjustment] = []
    for i in range(CAS_MAX_TRIPLETS):
        reason, amount, quantity = seg.el(2 + 3 * i), seg.el(3 + 3 * i), seg.el(4 + 3 * i)
        if not reason:
            break
        adjustments.append(
            Adjustment(
                group_code=group,
                reason_code=reason,
                amount=Decimal(amount),
                quantity=Decimal(quantity) if quantity else None,
            )
        )
    return adjustments


@dataclass
class _LineBuilder:
    procedure_code: str
    modifiers: tuple[str, ...]
    charge: Decimal
    paid: Decimal
    units: Decimal
    line_control_number: str | None = None
    adjustments: list[Adjustment] = field(default_factory=list)
    remark_codes: list[str] = field(default_factory=list)

    def build(self) -> AdjudicatedLine:
        return AdjudicatedLine(
            line_control_number=self.line_control_number,
            procedure_code=self.procedure_code,
            modifiers=self.modifiers,
            charge=self.charge,
            paid=self.paid,
            units=self.units,
            adjustments=tuple(self.adjustments),
            remark_codes=tuple(self.remark_codes),
        )


@dataclass
class _ClaimBuilder:
    patient_control_number: str
    status_code: str
    charge: Decimal
    paid: Decimal
    payer_claim_control_number: str
    adjustments: list[Adjustment] = field(default_factory=list)
    remark_codes: list[str] = field(default_factory=list)
    lines: list[_LineBuilder] = field(default_factory=list)

    def build(self) -> AdjudicatedClaim:
        return AdjudicatedClaim(
            patient_control_number=self.patient_control_number,
            status_code=self.status_code,
            charge=self.charge,
            paid=self.paid,
            payer_claim_control_number=self.payer_claim_control_number,
            claim_adjustments=tuple(self.adjustments),
            claim_remark_codes=tuple(self.remark_codes),
            lines=tuple(ln.build() for ln in self.lines),
        )


def parse_835(raw: str) -> Remittance:
    """Parse one 835 transaction into a Remittance."""
    payment_date: date | None = None
    trace_number = ""
    payer: Payer | None = None
    claims: list[_ClaimBuilder] = []
    claim: _ClaimBuilder | None = None
    line: _LineBuilder | None = None

    for seg in tokenize(raw):
        match seg.tag:
            case "BPR":
                payment_date = parse_date(seg.el(16))
            case "TRN":
                trace_number = seg.el(2)
            case "N1" if seg.el(1) == "PR":
                try:
                    payer = Payer(seg.el(4))
                except ValueError as exc:
                    raise X12Error(f"unsupported payer id {seg.el(4)!r}") from exc
            case "CLP":
                claim = _ClaimBuilder(
                    patient_control_number=seg.el(1),
                    status_code=seg.el(2),
                    charge=Decimal(seg.el(3)),
                    paid=Decimal(seg.el(4) or "0"),
                    payer_claim_control_number=seg.el(7),
                )
                claims.append(claim)
                line = None
            case "CAS" if claim is not None:
                target = line.adjustments if line is not None else claim.adjustments
                target.extend(parse_cas(seg))
            case "MOA" if claim is not None:
                claim.remark_codes.extend(code for code in seg.elements[2:7] if code)
            case "SVC" if claim is not None:
                procedure = seg.composite(1)
                line = _LineBuilder(
                    procedure_code=procedure[1],
                    modifiers=tuple(m for m in procedure[2:] if m),
                    charge=Decimal(seg.el(2)),
                    paid=Decimal(seg.el(3) or "0"),
                    units=Decimal(seg.el(5) or "1"),
                )
                claim.lines.append(line)
            case "REF" if line is not None and seg.el(1) == "6R":
                line.line_control_number = seg.el(2)
            case "LQ" if line is not None and seg.el(1) == "HE":
                line.remark_codes.append(seg.el(2))
            case _:
                pass

    if payment_date is None or payer is None or not trace_number:
        raise X12Error("835 is missing BPR16, TRN02 or the N1*PR payer")
    return Remittance(
        trace_number=trace_number,
        payer=payer,
        payment_date=payment_date,
        claims=tuple(c.build() for c in claims),
    )
