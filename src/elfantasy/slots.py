"""T-slots: which day of a round each game is played on (T1, T2, T3...)."""
from __future__ import annotations

import sqlite3
from datetime import date

import pandas as pd

from .store import read_df


def assign_slots(games: pd.DataFrame) -> pd.DataFrame:
    out = games.copy()
    day = out["local_date"].str[:10]
    out["slot"] = (day.groupby([out["season"], out["round"]])
                   .rank(method="dense").astype(int))
    return out


def next_round(conn: sqlite3.Connection, season: str, today: str | None = None) -> int | None:
    """The round to plan for: earliest upcoming unplayed game at or after the latest round with results.

    A postponed game left behind in an older round (or rescheduled to a later date) is ignored.
    """
    g = read_df(conn, "SELECT round, local_date, played FROM games WHERE season = ?", (season,))
    if g.empty or not (g["played"] == 0).any():
        return None
    played = g.loc[g["played"] == 1, "round"]
    floor = played.max() if len(played) else g["round"].min()
    cand = g[(g["played"] == 0) & (g["round"] >= floor)]
    if cand.empty:
        return None
    today = today or date.today().isoformat()
    upcoming = cand[cand["local_date"].fillna("").str[:10] >= today]
    return int((upcoming if len(upcoming) else cand)["round"].min())


def next_unstarted_round(conn: sqlite3.Connection, season: str) -> int | None:
    """The first round at or after next_round with no game played yet (the one to pick a team for)."""
    start = next_round(conn, season)
    if start is None:
        return None
    g = read_df(conn, """SELECT round FROM games WHERE season = ? AND round >= ?
                         GROUP BY round HAVING MAX(played) = 0 ORDER BY round LIMIT 1""", (season, start))
    return int(g["round"].iloc[0]) if len(g) else None


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
