from pathlib import Path

import pytest

from elfantasy.store import connect

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    yield c
    c.close()


@pytest.fixture
def fixture_conn(tmp_path):
    """DB with rounds 10-11 fixtures, round-10 box scores, the real export and player matching."""
    from fakes import FakeClient
    from elfantasy.fantasy_import import import_export
    from elfantasy.matching import match_players
    from elfantasy.refresh import refresh_season

    c = connect(tmp_path / "fx.db")
    refresh_season(c, FakeClient(FIXTURES), "E2026")
    import_export(c, FIXTURES / "players_stats.xlsx")
    match_players(c, "E2026", tmp_path / "no_overrides.json")
    yield c
    c.close()
