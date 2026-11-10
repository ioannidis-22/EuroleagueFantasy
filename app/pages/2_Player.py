import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from elfantasy import ui_data as ud
from elfantasy.dvp import how_they_concede
from elfantasy.metrics import price_history
from elfantasy.views import history_vs_teams, matchup_table

st.set_page_config(page_title="Player · EL Fantasy PIR", page_icon="🏀", layout="wide")
t = ud.player_table()
if t.empty:
    st.title("Player profile")
    st.info("No data yet — use the Data page first.")
    st.stop()

s = ud.settings()
t = t.sort_values(["surname", "name"])
label = dict(zip(t.fantasy_id, t.player + " (" + t.team + ")"))
if st.session_state.get("player") not in label:
    st.session_state["player"] = t.sort_values("fpt", ascending=False).fantasy_id.iloc[0]
fid = st.sidebar.selectbox("Player", list(label), key="player", format_func=label.get)
p = t.set_index("fantasy_id").loc[fid]
st.title(f"{p.player}")
st.caption(f"{p.team} · {p.position}")


def num(v, f="{:.1f}"):
    return "—" if pd.isna(v) else f.format(v)


m = st.columns(6)
m[0].metric("Price", num(p.price), num(p.plus, "{:+.1f}"))
m[1].metric("FPT (fantasy avg)", num(p.fpt))
m[2].metric("PIR season", num(p.pir_avg))
m[3].metric("PIR last 5", num(p.pir_last5), num(p.form_delta, "{:+.1f}"))
m[4].metric("Minutes last 5", num(p.min_last5), num(p.min_last5 - p.min_avg, "{:+.1f}"))
m[5].metric("Next round", "—" if pd.isna(p.slot) else f"T{int(p.slot)} vs {p.opp}")

if pd.isna(p.player_code):
    st.info("This player isn't linked to Euroleague data (no games found). Link him on the Data page if he has played.")
    st.stop()

log = ud.load_log(ud.db(), s.season)
g = log[log.player_code == p.player_code].sort_values("local_date")
if g.empty:
    st.info("No games this season yet.")
else:
    played = g[g.dnp == 0].copy()
    played["roll3"] = played["pir"].rolling(3, min_periods=1).mean()
    st.subheader("Game log")
    fig = go.Figure()
    fig.add_bar(x=played["round"], y=played["pir"], name="PIR",
                hovertext=played["opp_tv"], marker_color="#4C78A8")
    fig.add_scatter(x=played["round"], y=played["roll3"], name="3-game avg", mode="lines+markers",
                    line_color="#F58518")
    dnp = g[g.dnp == 1]
    if len(dnp):
        fig.add_scatter(x=dnp["round"], y=[0] * len(dnp), mode="markers", name="DNP",
                        marker=dict(symbol="x", size=11, color="#E45756"))
    fig.update_layout(height=320, margin=dict(t=10, b=10), xaxis_title="Round", yaxis_title="PIR",
                      legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig)
    figm = px.bar(played, x="round", y="minutes", hover_data=["opp_tv"], height=220)
    figm.update_layout(margin=dict(t=10, b=10), xaxis_title="Round", yaxis_title="Minutes")
    st.plotly_chart(figm)

    left, right = st.columns(2)
    with left:
        st.subheader("Where his PIR comes from")
        parts = pd.DataFrame({"part": ["Scoring", "Rebounding", "Playmaking", "Defense", "Negatives"],
                              "value": [p.scoring, p.rebounding, p.playmaking, p.defense, -p.negatives]})
        figb = px.bar(parts, x="value", y="part", orientation="h", color="part", height=260,
                      color_discrete_sequence=["#4C78A8", "#54A24B", "#B279A2", "#72B7B2", "#E45756"])
        figb.update_layout(showlegend=False, margin=dict(t=10, b=10), xaxis_title="per game", yaxis_title="")
        st.plotly_chart(figb)
    with right:
        st.subheader("Consistency")
        c = st.columns(3)
        c[0].metric("Floor (P20)", num(p.p20))
        c[1].metric("Ceiling (P80)", num(p.p80))
        c[2].metric("Spread (SD)", num(p.sd))
        c = st.columns(3)
        c[0].metric(f"Boom ≥{s.boom:g}", num(p.boom_rate, "{:.0%}"))
        c[1].metric(f"Bust <{s.bust:g}", num(p.bust_rate, "{:.0%}"))
        c[2].metric("DNP rate", num(p.dnp_rate, "{:.0%}"))
        figh = px.histogram(played, x="pir", nbins=12, height=180)
        figh.update_layout(margin=dict(t=10, b=10), xaxis_title="PIR per game", yaxis_title="games")
        st.plotly_chart(figh)

ph = price_history(ud.conn(), fid)
if len(ph) > 1:
    st.subheader("Price history")
    st.plotly_chart(px.line(ph, x="matchday", y="price", markers=True, height=220))

if pd.notna(p.opp):
    st.subheader(f"Matchup: next opponent {p.opp} vs {p.position}s")
    tab = ud.load_dvp(ud.db(), s.season, "season", "all", "per40", ud.win_bonus(), s.dvp_shrink_minutes)
    mt = matchup_table(log, p.player_code, p.opp, p.position, tab)
    st.dataframe(mt.style.format({"player_per40": "{:.1f}", "opp_index": "{:+.0%}"}, na_rep="—"),
                 hide_index=True)
    st.caption("Player per 40 minutes beside what this opponent allows to his position vs league average "
               "(+ = gives up more).")
    if (p.opp, p.position) in tab.index:
        hi, lo = how_they_concede(tab.loc[(p.opp, p.position)])
        st.markdown("**Gives up most:** " + ", ".join(f"{k} {v:+.0%}" for k, v in hi)
                    + "  \n**Gives up least:** " + ", ".join(f"{k} {v:+.0%}" for k, v in lo))

st.subheader("This season vs each team")
h = history_vs_teams(log, p.player_code)
st.dataframe(h.style.format({"pir_avg": "{:.1f}", "min_avg": "{:.1f}"}), hide_index=True)
