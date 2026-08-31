"""
song_base 专辑追加 + YT/BL 链接搜索，共用配置。

配置文件: SongBase/new_albums_config.json
格式:
[
  {"artist": "Yutaka Hirasaka", "album": "still glow", "search": "Yutaka Hirasaka still glow"},
  ...
]

用法:
  python3 SongBase/manage_albums.py add          # 追加专辑到曲库
  python3 SongBase/manage_albums.py links        # 搜索 YT/BL 链接
  python3 SongBase/manage_albums.py all          # 追加 + 搜索
  python3 SongBase/manage_albums.py monitor      # 启动监控面板
"""
import asyncio
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
from qqmusic_api import Client

BASE = Path(__file__).resolve().parent
JSON_PATH = BASE / "song_base_by_artist.json"
MD_PATH = BASE / "song_base_by_artist.md"
CONFIG_PATH = BASE / "new_albums_config.json"
DISCARDED_PATH = BASE / "archive" / "removed_tracks" / "discarded_tracks.json"
YTDLP_BIN = "yt-dlp"

# ---- 艺人多语言别名 ----
ARTIST_ALIASES = {
    "坂本龙一": "Ryuichi Sakamoto",
    "中村遥": "haruka nakamura",
    "吉村弘": "Hiroshi Yoshimura",
    "青葉市子": "ichiko aoba",
    "小濑村晶": "Akira Kosemura",
    "高木正勝": "Masakatsu Takagi",
    "北村英治": "Eiji Kitamura",
}

# ---- 验证规则 ----
BANNED_TITLE_RE = re.compile(
    r"\b(live|concert|现场|演唱会|cover|翻唱|remix|混音|伴奏|剪辑|"
    r"karaoke|instrumental|reaction|rehearsal|排练|demo|"
    r"live session|full performance|guitar tutorial|教学|"
    r"中英字幕|中日字幕|歌词|lyrics? video|fan.?made|试听)\b",
    re.IGNORECASE,
)

GENERIC_CHANNEL_KEYWORDS = [
    "release", "various artists", "bbc radio", "kexp", "npr music",
    "tiny desk", "colors", "audio tree", "pitchfork", "triple j",
    "环球音乐", "索尼音乐", "华纳音乐", "music video", "records",
    "vevo", "music group", "entertainment", "publishing",
]


def load_config():
    if not CONFIG_PATH.exists():
        print(f"❌ 配置文件不存在: {CONFIG_PATH}")
        print("   请创建该文件，格式: [{{\"artist\": \"...\", \"album\": \"...\", \"search\": \"...\"}}, ...]")
        sys.exit(1)
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s).strip()


def normalize_artist(name):
    return re.sub(r"[,\s&]+", "", name.lower().strip())


def resolve_alias(name):
    return ARTIST_ALIASES.get(name, name)


def artists_match(a, b):
    a, b = resolve_alias(a), resolve_alias(b)
    na, nb = normalize_artist(a), normalize_artist(b)
    if na == nb:
        return True
    if len(na) > 2 and len(nb) > 2:
        if na in nb or nb in na:
            return True
    return False


def normalize_text(s):
    s = s.lower().strip()
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\b(official|tv|music|channel|vevo|band|jp|us|uk)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def channel_matches_artist(channel, artist):
    ch = channel.lower().strip()
    if any(kw in ch for kw in GENERIC_CHANNEL_KEYWORDS):
        return False, "none"
    if ch.endswith(" - topic"):
        ch = ch[:-8].strip()
    art = artist.lower().strip()
    pri = artist.split(",")[0].strip().lower()
    if ch == art or ch == pri:
        return True, "high"
    if normalize_text(ch) in (normalize_text(art), normalize_text(pri)):
        return True, "high"
    return False, "none"


def is_banned_title(title):
    return bool(BANNED_TITLE_RE.search(title))


def title_matches_song(title, song_name):
    t = title.lower().replace("&amp;", "&")
    s = song_name.lower().strip()
    return s in t


def verify_youtube_oembed(url, artist, timeout=10):
    try:
        r = requests.get(f"https://www.youtube.com/oembed?url={url}&format=json", timeout=timeout)
        if r.status_code != 200:
            return False
        matched, _ = channel_matches_artist(r.json().get("author_name", ""), artist)
        return matched
    except Exception:
        return False


def sec_to_display(seconds):
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


# ═══════════════════════════════════
#  Part 1: 追加专辑
# ═══════════════════════════════════

