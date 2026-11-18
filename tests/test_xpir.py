import pandas as pd
import pytest

from elfantasy.xpir import (EFFICIENCIES, HALF_LIVES, VOLUME_STATS, channel_table, features_for_round,
                            fit_xpir, foul_value, player_priors, predict_xpir)
from synth import make_log, pir_games, synth_poss, synth_season

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


def fouls_league():
    """Rounds 1-5: four guards alternate between SOFT (they draw 6 fouls) and AVG (they draw 2)."""
    players = {}
    for i in range(4):
        games = []
        for r in range(1, 6):
            soft = (r + i) % 2 == 0
            games.append({"round": r, "opp_tv": "SOFT" if soft else "AVG", "minutes": 30,
                          "fd": 6 if soft else 2, "fta": 6 if soft else 2, "ftm": 4 if soft else 1,
                          "ast": 3, "fga2": 4, "fgm2": 2, "fga3": 3, "fgm3": 1})
        players[f"g{i}"] = {"position": "Guard", "games": games}
    return make_log(players)


def fixture(opp, code="g0", position="Guard", home=1):
    return pd.DataFrame({"player_code": [code], "position": [position], "opp_tv": [opp], "is_home": [home]})


def test_opponent_multiplier_raises_matching_channel():
    log = fouls_league()
    poss = synth_poss(log)
    soft = features_for_round(log, poss, 6, fixture("SOFT"), ZERO, INF, 0.5)
    avg = features_for_round(log, poss, 6, fixture("AVG"), ZERO, INF, 0.5)
    assert soft.loc["g0", "opp_fd"] > 1.0 > avg.loc["g0", "opp_fd"]
    assert soft.loc["g0", "opp_ast"] == pytest.approx(1.0)
    assert soft.loc["g0", "raw"] > avg.loc["g0", "raw"]


def test_no_leakage_from_target_round_or_later():
    log = synth_season(rounds=8, players=20, seed=3)
    changed = log.copy()
    later = changed["round"] >= 6
    changed.loc[later, ["ast", "fd", "minutes"]] = changed.loc[later, ["ast", "fd", "minutes"]] * 3
    changed.loc[later, "pir"] += 50
    fx = log[log["round"] == 6][["player_code", "position", "opp_tv", "is_home"]]
    a = features_for_round(log, synth_poss(log), 6, fx, ZERO, INF, 0.5)
    b = features_for_round(changed, synth_poss(changed), 6, fx, ZERO, INF, 0.5)
    pd.testing.assert_frame_equal(a, b)


@pytest.fixture(scope="module")
def season():
    return synth_season(rounds=10, players=40, seed=1)


@pytest.fixture(scope="module")
def model(season):
    return fit_xpir(season, synth_poss(season), rounds=list(range(4, 11)))


def test_fit_recovers_calibration_on_synthetic_season(model):
    assert 0.6 < model.beta < 1.4 and model.mae < model.mae_baseline
    assert set(model.k) == {*VOLUME_STATS, *EFFICIENCIES} and model.half_life in HALF_LIVES
    assert model.train_rows > 200


def test_predict_handles_player_without_history(model, season):
    fx = pd.concat([fixture("T1", code="P000"), fixture("T1", code="new")])
    out = predict_xpir(model, season, synth_poss(season), 11, fx)
    assert out.loc["new", "xpir"] > 0 and out.loc["new", "games"] == 0
    assert out.loc["P000", "games"] > 0
