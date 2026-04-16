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
        # SQL logic: 
        # 1. Join tasters with ratings to count event participation
        # 2. Group by taster ID
        # 3. HAVING count > 0 removes 'blank/empty' tasters who haven't participated
        # 4. ORDER BY participation DESC puts the most active users at the top
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
    
    # Generate labels like "Name (12 sessions)" for better UX
    taster_options = tasters_df.apply(lambda x: f"{x['name']} ({x['session_count']} sessions)", axis=1).tolist()
    name_to_id_map = dict(zip(taster_options, tasters_df['id']))
    name_to_admin_map = dict(zip(taster_options, tasters_df['is_admin']))

    selected_label = st.selectbox("Select your profile:", [""] + taster_options)
    
    if st.button("Enter Journey", use_container_width=True, type="primary"):
        if selected_label:
            # Extract the original name from the label (everything before the first " (")
            original_name = selected_label.split(" (")[0]
            
            st.session_state.update({
                'current_taster': original_name,
                'taster_id': int(name_to_id_map[selected_label]),
                'is_admin': bool(name_to_admin_map[selected_label]),
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