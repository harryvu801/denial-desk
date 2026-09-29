"""CARC/RARC code metadata, resolved as of a date.

The code lists are versioned by X12, and a denial must be interpreted against the list in
force when it was adjudicated. This module is pure: it builds a table from already-loaded
rows. Reading the committed data file happens in `denial_desk.reference`. See ADR-004.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from pydantic import BaseModel


class CodeDefinition(BaseModel, frozen=True):
    code: str
    description: str
    effective_start: date
    effective_end: date | None = None

    def in_force(self, as_of: date) -> bool:
        return self.effective_start <= as_of and (
            self.effective_end is None or as_of <= self.effective_end
        )


class CodeTable:
    """Lookup of one code list (CARC or RARC) by code and as-of date."""

    def __init__(self, definitions: Iterable[CodeDefinition]) -> None:
        self._by_code: dict[str, list[CodeDefinition]] = {}
        for d in definitions:
            self._by_code.setdefault(d.code, []).append(d)

    def lookup(self, code: str, as_of: date) -> CodeDefinition | None:
        """The definition in force on `as_of`, or None if the code was not valid then."""
        for d in self._by_code.get(code, []):
            if d.in_force(as_of):
                return d
        return None

    def describe(self, code: str, as_of: date) -> str:
        d = self.lookup(code, as_of)
        return d.description if d else f"Unknown or inactive code {code} as of {as_of}"
