import pytest

from conftest import FIXTURES
from elfantasy.el_client import ELApiError
from fakes import FakeClient
from elfantasy.refresh import refresh_season
from elfantasy.store import read_df


def test_refresh_stores_played_games_and_reports_failures(conn):
    r = refresh_season(conn, FakeClient(FIXTURES, fail_on={95}), "E2026")
    assert r.games_total == 20 and r.new_box_scores == 9
    assert [code for code, _ in r.failed] == [95] and "boom 95" in r.failed[0][1]
    stored = set(read_df(conn, "select distinct game_code from box_player")["game_code"])
    assert 95 not in stored and len(stored) == 9
    assert 95 not in set(read_df(conn, "select distinct game_code from box_team")["game_code"])
    assert read_df(conn, "select count(*) n from teams")["n"][0] == 20
    assert read_df(conn, "select count(*) n from el_players")["n"][0] == 18


def test_second_refresh_fetches_only_missing(conn):
    c = FakeClient(FIXTURES, fail_on={95})
    refresh_season(conn, c, "E2026")
    c.fail_on = set()
    n = c.box_calls
    r = refresh_season(conn, c, "E2026")
    assert r.new_box_scores == 1 and c.box_calls == n + 1 and r.failed == []


def test_progress_callback(conn):
    seen = []
    refresh_season(conn, FakeClient(FIXTURES), "E2026", progress=lambda i, n: seen.append((i, n)))
    assert seen[-1] == (10, 10)


def test_refresh_v3_source_stores_positions(conn):
    c = FakeClient(FIXTURES)
    r = refresh_season(conn, c, "E2026", source="v3")
    assert r.new_box_scores == 10 and r.failed == []
    pos = read_df(conn, "select position from el_players where player_code = '014163'")
    assert list(pos["position"]) == ["Guard"]


class DownClient(FakeClient):
    def __init__(self, exc):
        super().__init__(FIXTURES)
        self.exc = exc

    def games(self, season):
        raise self.exc


@pytest.mark.parametrize("exc", [ELApiError("offline"), KeyError("data")])
def test_fixtures_failure_reported_not_raised(conn, exc):
    r = refresh_season(conn, DownClient(exc), "E2026")
    assert r.games_total == 0 and r.new_box_scores == 0
    assert len(r.failed) == 1 and r.failed[0][0] == 0 and "fixtures" in r.failed[0][1]


def test_malformed_games_payload_reported(conn):
    class Bad(FakeClient):
        def games(self, season):
            return {"data": [{"gameCode": 1}]}          # missing round, clubs, ...
    r = refresh_season(conn, Bad(FIXTURES), "E2026")
    assert r.failed and "fixtures" in r.failed[0][1]
