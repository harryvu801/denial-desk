"""Core domain objects.

The normalized denial record is the spine of the system: X12 parsing produces it, triage
consumes it, and evals are labeled against it.

Submitted data (837P) and adjudicated data (835) are deliberately separate types. The payer
can re-code a line, and the billed charge on the claim is not the same fact as the charge
the payer says it received. Mixing them into one object hides exactly those discrepancies.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class Payer(StrEnum):
    """The four state Medicaid payers modeled in the synthetic set. See ADR-005."""

    UT_MEDICAID = "UT"
    AZ_MEDICAID = "AZ"
    NV_MEDICAID = "NV"
    ID_MEDICAID = "ID"


class GroupCode(StrEnum):
    """CAS01 claim adjustment group code."""

    CONTRACTUAL = "CO"
    OTHER = "OA"
    PAYER_INITIATED = "PI"
    PATIENT_RESPONSIBILITY = "PR"
    CORRECTION_REVERSAL = "CR"


class ResolutionPath(StrEnum):
    CORRECTED_CLAIM = "corrected_claim"
    APPEAL = "appeal"
    WRITE_OFF = "write_off"
    NO_ACTION = "no_action"  # e.g. a duplicate: the balance lives on the original claim
    NEEDS_HUMAN = "needs_human"


class RootCause(StrEnum):
    """Why a line was denied, at the level a billing team acts on. Several share a CARC
    (CARC 16 covers three), which is what makes classification more than a lookup. ADR-027."""

    MISSING_PRIOR_AUTH = "missing_prior_auth"
    TIMELY_FILING = "timely_filing"
    DUPLICATE_SUBMISSION = "duplicate_submission"
    MISSING_RENDERING_NPI = "missing_rendering_npi"
    MISSING_MODIFIER = "missing_modifier"
    INVALID_PROCEDURE_CODE = "invalid_procedure_code"
    OTHER_INSURANCE_PRIMARY = "other_insurance_primary"
    COVERAGE_TERMINATED = "coverage_terminated"
    UNITS_EXCEED_AUTH = "units_exceed_auth"
    MEMBER_ID_MISMATCH = "member_id_mismatch"
    FREQUENCY_LIMIT = "frequency_limit"
    MEDICAL_NECESSITY = "medical_necessity"
    BUNDLED_SERVICE = "bundled_service"
    MISSING_INFORMATION_UNSPECIFIED = "missing_information_unspecified"
    UNKNOWN = "unknown"


class Lane(StrEnum):
    """Which lane proposed this resolution. Recorded on every record so the share of
    denials that never touched a model is a measured number. See ADR-006, ADR-026."""

    DETERMINISTIC = "deterministic"
    MODEL = "model"
    HUMAN = "human"


# CARCs that explain a payment reduction without being a denial. CO-45 (charge exceeds fee
# schedule) appears on nearly every paid line; counting it would make every line a denial.
NON_DENIAL_CARCS: frozenset[str] = frozenset({"45"})


class Adjustment(BaseModel, frozen=True):
    """One reason/amount pair from a CAS segment. A single CAS segment carries up to six
    of these; the parser explodes them."""

    group_code: GroupCode
    reason_code: str = Field(min_length=1, max_length=5, description="CARC, e.g. '197'")
    amount: Decimal
    quantity: Decimal | None = None

    @property
    def is_denial(self) -> bool:
        return (
            self.group_code is not GroupCode.PATIENT_RESPONSIBILITY
            and self.reason_code not in NON_DENIAL_CARCS
            and self.amount > 0
        )


class SubmittedLine(BaseModel, frozen=True):
    """837P loop 2400 — one service line as billed."""

    line_number: int = Field(ge=1, description="LX01")
    line_control_number: str = Field(min_length=1, description="REF*6R; echoed back in the 835")
    procedure_code: str = Field(min_length=5, max_length=5, description="SV101-2, CPT/HCPCS")
    modifiers: tuple[str, ...] = ()
    charge: Decimal = Field(ge=0)
    units: Decimal = Field(gt=0)
    service_date: date


class SubmittedClaim(BaseModel, frozen=True):
    """837P loop 2300 plus the subscriber and payer it belongs to."""

    patient_control_number: str = Field(min_length=1, description="CLM01")
    payer: Payer
    member_id: str = Field(description="NM109 in loop 2010BA")
    total_charge: Decimal = Field(ge=0)
    submission_date: date = Field(description="BHT04")
    frequency_code: str = Field(default="1", description="CLM05-3: 1 original, 7 replacement")
    prior_auth_number: str | None = Field(default=None, description="REF*G1")
    lines: tuple[SubmittedLine, ...]

    @model_validator(mode="after")
    def _lines_sum_to_total(self) -> SubmittedClaim:
        if sum((ln.charge for ln in self.lines), Decimal(0)) != self.total_charge:
            raise ValueError("CLM02 total charge does not equal the sum of SV102 line charges")
        return self


class AdjudicatedLine(BaseModel, frozen=True):
    """835 loop 2110 — what the payer did with one service line."""

    line_control_number: str | None = Field(default=None, description="REF*6R")
    procedure_code: str
    modifiers: tuple[str, ...] = ()
    charge: Decimal
    paid: Decimal
    units: Decimal = Decimal(1)
    adjustments: tuple[Adjustment, ...] = ()
    remark_codes: tuple[str, ...] = Field(default=(), description="LQ*HE RARCs")

    @model_validator(mode="after")
    def _balances(self) -> AdjudicatedLine:
        # Charge minus paid must equal the sum of adjustments. An 835 line that does not
        # balance is malformed, and a denial built from it would be built on wrong numbers.
        adjusted = sum((a.amount for a in self.adjustments), Decimal(0))
        if self.charge - self.paid != adjusted:
            raise ValueError(
                f"line {self.line_control_number}: charge {self.charge} - paid {self.paid}"
                f" != adjustments {adjusted}"
            )
        return self


class AdjudicatedClaim(BaseModel, frozen=True):
    """835 loop 2100 — one CLP and its service lines."""

    patient_control_number: str = Field(description="CLP01, echoes 837 CLM01")
    status_code: str = Field(description="CLP02: 1 primary, 4 denied, 22 reversal, ...")
    charge: Decimal
    paid: Decimal
    payer_claim_control_number: str = Field(description="CLP07, the payer's ICN")
    claim_adjustments: tuple[Adjustment, ...] = ()
    claim_remark_codes: tuple[str, ...] = Field(default=(), description="MOA RARCs")
    lines: tuple[AdjudicatedLine, ...] = ()


class Remittance(BaseModel, frozen=True):
    """One 835 transaction."""

    trace_number: str = Field(min_length=1, description="TRN02 — check or EFT trace")
    payer: Payer
    payment_date: date = Field(description="BPR16")
    claims: tuple[AdjudicatedClaim, ...]


class DenialRecord(BaseModel, frozen=True):
    """One denied service line, normalized from an 837P/835 pair.

    Identity is (patient_control_number, line_control_number) — see ADR-028.
    """

    patient_control_number: str
    line_control_number: str
    payer: Payer
    payer_claim_control_number: str
    submitted: SubmittedLine
    adjudicated: AdjudicatedLine
    claim_adjustments: tuple[Adjustment, ...] = ()
    claim_remark_codes: tuple[str, ...] = ()
    prior_auth_number: str | None = None
    submission_date: date
    adjudication_date: date

    @property
    def denial_adjustments(self) -> tuple[Adjustment, ...]:
        return tuple(a for a in self.adjudicated.adjustments if a.is_denial)

    @property
    def denied_amount(self) -> Decimal:
        """Dollars at risk: the non-contractual, non-patient adjustments on this line."""
        return sum((a.amount for a in self.denial_adjustments), Decimal(0))

    @property
    def primary_carc(self) -> str:
        """The CARC carrying the most money. Ties break on CAS order."""
        return max(self.denial_adjustments, key=lambda a: a.amount).reason_code

    @property
    def remark_codes(self) -> tuple[str, ...]:
        return self.adjudicated.remark_codes + self.claim_remark_codes

    @model_validator(mode="after")
    def _is_actually_denied(self) -> DenialRecord:
        if not any(a.is_denial for a in self.adjudicated.adjustments):
            raise ValueError("a DenialRecord needs at least one denial adjustment")
        return self


class Evidence(BaseModel, frozen=True):
    """A single retrieved passage supporting a conclusion. Used from stage 2 on.

    Every factual assertion in a generated appeal must trace to one of these. See ADR-012.
    """

    source_id: str
    section: str
    text: str
    score: float
    provenance: str = Field(description="Where this came from; rendered into the prompt.")


class Resolution(BaseModel, frozen=True):
    """What the system proposes to do about a denial. Never auto-executed. See ADR-007."""

    patient_control_number: str
    line_control_number: str
    lane: Lane
    path: ResolutionPath
    rule_id: str | None = None
    rationale: str
    citations: tuple[str, ...] = ()
    filing_deadline: date | None = Field(
        default=None,
        description="Computed in Python, never by a model. See ADR-010.",
    )
