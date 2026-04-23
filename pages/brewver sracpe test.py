import requests
from lxml import html
import re
import os
import json

# --- CONFIG ---
UPLOADS_DIR = "uploads"
if not os.path.exists(UPLOADS_DIR):
    os.makedirs(UPLOADS_DIR)

def parse_brewery_and_group(raw_name):
    """Splits 'Brewery (Group)' into ('Brewery', 'Group')"""
    if not raw_name: return "", None
    match = re.search(r'^(.*?)\s*\((.*)\)$', raw_name.strip())
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return raw_name.strip(), None

def download_beer_image(img_url, beer_id):
    """Downloads image and saves it as {beer_id}.jpg"""
    if not img_url: return False
    try:
        if img_url.startswith('/'):
            img_url = f"https://brewver.com{img_url}"
        res = requests.get(img_url, stream=True, timeout=10)
        if res.status_code == 200:
            file_path = os.path.join(UPLOADS_DIR, f"{beer_id}.jpg")
            with open(file_path, 'wb') as f:
                for chunk in res.iter_content(1024):
                    f.write(chunk)
            return True
    except: return False
    return False

def get_beer_details_ready_for_db(beer_url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    try:
        # Extract Beer ID from URL (e.g., 565517)
        beer_id = beer_url.split('/')[-2] if beer_url.split('/')[-1].isalpha() else beer_url.split('/')[-1]
        
        # --- 1. FETCH BEER PAGE ---
        res = requests.get(beer_url, headers=headers, timeout=10)
        tree = html.fromstring(res.content)
        
        # Basic Info
        beer_name = tree.xpath("//h3/text()")[0].strip() if tree.xpath("//h3/text()") else None
        
        # Description (Joining multiple text nodes to capture all paragraphs)
        desc_nodes = tree.xpath("//div[contains(@class, 'description')]//text()")
        description = " ".join([t.strip() for t in desc_nodes if t.strip()]) if desc_nodes else ""

        # Score (User Rating)
        score_xpath = tree.xpath("//div[contains(@class, 'statsbubble-text-large')]/text()")
        score = float(score_xpath[0].strip()) if score_xpath else 0.0

        # Rating Count (Ticks)
        count_xpath = tree.xpath("//div[contains(@class, 'statsbubble-text-small')]/text()")
        count_raw = re.sub(r'[^0-9]', '', count_xpath[0]) if count_xpath else ""
        rating_count = int(count_raw) if count_raw else 0

        # ABV & IBU (From the Technical Data table)
        abv_text = tree.xpath("//table[contains(@class, 'beerdata_table')]//td[contains(text(), 'ABV')]/text()")
        abv_val = float(re.sub(r'[^0-9.]', '', abv_text[0])) if abv_text else 0.0

        ibu_text = tree.xpath("//table[contains(@class, 'beerdata_table')]//td[contains(text(), 'IBU')]/text()")
        ibu_raw = re.sub(r'[^0-9]', '', ibu_text[0]) if ibu_text else ""
        ibu_val = int(ibu_raw) if ibu_raw else 0

        # Image Logic
        img_src = tree.xpath("//img[contains(@class, 'beerimage')]/@src")
        img_url = img_src[0] if img_src else None
        
        # Brewery URL (to follow in Stage 2)
        raw_brewery = tree.xpath("//h4/a[1]/text()")[0].strip() if tree.xpath("//h4/a[1]/text()") else ""
        brewery_link_rel = tree.xpath("//h4/a[1]/@href")
        brewery_url = f"https://brewver.com{brewery_link_rel[0]}" if brewery_link_rel else None

        # --- 2. PARSE BREWERY/GROUP ---
        b_name, g_name = parse_brewery_and_group(raw_brewery)

        # --- 3. FETCH BREWERY PAGE FOR LOCATION ---
        city, state, country = "", "", ""
        if brewery_url:
            b_res = requests.get(brewery_url, headers=headers, timeout=10)
            b_tree = html.fromstring(b_res.content)
            loc_links = b_tree.xpath("//h4/a/text()")
            if len(loc_links) >= 3:
                city, state, country = [l.strip() for l in loc_links[:3]]

        # --- 4. ASSET DOWNLOAD ---
        download_beer_image(img_url, beer_id)

        # --- 5. RESULT ---
        return {
            "beer_id": beer_id,
            "beer_name_scraped": beer_name,
            "description": description,
            "brewver_score": score,
            "rating_count": rating_count,
            "abv": abv_val,
            "ibu": ibu_val,
            "brewery_name": b_name,
            "group_name": g_name,
            "city": city,
            "state": state,
            "country_name": country,
            "brewver_url": beer_url
        }
        
    except Exception as e:
        print(f"Scrape failed: {e}")
        return None

if __name__ == "__main__":
    # Test URL
    target_url = "https://brewver.com/beers/565517/Alien-Form"
    result = get_beer_details_ready_for_db(target_url)
    
    if result:
        print(json.dumps(result, indent=4))