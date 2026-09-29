"""Root-cause classification metrics: accuracy, per-class F1, confusion matrix.

Always report per-class and per-slice, never only the aggregate. An 88% average concealing
46% on one payer is the exact failure aggregate metrics are built to hide. See ADR-013.

TODO(stage-2).
"""
