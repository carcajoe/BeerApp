import streamlit as st
import pandas as pd
import plotly.express as px
import sqlite3
import os

# --- 1. CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_NAME = os.path.join(BASE_DIR, "beer_tracker.db")

def get_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;") 
    return conn

# Security Check: Ensure user is logged in
if 'current_taster' not in st.session_state or st.session_state.current_taster is None:
    st.warning("Please log in on the main page.")
    st.stop()

# --- 2. DATA FETCHING & SESSION DETECTION ---
with get_connection() as conn:
    last_ev_row = conn.execute("SELECT MAX(tasting_no) FROM events").fetchone()
    latest_db_tasting = last_ev_row[0] if last_ev_row and last_ev_row[0] else 1

curr_t = st.session_state.get('current_tasting', latest_db_tasting)

# Header with Refresh Button
col_header, col_btn = st.columns([4, 1])
col_header.header(f"🏆 Session {curr_t} Results")
if col_btn.button("🔄 Refresh Data"):
    st.rerun()

# --- MODIFIED SQL: Joins mapping table and filters by integer tasting_no ---
query = """
SELECT 
    m.beer_event_position AS beer_id, 
    COALESCE(NULLIF(b.beer_name_scraped, ''), b.beer_name_manual, 'Beer ' || m.beer_event_position) as Beer,
    b.untappd_score,
    b.brewver_score,
    t.name as Taster,
    r.points_assigned as Points
FROM beers b
JOIN beer_event_mapping m ON b.beer_id = m.beer_id
LEFT JOIN ratings r ON m.beer_event_position = r.beer_key
LEFT JOIN tasters t ON r.taster_id = t.id
WHERE m.tasting_no = ?
"""

with get_connection() as conn:
    # --- MODIFIED PARAMS: Passes integer curr_t instead of LIKE string ---
    raw_df = pd.read_sql(query, conn, params=(curr_t,))

valid_df = raw_df.dropna(subset=['Points'])

if not valid_df.empty:
    # --- 3. TABLE LOGIC (STAYS THE SAME) ---
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

    st.divider()

    # --- 4. CHART LOGIC (STAYS THE SAME) ---
    chart_data = valid_df.groupby(['Beer', 'Taster'])['Points'].sum().reset_index()
    rank_order = chart_data.groupby('Beer')['Points'].sum().sort_values(ascending=True).index.tolist()
    
    fig = px.bar(
        chart_data, y="Beer", x="Points", color="Taster", orientation='h',
        category_orders={"Beer": rank_order[::-1]}, 
        text="Points",
        title="Point Contribution by Taster",
        color_discrete_sequence=px.colors.qualitative.Pastel
    )
    
    fig.update_layout(
        barmode='stack', 
        height=400 + (len(rank_order) * 35),
        yaxis_title=None,
        xaxis_title="Total Points",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )

    fig.update_traces(
        texttemplate='%{text}', 
        textposition='inside',
        insidetextanchor='middle',
        textfont=dict(size=18, color='#666666')
    )
    
    st.plotly_chart(fig, use_container_width=True)

else:
    st.warning(f"No votes recorded for Session #{curr_t}.")