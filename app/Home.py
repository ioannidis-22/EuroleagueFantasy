import streamlit as st

from elfantasy import ui_data as ud

st.set_page_config(page_title="EL Fantasy PIR", page_icon="🏀", layout="wide")
st.title("Round dashboard")
if ud.latest_matchday() is None:
    st.info("No data yet. Open the **Data** page to import your fantasy export and download games.")
