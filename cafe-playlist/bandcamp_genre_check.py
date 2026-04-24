"""
Bandcamp 专辑 Genre 核查工具
对 albums.json 中 noise_source='estimated' 的专辑，通过 Bandcamp 搜索+页面抓取真实 genre 标签
"""

import json
import time
import random
import re
import urllib.request
import urllib.parse
import urllib.error
import ssl
import os
import sys

# SSL context for HTTPS
SSL_CTX = ssl.create_default_context()

ALBUMS_PATH = os.path.join(os.path.dirname(__file__), "data", "albums.json")
LOG_PATH = os.path.join(os.path.dirname(__file__), "data", "bandcamp_genre_log.json")

# Rate limiting
MIN_DELAY = 2.0
MAX_DELAY = 4.0


def fetch_url(url, timeout=15):
    """Fetch URL content with proper headers"""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [ERR] Fetch failed: {e}")
        return None


def search_bandcamp(artist, album_name):
    """Search Bandcamp for an album, return list of result URLs"""
    query = f"{artist} {album_name}"
    encoded = urllib.parse.quote(query)
    url = f"https://bandcamp.com/search?q={encoded}&type=album"
    
    html = fetch_url(url)
    if not html:
        return []
    
    # Extract album result URLs from search results
    # Bandcamp search results contain links like /artist/.../album/...
    # or direct album URLs
    results = []
    
    # Pattern 1: direct album links from search results
    # Look for href patterns that point to album pages
    pattern = r'href="(https?://[^"]*\.bandcamp\.com/(?:album|track)/[^"]*)"'
    matches = re.findall(pattern, html, re.IGNORECASE)
    results.extend(matches)
    
    # Pattern 2: relative URLs (need base domain)
    pattern2 = r'href="(/(?:artist|album)/[^"]*)"[^>]*title="([^"]*)"'
    matches2 = re.findall(pattern2, html, re.IGNORECASE)
    for path, title in matches2:
        full_url = f"https://bandcamp.com{path}" if path.startswith("/") else f"https://{path}"
        if full_url not in results:
            results.append(full_url)
    
    return results


