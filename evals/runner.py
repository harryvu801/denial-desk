"""Run evals, record provenance, compare against baseline, gate the build.

Every run writes a record containing: git SHA, prompt version, model versions, retrieval
index version, dataset versions, full settings snapshot, every metric, and total spend.
Two runs can then be diffed, which is the difference between an eval system and a folder of
scripts. See ADR-017.

--gate compares against evals/baseline.json and exits non-zero when any gated metric
regresses beyond its tolerance, or when cost per claim rises beyond its ceiling. A prompt
change that improves accuracy 2% while tripling cost should fail. See ADR-019.

TODO(stage-2 for the skeleton, stage-5 for the full record/diff).
"""

from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suites", nargs="+", default=["accuracy"])
    parser.add_argument("--gate", action="store_true")
    parser.parse_args()
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
