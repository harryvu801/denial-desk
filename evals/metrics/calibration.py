"""Judge calibration — does the judge agree with Harry?

Procedure, and the order is not negotiable:
  1. Hand-grade ~150 appeal letters against the rubric. Do this FIRST, without looking at
     any judge output, or the labels are contaminated.
  2. Run the judge over the same set.
  3. Report Cohen's kappa per rubric dimension, plus the disagreement cases.
  4. Read the disagreements. They are the most informative artifact the project produces.

A judge below roughly kappa 0.6 on a dimension is not a measurement instrument and its
scores on that dimension must not be gated on. See ADR-014.

TODO(stage-3).
"""
