"""Versioned golden datasets.

A dataset is a directory under data/golden/<suite>/<version>/ containing the examples plus
a manifest recording how it was produced: generator seed, generator version, labeling date,
and labeler. Committed to git — they are small, and the whole point is that a result from
six weeks ago can be reproduced exactly. See ADR-017.

The hand-labeled generation set is the expensive one. Label it before the system is good,
or it will be shaped to flatter what already exists. See ADR-013.

TODO(stage-2).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

GOLDEN_ROOT = Path(__file__).parent.parent / "data" / "golden"


class DatasetManifest(BaseModel):
    suite: str
    version: str
    n_examples: int
    generator_seed: int | None
    generator_version: str | None
    labeled_by: str | None
    labeled_on: str | None
    notes: str = ""


def load(suite: str, version: str = "latest") -> tuple[list[dict[str, object]], DatasetManifest]:
    raise NotImplementedError
