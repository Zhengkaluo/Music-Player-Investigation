#!/usr/bin/env python3
"""
lastfm_genre_tagger.py v4
使用 Last.fm API 批量获取专辑/艺人的 top tags，更新 albums.json 中的 genres 字段。
只处理 noise_source == 'estimated' 的专辑。

新增功能：
  - 每 10 张自动保存（防止中断丢失进度）
  - 断点续传（自动跳过已处理的专辑）
  - 跳过中国大陆专辑（Last.fm 数据质量差）

过滤策略：
  1. blocklist：明确非 genre 的 tag（年份、国家、平台、情绪形容词...）
  2. allowlist：已知 genre 直接映射
  3. 未知 tag：保留（Title Case），不作为 genre 无意义
"""

import json, time, random, requests
from pathlib import Path

# ============ 配置 ============
API_KEY   = "87360810cc3f4f2ed32e52ac7878c03e"
DATA_FILE = Path(r"f:\SystemPlayerInvestigation\cafe-playlist\data\albums.json")
OUT_FILE  = Path(r"f:\SystemPlayerInvestigation\cafe-playlist\data\albums.json")
LOG_FILE  = Path(r"f:\SystemPlayerInvestigation\cafe-playlist\data\lastfm_log.json")
MIN_WEIGHT = 25   # tag 最低权重（Last.fm 返回 count）
MAX_TAGS   = 4     # 每张专辑最多取几个 tag
SKIP_CHINA = True  # 跳过中国大陆专辑（Last.fm 数据质量差）
SAVE_EVERY = 10    # 每处理 N 张专辑保存一次

# ============ blocklist：明确不是 genre 的 tag ============
JUNK = {
    # 年份 / 年代
    "2026","2025","2024","2023","2022","2021","2020",
    "2019","2018","2017","2016","2015","2014","2013","2012","2011","2010",
    "2009","2008","2007","2006","2005","2000s","1990s","1980s","1970s",
    # 国家 / 地区（不是 genre）
    "chinese","china","china pop","chinese music",
    "japanese","japan","japanese music","j-pop","jpop",
    "korean","korea","k-pop","kpop","korean music",
    "british","uk","britain","english","britpop",
    "american","usa","us","americana",
    "canadian","canada","canadian pop",
    "australian","australia","new zealand","nz",
    "german","germany","deutsch","french","france",
    "italian","italy","spanish","spain","mexican","mexico",
    "swedish","sweden","norwegian","norway","finnish","finland",
    "icelandic","iceland","dutch","netherlands","belgian","belgium",
    "irish","ireland","scottish","scotland","polish","poland",
    "russian","russia","portuguese","portugal","brazilian","brazil",
    "thai","thailand","indonesian","indonesia","malaysian","malaysia",
    "singaporean","singapore","philippine","philippines","vietnamese","vietnam",
    "indian","india",
    # 语言
    "english language","japanese language","chinese language","korean language","spanish language",
    # 情绪形容词（太泛，不是 genre）
    "beautiful","great","awesome","amazing","favorite","favourite","best",
    "love","hate","sad","happy","angry","chill","relaxing","cool","nice","fun",
    "good","bad","perfect","wonderful","fantastic","incredible","brilliant","excellent",
    "soothing","relaxing","calm","peaceful","energetic","powerful","emotional","nostalgic",
    "melancholy","depressing","uplifting","inspiring","romantic","sexy","dark","bright",
    # 平台 / 格式
    "spotify","apple music","youtube","soundcloud","bandcamp","tidal","deezer","pandora",
    "vinyl","cd","digital","download","streaming","physical","tape","cassette",
    # 其他噪音
    "seen live","live","cover","remix","acoustic version","demo","remaster","reissue",
    "new","recommended","under 10","under 20","over 10","long song","short song",
    "male vocalist","female vocalist","instrumental","vocal","male vocal","female vocal",
    "singer","band","artist","music","song","album","release",
    "2023 releases","2024 releases","2025 releases","2022 releases",
    # 乐队名误判为 tag（常见）
    "air","bonobo","massived attack","portishead","bjork","radiohead","sigur ros",
    "the beatles","beatles","nirvana","pink floyd","led zeppelin","queen",
}

