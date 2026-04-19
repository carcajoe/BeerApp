import streamlit as st
import sqlite3
import os
import io
from PIL import Image

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_NAME = os.path.join(BASE_DIR, "beer_tracker.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

def get_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;") 
    return conn

def compress_image(uploaded_file):
    img = Image.open(uploaded_file)
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=70, optimize=True)
    return buffer.getvalue()

# --- SESSION HANDLING ---
if 'current_tasting' not in st.session_state:
    with get_connection() as conn:
        last_ev = conn.execute("SELECT MAX(tasting_no) FROM events").fetchone()
        st.session_state.current_tasting = last_ev[0] if last_ev and last_ev[0] else 1

curr_tasting = st.session_state.current_tasting

st.title("📸 Register New Beer")
st.info(f"📍 Adding to Session #{curr_tasting}")

with st.form("add_beer_form", clear_on_submit=True):
    file = st.file_uploader("Photo", type=['jpg', 'jpeg', 'png'])
    temp_name = st.text_input("Beer Name")
    submit = st.form_submit_button("🚀 Upload", use_container_width=True)

    if submit and file and temp_name:
        try:
            img_data = compress_image(file)
            with get_connection() as conn:
                # 1. Create Beer
                cursor = conn.execute("INSERT INTO beers (beer_name_manual) VALUES (?)", (temp_name,))
                new_internal_id = cursor.lastrowid
                
                # 2. Get Next Position (Simple integer math now!)
                pos_cursor = conn.execute("""
                    SELECT COALESCE(MAX(position_in_session), 0) + 1 
                    FROM beer_event_mapping WHERE tasting_no = ?
                """, (curr_tasting,))
                next_pos = pos_cursor.fetchone()[0]
                
                # Create the string for the legacy image system
                b_pos_str = f"{curr_tasting}-{next_pos}"
                db_path = f"uploads/{b_pos_str}.jpg"
                
                # 3. Save Image & Update Paths
                conn.execute("UPDATE beers SET beer_image_url = ? WHERE beer_id = ?", (db_path, new_internal_id))
                
                # 4. Insert into clean Mapping Table
                conn.execute("""
                    INSERT INTO beer_event_mapping 
                    (beer_id, tasting_no, position_in_session, beer_event_position) 
                    VALUES (?, ?, ?, ?)
                """, (new_internal_id, curr_tasting, next_pos, b_pos_str))
                
                with open(os.path.join(UPLOAD_DIR, f"{b_pos_str}.jpg"), "wb") as f:
                    f.write(img_data)
                
                conn.commit()
                st.success(f"✅ Registered {temp_name} at position {next_pos}")
                st.balloons()
        except Exception as e:
            st.error(f"Error: {e}")