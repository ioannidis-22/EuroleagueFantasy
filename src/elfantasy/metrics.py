"""The season's game log: one row per player per played game, with PIR and context."""
from __future__ import annotations

import sqlite3

import pandas as pd

from .pir import pir_box
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
