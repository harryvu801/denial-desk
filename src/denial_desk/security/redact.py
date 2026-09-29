"""Redaction before anything reaches logs, traces, or the eval store.

The data is synthetic, so this protects nothing today. It is built anyway, because the
discipline is the point and because a system that only redacts in production has never had
its redaction tested. See ADR-022.

TODO(stage-4).
"""

from __future__ import annotations


def redact(text: str, mode: str = "strict") -> str:
    raise NotImplementedError


def scan_for_identifiers(text: str) -> list[str]:
    """Used as an output check on generated letters, not only as a logging filter."""
    raise NotImplementedError
