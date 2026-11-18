"""Expected PIR next round: per-channel volume x efficiency, valued with PIR's own arithmetic.

raw  = expected minutes * sum over channels of (per-minute volume * PIR per unit * opponent factor)
xPIR = alpha + beta * raw + gamma * home + delta * (last game PIR - his earlier average)
Expected minutes, like every rate, are pulled toward his position's value.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .dvp import POSITIONS, dvp
from .metrics import played_games

VOLUME_STATS = ["fga2", "fga3", "fd", "oreb", "dreb", "ast", "stl", "blk", "tov", "blka", "pf"]
EFFICIENCIES = {"p2": ("fgm2", "fga2"), "p3": ("fgm3", "fga3"), "ftp": ("ftm", "fta"), "ftr": ("fta", "fd")}
FIXED_UNIT = {"oreb": 1.0, "dreb": 1.0, "ast": 1.0, "stl": 1.0, "blk": 1.0,
              "tov": -1.0, "blka": -1.0, "pf": -1.0}
LEAGUE = "League"          # prior row for players without a known position
OPP_STATS = VOLUME_STATS   # the opponent's Defense-vs-Position index scales each volume
SUM_COLS = [*VOLUME_STATS, "fgm2", "fgm3", "ftm", "fta", "minutes"]

VOLUME_GRID = (0, 50, 100, 200, 400, 800, 1600)     # shrink strength in minutes
EFFICIENCY_GRID = (0, 5, 10, 20, 40, 80, 160)        # shrink strength in attempts
MINUTES_GRID = (0, .25, .5, .75, 1)                  # weight of season minutes vs last 3
MIN_SHRINK_GRID = (0, .5, 1, 2, 4)                   # minutes shrink toward the position median, in games
HALF_LIVES = (3, 6, 12, float("inf"))                # recency half-life in games


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
    rows = {}
    for name, g in [*p.groupby("position"), (LEAGUE, p)]:
        tot = g[SUM_COLS].sum()
        row = {f"r_{s}": tot[s] / tot["minutes"] if tot["minutes"] > 0 else np.nan for s in VOLUME_STATS}
        row.update({e: tot[m] / tot[a] if tot[a] > 0 else np.nan for e, (m, a) in EFFICIENCIES.items()})
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
    ws = p[SUM_COLS].mul(w, axis=0).groupby(p["player_code"]).sum()
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


def _shrink_minutes(own: pd.Series, games: pd.Series, median: pd.Series, m: float) -> pd.Series:
    """His expected minutes as if he had also played m games at his position's median minutes."""
    den = games + m
    return ((games * own + m * median) / den.where(den > 0, 1)).where(den > 0, median)


@dataclass
class XpirModel:
    """Every fitted xPIR number. The defaults are the unfitted model (train_rows == 0)."""
    k: dict[str, float] = field(default_factory=lambda: {**dict.fromkeys(VOLUME_STATS, 100.0),
                                                         **dict.fromkeys(EFFICIENCIES, 20.0)})
    half_life: float = float("inf")
    w_season_min: float = 0.5
    minutes_shrink: float = 1.0
    alpha: float = 0.0
    beta: float = 1.0
    gamma_home: float = 0.0
    delta_bounce: float = 0.0
    train_rows: int = 0
    mae: float = float("nan")
    mae_baseline: float = float("nan")

    def calibrate(self, f: pd.DataFrame) -> pd.Series:
        """xPIR from features: alpha + beta*raw + gamma*home + delta*last_dev, floored at 0."""
        x = self.alpha + self.beta * f["raw"] + self.gamma_home * f["home"] + self.delta_bounce * f["last_dev"]
        return x.clip(lower=0)


@dataclass
class _Before:
    """What a round's prediction may use: games before it, position priors, opponent indices."""
    log: pd.DataFrame
    priors: pd.DataFrame
    opp: pd.DataFrame


