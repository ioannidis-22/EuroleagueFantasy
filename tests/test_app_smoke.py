import pytest
from streamlit.testing.v1 import AppTest

from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
PAGES = [str(APP / "Home.py"), str(APP / "pages" / "5_Data.py")]


@pytest.mark.parametrize("page", PAGES)
def test_page_runs(page, fixture_data_dir):
    at = AppTest.from_file(page, default_timeout=60).run()
    assert not at.exception, at.exception


def test_page_runs_on_empty_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ELFANTASY_DATA", str(tmp_path / "empty"))
    for page in PAGES:
        at = AppTest.from_file(page, default_timeout=60).run()
        assert not at.exception, (page, at.exception)
