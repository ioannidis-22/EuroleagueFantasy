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


from elfantasy.pir import BOX_COMPONENTS  # noqa: E402
from elfantasy.views import history_vs_teams, matchup_table, player_rates40  # noqa: E402


def mini_log():
    rows = []
    for g, (opp, pts, mins, dnp) in enumerate([("AAA", 20, 40, 0), ("BBB", 10, 20, 0), ("AAA", 0, 0, 1)]):
        r = {c: 0 for c in BOX_COMPONENTS}
        r.update(player_code="p1", opp_tv=opp, pts=pts, pir=pts, minutes=mins, dnp=dnp,
                 season="E2026", game_code=g, local_date=f"2026-10-0{g + 1}")
        rows.append(r)
    return pd.DataFrame(rows)


def test_player_rates40_ignores_dnp():
    r = player_rates40(mini_log(), "p1")
    assert r["pts"] == 30 / 60 * 40 and r["pir"] == 20


def test_matchup_table_pairs_rates_with_opponent_index():
    dv = pd.DataFrame({"idx_pts": [0.25], "idx_pir": [0.1]},
                      index=pd.MultiIndex.from_tuples([("AAA", "Guard")], names=["def_tv", "position"]))
    m = matchup_table(mini_log(), "p1", "AAA", "Guard", dv).set_index("stat")
    assert m.loc["pts", "player_per40"] == 20 and m.loc["pts", "opp_index"] == 0.25
    assert pd.isna(m.loc["ast", "opp_index"])


def test_matchup_table_without_dvp_row():
    m = matchup_table(mini_log(), "p1", "ZZZ", "Guard", pd.DataFrame())
    assert m["opp_index"].isna().all() and len(m) > 0


def test_history_vs_teams():
    h = history_vs_teams(mini_log(), "p1").set_index("opp_tv")
    assert h.loc["AAA", "games"] == 1 and h.loc["AAA", "pir_avg"] == 20 and h.loc["BBB", "pir_avg"] == 10
