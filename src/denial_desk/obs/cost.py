"""Per-claim cost attribution.

Cost is recorded on the Resolution, not just emitted as a metric, so that the eval report
can break cost down by denial category and by lane. The share of denials resolved with zero
model spend is the headline number. See ADR-006.

TODO(stage-5).
"""
