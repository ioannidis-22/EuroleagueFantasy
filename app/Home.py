import pandas as pd
import streamlit as st

from elfantasy import ui_data as ud
from elfantasy.matching import unmatched_players
from elfantasy.slots import next_round, team_slots
from elfantasy.store import read_df

st.set_page_config(page_title="EL Fantasy PIR", page_icon="🏀", layout="wide")
st.title("Round dashboard")
conn, s = ud.conn(), ud.settings()
md = ud.latest_matchday()
if md is None:
    st.info("No data yet. Open the **Data** page to import your fantasy export and download games.")
    st.stop()

# ---- next round and T-slots
r = next_round(conn, s.season)
if r is None:
    st.subheader("No upcoming games in the schedule.")
else:
    st.subheader(f"Next: Round {r}")
    ts = team_slots(conn, s.season, r)
    home = ts[ts.is_home == 1]
    groups = list(home.groupby("slot"))
    for col, (slot, g) in zip(st.columns(max(1, len(groups))), groups):
        col.markdown(f"**T{slot} · {pd.Timestamp(g['local_date'].iloc[0]):%a %d %b}**")
        col.markdown("\n".join(f"- {h} vs {a}" for h, a in zip(g.tv_code, g.opp_tv)))

# ---- freshness and alerts
snap = read_df(conn, "SELECT imported_at FROM snapshots WHERE matchday = ?", (md,))
last = read_df(conn, "SELECT MAX(local_date) d FROM games WHERE season = ? AND played = 1",
               (s.season,))["d"].iloc[0]
full = read_df(conn, """SELECT MAX(round) r FROM (SELECT round FROM games WHERE season = ?
                        GROUP BY round HAVING MIN(played) = 1)""", (s.season,))["r"].iloc[0]
missing = read_df(conn, """SELECT COUNT(*) n FROM games g WHERE season = ? AND played = 1 AND NOT EXISTS
                           (SELECT 1 FROM box_player b WHERE b.season = g.season AND b.game_code = g.game_code)""",
                  (s.season,))["n"].iloc[0]
a, b, c = st.columns(3)
a.metric("Fantasy snapshot", f"Matchday {md}", f"imported {str(snap['imported_at'].iloc[0])[:16]}",
         delta_color="off")
b.metric("Last final game", pd.Timestamp(last).strftime("%d %b") if last else "—")
c.metric("Win bonus in use", f"{ud.win_bonus():.2f}")
if pd.notna(full) and int(full) > md:
    st.warning(f"Round {int(full)} is finished but your latest export is matchday {md} — import a newer export.")
if missing:
    st.warning(f"{missing} finished games have no box score yet — run **Refresh games** on the Data page.")
n_un = len(unmatched_players(conn))
if n_un:
    st.info(f"{n_un} fantasy players aren't linked to Euroleague data (see the Data page).")
for rep in st.session_state.get("refresh_reports", []):
    if rep["failed"]:
        st.warning(f"Last refresh: {len(rep['failed'])} downloads failed for {rep['season']}.")

# ---- top lists
t = ud.player_table()
pos = st.radio("Position", ["All", "Guard", "Forward", "Center"], horizontal=True)
if pos != "All":
    t = t[t.position == pos]
BASE = ["player", "team", "position", "price", "slot", "opp"]
FMT = {"price": "{:.1f}", "fpt": "{:.1f}", "fpt_per_credit": "{:.2f}", "plus": "{:+.1f}",
       "pir_avg": "{:.1f}", "pir_last5": "{:.1f}", "form_delta": "{:+.1f}", "p20": "{:.1f}",
       "slot": "T{:.0f}"}


def top(df: pd.DataFrame, col: str, cols: list[str], asc: bool = False, n: int = 10) -> None:
    out = df.dropna(subset=[col]).sort_values(col, ascending=asc).head(n)[BASE + cols]
    st.dataframe(out.style.format(FMT, na_rep="—"), hide_index=True, width="stretch")


played = t[t.games.fillna(0) >= 3]
left, right = st.columns(2)
with left:
    st.markdown("**In form** — last 5 games vs season PIR")
    top(played, "form_delta", ["pir_avg", "pir_last5", "form_delta"])
    st.markdown("**Price risers**")
    top(t, "plus", ["fpt", "plus"])
    st.markdown("**Most reliable** — floor (20th-percentile PIR)")
    top(played, "p20", ["pir_avg", "p20"])
with right:
    st.markdown("**Best value** — fantasy points per credit")
    top(t, "fpt_per_credit", ["fpt", "fpt_per_credit"])
    st.markdown("**Price fallers**")
    top(t, "plus", ["fpt", "plus"], asc=True)
    st.markdown("**Out of form**")
    top(played, "form_delta", ["pir_avg", "pir_last5", "form_delta"], asc=True)
