from io import BytesIO

import openpyxl
import pandas as pd
import pytest

from conftest import FIXTURES
from fakes import FakeClient
from elfantasy.fantasy_import import ExportFormatError
from elfantasy.matchday import backtest, run_matchday, value_excel_bytes
from elfantasy.price_rule import PriceRule
from elfantasy.settings import Settings
from elfantasy.store import connect
from elfantasy.value import build_value_table
from elfantasy.xpir import VOLUME_STATS, XpirModel
from synth import seed_season_db, synth_season


@pytest.fixture
def fixture_conn_multi_round(conn):
    """Rounds 1-8 played by 40 synthetic players; exports stored for matchdays 7 and 8."""
    seed_season_db(conn, synth_season(rounds=8, players=40, seed=2), snapshot_rounds=[7, 8])
    return conn


def test_backtest_shape(fixture_conn_multi_round):
    bt = backtest(fixture_conn_multi_round, "E2026", PriceRule(), first_round=5)
    assert list(bt["round"]) == [5, 6, 7, 8] and (bt.mae_xpir > 0).all() and (bt.n > 0).all()
    assert list(bt.columns) == ["round", "n", "mae_xpir", "mae_baseline", "buy_n", "buy_hit", "sell_n", "sell_hit"]
    known = bt.set_index("round")
    assert known.loc[[5, 6], ["buy_hit", "sell_hit"]].isna().all().all()     # no export: prices unknown
    assert (known.loc[[7, 8], "buy_n"] + known.loc[[7, 8], "sell_n"] > 0).all()
    hits = known.loc[[7, 8], ["buy_hit", "sell_hit"]].stack()
    assert ((hits >= 0) & (hits <= 1)).all()


def test_excel_has_three_sheets(fixture_conn):
    model = XpirModel()
    v, st = build_value_table(fixture_conn, "E2026", 11, PriceRule(), model, Settings())
    wb = openpyxl.load_workbook(BytesIO(value_excel_bytes(v, st, model, PriceRule(), 11)))
    assert wb.sheetnames == ["Value", "Stat analysis", "Model"]
    assert wb["Value"].max_row == len(v) + 1
    items = {r[0]: r[1] for r in wb["Model"].iter_rows(min_row=2, values_only=True)}
    assert items["Price rule k"] == 0.042 and items["Price rule source"] == "default"
    assert all(f"Shrink strength {s}" in items for s in VOLUME_STATS)


def test_run_matchday_on_fixtures(tmp_path, monkeypatch):
    monkeypatch.setenv("ELFANTASY_DATA", str(tmp_path / "data"))
    conn = connect(tmp_path / "data" / "elfantasy.db")
    client = FakeClient(FIXTURES)
    r = run_matchday(conn, FIXTURES / "players_stats.xlsx", client, Settings())
    assert (r.matchday, r.round_) == (11, 11)
    assert r.refresh.new_box_scores == 10 and not r.refresh.failed
    assert len(r.value) == 340 and r.unmatched == (r.value.p_play.isna()).sum()
    assert r.rule == PriceRule() and isinstance(r.model, XpirModel)
    assert r.backtest is None                       # computed only when the page asks
    assert set(r.stats.fantasy_id) == set(r.value.loc[r.value.label != "NO DATA", "fantasy_id"])


class RecordingClient(FakeClient):
    def __init__(self, fixtures_dir):
        super().__init__(fixtures_dir)
        self.calls = []

    def games(self, season):
        self.calls.append("games")
        return super().games(season)


def test_bad_export_raises_before_any_refresh(tmp_path, monkeypatch):
    monkeypatch.setenv("ELFANTASY_DATA", str(tmp_path / "data"))
    bad = tmp_path / "bad.xlsx"
    wb = openpyxl.Workbook()
    wb.active.append(["ID", "Name", "Something else"])
    wb.save(bad)
    client = RecordingClient(FIXTURES)
    with pytest.raises(ExportFormatError):
        run_matchday(connect(tmp_path / "data" / "elfantasy.db"), bad, client, Settings())
    assert client.calls == [] and client.box_calls == 0
