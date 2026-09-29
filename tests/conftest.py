"""Shared fixtures.

Unit tests must run with no database server and no network. Anything needing either is
marked @pytest.mark.integration; anything making real model calls is marked
@pytest.mark.costly and is excluded from the default run. See ADR-002.

The X12 fixtures in tests/fixtures are hand-written, not generated: a parser test is only
meaningful if the right answer is known independently of the generator.
"""

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_835_raw() -> str:
    return (FIXTURES / "sample.835").read_text()


@pytest.fixture
def sample_837_raw() -> str:
    return (FIXTURES / "sample.837").read_text()
