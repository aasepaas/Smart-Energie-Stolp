from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_bytes():
    """Leest een test-CSV uit tests/fixtures."""
    return lambda name: (FIXTURES / name).read_bytes()
