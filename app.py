import streamlit as st
import sqlite3
import pandas as pd
import numpy as np
import os
import base64
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
        'current_taster': None, 'is_admin': False, 'taster_id': None,
        'current_tasting': 1, 'benchmarks': None
    })

def update_benchmarks():
    with get_connection() as conn:
        try:
            xp_df = pd.read_sql("SELECT taster_id, COUNT(DISTINCT beer_key) as count FROM ratings GROUP BY taster_id", conn)
            st.session_state['benchmarks'] = {
                "xp": np.percentile(xp_df['count'], [20, 80]) if not xp_df.empty else [2, 10],
                "strength": [8, 25], "participation": [6, 12], "quality": [0.65, 0.82]
            }
        except: pass

def get_base64_img(path):
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except: return ""

# --- CLEAN SHEET RESPONSIVE LAYOUT ---
def apply_layout_styles(is_login=False):
    css = """
    <style>
        .stApp { align-items: center; }
        .main-container { width: 95%; max-width: 720px; margin: 0 auto; }
        .responsive-img {
            width: 100%;
            max-width: 720px;
            height: auto;
            border-radius: 12px;
            display: block;
            margin: 0 auto 20px auto;
        }
        h1, h2, h3, .stMarkdown { text-align: center !important; }
        [data-testid="stWidgetLabel"] { text-align: center !important; justify-content: center; }
    """
    if is_login:
        css += """
            [data-testid="stSidebar"] { display: none !important; }
            [data-testid="stAppViewContainer"] { padding-left: 0 !important; }
            section[data-testid="stMain"] { padding: 0 !important; }
        """
    css += "</style>"
    st.markdown(css, unsafe_allow_html=True)

# --- 1. LOGIN SCREEN (OUT) ---
if st.session_state.current_taster is None:
    st.set_page_config(page_title="Beer Vault Login", page_icon="🍺", layout="centered")
    apply_layout_styles(is_login=True)
    
    out_b64 = get_base64_img(os.path.join(BASE_DIR, "OUT.jpg"))
    st.markdown(f'<img src="data:image/jpeg;base64,{out_b64}" class="responsive-img">', unsafe_allow_html=True)
    st.markdown("<h1>Beer Vault Access</h1>", unsafe_allow_html=True)
    
    with st.form("login_form"):
        st.markdown("### Who are you?")
        with get_connection() as conn:
            try:
                # Query keeps logic to order by session count[cite: 3]
                query = """
                    SELECT t.id, t.name, t.is_admin, 
                           COUNT(DISTINCT SUBSTR(m.beer_event_position, 1, INSTR(m.beer_event_position, '-') - 1)) as sessions
                    FROM tasters t
                    LEFT JOIN ratings r ON t.id = r.taster_id
                    LEFT JOIN beer_event_mapping m ON r.beer_key = m.beer_event_position
                    WHERE t.active = 'Y'
                    GROUP BY t.id
                    ORDER BY sessions DESC, t.name ASC
                """
                tasters_df = pd.read_sql(query, conn)
                last_ev = conn.execute("SELECT MAX(tasting_no) FROM events").fetchone()
                latest_session = last_ev[0] if last_ev and last_ev[0] else 1
            except:
                tasters_df = pd.DataFrame(columns=['id', 'name', 'is_admin', 'sessions'])
                latest_session = 1
        
        # Display only Name, but maintains order from tasters_df[cite: 3]
        taster_options = tasters_df['name'].tolist() if not tasters_df.empty else []
        name_to_data = {row['name']: row for _, row in tasters_df.iterrows()}

        selected_label = st.selectbox("Select your profile:", [""] + taster_options)
        pwd_input = st.text_input("Password", type="password")
        
        if st.form_submit_button("Unlock & Enter Journey", use_container_width=True):
            if selected_label and selected_label != "":
                user_row = name_to_data[selected_label]
                req_secret = "ADMIN_PASSWORD" if bool(user_row['is_admin']) else "USER_PASSWORD"
                
                if pwd_input == st.secrets[req_secret]:
                    st.session_state.update({
                        'current_taster': user_row['name'],
                        'taster_id': int(user_row['id']),
                        'is_admin': bool(user_row['is_admin']),
                        'current_tasting': latest_session
                    })
                    update_benchmarks()
                    st.rerun()
                else:
                    st.error("🚫 Invalid Key")
    st.stop()

# --- 2. MAIN APP (IN) ---
st.set_page_config(page_title="Beer Tracker Elite", page_icon="🍺", layout="wide")
apply_layout_styles(is_login=False)

with st.sidebar:
    st.markdown(f"### 👤 {st.session_state.current_taster}")
    if st.button("🚪 Log Out", use_container_width=True):
        st.session_state.current_taster = None
        st.rerun()
    st.divider()

in_b64 = get_base64_img(os.path.join(BASE_DIR, "IN.jpg"))
st.markdown(f'<div class="main-container"><img src="data:image/jpeg;base64,{in_b64}" class="responsive-img"></div>', unsafe_allow_html=True)

pg_dash = st.Page("pages/dashboard.py", title="Dashboard", icon="🗺️", default=True)
pg_rate = st.Page("pages/rate_beers.py", title="Rate Beers", icon="⭐")
pg_lead = st.Page("pages/leaderboard.py", title="Leaderboard", icon="🏆")
pg_hall = st.Page("pages/analytics.py", title="Hall of Fame", icon="📈")
pg_add  = st.Page("pages/add_beer.py", title="Add Beer", icon="📸")
pg_admin = st.Page("pages/curation.py", title="Admin Curation", icon="🛠️")

if st.session_state.is_admin:
    pg = st.navigation({"User": [pg_dash, pg_rate, pg_lead, pg_hall], "Admin": [pg_add, pg_admin]})
else:
    pg = st.navigation([pg_dash, pg_rate, pg_lead, pg_hall])

pg.run()