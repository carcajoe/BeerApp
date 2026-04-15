import streamlit as st
import sqlite3
import pandas as pd
import os
import plotly.express as px
from PIL import Image
import io

# --- 1. CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "beer_tracker.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
TASTER_DIR = os.path.join(BASE_DIR, "assets", "tasters")

def get_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;") 
    return conn

# --- 2. UI HELPERS ---
def get_beer_name(row):
    """Returns Scraped name if exists, otherwise Manual name."""
    if pd.notna(row.get('beer_name_scraped')) and row['beer_name_scraped'] != "":
        return row['beer_name_scraped']
    return row.get('beer_name_manual', "Unknown Beer")

def get_image(filename, folder=UPLOAD_DIR, fallback="default_beer.png"):
    """Handles local image lookups with fallbacks."""
    if filename:
        path = os.path.join(folder, filename)
        if os.path.exists(path):
            return path
    return os.path.join(BASE_DIR, "assets", fallback)

# --- 3. SESSION LOGIC (Bulletproof Parsing) ---
with get_connection() as conn:
    res = conn.execute("SELECT beer_id FROM beers WHERE beer_id LIKE '%-%'").fetchall()
    sessions = []
    if res:
        for r in res:
            try:
                parts = r[0].split('-')
                if parts[0].isdigit():
                    sessions.append(int(parts[0]))
            except (ValueError, IndexError, AttributeError):
                continue
    current_tasting = max(sessions) if sessions else 1

# --- BREWERY EDITING MODULE ---

@st.dialog("Manage Breweries", width="large")
def edit_breweries_dialog():
    with get_connection() as conn:
        # Load existing breweries
        existing_breweries = pd.read_sql("SELECT brewery_id, brewery_name FROM breweries ORDER BY brewery_name", conn)
        # Load countries
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
                conn.row_factory = sqlite3.Row # This prevents the "tuple indices" error
                b = conn.execute("SELECT * FROM breweries WHERE brewery_id = ?", (int(sel_id),)).fetchone()
                if b:
                    init = {
                        "name": b['brewery_name'] or "",
                        "group": b['group_name'] or "",
                        "city": b['city'] or "",
                        "country_code": b['country_code'] or "US",
                        "notes": b['notes'] or ""
                    }

    new_name = st.text_input("Brewery Name", value=init["name"])
    c1, c2 = st.columns(2)
    new_group = c1.text_input("Group Name", value=init["group"])
    new_city = c2.text_input("City", value=init["city"])
    
    c_list = countries_df['country_name'].tolist()
    c_idx = 0
    if init["country_code"] in countries_df['country_code'].values:
        c_idx = countries_df[countries_df['country_code'] == init["country_code"]].index[0]
        
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

# --- 4. STREAMLIT UI SETUP ---
st.set_page_config(page_title="Beer Tracker Elite v2", layout="wide", page_icon="🍺")
st.sidebar.title(f"🍻 Session #{current_tasting}")
page = st.sidebar.radio("Navigation", ["Dashboard", "Add Beer", "Admin Curation", "Rate Beers", "Leaderboard"])

