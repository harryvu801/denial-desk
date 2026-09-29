"""Join submitted claims (837P) to remittances (835) and emit one DenialRecord per denied line.

Lines are matched on (patient control number, line control number): CLP01 echoes CLM01,
and the 835's REF*6R echoes the 837's REF*6R. See ADR-028. A line that cannot be matched
is reported as an issue for a human, never guessed at.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from denial_desk.domain.models import DenialRecord, Remittance, SubmittedClaim, SubmittedLine

REVERSAL_STATUS = "22"


@dataclass(frozen=True)
class JoinIssue:
    patient_control_number: str
    line_control_number: str | None
    reason: str


def join(
    claims: Iterable[SubmittedClaim], remittances: Iterable[Remittance]
) -> tuple[list[DenialRecord], list[JoinIssue]]:
    submitted: dict[tuple[str, str], tuple[SubmittedClaim, SubmittedLine]] = {
        (c.patient_control_number, ln.line_control_number): (c, ln)
        for c in claims
        for ln in c.lines
    }
    denials: list[DenialRecord] = []
    issues: list[JoinIssue] = []

    for remit in remittances:
        for adj_claim in remit.claims:
            pcn = adj_claim.patient_control_number
            if adj_claim.status_code == REVERSAL_STATUS:
                # A reversal undoes an earlier payment; it is not itself a denial. Handling
                # reversal + re-adjudication pairs is out of MVP scope and listed in the README.
                issues.append(JoinIssue(pcn, None, "reversal (CLP02=22) skipped"))
                continue
            for adj_line in adj_claim.lines:
                if not any(a.is_denial for a in adj_line.adjustments):
                    continue
                lcn = adj_line.line_control_number
                match = submitted.get((pcn, lcn)) if lcn else None
                if match is None:
                    issues.append(JoinIssue(pcn, lcn, "no matching 837 line (REF*6R)"))
                    continue
                claim, line = match
                denials.append(
                    DenialRecord(
                        patient_control_number=pcn,
                        line_control_number=line.line_control_number,
                        payer=remit.payer,
                        payer_claim_control_number=adj_claim.payer_claim_control_number,
                        submitted=line,
                        adjudicated=adj_line,
                        claim_adjustments=adj_claim.claim_adjustments,
                        claim_remark_codes=adj_claim.claim_remark_codes,
                        prior_auth_number=claim.prior_auth_number,
                        submission_date=claim.submission_date,
                        adjudication_date=remit.payment_date,
                    )
                )
    return denials, issues
