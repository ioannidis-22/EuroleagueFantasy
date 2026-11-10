from pathlib import Path

import pytest

from elfantasy.store import connect

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    yield c
    c.close()
