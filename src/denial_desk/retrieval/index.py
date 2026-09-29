"""Index construction: pgvector for dense, rank_bm25 for lexical.

Both indexes are built over the same chunk set so that hybrid scores are comparable and a
chunking change re-indexes both at once. See ADR-009.

TODO(stage-2).
"""

from __future__ import annotations

from pathlib import Path


def build_index(corpus_dir: Path, chunker_name: str, index_version: str) -> None:
    """Index version is recorded on every eval run — see ADR-017."""
    raise NotImplementedError
