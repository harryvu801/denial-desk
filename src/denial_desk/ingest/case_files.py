"""Synthetic case files with a planted correct action. See ADR-029.

For each denied line the generator builds the evidence a biller would pull, and plants in it
the fact that decides the action — an authorization extension on file, a retroactive
eligibility span, a care note documenting need. The expected action is recorded in the
labels; the case file itself never states it.

Each case file uses its own RNG seeded from (seed, line control number), not the claim
generator's RNG. Adding or changing case-file logic therefore never shifts the claims, and a
given line's case file does not depend on how many claims were generated.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from denial_desk.domain.case_file import Authorization, CaseFile, EligibilitySpan, Visit
from denial_desk.domain.models import ResolutionPath

PROGRAM = "Medicaid HCBS waiver"

DISTRACTORS = (
    "Family asked to move Tuesday visits to the afternoon starting next month.",
    "Caregiver completed annual infection-control training last week.",
    "Member's daughter remains the emergency contact; phone number unchanged.",
    "Incontinence supplies were delivered on schedule.",
    "Member enjoyed the community center outing on Friday.",
    "Quarterly home safety check found no new hazards.",
)

# Root causes the rules lane settles: the generator's own view of the right action, written
# independently of the playbook (ADR-027).
RULE_LANE_ACTIONS: dict[str, ResolutionPath] = {
    "missing_prior_auth": ResolutionPath.CORRECTED_CLAIM,
    "timely_filing": ResolutionPath.WRITE_OFF,
    "duplicate_submission": ResolutionPath.NO_ACTION,
    "missing_rendering_npi": ResolutionPath.CORRECTED_CLAIM,
    "invalid_procedure_code": ResolutionPath.CORRECTED_CLAIM,
    "missing_modifier": ResolutionPath.CORRECTED_CLAIM,
    "other_insurance_primary": ResolutionPath.CORRECTED_CLAIM,
    "member_id_mismatch": ResolutionPath.CORRECTED_CLAIM,
    "frequency_limit": ResolutionPath.WRITE_OFF,
}


@dataclass(frozen=True)
class DeniedLineFacts:
    """What the case-file builder needs to know about a denied line."""

    patient_control_number: str
    line_control_number: str
    member_id: str
    root_cause: str
    procedure_code: str
    units: int
    authorized_units: int
    service_date: date
    adjudication_date: date
    prior_auth_number: str | None
    other_procedure_code: str


@dataclass(frozen=True)
class Expected:
    action: ResolutionPath
    variant: str
    suggestion: str | None = None  # recorded for reviewers, never scored


def _clock(minutes_after_midnight: int) -> time:
    return (datetime(2000, 1, 1) + timedelta(minutes=minutes_after_midnight)).time()


def _visit(day: date, start_min: int, units: int, caregiver: str, procedure: str) -> Visit:
    # Cap at 23:59 so long synthetic visits stay within one day.
    end_min = min(start_min + units * 15, 23 * 60 + 59)
    return Visit(
        service_date=day,
        start=_clock(start_min),
        end=_clock(end_min),
        caregiver_id=caregiver,
        procedure_code=procedure,
    )


def build_case_file(seed: int, f: DeniedLineFacts) -> tuple[CaseFile, Expected]:
    rng = random.Random(f"{seed}:casefile:{f.line_control_number}")
    dos = f.service_date
    caregiver = f"CG{rng.randrange(1000, 9999)}"
    auth_number = f.prior_auth_number or f"PA{rng.randrange(10**6, 10**7)}"
    period_start, period_end = date(dos.year, 1, 1), date(dos.year, 12, 31)

    authorizations = [
        Authorization(
            auth_number=auth_number,
            procedure_code=f.procedure_code,
            units=max(f.authorized_units, f.units),
            start=period_start,
            end=period_end,
        )
    ]
    eligibility = [EligibilitySpan(member_id=f.member_id, program=PROGRAM, start=date(2025, 7, 1))]
    visits = [_visit(dos, 9 * 60, f.units, caregiver, f.procedure_code)]
    sentences = rng.sample(DISTRACTORS, k=rng.randint(1, 2))
    variant_a = rng.random() < 0.5

    match f.root_cause:
        case "units_exceed_auth":
            authorizations = [authorizations[0].model_copy(update={"units": f.authorized_units})]
            if variant_a:
                extension = f"PA{rng.randrange(10**6, 10**7)}"
                authorizations.append(
                    Authorization(
                        auth_number=extension,
                        procedure_code=f.procedure_code,
                        units=f.units - f.authorized_units,
                        start=dos - timedelta(days=rng.randint(3, 10)),
                        end=period_end,
                        note="Extension approved by case manager after reassessment.",
                    )
                )
                sentences.append(
                    "Reassessment found increased need; case manager approved more hours."
                )
                expected = Expected(ResolutionPath.CORRECTED_CLAIM, "extension_on_file")
            else:
                sentences.append(
                    "Caregiver stayed past the scheduled hours because the member's son was late"
                    " returning home. No additional hours were requested."
                )
                expected = Expected(ResolutionPath.WRITE_OFF, "no_extension")

        case "coverage_terminated":
            ended = dos - timedelta(days=rng.randint(5, 20))
            eligibility = [eligibility[0].model_copy(update={"end": ended})]
            if variant_a:
                eligibility.append(
                    EligibilitySpan(
                        member_id=f.member_id,
                        program=PROGRAM,
                        start=ended + timedelta(days=1),
                        note=(
                            "Retroactive reinstatement after redetermination; entered"
                            f" {f.adjudication_date + timedelta(days=rng.randint(3, 15))}."
                        ),
                    )
                )
                # Per the author: suggest a rebill, assert nothing. A human decides.
                expected = Expected(ResolutionPath.NEEDS_HUMAN, "retro_reinstated", "rebill")
            else:
                sentences.append("Member moved out of state; services ended with this visit.")
                expected = Expected(ResolutionPath.WRITE_OFF, "no_coverage")

        case "medical_necessity":
            if variant_a:
                order = dos - timedelta(days=rng.randint(30, 90))
                sentences.append(
                    "Member needs hands-on help with bathing, dressing and transfers."
                    f" Physician order dated {order} is on file and the service is on the"
                    " current care plan."
                )
                expected = Expected(ResolutionPath.APPEAL, "need_documented")
            else:
                sentences.append(
                    "Member is independent with bathing and dressing. This service is not on"
                    " the current care plan."
                )
                expected = Expected(ResolutionPath.WRITE_OFF, "need_not_supported")

        case "bundled_service":
            if variant_a:
                other_start = 9 * 60 + f.units * 15 + 60  # an hour after the first visit ends
                visits.append(
                    _visit(dos, other_start, 4, f"CG{rng.randrange(1000, 9999)}",
                           f.other_procedure_code)
                )  # fmt: skip
                expected = Expected(ResolutionPath.APPEAL, "distinct_visits")
            else:
                visits.append(_visit(dos, 9 * 60 + 30, 4, caregiver, f.other_procedure_code))
                expected = Expected(ResolutionPath.WRITE_OFF, "overlapping_visits")

        case "missing_information_unspecified":
            if variant_a:
                new_id = f"{f.member_id[:2]}{rng.randrange(10**8, 10**9)}"
                changed = dos - timedelta(days=rng.randint(5, 30))
                eligibility = [
                    eligibility[0].model_copy(update={"end": changed - timedelta(days=1)}),
                    EligibilitySpan(
                        member_id=new_id,
                        program=PROGRAM,
                        start=changed,
                        note="Member ID reissued after a records merge.",
                    ),
                ]
                sentences.append(f"State reissued the member's ID card effective {changed}.")
                expected = Expected(ResolutionPath.CORRECTED_CLAIM, "member_id_changed")
            else:
                expected = Expected(ResolutionPath.NEEDS_HUMAN, "unexplained")

        case cause if cause in RULE_LANE_ACTIONS:
            expected = Expected(RULE_LANE_ACTIONS[cause], "rules_lane")

        case cause:
            raise ValueError(f"no case-file builder for root cause {cause!r}")

    rng.shuffle(sentences)
    return (
        CaseFile(
            patient_control_number=f.patient_control_number,
            line_control_number=f.line_control_number,
            authorizations=tuple(authorizations),
            eligibility=tuple(eligibility),
            visits=tuple(visits),
            care_note=" ".join(sentences),
        ),
        expected,
    )
