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

# --- DYNAMIC CALIBRATION (Pillar Logic) ---
def update_benchmarks():
    """Calculates 20/80 percentile benchmarks using the correct table columns."""
    with get_connection() as conn:
        # 1. XP (Sessions per taster)
        xp_df = pd.read_sql("""
            SELECT taster_id, COUNT(DISTINCT SUBSTR(beer_key, 1, INSTR(beer_key, '-')-1)) as count 
            FROM ratings GROUP BY taster_id
        """, conn)
        
        # 2. Event Metrics
        # JOINING b.beer_id (from beers table) to r.beer_key (from ratings table)
        event_df = pd.read_sql("""
            SELECT 
                SUBSTR(r.beer_key, 1, INSTR(r.beer_key, '-')-1) as eid,
                COUNT(DISTINCT r.beer_key) as beer_count,
                COUNT(DISTINCT r.taster_id) as voter_count,
                AVG(b.untappd_score) / 5.0 as avg_quality
            FROM beers b
            JOIN ratings r ON b.beer_id = r.beer_key
            GROUP BY eid
        """, conn)

    # Calculate Quintiles
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

# --- LOGIN SCREEN ---
if st.session_state.current_taster is None:
    st.set_page_config(page_title="Beer Tracker Login", page_icon="🍺")
    st.image(os.path.join(BASE_DIR, "OUT.jpg"), width=720)
    st.title("🍻 Beer Tracker Elite v2")
    
    with get_connection() as conn:
        query = """
            SELECT 
                t.id, 
                t.name, 
                t.is_admin, 
                COUNT(DISTINCT SUBSTR(r.beer_key, 1, INSTR(r.beer_key, '-') - 1)) as session_count
            FROM tasters t
            JOIN ratings r ON t.id = r.taster_id
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
            original_name = selected_label.split(" (")[0]
            st.session_state.update({
                'current_taster': original_name,
                'taster_id': int(name_to_id_map[selected_label]),
                'is_admin': bool(name_to_admin_map[selected_label]),
                'current_tasting': latest_session
            })
            update_benchmarks() # Calibrate points system on login
            st.rerun()
        else:
            st.warning("Please select a name.")
    st.stop()

# --- NAVIGATION SETUP (Logged In) ---
st.set_page_config(page_title="Beer Tracker Elite", page_icon="🍺", layout="wide")
st.image(os.path.join(BASE_DIR, "IN.jpg"), width=720)

# Page Definitions
pg_dash = st.Page("pages/dashboard.py", title="Dashboard", icon="🗺️", default=True)
pg_rate = st.Page("pages/rate_beers.py", title="Rate Beers", icon="⭐")
pg_lead = st.Page("pages/leaderboard.py", title="Leaderboard", icon="🏆")
pg_hall = st.Page("pages/analytics.py", title="Hall of Fame", icon="📈") # The New Analytics Page
pg_add  = st.Page("pages/add_beer.py", title="Add Beer", icon="📸")
pg_admin = st.Page("pages/curation.py", title="Admin Curation", icon="🛠️")

# Build navigation
user_pages = [pg_dash, pg_rate, pg_lead, pg_hall]
admin_pages = [pg_add, pg_admin]

if st.session_state.is_admin:
    pages_to_show = {"User": user_pages, "Admin": admin_pages}
else:
    pages_to_show = user_pages

pg = st.navigation(pages_to_show)

# Sidebar Footer
st.sidebar.divider()
st.sidebar.caption(f"Logged in as: **{st.session_state.current_taster}**")

if st.sidebar.button("Recalibrate Benchmarks"):
    update_benchmarks()
    st.toast("Club benchmarks updated based on current data!")

if st.sidebar.button("Log Out"):
    st.session_state.current_taster = None
    st.rerun()

pg.run()