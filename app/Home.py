import streamlit as st

from elfantasy.el_client import ELClient
from elfantasy.hud import render_result
from elfantasy.matchday import run_matchday
from elfantasy.paths import cache_dir, data_dir, db_path, settings_path
from elfantasy.settings import load_settings
from elfantasy.store import connect

st.set_page_config(page_title="EL fantasy value picks", page_icon="🏀", layout="wide")
st.title("Euroleague fantasy value picks")
upload = st.file_uploader("players_stats.xlsx from the fantasy site", type=["xlsx"])

if st.button("Run", type="primary", disabled=upload is None):
    imports = data_dir() / "imports"
    imports.mkdir(exist_ok=True)
    path = imports / "upload.xlsx"
    path.write_bytes(upload.getvalue())
    s = load_settings(settings_path())
    conn = connect(db_path())
    st.session_state.pop("result", None)
    try:
        with st.spinner("Importing, downloading new games and fitting. The box-score server may make "
                        "this pause for a few minutes."):
            result = run_matchday(conn, path, ELClient(cache_dir(), delay_s=s.api_delay_s), s)
    except ValueError as e:          # a changed export format (ExportFormatError) or no round left
        st.error(str(e))
    else:
        path.replace(imports / f"matchday_{result.matchday}.xlsx")
        st.session_state["result"] = result
    finally:
        conn.close()

if "result" in st.session_state:
    render_result(st.session_state["result"])
