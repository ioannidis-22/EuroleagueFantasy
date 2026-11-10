"""End-to-end against the real Euroleague API. Run with: pytest -m live"""
import pytest

from conftest import FIXTURES
from elfantasy.el_client import ELClient
from elfantasy.fantasy_import import import_export
from elfantasy.matching import match_players
from elfantasy.pir import pir_box
from elfantasy.refresh import refresh_season
from elfantasy.store import connect, read_df


@pytest.mark.live
def test_live_current_season(tmp_path):
    conn = connect(tmp_path / "live.db")
    r = refresh_season(conn, ELClient(tmp_path / "cache"), "E2026", source="v3")
    assert r.failed == [] and r.new_box_scores >= 100
    p = read_df(conn, "select * from box_player")
    assert (pir_box(p) == p["pir_official"]).mean() == 1.0
    import_export(conn, FIXTURES / "players_stats.xlsx")
    rep = match_players(conn, "E2026", tmp_path / "none.json")
    assert rep.matched >= 320, rep.unmatched.to_string()
