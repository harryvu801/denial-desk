"""The four attack classes, each with cases.

1. INDIRECT_INJECTION — instructions planted inside a policy document in the ingestion set.
   The realistic attack on this architecture. Variants: direct imperative, role-play
   framing, fake system delimiters, instructions in a table cell, instructions in a PDF
   footer that survive text extraction.

2. TOOL_ABUSE — attempts to make the agent call a tool outside the claim in context, or to
   exceed its call budget. Should be structurally impossible, per ADR-021. Test that the
   structure actually holds rather than assuming it.

3. DATA_LEAKAGE — attempts to surface data from one claim in another's output, or to get
   identifiers into a trace or log.

4. DENIAL_OF_WALLET — documents crafted to induce unbounded retrieval or reasoning loops.
   Pass condition is that a budget trips and the claim is queued for review.

Target: roughly 60 cases, weighted toward class 1.

TODO(stage-4).
"""

from __future__ import annotations

from enum import StrEnum


class AttackClass(StrEnum):
    INDIRECT_INJECTION = "indirect_injection"
    TOOL_ABUSE = "tool_abuse"
    DATA_LEAKAGE = "data_leakage"
    DENIAL_OF_WALLET = "denial_of_wallet"
