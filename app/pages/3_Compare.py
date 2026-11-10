import pandas as pd
import plotly.express as px
import streamlit as st

from elfantasy import ui_data as ud

st.set_page_config(page_title="Compare · EL Fantasy PIR", page_icon="🏀", layout="wide")
st.title("Compare players")
t = ud.player_table()
if t.empty:
    st.info("No data yet — use the Data page first.")
    st.stop()

s = ud.settings()
t = t.sort_values(["surname", "name"])
label = dict(zip(t.fantasy_id, t.player + " (" + t.team + ")"))
st.session_state["compare"] = [f for f in st.session_state.get("compare", []) if f in label]
picked = st.multiselect("Players (2–4)", list(label), key="compare", format_func=label.get, max_selections=4)
if len(picked) < 2:
    st.info("Pick at least two players.")
    st.stop()

sel = t.set_index("fantasy_id").loc[picked]
ROWS = {"team": "Team", "position": "Position", "price": "Price", "fpt": "FPT", "fpt_per_credit": "FPT/credit",
        "games": "Games", "min_avg": "Minutes", "min_last5": "Minutes L5", "pir_avg": "PIR",
        "pir_last5": "PIR L5", "pir_per30": "PIR/30", "p20": "Floor P20", "p80": "Ceiling P80", "sd": "SD",
        "boom_rate": "Boom %", "bust_rate": "Bust %", "dnp_rate": "DNP %", "slot": "T next", "opp": "Next opp",
        "opp_rank": "Opp DvP rank"}
table = sel[list(ROWS)].rename(columns=ROWS).T
table.columns = sel["player"]


def fmt(v):
    if isinstance(v, float):
        return "—" if pd.isna(v) else f"{v:.2f}" if abs(v) < 1 else f"{v:.1f}"
    return v


st.dataframe(table.map(fmt), width="stretch")

log = ud.load_log(ud.db(), s.season)
codes = dict(zip(sel["player_code"], sel["player"]))
g = log[log.player_code.isin([c for c in codes if pd.notna(c)]) & (log.dnp == 0)].copy()
if len(g):
    g["player"] = g["player_code"].map(codes)
    st.subheader("PIR per game")
    fig = px.line(g.sort_values("local_date"), x="round", y="pir", color="player", markers=True, height=320)
    fig.update_layout(margin=dict(t=10, b=10), legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig)

st.subheader("Where PIR comes from (per game)")
parts = sel.set_index("player")[["scoring", "rebounding", "playmaking", "defense", "negatives"]].copy()
parts["negatives"] = -parts["negatives"]
long = parts.reset_index().melt(id_vars="player", var_name="part", value_name="per game")
figb = px.bar(long, x="part", y="per game", color="player", barmode="group", height=320)
figb.update_layout(margin=dict(t=10, b=10), legend=dict(orientation="h", y=1.1))
st.plotly_chart(figb)