# --- PAGE: DASHBOARD ---
if page == "Dashboard":
    st.title("🗺️ Global Beer Journey")
    
    with get_connection() as conn:
        query = """
        SELECT 
            b.*, 
            s.l1_type, s.l2_category, s.l3_substyle, 
            br.brewery_name, br.group_name, br.city,
            br.lat, br.lon,  -- Added the new coordinate columns
            c.country_name, c.continent, c.is_non_brewing,
            e.tasting_no, e.date as event_date, e.location as event_location, e.title as event_title,
            (SELECT COUNT(DISTINCT r2.taster_id) FROM ratings r2 WHERE r2.beer_key = b.beer_id) as participant_count,
            GROUP_CONCAT(DISTINCT t.name || ': ' || r.points_assigned) as taster_scores,
            GROUP_CONCAT(DISTINCT t.name) as taster_names
        FROM beers b
        LEFT JOIN styles s ON b.style_id = s.id
        LEFT JOIN breweries br ON b.brewery_id = br.brewery_id
        LEFT JOIN countries c ON br.country_code = c.country_code
        LEFT JOIN events e ON CAST(SUBSTR(b.beer_id, 1, INSTR(b.beer_id, '-') - 1) AS INTEGER) = e.tasting_no
        LEFT JOIN ratings r ON b.beer_id = r.beer_key
        LEFT JOIN tasters t ON r.taster_id = t.id
        GROUP BY b.beer_id
        """
        df_raw = pd.read_sql(query, conn)
        tasters_list = pd.read_sql("SELECT name FROM tasters", conn)['name'].tolist()
        # Fetch full country list for the background map logic
        all_countries = pd.read_sql("SELECT country_name, is_non_brewing FROM countries", conn)

    # --- DATA PREP ---
    df_raw['display_name'] = df_raw.apply(
        lambda x: x['beer_name_scraped'] if pd.notna(x['beer_name_scraped']) and str(x['beer_name_scraped']).strip() != "" 
        else (x['beer_name_manual'] if pd.notna(x['beer_name_manual']) else f"Beer {x['beer_id']}"), axis=1
    )
    
    df_raw['event_display'] = df_raw.apply(
        lambda x: f"{x['event_date']} | #{x['tasting_no']} {x['event_title']}" if pd.notna(x['tasting_no']) else "No Event", axis=1
    )

    # --- TOP FILTERS ---
    st.markdown("### 🔍 Filter Journey")
    f_row1_col1, f_row1_col2, f_row1_col3 = st.columns(3)
    f_row2_col1, f_row2_col2, f_row2_col3 = st.columns(3)

    event_options = sorted([opt for opt in df_raw['event_display'].unique() if opt != "No Event"], reverse=True)
    if "No Event" in df_raw['event_display'].unique():
        event_options.append("No Event")
    selected_event = f_row1_col1.multiselect("EventInfo", options=event_options)

    selected_beers = f_row1_col2.multiselect("BeerName", options=sorted(df_raw['display_name'].unique()))
    selected_brewery = f_row1_col3.multiselect("Brewery", options=sorted(df_raw['brewery_name'].dropna().unique()))
    selected_style = f_row2_col1.multiselect("BeerStyle", options=sorted(df_raw['l3_substyle'].dropna().unique()))
    selected_taster = f_row2_col2.multiselect("Taster", options=sorted(tasters_list))
    selected_country = f_row2_col3.multiselect("BeerCountry", options=sorted(df_raw['country_name'].dropna().unique()))

    # --- FILTERING LOGIC ---
    df_filtered = df_raw.copy()
    if selected_event: df_filtered = df_filtered[df_filtered['event_display'].isin(selected_event)]
    if selected_beers: df_filtered = df_filtered[df_filtered['display_name'].isin(selected_beers)]
    if selected_brewery: df_filtered = df_filtered[df_filtered['brewery_name'].isin(selected_brewery)]
    if selected_style: df_filtered = df_filtered[df_filtered['l3_substyle'].isin(selected_style)]
    if selected_country: df_filtered = df_filtered[df_filtered['country_name'].isin(selected_country)]
    if selected_taster:
        df_filtered = df_filtered[df_filtered['taster_names'].apply(lambda x: any(t in str(x).split(',') for t in selected_taster) if pd.notna(x) else False)]

    # Sorting
    df_filtered['session_num'] = df_filtered['beer_id'].str.split('-').str[0].astype(int)
    df_filtered['beer_num'] = df_filtered['beer_id'].str.split('-').str[1].astype(int)
    df_filtered = df_filtered.sort_values(['session_num', 'beer_num'], ascending=[False, False])

    # --- TOP METRICS ---

    # Calculate sessions by excluding ID 0 from the unique count
    session_count = df_filtered[df_filtered['tasting_no'] != 0]['tasting_no'].nunique()

    # Display the metrics
    st.divider()
    m4, m1, m2 = st.columns(3)
    m1.metric("Beers", len(df_filtered))
    m2.metric("Countries", df_filtered['country_name'].nunique())
    m4.metric("Sessions", session_count)

