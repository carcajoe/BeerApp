import streamlit as st
import sqlite3
import pd as pd
import pandas as pd
import os
from contextlib import contextmanager

# --- CONFIG & PATHS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "beer_tracker.db")

@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    try: yield conn
    finally: conn.close()

# --- INITIALIZE SESSION STATE ---
if 'current_taster' not in st.session_state:
    st.session_state.update({
        'current_taster': None,
        'is_admin': False,
        'taster_id': None,
        'current_tasting': 1
    })

# --- LOGIN SCREEN ---
if st.session_state.current_taster is None:
    st.set_page_config(page_title="Beer Tracker Login", page_icon="🍺")
    
    # Header Image for Login
    st.image(os.path.join(BASE_DIR, "OUT.jpg"), width=720)
    
    st.title("🍻 Beer Tracker Elite v2")
    
    with get_connection() as conn:
        tasters_df = pd.read_sql("SELECT id, name, is_admin FROM tasters", conn)
        last_ev = conn.execute("SELECT MAX(tasting_no) FROM events").fetchone()
        latest_session = last_ev[0] if last_ev and last_ev[0] else 1
    
    st.markdown("### Who are you?")
    name = st.selectbox("Select your profile:", [""] + sorted(tasters_df['name'].tolist()))
    
    if st.button("Enter Journey", use_container_width=True, type="primary"):
        if name:
            user = tasters_df[tasters_df['name'] == name].iloc[0]
            st.session_state.update({
                'current_taster': name,
                'taster_id': int(user['id']),
                'is_admin': bool(user['is_admin']),
                'current_tasting': latest_session
            })
            st.rerun()
        else:
            st.warning("Please select a name.")
    st.stop()

# --- NAVIGATION SETUP (Logged In) ---
# Header Image for Logged In
st.image(os.path.join(BASE_DIR, "IN.jpg"), width=720)

# Define pages pointing to the files in /pages/
pg_dash = st.Page("pages/dashboard.py", title="Dashboard", icon="🗺️", default=True)
pg_rate = st.Page("pages/rate_beers.py", title="Rate Beers", icon="⭐")
pg_lead = st.Page("pages/leaderboard.py", title="Leaderboard", icon="🏆")
pg_add  = st.Page("pages/add_beer.py", title="Add Beer", icon="📸")
pg_admin = st.Page("pages/curation.py", title="Admin Curation", icon="🛠️")

# Build sidebar based on permissions
user_pages = [pg_dash, pg_rate, pg_lead]
admin_pages = [pg_add, pg_admin]

if st.session_state.is_admin:
    pages_to_show = {"User": user_pages, "Admin": admin_pages}
else:
    pages_to_show = user_pages

pg = st.navigation(pages_to_show)

# Sidebar Footer
st.sidebar.divider()
st.sidebar.caption(f"Logged in as: **{st.session_state.current_taster}**")
if st.sidebar.button("Log Out"):
    st.session_state.current_taster = None
    st.rerun()

pg.run()