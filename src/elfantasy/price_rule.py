"""The fantasy game's price rule, measured from consecutive exports.

Played:        change = k * (round PIR - break_even(price)),  break_even = a * price + c
Didn't play:   change = d
Export matchday N carries the prices after round N-1, so the move from export N-1 to N comes
from round N-1's PIR.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .metrics import game_log, played_games
from .store import read_df


@dataclass(frozen=True)
class PriceRule:
    k: float = 0.042
    a: float = 1.14
    c: float = -1.0
    d: float = -0.06
    n: int = 0
    r2: float = float("nan")
    source: str = "default"

    def break_even(self, price):
        return self.a * price + self.c

    def change(self, pir, price):
        return self.k * (pir - self.break_even(price))


def _price_moves(conn: sqlite3.Connection, season: str) -> pd.DataFrame:
    """One row per matched player per stored export pair (N-1, N): price_prev, dp and round N-1 PIR
    (NaN when he didn't play)."""
    mds = set(read_df(conn, "SELECT matchday FROM snapshots")["matchday"])
    pairs = sorted((m - 1, m) for m in mds if m - 1 in mds)
    cols = ["matchday", "player_code", "price_prev", "dp", "pir"]
    if not pairs:
        return pd.DataFrame(columns=cols)
    fp = read_df(conn, "SELECT matchday, fantasy_id, price FROM fantasy_players")
    pm = read_df(conn, "SELECT fantasy_id, player_code FROM player_map")
    round_pir = played_games(game_log(conn, season)).groupby(["round", "player_code"])["pir"].sum()
    out = []
    for prev, cur in pairs:
        m = (fp[fp["matchday"] == prev].merge(fp[fp["matchday"] == cur], on="fantasy_id",
                                               suffixes=("_prev", ""))
             .merge(pm, on="fantasy_id"))
        m["dp"] = m["price"] - m["price_prev"]
        m["pir"] = round_pir.reindex(pd.MultiIndex.from_arrays(
            [np.full(len(m), prev), m["player_code"]])).to_numpy()
        out.append(m[cols])
    return pd.concat(out, ignore_index=True)


def fit_price_rule(conn: sqlite3.Connection, season: str, min_rows: int = 30) -> PriceRule:
    moves = _price_moves(conn, season)
    played = moves[moves["pir"].notna()]
    if len(played) < min_rows:
        return PriceRule()
    x = np.column_stack([np.ones(len(played)), played["pir"], played["price_prev"]]).astype(float)
    y = played["dp"].to_numpy(float)
    (b0, b1, b2), *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ np.array([b0, b1, b2])
    r2 = 1 - (resid ** 2).sum() / ((y - y.mean()) ** 2).sum()
    idle = moves.loc[moves["pir"].isna(), "dp"]
    d = float(idle.mean()) if len(idle) else PriceRule().d
    return PriceRule(k=float(b1), a=float(-b2 / b1), c=float(-b0 / b1), d=d, n=len(played),
                     r2=float(r2), source="fitted")
