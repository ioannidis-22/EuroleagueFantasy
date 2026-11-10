"""PIR (Performance Index Rating) and fantasy points."""
from __future__ import annotations

import pandas as pd

BOX_COMPONENTS = ["pts", "fgm2", "fga2", "fgm3", "fga3", "ftm", "fta", "oreb", "dreb", "ast",
                  "stl", "tov", "blk", "blka", "pf", "fd"]


def pir_box(df: pd.DataFrame) -> pd.Series:
    """PIR from box-score columns."""
    plus = df["pts"] + df["oreb"] + df["dreb"] + df["ast"] + df["stl"] + df["blk"] + df["fd"]
    misses = (df["fga2"] - df["fgm2"]) + (df["fga3"] - df["fgm3"]) + (df["fta"] - df["ftm"])
    return plus - misses - df["tov"] - df["blka"] - df["pf"]


def pir_export(df: pd.DataFrame) -> pd.Series:
    """PIR from the fantasy export's per-game average columns."""
    plus = df["pts"] + df["reb"] + df["ast"] + df["stl"] + df["blk"] + df["fd"]
    return plus - df["tov"] - df["blka"] - df["pf"] - df["fg_missed"] - df["ft_missed"]


def fpt(pir: pd.Series, won: pd.Series, win_bonus: float) -> pd.Series:
    """Fantasy points: PIR plus the win bonus when the player's team won (won is 0/1)."""
    return pir + win_bonus * won
