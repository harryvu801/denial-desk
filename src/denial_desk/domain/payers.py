"""Payer filing rules and deadline arithmetic.

Deadlines are computed here, in code, from dates and a rule table. A model is never asked
to do this arithmetic — a missed filing deadline is unrecoverable. See ADR-010.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from pydantic import BaseModel, model_validator


class FilingLimit(BaseModel, frozen=True):
    """A limit expressed the way the source states it: in days or in calendar months."""

    days: int | None = None
    months: int | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> FilingLimit:
        if (self.days is None) == (self.months is None):
            raise ValueError("a filing limit needs exactly one of days or months")
        return self

    def deadline_from(self, start: date) -> date:
        if self.days is not None:
            return start + timedelta(days=self.days)
        assert self.months is not None
        month_index = start.month - 1 + self.months
        year, month = start.year + month_index // 12, month_index % 12 + 1
        # Clamp to month end: six months after Aug 31 is Feb 28/29, not an invalid date.
        day = min(start.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)


class PayerRules(BaseModel, frozen=True):
    name: str
    initial_filing_limit: FilingLimit
    correction_limit: FilingLimit
    verified: bool
    citations: tuple[str, ...]

    def initial_deadline(self, service_date: date) -> date:
        return self.initial_filing_limit.deadline_from(service_date)

    def correction_deadline(self, service_date: date) -> date:
        return self.correction_limit.deadline_from(service_date)
