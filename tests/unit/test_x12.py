from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from denial_desk.domain.models import GroupCode, Lane, Payer, ResolutionPath
from denial_desk.ingest.join import join
from denial_desk.ingest.x12.parser_835 import parse_835, parse_cas
from denial_desk.ingest.x12.parser_837p import parse_837p
from denial_desk.ingest.x12.segments import Delimiters, Segment, X12Error, tokenize
from denial_desk.triage.rules import triage


def test_delimiters_are_read_from_isa(sample_835_raw: str) -> None:
    assert Delimiters.from_isa(sample_835_raw) == Delimiters(
        element="*", composite=":", segment="~"
    )


def test_non_isa_input_is_rejected() -> None:
    with pytest.raises(X12Error):
        tokenize("GS*HP*X~")


def test_segment_access_is_one_based_and_tolerates_missing_trailing_elements() -> None:
    seg = Segment(tag="CLP", elements=("PCN-A", "1", "204.00"))
    assert seg.el(1) == "PCN-A"
    assert seg.el(9) == ""
    with pytest.raises(IndexError):
        seg.el(0)


def test_cas_explodes_multiple_triplets() -> None:
    seg = Segment(tag="CAS", elements=("CO", "4", "80.00", "", "45", "4.00"))
    adjustments = parse_cas(seg)
    assert [(a.reason_code, a.amount) for a in adjustments] == [
        ("4", Decimal("80.00")),
        ("45", Decimal("4.00")),
    ]
    assert all(a.group_code is GroupCode.CONTRACTUAL for a in adjustments)


def test_cas_rejects_unknown_group() -> None:
    with pytest.raises(X12Error):
        parse_cas(Segment(tag="CAS", elements=("XX", "4", "1.00")))


def test_parse_835(sample_835_raw: str) -> None:
    remit = parse_835(sample_835_raw)
    assert remit.trace_number == "UTTRACE0001"
    assert remit.payer is Payer.UT_MEDICAID
    assert remit.payment_date == date(2026, 2, 1)

    claim_a, claim_b = remit.claims
    assert claim_a.payer_claim_control_number == "UTICN0001"
    line = claim_a.lines[1]
    assert line.line_control_number == "PCN-A-2"
    assert line.remark_codes == ("M51",)
    assert [a.reason_code for a in line.adjustments] == ["4", "45"]

    # CAS before the first SVC is claim-level; MOA remark codes are claim-level too.
    assert [a.reason_code for a in claim_b.claim_adjustments] == ["23"]
    assert claim_b.claim_remark_codes == ("MA130",)
    assert [a.reason_code for a in claim_b.lines[0].adjustments] == ["16"]


def test_unbalanced_835_line_fails(sample_835_raw: str) -> None:
    broken = sample_835_raw.replace("CAS*CO*45*20.00~", "CAS*CO*45*19.00~")
    with pytest.raises(ValidationError, match="adjustments"):
        parse_835(broken)


def test_parse_837p(sample_837_raw: str) -> None:
    claim_a, claim_b = parse_837p(sample_837_raw)
    assert claim_a.patient_control_number == "PCN-A"
    assert claim_a.submission_date == date(2026, 1, 10)
    assert claim_a.prior_auth_number is None
    assert [ln.procedure_code for ln in claim_a.lines] == ["T1019", "S5130"]
    assert claim_a.lines[0].modifiers == ("U1",)
    assert claim_a.lines[1].modifiers == ()
    assert claim_b.frequency_code == "7"
    assert claim_b.prior_auth_number == "PA555"


def test_join_emits_only_denied_lines(sample_837_raw: str, sample_835_raw: str) -> None:
    denials, issues = join(parse_837p(sample_837_raw), [parse_835(sample_835_raw)])
    assert issues == []
    by_line = {d.line_control_number: d for d in denials}
    assert set(by_line) == {"PCN-A-2", "PCN-B-1"}  # PCN-A-1 was paid with only CO-45

    a2 = by_line["PCN-A-2"]
    assert a2.primary_carc == "4"
    assert a2.denied_amount == Decimal("80.00")  # CO-45 is not counted as denied money
    assert by_line["PCN-B-1"].remark_codes == ("MA130",)


def test_join_reports_unmatched_lines(sample_835_raw: str) -> None:
    denials, issues = join([], [parse_835(sample_835_raw)])
    assert denials == []
    assert {i.line_control_number for i in issues} == {"PCN-A-2", "PCN-B-1"}


def test_expired_correction_window_goes_to_a_human(
    sample_837_raw: str, sample_835_raw: str
) -> None:
    denials, _ = join(parse_837p(sample_837_raw), [parse_835(sample_835_raw)])
    modifier_denial = next(d for d in denials if d.line_control_number == "PCN-A-2")

    # Utah's correction window is 365 days from the 2026-01-06 date of service.
    in_window = triage(modifier_denial, as_of=date(2027, 1, 6))
    assert in_window.path is ResolutionPath.CORRECTED_CLAIM
    assert in_window.filing_deadline == date(2027, 1, 6)

    expired = triage(modifier_denial, as_of=date(2027, 1, 7))
    assert (expired.lane, expired.path) == (Lane.HUMAN, ResolutionPath.NEEDS_HUMAN)
    assert expired.rule_id == "modifier-missing-or-invalid"
    assert "closed on 2027-01-06" in expired.rationale