def extract_genres_from_album_page(url):
    """
    Visit a Bandcamp album page and extract genre tags.
    Returns (genres_list, location_string) or (None, None) on failure.
    
    Bandcamp pages use multiple formats for tags:
    1. HTML <a> links in tags section: [tag_name](https://bandcamp.com/discover/tag-slug)
    2. data-genre attribute on tralbum-details
    3. Embedded JSON item_data
    4. meta keywords
    """
    html = fetch_url(url)
    if not html:
        return None, None
    
    genres = set()
    location = None
    
    # Method 1: Extract from "tags" section
    # Bandcamp renders tags as [tag_text](https://bandcamp.com/discover/tag-slug)
    # In HTML this becomes <a href="...">tag_text</a> with discover URLs
    # Pattern: any link pointing to bandcamp.com/discover/
    discover_links = re.findall(
        r'<a[^>]+href="(https?://[^"]*bandcamp\.com/discover/[^"]*)"[^>]*>([^<]+)</a>',
        html, re.IGNORECASE
    )
    for link_url, tag_text in discover_links:
        tag_text = tag_text.strip()
        if tag_text and len(tag_text) > 1 and len(tag_text) < 50:
            genres.add(tag_text)
            
            # Check if it looks like a location tag
            loc_indicators = ["city", "state", "country", ",", 
                            "los angeles", "new york", "london", "tokyo",
                            "paris", "berlin", "seoul", "beijing", "shanghai",
                            "taipei", "bangkok", "sydney", "melbourne",
                            "san francisco", "chicago", "miami", "toronto",
                            "vancouver", "montreal", "osaka", "kyoto",
                            "taiwan", "japan", "usa", "uk", "us ", "california",
                            "florida", "texas", "oregon", "washington"]
            tag_lower = tag_text.lower().strip()
            if any(indicator in tag_lower for indicator in loc_indicators):
                location = tag_text
    
    # Method 2: <a class="genre"> or <a class="tag"> tags  
    genre_tag_matches = re.findall(r'<a\s+class="(?:genre|tag)"[^>]*>([^<]+)</a>', html, re.IGNORECASE)
    for g in genre_tag_matches:
        g = g.strip()
        if g and len(g) > 1 and len(g) < 50:
            genres.add(g)
    
    # Method 3: data-genre / data-tags attributes
    dg_match = re.search(r'data-(?:genre|tags?)="([^"]+)"', html, re.IGNORECASE)
    if dg_match:
        raw = dg_match.group(1)
        for g in raw.split(","):
            g = g.strip()
            if g and len(g) > 1:
                genres.add(g)
    
    # Method 4: embedded item_data JSON - look for genre field
    id_match = re.search(r'"genre"\s*:\s*"([^"]+)"', html)
    if id_match:
        g = id_match.group(1).strip()
        if g:
            genres.add(g)
    
    sub_match = re.search(r'"subgenre"\s*:\s*"([^"]+)"', html)
    if sub_match:
        g = sub_match.group(1).strip()
        if g:
            genres.add(g)
    
    # Method 5: meta keywords
    kw_match = re.search(r'<meta\s+name="keywords"\s+content="([^"]+)"', html, re.IGNORECASE)
    if kw_match:
        keywords = kw_match.group(1).split(",")
        for kw in keywords:
            kw = kw.strip()
            if kw and 1 < len(kw) < 50:
                genres.add(kw)

    # Clean up junk tags
    junk_tags = {
        "bandcamp", "download", "mp3", "flac", "vinyl", "cd", "cassette",
        "merchandise", "buy now", "name your price", "free download",
        "streaming", "digital album", "limited edition",
        # Non-genre location-ish that we've already captured separately
    }
    genres -= junk_tags
    
    # Also try to get artist location from bio/about section
    if not location:
        bio_patterns = [
            r'(\w+[,\s]+\w+(?:,\s*\w+)?)\s*</div>\s*<div class="bio-component"',
            r'location["\s:]+([^"<>\n]{2,40})',
            r'([A-Z][a-z]+(?:\s*,\s*(?:[A-Z][a-z]+|[A-Z]{2}))+)',
        ]
        for pat in bio_patterns:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                loc_candidate = m.group(1).strip()
                if loc_candidate and 1 < len(loc_candidate) < 60:
                    # Filter out obvious non-locations
                    if not any(x in loc_candidate.lower() for x in ['album', 'track', 'song', 'music']):
                        location = loc_candidate
                        break
    
    return sorted(genres) if genres else None, location


