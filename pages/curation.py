import streamlit as st
import pandas as pd
import sqlite3
import os

# --- CONFIGURATION & DATABASE ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_NAME = os.path.join(BASE_DIR, "beer_tracker.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

def get_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;") 
    return conn

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

# Placeholder for brewery dialog if not defined elsewhere
def edit_breweries_dialog():
    st.warning("Brewery management dialog function needed.")

# --- PAGE LOGIC ---
st.header("🛠️ Admin Curation")

# Action Row for Dialogs
col_act1, col_act2 = st.columns(2)

if col_act1.button("🏭 Manage Breweries", use_container_width=True):
    edit_breweries_dialog()
    
if col_act2.button("🆕 New Event", use_container_width=True, type="primary"):
    open_new_event_dialog()

st.divider()

with get_connection() as conn:
    events_df = pd.read_sql("SELECT tasting_no, title, date FROM events ORDER BY tasting_no DESC", conn)
    styles = pd.read_sql("SELECT id, l3_substyle FROM styles ORDER BY l3_substyle", conn)
    breweries = pd.read_sql("SELECT brewery_id, brewery_name FROM breweries ORDER BY brewery_name", conn)

if events_df.empty:
    st.warning("No events found.")
else:
    events_df['display'] = events_df.apply(lambda x: f"#{x['tasting_no']} - {x['title']}", axis=1)
    sel_ev = st.selectbox("Select Event", options=events_df['display'].tolist())
    target_t = int(events_df[events_df['display'] == sel_ev]['tasting_no'].values[0])

    with get_connection() as conn:
        beers = pd.read_sql("SELECT * FROM beers WHERE beer_id LIKE ?", conn, params=(f"{target_t}-%",))

    st.subheader(f"Editing {len(beers)} beers")
    
    for _, beer in beers.iterrows():
        bid = beer['beer_id']
        
        s_name = beer['beer_name_scraped']
        m_name = beer['beer_name_manual']
        
        if not pd.isna(s_name) and str(s_name).strip() != "":
            h_name = s_name
        elif not pd.isna(m_name) and str(m_name).strip() != "":
            h_name = m_name
        else:
            h_name = "Unnamed Beer"

        with st.expander(f"📝 {h_name} ({bid})"):
            try:
                c_left, c_right = st.columns([1, 3])
                
                # --- IMAGE COLUMN ---
                img_file = os.path.join(UPLOAD_DIR, f"{bid}.jpg")
                if os.path.exists(img_file):
                    c_left.image(img_file, use_container_width=True)
                else:
                    c_left.warning("No Image")
                
                current_img_url = "" if pd.isna(beer['beer_image_url']) else beer['beer_image_url']
                new_img_path = c_left.text_input("Path", value=current_img_url, key=f"ip_{bid}")
                
                with c_right:
                    n1, n2 = st.columns(2)
                    val_manual = "" if pd.isna(m_name) else m_name
                    val_scraped = "" if pd.isna(s_name) else s_name
                    
                    new_man = n1.text_input("Manual Name", value=val_manual, key=f"nm_{bid}")
                    new_scr = n2.text_input("Scraped Name", value=val_scraped, key=f"ns_{bid}")
                    
                    d1, d2 = st.columns(2)
                    s_list = styles['l3_substyle'].tolist()
                    try:
                        if pd.isna(beer['style_id']): raise ValueError
                        s_val = styles[styles['id'] == beer['style_id']]['l3_substyle'].values[0]
                        s_idx = s_list.index(s_val)
                    except: s_idx = 0
                    
                    b_list = breweries['brewery_name'].tolist()
                    try:
                        if pd.isna(beer['brewery_id']): raise ValueError
                        b_val = breweries[breweries['brewery_id'] == beer['brewery_id']]['brewery_name'].values[0]
                        b_idx = b_list.index(b_val)
                    except: b_idx = 0
                    
                    sel_style = d1.selectbox("Style", s_list, index=s_idx, key=f"ds_{bid}")
                    sel_brew = d2.selectbox("Brewery", b_list, index=b_idx, key=f"db_{bid}")
                    
                    a1, a2, a3 = st.columns(3)
                    new_abv = a1.number_input("ABV", value=float(0.0 if pd.isna(beer['abv']) else beer['abv']), key=f"av_{bid}")
                    new_us = a2.number_input("Untappd", value=float(0.0 if pd.isna(beer['untappd_score']) else beer['untappd_score']), key=f"us_{bid}")
                    new_bs = a3.number_input("Brewver", value=float(0.0 if pd.isna(beer['brewver_score']) else beer['brewver_score']), key=f"bs_{bid}")
                    
                    val_u_url = "" if pd.isna(beer['untappd_url']) else beer['untappd_url']
                    new_u_url = st.text_input("Untappd URL", value=val_u_url, key=f"uu_{bid}")
                    
                    val_desc = "" if pd.isna(beer['description']) else beer['description']
                    new_desc = st.text_area("Description", value=val_desc, key=f"de_{bid}")
                    
                    if st.button("Save", key=f"btn_{bid}", use_container_width=True):
                        f_sid = int(styles[styles['l3_substyle'] == sel_style]['id'].values[0])
                        f_bid = int(breweries[breweries['brewery_name'] == sel_brew ]['brewery_id'].values[0])
                        
                        with get_connection() as conn:
                            conn.execute("""
                                UPDATE beers SET 
                                beer_name_manual=?, beer_name_scraped=?, style_id=?, brewery_id=?, 
                                abv=?, beer_image_url=?, untappd_score=?, brewver_score=?, 
                                untappd_url=?, description=? WHERE beer_id=?
                            """, (new_man, new_scr, f_sid, f_bid, new_abv, new_img_path, new_us, new_bs, new_u_url, new_desc, bid))
                            conn.commit()
                        st.success("Saved!")
                        st.rerun()
            except Exception as e:
                st.error(f"Error loading fields for {bid}: {e}")