"""Chunking strategies, plural — on purpose.

Three strategies are implemented so the choice can be settled by measurement rather than
by a blog post. The comparison is a deliverable, not scaffolding to be deleted once one
wins. See ADR-008.

TODO(stage-2).
"""

from __future__ import annotations

from typing import Protocol

from denial_desk.domain.models import Evidence


class Chunker(Protocol):
    name: str

    def chunk(self, document_text: str, source_id: str) -> list[Evidence]: ...


class FixedWindowChunker:
    """Baseline: N tokens with overlap. Cheap, ignores document structure."""

    name = "fixed"


class SectionAwareChunker:
    """Splits on the manual's own heading hierarchy.

    Expected to win for this corpus, because provider manuals are written as numbered
    policy sections and a citation to '§ 4.3.2' is only meaningful if the chunk boundary
    respects it. Expectations are not evidence — measure it.
    """

    name = "section"


class SemanticChunker:
    """Embedding-similarity boundaries. Included as the expensive control."""

    name = "semantic"
