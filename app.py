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
    # Responsive container logic: 95% on mobile, max 720px on desktop
    css = """
    <style>
        /* 1. Global Reset & Centering */
        .stApp { align-items: center; }
        
        .main-container {
            width: 95%;
            max-width: 720px;
            margin: 0 auto;
        }

        /* 2. Responsive Image Lock */
        .responsive-img {
            width: 100%;
            max-width: 720px;
            height: auto;
            border-radius: 12px;
            display: block;
            margin: 0 auto 20px auto;
        }

        /* 3. Text & Widget Centering */
        h1, h2, h3, .stMarkdown { text-align: center !important; }
        [data-testid="stWidgetLabel"] { text-align: center !important; justify-content: center; }
        
        /* 4. Fix Sidebar Interference on Login */
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
    st.set_page_config(page_title="Login", page_icon="🍺", layout="centered")
    apply_layout_styles(is_login=True)
    
    # Image Header
    out_b64 = get_base64_img(os.path.join(BASE_DIR, "OUT.jpg"))
    st.markdown(f'<img src="data:image/jpeg;base64,{out_b64}" class="responsive-img">', unsafe_allow_html=True)
    
    st.markdown("<h1>Beer Vault Access</h1>", unsafe_allow_html=True)
    
    # Use a container for the form to ensure CSS targeting works
    with st.container():
        with st.form("login_form", clear_on_submit=False):
            with get_connection() as conn:
                try:
                    tasters_df = pd.read_sql("SELECT id, name, is_admin FROM tasters WHERE active = 'Y' ORDER BY name ASC", conn)
                except:
                    tasters_df = pd.DataFrame(columns=['id', 'name', 'is_admin'])
            
            user_list = tasters_df['name'].tolist()
            selected_user = st.selectbox("Who are you?", [""] + user_list)
            password = st.text_input("Access Key", type="password")
            
            if st.form_submit_button("Unlock & Enter", use_container_width=True):
                if selected_user:
                    user_data = tasters_df[tasters_df['name'] == selected_user].iloc[0]
                    secret = "ADMIN_PASSWORD" if bool(user_data['is_admin']) else "USER_PASSWORD"
                    
                    if password == st.secrets[secret]:
                        st.session_state.update({
                            'current_taster': user_data['name'],
                            'taster_id': int(user_data['id']),
                            'is_admin': bool(user_data['is_admin'])
                        })
                        update_benchmarks()
                        st.rerun()
                    else:
                        st.error("Invalid Key")
    st.stop()

# --- 2. MAIN APP (IN) ---
st.set_page_config(page_title="Beer Tracker", page_icon="🍺", layout="wide")
apply_layout_styles(is_login=False)

# Sidebar: User Info ALWAYS at the top
with st.sidebar:
    st.markdown(f"### 👤 {st.session_state.current_taster}")
    if st.button("Logout", use_container_width=True):
        st.session_state.current_taster = None
        st.rerun()
    st.divider()

# Header
in_b64 = get_base64_img(os.path.join(BASE_DIR, "IN.jpg"))
st.markdown(f'<div class="main-container"><img src="data:image/jpeg;base64,{in_b64}" class="responsive-img"></div>', unsafe_allow_html=True)

# Navigation
pages = [
    st.Page("pages/dashboard.py", title="Dashboard", icon="🗺️", default=True),
    st.Page("pages/rate_beers.py", title="Rate Beers", icon="⭐"),
    st.Page("pages/leaderboard.py", title="Leaderboard", icon="🏆"),
    st.Page("pages/analytics.py", title="Hall of Fame", icon="📈")
]

if st.session_state.is_admin:
    pages.extend([
        st.Page("pages/add_beer.py", title="Add Beer", icon="📸"),
        st.Page("pages/curation.py", title="Admin Curation", icon="🛠️")
    ])

st.navigation(pages).run()