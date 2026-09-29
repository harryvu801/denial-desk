"""Committed reference data: CARC/RARC code lists and payer filing rules.

This is the I/O half of `domain.codes` and `domain.payers` — the domain package stays pure and
receives already-parsed rows. Loaded once and cached, since the files never change at runtime.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from denial_desk.domain.codes import CodeDefinition, CodeTable
from denial_desk.domain.payers import PayerRules

_DIR = Path(__file__).parent


def _read(name: str) -> Any:
    return json.loads((_DIR / name).read_text())


@cache
def carc_table() -> CodeTable:
    return CodeTable(CodeDefinition.model_validate(row) for row in _read("carc.json")["codes"])


@cache
def rarc_table() -> CodeTable:
    return CodeTable(CodeDefinition.model_validate(row) for row in _read("rarc.json")["codes"])


@cache
def payer_rules() -> dict[str, PayerRules]:
    return {
        code: PayerRules.model_validate(row) for code, row in _read("payers.json")["payers"].items()
    }