def estimate_noise_level_from_genres(genres):
    """
    Given Bandcamp genres, estimate noise level (1-7).
    Lower = quieter/calmer, Higher = louder/more energetic.
    """
    genre_noise_map = {
        # Very quiet (1-2)
        "ambient": 1.5, "drone": 1.5, "new age": 1.5, "meditation": 1.5,
        "classical": 2.0, "chamber music": 2.0, "minimalism": 2.0,
        "acoustic": 2.5, "folk": 2.5, "piano": 2.0,
        
        # Quiet-moderate (2.5-3.5)
        "jazz": 2.5, "bossa nova": 2.0, "lo-fi": 3.0,
        "soul": 3.0, "r&b": 3.0, "quiet storm": 2.5,
        "easy listening": 2.0, "lounge": 2.5, "chillout": 2.5,
        "dream pop": 3.0, "slowcore": 2.5,
        
        # Moderate (3-4.5)
        "indie rock": 4.0, "indie": 3.5, "alternative": 4.0,
        "pop": 3.5, "synthpop": 3.5, "electropop": 3.5,
        "electronic": 3.5, "trip hop": 3.0, "downtempo": 3.0,
        "funk": 3.5, "groove": 3.5, "neo-soul": 3.0,
        "singer-songwriter": 3.0, "soft rock": 3.0,
        
        # Moderate-loud (4-5.5)
        "rock": 4.5, "psychedelic": 4.5, "shoegaze": 5.0,
        "post-rock": 4.5, "math rock": 5.0, "art rock": 4.5,
        "hip hop": 4.0, "rap": 4.0, "beats": 4.0,
        "reggae": 3.5, "dub": 3.5, "latin": 4.0,
        "fusion": 4.0, "contemporary jazz": 3.5,
        
        # Loud (5-6.5)
        "punk": 6.0, "emo": 5.5, "hard rock": 5.5,
        "metal": 6.5, "hardcore": 6.5, "post-hardcore": 6.0,
        "industrial": 5.5, "noise rock": 7.0, "experimental": 5.0,
        "post-punk": 5.5, "garage rock": 5.5,
        
        # Electronic variants
        "house": 4.5, "techno": 5.0, "trance": 4.5,
        "idm": 4.5, "breakbeat": 4.5, "drum and bass": 5.0,
        "ambient techno": 3.0, "detroit techno": 4.5,
        "chiptune": 4.5, "synthwave": 4.0,
    }
    
    scores = []
    for g in genres:
        gl = g.lower().strip()
        # Direct match
        if gl in genre_noise_map:
            scores.append(genre_noise_map[gl])
        else:
            # Partial match
            for key, val in genre_noise_map.items():
                if key in gl or gl in key:
                    scores.append(val)
                    break
            else:
                # Unknown genre, default moderate
                scores.append(4.0)
    
    if not scores:
        return 4.0
    
    return round(sum(scores) / len(scores), 2)


def normalize_region(location_str):
    """Convert Bandcamp location to our region format."""
    if not location_str:
        return None
    
    loc_lower = location_str.lower()
    
    country_map = {
        "united states": "美国", "usa": "美国", "us": "美国",
        "uk": "英国", "united kingdom": "英国", "britain": "英国",
        "japan": "日本",
        "china": "大陆", "shanghai": "大陆", "beijing": "大陆",
        "taiwan": "台湾",
        "france": "法国",
        "germany": "德国",
        "canada": "加拿大",
        "australia": "澳大利亚",
        "korea": "韩国", "south korea": "韩国",
        "thailand": "泰国",
        "switzerland": "瑞士",
        "brazil": "巴西",
        "netherlands": "荷兰",
        "sweden": "瑞典",
        "norway": "挪威",
        "italy": "意大利",
        "spain": "西班牙",
        "russia": "俄罗斯",
        "philippines": "菲律宾",
        "malaysia": "马来西亚",
        "indonesia": "印度尼西亚",
        "ireland": "爱尔兰",
        "scotland": "苏格兰",
        "mexico": "墨西哥",
        "argentina": "阿根廷",
        "poland": "波兰",
        "finland": "芬兰",
        "denmark": "丹麦",
        "iceland": "冰岛",
        "new zealand": "新西兰",
    }
    
    for key, val in country_map.items():
        if key in loc_lower:
            return val
    
    return location_str  # Return original if no match