def _before(log: pd.DataFrame, poss: pd.DataFrame, round_: int) -> _Before:
    before = log[log["round"] < round_]
    has_positions = played_games(before)["position"].isin(POSITIONS).any()
    opp = (dvp(before, poss, 0.0, basis="per40", shrink_minutes=400)[[f"idx_{s}" for s in OPP_STATS]]
           if has_positions else pd.DataFrame(columns=[f"idx_{s}" for s in OPP_STATS], dtype=float))
    return _Before(before, player_priors(before), opp)


def _features(b: _Before, fixtures: pd.DataFrame, k: dict[str, float], half_life: float,
              w_season_min: float, minutes_shrink: float) -> pd.DataFrame:
    fx = fixtures.drop_duplicates("player_code").set_index("player_code")
    t = channel_table(b.log, k, half_life).reindex(fx.index)
    position = fx["position"].where(fx["position"].notna(), t["position"])
    new = t["games"].isna()
    if new.any():                          # no games before the round: his position's prior
        fill = prior_rows(b.priors, position[new])
        cols = [c for c in fill.columns if c in t.columns]
        t.loc[new, cols] = fill[cols]
        for c in ("min_w", "min_season", "min_last3"):
            t.loc[new, c] = fill["min_median"]
        t.loc[new, ["games", "last_dev"]] = 0
    t["position"] = position
    t["opp_tv"] = fx["opp_tv"]
    t["home"] = fx["is_home"].astype(float)
    own = w_season_min * t["min_season"] + (1 - w_season_min) * t["min_last3"]
    median = prior_rows(b.priors, position)["min_median"]
    t["xmin"] = _shrink_minutes(own, t["games"], median, minutes_shrink)
    keys = pd.MultiIndex.from_arrays([t["opp_tv"], t["position"]])
    idx = b.opp.reindex(keys).set_axis(t.index) if len(b.opp) else b.opp.reindex(t.index)
    for s in OPP_STATS:
        t[f"opp_{s}"] = (1 + idx[f"idx_{s}"]).clip(0.5, 1.5).fillna(1.0)
    t["raw"] = t["xmin"] * sum(t[f"r_{s}"] * t[f"v_{s}"] * t[f"opp_{s}"] for s in VOLUME_STATS)
    return t


def features_for_round(log: pd.DataFrame, poss: pd.DataFrame, round_: int, fixtures: pd.DataFrame,
                       k: dict[str, float], half_life: float, w_season_min: float,
                       minutes_shrink: float) -> pd.DataFrame:
    """Per fixture player (index player_code): raw xPIR and its pieces, from games before round_ only.

    fixtures: player_code, position, opp_tv, is_home.
    """
    return _features(_before(log, poss, round_), fixtures, k, half_life, w_season_min, minutes_shrink)


def predict_xpir(model: XpirModel, log: pd.DataFrame, poss: pd.DataFrame, round_: int,
                 fixtures: pd.DataFrame) -> pd.DataFrame:
    f = features_for_round(log, poss, round_, fixtures, model.k, model.half_life, model.w_season_min,
                           model.minutes_shrink)
    return f.assign(xpir=model.calibrate(f))


def _fixtures(games: pd.DataFrame) -> pd.DataFrame:
    return games[["player_code", "position", "opp_tv", "is_home"]]


def _shrink_rows(befores: dict[int, _Before], targets: dict[int, pd.DataFrame]) -> pd.DataFrame:
    """Per (round, player with history): unweighted history sums, his round totals and his prior."""
    out = []
    for r, b in befores.items():
        hist = played_games(b.log).groupby("player_code")[SUM_COLS].sum()
        tgt = targets[r].set_index("player_code")
        common = tgt.index.intersection(hist.index)
        prior = prior_rows(b.priors, tgt.loc[common, "position"])
        out.append(pd.concat({"hist": hist.loc[common], "tgt": tgt.loc[common, SUM_COLS], "prior": prior},
                             axis=1))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def _best(grid, hist_x, hist_n, prior, y, weight) -> float:
    """The grid value whose shrunk history best predicts y (weighted squared error)."""
    def err(k):
        den = hist_n + k
        pred = np.where(den > 0, (hist_x + prior * k) / den.where(den > 0, 1), prior)
        return float((weight * (y - pred) ** 2).sum())
    return float(min(grid, key=err))


