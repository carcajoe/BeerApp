import streamlit as st
import pandas as pd
import plotly.express as px
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

# Security Check
if 'current_taster' not in st.session_state or st.session_state.current_taster is None:
    st.warning("Please log in on the main page.")
    st.stop()

st.title("🗺️ Global Beer Journey")

# --- 2. DATA LOADING ---
with get_connection() as conn:
    query = """
    SELECT 
        m.beer_event_position AS beer_id, 
        b.beer_id AS internal_beer_id,   
        b.beer_name_manual, b.beer_name_scraped, 
        b.abv, b.untappd_score, b.brewver_score,
        b.untappd_url, b.description,
        s.l1_type, s.l2_category, s.l3_substyle, 
        br.brewery_name, br.city, br.lat, br.lon,
        c.country_name, c.continent,
        e.tasting_no, e.date as event_date, e.title as event_title,
        m.position_in_session,
        (SELECT COUNT(DISTINCT r2.taster_id) FROM ratings r2 WHERE r2.beer_key = m.beer_event_position) as participant_count,
        GROUP_CONCAT(DISTINCT t.name || ': ' || r.points_assigned) as taster_scores,
        GROUP_CONCAT(DISTINCT t.name) as taster_names
    FROM beer_event_mapping m
    JOIN beers b ON m.beer_id = b.beer_id
    LEFT JOIN styles s ON b.style_id = s.id
    LEFT JOIN breweries br ON b.brewery_id = br.brewery_id
    LEFT JOIN countries c ON br.country_code = c.country_code
    LEFT JOIN events e ON m.tasting_no = e.tasting_no
    LEFT JOIN ratings r ON m.beer_event_position = r.beer_key
    LEFT JOIN tasters t ON r.taster_id = t.id
    GROUP BY m.beer_event_position
    """
    df_raw = pd.read_sql(query, conn)
    tasters_list = pd.read_sql("SELECT name FROM tasters", conn)['name'].tolist()

# --- 3. DATA PREP ---
df_raw['display_name'] = df_raw.apply(
    lambda x: x['beer_name_scraped'] if pd.notna(x['beer_name_scraped']) and str(x['beer_name_scraped']).strip() != "" 
    else (x['beer_name_manual'] if pd.notna(x['beer_name_manual']) else f"Beer {x['beer_id']}"), axis=1
)

df_raw['event_display'] = df_raw.apply(
    lambda x: f"{x['event_date']} | #{x['tasting_no']} {x['event_title']}" if pd.notna(x['tasting_no']) else "No Event", axis=1
)

# --- 4. TOP FILTERS ---
st.markdown("### 🔍 Filter Journey")
f_row1_col1, f_row1_col2, f_row1_col3 = st.columns(3)
f_row2_col1, f_row2_col2, f_row2_col3 = st.columns(3)

event_options = sorted([opt for opt in df_raw['event_display'].unique() if opt != "No Event"], reverse=True)
if "No Event" in df_raw['event_display'].unique():
    event_options.append("No Event")

selected_event = f_row1_col1.multiselect("Event Info", options=event_options)
selected_beers = f_row1_col2.multiselect("Beer Name", options=sorted(df_raw['display_name'].unique()))
selected_brewery = f_row1_col3.multiselect("Brewery", options=sorted(df_raw['brewery_name'].dropna().unique()))
selected_style = f_row2_col1.multiselect("Beer Style", options=sorted(df_raw['l3_substyle'].dropna().unique()))
selected_taster = f_row2_col2.multiselect("Taster", options=sorted(tasters_list))
selected_country = f_row2_col3.multiselect("Beer Country", options=sorted(df_raw['country_name'].dropna().unique()))

# --- 5. FILTERING LOGIC ---
df_filtered = df_raw.copy()
if selected_event: df_filtered = df_filtered[df_filtered['event_display'].isin(selected_event)]
if selected_beers: df_filtered = df_filtered[df_filtered['display_name'].isin(selected_beers)]
if selected_brewery: df_filtered = df_filtered[df_filtered['brewery_name'].isin(selected_brewery)]
if selected_style: df_filtered = df_filtered[df_filtered['l3_substyle'].isin(selected_style)]
if selected_country: df_filtered = df_filtered[df_filtered['country_name'].isin(selected_country)]
if selected_taster:
    df_filtered = df_filtered[df_filtered['taster_names'].apply(lambda x: any(t in str(x).split(',') for t in selected_taster) if pd.notna(x) else False)]

# Sorting logic - Now using the clean integer columns we created
df_filtered = df_filtered.sort_values(['tasting_no', 'position_in_session'], ascending=[False, False])

# --- 6. TOP METRICS ---
session_count = df_filtered[df_filtered['tasting_no'].notna()]['tasting_no'].nunique()

st.divider()
m4, m1, m2 = st.columns(3)
m1.metric("Beers", len(df_filtered))
m2.metric("Countries", df_filtered['country_name'].nunique())
m4.metric("Sessions", session_count)

# --- 7. MAP SECTION (Your Original Styles) ---
tasted_counts = df_filtered[df_filtered['country_name'].notna()].groupby('country_name').size().reset_index(name='beer_count')
city_data = df_filtered[df_filtered['lat'].notna()].groupby(['city', 'lat', 'lon', 'country_name']).size().reset_index(name='city_beer_count')
is_filtered = bool(selected_country or selected_event or selected_beers or selected_brewery or selected_style or selected_taster)

fig = px.choropleth(
    tasted_counts, 
    locations="country_name", 
    locationmode='country names', 
    color="beer_count", 
    color_continuous_scale=[[0, "#FFFFE0"], [0.3, "#FFD700"], [1.0, "#8B4513"]]
)

if not city_data.empty:
    city_trace = px.scatter_geo(
        city_data, lat='lat', lon='lon', size='city_beer_count',
        hover_name='city', text='city' if is_filtered else None,
        color_discrete_sequence=["#222222"],
        custom_data=['city', 'city_beer_count', 'country_name']
    ).data[0]
    city_trace.update(hovertemplate="<b>%{customdata[0]}, %{customdata[2]}</b><br>Beers: %{customdata[1]}<extra></extra>", textposition='top center')
    fig.add_trace(city_trace)

fig.update_geos(
    visible=True, resolution=50, showcountries=True, countrycolor="#999999",
    showocean=True, oceancolor="#A2CFFE", showland=True, landcolor="#FFFFFF",
    fitbounds="locations" if is_filtered else False, projection_type="natural earth"
)
fig.update_layout(height=500, margin={"r":0,"t":0,"l":0,"b":0}, coloraxis_showscale=False, uirevision=str(is_filtered))
st.plotly_chart(fig, use_container_width=True)

# --- 8. PAGINATED BEER LIST ---
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