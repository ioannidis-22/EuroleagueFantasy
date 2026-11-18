import pandas as pd
import pytest

from elfantasy.price_rule import PriceRule
from elfantasy.settings import Settings
from elfantasy.slots import team_slots
from elfantasy.store import read_df, upsert_rows
from elfantasy.value import build_value_table, p_play
from elfantasy.xpir import EFFICIENCIES, VOLUME_STATS, XpirModel
from synth import make_log

FIXED_MODEL = XpirModel(k={**dict.fromkeys(VOLUME_STATS, 100.0), **dict.fromkeys(EFFICIENCIES, 20.0)},
                        half_life=float("inf"), w_season_min=0.5, alpha=0.0, beta=1.0, gamma_home=0.0,
                        delta_bounce=0.0)
VEZENKOV = "3469"


def value(conn, s=Settings(), round_=11):
    return build_value_table(conn, "E2026", round_, PriceRule(), FIXED_MODEL, s)


def test_value_formula_and_labels(fixture_conn):
    v, _ = value(fixture_conn)
    scored = v[v.label != "NO DATA"]
    assert len(scored) > 0
    for r in scored.itertuples():
        expected = r.p_play * 0.042 * (r.xpir - (1.14 * r.price - 1.0)) + (1 - r.p_play) * -0.06
        assert r.value == pytest.approx(expected) and r.roi == pytest.approx(r.value / r.price)
        assert r.break_even == pytest.approx(1.14 * r.price - 1.0)
    assert set(v.label) <= {"BUY", "HOLD", "SELL", "NO DATA"}
    assert (v.loc[v.label == "BUY", "value"] >= 0.10).all() and (v.loc[v.label == "SELL", "value"] <= -0.10).all()
    hold = v.loc[v.label == "HOLD", "value"]
    assert ((hold > -0.10) & (hold < 0.10)).all()
    assert list(scored.value) == sorted(scored.value, reverse=True)
    assert (v.label.iloc[len(scored):] == "NO DATA").all()          # unscored rows at the bottom


def seed_previous_snapshot(conn, bump: dict[str, float]):
    fp = read_df(conn, "SELECT * FROM fantasy_players WHERE matchday = 11")
    fp["matchday"] = 10
    fp["price"] = fp["price"] + fp["fantasy_id"].map(bump).fillna(0.0)
    upsert_rows(conn, "fantasy_players", fp)
    upsert_rows(conn, "snapshots", pd.DataFrame([{"matchday": 10, "reference_matchdays": "[10]",
                                                  "imported_at": "x", "file_hash": "h10"}]))


def test_dip_flag(fixture_conn):
    seed_previous_snapshot(fixture_conn, {VEZENKOV: 0.4})
    everyone_buys = Settings(value_buy=-10.0, value_sell=-20.0, dip_min_avg=0.0)
    v = value(fixture_conn, everyone_buys)[0].set_index("fantasy_id")
    r = v.loc[VEZENKOV]
    assert r.last_price_change == pytest.approx(-0.4) and r.label == "BUY" and r.dip
    assert not v.drop(VEZENKOV).dip.any()                         # no one else's price fell
    bigger_drop_needed = Settings(value_buy=-10.0, value_sell=-20.0, dip_min_avg=0.0, dip_drop=0.5)
    assert not value(fixture_conn, bigger_drop_needed)[0].set_index("fantasy_id").loc[VEZENKOV, "dip"]


def test_last_price_change_nan_without_previous_snapshot(fixture_conn):
    v, _ = value(fixture_conn)
    assert v.last_price_change.isna().all() and not v.dip.any()


def test_unmatched_player_kept_as_no_data(fixture_conn):
    v, _ = value(fixture_conn)
    matched = len(read_df(fixture_conn, "SELECT * FROM player_map"))
    assert len(v) == 340
    assert v.p_play.isna().sum() == 340 - matched
    assert (v.loc[v.p_play.isna(), "label"] == "NO DATA").all()


def test_fixture_uses_export_team(fixture_conn):
    fixture_conn.execute("UPDATE fantasy_players SET team = 'PAO' WHERE fantasy_id = ?", (VEZENKOV,))
    fixture_conn.commit()
    v, _ = value(fixture_conn)
    pao = team_slots(fixture_conn, "E2026", 11).set_index("tv_code").loc["PAO", "opp_tv"]
    assert v.set_index("fantasy_id").loc[VEZENKOV, "opp"] == pao


def test_p_play_prior_and_recent_dnps():
    # AAA played rounds 1-7; before round 7 its last five games are rounds 2-6
    games = pd.DataFrame({"tv_code": "AAA", "game_code": range(1, 8), "round": range(1, 8),
                          "local_date": [f"2026-10-0{r}" for r in range(1, 8)]})
    log = make_log({"p": {"position": "Guard", "games": [{"round": 1}, {"round": 2}, {"round": 3, "dnp": 1,
                                                                                      "minutes": 0},
                                                         {"round": 6}, {"round": 7}]}})
    team_of = pd.Series({"p": "AAA", "q": "ZZZ"})
    s = p_play(log, games, team_of, before_round=7)
    assert s["p"] == pytest.approx((2 + 1.8) / (5 + 2))
    assert s["q"] == pytest.approx(0.9)                            # no games yet: the prior


def test_stat_analysis_sums_to_raw(fixture_conn):
    v, st = value(fixture_conn)
    scored = v[(v.label != "NO DATA") & (v.xpir > 0)]
    for r in scored.head(5).itertuples():
        one = st[st.fantasy_id == r.fantasy_id]
        assert list(one.channel) == list(dict.fromkeys(one.channel)) and len(one) == len(VOLUME_STATS)
        assert one.pir_per_game.sum() == pytest.approx(r.xpir)      # FIXED_MODEL: xPIR == raw
        fd = one.set_index("channel").loc["fouls drawn", "efficiency"]
        assert fd.startswith("FTA/FD ") and "FT% " in fd