# --- COMBINED MAP SECTION (The "Layout-Level" Fix) ---
    
    # 1. Data Prep
    tasted_counts = df_filtered[df_filtered['country_name'].notna()].groupby('country_name').size().reset_index(name='beer_count')
    city_data = df_filtered[df_filtered['lat'].notna()].groupby(['city', 'lat', 'lon', 'country_name']).size().reset_index(name='city_beer_count')
    
    # Determine if any filter is active
    is_filtered = bool(selected_country or selected_event or selected_beers or selected_brewery or selected_style or selected_taster)

    # 2. THE DATA LAYER (The only thing fitbounds will look at)
    # We initialize with ONLY the tasted countries
    fig = px.choropleth(
        tasted_counts, 
        locations="country_name", 
        locationmode='country names', 
        color="beer_count", 
        color_continuous_scale=[[0, "#FFFFE0"], [0.3, "#FFD700"], [1.0, "#8B4513"]]
    )

    # 3. THE CITY LAYER
    if not city_data.empty:
        city_trace = px.scatter_geo(
            city_data,
            lat='lat', lon='lon',
            size='city_beer_count',
            hover_name='city',
            text='city' if is_filtered else None,
            color_discrete_sequence=["#222222"],
            custom_data=['city', 'city_beer_count', 'country_name']
        ).data[0]
        
        city_trace.update(
            hovertemplate="<b>%{customdata[0]}, %{customdata[2]}</b><br>Beers: %{customdata[1]}<extra></extra>",
            textposition='top center'
        )
        fig.add_trace(city_trace)

    # 4. THE GEOGRAPHIC ENGINE (The Fix)
    fig.update_geos(
        visible=True, 
        resolution=50,
        showcountries=True, 
        countrycolor="#999999", # The borders
        showocean=True, 
        oceancolor="#A2CFFE",
        showland=True, 
        landcolor="#FFFFFF", # Set untasted brewing countries to WHITE at the base level
        # We handle the "Non-brewing" grey by using the frame background or a separate logic
        fitbounds="locations" if is_filtered else False,
        projection_type="natural earth"
    )

    # 5. REMOVE THE WHITE TRACE ENTIRELY
    # Instead of adding a trace for untasted countries (which breaks zoom), 
    # we let 'landcolor' handle the white, and we only color the "Tasted" ones via Choropleth.

    fig.update_layout(
        height=500, 
        margin={"r":0,"t":0,"l":0,"b":0}, 
        coloraxis_showscale=False,
        uirevision=str(is_filtered) # Forces camera reset on filter change
    )
    
    st.plotly_chart(fig, use_container_width=True)

    # --- PAGINATED BEER LIST ---
    st.markdown("### 📋 Beer Details")
    items_per_page = 10
    total_pages = (len(df_filtered) // items_per_page) + (1 if len(df_filtered) % items_per_page > 0 else 0)
    
    if total_pages > 1:
        page_num = st.number_input(f"Page (1 of {total_pages})", min_value=1, max_value=total_pages, step=1)
    else: page_num = 1
        
    start_idx = (page_num - 1) * items_per_page
    df_page = df_filtered.iloc[start_idx : start_idx + items_per_page]

    if df_filtered.empty:
        st.warning("No beers match the filters.")
    else:
        for _, row in df_page.iterrows():
            with st.container():
                c1, c2, c3, c4 = st.columns([1, 3, 2, 2])
                img_path = os.path.join(UPLOAD_DIR, f"{row['beer_id']}.jpg")
                if os.path.exists(img_path): c1.image(img_path, width=100)
                else: c1.info("No Photo")
                
                c2.markdown(f"### {row['display_name']}")
                c2.caption(f"ID: {row['beer_id']} | {row['brewery_name']} ({row['country_name']})")
                c2.write(f"**Style:** {row['l3_substyle'] or 'Unknown'} | **ABV:** {row['abv'] or '?'}%")
                
                c3.markdown(f"**{row['event_title'] or 'Private Tasting'}**")
                c3.write(f"📅 {row['event_date'] or 'N/A'}")
                c3.write(f"👥 {int(row['participant_count'])} Tasters")
                
                c4.markdown("**Ratings**")
                if row['taster_scores']:
                    for s in row['taster_scores'].split(','): c4.caption(f"⭐ {s}")
                else: c4.caption("No ratings")
                st.divider()

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

# --- PAGE: ADD BEER ---
if page == "Add Beer":
    # 1. Initialize Session State
    if 'current_tasting' not in st.session_state:
        with get_connection() as conn:
            last_ev_row = conn.execute("SELECT MAX(tasting_no) FROM events").fetchone()
            st.session_state.current_tasting = last_ev_row[0] if last_ev_row and last_ev_row[0] else 1

    curr_tasting = st.session_state.current_tasting
    
    # 2. Header & New Event Button
    # We place the button in a distinct container to ensure visibility
    header_container = st.container()
    col_h, col_btn = header_container.columns([3, 1])
    
    col_h.title("📸 Register New Beer")
    
    # Check if the button is being rendered
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
                    
# --- PAGE: ADMIN CURATION ---
elif page == "Admin Curation":
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
            
            # --- THE FIX FOR NaN ---
            # We check if names are 'None', empty strings, or Pandas NaN
            s_name = beer['beer_name_scraped']
            m_name = beer['beer_name_manual']
            
            if not pd.isna(s_name) and str(s_name).strip() != "":
                h_name = s_name
            elif not pd.isna(m_name) and str(m_name).strip() != "":
                h_name = m_name
            else:
                h_name = "Unnamed Beer"
            # -----------------------

            with st.expander(f"📝 {h_name} ({bid})"):
                try:
                    c_left, c_right = st.columns([1, 3])
                    
                    # --- IMAGE COLUMN ---
                    img_file = os.path.join(UPLOAD_DIR, f"{bid}.jpg")
                    if os.path.exists(img_file):
                        c_left.image(img_file, use_container_width=True)
                    else:
                        c_left.warning("No Image")
                    
                    # Ensure path text input doesn't show 'nan' either
                    current_img_url = "" if pd.isna(beer['beer_image_url']) else beer['beer_image_url']
                    new_img_path = c_left.text_input("Path", value=current_img_url, key=f"ip_{bid}")
                    
                    with c_right:
                        n1, n2 = st.columns(2)
                        
                        # Use empty strings if the DB value is NaN
                        val_manual = "" if pd.isna(m_name) else m_name
                        val_scraped = "" if pd.isna(s_name) else s_name
                        
                        new_man = n1.text_input("Manual Name", value=val_manual, key=f"nm_{bid}")
                        new_scr = n2.text_input("Scraped Name", value=val_scraped, key=f"ns_{bid}")
                        
                        d1, d2 = st.columns(2)
                        
                        # Style & Brewery safety (Index logic)
                        s_list = styles['l3_substyle'].tolist()
                        try:
                            # Correctly handle NULL/NaN style_id
                            if pd.isna(beer['style_id']): raise ValueError
                            s_val = styles[styles['id'] == beer['style_id']]['l3_substyle'].values[0]
                            s_idx = s_list.index(s_val)
                        except: s_idx = 0
                        
                        b_list = breweries['brewery_name'].tolist()
                        try:
                            # Correctly handle NULL/NaN brewery_id
                            if pd.isna(beer['brewery_id']): raise ValueError
                            b_val = breweries[breweries['brewery_id'] == beer['brewery_id']]['brewery_name'].values[0]
                            b_idx = b_list.index(b_val)
                        except: b_idx = 0
                        
                        sel_style = d1.selectbox("Style", s_list, index=s_idx, key=f"ds_{bid}")
                        sel_brew = d2.selectbox("Brewery", b_list, index=b_idx, key=f"db_{bid}")
                        
                        # ABV & Scores (Using 0.0 if NaN)
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

# --- PAGE: RATE BEERS ---
elif page == "Rate Beers":
    # 1. DYNAMIC SESSION DETECTION
    # Always grab the latest tasting_no from the DB as the default
    with get_connection() as conn:
        last_ev_row = conn.execute("SELECT MAX(tasting_no) FROM events").fetchone()
        latest_db_tasting = last_ev_row[0] if last_ev_row and last_ev_row[0] else 1
    
    # Use session_state if set, otherwise use the absolute latest from DB
    curr_tasting = st.session_state.get('current_tasting', latest_db_tasting)
    
    st.header(f"⭐ Vote - Session {curr_tasting}")
    
    with get_connection() as conn:
        beers = pd.read_sql("SELECT * FROM beers WHERE beer_id LIKE ?", conn, params=(f"{curr_tasting}-%",))
        taster_list = [r[0] for r in conn.execute("SELECT name FROM tasters").fetchall()]
    
    if beers.empty: 
        st.warning(f"No beers found for session #{curr_tasting}.")
        # Optional: Add a button to switch to the latest DB session if stuck
        if st.button("Switch to Latest Session"):
            st.session_state.current_tasting = latest_db_tasting
            st.rerun()
    else:
        user = st.selectbox("Who is voting?", ["Select..."] + taster_list + ["+ New Taster"])
        actual_name = st.text_input("Confirm Name") if user == "+ New Taster" else user

        if actual_name and actual_name != "Select...":
            # --- OVERWRITE CHECK ---
            with get_connection() as conn:
                voted = conn.execute("""
                    SELECT COUNT(*) FROM ratings r 
                    JOIN tasters t ON r.taster_id = t.id 
                    WHERE t.name = ? AND r.beer_key LIKE ?
                """, (actual_name, f"{curr_tasting}-%")).fetchone()[0]
                
            if voted: 
                st.warning("⚠️ You've already voted for this session. Submitting again will update your scores.")

            # --- RANKING LOGIC ---
            if 'rankings' not in st.session_state: 
                st.session_state.rankings = {b['beer_id']: None for _, b in beers.iterrows()}
            
            used_ranks = [v for v in st.session_state.rankings.values() if v is not None]
            
            for _, b in beers.iterrows():
                st.markdown("---")
                col1, col2 = st.columns([1, 2])
                
                img_path = os.path.join(UPLOAD_DIR, f"{b['beer_id']}.jpg")
                if os.path.exists(img_path): 
                    col1.image(img_path, width=150)
                else:
                    col1.info("No Photo")
                
                with col2:
                    # --- THE FIX FOR NaN ---
                    s_name = b['beer_name_scraped']
                    m_name = b['beer_name_manual']
                    
                    if not pd.isna(s_name) and str(s_name).strip() != "":
                        name_display = s_name
                    elif not pd.isna(m_name) and str(m_name).strip() != "":
                        name_display = m_name
                    else:
                        name_display = f"Beer {b['beer_id']}"
                    # -----------------------

                    st.subheader(name_display)
                    st.caption(f"ID: {b['beer_id']}")
                    
                    curr = st.session_state.rankings[b['beer_id']]
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

            # --- SUBMISSION ---
            if st.button("Submit Final Rankings", use_container_width=True):
                if None in st.session_state.rankings.values(): 
                    st.error("Please rank ALL beers before submitting!")
                else:
                    with get_connection() as conn:
                        conn.execute("INSERT OR IGNORE INTO tasters (name) VALUES (?)", (actual_name,))
                        t_id = conn.execute("SELECT id FROM tasters WHERE name=?", (actual_name,)).fetchone()[0]
                        
                        conn.execute("DELETE FROM ratings WHERE taster_id=? AND beer_key LIKE ?", (t_id, f"{curr_tasting}-%"))
                        
                        for b_id, rank in st.session_state.rankings.items():
                            points = (len(beers) + 1) - rank
                            conn.execute("""
                                INSERT INTO ratings (beer_key, taster_id, points_assigned) 
                                VALUES (?, ?, ?)
                            """, (b_id, t_id, points))
                        
                        conn.commit()
                    
                    st.success(f"Scores for {actual_name} recorded successfully!")
                    st.balloons()
                    del st.session_state.rankings
                    st.rerun()

# --- PAGE: LEADERBOARD ---
elif page == "Leaderboard":
    with get_connection() as conn:
        last_ev_row = conn.execute("SELECT MAX(tasting_no) FROM events").fetchone()
        latest_db_tasting = last_ev_row[0] if last_ev_row and last_ev_row[0] else 1
    
    curr_t = st.session_state.get('current_tasting', latest_db_tasting)
    
    # Header with Refresh Button
    col_header, col_btn = st.columns([4, 1])
    col_header.header(f"🏆 Session {curr_t} Results")
    if col_btn.button("🔄 Refresh Data"):
        st.rerun()
    
    query = """
    SELECT 
        b.beer_id, 
        COALESCE(NULLIF(b.beer_name_scraped, ''), b.beer_name_manual, 'Beer ' || b.beer_id) as Beer,
        b.untappd_score,
        b.brewver_score,
        t.name as Taster,
        r.points_assigned as Points
    FROM beers b
    LEFT JOIN ratings r ON b.beer_id = r.beer_key
    LEFT JOIN tasters t ON r.taster_id = t.id
    WHERE b.beer_id LIKE ?
    """
    
    with get_connection() as conn:
        raw_df = pd.read_sql(query, conn, params=(f"{curr_t}-%",))
    
    valid_df = raw_df.dropna(subset=['Points'])
    
    if not valid_df.empty:
        # --- CHART LOGIC (Winner at the Top) ---
        chart_data = valid_df.groupby(['Beer', 'Taster'])['Points'].sum().reset_index()
        # Your fixed order logic
        rank_order = chart_data.groupby('Beer')['Points'].sum().sort_values(ascending=False).index.tolist()
        
        fig = px.bar(
            chart_data, y="Beer", x="Points", color="Taster", orientation='h',
            category_orders={"Beer": rank_order},
            title="Point Contribution by Taster",
            color_discrete_sequence=px.colors.qualitative.Pastel
        )
        fig.update_layout(
            barmode='stack', 
            height=400 + (len(rank_order) * 25), 
            yaxis_title=None,
            xaxis_title="Total Points"
        )
        st.plotly_chart(fig, use_container_width=True)

        # --- TABLE LOGIC ---
        st.markdown("### 📊 Final Rankings")
        
        table_df = valid_df.groupby('beer_id').agg({
            'Beer': 'first',
            'untappd_score': 'first',
            'brewver_score': 'first',
            'Points': 'sum'
        }).reset_index()
        
        table_df = table_df.sort_values('Points', ascending=False).reset_index(drop=True)
        
        def calc_global_data(row):
            u = row['untappd_score']
            b = row['brewver_score']
            if pd.notna(u) and u > 0:
                return pd.Series([float(u), "Untappd"])
            if pd.notna(b) and b > 0:
                return pd.Series([float(b), "Brewver"])
            return pd.Series([0.0, "N/A"])

        table_df[['Global_Rating', 'Source']] = table_df.apply(calc_global_data, axis=1)

        table_df.insert(0, 'Rank', range(1, len(table_df) + 1))
        def add_medal(rank):
            if rank == 1: return "1 🥇"
            elif rank == 2: return "2 🥈"
            elif rank == 3: return "3 🥉"
            return str(rank)
        table_df['Rank'] = table_df['Rank'].apply(add_medal)

        st.dataframe(
            table_df[['Rank', 'Beer', 'Points', 'Global_Rating', 'Source']],
            column_config={
                "Rank": st.column_config.TextColumn("Rank"),
                "Points": st.column_config.NumberColumn("Session Points", format="%d pts"),
                "Global_Rating": st.column_config.NumberColumn("Global Rating", format="%.2f ⭐"),
                "Source": st.column_config.TextColumn("Source")
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.warning(f"No votes recorded for Session #{curr_t}.")