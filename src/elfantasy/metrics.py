"""Per-player metrics: game log, form, consistency, value, and the win-bonus estimate."""
from __future__ import annotations

import json
import sqlite3

import numpy as np
import pandas as pd

from .pir import BOX_COMPONENTS, pir_box
from .settings import Settings
from .store import read_df

_LOG_SQL = """
WITH latest AS (SELECT MAX(matchday) md FROM snapshots),
fan AS (SELECT pm.player_code, MIN(pm.fantasy_id) fantasy_id,
               MIN(fp.name || ' ' || fp.surname) fname, MIN(fp.position) fpos
        FROM player_map pm
        JOIN fantasy_players fp ON fp.fantasy_id = pm.fantasy_id AND fp.matchday = (SELECT md FROM latest)
        GROUP BY pm.player_code),
elp AS (SELECT player_code, MIN(name) ename, MIN(position) epos FROM el_players GROUP BY player_code)
SELECT b.*, g.round, g.local_date,
       CASE WHEN b.club_code = g.home_club THEN 1 ELSE 0 END AS is_home,
       CASE WHEN b.club_code = g.home_club THEN g.home_score - g.away_score
            ELSE g.away_score - g.home_score END AS margin,
       CASE WHEN b.club_code = g.home_club THEN g.away_club ELSE g.home_club END AS opp_club,
       fan.fantasy_id, COALESCE(fan.fname, elp.ename) AS name, COALESCE(fan.fpos, elp.epos) AS position
FROM box_player b
JOIN games g ON g.season = b.season AND g.game_code = b.game_code AND g.played = 1
LEFT JOIN fan ON fan.player_code = b.player_code
LEFT JOIN elp ON elp.player_code = b.player_code
WHERE b.season = ?
"""


def game_log(conn: sqlite3.Connection, season: str) -> pd.DataFrame:
    log = read_df(conn, _LOG_SQL, (season,))
    tv = dict(read_df(conn, "SELECT club_code, tv_code FROM teams").itertuples(index=False, name=None))
    log["team_tv"] = log["club_code"].map(tv)
    log["opp_tv"] = log["opp_club"].map(tv)
    log["won"] = (log["margin"] > 0).astype(int)
    log["pir"] = pir_box(log) if len(log) else pd.Series(dtype=float)
    return log.sort_values(["local_date", "game_code", "player_code"]).reset_index(drop=True)


def _negatives(df: pd.DataFrame) -> pd.Series:
    misses = (df["fga2"] - df["fgm2"]) + (df["fga3"] - df["fgm3"]) + (df["fta"] - df["ftm"])
    return misses + df["tov"] + df["blka"] + df["pf"]


SUMMARY_COLS = ["games", "dnp_rate", "min_avg", "min_last5", "pir_avg", "pir_last3", "pir_last5",
                "form_trend", "pir_per30", "p20", "p80", "sd", "boom_rate", "bust_rate",
                "scoring", "rebounding", "playmaking", "defense", "negatives"]


def _summarize(g: pd.DataFrame, s: Settings) -> dict:
    total = len(g)
    played = g[g["dnp"] == 0].sort_values("local_date")
    n = len(played)
    out = dict.fromkeys(SUMMARY_COLS, np.nan)
    out.update(games=n, dnp_rate=(total - n) / total if total else np.nan, form_trend=None)
    if n == 0:
        return out
    pir = played["pir"].astype(float)
    mins = played["minutes"].astype(float)
    avg, last5 = pir.mean(), pir.tail(5).mean()
    diff = last5 - avg
    out.update(
        min_avg=mins.mean(), min_last5=mins.tail(5).mean(), pir_avg=avg, pir_last3=pir.tail(3).mean(),
        pir_last5=last5,
        form_trend="up" if diff >= s.form_threshold else ("down" if diff <= -s.form_threshold else "flat"),
        pir_per30=pir.sum() / mins.sum() * 30 if mins.sum() > 0 else np.nan,
        p20=float(np.percentile(pir, 20)), p80=float(np.percentile(pir, 80)),
        sd=pir.std(ddof=1) if n > 1 else np.nan,
        boom_rate=(pir >= s.boom).mean(), bust_rate=(pir < s.bust).mean(),
        scoring=played["pts"].mean(), rebounding=(played["oreb"] + played["dreb"]).mean(),
        playmaking=(played["ast"] + played["fd"]).mean(), defense=(played["stl"] + played["blk"]).mean(),
        negatives=_negatives(played).mean(),
    )
    return out


def player_summary(log: pd.DataFrame, s: Settings) -> pd.DataFrame:
    rows = {code: _summarize(g, s) for code, g in log.groupby("player_code", sort=False)}
    out = pd.DataFrame.from_dict(rows, orient="index", columns=SUMMARY_COLS)
    out.index.name = "player_code"
    return out


def value_table(conn: sqlite3.Connection, matchday: int) -> pd.DataFrame:
    v = read_df(conn, """SELECT fantasy_id, name, surname, team, position, price, plus, fpt
                         FROM fantasy_players WHERE matchday = ?""", (matchday,))
    v["fpt_per_credit"] = v["fpt"] / v["price"]
    return v


def price_history(conn: sqlite3.Connection, fantasy_id: str) -> pd.DataFrame:
    return read_df(conn, """SELECT matchday, price, fpt FROM fantasy_players
                            WHERE fantasy_id = ? ORDER BY matchday""", (str(fantasy_id),))


def estimate_win_bonus(conn: sqlite3.Connection, season: str, matchday: int) -> float | None:
    snap = read_df(conn, "SELECT reference_matchdays FROM snapshots WHERE matchday = ?", (matchday,))
    if snap.empty:
        return None
    reference = set(json.loads(snap["reference_matchdays"].iloc[0]))
    rounds = read_df(conn, """SELECT round FROM games WHERE season = ?
                              GROUP BY round HAVING MIN(played) = 1""", (season,))
    usable = reference & set(rounds["round"].astype(int))
    log = game_log(conn, season)
    log = log[log["round"].isin(usable) & (log["dnp"] == 0) & log["fantasy_id"].notna()]
    fpt = read_df(conn, "SELECT fantasy_id, fpt FROM fantasy_players WHERE matchday = ?", (matchday,))
    agg = log.groupby("fantasy_id").agg(games=("pir", "size"), pir=("pir", "mean"), share=("won", "mean"))
    agg = agg[agg["games"] >= 3].join(fpt.set_index("fantasy_id"), how="inner").dropna(subset=["fpt"])
    if len(agg) < 20:
        return None
    gap = agg["fpt"] - agg["pir"]
    denom = (agg["share"] ** 2).sum()
    return float((gap * agg["share"]).sum() / denom) if denom > 0 else None


def effective_win_bonus(conn: sqlite3.Connection, s: Settings) -> float:
    if s.win_bonus is not None:
        return float(s.win_bonus)
    md = read_df(conn, "SELECT MAX(matchday) md FROM snapshots")["md"].iloc[0]
    if pd.isna(md):
        return 0.0
    est = estimate_win_bonus(conn, s.season, int(md))
    return est if est is not None else 0.0
