import streamlit as st

from elfantasy import ui_data as ud

st.set_page_config(page_title="Players · EL Fantasy PIR", page_icon="🏀", layout="wide")
st.title("Player explorer")
t = ud.player_table()
if t.empty:
    st.info("No data yet — use the Data page first.")
    st.stop()

LABELS = {
    "player": "Player", "team": "Team", "position": "Pos", "price": "Price", "plus": "Price Δ",
    "fpt": "FPT", "fpt_per_credit": "FPT/credit", "games": "GP", "min_avg": "Min", "min_last5": "Min L5",
    "pir_avg": "PIR", "pir_last3": "PIR L3", "pir_last5": "PIR L5", "form_delta": "Form Δ",
    "form_trend": "Trend", "pir_per30": "PIR/30", "p20": "Floor P20", "p80": "Ceiling P80", "sd": "SD",
    "boom_rate": "Boom %", "bust_rate": "Bust %", "dnp_rate": "DNP %", "slot": "T", "opp": "Next opp",
    "opp_rank": "Opp rank", "opp_idx": "Opp DvP", "scoring": "Scoring", "rebounding": "Rebounding",
    "playmaking": "Playmaking", "defense": "Defense", "negatives": "Negatives",
}
DEFAULT = ["player", "team", "position", "price", "fpt", "fpt_per_credit", "games", "pir_avg",
           "pir_last5", "form_trend", "min_last5", "p20", "p80", "slot", "opp", "opp_rank"]
PCT = ("boom_rate", "bust_rate", "dnp_rate", "opp_idx")

with st.sidebar:
    pos = st.multiselect("Position", ["Guard", "Forward", "Center"])
    teams = st.multiselect("Team", sorted(t.team.dropna().unique()))
    lo, hi = float(t.price.min()), float(t.price.max())
    price = st.slider("Price", lo, hi, (lo, hi), step=0.1)
    slots = st.multiselect("T-slot next round", sorted(int(x) for x in t.slot.dropna().unique()),
                           format_func=lambda x: f"T{x}")
    min_games = st.number_input("Minimum games", 0, 40, 0)
    cols = st.multiselect("Columns", list(LABELS), default=DEFAULT, format_func=LABELS.get) or DEFAULT

f = t[t.price.between(*price)]
if pos:
    f = f[f.position.isin(pos)]
if teams:
    f = f[f.team.isin(teams)]
if slots:
    f = f[f.slot.isin(slots)]
if min_games:
    f = f[f.games.fillna(0) >= min_games]

view = f[cols].rename(columns=LABELS)
fmt = {LABELS[c]: ("{:.0%}" if c in PCT else ("T{:.0f}" if c == "slot" else "{:.1f}"))
       for c in cols if f[c].dtype.kind == "f"}
st.caption(f"{len(view)} players · click a column header to sort")
st.dataframe(view.style.format(fmt, na_rep="—"), hide_index=True, width="stretch", height=640)
st.download_button("Download CSV", f[cols].to_csv(index=False).encode("utf-8-sig"), "players.csv", "text/csv")
