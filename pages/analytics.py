import streamlit as st
import pandas as pd
import sqlite3
import os
import numpy as np

# --- 1. DATABASE & PATHS ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_NAME = os.path.join(BASE_DIR, "beer_tracker.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

# --- 2. DATA LOADING ---
@st.cache_data(show_spinner="Mining all-time legends...")
def load_analysis_data():
    with get_connection() as conn:
        ratings = pd.read_sql("SELECT taster_id, beer_key, points_assigned FROM ratings", conn)
        
        # Joined brewery group, country name, style L3 name/desc, and beer description
        beers = pd.read_sql("""
            SELECT 
                m.beer_event_position AS beer_id, 
                b.beer_id AS internal_beer_id, 
                b.beer_name_manual, 
                b.beer_name_scraped, 
                b.description AS beer_desc,
                b.brewery_id, 
                b.untappd_score,
                b.abv, 
                s.l3_substyle AS style_name,
                s.description AS style_info,
                c.country_name AS country, 
                br.brewery_name,
                br.group_name,
                m.tasting_no
            FROM beers b 
            JOIN beer_event_mapping m ON b.beer_id = m.beer_id
            LEFT JOIN breweries br ON b.brewery_id = br.brewery_id
            LEFT JOIN countries c ON br.country_code = c.country_code
            LEFT JOIN styles s ON b.style_id = s.id
        """, conn)
        
        tasters = pd.read_sql("SELECT id, name FROM tasters", conn)
        events = pd.read_sql("SELECT tasting_no, date, title FROM events ORDER BY tasting_no DESC", conn)
        
        mapping = pd.read_sql("""
            SELECT tasting_no, 
            MAX(CAST(SUBSTR(beer_event_position, INSTR(beer_event_position, '-') + 1) AS INTEGER)) as max_pos
            FROM beer_event_mapping
            GROUP BY tasting_no
        """, conn)
        
    return ratings, beers, tasters, events, mapping

ratings_raw, beers_df, tasters_df, events_df, mapping_df = load_analysis_data()

# --- 3. THE ELITE SCALING ENGINE ---
def get_detailed_multipliers(session_ratings, e_no, v_count, b_count, toggles):
    bench = st.session_state.get('benchmarks')
    if not bench: return {"Baseline": "1.00x"}, 1.0
    
    details = {}
    if toggles['xp'] and v_count > 0:
        t_ids = session_ratings['taster_id'].unique()
        avg_xp = ratings_raw[ratings_raw['taster_id'].isin(t_ids)].groupby('taster_id').size().mean()
        val = np.interp(avg_xp, bench['xp'], [0.8, 1.2])
        details['Taster XP'] = f"{val:.2f}x"
    if toggles['str']:
        val = np.interp(b_count, bench['strength'], [0.9, 1.1])
        details['Session Size'] = f"{val:.2f}x"
    if toggles['part']:
        val = np.interp(v_count, bench['participation'], [0.85, 1.15])
        details['Voter Count'] = f"{val:.2f}x"
    if toggles['qual']:
        session_beers_meta = beers_df[beers_df['tasting_no'] == int(e_no)]
        avg_q = session_beers_meta['untappd_score'].mean() / 5.0 if not session_beers_meta.empty else 0.7
        val = np.interp(avg_q, bench['quality'], [0.9, 1.1])
        details['Session Quality'] = f"{val:.2f}x"
        
    final_m = np.prod([float(v.replace('x','')) for v in details.values()]) if details else 1.0
    return details, final_m

def scale_score(raw_pct, multiplier):
    if raw_pct <= 0: return 0.0
    anchor = 0.75
    projected = (raw_pct / 100.0) * anchor * multiplier
    if projected > 0.90:
        overflow = projected - 0.90
        soft_cap = 0.90 + (0.10 * np.tanh(overflow / 0.10))
        return soft_cap * 100
    return projected * 100

# --- 4. SIDEBAR ---
st.sidebar.header("🛠️ Analysis Controls")
user_list = ["All Tasters"] + sorted(tasters_df['name'].tolist())
selected_user = st.sidebar.selectbox("Show Rankings for:", user_list)

st.sidebar.divider()
st.sidebar.subheader("⚖️ Weighting Components")
toggles = {
    'xp': st.sidebar.checkbox("Taster Experience (XP)", value=True),
    'str': st.sidebar.checkbox("Session Strength", value=True),
    'part': st.sidebar.checkbox("Participation", value=True),
    'qual': st.sidebar.checkbox("Global Quality", value=True)
}

# --- 5. GLOBAL AGGREGATION ---
def get_all_time_top_20():
    if selected_user != "All Tasters":
        uid = tasters_df[tasters_df['name'] == selected_user]['id'].values[0]
        v_ratings = ratings_raw[ratings_raw['taster_id'] == uid]
    else:
        v_ratings = ratings_raw
    
    agg = v_ratings.groupby('beer_key')['points_assigned'].sum().reset_index()
    agg = agg.merge(beers_df, left_on='beer_key', right_on='beer_id')
    
    results = []
    for _, row in agg.iterrows():
        e_no = str(row['tasting_no'])
        s_ratings_all = ratings_raw[ratings_raw['beer_key'].astype(str).str.startswith(f"{e_no}-")]
        s_voters = s_ratings_all['taster_id'].nunique()
        s_map = mapping_df[mapping_df['tasting_no'] == int(e_no)]
        s_b_count = int(s_map['max_pos'].values[0]) if not s_map.empty else 1
        
        _, m = get_detailed_multipliers(s_ratings_all, e_no, s_voters, s_b_count, toggles)
        eff_voters = 1 if selected_user != "All Tasters" else s_voters
        raw_pct = (row['points_assigned'] / (eff_voters * s_b_count)) * 100
        elite_score = scale_score(raw_pct, m)
        
        results.append({
            "Beer": row['beer_name_scraped'] or row['beer_name_manual'],
            "Brewery": row['brewery_name'],
            "Elite Score": round(elite_score, 2),
            "Raw %": round(raw_pct, 2),
            "Untappd": row['untappd_score'] or 0,
            "Session": f"#{e_no}"
        })
    
    df = pd.DataFrame(results)
    if not df.empty:
        df = df.sort_values(by=["Elite Score", "Raw %", "Untappd"], ascending=False).head(20)
    return df