def _fit_k(rows: pd.DataFrame) -> dict[str, float]:
    h, t, p = rows["hist"], rows["tgt"], rows["prior"]
    k = {s: _best(VOLUME_GRID, h[s], h["minutes"], p[f"r_{s}"], t[s] / t["minutes"], t["minutes"])
         for s in VOLUME_STATS}
    for e, (made, att) in EFFICIENCIES.items():
        ok = t[att] > 0
        k[e] = _best(EFFICIENCY_GRID, h.loc[ok, made], h.loc[ok, att], p.loc[ok, e],
                     t.loc[ok, made] / t.loc[ok, att], t.loc[ok, att])
    return k


def _fit_minutes(befores: dict[int, _Before], targets: dict[int, pd.DataFrame]) -> tuple[float, float]:
    """(season minutes weight, minutes shrink), each picked by squared error on his next game's minutes."""
    zero = dict.fromkeys([*VOLUME_STATS, *EFFICIENCIES], 0.0)
    parts = []
    for r, b in befores.items():
        d = (targets[r].set_index("player_code")[["minutes", "position"]]
             .join(channel_table(b.log, zero, float("inf"))[["games", "min_season", "min_last3"]], how="inner"))
        parts.append(d.assign(median=prior_rows(b.priors, d["position"])["min_median"]))
    m = pd.concat(parts)

    def own(w):
        return w * m["min_season"] + (1 - w) * m["min_last3"]

    w = float(min(MINUTES_GRID, key=lambda w: float(((m["minutes"] - own(w)) ** 2).sum())))
    shrink = float(min(MIN_SHRINK_GRID, key=lambda s: float(
        ((m["minutes"] - _shrink_minutes(own(w), m["games"], m["median"], s)) ** 2).sum())))
    return w, shrink


def _calibration(rows: pd.DataFrame) -> list[float]:
    x = np.column_stack([np.ones(len(rows)), rows["raw"], rows["home"], rows["last_dev"]]).astype(float)
    coef, *_ = np.linalg.lstsq(x, rows["pir"].to_numpy(float), rcond=None)
    return [float(c) for c in coef]


def fit_xpir(log: pd.DataFrame, poss: pd.DataFrame, rounds: list[int]) -> XpirModel:
    """Fit every xPIR number on the given rounds, each predicted only from games before it.

    Per-stat shrink strengths, the minutes weight and the minutes shrink are fitted first (equal game
    weights), then the half-life is picked by the calibrated MAE. Training rows: players who played
    the round and had played before it. With no such rows the unfitted XpirModel() is returned.
    """
    played = played_games(log)
    targets = {int(r): g.drop_duplicates("player_code")
               for r, g in played[played["round"].isin(rounds)].groupby("round")}
    befores = {r: _before(log, poss, r) for r in targets}
    shrink = _shrink_rows(befores, targets)
    if shrink.empty:
        return XpirModel()
    k = _fit_k(shrink)
    w, shrink_min = _fit_minutes(befores, targets)

    best = None
    for hl in HALF_LIVES:
        rows = pd.concat([_features(befores[r], _fixtures(g), k, hl, w, shrink_min)
                          .join(g.set_index("player_code")["pir"]) for r, g in targets.items()])
        rows = rows[rows["games"] > 0]
        m = XpirModel(k, hl, w, shrink_min, *_calibration(rows), train_rows=len(rows))
        m.mae = float((rows["pir"] - m.calibrate(rows)).abs().mean())
        m.mae_baseline = float((rows["pir"] - rows["pir_avg"]).abs().mean())
        if best is None or m.mae < best.mae:
            best = m
    return best
