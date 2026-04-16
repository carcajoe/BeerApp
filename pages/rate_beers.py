import streamlit as st
import pandas as pd
import sqlite3
import os

# --- 1. CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_NAME = os.path.join(BASE_DIR, "beer_tracker.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

def get_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;") 
    return conn

# Security Check: Ensure user is logged in
if 'current_taster' not in st.session_state or st.session_state.current_taster is None:
    st.warning("Please log in on the main page.")
    st.stop()

# --- 2. DYNAMIC SESSION DETECTION ---
with get_connection() as conn:
    last_ev_row = conn.execute("SELECT MAX(tasting_no) FROM events").fetchone()
    latest_db_tasting = last_ev_row[0] if last_ev_row and last_ev_row[0] else 1

# Use state if set (from a previous selection), otherwise default to newest
curr_tasting = st.session_state.get('current_tasting', latest_db_tasting)

st.header(f"⭐ Vote - Session {curr_tasting}")
st.info(f"Voting as: **{st.session_state.current_taster}**")

# --- 3. LOAD SESSION BEERS ---
with get_connection() as conn:
    beers = pd.read_sql("SELECT * FROM beers WHERE beer_id LIKE ?", conn, params=(f"{curr_tasting}-%",))

if beers.empty: 
    st.warning(f"No beers found for session #{curr_tasting}.")
    if st.button("Switch to Latest Session"):
        st.session_state.current_tasting = latest_db_tasting
        st.rerun()
else:
    actual_name = st.session_state.current_taster
    t_id = st.session_state.taster_id

    # --- OVERWRITE CHECK ---
    with get_connection() as conn:
        voted = conn.execute("""
            SELECT COUNT(*) FROM ratings r 
            WHERE r.taster_id = ? AND r.beer_key LIKE ?
        """, (t_id, f"{curr_tasting}-%")).fetchone()[0]
        
    if voted: 
        st.warning("⚠️ You've already voted for this session. Submitting again will update your scores.")

    # --- RANKING LOGIC ---
    if 'rankings' not in st.session_state: 
        st.session_state.rankings = {b['beer_id']: None for _, b in beers.iterrows()}
    
    used_ranks = [v for v in st.session_state.rankings.values() if v is not None]
    
    # Render Beer list for ranking
    for _, b in beers.iterrows():
        st.markdown("---")
        col1, col2 = st.columns([1, 2])
        
        img_path = os.path.join(UPLOAD_DIR, f"{b['beer_id']}.jpg")
        if os.path.exists(img_path): 
            col1.image(img_path, width=150)
        else:
            col1.info("No Photo")
        
        with col2:
            # Beer Name Display Logic
            s_name = b['beer_name_scraped']
            m_name = b['beer_name_manual']
            
            if not pd.isna(s_name) and str(s_name).strip() != "":
                name_display = s_name
            elif not pd.isna(m_name) and str(m_name).strip() != "":
                name_display = m_name
            else:
                name_display = f"Beer {b['beer_id']}"

            st.subheader(name_display)
            st.caption(f"ID: {b['beer_id']}")
            
            curr = st.session_state.rankings[b['beer_id']]
            # Only show ranks that aren't taken, unless it's the rank currently assigned to THIS beer
            avail = [i for i in range(1, len(beers)+1) if i not in used_ranks or i == curr]
            
            choice = st.selectbox(
                f"Rank for {b['beer_id']}", 
                options=["-"] + sorted(avail), 
                index=0 if curr is None else sorted(avail).index(curr) + 1,
                key=f"sel_{b['beer_id']}"
            )
            
            if choice != "-" and st.session_state.rankings[b['beer_id']] != choice:
                st.session_state.rankings[b['beer_id']] = choice
                st.rerun()

    # --- 4. SUBMISSION ---
    st.markdown("### Done?")
    if st.button("Submit Final Rankings", use_container_width=True, type="primary"):
        if None in st.session_state.rankings.values(): 
            st.error("Please rank ALL beers before submitting!")
        else:
            with get_connection() as conn:
                # Clear existing votes for this user in this session
                conn.execute("DELETE FROM ratings WHERE taster_id=? AND beer_key LIKE ?", (t_id, f"{curr_tasting}-%"))
                
                for b_id, rank in st.session_state.rankings.items():
                    # Calculate points (Reverse of rank: 1st place gets highest points)
                    points = (len(beers) + 1) - rank
                    conn.execute("""
                        INSERT INTO ratings (beer_key, taster_id, points_assigned) 
                        VALUES (?, ?, ?)
                    """, (b_id, t_id, points))
                
                conn.commit()
            
            # Clean up rankings from state so the next voter/session starts fresh
            if 'rankings' in st.session_state:
                del st.session_state.rankings
                
            st.success(f"Scores for {actual_name} recorded! Redirecting...")
            
            # Change "pages/leaderboard.py" to your actual filename if it differs
            st.switch_page("pages/leaderboard.py")