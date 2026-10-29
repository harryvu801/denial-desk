"""Synthetic 837P/835 generator.

Deterministic given a seed, so a dataset is reproducible from (seed, GENERATOR_VERSION)
rather than from a committed blob. See ADR-005.

Two rules keep the ground truth honest:
  - This module never imports from `triage/`. The denial scenarios below are written
    independently of the playbook, so the rules lane is measured against data it was not
    shaped from. (The distribution is still hand-declared — see ADR-027 and the README.)
  - Labels are root causes, not CARCs. Several root causes share a CARC (16 has three), so
    "classify the denial" cannot be solved by reading the CARC alone.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from denial_desk.domain.models import GroupCode, Payer
from denial_desk.ingest.case_files import DeniedLineFacts, Expected, build_case_file
from denial_desk.reference import payer_rules

GENERATOR_VERSION = "0.2.0"  # 0.2.0: case files + expected actions (ADR-029)
START_DATE = date(2026, 1, 5)  # fixed, never date.today(): determinism
PROVIDER_NPI = "1234567893"
PAYER_NAMES = {
    Payer.UT_MEDICAID: "UTAH MEDICAID",
    Payer.AZ_MEDICAID: "AHCCCS",
    Payer.NV_MEDICAID: "NEVADA MEDICAID",
    Payer.ID_MEDICAID: "IDAHO MEDICAID",
}

# Home and community based services codes, billed in 15-minute units. Rates are invented.
PROCEDURES: dict[str, Decimal] = {
    "T1019": Decimal("6.25"),  # personal care services, per 15 min
    "S5125": Decimal("5.80"),  # attendant care services, per 15 min
    "S5130": Decimal("5.10"),  # homemaker services, per 15 min
    "T1005": Decimal("7.40"),  # respite care services, per 15 min
    "G0156": Decimal("9.15"),  # home health aide, per 15 min
}
REQUIRED_MODIFIER = "U1"  # synthetic stand-in for a state-required program modifier

FIRST = ["ALEX", "JORDAN", "SAM", "RILEY", "CASEY", "MORGAN", "TAYLOR", "AVERY", "QUINN"]
LAST = ["TESTPATIENT", "SYNTHETIC", "EXAMPLE", "SAMPLE", "FICTIONAL", "DEMO"]


@dataclass(frozen=True)
class Scenario:
    """One way a claim gets denied, with the evidence for it planted in the claim."""

    root_cause: str
    carc: str
    weight: int
    scope: str  # "claim": every line denied; "line": one line denied, the rest paid
    group: GroupCode = GroupCode.CONTRACTUAL
    rarcs: tuple[str, ...] = ()
    description: str = ""


# Declared, skewed distribution (ADR-005). Weights are relative, out of 100 denials. They
# are a modeling assumption, not measured data — say so wherever the numbers are reported.
SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "missing_prior_auth",
        "197",
        18,
        "claim",
        rarcs=("N54",),
        description="No REF*G1 authorization number on the claim.",
    ),
    Scenario(
        "timely_filing",
        "29",
        14,
        "claim",
        description="Submitted after the payer's initial filing limit.",
    ),
    Scenario(
        "duplicate_submission",
        "18",
        12,
        "claim",
        description="Same service already adjudicated on an earlier claim.",
    ),
    Scenario(
        "missing_rendering_npi",
        "16",
        10,
        "claim",
        rarcs=("N290",),
        description="Rendering provider NM1*82 omitted.",
    ),
    Scenario(
        "missing_modifier",
        "4",
        8,
        "line",
        description=f"Required {REQUIRED_MODIFIER} modifier missing on the line.",
    ),
    Scenario(
        "invalid_procedure_code",
        "16",
        6,
        "line",
        rarcs=("M51",),
        description="Procedure code invalid for this program.",
    ),
    Scenario(
        "other_insurance_primary",
        "22",
        6,
        "claim",
        description="Member has other coverage that must be billed first.",
    ),
    Scenario(
        "coverage_terminated",
        "27",
        5,
        "claim",
        rarcs=("N30",),
        description="Date of service after the member's eligibility ended.",
    ),
    Scenario(
        "units_exceed_auth",
        "198",
        5,
        "line",
        rarcs=("N362",),
        description="Units billed exceed the authorized units.",
    ),
    Scenario(
        "member_id_mismatch",
        "140",
        4,
        "claim",
        description="Member ID and name do not match payer records.",
    ),
    Scenario(
        "frequency_limit",
        "119",
        4,
        "line",
        rarcs=("M86",),
        description="Benefit maximum for the period already reached.",
    ),
    Scenario(
        "medical_necessity",
        "50",
        3,
        "line",
        description="Payer judged the service not medically necessary.",
    ),
    Scenario(
        "bundled_service", "97", 3, "line", description="Included in another service already paid."
    ),
    Scenario(
        "missing_information_unspecified",
        "16",
        2,
        "claim",
        description="Missing information, no remark code given.",
    ),
)
DENIAL_RATE = 0.35  # share of claims that carry a denial scenario


@dataclass
class _Line:
    line_number: int
    line_control_number: str
    procedure_code: str
    modifiers: tuple[str, ...]
    units: int
    charge: Decimal
    service_date: date
    # adjudication
    paid: Decimal = Decimal(0)
    cas: list[tuple[GroupCode, str, Decimal]] = field(default_factory=list)
    rarcs: tuple[str, ...] = ()
    root_cause: str | None = None
    carc: str | None = None


@dataclass
class _Claim:
    pcn: str
    payer: Payer
    member_id: str
    first: str
    last: str
    submission_date: date
    prior_auth: str | None
    rendering_npi: str | None
    lines: list[_Line]
    icn: str = ""
    payment_date: date = START_DATE

    @property
    def total_charge(self) -> Decimal:
        return sum((ln.charge for ln in self.lines), Decimal(0))

    @property
    def total_paid(self) -> Decimal:
        return sum((ln.paid for ln in self.lines), Decimal(0))


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _make_claim(rng: random.Random, index: int) -> tuple[_Claim, Scenario | None]:
    payer = rng.choice(list(Payer))
    pcn = f"PCN{index:06d}"
    first_dos = START_DATE + timedelta(days=rng.randrange(0, 60))
    lines: list[_Line] = []
    for n in range(1, rng.randint(1, 3) + 1):
        code = rng.choice(list(PROCEDURES))
        units = rng.choice([4, 8, 12, 16, 24, 32])
        lines.append(
            _Line(
                line_number=n,
                line_control_number=f"{pcn}-{n}",
                procedure_code=code,
                modifiers=(REQUIRED_MODIFIER,),
                units=units,
                charge=_money(PROCEDURES[code] * units * Decimal("1.20")),
                service_date=first_dos + timedelta(days=n - 1),
            )
        )
    claim = _Claim(
        pcn=pcn,
        payer=payer,
        member_id=f"{payer.value}{rng.randrange(10**8, 10**9)}",
        first=rng.choice(FIRST),
        last=rng.choice(LAST),
        submission_date=lines[-1].service_date + timedelta(days=rng.randint(3, 30)),
        prior_auth=f"PA{rng.randrange(10**6, 10**7)}",
        rendering_npi=f"1{rng.randrange(10**8, 10**9)}",
        lines=lines,
    )
    scenario = None
    if rng.random() < DENIAL_RATE:
        scenario = rng.choices(SCENARIOS, weights=[s.weight for s in SCENARIOS])[0]
    return claim, scenario


def _plant_evidence(rng: random.Random, claim: _Claim, scenario: Scenario) -> list[_Line]:
    """Mutate the claim so the 837 itself carries the evidence, then return denied lines."""
    targets = claim.lines if scenario.scope == "claim" else [rng.choice(claim.lines)]
    match scenario.root_cause:
        case "missing_prior_auth":
            claim.prior_auth = None
        case "timely_filing":
            limit = payer_rules()[claim.payer.value].initial_deadline(claim.lines[0].service_date)
            claim.submission_date = limit + timedelta(days=rng.randint(1, 60))
        case "missing_rendering_npi":
            claim.rendering_npi = None
        case "missing_modifier":
            targets[0].modifiers = ()
        case "invalid_procedure_code":
            targets[0].procedure_code = "T1099"  # not a code this program covers
        case "units_exceed_auth":
            targets[0].units *= 3
            targets[0].charge = _money(
                PROCEDURES.get(targets[0].procedure_code, Decimal(6))
                * targets[0].units
                * Decimal("1.20")
            )
        case _:
            pass  # evidence lives outside the 837 (payer history, eligibility, other coverage)
    return targets


def _adjudicate(rng: random.Random, claim: _Claim, scenario: Scenario | None) -> None:
    denied = _plant_evidence(rng, claim, scenario) if scenario else []
    for ln in claim.lines:
        if ln in denied and scenario is not None:
            ln.paid = Decimal(0)
            ln.cas = [(scenario.group, scenario.carc, ln.charge)]
            ln.rarcs = scenario.rarcs
            ln.root_cause, ln.carc = scenario.root_cause, scenario.carc
        else:
            allowed = _money(ln.charge / Decimal("1.20"))
            ln.paid = allowed
            ln.cas = [(GroupCode.CONTRACTUAL, "45", ln.charge - allowed)]
    claim.payment_date = claim.submission_date + timedelta(days=rng.randint(10, 25))


# --- X12 writing -------------------------------------------------------------------------


def _isa(control: int, when: date, receiver: str) -> str:
    fields = [
        "00", " " * 10, "00", " " * 10,
        "ZZ", "SYNTHSENDER".ljust(15), "ZZ", receiver.ljust(15),
        when.strftime("%y%m%d"), "1200", "^", "00501", f"{control:09d}", "0", "T", ":",
    ]  # fmt: skip
    return "ISA*" + "*".join(fields) + "~"


def _envelope(body: list[str], control: int, when: date, receiver: str, functional: str,
              version: str, ts: str) -> str:  # fmt: skip
    st = [f"ST*{ts}*0001*{version}" if ts == "837" else f"ST*{ts}*0001", *body]
    st.append(f"SE*{len(st) + 1}*0001")
    out = [
        _isa(control, when, receiver),
        f"GS*{functional}*SYNTHSENDER*{receiver}*{when:%Y%m%d}*1200*{control}*X*{version}",
        *st,
        f"GE*1*{control}",
        f"IEA*1*{control:09d}",
    ]
    return "\n".join(seg if seg.endswith("~") else seg + "~" for seg in out) + "\n"


def _write_837(claims: list[_Claim], control: int) -> str:
    payer, when = claims[0].payer, claims[0].submission_date
    body = [
        f"BHT*0019*00*B{control}*{when:%Y%m%d}*1200*CH",
        "NM1*41*2*SYNTHETIC BILLING SERVICE*****46*SYN0001",
        f"NM1*40*2*{PAYER_NAMES[payer]}*****46*{payer.value}",
        "HL*1**20*1",
        f"NM1*85*2*SYNTHETIC HOME CARE AGENCY*****XX*{PROVIDER_NPI}",
    ]
    for hl, c in enumerate(claims, start=2):
        body += [
            f"HL*{hl}*1*22*0",
            "SBR*P*18*******MC",
            f"NM1*IL*1*{c.last}*{c.first}****MI*{c.member_id}",
            f"NM1*PR*2*{PAYER_NAMES[payer]}*****PI*{payer.value}",
            f"CLM*{c.pcn}*{c.total_charge}***12:B:1*Y*A*Y*Y",
        ]
        if c.prior_auth:
            body.append(f"REF*G1*{c.prior_auth}")
        body.append("HI*ABK:Z741")
        if c.rendering_npi:
            body.append(f"NM1*82*1*CAREGIVER*SYNTHETIC****XX*{c.rendering_npi}")
        for ln in c.lines:
            proc = ":".join(["HC", ln.procedure_code, *ln.modifiers])
            body += [
                f"LX*{ln.line_number}",
                f"SV1*{proc}*{ln.charge}*UN*{ln.units}***1",
                f"DTP*472*D8*{ln.service_date:%Y%m%d}",
                f"REF*6R*{ln.line_control_number}",
            ]
    return _envelope(body, control, when, payer.value, "HC", "005010X222A1", "837")


def _write_835(claims: list[_Claim], control: int) -> str:
    payer, when = claims[0].payer, claims[0].payment_date
    total = sum((c.total_paid for c in claims), Decimal(0))
    body = [
        f"BPR*I*{total}*C*ACH*CCP*01*999999999*DA*123456*1512345678**01*999999999*DA*654321"
        f"*{when:%Y%m%d}",
        f"TRN*1*{payer.value}{when:%Y%m%d}{control:04d}*1512345678",
        f"N1*PR*{PAYER_NAMES[payer]}*XV*{payer.value}",
        f"N1*PE*SYNTHETIC HOME CARE AGENCY*XX*{PROVIDER_NPI}",
        "LX*1",
    ]
    for c in claims:
        status = "1" if c.total_paid > 0 else "4"
        body += [
            f"CLP*{c.pcn}*{status}*{c.total_charge}*{c.total_paid}*0*MC*{c.icn}*12*1",
            f"NM1*QC*1*{c.last}*{c.first}****MI*{c.member_id}",
        ]
        for ln in c.lines:
            proc = ":".join(["HC", ln.procedure_code, *ln.modifiers])
            body += [
                f"SVC*{proc}*{ln.charge}*{ln.paid}**{ln.units}",
                f"DTM*472*{ln.service_date:%Y%m%d}",
                *[f"CAS*{g.value}*{carc}*{amt}" for g, carc, amt in ln.cas],
                f"REF*6R*{ln.line_control_number}",
                *[f"LQ*HE*{r}" for r in ln.rarcs],
            ]
    return _envelope(body, control, when, payer.value, "HP", "005010X221A1", "835")


def _facts(claim: _Claim, line: _Line) -> DeniedLineFacts:
    assert line.root_cause is not None
    others = [p for p in PROCEDURES if p != line.procedure_code]
    return DeniedLineFacts(
        patient_control_number=claim.pcn,
        line_control_number=line.line_control_number,
        member_id=claim.member_id,
        root_cause=line.root_cause,
        procedure_code=line.procedure_code,
        units=line.units,
        # units_exceed_auth tripled the billed units; the original authorization covered a third.
        authorized_units=line.units // 3 if line.root_cause == "units_exceed_auth" else line.units,
        service_date=line.service_date,
        adjudication_date=claim.payment_date,
        prior_auth_number=claim.prior_auth,
        other_procedure_code=others[int(line.line_control_number.rsplit("-", 1)[1]) % len(others)],
    )


def generate(out_dir: Path, n_claims: int, seed: int = 42) -> dict[str, int]:
    """Write paired 837P and 835 files plus a ground-truth manifest. Returns counts.

    Files are grouped one per (payer, date): every claim in an 837 shares BHT04 as its
    submission date, and every claim in an 835 shares BPR16 as its payment date.
    """
    rng = random.Random(seed)  # one seeded instance; never the module-level `random`
    claims: list[_Claim] = []
    for i in range(1, n_claims + 1):
        claim, scenario = _make_claim(rng, i)
        claim.icn = f"{claim.payer.value}ICN{i:08d}"
        _adjudicate(rng, claim, scenario)
        claims.append(claim)

    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in [*out_dir.glob("*.837"), *out_dir.glob("*.835")]:
        stale.unlink()

    by_submission: dict[tuple[Payer, date], list[_Claim]] = defaultdict(list)
    by_payment: dict[tuple[Payer, date], list[_Claim]] = defaultdict(list)
    for c in claims:
        by_submission[(c.payer, c.submission_date)].append(c)
        by_payment[(c.payer, c.payment_date)].append(c)

    for control, ((payer, when), group) in enumerate(sorted(by_submission.items()), start=1):
        (out_dir / f"{payer.value}_{when:%Y%m%d}.837").write_text(_write_837(group, control))
    for control, ((payer, when), group) in enumerate(sorted(by_payment.items()), start=1):
        (out_dir / f"{payer.value}_{when:%Y%m%d}.835").write_text(_write_835(group, control))

    labels: list[dict[str, object]] = []
    with (out_dir / "case_files.jsonl").open("w") as case_fh:
        for c in claims:
            for ln in c.lines:
                expected: Expected | None = None
                if ln.root_cause is not None:
                    case_file, expected = build_case_file(seed, _facts(c, ln))
                    case_fh.write(case_file.model_dump_json() + "\n")
                labels.append(
                    {
                        "patient_control_number": c.pcn,
                        "line_control_number": ln.line_control_number,
                        "payer": c.payer.value,
                        "denied": ln.root_cause is not None,
                        "root_cause": ln.root_cause,
                        "carc": ln.carc,
                        "rarcs": list(ln.rarcs),
                        "expected_action": expected.action.value if expected else None,
                        "variant": expected.variant if expected else None,
                        "suggestion": expected.suggestion if expected else None,
                    }
                )
    with (out_dir / "labels.jsonl").open("w") as fh:
        fh.writelines(json.dumps(row) + "\n" for row in labels)
    (out_dir / "manifest.json").write_text(
        json.dumps(
            {
                "generator_version": GENERATOR_VERSION,
                "seed": seed,
                "n_claims": n_claims,
                "n_lines": len(labels),
                "n_denied_lines": sum(1 for r in labels if r["denied"]),
                "denial_rate": DENIAL_RATE,
                "distribution": {s.root_cause: s.weight for s in SCENARIOS},
                "note": "Synthetic data. The distribution is declared, not measured.",
            },
            indent=2,
        )
        + "\n"
    )
    return {"claims": n_claims, "lines": len(labels),
            "denied_lines": sum(1 for r in labels if r["denied"])}  # fmt: skip
