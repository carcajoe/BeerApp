import streamlit as st
import sqlite3
import os
import io
from PIL import Image

# --- CONFIGURATION & DATABASE ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_NAME = os.path.join(BASE_DIR, "beer_tracker.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

def get_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;") 
    return conn

# --- UTILITY: IMAGE COMPRESSION ---
def compress_image(uploaded_file):
    img = Image.open(uploaded_file)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=70, optimize=True)
    return buffer.getvalue()

# --- DIALOG: CREATE NEW EVENT ---
@st.dialog("Close current and Open New Event")
def open_new_event_dialog():
    with get_connection() as conn:
        max_tasting_row = conn.execute("SELECT MAX(tasting_no) FROM events").fetchone()
        max_tasting = max_tasting_row[0] if max_tasting_row and max_tasting_row[0] else 0
        next_tasting = max_tasting + 1

    st.write(f"This will finalize previous sessions and start **Session #{next_tasting}**.")
    
    new_title = st.text_input("Event Title", placeholder="e.g. Easter Stout Extravaganza")
    new_date = st.date_input("Event Date")
    new_loc = st.text_input("Location", value="Budapest")
    
    if st.button("Save & Start New Session", use_container_width=True):
        if new_title:
            with get_connection() as conn:
                conn.execute("""
                    INSERT INTO events (tasting_no, title, date, location) 
                    VALUES (?, ?, ?, ?)
                """, (next_tasting, new_title, str(new_date), new_loc))
                conn.commit()
            
            st.session_state.current_tasting = next_tasting
            st.success(f"Session #{next_tasting} is now active!")
            st.rerun()
        else:
            st.error("Please provide a title for the event.")

# --- PAGE LOGIC ---
# 1. Initialize Session State
if 'current_tasting' not in st.session_state:
    with get_connection() as conn:
        last_ev_row = conn.execute("SELECT MAX(tasting_no) FROM events").fetchone()
        st.session_state.current_tasting = last_ev_row[0] if last_ev_row and last_ev_row[0] else 1

curr_tasting = st.session_state.current_tasting

# 2. Header & New Event Button
header_container = st.container()
col_h, col_btn = header_container.columns([3, 1])

col_h.title("📸 Register New Beer")

if col_btn.button("🆕 New Event", use_container_width=True, type="primary"):
    open_new_event_dialog()

st.info(f"📍 Currently adding to: **Session #{curr_tasting}**")

# 3. Beer Registration Form
with st.form("add_beer_form", clear_on_submit=True):
    file = st.file_uploader("Snap or Upload Photo", type=['jpg', 'jpeg', 'png'])
    temp_name = st.text_input("Manual Beer Name / Reference")
    submit = st.form_submit_button("🚀 Upload to Server", use_container_width=True)

    if submit:
        if not file or not temp_name:
            st.error("Missing data: Please provide both a photo and a name.")
        else:
            try:
                img_data = compress_image(file)
                
                with get_connection() as conn:
                    # Find max suffix for current session
                    prefix = f"{curr_tasting}-%"
                    cursor = conn.execute("""
                        SELECT MAX(CAST(SUBSTR(beer_id, INSTR(beer_id, '-') + 1) AS INTEGER))
                        FROM beers 
                        WHERE beer_id LIKE ?
                    """, (prefix,))
                    
                    max_val = cursor.fetchone()[0]
                    next_seq = (max_val + 1) if max_val is not None else 1
                    
                    b_id = f"{curr_tasting}-{next_seq}"
                    db_path = f"uploads/{b_id}.jpg"
                    
                    conn.execute("""
                        INSERT INTO beers (beer_id, beer_name_manual, beer_image_url, country) 
                        VALUES (?, ?, ?, ?)
                    """, (b_id, temp_name, db_path, 'Unknown'))
                    
                    save_path = os.path.join(UPLOAD_DIR, f"{b_id}.jpg")
                    with open(save_path, "wb") as f:
                        f.write(img_data)
                    
                    conn.commit()
                    
                st.success(f"✅ Registered: {temp_name} as **{b_id}**")
                st.balloons()
                
            except Exception as e:
                st.error(f"❌ System Error: {e}")