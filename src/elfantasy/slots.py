"""T-slots: which day of a round each game is played on (T1, T2, T3...)."""
from __future__ import annotations

import sqlite3

import pandas as pd

from .store import read_df


def assign_slots(games: pd.DataFrame) -> pd.DataFrame:
    out = games.copy()
    day = out["local_date"].str[:10]
    out["slot"] = (day.groupby([out["season"], out["round"]])
                   .rank(method="dense").astype(int))
    return out


def next_round(conn: sqlite3.Connection, season: str) -> int | None:
    r = read_df(conn, "SELECT MIN(round) r FROM games WHERE season = ? AND played = 0", (season,))
    v = r["r"].iloc[0]
    return None if pd.isna(v) else int(v)


def team_slots(conn: sqlite3.Connection, season: str, round_: int) -> pd.DataFrame:
    g = read_df(conn, """SELECT g.season, g.game_code, g.round, g.local_date,
                                h.tv_code AS home_tv, a.tv_code AS away_tv
                         FROM games g
                         JOIN teams h ON h.club_code = g.home_club
                         JOIN teams a ON a.club_code = g.away_club
                         WHERE g.season = ? AND g.round = ?""", (season, round_))
    cols = ["tv_code", "slot", "game_code", "opp_tv", "is_home", "local_date"]
    if g.empty:
        return pd.DataFrame(columns=cols)
    g = assign_slots(g)
    home = g.assign(tv_code=g["home_tv"], opp_tv=g["away_tv"], is_home=1)
    away = g.assign(tv_code=g["away_tv"], opp_tv=g["home_tv"], is_home=0)
    return pd.concat([home, away])[cols].sort_values(["slot", "local_date", "tv_code"]).reset_index(drop=True)
