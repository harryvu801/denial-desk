"""Axis two — robustness.

  - variance: the same 50 inputs, five runs, at production temperature. Report spread, not
    just the mean. A system whose answer moves between runs cannot be gated on a single run.
  - prompt sensitivity: benign rewordings of the denial narrative must not change the
    classification.
  - degraded retrieval: starve the retriever deliberately. Does the system refuse, or does
    it start inventing policy? Refusal is the pass condition.
  - adversarial set: ~50 denials citing policies that do not exist or that are genuinely
    ambiguous. Measured as refusal rate and hallucination rate.

See ADR-011.

TODO(stage-3).
"""
