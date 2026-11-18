from statistics import mean

import pandas as pd
import pytest

from elfantasy.dvp import dvp, possessions
from elfantasy.pir import BOX_COMPONENTS


def rows(def_tv, game_code, day, players, position="Center", attacker_home=0, won=0, starter=1):
    """players: list of (pir, minutes). pir is put in pts so pir == pts."""
    out = []
    for i, (pir, mins) in enumerate(players):
        r = {c: 0 for c in BOX_COMPONENTS}
        r.update(pts=pir, pir=pir, minutes=mins, dnp=0, is_starter=starter, position=position,
                 opp_tv=def_tv, team_tv="ATT", is_home=attacker_home, won=won, season="E2026",
                 game_code=game_code, local_date=f"2026-10-{day:02d}T20:00:00",
                 player_code=f"{game_code}-{i}")
        out.append(r)
    return out


def poss_for(log, value=70.0):
    g = log[["season", "game_code"]].drop_duplicates()
    return g.assign(poss=value)


@pytest.fixture
def log():
    # AAA hosts game 1 (two centres 10+6 in 20+20 min) and visits game 2 (one centre 8 in 40 min)
    # BBB hosts game 3 (one centre 4 in 40 min)
    return pd.DataFrame(rows("AAA", 1, 1, [(10, 20), (6, 20)], attacker_home=0)
                        + rows("AAA", 2, 2, [(8, 40)], attacker_home=1)
                        + rows("BBB", 3, 3, [(4, 40)], attacker_home=0))


def test_per_game_and_per40(log):
    t = dvp(log, poss_for(log), 0.0, basis="game", shrink_minutes=0).loc[("AAA", "Center")]
    assert t.pir == 12 and t.games == 2 and t.minutes == 80
    t40 = dvp(log, poss_for(log), 0.0, basis="per40", shrink_minutes=0).loc[("AAA", "Center")]
    assert t40.pir == pytest.approx(24 / 80 * 40)


def test_index_rank_and_shrinkage(log):
    raw = dvp(log, poss_for(log), 0.0, shrink_minutes=0)
    assert raw.loc[("AAA", "Center"), "rank_pir"] == 1 and raw.loc[("BBB", "Center"), "rank_pir"] == 2
    league = 28 / 120 * 40
    assert raw.loc[("AAA", "Center"), "idx_pir"] == pytest.approx(12 / league - 1)
    big = dvp(log, poss_for(log), 0.0, shrink_minutes=1e9)
    assert abs(big.loc[("AAA", "Center"), "idx_pir"]) < 1e-6


def test_last5_and_home_windows():
    many = pd.DataFrame(sum((rows("AAA", g, g, [(g, 30)]) for g in range(1, 8)), []))
    t = dvp(many, poss_for(many), 0.0, window="last5", shrink_minutes=0).loc[("AAA", "Center")]
    assert t.games == 5 and t.pir == mean([3, 4, 5, 6, 7])


def test_home_away_split(log):
    h = dvp(log, poss_for(log), 0.0, window="home", shrink_minutes=0)
    assert set(h.index.get_level_values(0)) == {"AAA", "BBB"}
    assert h.loc[("AAA", "Center"), "games"] == 1 and h.loc[("AAA", "Center"), "pir"] == 16
    a = dvp(log, poss_for(log), 0.0, window="away", shrink_minutes=0)
    assert set(a.index.get_level_values(0)) == {"AAA"} and a.loc[("AAA", "Center"), "pir"] == 8


def test_role_filter():
    log = pd.DataFrame(rows("AAA", 1, 1, [(10, 30)], starter=1) + rows("AAA", 1, 1, [(2, 10)], starter=0))
    s = dvp(log, poss_for(log), 0.0, role="bench", shrink_minutes=0).loc[("AAA", "Center")]
    assert s.pir == 2


def test_per100_uses_possessions(log):
    t = dvp(log, poss_for(log, 70.0), 0.0, basis="per100", shrink_minutes=0).loc[("AAA", "Center")]
    assert t.pir == pytest.approx(mean([16 / 70 * 100, 8 / 70 * 100]))


def test_fpt_includes_bonus_for_attacking_wins():
    log = pd.DataFrame(rows("AAA", 1, 1, [(10, 20), (6, 20)], won=1))
    t = dvp(log, poss_for(log), 2.0, shrink_minutes=0).loc[("AAA", "Center")]
    assert t.fpt == pytest.approx(16 + 2 * 2.0)


def test_shooting_allowed(log):
    log.loc[log.game_code == 1, ["fgm2", "fga2"]] = [2, 4]
    t = dvp(log, poss_for(log), 0.0, shrink_minutes=0).loc[("AAA", "Center")]
    assert t.fg2_pct == pytest.approx(4 / 8)


def test_possessions():
    bt = pd.DataFrame({"season": "S", "game_code": [1, 1], "club_code": ["A", "B"],
                       "fga2": [40, 30], "fga3": [20, 30], "fta": [10, 20], "oreb": [10, 8], "tov": [12, 14]})
    p = possessions(bt).iloc[0]
    assert p.poss == pytest.approx(mean([40 + 20 + 4.4 - 10 + 12, 30 + 30 + 8.8 - 8 + 14]))
