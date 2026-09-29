"""Axis three — cost and latency.

Reported on every run: USD per claim, tokens per claim split by retrieval vs generation,
p50/p95 end-to-end latency, and the deterministic share (percentage of denials resolved
with zero model spend). That last number is the quantified argument for the two-lane
architecture and belongs at the top of the README. See ADR-006.

TODO(stage-2).
"""
