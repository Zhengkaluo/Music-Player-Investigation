#!/usr/bin/env python3
"""
lastfm_retry_failed.py
对 lastfm_log.json 中失败的专辑重新尝试获取 tags。
改进点：
  1. 降低 MIN_WEIGHT 到 10（更宽松）
  2. 尝试 artist.getTopTags（即使 album 失败）
  3. 对中文专辑，尝试去掉特殊字符后再搜索
"""

import json, time, random, requests
from pathlib import Path
import re

# ============ 配置 ============
API_KEY   = "87360810cc3f4f2ed32e52ac7878c03e"
DATA_FILE = Path(r"f:\SystemPlayerInvestigation\cafe-playlist\data\albums.json")
LOG_FILE  = Path(r"f:\SystemPlayerInvestigation\cafe-playlist\data\lastfm_log.json")
MIN_WEIGHT = 10   # 降低阈值（原来 25）
MAX_TAGS   = 4

# ============ blocklist ============
JUNK = {
    "2026","2025","2024","2023","2022","2021","2020",
    "2019","2018","2017","2016","2015","2014","2013","2012","2011","2010",
    "chinese","china","japanese","japan","korean","korea","british","uk",
    "american","usa","australian","german","french","italian","spanish",
    "spotify","apple music","youtube","soundcloud","bandcamp",
    "beautiful","great","awesome","amazing","love","hate","sad","happy",
    "chill","relaxing","cool","good","bad","perfect","wonderful",
    "seen live","live","cover","remix","acoustic","demo","remaster",
}

GMAP = {
    "indie-pop":"indie-pop", "indie pop":"indie-pop",
    "indie-folk":"indie-folk", "indie folk":"indie-folk",
    "singer-songwriter":"singer-songwriter",
    "r&b":"R&B", "rnb":"R&B",
    "soul":"soul", "neo-soul":"neo-soul",
    "folk":"folk", "pop":"pop", "rock":"rock",
    "electronic":"electronic", "indie-rock":"indie-rock",
    "alternative rock":"alternative rock", "hip hop":"hiphop",
    "lo-fi":"Lofi", "ambient":"ambient",
}

def is_junk(tag):
    return tag.lower().strip() in JUNK or tag.isdigit()

def norm(tag):
    t = tag.lower().strip()
    return GMAP.get(t, t.title())

# ============ Last.fm API ============
def api(method, params):
    params.update({"method": method, "api_key": API_KEY, "format": "json", "autocorrect": 1})
    for i in range(3):
        try:
            r = requests.get("https://ws.audioscrobbler.com/2.0/", params=params, timeout=10)
            r.raise_for_status()
            d = r.json()
            return (d, None) if "error" not in d else (None, d.get("message",""))
        except Exception as e:
            if i == 2: return None, str(e)
            time.sleep(1)
    return None, "max retries"

def get_tags(artist, album=None):
    method = "album.getTopTags" if album else "artist.getTopTags"
    params = {"artist": artist}
    if album: params["album"] = album
    data, err = api(method, params)
    if not data or "toptags" not in data:
        return [], err
    raw = data["toptags"].get("tag", [])
    if isinstance(raw, dict): raw = [raw]
    result = []
    for t in raw:
        name = t.get("name", "").strip()
        if not name or is_junk(name): continue
        try: w = int(t.get("count", 0))
        except: w = 0
        if w >= MIN_WEIGHT:
            result.append((name, w))
    return result, None

def clean_query(text):
    """清理查询字符串（去掉特殊字符、版本信息等）"""
    # 去掉括号内容
    text = re.sub(r'\(.*?\)', '', text)
    text = re.sub(r'\[.*?\]', '', text)
    # 去掉特殊字符
    text = re.sub(r'[^\w\s\-]', ' ', text)
    return text.strip()

# ============ main ============
def main():
    # 读取专辑数据
    with open(DATA_FILE, encoding="utf-8") as f:
        albums = json.load(f)
    albums_dict = {a["name"]: a for a in albums}
    
    # 读取日志，找出失败的专辑
    with open(LOG_FILE, encoding="utf-8") as f:
        log = json.load(f)
    
    failed_entries = [e for e in log if e.get("status") == "failed"]
    print(f"失败专辑总数：{len(failed_entries)}")
    print("-" * 60)
    
    updated = 0
    still_failed = []
    
    for i, entry in enumerate(failed_entries):
        artist = entry["artist"]
        album = entry["album"]
        print(f"[{i+1}/{len(failed_entries)}] {artist} - {album}")
        
        # 尝试 1：直接用原始 artist + album
        tags, err = get_tags(artist, album)
        
        # 尝试 2：清理 album 名称后重试
        if not tags:
            clean_album = clean_query(album)
            if clean_album != album:
                print(f"  重试（清理后）：{clean_album}")
                tags, err = get_tags(artist, clean_album)
        
        # 尝试 3：只用 artist（不用 album）
        if not tags:
            tags, err = get_tags(artist)
        
        if not tags:
            print(f"  ❌ 仍然失败：{err or 'no valid tags'}")
            still_failed.append({"artist": artist, "album": album, "reason": err or "no valid tags"})
            time.sleep(random.uniform(0.5, 1.0))
            continue
        
        # 去重，保留最高 weight
        seen = {}
        for t, w in tags:
            n = norm(t)
            if n not in seen or w > seen[n]: seen[n] = w
        final = sorted(seen, key=seen.get, reverse=True)[:MAX_TAGS]
        
        # 更新 albums.json
        if album in albums_dict:
            old = albums_dict[album].get("genres", [])
            albums_dict[album]["genres"] = final
            albums_dict[album]["noise_source"] = "lastfm-retry"
            print(f"  ✅ OK: {old} -> {final}")
            updated += 1
        
        # 更新日志
        entry["status"] = "ok"
        entry["new"] = final
        entry["old"] = entry.get("old", [])
        entry["retry"] = True
        
        time.sleep(random.uniform(0.8, 1.5))
    
    print("-" * 60)
    print(f"重试成功：{updated}  仍然失败：{len(still_failed)}")
    
    # 保存 albums.json
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(albums, f, ensure_ascii=False, indent=2)
    print(f"✅ 已更新 {DATA_FILE}")
    
    # 保存日志
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    print(f"✅ 已更新 {LOG_FILE}")
    
    # 保存仍然失败的列表
    if still_failed:
        fail_file = Path(r"f:\SystemPlayerInvestigation\cafe-playlist\data\lastfm_still_failed.json")
        with open(fail_file, "w", encoding="utf-8") as f:
            json.dump(still_failed, f, ensure_ascii=False, indent=2)
        print(f"❌ 仍然失败 {len(still_failed)} 张，已保存到 {fail_file}")
    
    return still_failed

if __name__ == "__main__":
    main()
