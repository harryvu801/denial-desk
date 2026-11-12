from datetime import date

import pytest
from pydantic import ValidationError

from denial_desk.domain.codes import CodeDefinition, CodeTable
from denial_desk.domain.payers import FilingLimit
from denial_desk.reference import carc_table, payer_rules


def test_month_limits_clamp_to_month_end() -> None:
    assert FilingLimit(months=6).deadline_from(date(2025, 8, 31)) == date(2026, 2, 28)
    assert FilingLimit(months=12).deadline_from(date(2026, 1, 15)) == date(2027, 1, 15)


def test_day_limits() -> None:
    assert FilingLimit(days=180).deadline_from(date(2026, 1, 1)) == date(2026, 6, 30)


def test_filing_limit_needs_exactly_one_unit() -> None:
    with pytest.raises(ValidationError):
        FilingLimit(days=1, months=1)
    with pytest.raises(ValidationError):
        FilingLimit()


def test_code_lookup_respects_effective_dates() -> None:
    table = CodeTable(
        [CodeDefinition(code="X1", description="old", effective_start=date(2020, 1, 1),
                        effective_end=date(2023, 12, 31))]
    )  # fmt: skip
    assert table.describe("X1", date(2022, 6, 1)) == "old"
    assert table.lookup("X1", date(2024, 6, 1)) is None


def test_reference_data_loads() -> None:
    assert "filing" in carc_table().describe("29", date(2026, 1, 1))
    assert set(payer_rules()) == {"UT", "AZ", "NV", "ID"}
    assert payer_rules()["AZ"].initial_deadline(date(2026, 1, 10)) == date(2026, 7, 10)


def test_appeal_deadline_is_the_latest_clock_or_unknown() -> None:
    rules = payer_rules()
    service, remit = date(2026, 1, 10), date(2026, 3, 1)
    # AHCCCS: 12 months from service or 60 days from the denial, whichever is later.
    assert rules["AZ"].appeal_deadline(service, remit) == date(2027, 1, 10)
    assert rules["AZ"].appeal_deadline(date(2025, 2, 1), remit) == date(2026, 4, 30)
    # Nevada and Utah: 30 days from the remittance.
    assert rules["NV"].appeal_deadline(service, remit) == date(2026, 3, 31)
    assert rules["UT"].appeal_deadline(service, remit) == date(2026, 3, 31)
    # Idaho: not researched yet, so no number is invented.
    assert rules["ID"].appeal_deadline(service, remit) is None
    assert not rules["ID"].appeal_verified and all(r.verified for r in rules.values())
