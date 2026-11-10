import pandas as pd
import plotly.express as px
import streamlit as st

from elfantasy import ui_data as ud
from elfantasy.dvp import POSITIONS, fixture_difficulty, fixture_difficulty_values, how_they_concede
from elfantasy.slots import next_round
from elfantasy.views import conceded_trend

st.set_page_config(page_title="Opponents · EL Fantasy PIR", page_icon="🏀", layout="wide")
st.title("Opponents — Defense vs Position")
s = ud.settings()
if ud.load_log(ud.db(), s.season).empty:
    st.info("No games yet — use the Data page first.")
    st.stop()

METRICS = {"pir": "PIR", "fpt": "Fantasy points", "pts": "Points", "oreb": "Off. rebounds",
           "dreb": "Def. rebounds", "ast": "Assists", "stl": "Steals", "blk": "Blocks", "fd": "Fouls drawn",
           "tov": "Turnovers", "pf": "Fouls committed", "blka": "Blocks against",
           "fg2_pct": "2P% allowed", "fg3_pct": "3P% allowed", "ft_pct": "FT%"}
WINDOWS = {"season": "Season", "last5": "Last 5 games", "home": "Opponent at home", "away": "Opponent away"}
ROLES = {"all": "All players", "starters": "Starters", "bench": "Bench"}
BASES = {"game": "Per game", "per40": "Per 40 minutes", "per100": "Per 100 possessions"}
wb = ud.win_bonus()


def table(season, window="season", role="all", basis="per40"):
    return ud.load_dvp(ud.db(), season, window, role, basis, wb, s.dvp_shrink_minutes)


def heatmap(tab: pd.DataFrame, metric: str, show: str, key: str) -> None:
    if tab.empty:
        st.info("Not enough data for this view.")
        return
    col = f"idx_{metric}" if show == "Index vs league" else metric
    grid = tab[col].unstack("position").reindex(columns=list(POSITIONS))
    order = tab["idx_pir"].unstack("position").mean(axis=1).sort_values(ascending=False).index
    grid = grid.loc[order]
    if show == "Index vs league":
        lim = max(0.05, float(grid.abs().max().max()))
        fig = px.imshow(grid, color_continuous_scale="RdBu_r", zmin=-lim, zmax=lim, text_auto="+.0%",
                        aspect="auto", height=640)
    else:
        fig = px.imshow(grid, color_continuous_scale="Reds", text_auto=".2f" if "pct" in metric else ".1f",
                        aspect="auto", height=640)
    fig.update_layout(margin=dict(t=10, b=10), coloraxis_colorbar_title="")
    st.plotly_chart(fig, key=key)
    st.caption("Rows sorted softest → toughest (overall PIR index). Red = gives up more than the league "
               "average to that position; blue = gives up less.")


tab_heat, tab_team, tab_fix = st.tabs(["Heatmap", "Team", "Fixture difficulty"])

with tab_heat:
    c = st.columns(5)
    show = c[0].radio("Show", ["Index vs league", "Raw value"], key="heat_show")
    metric = c[1].selectbox("Stat", list(METRICS), format_func=METRICS.get)
    window = c[2].selectbox("Window", list(WINDOWS), format_func=WINDOWS.get)
    role = c[3].selectbox("Players", list(ROLES), format_func=ROLES.get)
    if show == "Raw value":
        basis = c[4].selectbox("Basis", list(BASES), index=1, format_func=BASES.get)
    else:
        basis = "per40"
        c[4].caption("Index = per 40 minutes vs league average, adjusted for small samples.")
    heatmap(table(s.season, window, role, basis), metric, show, "heat_current")

with tab_team:
    tab = table(s.season, basis=st.radio("Basis", list(BASES), index=1, format_func=BASES.get,
                                         horizontal=True, key="team_basis"))
    teams = sorted(tab.index.get_level_values("def_tv").unique()) if len(tab) else []
    if teams:
        team = st.selectbox("Team", teams)
        cols = st.columns(3)
        for col, pos in zip(cols, POSITIONS):
            if (team, pos) not in tab.index:
                continue
            row = tab.loc[(team, pos)]
            hi, lo = how_they_concede(row)
            col.markdown(f"### vs {pos}s · rank {int(row.rank_pir)}/{tab.xs(pos, level='position').shape[0]}")
            col.markdown("**Gives up most:** " + ", ".join(f"{METRICS.get(k, k)} {v:+.0%}" for k, v in hi)
                         + "  \n**Gives up least:** " + ", ".join(f"{METRICS.get(k, k)} {v:+.0%}" for k, v in lo))
            detail = pd.DataFrame({"value": [row.get(k) for k in METRICS],
                                   "index": [row.get(f"idx_{k}") for k in METRICS]},
                                  index=[METRICS[k] for k in METRICS])
            col.dataframe(detail.style.format({"value": "{:.2f}", "index": "{:+.0%}"}, na_rep="—"))
        tr = conceded_trend(ud.load_log(ud.db(), s.season), team)
        if len(tr):
            fig = px.line(tr, x="round", y="rolling_pir", color="position", markers=True, height=300,
                          labels={"rolling_pir": "PIR conceded (5-game avg)"})
            fig.update_layout(margin=dict(t=10, b=10))
            st.plotly_chart(fig, key="trend")

with tab_fix:
    r = next_round(ud.conn(), s.season)
    if r is None:
        st.info("No upcoming rounds in the schedule.")
    else:
        c = st.columns(2)
        pos = c[0].selectbox("Your player's position", list(POSITIONS), key="fix_pos")
        n = c[1].slider("Rounds ahead", 1, 5, 3)
        tab = table(s.season)
        vals = fixture_difficulty_values(ud.conn(), s.season, r, n, pos, tab)
        labels = fixture_difficulty(ud.conn(), s.season, r, n, pos, tab)
        if vals.empty:
            st.info("No fixtures found.")
        else:
            vals = vals.loc[vals.mean(axis=1).sort_values(ascending=False).index]
            labels = labels.loc[vals.index, vals.columns]
            lim = max(0.05, float(vals.abs().max().max()))
            fig = px.imshow(vals, color_continuous_scale="RdBu_r", zmin=-lim, zmax=lim, aspect="auto",
                            height=640)
            fig.update_traces(text=labels.values, texttemplate="%{text}")
            fig.update_layout(margin=dict(t=10, b=10), coloraxis_colorbar_title="")
            st.plotly_chart(fig, key="fixtures")
            st.caption(f"Each cell: opponent, T-slot, and how much PIR that opponent concedes to {pos}s vs "
                       "the league (red = easier matchup). Teams sorted easiest run first.")

