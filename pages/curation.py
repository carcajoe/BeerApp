import streamlit as st
import pandas as pd
import sqlite3
import os
import requests
from lxml import html
import re
from contextlib import contextmanager
import base64
from urllib.parse import quote

# --- CONFIG & PATHS ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_NAME = os.path.join(BASE_DIR, "beer_tracker.db")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")

if not os.path.exists(UPLOADS_DIR):
    os.makedirs(UPLOADS_DIR)

@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    try: yield conn
    finally: conn.close()

# --- HELPERS ---

def try_parse_int(value):
    if value is None: return None
    clean_val = re.sub(r'[^0-9]', '', str(value))
    return int(clean_val) if clean_val else None

def try_parse_float(value):
    if value is None: return None
    clean_val = re.sub(r'[^0-9.]', '', str(value))
    try:
        return float(clean_val) if clean_val else None
    except ValueError:
        return None

def get_base64_img(path):
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None

def get_country_code(country_name):
    if not country_name: return "US"
    try:
        with get_connection() as conn:
            res = conn.execute(
                "SELECT country_code FROM countries WHERE country_name LIKE ? OR synonyms LIKE ?", 
                (f"%{country_name}%", f"%{country_name}%")
            ).fetchone()
            return res[0] if res else "US"
    except: return "US"

def parse_brewery_and_group(raw_name):
    if not raw_name: return "", None
    match = re.search(r'^(.*?)\s*\((.*)\)$', raw_name.strip())
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return raw_name.strip(), None

def download_beer_image(img_url, local_bid):
    if not img_url: return False
    # If using proxy for the page, we usually need it for the image too if hosted on same domain
    api_key = st.secrets.get("SCRAPER_API_KEY")
    if img_url.startswith('/'):
        img_url = f"https://brewver.com{img_url}"
    
    try:
        if api_key:
            proxy_url = f"http://api.scraperapi.com?api_key={api_key}&url={quote(img_url)}"
            res = requests.get(proxy_url, stream=True, timeout=20)
        else:
            res = requests.get(img_url, stream=True, timeout=10)
            
        if res.status_code == 200:
            file_path = os.path.join(UPLOADS_DIR, f"{local_bid}.jpg")
            with open(file_path, 'wb') as f:
                for chunk in res.iter_content(1024):
                    f.write(chunk)
            return True
    except: return False
    return False

def get_or_create_brewery(name, group, city, state, country_code):
    if not name: return 1
    with get_connection() as conn:
        res = conn.execute("SELECT brewery_id FROM breweries WHERE brewery_name = ?", (name,)).fetchone()
        if res:
            conn.execute(
                "UPDATE breweries SET group_name=?, city=?, state=?, country_code=? WHERE brewery_id=?", 
                (group, city, state, country_code, res[0])
            )
            conn.commit()
            return res[0]
        
        cursor = conn.execute(
            "INSERT INTO breweries (brewery_name, group_name, city, state, country_code) VALUES (?, ?, ?, ?, ?)",
            (name, group, city, state, country_code)
        )
        conn.commit()
        return cursor.lastrowid

# --- SCRAPER ---

def scrape_brewver_data(url, local_bid):
    api_key = st.secrets.get("SCRAPER_API_KEY")
    
    if not api_key:
        st.error("Missing SCRAPER_API_KEY in Streamlit Secrets!")
        return None

    # ScraperAPI handles headers/rotation for us
    proxy_url = f"http://api.scraperapi.com?api_key={api_key}&url={quote(url)}"
    
    try:
        print(f"DEBUG: Proxying request for URL: {url}")
        res = requests.get(proxy_url, timeout=30)
        print(f"DEBUG: Proxy Status Code: {res.status_code}")

        if res.status_code != 200:
            st.error(f"Proxy failed (Code {res.status_code}). Check API credits or URL.")
            return None

        tree = html.fromstring(res.content)
        
        # 1. Identity & Description
        name = tree.xpath("//h3/text()")[0].strip() if tree.xpath("//h3/text()") else ""
        desc_nodes = tree.xpath("//div[contains(@class, 'description')]//text()")
        description = " ".join([t.strip() for t in desc_nodes if t.strip()]) if desc_nodes else ""
        
        # 2. Score & Ticks (Rating Count)
        score_node = tree.xpath("//div[contains(@class, 'statsbubble-text-large')]/text()")
        score = try_parse_float(score_node[0]) if score_node else None

        ticks_xpath = "//div[contains(@class, 'statsbubble')][.//div[contains(text(), 'Ticks')]]//div[contains(@class, 'statsbubble-text-small')]/text()"
        ticks_node = tree.xpath(ticks_xpath)
        rating_count = try_parse_int(ticks_node[0]) if ticks_node else None

        # 3. ABV & IBU
        abv_text = tree.xpath("//table[contains(@class, 'beerdata_table')]//td[contains(text(), 'ABV')]/text()")
        abv_val = try_parse_float(abv_text[0]) if abv_text else None

        ibu_text = tree.xpath("//table[contains(@class, 'beerdata_table')]//td[contains(text(), 'IBU')]/text()")
        ibu_val = try_parse_int(ibu_text[0]) if ibu_text else None

        # 4. Image
        img_src = tree.xpath("//img[contains(@class, 'beerimage')]/@src")
        if img_src:
            download_beer_image(img_src[0], local_bid)

        # 5. Brewery
        raw_brewery = tree.xpath("//h4/a[1]/text()")[0].strip() if tree.xpath("//h4/a[1]/text()") else ""
        brewery_link_rel = tree.xpath("//h4/a[1]/@href")
        b_name, g_name = parse_brewery_and_group(raw_brewery)
        
        city, state, country_name = "", "", ""
        if brewery_link_rel:
            try:
                b_url = f"https://brewver.com{brewery_link_rel[0]}"
                b_proxy_url = f"http://api.scraperapi.com?api_key={api_key}&url={quote(b_url)}"
                b_res = requests.get(b_proxy_url, timeout=20)
                b_tree = html.fromstring(b_res.content)
                loc_links = b_tree.xpath("//h4/a/text()")
                if len(loc_links) >= 3:
                    city, state, country_name = [l.strip() for l in loc_links[:3]]
            except Exception as b_err:
                print(f"DEBUG: Brewery proxy error: {b_err}")

        country_cd = get_country_code(country_name or state)
        brew_id = get_or_create_brewery(b_name, g_name, city, state, country_cd)

        return {
            "name": name, "abv": abv_val, "ibu": ibu_val, "score": score, 
            "count": rating_count, "desc": description, "brewery_id": brew_id, "country": country_name
        }
    except Exception as e:
        print(f"DEBUG: Proxy Scraper Exception: {str(e)}")
        st.error(f"Scraper error: {e}")
        return None