async def search_album(client, query, target_artist, target_album, existing_mid=""):
    if existing_mid:
        return {"mid": existing_mid, "name": target_album, "singers": [target_artist]}

    try:
        result = await client.search.search_by_type(query, num=10, search_type=2)
        albums = result.album
    except Exception as e:
        print(f"    ❌ 搜索失败: {e}")
        return None

    if not albums:
        print(f"    ❌ 未找到任何专辑")
        return None

    target_lower = target_album.lower().strip()

    # 精确匹配
    for a in albums:
        aname = strip_html(a.name).lower().strip()
        singers = [strip_html(s.name) for s in (a.singer_list or [])]
        if aname == target_lower:
            for s_name in singers:
                if artists_match(s_name, target_artist):
                    print(f"    ✅ {strip_html(a.name)} mid={a.mid}")
                    return {"mid": a.mid, "name": strip_html(a.name), "singers": singers}

    # 包含匹配
    for a in albums:
        aname = strip_html(a.name).lower().strip()
        singers = [strip_html(s.name) for s in (a.singer_list or [])]
        if target_lower in aname and len(aname) <= len(target_lower) + 30:
            for s_name in singers:
                if artists_match(s_name, target_artist):
                    print(f"    ⚠️ {strip_html(a.name)} mid={a.mid}")
                    return {"mid": a.mid, "name": strip_html(a.name), "singers": singers}

    print(f"    ❌ 未匹配, 候选:", [strip_html(a.name) for a in albums[:3]])
    return None


async def fetch_songs(client, album_mid):
    try:
        resp = await client.album.get_song(album_mid, num=100)
        return [{"title": str(s.name), "mid": s.mid, "duration": s.interval} for s in resp.song_list]
    except Exception as e:
        print(f"      ❌ 获取失败: {e}")
        return []


