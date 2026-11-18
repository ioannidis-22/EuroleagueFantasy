"""BUY / HOLD / SELL by expected price change next round.

value = P(play) * k * (xPIR - break_even(price)) + (1 - P(play)) * d,   ROI = value / price
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from .dvp import possessions
from .metrics import game_log, played_games
from .price_rule import PriceRule
from .settings import Settings
from .slots import team_slots
from .store import read_df
from .xpir import VOLUME_STATS, XpirModel, predict_xpir

P_PLAY_PRIOR, P_PLAY_PRIOR_GAMES, P_PLAY_WINDOW = 0.9, 2, 5
NO_DATA = "NO DATA"
VALUE_COLS = ["fantasy_id", "player", "team", "position", "price", "last_price_change", "opp", "home", "slot",
              "p_play", "xpir", "break_even", "value", "roi", "label", "dip", "pir_avg", "games"]
CHANNELS = {"fga2": "2-point attempts", "fga3": "3-point attempts", "fd": "fouls drawn",
            "oreb": "offensive rebounds", "dreb": "defensive rebounds", "ast": "assists", "stl": "steals",
            "blk": "blocks", "tov": "turnovers", "blka": "blocks against", "pf": "fouls committed"}
EFFICIENCY_TEXT = {"fga2": lambda f: f"2P% {f.p2:.0%}", "fga3": lambda f: f"3P% {f.p3:.0%}",
                   "fd": lambda f: f"FTA/FD {f.ftr:.2f} · FT% {f.ftp:.0%}"}


def team_games(conn: sqlite3.Connection, season: str) -> pd.DataFrame:
    """One row per team per played game: tv_code, game_code, round, local_date."""
    g = read_df(conn, """SELECT g.game_code, g.round, g.local_date, h.tv_code AS home_tv, a.tv_code AS away_tv
                         FROM games g
                         JOIN teams h ON h.club_code = g.home_club
                         JOIN teams a ON a.club_code = g.away_club
                         WHERE g.season = ? AND g.played = 1""", (season,))
    cols = ["tv_code", "game_code", "round", "local_date"]
    return pd.concat([g.assign(tv_code=g["home_tv"]), g.assign(tv_code=g["away_tv"])])[cols]


def p_play(log: pd.DataFrame, games: pd.DataFrame, team_of: pd.Series, before_round: int) -> pd.Series:
    """Share of his team's last 5 played games (before the round) he played, smoothed toward 0.9.

    team_of maps player_code -> tv_code (his current team).
    """
    window = (games[games["round"] < before_round].sort_values(["local_date", "game_code"])
              .groupby("tv_code").tail(P_PLAY_WINDOW)[["tv_code", "game_code"]])
    on = played_games(log)[["player_code", "game_code"]].drop_duplicates().assign(on=1)
    x = (team_of.rename("tv_code").rename_axis("player_code").reset_index()
         .merge(window, on="tv_code", how="left")
         .merge(on, on=["player_code", "game_code"], how="left"))
    agg = x.groupby("player_code").agg(n=("game_code", "count"), played=("on", "sum"))
    p = (agg["played"] + P_PLAY_PRIOR * P_PLAY_PRIOR_GAMES) / (agg["n"] + P_PLAY_PRIOR_GAMES)
    return p.reindex(team_of.index)


def label(value: pd.Series, s: Settings) -> pd.Series:
    return pd.Series(np.select([value.isna(), value >= s.value_buy, value <= s.value_sell],
                               [NO_DATA, "BUY", "SELL"], "HOLD"), index=value.index)


def _prices(conn: sqlite3.Connection, matchday: int | None) -> tuple[pd.DataFrame, pd.Series]:
    """Export rows at matchday (latest when None) and the previous stored export's prices."""
    mds = sorted(read_df(conn, "SELECT matchday FROM snapshots")["matchday"])
    md = matchday if matchday is not None else mds[-1]
    fp = read_df(conn, """SELECT fantasy_id, name || ' ' || surname AS player, team, position, price
                          FROM fantasy_players WHERE matchday = ?""", (md,))
    earlier = [m for m in mds if m < md]
    prev = (read_df(conn, "SELECT fantasy_id, price FROM fantasy_players WHERE matchday = ?", (earlier[-1],))
            .set_index("fantasy_id")["price"] if earlier else pd.Series(dtype=float))
    return fp, prev


def _stat_sheet(scored: pd.DataFrame, f: pd.DataFrame) -> pd.DataFrame:
    rows = scored[["fantasy_id", "player", "team", "player_code"]].join(f, on="player_code")
    parts = []
    for s in VOLUME_STATS:
        volume = rows[f"r_{s}"] * rows["xmin"]
        text = EFFICIENCY_TEXT.get(s)
        parts.append(pd.DataFrame({
            "fantasy_id": rows["fantasy_id"], "player": rows["player"], "team": rows["team"],
            "channel": CHANNELS[s], "volume_per_game": volume,
            "efficiency": [text(r) for r in rows.itertuples()] if text else "",
            "value_per_unit": rows[f"v_{s}"], "opp_mult": rows[f"opp_{s}"],
            "pir_per_game": volume * rows[f"v_{s}"] * rows[f"opp_{s}"]}, index=rows.index))
    # players in value order, channels in table order within each player
    return pd.concat(parts).sort_index(kind="stable").reset_index(drop=True)


def build_value_table(conn: sqlite3.Connection, season: str, round_: int, rule: PriceRule, model: XpirModel,
                      s: Settings, matchday: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(value table, per-channel stat analysis) for every player in the export at `matchday` (latest
    by default), scored for round_. Unmatched players or players without a fixture are NO DATA."""
    fp, prev = _prices(conn, matchday)
    t = fp.merge(read_df(conn, "SELECT fantasy_id, player_code FROM player_map"), on="fantasy_id", how="left")
    t["last_price_change"] = t["price"] - t["fantasy_id"].map(prev)
    slots = (team_slots(conn, season, round_).sort_values("slot").drop_duplicates("tv_code")
             .rename(columns={"tv_code": "team", "opp_tv": "opp", "is_home": "home"}))
    t = t.merge(slots[["team", "slot", "opp", "home"]], on="team", how="left")

    log = game_log(conn, season)
    poss = possessions(read_df(conn, "SELECT * FROM box_team WHERE season = ?", (season,)))
    scored = t[t["player_code"].notna() & t["opp"].notna()]
    fixtures = scored.rename(columns={"opp": "opp_tv", "home": "is_home"})[
        ["player_code", "position", "opp_tv", "is_home"]]
    f = predict_xpir(model, log, poss, round_, fixtures)
    matched = t[t["player_code"].notna()]
    pp = p_play(log, team_games(conn, season), matched.set_index("player_code")["team"], round_)

    t["p_play"] = t["player_code"].map(pp)
    for c in ("xpir", "pir_avg", "games"):
        t[c] = t["player_code"].map(f[c])
    t["break_even"] = rule.break_even(t["price"])
    t["value"] = t["p_play"] * rule.change(t["xpir"], t["price"]) + (1 - t["p_play"]) * rule.d
    t["roi"] = t["value"] / t["price"]
    t["label"] = label(t["value"], s)
    t["dip"] = ((t["pir_avg"] >= s.dip_min_avg) & (t["last_price_change"] <= -s.dip_drop)
                & (t["label"] == "BUY"))
    t = t.sort_values("value", ascending=False, na_position="last", kind="stable").reset_index(drop=True)
    return t[VALUE_COLS], _stat_sheet(t[t["value"].notna()], f)