# --- UI (Rest remains unchanged) ---

st.header("🛠️ Admin Curation")

with get_connection() as conn:
    events = pd.read_sql("SELECT tasting_no, theme FROM events ORDER BY tasting_no DESC", conn)
    styles = pd.read_sql("SELECT id, l3_substyle FROM styles", conn)
    breweries = pd.read_sql("SELECT brewery_id, brewery_name FROM breweries ORDER BY brewery_name", conn)

if not events.empty:
    ev_list = [f"#{row['tasting_no']} {row['theme']}" for _, row in events.iterrows()]
    sel_ev = st.selectbox("Session", ev_list)
    ev_no = int(sel_ev.split(" ")[0].replace("#", ""))

    with get_connection() as conn:
        beers = pd.read_sql("""
            SELECT b.*, m.beer_event_position as pos 
            FROM beers b 
            JOIN beer_event_mapping m ON b.beer_id = m.beer_id 
            WHERE m.beer_event_position LIKE ? ORDER BY m.beer_event_position ASC
        """, conn, params=(f"{ev_no}-%",))

    for _, beer in beers.iterrows():
        bid = beer['beer_id']
        with st.expander(f"🍺 {beer['beer_name_scraped'] or beer['beer_name_manual'] or 'New'} ({beer['pos']})"):
            
            url = st.text_input("Brewver URL", value=beer['brewver_url'] or "", key=f"u{bid}")
            if st.button("Scrape Data", key=f"btn_{bid}"):
                data = scrape_brewver_data(url, bid)
                if data: 
                    st.session_state[f"temp_{bid}"] = data
                    st.rerun()

            with st.form(key=f"f{bid}"):
                sd = st.session_state.get(f"temp_{bid}", {})
                
                c1, c2 = st.columns([1, 4])
                with c1:
                    img_path = os.path.join(UPLOADS_DIR, f"{bid}.jpg")
                    b64 = get_base64_img(img_path)
                    if b64: st.markdown(f'<img src="data:image/jpeg;base64,{b64}" width="100%">', unsafe_allow_html=True)
                
                with c2:
                    m_name = st.text_input("Manual Name", value=beer['beer_name_manual'] or "")
                    s_name = st.text_input("Scraped Name", value=sd.get('name', beer['beer_name_scraped'] or ""))
                    
                    col_s, col_b = st.columns(2)
                    cur_style_idx = styles[styles['id'] == beer['style_id']].index[0] if beer['style_id'] in styles['id'].values else 0
                    f_style = col_s.selectbox("Style", styles['l3_substyle'].tolist(), index=int(cur_style_idx))
                    
                    cur_brew_id = sd.get('brewery_id', beer['brewery_id'])
                    cur_brew_idx = breweries[breweries['brewery_id'] == cur_brew_id].index[0] if cur_brew_id in breweries['brewery_id'].values else 0
                    f_brewery = col_b.selectbox("Brewery", breweries['brewery_name'].tolist(), index=int(cur_brew_idx))

                    v1, v2, v3, v4 = st.columns(4)
                    f_abv = v1.number_input("ABV", value=float(sd.get('abv') if sd.get('abv') is not None else (beer['abv'] or 0.0)))
                    f_ibu = v2.number_input("IBU", value=int(sd.get('ibu') if sd.get('ibu') is not None else (beer['ibu'] or 0)))
                    f_brv = v3.number_input("Score", value=float(sd.get('score') if sd.get('score') is not None else (beer['brewver_score'] or 0.0)))
                    f_rat = v4.number_input("Ratings", value=int(sd.get('count') if sd.get('count') is not None else (beer['rating_count'] or 0)))
                    
                    f_desc = st.text_area("Description", value=sd.get('desc', beer['description'] or ""))

                if st.form_submit_button("Save"):
                    sid = styles[styles['l3_substyle'] == f_style]['id'].iloc[0]
                    brid = breweries[breweries['brewery_name'] == f_brewery]['brewery_id'].iloc[0]
                    
                    with get_connection() as conn:
                        conn.execute("""
                            UPDATE beers SET 
                            beer_name_manual=?, beer_name_scraped=?, style_id=?, brewery_id=?, 
                            abv=?, ibu=?, brewver_score=?, rating_count=?, description=?, 
                            brewver_url=?, country=?
                            WHERE beer_id=?
                        """, (m_name, s_name, int(sid), int(brid), 
                              f_abv, f_ibu, f_brv, f_rat, f_desc, url, sd.get('country', beer['country']), bid))
                        conn.commit()
                    st.session_state.pop(f"temp_{bid}", None)
                    st.success("Saved!")
                    st.rerun()