"""Expected PIR next round: per-channel volume x efficiency, valued with PIR's own arithmetic.

xPIR(raw) = expected minutes * sum over channels of (per-minute volume * PIR per unit * opponent factor)
"""
from __future__ import annotations

import pandas as pd

from .metrics import played_games

VOLUME_STATS = ["fga2", "fga3", "fd", "oreb", "dreb", "ast", "stl", "blk", "tov", "blka", "pf"]
EFFICIENCIES = {"p2": ("fgm2", "fga2"), "p3": ("fgm3", "fga3"), "ftp": ("ftm", "fta"), "ftr": ("fta", "fd")}
FIXED_UNIT = {"oreb": 1.0, "dreb": 1.0, "ast": 1.0, "stl": 1.0, "blk": 1.0,
              "tov": -1.0, "blka": -1.0, "pf": -1.0}
LEAGUE = "League"          # prior row for players without a known position


def foul_value(fta_per_fd, ft_pct):
    """PIR of one foul drawn: +1 for the foul, then each free throw is +1 made / -1 missed."""
    return 1 + fta_per_fd * (2 * ft_pct - 1)


def unit_values(p2, p3, ftp, ftr) -> dict:
    """PIR per unit of each volume stat. A 2PA is +2 made / -1 missed, a 3PA +3 / -1."""
    return {"fga2": 3 * p2 - 1, "fga3": 4 * p3 - 1, "fd": foul_value(ftr, ftp), **FIXED_UNIT}


def _with_values(t: pd.DataFrame) -> pd.DataFrame:
    v = unit_values(t["p2"], t["p3"], t["ftp"], t["ftr"])
    for s in VOLUME_STATS:
        t[f"v_{s}"] = v[s]
    t["pir_per_min"] = sum(t[f"r_{s}"] * t[f"v_{s}"] for s in VOLUME_STATS)
    return t


def player_priors(log_before: pd.DataFrame) -> pd.DataFrame:
    """Pooled per-minute rates and efficiencies per position, plus a league-wide row."""
    p = played_games(log_before)
    groups = [*p.groupby("position"), (LEAGUE, p)]
    rows = {}
    for name, g in groups:
        tot = g[[*VOLUME_STATS, "fgm2", "fgm3", "ftm", "fta", "minutes"]].sum()
        row = {f"r_{s}": tot[s] / tot["minutes"] for s in VOLUME_STATS}
        row.update({e: tot[m] / tot[a] if tot[a] > 0 else float("nan") for e, (m, a) in EFFICIENCIES.items()})
        row["min_median"] = g["minutes"].median()
        rows[name] = row
    pri = pd.DataFrame.from_dict(rows, orient="index")
    for e in EFFICIENCIES:
        pri[e] = pri[e].fillna(pri.loc[LEAGUE, e])
    return _with_values(pri)


def prior_rows(pri: pd.DataFrame, positions: pd.Series) -> pd.DataFrame:
    """The prior row for each position (league row when unknown), indexed like `positions`."""
    key = positions.where(positions.isin(pri.index), LEAGUE)
    return pri.reindex(key).set_axis(positions.index)


def channel_table(log_before: pd.DataFrame, k: dict[str, float], half_life: float) -> pd.DataFrame:
    """Per player: shrunk per-minute volumes, efficiencies, unit values and minutes from his games.

    Game weight 0.5 ** (age / half_life), age 0 = his latest game. Each rate is pulled toward his
    position's pooled rate by k[stat] minutes (volumes) or k[e] attempts (efficiencies).
    """
    p = played_games(log_before).sort_values(["local_date", "game_code"])
    by = p.groupby("player_code")
    w = 0.5 ** (by.cumcount(ascending=False) / half_life)
    cols = [*VOLUME_STATS, "fgm2", "fgm3", "ftm", "fta", "minutes"]
    ws = p[cols].mul(w, axis=0).groupby(p["player_code"]).sum()
    n = by.size()
    last = by["pir"].last()

    t = pd.DataFrame({"position": by["position"].first(), "games": n,
                      "min_w": ws["minutes"] / w.groupby(p["player_code"]).sum(),
                      "min_season": by["minutes"].mean(),
                      "min_last3": p.groupby("player_code").tail(3).groupby("player_code")["minutes"].mean(),
                      "pir_avg": by["pir"].mean(),
                      "last_dev": ((last - (by["pir"].sum() - last) / (n - 1)).where(n >= 2, 0.0))})
    prior = prior_rows(player_priors(log_before), t["position"])
    for s in VOLUME_STATS:
        t[f"r_{s}"] = (ws[s] + prior[f"r_{s}"] * k[s]) / (ws["minutes"] + k[s])
    for e, (made, att) in EFFICIENCIES.items():
        den = ws[att] + k[e]
        t[e] = ((ws[made] + prior[e] * k[e]) / den).where(den > 0, prior[e])
    return _with_values(t)
