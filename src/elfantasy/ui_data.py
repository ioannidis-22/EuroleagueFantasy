"""Cached data access for the Streamlit pages (keyed by DB path so tests stay isolated)."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pandas as pd
import streamlit as st

from . import paths
from .dvp import dvp, possessions
from .metrics import effective_win_bonus, game_log, player_summary
from .settings import Settings, load_settings
from .store import connect, read_df


def db() -> str:
    return str(paths.db_path())


@st.cache_resource
def get_conn(db_path: str):
    return connect(Path(db_path))


def conn():
    return get_conn(db())


def settings() -> Settings:
    return load_settings(paths.settings_path())


@st.cache_data(show_spinner=False)
def load_log(db_path: str, season: str) -> pd.DataFrame:
    return game_log(get_conn(db_path), season)


@st.cache_data(show_spinner=False)
def load_summary(db_path: str, season: str, settings_dict: dict) -> pd.DataFrame:
    s = Settings(**settings_dict)
    return player_summary(load_log(db_path, season), s)


@st.cache_data(show_spinner=False)
def load_win_bonus(db_path: str, settings_dict: dict) -> float:
    s = Settings(**settings_dict)
    return effective_win_bonus(get_conn(db_path), s)


@st.cache_data(show_spinner=False)
def load_dvp(db_path: str, season: str, window: str, role: str, basis: str,
             win_bonus: float, shrink: float) -> pd.DataFrame:
    log = load_log(db_path, season)
    if log.empty:
        return pd.DataFrame()
    poss = possessions(read_df(get_conn(db_path), "SELECT * FROM box_team WHERE season = ?", (season,)))
    return dvp(log, poss, win_bonus, window=window, role=role, basis=basis, shrink_minutes=shrink)


def summary(season: str | None = None) -> pd.DataFrame:
    s = settings()
    return load_summary(db(), season or s.season, asdict(s))


def win_bonus() -> float:
    return load_win_bonus(db(), asdict(settings()))


def latest_matchday() -> int | None:
    v = read_df(conn(), "SELECT MAX(matchday) md FROM snapshots")["md"].iloc[0]
    return None if pd.isna(v) else int(v)


def clear_caches() -> None:
    st.cache_data.clear()


@st.cache_data(show_spinner=False)
def load_player_table(db_path: str, season: str, matchday: int, settings_dict: dict) -> pd.DataFrame:
    from .views import player_table as build
    s = Settings(**settings_dict)
    wb = load_win_bonus(db_path, settings_dict)
    tab = load_dvp(db_path, season, "season", "all", "per40", wb, s.dvp_shrink_minutes)
    return build(get_conn(db_path), season, matchday, load_summary(db_path, season, settings_dict), tab)


def player_table() -> pd.DataFrame:
    md = latest_matchday()
    if md is None:
        return pd.DataFrame()
    s = settings()
    return load_player_table(db(), s.season, md, asdict(s))
