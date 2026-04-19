import streamlit as st
import sqlite3
import pandas as pd
import numpy as np
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

# --- DYNAMIC CALIBRATION ---
def update_benchmarks():
    with get_connection() as conn:
        xp_df = pd.read_sql("""
            SELECT taster_id, COUNT(DISTINCT SUBSTR(beer_key, 1, INSTR(beer_key, '-')-1)) as count 
            FROM ratings GROUP BY taster_id
        """, conn)
        
        event_df = pd.read_sql("""
            SELECT 
                SUBSTR(m.beer_event_position, 1, INSTR(m.beer_event_position, '-')-1) as eid,
                COUNT(DISTINCT m.beer_event_position) as beer_count,
                COUNT(DISTINCT r.taster_id) as voter_count,
                AVG(b.untappd_score) / 5.0 as avg_quality
            FROM beers b
            JOIN beer_event_mapping m ON b.beer_id = m.beer_id
            JOIN ratings r ON m.beer_event_position = r.beer_key
            GROUP BY eid
        """, conn)

    st.session_state['benchmarks'] = {
        "xp": np.percentile(xp_df['count'], [20, 80]) if not xp_df.empty else [2, 10],
        "strength": np.percentile(event_df['beer_count'], [20, 80]) if not event_df.empty else [8, 25],
        "participation": np.percentile(event_df['voter_count'], [20, 80]) if not event_df.empty else [6, 12],
        "quality": np.percentile(event_df['avg_quality'], [20, 80]) if not event_df.empty else [0.65, 0.82]
    }

# --- INITIALIZE SESSION STATE ---
if 'current_taster' not in st.session_state:
    st.session_state.update({
        'current_taster': None,
        'is_admin': False,
        'taster_id': None,
        'current_tasting': 1,
        'benchmarks': None
    })

# --- REUSABLE HEADER FUNCTION ---
def render_branded_header(image_name):
    # Use 5 columns to create a narrower middle slot for the 720px image 
    # to prevent it from looking "small" due to column stretching
    _, _, col_mid, _, _ = st.columns([1, 1, 4, 1, 1])
    with col_mid:
        st.image(os.path.join(BASE_DIR, image_name), width=720)

# --- LOGIN SCREEN ---
if st.session_state.current_taster is None:
    st.set_page_config(page_title="Beer Tracker Login", page_icon="🍺", layout="wide")
    
    render_branded_header("OUT.jpg")
    
    st.title("🍻 Beer Tracker Elite v2")
    
    with get_connection() as conn:
        query = """
            SELECT t.id, t.name, t.is_admin, 
                   COUNT(DISTINCT SUBSTR(m.beer_event_position, 1, INSTR(m.beer_event_position, '-') - 1)) as session_count
            FROM tasters t
            JOIN ratings r ON t.id = r.taster_id
            JOIN beer_event_mapping m ON r.beer_key = m.beer_event_position
            GROUP BY t.id
            HAVING session_count > 0
            ORDER BY session_count DESC, t.name ASC
        """
        tasters_df = pd.read_sql(query, conn)
        last_ev = conn.execute("SELECT MAX(tasting_no) FROM events").fetchone()
        latest_session = last_ev[0] if last_ev and last_ev[0] else 1
    
    st.markdown("### Who are you?")
    taster_options = tasters_df.apply(lambda x: f"{x['name']} ({x['session_count']} sessions)", axis=1).tolist()
    name_to_id_map = dict(zip(taster_options, tasters_df['id']))
    name_to_admin_map = dict(zip(taster_options, tasters_df['is_admin']))

    selected_label = st.selectbox("Select your profile:", [""] + taster_options)
    
    if st.button("Enter Journey", use_container_width=True, type="primary"):
        if selected_label:
            st.session_state.update({
                'current_taster': selected_label.split(" (")[0],
                'taster_id': int(name_to_id_map[selected_label]),
                'is_admin': bool(name_to_admin_map[selected_label]),
                'current_tasting': latest_session
            })
            update_benchmarks()
            st.rerun()
    st.stop()

# --- NAVIGATION SETUP (Logged In) ---
st.set_page_config(page_title="Beer Tracker Elite", page_icon="🍺", layout="wide")

render_branded_header("IN.jpg")

# Page Definitions
pg_dash = st.Page("pages/dashboard.py", title="Dashboard", icon="🗺️", default=True)
pg_rate = st.Page("pages/rate_beers.py", title="Rate Beers", icon="⭐")
pg_lead = st.Page("pages/leaderboard.py", title="Leaderboard", icon="🏆")
pg_hall = st.Page("pages/analytics.py", title="Hall of Fame", icon="📈")
pg_add  = st.Page("pages/add_beer.py", title="Add Beer", icon="📸")
pg_admin = st.Page("pages/curation.py", title="Admin Curation", icon="🛠️")

# Navigation Routing
if st.session_state.is_admin:
    pg = st.navigation({
        "User": [pg_dash, pg_rate, pg_lead, pg_hall],
        "Admin": [pg_add, pg_admin]
    })
else:
    pg = st.navigation([pg_dash, pg_rate, pg_lead, pg_hall])

# Sidebar
st.sidebar.divider()
st.sidebar.caption(f"Logged in as: **{st.session_state.current_taster}**")
if st.sidebar.button("Log Out"):
    st.session_state.current_taster = None
    st.rerun()

pg.run()