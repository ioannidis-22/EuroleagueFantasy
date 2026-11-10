"""Table assemblies used by the app pages (joins only; metrics live elsewhere)."""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from .metrics import value_table
from .slots import next_round, team_slots
from .store import read_df


def next_fixtures(conn: sqlite3.Connection, season: str) -> pd.DataFrame:
    """Per team for the next round: first slot, opponent, home flag, number of games."""
    r = next_round(conn, season)
    if r is None:
        return pd.DataFrame(columns=["team", "slot", "opp", "is_home", "games_next", "round"])
    ts = team_slots(conn, season, r).sort_values("slot")
    g = ts.groupby("tv_code").agg(slot=("slot", "first"), opp=("opp_tv", "first"),
                                  is_home=("is_home", "first"), games_next=("game_code", "size"))
    return g.reset_index().rename(columns={"tv_code": "team"}).assign(round=r)


def player_table(conn: sqlite3.Connection, season: str, matchday: int, summary: pd.DataFrame,
                 dvp_table: pd.DataFrame) -> pd.DataFrame:
    v = value_table(conn, matchday)
    v["player"] = v["name"] + " " + v["surname"]
    pm = read_df(conn, "SELECT fantasy_id, player_code FROM player_map")
    t = v.merge(pm, on="fantasy_id", how="left")
    t = t.merge(summary, left_on="player_code", right_index=True, how="left")
    t["form_delta"] = t["pir_last5"] - t["pir_avg"]
    t = t.merge(next_fixtures(conn, season), on="team", how="left")
    if len(dvp_table):
        d = dvp_table[["rank_pir", "idx_pir"]].reset_index().rename(
            columns={"def_tv": "opp", "rank_pir": "opp_rank", "idx_pir": "opp_idx"})
        t = t.merge(d, on=["opp", "position"], how="left")
    else:
        t["opp_rank"], t["opp_idx"] = np.nan, np.nan
    return t


RATE_STATS = ["pts", "oreb", "dreb", "ast", "stl", "blk", "fd", "tov", "blka", "pf",
              "fga2", "fga3", "fta", "pir"]


def player_rates40(log: pd.DataFrame, player_code: str) -> pd.Series:
    p = log[(log["player_code"] == player_code) & (log["dnp"] == 0)]
    mins = p["minutes"].sum()
    if mins <= 0:
        return pd.Series(np.nan, index=RATE_STATS)
    return p[RATE_STATS].sum() / mins * 40


def matchup_table(log: pd.DataFrame, player_code: str, opp: str, position: str,
                  dvp_table: pd.DataFrame) -> pd.DataFrame:
    rates = player_rates40(log, player_code)
    key = (opp, position)
    row = dvp_table.loc[key] if len(dvp_table) and key in dvp_table.index else pd.Series(dtype=float)
    return pd.DataFrame({"stat": RATE_STATS, "player_per40": rates.values,
                         "opp_index": [row.get(f"idx_{c}", np.nan) for c in RATE_STATS]})


def history_vs_teams(log: pd.DataFrame, player_code: str) -> pd.DataFrame:
    p = log[(log["player_code"] == player_code) & (log["dnp"] == 0)]
    return (p.groupby("opp_tv").agg(games=("pir", "size"), pir_avg=("pir", "mean"),
                                    min_avg=("minutes", "mean"), last=("local_date", "max"))
            .reset_index().sort_values(["games", "pir_avg"], ascending=False))


def conceded_trend(log: pd.DataFrame, def_tv: str, window: int = 5) -> pd.DataFrame:
    """PIR conceded per game to each position by one team, with a rolling mean over its games."""
    p = log[(log["opp_tv"] == def_tv) & (log["dnp"] == 0) & log["position"].notna()]
    games = p[["season", "game_code", "round", "local_date"]].drop_duplicates().sort_values("local_date")
    per = p.groupby(["season", "game_code", "position"])["pir"].sum().unstack(fill_value=0)
    per = games.merge(per.reset_index(), on=["season", "game_code"], how="left").fillna(0)
    long = per.melt(id_vars=["season", "game_code", "round", "local_date"], var_name="position",
                    value_name="pir")
    long = long.sort_values("local_date")
    long["rolling_pir"] = long.groupby("position")["pir"].transform(
        lambda x: x.rolling(window, min_periods=1).mean())
    return long.reset_index(drop=True)
