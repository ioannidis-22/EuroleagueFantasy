"""Defense vs Position: what each team concedes to Guards, Forwards and Centers."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .pir import BOX_COMPONENTS

POSITIONS = ("Guard", "Forward", "Center")
DVP_COMPONENTS = BOX_COMPONENTS + ["pir", "fpt"]
SHOTS = {"fg2_pct": ("fgm2", "fga2"), "fg3_pct": ("fgm3", "fga3"), "ft_pct": ("ftm", "fta")}
GAME_KEY = ["season", "game_code"]


def possessions(box_team: pd.DataFrame) -> pd.DataFrame:
    p = box_team.assign(poss=box_team["fga2"] + box_team["fga3"] + 0.44 * box_team["fta"]
                        - box_team["oreb"] + box_team["tov"])
    return p.groupby(GAME_KEY, as_index=False)["poss"].mean()


def _window_games(log: pd.DataFrame, window: str) -> pd.DataFrame:
    """(def_tv, season, game_code) pairs in the window, judged from the defending team's side."""
    g = (log.assign(def_tv=log["opp_tv"], def_home=1 - log["is_home"])
         [["def_tv", "season", "game_code", "local_date", "def_home"]].drop_duplicates(["def_tv", *GAME_KEY]))
    if window == "home":
        g = g[g["def_home"] == 1]
    elif window == "away":
        g = g[g["def_home"] == 0]
    elif window == "last5":
        g = g.sort_values("local_date").groupby("def_tv", group_keys=False).tail(5)
    elif window != "season":
        raise ValueError(f"unknown window {window!r}")
    return g[["def_tv", *GAME_KEY]]


def dvp(log: pd.DataFrame, poss: pd.DataFrame, win_bonus: float, window: str = "season",
        role: str = "all", basis: str = "game", shrink_minutes: float = 400) -> pd.DataFrame:
    played = log[(log["dnp"] == 0) & log["position"].isin(POSITIONS)].copy()
    played["fpt"] = played["pir"] + win_bonus * played["won"]
    played["def_tv"] = played["opp_tv"]
    games = _window_games(played, window)
    if role == "starters":
        played = played[played["is_starter"] == 1]
    elif role == "bench":
        played = played[played["is_starter"] == 0]
    elif role != "all":
        raise ValueError(f"unknown role {role!r}")
    played = played.merge(games, on=["def_tv", *GAME_KEY])

    sums = ["minutes", *DVP_COMPONENTS]
    # one row per (def team, position, game), zero-filled so games without that position count
    grid = games.merge(pd.DataFrame({"position": POSITIONS}), how="cross")
    per_game = (played.groupby(["def_tv", "position", *GAME_KEY])[sums].sum().reset_index())
    per_game = grid.merge(per_game, on=["def_tv", "position", *GAME_KEY], how="left").fillna({c: 0 for c in sums})
    per_game = per_game.merge(poss, on=GAME_KEY, how="left")

    tot = per_game.groupby(["def_tv", "position"])[sums].sum()
    n_games = per_game.groupby(["def_tv", "position"]).size().rename("games")
    tot = tot[tot["minutes"] > 0]
    n_games = n_games.loc[tot.index]

    if basis == "game":
        out = tot[DVP_COMPONENTS].div(n_games, axis=0)
    elif basis == "per40":
        out = tot[DVP_COMPONENTS].div(tot["minutes"], axis=0) * 40
    elif basis == "per100":
        scaled = per_game[DVP_COMPONENTS].div(per_game["poss"], axis=0) * 100
        out = (scaled.assign(def_tv=per_game["def_tv"], position=per_game["position"])
               .groupby(["def_tv", "position"])[DVP_COMPONENTS].mean().loc[tot.index])
    else:
        raise ValueError(f"unknown basis {basis!r}")
    out = out.copy()
    out["games"] = n_games
    out["minutes"] = tot["minutes"]

    # shrunk per-40 index vs the league rate for the same position
    league = tot.groupby(level="position")[sums].sum()
    league40 = league[DVP_COMPONENTS].div(league["minutes"], axis=0) * 40
    rate40 = tot[DVP_COMPONENTS].div(tot["minutes"], axis=0) * 40
    lg = league40.reindex(tot.index.get_level_values("position")).set_axis(tot.index)
    k = shrink_minutes
    shrunk = (rate40.mul(tot["minutes"], axis=0) + lg * k).div(tot["minutes"] + k, axis=0)
    idx = (shrunk / lg.replace(0, np.nan)) - 1
    for c in DVP_COMPONENTS:
        out[f"idx_{c}"] = idx[c]

    for name, (made, att) in SHOTS.items():
        pct = tot[made] / tot[att].replace(0, np.nan)
        lg_pct = (league[made] / league[att].replace(0, np.nan)).reindex(
            tot.index.get_level_values("position")).set_axis(tot.index)
        out[name] = pct
        out[f"idx_{name}"] = pct / lg_pct - 1

    out["rank_pir"] = out.groupby(level="position")["idx_pir"].rank(ascending=False, method="min").astype(int)
    return out.sort_index()

