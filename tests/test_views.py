import pandas as pd

from elfantasy.dvp import dvp, possessions
from elfantasy.metrics import game_log, player_summary
from elfantasy.settings import Settings
from elfantasy.store import read_df
from elfantasy.views import player_table


def build(conn):
    log = game_log(conn, "E2026")
    tab = dvp(log, possessions(read_df(conn, "select * from box_team")), 0.0)
    return player_table(conn, "E2026", 11, player_summary(log, Settings()), tab)


def test_player_table_joins_value_form_and_next_opponent(fixture_conn):
    t = build(fixture_conn).set_index("fantasy_id")
    assert len(t) == 340
    v = t.loc["3469"]
    assert v.player == "Sasha Vezenkov" and v.price == 18.9 and v.games == 1
    assert v.slot in (1, 2, 3) and v.opp != "OLY"
    assert v.form_delta == v.pir_last5 - v.pir_avg


def test_opponent_rank_joined_where_dvp_has_row(fixture_conn):
    log = game_log(fixture_conn, "E2026")
    tab = dvp(log, possessions(read_df(fixture_conn, "select * from box_team")), 0.0)
    t = player_table(fixture_conn, "E2026", 11, player_summary(log, Settings()), tab)
    has = t.dropna(subset=["opp_rank"])
    assert len(has) > 0
    for r in has.head(5).itertuples():
        assert r.opp_rank == tab.loc[(r.opp, r.position), "rank_pir"]


def test_unmatched_players_kept_with_nan_stats(fixture_conn):
    t = build(fixture_conn)
    unmatched = t[t["player_code"].isna()]
    assert len(unmatched) > 0 and unmatched["games"].isna().all()
    assert unmatched["slot"].notna().all()     # slot comes from the team, not the match
