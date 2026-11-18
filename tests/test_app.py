from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from conftest import FIXTURES
from fakes import FakeClient
from elfantasy.matchday import run_matchday
from elfantasy.settings import Settings
from elfantasy.store import connect

HOME = str(Path(__file__).resolve().parents[1] / "app" / "Home.py")


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    """A fixture-data run where one box score (game 95) failed to download."""
    d = tmp_path_factory.mktemp("data")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("ELFANTASY_DATA", str(d))
        conn = connect(d / "elfantasy.db")
        r = run_matchday(conn, FIXTURES / "players_stats.xlsx", FakeClient(FIXTURES, fail_on=(95,)), Settings())
        conn.close()
    return r


def page_with(result):
    at = AppTest.from_file(HOME, default_timeout=60)
    at.session_state["result"] = result
    return at.run()


def test_page_runs_without_upload(tmp_path, monkeypatch):
    monkeypatch.setenv("ELFANTASY_DATA", str(tmp_path / "empty"))
    at = AppTest.from_file(HOME, default_timeout=60).run()
    assert not at.exception, at.exception
    assert at.title[0].value == "Euroleague fantasy value picks"
    assert len(at.dataframe) == 0 and at.button[0].disabled


def test_table_lists_every_export_player(result):
    at = page_with(result)
    assert not at.exception, at.exception
    table = at.dataframe[0].value
    assert len(table) == 340
    assert list(table.columns) == ["Player", "Team", "Pos", "Price", "Last change", "Opponent", "P(play)", "xPIR",
                                   "Break-even", "Value", "ROI", "Label", "DIP"]
    assert (table["Label"].iloc[-result.unmatched:] == "NO DATA").all()      # NO DATA rows at the bottom


def test_label_and_position_filters_narrow_the_table(result):
    at = page_with(result)
    at.multiselect(key="label_filter").set_value(["NO DATA"]).run()
    table = at.dataframe[0].value
    assert len(table) == (result.value.label == "NO DATA").sum() < 340
    assert set(table["Label"]) == {"NO DATA"}
    at.selectbox(key="position_filter").set_value("Center").run()
    assert set(at.dataframe[0].value["Pos"]) == {"Center"}


def test_formula_card_and_messages(result):
    at = page_with(result)
    shown = " ".join(c.value for c in at.code)
    assert "0.042" in shown and "1.14" in shown and f"Round {result.round_}" in " ".join(h.value for h in at.subheader)
    assert any("95" in w.value for w in at.warning)                         # the failed box score
    assert any("Backtest" in c.value for c in at.caption)
