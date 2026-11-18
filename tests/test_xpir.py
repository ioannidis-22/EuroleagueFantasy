import pytest

from elfantasy.xpir import EFFICIENCIES, VOLUME_STATS, channel_table, foul_value, player_priors
from synth import make_log, pir_games

INF = float("inf")
ZERO = {s: 0.0 for s in [*VOLUME_STATS, *EFFICIENCIES]}

VARIED = [
    {"minutes": 31, "fgm2": 5, "fga2": 9, "fgm3": 2, "fga3": 6, "ftm": 4, "fta": 5, "fd": 4, "oreb": 2,
     "dreb": 5, "ast": 3, "stl": 1, "blk": 1, "tov": 2, "blka": 1, "pf": 3},
    {"minutes": 24, "fgm2": 2, "fga2": 7, "fgm3": 0, "fga3": 4, "ftm": 1, "fta": 2, "fd": 2, "oreb": 0,
     "dreb": 3, "ast": 5, "stl": 0, "blk": 0, "tov": 4, "blka": 0, "pf": 2},
    {"minutes": 18, "fgm2": 3, "fga2": 3, "fgm3": 3, "fga3": 5, "ftm": 6, "fta": 8, "fd": 5, "oreb": 1,
     "dreb": 1, "ast": 0, "stl": 2, "blk": 0, "tov": 1, "blka": 2, "pf": 4},
]


def test_foul_value_matches_season_examples():
    assert foul_value(1.31, 0.92) == pytest.approx(2.1004)      # Maledon
    assert foul_value(0.72, 0.72) == pytest.approx(1.3168)      # Shorts


def test_channels_reproduce_pir_exactly_without_shrinkage():
    log = make_log({"p": {"position": "Guard", "games": VARIED}})
    t = channel_table(log, ZERO, INF)
    assert t.loc["p", "pir_per_min"] * log.minutes.sum() == pytest.approx(log.pir.sum())


def two_guards():
    big = [{"minutes": 30, "fga3": 6}] * 10
    tiny = [{"minutes": 5, "fga3": 3}]
    return make_log({"big": {"position": "Guard", "games": big},
                     "tiny": {"position": "Guard", "games": tiny}})


def test_shrinkage_pulls_small_samples_to_position():
    log = two_guards()
    prior = 63 / 305                       # pooled guard 3PA per minute
    assert channel_table(log, ZERO, INF).loc["tiny", "r_fga3"] == pytest.approx(3 / 5)
    t = channel_table(log, {**ZERO, "fga3": 100.0}, INF)
    assert t.loc["tiny", "r_fga3"] == pytest.approx((3 + 100 * prior) / (5 + 100))
    assert t.loc["big", "r_fga3"] == pytest.approx((60 + 100 * prior) / (300 + 100))
    huge = channel_table(log, {**ZERO, "fga3": 1e9}, INF)
    assert huge.loc["tiny", "r_fga3"] == pytest.approx(huge.loc["big", "r_fga3"], rel=0.05)


def test_recency_half_life_weights_latest_game_most():
    log = make_log({"p": {"position": "Guard", "games": [{"ast": a} for a in (1, 2, 3, 4, 5)]}})
    assert channel_table(log, ZERO, 1.0).loc["p", "r_ast"] > channel_table(log, ZERO, INF).loc["p", "r_ast"]
    assert channel_table(log, ZERO, INF).loc["p", "r_ast"] == pytest.approx(15 / 100)


def test_player_without_games_gets_position_prior():
    log = make_log({"g1": {"position": "Guard", "games": VARIED},
                    "c1": {"position": "Center", "games": pir_games([20, 30])}})
    pri = player_priors(log)
    guards = log[log.position == "Guard"]
    assert pri.loc["Guard", "pir_per_min"] == pytest.approx(guards.pir.sum() / guards.minutes.sum())
    assert pri.loc["Center", "pir_per_min"] == pytest.approx(50 / 40)


def test_last_dev_and_dnps_ignored():
    games = pir_games([10, 12, 2]) + [{"dnp": 1, "minutes": 0}]
    t = channel_table(make_log({"p": {"position": "Guard", "games": games}}), ZERO, INF)
    assert t.loc["p", "last_dev"] == pytest.approx(2 - 11)
    assert t.loc["p", "games"] == 3 and t.loc["p", "pir_avg"] == pytest.approx(8)
