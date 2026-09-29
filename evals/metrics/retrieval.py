"""Retrieval metrics: recall@k, nDCG@k, MRR.

Measured separately from generation on purpose. When an answer is wrong you need to know
whether the model never had the right passage or had it and ignored it — those have
opposite fixes. See ADR-008.

TODO(stage-2).
"""
