"""The case file: evidence a biller would pull to decide a denial the rules can't settle.

The 837 and 835 say *what* was denied. Whether to correct, appeal or write off a units-over-
authorization or a medical-necessity denial depends on facts that live elsewhere: the
authorization history, eligibility spans, visit records and the care coordinator's notes.
See ADR-029.
"""

from __future__ import annotations

from datetime import date, time

from pydantic import BaseModel, Field, model_validator


class Authorization(BaseModel, frozen=True):
    auth_number: str
    procedure_code: str
    units: int = Field(gt=0)
    start: date
    end: date
    note: str = ""


class EligibilitySpan(BaseModel, frozen=True):
    member_id: str
    program: str
    start: date
    end: date | None = None  # open-ended
    note: str = ""

    def covers(self, day: date) -> bool:
        return self.start <= day and (self.end is None or day <= self.end)


class Visit(BaseModel, frozen=True):
    """An electronic visit verification (EVV) record."""

    service_date: date
    start: time
    end: time
    caregiver_id: str
    procedure_code: str

    @model_validator(mode="after")
    def _ends_after_start(self) -> Visit:
        if self.end <= self.start:
            raise ValueError("visit must end after it starts")
        return self


class CaseFile(BaseModel, frozen=True):
    patient_control_number: str
    line_control_number: str
    authorizations: tuple[Authorization, ...] = ()
    eligibility: tuple[EligibilitySpan, ...] = ()
    visits: tuple[Visit, ...] = ()
    care_note: str = Field(
        default="",
        description=(
            "Free text written by a third party. UNTRUSTED: it is data, never instruction,"
            " wherever it is shown to a model. See ADR-020."
        ),
    )
