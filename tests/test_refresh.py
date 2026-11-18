import json

import pytest

from conftest import FIXTURES
from elfantasy.el_client import ELApiError
from elfantasy.el_parse import parse_boxscore
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


def box_players(games):
    """(club, player code) of everyone in the fixture box scores of these games."""
    rows = set()
    for g in games:
        players, _ = parse_boxscore(json.loads((FIXTURES / f"box_E2026_{g}.json").read_text(encoding="utf-8")),
                                    "E2026", g)
        rows |= set(zip(players["club_code"], players["player_code"]))
    return rows


def rosters(games):
    out = {}
    for club, code in sorted(box_players(games)):
        out.setdefault(club, []).append(code)
    return out


ROUND_10 = set(range(91, 101))


def test_second_refresh_with_nothing_new_skips_rosters(conn):
    c = FakeClient(FIXTURES, rosters=rosters(ROUND_10))
    refresh_season(conn, c, "E2026")
    assert len(c.people_calls) == 20                  # no roster stored yet: every club
    refresh_season(conn, c, "E2026")
    assert len(c.people_calls) == 20


def test_box_score_with_unknown_player_fetches_his_club_roster(conn):
    c = FakeClient(FIXTURES, fail_on={95}, rosters=rosters(ROUND_10 - {95}))
    refresh_season(conn, c, "E2026")
    c.fail_on, c.rosters, n = set(), rosters(ROUND_10), len(c.people_calls)
    r = refresh_season(conn, c, "E2026")
    new = box_players({95})
    assert r.new_box_scores == 1
    assert sorted(c.people_calls[n:]) == sorted({club for club, _ in new})
    known = set(read_df(conn, "select club_code, player_code from el_players").itertuples(index=False, name=None))
    assert new <= known


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