# ============ allowlist：Last.fm tag → 我们的 genres 体系 ============
GMAP = {
    "indie-pop":"indie-pop", "indie pop":"indie-pop",
    "indie-folk":"indie-folk", "indie folk":"indie-folk",
    "singer-songwriter":"singer-songwriter", "singer/songwriter":"singer-songwriter",
    "r&b":"R&B", "rnb":"R&B", "rhythm and blues":"R&B",
    "soul":"soul", "neo-soul":"neo-soul", "neo soul":"neo-soul",
    "folk":"folk", "folk rock":"folk rock", "folk-pop":"folk-pop",
    "pop":"pop", "pop rock":"pop rock", "synth-pop":"synth-pop", "synth pop":"synth-pop",
    "electronic":"electronic", "electronica":"electronic", "edm":"electronic",
    "indie-rock":"indie-rock", "indie rock":"indie-rock",
    "alternative rock":"alternative rock", "alt-rock":"alternative rock",
    "hip hop":"hiphop", "hip-hop":"hiphop", "rap":"hiphop",
    "lo-fi":"Lofi", "lofi":"Lofi", "downtempo":"downtempo", "down-tempo":"downtempo",
    "dream pop":"dream pop", "shoegaze":"shoegaze",
    "ambient":"ambient",
    "post-rock":"post-rock", "post rock":"post-rock",
    "math-rock":"math-rock", "math rock":"math-rock",
    "contemporary jazz":"contemporary-jazz", "jazz":"jazz",
    "chamber pop":"chamber pop",
    "rock":"rock", "punk":"punk", "emo":"emo",
    "experimental":"experimental", "noise":"noise",
    "acoustic":"acoustic", "acoustic pop":"acoustic",
    "country":"country",
    "latin pop":"latin pop", "latin-pop":"latin pop",
    "soundtrack":"soundtrack", "film score":"film-score", "ost":"soundtrack",
    "classical":"classical", "orchestral":"orchestral",
    "reggae":"reggae", "funk":"funk", "blues":"blues",
    "trip-hop":"trip-hop", "trip hop":"trip-hop", "chillout":"chillout",
    "christian":"christian", "gospel":"gospel", "worship":"worship",
    "christmas":"christmas", "holiday":"holiday",
    "comedy":"comedy", "spoken word":"spoken-word", "audiobook":"audiobook",
    "healing":"healing", "meditation":"meditation", "relaxation":"relaxation",
    "disney":"disney", "kids":"kids",
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

def fetch(artist, album_name):
    tags, err = get_tags(artist, album_name)
    if len(tags) >= 2:
        return tags, None
    tags2, err2 = get_tags(artist)
    return (tags2, None) if tags2 else (tags, err or err2)

# ============ 保存函数 ============
def save_progress(albums, log):
    """保存 albums.json 和日志"""
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(albums, f, ensure_ascii=False, indent=2)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    print(f"  💾 已保存进度（{len(log)} 条记录）")

# ============ 断点续传 ============
def load_processed_keys():
    """从日志中加载已处理的 (artist, album) 集合"""
    if not LOG_FILE.exists():
        return set()
    try:
        with open(LOG_FILE, encoding="utf-8") as f:
            log = json.load(f)
        keys = set()
        for entry in log:
            key = (entry["artist"], entry["album"])
            keys.add(key)
        print(f"📂 发现已有日志，已处理 {len(keys)} 张专辑，将自动跳过")
        return keys
    except:
        return set()

# ============ main ============
def main():
    with open(DATA_FILE, encoding="utf-8") as f:
        albums = json.load(f)

    # 加载已处理的专辑
    processed_keys = load_processed_keys()
    
    # 加载已有日志
    if LOG_FILE.exists():
        with open(LOG_FILE, encoding="utf-8") as f:
            log = json.load(f)
    else:
        log = []

    targets = [a for a in albums if a.get("noise_source") == "estimated"]
    
    # 过滤掉已处理的
    pending = []
    for alb in targets:
        key = (alb["artist"], alb["name"])
        if key not in processed_keys:
            pending.append(alb)
    
    print(f"总计（estimated）：{len(targets)}  待处理：{len(pending)}  已处理：{len(processed_keys)}")
    print("-" * 60)

    updated, failed, skipped = 0, 0, 0
    counter = 0  # 计数器：每 SAVE_EVERY 张保存一次

    for i, alb in enumerate(pending):
        artist = alb["artist"]; name = alb["name"]
        
        # 跳过中国大陆专辑（支持中英文）
        region = alb.get("region", "")
        if SKIP_CHINA and region in ("China", "大陆"):
            print(f"[{i+1}/{len(pending)}] SKIP (China/大陆): {artist} - {name}")
            log.append({"artist":artist,"album":name,"status":"skipped","reason":f"China region ({region})"})
            skipped += 1
            counter += 1
            time.sleep(random.uniform(0.3, 0.6))
            # 每 SAVE_EVERY 张保存一次
            if counter % SAVE_EVERY == 0:
                save_progress(albums, log)
            continue
        
        print(f"[{i+1}/{len(pending)}] {artist} - {name}")

        tags_raw, err = fetch(artist, name)
        if not tags_raw:
            print(f"  SKIP: {err or 'no valid tags'}")
            failed += 1
            log.append({"artist":artist,"album":name,"status":"failed","reason":err or "no valid tags"})
            counter += 1
            time.sleep(random.uniform(0.5, 1.0))
            # 每 SAVE_EVERY 张保存一次
            if counter % SAVE_EVERY == 0:
                save_progress(albums, log)
            continue

        # 去重，保留最高 weight
        seen = {}
        for t, w in tags_raw:
            n = norm(t)
            if n not in seen or w > seen[n]: seen[n] = w
        final = sorted(seen, key=seen.get, reverse=True)[:MAX_TAGS]

        old = alb.get("genres", [])
        alb["genres"] = final
        alb["noise_source"] = "lastfm"
        print(f"  OK: {old} -> {final}")
        updated += 1
        log.append({"artist":artist,"album":name,"status":"ok","old":old,"new":final})
        counter += 1
        time.sleep(random.uniform(0.8, 1.5))

        # 每 SAVE_EVERY 张保存一次
        if counter % SAVE_EVERY == 0:
            save_progress(albums, log)

    print("-" * 60)
    print(f"完成！更新：{updated}  失败：{failed}  跳过：{skipped}")
    print(f"总计处理：{updated + failed + skipped}")
    
    # 最终保存
    save_progress(albums, log)
    print(f"\n✅ 全部完成！日志：{LOG_FILE}")

if __name__ == "__main__":
    main()
