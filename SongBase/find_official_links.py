"""
查找 QQ 音乐歌单中每首歌的 YouTube / Bilibili 官方录音版本链接。

规则:
- YouTube: 只接受匹配艺人名的 Artist - Topic 频道或官方频道，oEmbed 二次验证
- Bilibili: 只接受音乐人本人账号
- 禁止标题含: Live, 现场, 演唱会, Cover, 翻唱, Remix, 混音, 伴奏, 剪辑
- 同名误匹配、粉丝频道、搬运号一律拒绝
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

BASE = Path("/Users/kaluozheng/Music-Player-Investigation/SongBase")
JSON_PATH = BASE / "qqmusic_playlists.json"
MD_PATH = BASE / "qqmusic_playlists.md"
YTDLP_BIN = "/Users/kaluozheng/.workbuddy/binaries/python/envs/default/bin/yt-dlp"

BANNED_TITLE_RE = re.compile(
    r'\b(live|concert|现场|演唱会|cover|翻唱|remix|混音|伴奏|剪辑|'
    r'karaoke|instrumental|reaction|rehearsal|排练|demo|'
    r'live session|full performance|guitar tutorial|教学|'
    r'中英字幕|中日字幕|歌词|lyrics? video|fan.?made|试听)\b',
    re.IGNORECASE
)

# 泛频道关键词（非艺人本人）
GENERIC_CHANNEL_KEYWORDS = [
    "release", "various artists", "bbc radio", "kexp", "npr music",
    "tiny desk", "colors", "audio tree", "pitchfork", "triple j",
    "环球音乐", "索尼音乐", "华纳音乐", "music video", "records",
    "vevo", "music group", "entertainment", "publishing",
]


def normalize_text(s: str) -> str:
    """去掉常见后缀和标点，用于频道名比对"""
    s = s.lower().strip()
    # CamelCase → 分词: "mogwaiTV" → "mogwai tv"
    s = re.sub(r'([a-z])([A-Z])', r'\1 \2', s)
    s = re.sub(r'[^\w\s]', '', s)  # 去标点
    s = re.sub(r'\b(official|tv|music|channel|vevo|band|jp|us|uk)\b', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s



def tokenize(s: str) -> set[str]:
    return set(re.split(r'\s+', normalize_text(s))) - {''}


def channel_matches_artist(channel: str, artist: str):
    """检查频道名是否匹配艺人名。只返回 high/matched=True 或 none/matched=False。
    拒绝一切中等置信度匹配（粉丝号、搬运号风险过高）。"""
    ch = channel.lower().strip()
    
    # 先检查泛频关键词（抢在匹配前，避免发布厂牌被误认）
    if any(kw in ch for kw in GENERIC_CHANNEL_KEYWORDS):
        return (False, "none")
    
    # 去掉 " - topic" 后缀
    if ch.endswith(" - topic"):
        ch = ch[:-8].strip()
    
    art_clean = artist.lower().strip()
    primary = artist.split(",")[0].strip().lower()
    
    # 规则1: 精确匹配 → 高置信度
    if ch == art_clean or ch == primary:
        return (True, "high")
    
    # 规则2: normalize 后严格相等（不包括子串）
    ch_norm = normalize_text(ch)
    art_norm = normalize_text(art_clean)
    pri_norm = normalize_text(primary)
    if ch_norm == art_norm or ch_norm == pri_norm:
        return (True, "high")
    
    # 规则3: normalize 后 artist 是 channel 的子串 → 需严格检查
    # 仅允许 "artist" == "artistXXX" 这种明确情况
    # 禁止 "partOfName" 在 "name" 中出现这种模糊情形
    if art_norm and ch_norm:
        # artist 是 channel 的前缀（如 "mogwai" → "mogwaitv"）
        if ch_norm.startswith(art_norm):
            return (True, "high")
        # artist 是 channel 的后缀
        if ch_norm.endswith(art_norm):
            return (True, "high")
    
    # 拒绝所有 token 重叠 / 子串匹配（之前的中等置信度规则）
    return (False, "none")


def is_banned_title(title: str) -> bool:
    return bool(BANNED_TITLE_RE.search(title))


def title_matches_song(title: str, song_name: str) -> bool:
    """验证视频标题是否真的包含歌曲名（防止同名曲误匹配）"""
    t = title.lower().replace('&amp;', '&')
    s = song_name.lower().strip()
    # 歌曲名在标题中出现
    if s in t:
        return True
    # 部分匹配（长歌名至少匹配前几个词）
    words = s.split()
    if len(words) >= 3:
        first_words = ' '.join(words[:3])
        if first_words in t:
            return True
    return False


# ═══════════════════════════════════════════════════
# YOUTUBE SEARCH
# ═══════════════════════════════════════════════════

def search_youtube(song_name: str, artist: str, timeout: int = 20) -> str | None:
    """搜索 YouTube，在所有候选中找第一个通过验证的官方链接。"""
    query = f"{song_name} {artist.split(',')[0]}"
    try:
        result = subprocess.run(
            [
                YTDLP_BIN, "--flat-playlist", "--dump-json", "--no-warnings",
                "--skip-download", "--ignore-no-formats-error",
                f"ytsearch5:{query}", "--match-filter", "!is_live",
            ],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    if result.returncode != 0:
        return None

    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        video_id = data.get("id", "")
        title = data.get("title", "") or data.get("fulltitle", "")
        channel = (data.get("channel", "") or data.get("uploader", "") or "")

        if not video_id or not title:
            continue
        if is_banned_title(title):
            continue

        matched, confidence = channel_matches_artist(channel, artist)
        if not matched:
            continue

        # 只有高置信度才继续
        if confidence != "high":
            continue

        # 标题验证: 歌名必须在标题中出现
        if not title_matches_song(title, song_name):
            continue

        # oEmbed 二次验证（强制，不做跳过）
        link = f"https://youtube.com/watch?v={video_id}"
        if verify_youtube_oembed(link, artist):
            print(f"  [YT:high] {channel} → ✓", end="")
            return link

    return None


def verify_url_accessible(url: str, timeout: int = 10) -> bool:
    """快速验证 URL 是否可达"""
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        return r.status_code < 400
    except Exception:
        return False


def verify_youtube_oembed(url: str, artist: str, timeout: int = 10) -> bool:
    """用 oEmbed API 验证频道确实是官方的"""
    try:
        r = requests.get(
            f"https://www.youtube.com/oembed?url={url}&format=json",
            timeout=timeout,
        )
        if r.status_code != 200:
            return False
        d = r.json()
        author = d.get("author_name", "")
        matched, _ = channel_matches_artist(author, artist)
        return matched
    except Exception:
        return False


# ═══════════════════════════════════════════════════
# BILIBILI SEARCH
# ═══════════════════════════════════════════════════

def search_bilibili(song_name: str, artist: str, timeout: int = 10) -> str | None:
    """搜索 Bilibili，在所有候选中找第一个通过验证的官方链接。"""
    query = f"{song_name} {artist}"

    # 尝试多种查询策略
    queries = [query]
    # 对日语歌，同时尝试歌手名
    if any('\u3040' <= c <= '\u30ff' for c in artist):  # 含假名
        queries.append(f"{song_name} {artist.split(' ')[0]}")

    for q in queries:
        link = _search_bilibili_single(q, song_name, artist, timeout)
        if link:
            return link
    return None


def _search_bilibili_single(query: str, song_name: str, artist: str, timeout: int = 10) -> str | None:
    try:
        resp = requests.get(
            "https://api.bilibili.com/x/web-interface/wbi/search/type",
            params={"search_type": "video", "keyword": query, "page": 1, "page_size": 5},
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                "Referer": "https://www.bilibili.com/",
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    if data.get("code") != 0:
        return None

    artist_clean = artist.lower().strip()
    primary = artist.split(",")[0].strip().lower()

    for item in data.get("data", {}).get("result", []):
        title = item.get("title", "").replace('<em class="keyword">', '').replace('</em>', '')
        bvid = item.get("bvid", "")
        author = (item.get("author", "") or "").lower().strip()
        duration = item.get("duration", "")

        if not bvid or not title:
            continue
        if is_banned_title(title):
            continue

        # B 站验证: 作者名直接匹配艺人名
        if author == artist_clean or author == primary:
            if title_matches_song(title, song_name):
                print(f"  [BL] {author} → ✓", end="")
                return f"https://www.bilibili.com/video/{bvid}"

        # normalize 后匹配
        au_norm = normalize_text(author)
        art_norm = normalize_text(artist_clean)
        if au_norm == art_norm or au_norm == normalize_text(primary):
            if title_matches_song(title, song_name):
                print(f"  [BL] {author} → ✓", end="")
                return f"https://www.bilibili.com/video/{bvid}"

    return None


# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════

def process_all():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        playlists = json.load(f)

    yt_count = 0
    bl_count = 0
    total_songs = sum(p["song_count"] for p in playlists)

    song_idx = 0
    for pl in playlists:
        for song in pl["songs"]:
            song_idx += 1
            name = song["name"]
            artist = song["singer"]

            # 已有结果 && 非空 → 跳过
            existing_yt = song.get("youtube_link", "")
            existing_bl = song.get("bilibili_link", "")
            if existing_yt:
                yt_count += 1
            if existing_bl:
                bl_count += 1
            if existing_yt and existing_bl:
                continue

            prefix = f"[{song_idx}/{total_songs}] {name[:30]}"
            print(f"{prefix:65s}", end="", flush=True)

            # YouTube
            if not existing_yt:
                try:
                    link = search_youtube(name, artist)
                    song["youtube_link"] = link or ""
                    if link:
                        yt_count += 1
                except Exception as e:
                    song["youtube_link"] = ""
                    print(f"  YT❌{type(e).__name__}", end="")

            # Bilibili
            if not existing_bl:
                try:
                    link = search_bilibili(name, artist)
                    song["bilibili_link"] = link or ""
                    if link:
                        bl_count += 1
                except Exception as e:
                    song["bilibili_link"] = ""
                    print(f"  BL❌{type(e).__name__}", end="")

            print()

            # 每 25 首保存
            if song_idx % 25 == 0:
                save_files(playlists)
                print(f"  💾 [{song_idx}/{total_songs}] YT:{yt_count} BL:{bl_count}")

            time.sleep(1.5)

    # 最终保存
    save_files(playlists)
    print(f"\n{'='*50}")
    print(f"✓ 完成! YouTube: {yt_count}/{total_songs} | Bilibili: {bl_count}/{total_songs}")


def save_files(playlists):
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(playlists, f, ensure_ascii=False, indent=2)
    regenerate_md(playlists)


def regenerate_md(playlists):
    total_songs = sum(p["song_count"] for p in playlists)
    yt_total = sum(1 for p in playlists for s in p["songs"] if s.get("youtube_link"))
    bl_total = sum(1 for p in playlists for s in p["songs"] if s.get("bilibili_link"))

    lines = [
        "# QQ 音乐歌单整理（含官方录音链接）\n",
        f"> 导出时间: 2026-07-27\n",
        f"> 共 {len(playlists)} 份歌单，{total_songs} 首歌曲\n",
        f"> YouTube 匹配: {yt_total} | Bilibili 匹配: {bl_total}\n",
        "---\n",
    ]

    short_urls = [
        "https://c6.y.qq.com/base/fcgi-bin/u?__=ATaQMbKfMMK2",
        "https://c6.y.qq.com/base/fcgi-bin/u?__=udfVqUjqH7Bm",
        "https://c6.y.qq.com/base/fcgi-bin/u?__=7kY8JUyDHT1e",
    ]

    for idx, pl in enumerate(playlists):
        lines.append(f"## {idx + 1}. {pl['name']}\n")
        lines.append(f"- **创建者**: {pl['creator']}")
        lines.append(f"- **歌曲数**: {pl['song_count']}")
        lines.append(f"- **歌单链接**: {pl['link']}")
        lines.append(f"- **短链接**: {short_urls[idx]}\n")
        lines.append(f"| # | 歌曲名 | 歌手 | 专辑 | QQ音乐 | YouTube | Bilibili |")
        lines.append(f"|---|--------|------|------|--------|---------|----------|")

        for i, s in enumerate(pl["songs"], 1):
            yt = f"[▶️]({s.get('youtube_link', '')})" if s.get('youtube_link') else "暂未找到"
            bl = f"[▶️]({s.get('bilibili_link', '')})" if s.get('bilibili_link') else "暂未找到"
            lines.append(
                f"| {i} | {s['name']} | {s['singer']} | {s['album']} "
                f"| [🔗]({s['link']}) | {yt} | {bl} |"
            )
        lines.append("")

    with open(MD_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    process_all()
