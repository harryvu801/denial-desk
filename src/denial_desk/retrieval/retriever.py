"""Hybrid retrieval with reranking, and an explicit refusal floor.

Lexical matters here more than it does for most RAG: a denial turns on exact tokens like
'T1019' or 'CARC 197', and dense embeddings are unreliable on bare codes. Dense matters for
the paraphrased policy questions. Hence both, fused, then reranked. See ADR-009.

If the reranked top score is below settings.retrieval_min_score the retriever returns
nothing and the caller must refuse rather than answer. Refusing is a feature and it is
measured. See ADR-011.

TODO(stage-2).
"""

from __future__ import annotations

from denial_desk.domain.models import Evidence


def retrieve(query: str, k: int = 5) -> list[Evidence]:
    """Return reranked evidence, or an empty list when confidence is below the floor."""
    raise NotImplementedError