def process_album(album, idx, total, log):
    """Process a single album: search Bandcamp, extract genres, update."""
    artist = album.get("artist", "")
    name = album.get("name", "")
    mid = album.get("qq_music_album_mid", "?")
    
    print(f"\n[{idx}/{total}] {artist} - {name} ({mid})")
    
    # Check log first - skip if already done recently
    mid_key = mid if mid else f"{artist}_{name}"
    if mid_key in log:
        entry = log[mid_key]
        if entry.get("status") == "found" and entry.get("genres"):
            print(f"  [SKIP] Already have BC genres: {entry['genres']}")
            return "skip", entry
    
    # Search Bandcamp
    print(f"  Searching Bandcamp...")
    results = search_bandcamp(artist, name)
    
    if not results:
        print(f"  [!] No results on Bandcamp")
        log[mid_key] = {
            "artist": artist,
            "album": name,
            "status": "not_found",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "old_genres": album.get("genres", []),
        }
        return "not_found", None
    
    print(f"  Found {len(results)} result(s)")
    
    # Try each result, pick the best match
    best_genres = None
    best_location = None
    best_url = None
    
    for i, url in enumerate(results[:3]):  # Max 3 attempts
        print(f"  Checking result {i+1}: {url[:60]}...")
        genres, location = extract_genres_from_album_page(url)
        if genres:
            best_genres = genres
            best_location = location
            best_url = url
            print(f"  [OK] Genres: {genres}")
            if location:
                print(f"       Location: {location}")
            break
        time.sleep(random.uniform(MIN_DELAY * 0.5, MAX_DELAY * 0.5))
    
    if not best_genres:
        print(f"  [!] Could not extract genres from any page")
        log[mid_key] = {
            "artist": artist,
            "album": name,
            "status": "no_genres_extracted",
            "search_results": results[:3],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "old_genres": album.get("genres", []),
        }
        return "no_genres", None
    
    # Calculate noise level from real genres
    new_nl = estimate_noise_level_from_genres(best_genres)
    new_region = normalize_region(best_location)
    
    log[mid_key] = {
        "artist": artist,
        "album": name,
        "status": "found",
        "url": best_url,
        "genres": best_genres,
        "location": best_location,
        "normalized_region": new_region,
        "estimated_noise_level": new_nl,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "old_genres": album.get("genres", []),
        "old_noise_level": album.get("noise_level"),
        "old_region": album.get("region"),
    }
    
    return "found", {
        "genres": best_genres,
        "region": new_region,
        "noise_level": new_nl,
        "url": best_url,
    }


def main():
    start_idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    
    # Load albums
    with open(ALBUMS_PATH, "r", encoding="utf-8") as f:
        albums = json.load(f)
    
    # Load existing log
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            log = json.load(f)
    else:
        log = {}
    
    # Filter estimated albums
    estimated = [a for a in albums if a.get("noise_source") == "estimated"]
    total = len(estimated)
    
    print(f"Total albums to check: {total}")
    print(f"Starting from index: {start_idx}")
    print(f"Existing log entries: {len(log)}")
    
    stats = {"found": 0, "not_found": 0, "no_genres": 0, "skip": 0, "error": 0}
    
    for i in range(start_idx, total):
        album = estimated[i]
        
        try:
            status, result = process_album(album, i + 1, total, log)
            stats[status] += 1
            
            if status == "found" and result:
                # Update album in place
                album["genres"] = result["genres"]
                album["noise_source"] = "bandcamp"
                
                if result["region"]:
                    album["region"] = result["region"]
                
                if result["noise_level"]:
                    album["noise_level"] = result["noise_level"]
                
                # Add bandcamp URL for reference
                album["bandcamp_url"] = result["url"]
            
        except KeyboardInterrupt:
            print("\n\n[INTERRUPTED] Saving progress...")
            break
        except Exception as e:
            print(f"  [ERROR] {e}")
            stats["error"] += 1
        
        # Save progress every 10 albums + always save log
        if (i + 1) % 10 == 0 or i == total - 1:
            # Save albums
            with open(ALBUMS_PATH, "w", encoding="utf-8") as f:
                json.dump(albums, f, ensure_ascii=False, indent=2)
            # Save log
            with open(LOG_PATH, "w", encoding="utf-8") as f:
                json.dump(log, f, ensure_ascii=False, indent=2)
            print(f"\n  === Progress saved: {i+1}/{total} | Stats: {stats} ===\n")
        
        # Rate limit
        delay = random.uniform(MIN_DELAY, MAX_DELAY)
        time.sleep(delay)
    
    # Final save
    with open(ALBUMS_PATH, "w", encoding="utf-8") as f:
        json.dump(albums, f, ensure_ascii=False, indent=2)
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*60}")
    print(f"DONE! Final stats: {stats}")
    print(f"Log saved to: {LOG_PATH}")


if __name__ == "__main__":
    main()
