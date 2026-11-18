"""One matchday run: import the export, download new games, fit, score the next round, backtest."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd

from .dvp import possessions
from .fantasy_import import import_export
from .matching import match_players
from .metrics import game_log, played_games
from .paths import overrides_path
from .price_rule import PriceRule, fit_price_rule
from .refresh import RefreshReport, refresh_season
from .settings import Settings
from .slots import next_unstarted_round
from .store import read_df
from .value import build_value_table, team_games
from .xpir import EFFICIENCIES, VOLUME_STATS, XpirModel, fit_xpir, predict_xpir

FIRST_TRAIN_ROUND = 4      # rounds 1-3 only serve as history


@dataclass
class MatchdayResult:
    matchday: int
    round_: int
    rule: PriceRule
    model: XpirModel
    value: pd.DataFrame
    stats: pd.DataFrame
    backtest: pd.DataFrame
    refresh: RefreshReport
    unmatched: int


def _hits(conn, season, r, rule, model, s, log) -> dict:
    """BUY / SELL calls for round r from export r's prices, judged by the rule on the actual PIR."""
    v, _ = build_value_table(conn, season, r, rule, model, s, matchday=r)
    v = v.merge(read_df(conn, "SELECT fantasy_id, player_code FROM player_map"), on="fantasy_id")
    teams = set(team_games(conn, season).query("round == @r")["tv_code"])
    v = v[v["team"].isin(teams)]                    # his team has played round r
    pir = played_games(log)[lambda g: g["round"] == r].groupby("player_code")["pir"].sum()
    actual = v["player_code"].map(pir)
    realised = rule.change(actual, v["price"]).where(actual.notna(), rule.d)
    out = {}
    for name, sign in (("buy", 1), ("sell", -1)):
        sel = v["label"] == name.upper()
        out[f"{name}_n"] = int(sel.sum())
        out[f"{name}_hit"] = float((sign * realised[sel] > 0).mean()) if sel.any() else np.nan
    return out


def backtest(conn: sqlite3.Connection, season: str, rule: PriceRule, first_round: int = 5,
             s: Settings | None = None) -> pd.DataFrame:
    """Per round r >= first_round with games: fit on rounds [4, r), predict r, compare with the actual PIR.

    Hit rates only for rounds whose export (matchday r) is stored, so the prices are known.
    """
    s = s or Settings()
    log = game_log(conn, season)
    poss = possessions(read_df(conn, "SELECT * FROM box_team WHERE season = ?", (season,)))
    played = played_games(log)
    exports = set(read_df(conn, "SELECT matchday FROM snapshots")["matchday"])
    rows = []
    for r in sorted(int(x) for x in set(played["round"]) if x >= first_round):
        model = fit_xpir(log, poss, list(range(FIRST_TRAIN_ROUND, r)))
        games = played[played["round"] == r].drop_duplicates("player_code")
        f = predict_xpir(model, log, poss, r, games[["player_code", "position", "opp_tv", "is_home"]])
        f = f.join(games.set_index("player_code")["pir"])
        f = f[f["games"] > 0]
        row = {"round": r, "n": len(f), "mae_xpir": (f["pir"] - f["xpir"]).abs().mean(),
               "mae_baseline": (f["pir"] - f["pir_avg"]).abs().mean(),
               "buy_n": 0, "buy_hit": np.nan, "sell_n": 0, "sell_hit": np.nan}
        if r in exports:
            row.update(_hits(conn, season, r, rule, model, s, log))
        rows.append(row)
    return pd.DataFrame(rows, columns=["round", "n", "mae_xpir", "mae_baseline", "buy_n", "buy_hit", "sell_n",
                                       "sell_hit"])


def _model_rows(model: XpirModel, rule: PriceRule, round_: int) -> list[tuple[str, object]]:
    half_life = "equal weights" if np.isinf(model.half_life) else model.half_life
    rows = [("Scoring round", round_), ("Price rule source", rule.source), ("Price rule k", rule.k),
            ("Price rule a", rule.a), ("Price rule c", rule.c), ("Price rule d", rule.d),
            ("Price rule players", rule.n), ("Price rule R2", None if np.isnan(rule.r2) else rule.r2),
            ("xPIR alpha", model.alpha), ("xPIR beta", model.beta), ("xPIR home", model.gamma_home),
            ("xPIR bounce-back (delta)", model.delta_bounce), ("Recency half-life (games)", half_life),
            ("Season minutes weight", model.w_season_min), ("Training rows", model.train_rows),
            ("xPIR MAE", None if np.isnan(model.mae) else model.mae),
            ("Season-average MAE", None if np.isnan(model.mae_baseline) else model.mae_baseline)]
    unit = {**dict.fromkeys(VOLUME_STATS, "minutes"), **dict.fromkeys(EFFICIENCIES, "attempts")}
    rows += [(f"Shrink strength {stat}", f"{model.k[stat]:g} {unit[stat]}") for stat in unit]
    return rows


def value_excel_bytes(value_df: pd.DataFrame, stat_df: pd.DataFrame, model: XpirModel, rule: PriceRule,
                      round_: int) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        value_df.to_excel(xl, sheet_name="Value", index=False)
        stat_df.to_excel(xl, sheet_name="Stat analysis", index=False)
        pd.DataFrame(_model_rows(model, rule, round_), columns=["item", "value"]).to_excel(
            xl, sheet_name="Model", index=False)
    return buf.getvalue()


def run_matchday(conn: sqlite3.Connection, export_path: Path, client, s: Settings) -> MatchdayResult:
    """Import the export, download new games, refit the price rule and xPIR, score the next round.

    A malformed export raises ExportFormatError before anything is downloaded. Download failures
    are kept in the result's refresh report.
    """
    md = import_export(conn, export_path)
    report = refresh_season(conn, client, s.season, source="live")
    matching = match_players(conn, s.season, overrides_path())
    rule = fit_price_rule(conn, s.season)
    round_ = next_unstarted_round(conn, s.season)
    if round_ is None:
        raise ValueError("No upcoming round in the schedule.")
    log = game_log(conn, s.season)
    poss = possessions(read_df(conn, "SELECT * FROM box_team WHERE season = ?", (s.season,)))
    model = fit_xpir(log, poss, list(range(FIRST_TRAIN_ROUND, round_)))
    value, stats = build_value_table(conn, s.season, round_, rule, model, s)
    bt = backtest(conn, s.season, rule, s=s)
    return MatchdayResult(md, round_, rule, model, value, stats, bt, report, len(matching.unmatched))
