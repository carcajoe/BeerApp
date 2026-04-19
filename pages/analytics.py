import streamlit as st
import pandas as pd
import sqlite3
import os

# --- 1. DATABASE & PATHS ---
# Navigation scripts are in /pages/, so we go up one level to find the DB and uploads folder
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_NAME = os.path.join(BASE_DIR, "beer_tracker.db")

def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

st.set_page_config(page_title="Hall of Fame Analysis", page_icon="🏆", layout="wide")

# --- 2. DATA LOADING ---
@st.cache_data(show_spinner="Polishing the trophies...")
def load_analysis_data():
    with get_connection() as conn:
        # Map table-specific columns: ratings.points_assigned and beers.beer_id
        ratings = pd.read_sql("SELECT taster_id, beer_key, points_assigned FROM ratings", conn)
        beers = pd.read_sql("""
            SELECT beer_id, beer_name_manual, beer_name_scraped, 
                   brewery_id, beer_image_url, untappd_score 
            FROM beers
        """, conn)
        tasters = pd.read_sql("SELECT id, name FROM tasters", conn)
        events = pd.read_sql("SELECT tasting_no, title, date FROM events ORDER BY tasting_no DESC", conn)
        breweries = pd.read_sql("SELECT brewery_id, brewery_name FROM breweries", conn)
        
    return ratings, beers, tasters, events, breweries

ratings_raw, beers_df, tasters_df, events_df, breweries_df = load_analysis_data()

# --- 3. FILTERING UI ---
st.title("🏆 The Elite Grid")
st.markdown("A session-by-session breakdown of the top performers based on assigned points.")

with st.sidebar:
    st.header("Settings")
    all_tasters = sorted(tasters_df['name'].tolist())
    selected_names = st.multiselect(
        "Filter by Palates:", 
        options=all_tasters,
        placeholder="Everyone"
    )
    st.divider()
    st.caption("The grid displays the top 3 beers per session based on the average points from the selected tasters.")

# --- 4. PROCESSING ---
if selected_names:
    selected_ids = tasters_df[tasters_df['name'].isin(selected_names)]['id'].tolist()
    filtered_ratings = ratings_raw[ratings_raw['taster_id'].isin(selected_ids)]
else:
    filtered_ratings = ratings_raw

# Aggregate scores using points_assigned
beer_stats = filtered_ratings.groupby('beer_key')['points_assigned'].agg(['mean', 'count', 'std']).reset_index()
beer_stats.columns = ['beer_key', 'avg_score', 'vote_count', 'score_std']

# Merge metadata (Link ratings.beer_key to beers.beer_id)
full_beers = beer_stats.merge(beers_df, left_on='beer_key', right_on='beer_id', how='left')
full_beers = full_beers.merge(breweries_df, on='brewery_id', how='left')

def get_clean_name(row):
    m = row['beer_name_manual']
    s = row['beer_name_scraped']
    name = m if pd.notna(m) and str(m).strip() != "" else s
    return name if pd.notna(name) else f"Beer {row['beer_key']}"

full_beers['display_name'] = full_beers.apply(get_clean_name, axis=1)

# --- 5. GRID DISPLAY ---
def render_beer_card(medal, row):
    with st.container(border=True):
        # Header Row
        h1, h2 = st.columns([2, 1])
        h1.markdown(f"#### {medal}")
        h2.metric("Avg", f"{row['avg_score']:.2f}")
        
        # Middle Row: Image and Details
        img_col, txt_col = st.columns([1, 2])
        with img_col:
            raw_path = row['beer_image_url']
            display_img = "https://via.placeholder.com/150?text=No+Image"
            
            if pd.notna(raw_path) and str(raw_path).strip() != "":
                if str(raw_path).startswith(('http://', 'https://')):
                    display_img = raw_path
                else:
                    # Resolve local file path relative to project root
                    abs_path = os.path.normpath(os.path.join(BASE_DIR, raw_path))
                    if os.path.exists(abs_path):
                        display_img = abs_path
            
            st.image(display_img, use_container_width=True)
        
        with txt_col:
            st.markdown(f"**{row['display_name']}**")
            st.caption(f"🏭 {row['brewery_name'] if pd.notna(row['brewery_name']) else 'Unknown'}")
            st.caption(f"⭐ Untappd: {row['untappd_score'] if row['untappd_score'] else 'N/A'}")

        st.divider()
        
        # Bottom Row: The Ratings Popover (Click for Details)
        # Using a popover here because standard text cannot trigger a hover-popup in Streamlit
        with st.popover(f"👥 {int(row['vote_count'])} Ratings", use_container_width=True):
            st.markdown("### 📊 Analytics Detail")
            st.write(f"**Consistency:** {row['score_std']:.2f} (StdDev)" if pd.notna(row['score_std']) else "Only one rating recorded.")
            st.write(f"**Internal ID:** `{row['beer_key']}`")
            
            # Show a badge if the beer is exceptionally high quality based on global stats
            if 'benchmarks' in st.session_state and st.session_state['benchmarks']:
                q_threshold = st.session_state['benchmarks']['quality'][1]
                if (row['untappd_score'] or 0) / 5.0 >= q_threshold:
                    st.success("💎 Elite Quality Tier")

# Main Loop
rendered_sessions = 0
for _, event in events_df.iterrows():
    e_no = str(event['tasting_no'])
    
    # Filter using string startswith on the beer_key
    session_beers = full_beers[full_beers['beer_key'].astype(str).str.startswith(f"{e_no}-", na=False)].copy()
    top_3 = session_beers.sort_values(by='avg_score', ascending=False).head(3)
    
    if not top_3.empty:
        rendered_sessions += 1
        st.subheader(f"Session #{e_no}: {event['title']}")
        st.caption(f"📅 {event['date']}")
        
        grid_cols = st.columns(3)
        medals = ["🥇 Gold", "🥈 Silver", "🥉 Bronze"]
        
        for i, (idx, row) in enumerate(top_3.iterrows()):
            with grid_cols[i]:
                render_beer_card(medals[i], row)
        st.markdown("<br>", unsafe_allow_html=True)

if rendered_sessions == 0:
    st.info("No session data matches the current filters.")