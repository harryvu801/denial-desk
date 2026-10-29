"""Turn a denial and its case file into the exact text a model sees.

Two rules (ADR-020): untrusted free text is marked at the boundary, inside its own
delimited block, and anything in it that could forge or close a delimiter is neutralized
first. Structured facts go in as JSON so the model reads values, not prose about values.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from denial_desk.agent.prompts import Prompt
from denial_desk.domain.case_file import CaseFile
from denial_desk.domain.models import DenialRecord
from denial_desk.reference import carc_table, rarc_table


@dataclass(frozen=True)
class ProposalRequest:
    line_control_number: str
    prompt: Prompt
    system: str
    user: str


def neutralize(untrusted: str) -> str:
    """Escape angle brackets so untrusted text cannot open or close a delimiter block."""
    return untrusted.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def denial_facts(record: DenialRecord) -> dict[str, Any]:
    as_of = record.adjudication_date
    line = record.submitted
    return {
        "payer": record.payer.value,
        "procedure_code": line.procedure_code,
        "modifiers": list(line.modifiers),
        "units": str(line.units),
        "charge": str(line.charge),
        "denied_amount": str(record.denied_amount),
        "service_date": line.service_date.isoformat(),
        "submission_date": record.submission_date.isoformat(),
        "adjudication_date": as_of.isoformat(),
        "prior_auth_on_claim": record.prior_auth_number,
        "carc": {
            "code": record.primary_carc,
            "definition": carc_table().describe(record.primary_carc, as_of),
        },
        "rarcs": [
            {"code": code, "definition": rarc_table().describe(code, as_of)}
            for code in record.remark_codes
        ],
        "adjustments": [
            {"group": a.group_code.value, "carc": a.reason_code, "amount": str(a.amount)}
            for a in record.adjudicated.adjustments
        ],
    }


def build_request(record: DenialRecord, case_file: CaseFile, prompt: Prompt) -> ProposalRequest:
    structured = case_file.model_dump(mode="json", exclude={"care_note"})
    for key in ("patient_control_number", "line_control_number"):
        structured.pop(key)
    user = prompt.user_template.substitute(
        denial=json.dumps(denial_facts(record), indent=2, sort_keys=True),
        case_file=json.dumps(structured, indent=2, sort_keys=True),
        care_note=neutralize(case_file.care_note) or "(no note)",
    )
    return ProposalRequest(record.line_control_number, prompt, prompt.system, user)
