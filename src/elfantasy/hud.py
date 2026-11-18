"""The page's result section: the fitted formula, every player's value, the Excel file."""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from .dvp import POSITIONS
from .matchday import MatchdayResult, backtest, value_excel_bytes
from .paths import db_path, settings_path
from .settings import load_settings
from .store import connect
from .value import CHANNELS, NO_DATA
from .xpir import EFFICIENCIES, VOLUME_STATS

LABELS = ["BUY", "HOLD", "SELL", NO_DATA]
LABEL_STYLE = {"BUY": "background-color: #1f7a3a; color: white",
               "SELL": "background-color: #b3261e; color: white",
               "HOLD": "background-color: #6b7280; color: white",
               NO_DATA: "background-color: #d1d5db; color: #374151"}
COLUMNS = {"player": "Player", "team": "Team", "position": "Pos", "price": "Price",
           "last_price_change": "Last change", "opponent": "Opponent", "p_play": "P(play)", "xpir": "xPIR",
           "break_even": "Break-even", "value": "Value", "roi": "ROI", "label": "Label", "dip": "DIP"}
FORMAT = {"Price": "{:.1f}", "Last change": "{:+.1f}", "P(play)": "{:.0%}", "xPIR": "{:.1f}",
          "Break-even": "{:.1f}", "Value": "{:+.2f}", "ROI": "{:+.2%}"}
STAT_NAMES = {**CHANNELS, "p2": "2P%", "p3": "3P%", "ftp": "FT%", "ftr": "FTA per foul drawn"}


def _num(x: float) -> str:
    return f"{x:.2f}".replace("-", "−")


def _signed(x: float) -> str:
    return f"{'+' if x >= 0 else '−'} {abs(x):.2f}"


def _formula(r: MatchdayResult) -> None:
    rule, m = r.rule, r.model
    st.subheader(f"Round {r.round_} picks · export matchday {r.matchday}")
    st.code("\n".join([
        f"value      = P(play) × {rule.k:.3f} × (xPIR − break-even) + (1 − P(play)) × {_num(rule.d)}",
        f"break-even = {rule.a:.2f} × price {_signed(rule.c)}",
        f"xPIR       = {_num(m.alpha)} + {m.beta:.2f} × raw {_signed(m.gamma_home)} × home "
        f"{_signed(m.delta_bounce)} × last-game swing",
        "raw        = expected minutes × Σ channels (volume per minute × PIR per unit × opponent factor)"]),
        language=None)
    if rule.source == "fitted":
        st.caption(f"Price rule fitted on {rule.n} player-rounds from your stored exports (R² {rule.r2:.2f}).")
    else:
        st.caption("Price rule: the defaults. Fitting it needs the exports of two consecutive matchdays.")
    if m.train_rows:
        st.caption(f"xPIR fitted on {m.train_rows} player-games: off by {m.mae:.1f} PIR on average, "
                   f"against {m.mae_baseline:.1f} for the season average.")
    else:
        st.caption("xPIR not fitted yet (no earlier rounds to learn from): raw channel PIR is used as is.")
    with st.expander("Stat-line importance and bounce-back"):
        unit = {**dict.fromkeys(VOLUME_STATS, "minutes"), **dict.fromkeys(EFFICIENCIES, "attempts")}
        st.table(pd.DataFrame({"Stat": [STAT_NAMES[s] for s in unit],
                               "Pulled toward position average until": [f"{m.k[s]:g} {u}" for s, u in unit.items()]})
                 .set_index("Stat"))
        half_life = "equal weights" if np.isinf(m.half_life) else f"half-life {m.half_life:g} games"
        st.markdown(f"- Recency: {half_life}\n"
                    f"- Expected minutes: {m.w_season_min:.2f} × season + {1 - m.w_season_min:.2f} × last 3, "
                    f"pulled toward the position median (worth {m.minutes_shrink:g} of his games)\n"
                    f"- Bounce-back weight: {m.delta_bounce:+.2f} PIR per PIR of last-game swing")


def _accuracy(r: MatchdayResult) -> None:
    """The backtest line, computed on the first click and kept on the result for later reruns."""
    if r.backtest is None:
        if not st.button("Check accuracy", key="check_accuracy"):
            return
        s = load_settings(settings_path())
        conn = connect(db_path())
        try:
            with st.spinner("Refitting xPIR on each past round."):
                r.backtest = backtest(conn, s.season, r.rule, s=s)
        finally:
            conn.close()
    _backtest_line(r.backtest)


def _backtest_line(bt: pd.DataFrame) -> None:
    bt = bt.dropna(subset=["mae_xpir"])
    if bt.empty:
        st.caption("Backtest: not enough past rounds yet.")
        return
    mae = np.average(bt["mae_xpir"], weights=bt["n"])
    base = np.average(bt["mae_baseline"], weights=bt["n"])
    text = (f"Backtest, rounds {bt['round'].min()}–{bt['round'].max()}: xPIR off by {mae:.1f} PIR per player, "
            f"against {base:.1f} for the season average.")
    calls = []
    for name in ("buy", "sell"):
        n = int(bt[f"{name}_n"].sum())
        if n:
            hit = (bt[f"{name}_hit"].fillna(0) * bt[f"{name}_n"]).sum() / n
            calls.append(f"{name.upper()} right {hit:.0%} of {n}")
    text += (f" Calls, where a stored export gave the prices: {', '.join(calls)}." if calls
             else " BUY/SELL hit rates need stored exports of past matchdays.")
    st.caption(text)


def _opponent(v: pd.DataFrame) -> pd.Series:
    where = np.where(v["home"] == 1, "vs", "@")
    text = pd.Series(where, index=v.index) + " " + v["opp"].astype(str) + " · T" + v["slot"].astype("Int64").astype(str)
    return text.where(v["opp"].notna(), "")


def _table(v: pd.DataFrame) -> None:
    left, right = st.columns([3, 1])
    labels = left.multiselect("Label", LABELS, default=LABELS, key="label_filter")
    position = right.selectbox("Position", ["All", *POSITIONS], key="position_filter")
    shown = v[v["label"].isin(labels)]
    if position != "All":
        shown = shown[shown["position"] == position]
    table = shown.assign(opponent=_opponent(shown))[list(COLUMNS)].rename(columns=COLUMNS)
    st.dataframe(table.style.format(FORMAT, na_rep="—").map(LABEL_STYLE.get, subset=["Label"]),
                 hide_index=True, width="stretch", height=600)
    st.caption(f"{len(shown)} of {len(v)} players, best value first.")


def render_result(r: MatchdayResult) -> None:
    if r.refresh.failed:
        games = ", ".join(str(code) for code, _ in r.refresh.failed)
        st.warning(f"{len(r.refresh.failed)} downloads failed (game {games}). The picks use the games already "
                   "stored; run again later to fill them in.")
    if r.unmatched:
        st.caption(f"{r.unmatched} export players aren't linked to Euroleague data. They show as NO DATA.")
    _formula(r)
    _accuracy(r)
    _table(r.value)
    st.download_button("Download Excel", value_excel_bytes(r.value, r.stats, r.model, r.rule, r.round_),
                       file_name=f"value_round_{r.round_}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