# --- 6. RENDER TOP 20 ---
st.title(f"📈 {selected_user} Analytics")
with st.container(border=True):
    st.subheader("⭐ All-Time Elite Top 20")
    top_20_df = get_all_time_top_20()
    st.dataframe(top_20_df, use_container_width=True, hide_index=True)

st.divider()

# --- 7. SESSION GRID RENDERER ---
def render_beer_card(medal, row, v_count, b_count, multiplier, m_details):
    available_points = v_count * b_count
    raw_pct = (row['total_points'] / available_points) * 100 if available_points > 0 else 0
    elite_score = scale_score(raw_pct, multiplier)
    
    hover_text = "Modifier Impact (Anchor: 75%):\n" + "\n".join([f"- {k}: {v}" for k, v in m_details.items()])
    hover_text += f"\n\nSession Multiplier: {multiplier:.2f}x"

    with st.container(border=True):
        st.markdown(f"#### {medal}") 
        
        img_path = os.path.join(UPLOAD_DIR, f"{row['beer_key']}.jpg")
        if os.path.exists(img_path):
            st.image(img_path, use_container_width=True)
            st.markdown('<style>img { max-height: 280px; object-fit: contain; padding-bottom: 10px; }</style>', unsafe_allow_html=True)
        else:
            st.info("📷 No Photo")

        st.markdown(f"**{row['beer_name_scraped'] or row['beer_name_manual']}**")
        
        # ROW 1: BREWERY (GROUP)
        group_txt = f" ({row['group_name']})" if row['group_name'] else ""
        st.markdown(f"🏭 **{row['brewery_name'] or 'Unknown'}{group_txt}**")
        
        # ROW 2: COUNTRY
        st.markdown(f"🌍 {row['country'] or 'Unknown'}")
        
        # ROW 3: STYLE (L3) + Tooltip & ABV
        s_col1, s_col2 = st.columns([0.7, 0.3])
        with s_col1:
            # FIX: Convert style_info to string to prevent TypeError on built-in operation (Streamlit help requires str)
            h_info = str(row['style_info']) if pd.notna(row['style_info']) else "No additional style info available."
            st.markdown(f"🍺 {row['style_name'] or 'Unknown'}", help=h_info)
        with s_col2:
            st.markdown(f"🧪 **{row['abv'] or '??'}%**")
            
        # BEER INFO PANEL (Always displayed per request)
        with st.expander("📝 Beer Info", expanded=False):
            if row['beer_desc'] and str(row['beer_desc']).strip():
                st.write(row['beer_desc'])
            else:
                st.caption("No description available for this beer.")
        
        st.divider()
        st.markdown(f"📊 **Score:** `{int(row['total_points'])} / {available_points}`")
        
        c1, c2 = st.columns(2)
        c1.metric("Raw %", f"{raw_pct:.1f}%")
        
        norm_expect = raw_pct * 0.75
        c2.metric(
            label="Elite Score", 
            value=f"{elite_score:.1f}%", 
            delta=f"{elite_score - norm_expect:+.1f}% vs Norm",
            help=hover_text
        )

# --- 8. MAIN SESSION LOOP ---
if selected_user != "All Tasters":
    target_uid = tasters_df[tasters_df['name'] == selected_user]['id'].values[0]
    active_ratings = ratings_raw[ratings_raw['taster_id'] == target_uid]
else:
    active_ratings = ratings_raw

stats = active_ratings.groupby('beer_key')['points_assigned'].agg(['sum', 'count']).reset_index()
stats.columns = ['beer_key', 'total_points', 'vote_count']
full_data = stats.merge(beers_df, left_on='beer_key', right_on='beer_id', how='inner')

for _, event in events_df.iterrows():
    e_no = str(event['tasting_no'])
    s_ratings_all = ratings_raw[ratings_raw['beer_key'].astype(str).str.startswith(f"{e_no}-")]
    voters = s_ratings_all['taster_id'].nunique()
    row_map = mapping_df[mapping_df['tasting_no'] == int(e_no)]
    b_count = int(row_map['max_pos'].values[0]) if not row_map.empty else 0
    
    session_view = full_data[full_data['beer_key'].str.startswith(f"{e_no}-")].copy()
    if not session_view.empty:
        m_details, m_final = get_detailed_multipliers(s_ratings_all, e_no, voters, b_count, toggles)
        st.subheader(f"Session #{e_no}: {event['title']}")
        
        d_voters = 1 if selected_user != "All Tasters" else voters
        session_view['elite_temp'] = session_view.apply(
            lambda x: scale_score((x['total_points'] / (d_voters * b_count)) * 100, m_final), axis=1
        )
        top_3 = session_view.sort_values(['elite_temp', 'untappd_score'], ascending=False).head(3)
        
        cols = st.columns(3)
        medals = ["🥇 Gold", "🥈 Silver", "🥉 Bronze"]
        for i, (_, row) in enumerate(top_3.iterrows()):
            with cols[i]:
                render_beer_card(medals[i], row, d_voters, b_count, m_final, m_details)
        st.divider()