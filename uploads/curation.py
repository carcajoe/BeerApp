import streamlit as st
import pandas as pd
import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_NAME = os.path.join(BASE_DIR, "beer_tracker.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

def get_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;") 
    return conn

# --- BREWERY EDITING MODULE ---
@st.dialog("Manage Breweries", width="large")
def edit_breweries_dialog():
    with get_connection() as conn:
        existing_breweries = pd.read_sql("SELECT brewery_id, brewery_name FROM breweries ORDER BY brewery_name", conn)
        try:
            countries_df = pd.read_sql("SELECT country_code, country_name FROM countries ORDER BY country_name", conn)
        except:
            countries_df = pd.DataFrame([["US", "United States"], ["HU", "Hungary"]], columns=["country_code", "country_name"])
    
    mode = st.radio("Action", ["Edit Existing", "Add New"], horizontal=True)
    init = {"name": "", "group": "", "city": "", "country_code": "US", "notes": ""}
    sel_id = None

    if mode == "Edit Existing":
        choice = st.selectbox("Select Brewery", options=existing_breweries['brewery_name'].tolist())
        if choice:
            sel_id = existing_breweries[existing_breweries['brewery_name'] == choice]['brewery_id'].values[0]
            with get_connection() as conn:
                conn.row_factory = sqlite3.Row
                b = conn.execute("SELECT * FROM breweries WHERE brewery_id = ?", (int(sel_id),)).fetchone()
                if b:
                    init = {"name": b['brewery_name'], "group": b['group_name'], "city": b['city'], "country_code": b['country_code'], "notes": b['notes']}

    new_name = st.text_input("Brewery Name", value=init["name"])
    c1, c2 = st.columns(2)
    new_group = c1.text_input("Group Name", value=init["group"])
    new_city = c2.text_input("City", value=init["city"])
    
    c_list = countries_df['country_name'].tolist()
    c_idx = countries_df[countries_df['country_code'] == init["country_code"]].index[0] if init["country_code"] in countries_df['country_code'].values else 0
    new_c_name = st.selectbox("Country", options=c_list, index=int(c_idx))
    new_c_code = countries_df[countries_df['country_name'] == new_c_name]['country_code'].values[0]
    new_notes = st.text_area("Notes", value=init["notes"])

    if st.button("Save Brewery", use_container_width=True):
        with get_connection() as conn:
            if mode == "Edit Existing":
                conn.execute("UPDATE breweries SET brewery_name=?, group_name=?, city=?, country_code=?, notes=? WHERE brewery_id=?", 
                             (new_name, new_group, new_city, new_c_code, new_notes, int(sel_id)))
            else:
                conn.execute("INSERT INTO breweries (brewery_name, group_name, city, country_code, notes) VALUES (?, ?, ?, ?, ?)", 
                             (new_name, new_group, new_city, new_c_code, new_notes))
            conn.commit()
        st.success("Brewery Updated!")
        st.rerun()

# --- MAIN PAGE LOGIC ---
st.header("🛠️ Admin Curation")
if st.button("🏭 Manage Breweries", use_container_width=True):
    edit_breweries_dialog()
st.divider()

with get_connection() as conn:
    events_df = pd.read_sql("SELECT tasting_no, title FROM events ORDER BY tasting_no DESC", conn)
    styles = pd.read_sql("SELECT id, l3_substyle FROM styles ORDER BY l3_substyle", conn)
    breweries = pd.read_sql("SELECT brewery_id, brewery_name FROM breweries ORDER BY brewery_name", conn)

if not events_df.empty:
    events_df['display'] = events_df.apply(lambda x: f"#{x['tasting_no']} - {x['title']}", axis=1)
    sel_ev = st.selectbox("Select Event", options=events_df['display'].tolist())
    target_t = int(events_df[events_df['display'] == sel_ev]['tasting_no'].values[0])

    with get_connection() as conn:
        beers = pd.read_sql("""
            SELECT b.*, m.beer_event_position, m.position_in_session 
            FROM beers b 
            JOIN beer_event_mapping m ON b.beer_id = m.beer_id 
            WHERE m.tasting_no = ?
            ORDER BY m.position_in_session ASC
        """, conn, params=(target_t,))

    st.subheader(f"Editing {len(beers)} beers")
    for _, beer in beers.iterrows():
        bid = beer['beer_id']
        display_pos = beer['beer_event_position']
        h_name = beer['beer_name_scraped'] or beer['beer_name_manual'] or "Unnamed Beer"

        with st.expander(f"📝 {h_name} (Pos: {beer['position_in_session']})"):
            c_left, c_right = st.columns([1, 3])
            
            # Use the position string (14-1) to find the local image
            img_file = os.path.join(UPLOAD_DIR, f"{display_pos}.jpg")
            if os.path.exists(img_file):
                c_left.image(img_file, use_container_width=True)
            
            with c_right:
                n1, n2 = st.columns(2)
                new_man = n1.text_input("Manual Name", value=beer['beer_name_manual'] or "", key=f"nm_{bid}")
                new_scr = n2.text_input("Scraped Name", value=beer['beer_name_scraped'] or "", key=f"ns_{bid}")
                
                d1, d2 = st.columns(2)
                # Style Selection
                s_list = styles['l3_substyle'].tolist()
                s_idx = s_list.index(styles[styles['id'] == beer['style_id']]['l3_substyle'].values[0]) if beer['style_id'] in styles['id'].values else 0
                sel_style = d1.selectbox("Style", s_list, index=s_idx, key=f"ds_{bid}")
                
                # Brewery Selection
                b_list = breweries['brewery_name'].tolist()
                b_idx = b_list.index(breweries[breweries['brewery_id'] == beer['brewery_id']]['brewery_name'].values[0]) if beer['brewery_id'] in breweries['brewery_id'].values else 0
                sel_brew = d2.selectbox("Brewery", b_list, index=b_idx, key=f"db_{bid}")
                
                a1, a2, a3 = st.columns(3)
                new_abv = a1.number_input("ABV", value=float(beer['abv'] or 0.0), key=f"av_{bid}")
                new_us = a2.number_input("Untappd Score", value=float(beer['untappd_score'] or 0.0), key=f"us_{bid}")
                new_bs = a3.number_input("Brewver Score", value=float(beer['brewver_score'] or 0.0), key=f"bs_{bid}")
                
                new_u_url = st.text_input("Untappd URL", value=beer['untappd_url'] or "", key=f"uu_{bid}")
                new_desc = st.text_area("Description", value=beer['description'] or "", key=f"de_{bid}")
                
                if st.button("💾 Save master beer details", key=f"btn_{bid}", use_container_width=True):
                    f_sid = int(styles[styles['l3_substyle'] == sel_style]['id'].values[0])
                    f_bid = int(breweries[breweries['brewery_name'] == sel_brew ]['brewery_id'].values[0])
                    with get_connection() as conn:
                        conn.execute("""
                            UPDATE beers SET 
                            beer_name_manual=?, beer_name_scraped=?, style_id=?, brewery_id=?, 
                            abv=?, untappd_score=?, brewver_score=?, 
                            untappd_url=?, description=? WHERE beer_id=?
                        """, (new_man, new_scr, f_sid, f_bid, new_abv, new_us, new_bs, new_u_url, new_desc, bid))
                        conn.commit()
                    st.success(f"Updated {h_name}!")
                    st.rerun()