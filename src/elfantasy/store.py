"""SQLite storage: schema and small read/write helpers."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

_BOX = ("pts, fgm2, fga2, fgm3, fga3, ftm, fta, oreb, dreb, ast, stl, tov, blk, blka, pf, fd")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS snapshots(
    matchday INTEGER PRIMARY KEY, reference_matchdays TEXT, imported_at TEXT, file_hash TEXT);
CREATE TABLE IF NOT EXISTS fantasy_players(
    matchday INTEGER, fantasy_id TEXT, name TEXT, surname TEXT, position TEXT, team TEXT,
    price REAL, plus REAL, fpt REAL, pts REAL, reb REAL, ast REAL, stl REAL, tov REAL, blk REAL,
    blka REAL, fd REAL, pf REAL, fg_missed REAL, ft_missed REAL,
    PRIMARY KEY(matchday, fantasy_id));
CREATE TABLE IF NOT EXISTS fantasy_coaches(
    matchday INTEGER, name TEXT, surname TEXT, team TEXT, price REAL, plus REAL, fpt REAL,
    win_1_10 REAL, win_11_20 REAL, win_20 REAL, win_ot REAL,
    loss_1_10 REAL, loss_11_20 REAL, loss_20 REAL, loss_ot REAL,
    PRIMARY KEY(matchday, team));
CREATE TABLE IF NOT EXISTS teams(club_code TEXT PRIMARY KEY, tv_code TEXT UNIQUE, name TEXT);
CREATE TABLE IF NOT EXISTS games(
    season TEXT, game_code INTEGER, round INTEGER, phase TEXT, local_date TEXT, utc_date TEXT,
    home_club TEXT, away_club TEXT, home_score INTEGER, away_score INTEGER, played INTEGER,
    PRIMARY KEY(season, game_code));
CREATE TABLE IF NOT EXISTS box_player(
    season TEXT, game_code INTEGER, player_code TEXT, club_code TEXT, is_starter INTEGER,
    minutes REAL, dnp INTEGER, {_BOX}, pir_official REAL,
    PRIMARY KEY(season, game_code, player_code));
CREATE TABLE IF NOT EXISTS box_team(
    season TEXT, game_code INTEGER, club_code TEXT, {_BOX},
    PRIMARY KEY(season, game_code, club_code));
CREATE TABLE IF NOT EXISTS el_players(
    season TEXT, player_code TEXT, club_code TEXT, name TEXT, position TEXT,
    PRIMARY KEY(season, player_code, club_code));
CREATE TABLE IF NOT EXISTS player_map(fantasy_id TEXT PRIMARY KEY, player_code TEXT, method TEXT);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.executescript(SCHEMA)
    return conn


def read_df(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn, params=params)


def _insert(conn: sqlite3.Connection, table: str, df: pd.DataFrame, verb: str) -> None:
    if df.empty:
        return
    cols = list(df.columns)
    sql = f"{verb} INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
    rows = [tuple(None if pd.isna(v) else (v.item() if hasattr(v, "item") else v) for v in r)
            for r in df.itertuples(index=False, name=None)]
    conn.executemany(sql, rows)


def replace_rows(conn: sqlite3.Connection, table: str, df: pd.DataFrame,
                 where: dict[str, object] | None) -> None:
    with conn:
        if where is not None:
            clause = " AND ".join(f"{k} = ?" for k in where) or "1=1"
            conn.execute(f"DELETE FROM {table} WHERE {clause}", tuple(where.values()))
        _insert(conn, table, df, "INSERT")


def upsert_rows(conn: sqlite3.Connection, table: str, df: pd.DataFrame) -> None:
    with conn:
        _insert(conn, table, df, "INSERT OR REPLACE")
