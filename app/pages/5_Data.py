import json
import shutil
from dataclasses import asdict, replace
from pathlib import Path

import pandas as pd
import streamlit as st

from elfantasy import paths
from elfantasy import ui_data as ud
from elfantasy.el_client import ELClient
from elfantasy.fantasy_import import ExportFormatError, import_export
from elfantasy.matching import match_players, save_override, unmatched_players
from elfantasy.metrics import estimate_win_bonus
from elfantasy.refresh import refresh_season
from elfantasy.settings import save_settings
from elfantasy.store import read_df

st.set_page_config(page_title="Data · EL Fantasy PIR", page_icon="🏀", layout="wide")
st.title("Data")
conn = ud.conn()
s = ud.settings()

# ---------- status ----------
md = ud.latest_matchday()
snap = read_df(conn, "SELECT matchday, imported_at FROM snapshots ORDER BY matchday DESC LIMIT 1")
games = read_df(conn, """SELECT season, COUNT(*) total, SUM(played) played,
                                (SELECT COUNT(DISTINCT game_code) FROM box_player b WHERE b.season = g.season) stored
                         FROM games g GROUP BY season ORDER BY season""")
c1, c2 = st.columns(2)
c1.metric("Latest fantasy snapshot", f"Matchday {md}" if md else "none",
          snap["imported_at"].iloc[0] if len(snap) else None)
c2.dataframe(games, hide_index=True, width="stretch")

# ---------- import ----------
st.header("1 · Import fantasy export")
up = st.file_uploader("players_stats.xlsx from the fantasy site", type=["xlsx"])
if up is not None and st.button("Import", type="primary"):
    imports = paths.data_dir() / "imports"
    imports.mkdir(parents=True, exist_ok=True)
    tmp = imports / "_upload.xlsx"
    tmp.write_bytes(up.getvalue())
    try:
        new_md = import_export(conn, tmp)
    except ExportFormatError as e:
        st.error(f"Import refused — the export's columns changed. Missing: {e.missing or '-'}; "
                 f"unexpected: {e.unexpected or '-'}")
    else:
        shutil.move(tmp, imports / f"matchday_{new_md}.xlsx")
        rep = match_players(conn, s.season, paths.overrides_path())
        ud.clear_caches()
        st.success(f"Matchday {new_md} imported. {rep.matched} players matched, "
                   f"{len(rep.unmatched)} unmatched.")

# ---------- refresh ----------
st.header("2 · Refresh games")
st.caption("Downloads this season's fixtures and new box scores. The official box-score server "
           "rate-limits bursts; the app waits when told to, so this can pause for a few minutes.")
if st.button("Refresh games"):
    client = ELClient(paths.cache_dir(), delay_s=s.api_delay_s)
    reports = []
    for season in [s.season]:
        bar = st.progress(0.0, text=f"{season}…")
        rep = refresh_season(conn, client, season, source="live",
                             progress=lambda i, n, b=bar, se=season: b.progress(i / n, text=f"{se}: {i}/{n}"))
        bar.progress(1.0, text=f"{season}: done")
        reports.append(rep)
    match_players(conn, s.season, paths.overrides_path())
    ud.clear_caches()
    st.session_state["refresh_reports"] = [asdict(r) for r in reports]
for r in st.session_state.get("refresh_reports", []):
    msg = f"{r['season']}: {r['games_total']} games, {r['new_box_scores']} new box scores"
    if r["failed"]:
        st.warning(f"{msg}, {len(r['failed'])} failed — run Refresh again later.")
        st.dataframe(pd.DataFrame(r["failed"], columns=["game", "error"]), hide_index=True)
    else:
        st.success(msg)

# ---------- matching ----------
st.header("3 · Unmatched players")
um = unmatched_players(conn)
if um.empty:
    st.success("Every fantasy player is linked to a Euroleague player.")
else:
    st.caption("Usually players who haven't played this season (injured or left). "
               "Link one by hand if he has games.")
    st.dataframe(um, hide_index=True, width="stretch")
    pick = st.selectbox("Player to link", um["fantasy_id"],
                        format_func=lambda f: " ".join(um.loc[um.fantasy_id == f, ["name", "surname", "team"]].iloc[0]))
    team = um.loc[um.fantasy_id == pick, "team"].iloc[0]
    cands = read_df(conn, """SELECT DISTINCT e.player_code, e.name FROM el_players e
                             JOIN teams t ON t.club_code = e.club_code
                             WHERE e.season = ? AND t.tv_code = ? ORDER BY e.name""", (s.season, team))
    if cands.empty:
        st.info(f"No Euroleague players stored for {team} yet — refresh games first.")
    else:
        code = st.selectbox("Euroleague player", cands["player_code"],
                            format_func=lambda c: cands.loc[cands.player_code == c, "name"].iloc[0])
        if st.button("Save link"):
            save_override(paths.overrides_path(), pick, code)
            match_players(conn, s.season, paths.overrides_path())
            ud.clear_caches()
            st.rerun()

# ---------- settings ----------
st.header("4 · Settings")
est = estimate_win_bonus(conn, s.season, md) if md else None
with st.form("settings"):
    a, b, c = st.columns(3)
    boom = a.number_input("Boom game: PIR at least", value=float(s.boom), step=1.0)
    bust = b.number_input("Bust game: PIR below", value=float(s.bust), step=1.0)
    form_t = c.number_input("Form arrow threshold (PIR)", value=float(s.form_threshold), step=0.5)
    wb_txt = a.text_input("Win bonus (blank = estimated)",
                          value="" if s.win_bonus is None else str(s.win_bonus),
                          help=f"Current estimate from your data: {est:.2f}" if est is not None else
                          "Not enough data for an estimate yet.")
    shrink = b.number_input("DvP shrinkage (minutes)", value=float(s.dvp_shrink_minutes), step=50.0)
    if st.form_submit_button("Save settings"):
        try:
            wb = float(wb_txt) if wb_txt.strip() else None
        except ValueError:
            st.error("Win bonus must be a number or blank.")
        else:
            save_settings(replace(s, boom=boom, bust=bust, form_threshold=form_t, win_bonus=wb,
                                  dvp_shrink_minutes=shrink), paths.settings_path())
            ud.clear_caches()
            st.success("Saved.")
st.caption(f"Win bonus in use: {ud.win_bonus():.2f}"
           + (f" (estimated; your setting is blank)" if s.win_bonus is None else " (your setting)"))
