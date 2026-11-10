import pytest
from streamlit.testing.v1 import AppTest

from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
PAGES = [str(APP / "Home.py"), str(APP / "pages" / "1_Players.py"), str(APP / "pages" / "2_Player.py"),
         str(APP / "pages" / "3_Compare.py"), str(APP / "pages" / "4_Opponents.py"),
         str(APP / "pages" / "5_Data.py")]


def test_player_page_with_selection(fixture_data_dir):
    at = AppTest.from_file(str(APP / "pages" / "2_Player.py"), default_timeout=60)
    at.session_state["player"] = "3469"
    at.run()
    assert not at.exception, at.exception
    assert any("Vezenkov" in t.value for t in at.title)


def test_compare_page_with_selection(fixture_data_dir):
    at = AppTest.from_file(str(APP / "pages" / "3_Compare.py"), default_timeout=60)
    at.session_state["compare"] = ["3469", "10042"]
    at.run()
    assert not at.exception, at.exception


@pytest.mark.parametrize("page", PAGES)
def test_page_runs(page, fixture_data_dir):
    at = AppTest.from_file(page, default_timeout=60).run()
    assert not at.exception, at.exception


def test_page_runs_on_empty_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ELFANTASY_DATA", str(tmp_path / "empty"))
    for page in PAGES:
        at = AppTest.from_file(page, default_timeout=60).run()
        assert not at.exception, (page, at.exception)


def test_opponents_has_no_previous_seasons_tab(fixture_data_dir):
    at = AppTest.from_file(str(APP / "pages" / "4_Opponents.py"), default_timeout=60).run()
    assert [t.label for t in at.tabs] == ["Heatmap", "Team", "Fixture difficulty"]
