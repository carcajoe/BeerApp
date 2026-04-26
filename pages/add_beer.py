import streamlit as st
import sqlite3
import os
import io
from PIL import Image

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_NAME = os.path.join(BASE_DIR, "beer_tracker.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

def get_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;") 
    return conn

def compress_image(uploaded_file):
    img = Image.open(uploaded_file)
    if img.mode in ("RGBA", "P"): 
        img = img.convert("RGB")
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=70, optimize=True)
    return buffer.getvalue()

# --- SESSION HANDLING ---
if 'current_tasting' not in st.session_state:
    with get_connection() as conn:
        last_ev = conn.execute("SELECT MAX(tasting_no) FROM events").fetchone()
        st.session_state.current_tasting = last_ev[0] if last_ev and last_ev[0] else 1

curr_tasting = st.session_state.current_tasting

# --- UI HEADER ---
st.title("📸 Register New Beer")

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    st.info(f"📍 Current Session: #{curr_tasting}")

# --- ACTION: NEW EVENT MODAL ---
with col2:
    if st.button("🆕 New Event", use_container_width=True):
        st.session_state.show_new_event_modal = True

if st.session_state.get('show_new_event_modal'):
    with st.expander("📝 Start New Session", expanded=True):
        with st.form("new_event_form"):
            new_theme = st.text_input("Theme", placeholder="e.g. Belgian Classics")
            new_date = st.date_input("Date")
            c1, c2 = st.columns(2)
            if c1.form_submit_button("Start Session"):
                with get_connection() as conn:
                    new_no = curr_tasting + 1
                    conn.execute(
                        "INSERT INTO events (tasting_no, theme, date) VALUES (?, ?, ?)",
                        (new_no, new_theme, new_date.strftime('%Y-%m-%d'))
                    )
                    conn.commit()
                    st.session_state.current_tasting = new_no
                    st.session_state.show_new_event_modal = False
                    st.rerun()
            if c2.form_submit_button("Cancel"):
                st.session_state.show_new_event_modal = False
                st.rerun()

# --- ACTION: RESET EVENT (CLEAN DATA & FILES) ---
with col3:
    if st.button("🗑️ Reset Event", type="secondary", use_container_width=True):
        st.session_state.confirm_reset = True

if st.session_state.get('confirm_reset'):
    st.error(f"🚨 Wiping Session #{curr_tasting}: All beers, images, and ratings will be deleted.")
    rc1, rc2 = st.columns(2)
    if rc1.button("🔥 YES, DELETE EVERYTHING", type="primary", use_container_width=True):
        try:
            with get_connection() as conn:
                # 1. Delete Ratings using the new schema columns
                # This prevents ratings from being 'inherited' by new beers after reset
                conn.execute("DELETE FROM ratings WHERE tasting_no = ?", (curr_tasting,))
                
                # 2. Get list of beers to clean up files and records
                beers = conn.execute("""
                    SELECT b.beer_id, m.beer_event_position 
                    FROM beers b
                    JOIN beer_event_mapping m ON b.beer_id = m.beer_id
                    WHERE m.tasting_no = ?
                """, (curr_tasting,)).fetchall()
                
                for b_id, b_pos in beers:
                    # Physical Image Cleanup
                    img_path = os.path.join(UPLOAD_DIR, f"{b_pos}.jpg")
                    if os.path.exists(img_path):
                        os.remove(img_path)
                    
                    # Delete the actual beer record
                    conn.execute("DELETE FROM beers WHERE beer_id = ?", (b_id,))
                
                # 3. Clear the mapping table
                conn.execute("DELETE FROM beer_event_mapping WHERE tasting_no = ?", (curr_tasting,))
                conn.commit()
                
            st.session_state.confirm_reset = False
            st.success("Session reset complete.")
            st.rerun()
        except Exception as e:
            st.error(f"Reset failed: {e}")
    if rc2.button("Cancel", use_container_width=True):
        st.session_state.confirm_reset = False
        st.rerun()

st.divider()

# --- MAIN UPLOAD FORM ---
with st.form("add_beer_form", clear_on_submit=True):
    file = st.file_uploader("Capture/Upload Label", type=['jpg', 'jpeg', 'png'])
    temp_name = st.text_input("Beer Name / Placeholder")
    submit = st.form_submit_button("🚀 Register Beer", use_container_width=True)

    if submit and file and temp_name:
        try:
            img_data = compress_image(file)
            with get_connection() as conn:
                # 1. Create the master beer record
                cursor = conn.execute("INSERT INTO beers (beer_name_manual) VALUES (?)", (temp_name,))
                new_id = cursor.lastrowid
                
                # 2. Determine sequence within current session
                pos_cursor = conn.execute("""
                    SELECT COALESCE(MAX(position_in_session), 0) + 1 
                    FROM beer_event_mapping WHERE tasting_no = ?
                """, (curr_tasting,))
                next_pos = pos_cursor.fetchone()[0]
                
                # 3. Set path strings (using legacy hyphenated format for filenames)
                b_pos_str = f"{curr_tasting}-{next_pos}"
                db_path = f"uploads/{b_pos_str}.jpg"
                
                # 4. Link everything
                conn.execute("UPDATE beers SET beer_image_url = ? WHERE beer_id = ?", (db_path, new_id))
                conn.execute("""
                    INSERT INTO beer_event_mapping 
                    (beer_id, tasting_no, position_in_session, beer_event_position) 
                    VALUES (?, ?, ?, ?)
                """, (new_id, curr_tasting, next_pos, b_pos_str))
                
                # 5. Write file to disk
                with open(os.path.join(UPLOAD_DIR, f"{b_pos_str}.jpg"), "wb") as f:
                    f.write(img_data)
                
                conn.commit()
                st.success(f"✅ Registered '{temp_name}' at Position {next_pos}")
                st.balloons()
        except Exception as e:
            st.error(f"Upload failed: {e}")