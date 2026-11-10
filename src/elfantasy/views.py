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