def load_data():
    if not JSON_PATH.exists():
        print(f"❌ 曲库文件不存在: {JSON_PATH}")
        sys.exit(1)
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def load_discarded_ids():
    if not DISCARDED_PATH.exists():
        return set()
    payload = json.loads(DISCARDED_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "songbase.discarded-tracks/v1":
        raise ValueError("归档舍弃清单 schema_version 无效")
    return set(payload.get("tracks", {}))


def save_data(data):
    JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def rebuild_md(data):
    singers = data["singers"]
    lines = [
        "# QQ 音乐曲库（按歌手索引）",
        f"> {data['total_singers']} 位艺人 · {data['total_unique_songs']} 首歌曲 · {data['export_date']}",
        f"> YouTube: {sum(s['youtube'] for s in singers)} | Bilibili: {sum(s['bilibili'] for s in singers)}",
        "",
    ]
    for singer in singers:
        flags = []
        if singer["youtube"]:
            flags.append(f"YT:{singer['youtube']}")
        if singer["bilibili"]:
            flags.append(f"BL:{singer['bilibili']}")
        fstr = f" · {', '.join(flags)}" if flags else ""
        lines.append(f"## {singer['name']} ({singer['song_count']}首{fstr})")
        lines.append("| # | 歌曲 | 专辑 | 时长 | QQ音乐 | YouTube |")
        lines.append("|---|------|------|------|--------|---------|")
        for i, song in enumerate(singer["songs"], 1):
            dur = sec_to_display(song["duration"])
            qq = f"[🔗]({song['qq_music']})" if song["qq_music"] else "-"
            yt = f"[▶️]({song['youtube']})" if song["youtube"] else "-"
            lines.append(f"| {i} | {song['title']} | {song['album']} | {dur} | {qq} | {yt} |")
        lines.append("")
    MD_PATH.write_text("\n".join(lines), encoding="utf-8")


def recompute_stats(data):
    singers = data["singers"]
    singers.sort(key=lambda x: x["name"].lower())
    data["singers"] = singers
    data["total_singers"] = len(singers)
    all_titles = set()
    for s in singers:
        for sg in s["songs"]:
            all_titles.add((s["name"].lower(), sg["title"].lower()))
    data["total_unique_songs"] = len(all_titles)
    data["export_date"] = time.strftime("%Y-%m-%d")
    for s in singers:
        s["youtube"] = sum(1 for sg in s["songs"] if sg["youtube"])
        s["bilibili"] = sum(1 for sg in s["songs"] if sg["bilibili"])


def find_artist_index(singers, name):
    for i, s in enumerate(singers):
        if artists_match(s["name"], name):
            return i
    return None


async def cmd_add():
    config = load_config()
    data = load_data()
    singers = data["singers"]
    discarded_ids = load_discarded_ids()
    client = Client()

    new_total = 0
    for idx, item in enumerate(config):
        artist = item["artist"]
        album = item["album"]
        query = item.get("search", f"{artist} {album}")
        mid_override = item.get("qq_mid", "")

        print(f"[{idx+1}/{len(config)}] {artist} - {album}")
        info = await search_album(client, query, artist, album, mid_override)
        if not info:
            print(f"    ⏭ 跳过")
            continue

        songs = await fetch_songs(client, info["mid"])
        if not songs:
            continue

        discarded_from_album = [s for s in songs if f"qq:{s['mid']}" in discarded_ids]
        if discarded_from_album:
            print(f"    🗄 跳过归档舍弃 {len(discarded_from_album)} 首")
        songs = [s for s in songs if f"qq:{s['mid']}" not in discarded_ids]
        if not songs:
            continue

        objs = [{
            "title": s["title"],
            "full_singer": artist,
            "album": album,
            "duration": s["duration"],
            "qq_music": f"https://y.qq.com/n/ryqq/songDetail/{s['mid']}" if s["mid"] else "",
            "youtube": "",
            "bilibili": "",
        } for s in songs]

        idx_artist = find_artist_index(singers, artist)
        if idx_artist is not None:
            existing = singers[idx_artist]
            titles = {s["title"].lower() for s in existing["songs"]}
            added = 0
            for obj in objs:
                if obj["title"].lower() not in titles:
                    existing["songs"].append(obj)
                    titles.add(obj["title"].lower())
                    added += 1
            existing["song_count"] = len(existing["songs"])
            print(f"    📎 +{added}首 → 共 {existing['song_count']} 首")
            new_total += added
        else:
            singers.append({"name": artist, "song_count": len(objs), "youtube": 0, "bilibili": 0, "songs": objs})
            print(f"    ✨ 新艺人 +{len(objs)}首")
            new_total += len(objs)

        if idx < len(config) - 1:
            await asyncio.sleep(0.5)

    recompute_stats(data)
    save_data(data)
    rebuild_md(data)
    print(f"\n✅ 追加完成: +{new_total}首, 总计 {data['total_unique_songs']}首")


# ═══════════════════════════════════
#  Part 2: YT/BL 搜索
# ═══════════════════════════════════

def search_youtube(song_name, artist, timeout=20):
    primary = artist.split(",")[0].split("&")[0].strip()
    try:
        result = subprocess.run(
            [YTDLP_BIN, "--flat-playlist", "--dump-json", "--no-warnings",
             "--skip-download", "--ignore-no-formats-error",
             f"ytsearch5:{song_name} {primary}", "--match-filter", "!is_live"],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""

    if result.returncode != 0:
        return ""

    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        vid = d.get("id", "")
        title = d.get("title", "") or d.get("fulltitle", "")
        channel = d.get("channel", "") or d.get("uploader", "")
        if not vid or not title:
            continue
        if is_banned_title(title):
            continue
        matched, conf = channel_matches_artist(channel, artist)
        if not matched or conf != "high":
            continue
        if not title_matches_song(title, song_name):
            continue
        link = f"https://youtube.com/watch?v={vid}"
        if verify_youtube_oembed(link, artist):
            return link
    return ""


def search_bilibili(song_name, artist, timeout=10):
    primary = artist.split(",")[0].strip()
    try:
        resp = requests.get(
            "https://api.bilibili.com/x/web-interface/wbi/search/type",
            params={"search_type": "video", "keyword": f"{song_name} {primary}", "page": 1, "page_size": 5},
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "Referer": "https://www.bilibili.com/"},
            timeout=timeout,
        )
        resp.raise_for_status()
        d = resp.json()
    except Exception:
        return ""
    if d.get("code") != 0:
        return ""
    artist_clean = primary.lower().strip()
    for item in d["data"]["result"]:
        title = item["title"].replace('<em class="keyword">', '').replace('</em>', '')
        bvid = item.get("bvid", "")
        author = (item.get("author", "") or "").lower().strip()
        if not bvid or not title:
            continue
        if is_banned_title(title):
            continue
        if author == artist_clean or normalize_text(author) == normalize_text(artist_clean):
            if title_matches_song(title, song_name):
                return f"https://www.bilibili.com/video/{bvid}"
    return ""


def cmd_links():
    config = load_config()
    config_albums = {(c["artist"], c["album"]) for c in config}

    data = load_data()
    singers = data["singers"]

    tasks = []
    for s_idx, singer in enumerate(singers):
        for sg_idx, song in enumerate(singer["songs"]):
            if (singer["name"], song["album"]) not in config_albums:
                continue
            if not song["youtube"] or not song["bilibili"]:
                tasks.append((s_idx, sg_idx, song["title"], song["full_singer"],
                              not song["youtube"], not song["bilibili"]))

    print(f"🔍 需要搜索: {len(tasks)} 首歌")
    yt_found = bl_found = 0

    for i, (s_idx, sg_idx, title, artist, need_yt, need_bl) in enumerate(tasks):
        song = singers[s_idx]["songs"][sg_idx]
        print(f"[{i+1}/{len(tasks)}] {artist[:25]} - {title[:35]}", end="", flush=True)

        if need_yt:
            try:
                link = search_youtube(title, artist)
                if link:
                    song["youtube"] = link
                    yt_found += 1
                    print("  YT✓", end="")
                else:
                    print("  YT✗", end="")
            except Exception as e:
                print(f"  YT❌{type(e).__name__}", end="")
        else:
            print("  YT-", end="")

        if need_bl:
            try:
                link = search_bilibili(title, artist)
                if link:
                    song["bilibili"] = link
                    bl_found += 1
                    print("  BL✓", end="")
                else:
                    print("  BL✗", end="")
            except Exception as e:
                print(f"  BL❌{type(e).__name__}", end="")
        else:
            print("  BL-", end="")

        print()

        if (i + 1) % 20 == 0 or i == len(tasks) - 1:
            recompute_stats(data)
            save_data(data)
            if (i + 1) % 20 == 0:
                yt_t = sum(s["youtube"] for s in singers)
                bl_t = sum(s["bilibili"] for s in singers)
                print(f"  💾 [{i+1}/{len(tasks)}] YT:{yt_found}(总{yt_t}) BL:{bl_found}(总{bl_t})")

        if i < len(tasks) - 1:
            time.sleep(1.5)

    recompute_stats(data)
    save_data(data)
    rebuild_md(data)

    yt_t = sum(s["youtube"] for s in singers)
    bl_t = sum(s["bilibili"] for s in singers)
    print(f"\n✅ YT: {yt_found} | BL: {bl_found} | 总计 YT:{yt_t} BL:{bl_t}")

    # 重新生成 HTML
    print("🔨 生成 HTML...")
    subprocess.run([sys.executable, str(BASE / "build_song_base_browser.py")], cwd=str(BASE))


# ═══════════════════════════════════
#  Part 3: 监控面板
# ═══════════════════════════════════

MONITOR_HTML = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="5">
<title>YT/BL 链接搜索监控</title>
<style>
:root{--bg:#0d1117;--panel:#161b22;--line:#30363d;--text:#c9d1d9;--muted:#8b949e;--accent:#58a6ff;--green:#3fb950;--red:#f85149;--amber:#d29922}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 ui-sans-serif,-apple-system,sans-serif;padding:24px}
h1{font-size:20px;margin:0 0 4px;display:flex;align-items:center;gap:8px}
h1 .dot{width:10px;height:10px;border-radius:50%;background:var(--green);animation:pulse 1.5s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.sub{color:var(--muted);font-size:12px;margin:0 0 20px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:20px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.kpi .v{font-size:26px;font-weight:700}.kpi .l{color:var(--muted);font-size:12px;margin-top:2px}
.bar-wrap{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:20px}
.bar-wrap h3{font-size:14px;margin:0 0 12px;color:var(--muted);font-weight:600}
.bar-outer{height:12px;background:var(--bg);border-radius:6px;overflow:hidden}
.bar-inner{height:100%;border-radius:6px;transition:width .5s;background:linear-gradient(90deg,var(--accent),var(--green))}
.bar-stats{display:flex;justify-content:space-between;margin-top:8px;font-size:12px;color:var(--muted)}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:8px 10px;text-align:center;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-size:11px;text-align:left}
td:last-child{text-align:right}
.found{color:var(--green);font-weight:700}
.progress-mini{display:inline-block;width:80px;height:6px;background:var(--bg);border-radius:3px;vertical-align:middle;margin:0 6px;overflow:hidden}
.progress-mini div{height:100%;border-radius:3px;background:var(--green)}
.done td{opacity:.5}.done td:first-child{opacity:1}
</style></head><body>
<h1><span class="dot"></span>YouTube / Bilibili 搜索进度</h1>
<p class="sub">自动每 5 秒刷新 · 仅接受官方音乐人频道</p>
<div class="kpis" id="kpis"></div>
<div class="bar-wrap"><h3>整体进度</h3><div class="bar-outer"><div class="bar-inner" id="bar" style="width:0%"></div></div><div class="bar-stats"><span id="barText"></span><span id="rate"></span></div></div>
<table><thead><tr><th>艺人</th><th>专辑</th><th>总歌曲</th><th>YT</th><th>进度</th><th>详情</th></tr></thead><tbody id="tbody"></tbody></table>
<script>
fetch('/data').then(r=>r.json()).then(d=>{
  var ytDone=d.albums.reduce(function(a,b){return a+b.yt},0);
  var total=d.total,pct=Math.round(total?ytDone/total*100:0);
  document.getElementById('kpis').innerHTML=[
    ['待搜索',total,'首 · '+d.albums.length+' 张专辑'],
    ['YouTube',d.ytTotal,'总匹配 / '+ytDone+' 新增'],
    ['Bilibili',d.blTotal,'总匹配'],
    ['完成度',pct+'%','YT: '+ytDone+'/'+total]
  ].map(function(x){return '<div class="kpi"><div class="v">'+x[1]+'</div><div class="l">'+x[0]+'<br>'+x[2]+'</div></div>'}).join('');
  document.getElementById('bar').style.width=pct+'%';
  document.getElementById('barText').textContent=ytDone+' / '+total;
  document.getElementById('rate').textContent=pct+'%';
  document.getElementById('tbody').innerHTML=d.albums.map(function(a){
    var ap=Math.round(a.songs?a.yt/a.songs*100:0);
    return '<tr class="'+(a.yt===a.songs?'done':'')+'"><td>'+a.artist+'</td><td>'+a.album+'</td><td>'+a.songs+'</td><td class="found">'+a.yt+'</td><td><span class="progress-mini"><div style="width:'+ap+'%"></div></span> '+ap+'%</td><td>'+a.yt+'/'+a.songs+'</td></tr>';
  }).join('');
});
</script></body></html>"""


def cmd_monitor():
    from http.server import HTTPServer, BaseHTTPRequestHandler

    config = load_config()
    config_albums = {(c["artist"], c["album"]) for c in config}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/data":
                d = json.loads(JSON_PATH.read_text(encoding="utf-8"))
                singers = d["singers"]
                albums = []
                for singer in singers:
                    for song in singer["songs"]:
                        if (singer["name"], song["album"]) not in config_albums:
                            continue
                        found = next((a for a in albums if a["artist"] == singer["name"] and a["album"] == song["album"]), None)
                        if found:
                            found["songs"] += 1
                            if song["youtube"]:
                                found["yt"] += 1
                        else:
                            albums.append({"artist": singer["name"], "album": song["album"], "songs": 1,
                                           "yt": 1 if song["youtube"] else 0})
                total = sum(a["songs"] for a in albums)
                resp = {"albums": sorted(albums, key=lambda x: x["artist"].lower()), "total": total,
                        "yt": sum(a["yt"] for a in albums), "bl": 0,
                        "ytTotal": sum(s["youtube"] for s in singers),
                        "blTotal": sum(s["bilibili"] for s in singers)}
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(resp, ensure_ascii=False).encode())
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(MONITOR_HTML.encode())
            def log_message(self, *a):
                pass

    port = 8765
    server = HTTPServer(("0.0.0.0", port), H)
    print(f"📊 http://localhost:{port}")
    print(f"   Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋")


# ═══════════════════════════════════
#  Main
# ═══════════════════════════════════

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "add":
        asyncio.run(cmd_add())
    elif cmd == "links":
        cmd_links()
    elif cmd == "all":
        asyncio.run(cmd_add())
        cmd_links()
    elif cmd == "monitor":
        cmd_monitor()
    else:
        print("用法: python3 SongBase/manage_albums.py {add|links|all|monitor}")
        print("  add      - 从 new_albums_config.json 追加专辑到曲库")
        print("  links    - 为配置中的专辑搜索 YT/BL 链接")
        print("  all      - 追加 + 搜索")
        print("  monitor  - 启动监控面板 (http://localhost:8765)")
