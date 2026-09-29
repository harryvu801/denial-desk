"""LLM-as-judge over generated appeal letters.

Rubric dimensions, each scored independently rather than as one blended number:
  - grounding: every factual claim traces to a retrieved passage
  - correctness: the letter addresses the CARC actually on the denial
  - fabrication: no invented policy, citations, or figures
  - deadline: the stated filing deadline matches the computed one

The judge is a different model from the one under test, to avoid a model grading its own
characteristic failure modes as acceptable. See ADR-014.

Untrusted by default. Nothing here is believed until calibration.py says it agrees with a
human. See ADR-014.

TODO(stage-3).
"""
