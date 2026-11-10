import json

import pytest
import requests

from elfantasy.el_client import ELApiError, ELClient
from fakes import FakeSession


def test_boxscore_cached_after_first_fetch(tmp_path):
    s = FakeSession({"Boxscore": (200, {"Live": False, "Stats": [], "x": "Ναι"})})
    c = ELClient(tmp_path, delay_s=0, session=s)
    first = c.boxscore("E2026", 5)
    second = c.boxscore("E2026", 5)
    assert s.calls == 1 and first == second
    cached = json.loads((tmp_path / "E2026" / "box_5.json").read_text(encoding="utf-8"))
    assert cached["x"] == "Ναι"


def test_live_game_not_cached(tmp_path):
    s = FakeSession({"Boxscore": (200, {"Live": True, "Stats": []})})
    ELClient(tmp_path, delay_s=0, session=s).boxscore("E2026", 6)
    assert not (tmp_path / "E2026" / "box_6.json").exists()


def test_http_error_raises_after_retries(tmp_path):
    s = FakeSession({"games": (503, {})})
    with pytest.raises(ELApiError, match="games"):
        ELClient(tmp_path, delay_s=0, session=s, retries=2).games("E2026")
    assert s.calls == 3


def test_timeout_raises_api_error(tmp_path):
    s = FakeSession({"people": requests.Timeout("slow")})
    with pytest.raises(ELApiError):
        ELClient(tmp_path, delay_s=0, session=s, retries=1).people("E2026", "OLY")
    assert s.calls == 2


def test_urls(tmp_path):
    seen = []

    class Rec(FakeSession):
        def get(self, url, timeout=None):
            seen.append(url)
            return super().get(url, timeout)

    c = ELClient(tmp_path, delay_s=0, session=Rec({"": (200, {"Live": False})}))
    c.games("E2026"); c.people("E2026", "OLY"); c.boxscore("E2026", 7)
    assert seen == [
        "https://api-live.euroleague.net/v2/competitions/E/seasons/E2026/games",
        "https://api-live.euroleague.net/v2/competitions/E/seasons/E2026/clubs/OLY/people",
        "https://live.euroleague.net/api/Boxscore?gamecode=7&seasoncode=E2026",
    ]
