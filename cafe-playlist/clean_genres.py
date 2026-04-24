"""
风格标签清洗脚本
- 备份 albums.json → albums.json.bak
- 大小写统一（转小写）
- 同义词合并（手动维护的 synonym_map）
- 剔除非风格标签（人名、年份、收藏夹名等）
- 每条专辑内去重
- 写回 albums.json
"""
import json
import shutil
from pathlib import Path
from collections import Counter

DATA_DIR = Path(__file__).parent / "data"
ALBUMS_FILE = DATA_DIR / "albums.json"
BACKUP_FILE = DATA_DIR / "albums.json.bak"

# ─── 同义词合并表 ───────────────────────────────────────────────
# key = 要被合并掉的变体（小写），value = 规范名
SYNONYM_MAP = {
    # 大小写/连字符变体
    "indie": "indie-pop",
    "r&b": "r&b",
    "hiphop": "hip-hop",
    "hip hop rap": "hip-hop",
    "chinese hiphop": "chinese hip-hop",
    "instrumental hip-hop": "instrumental hip-hop",
    "instrumental hip hop": "instrumental hip-hop",
    "lo-fi hiphop": "lo-fi hip-hop",
    "lofi hip hop": "lo-fi hip-hop",
    "jazz hippop": "jazz hip-hop",
    "hardcore rap": "hardcore hip-hop",
    "underground hip-hop": "underground hip-hop",
    "alternative r&b": "alternative r&b",
    "k-pop": "k-pop",
    "j-pop": "j-pop",
    "j-rock": "j-rock",
    "c-pop": "c-pop",
    "cpop": "c-pop",
    "cantopop": "cantopop",
    "chinese indie": "chinese indie",
    "taiwanese indie": "taiwanese indie",
    "korean indie": "korean indie",
    "japanese indie": "japanese indie",
    "neo-soul": "neo-soul",
    "nu-jazz": "nu-jazz",
    "dark jazz": "dark jazz",
    "vocal jazz": "vocal jazz",
    "cool jazz": "cool jazz",
    "ambient jazz": "ambient jazz",
    "jazz fusion": "jazz fusion",
    "fusion jazz": "jazz fusion",
    "math jazz": "math jazz",
    "jazz rap": "jazz rap",
    "jazz hop": "jazz hop",
    "contemporary classical": "contemporary classical",
    "modern classical": "contemporary classical",
    "new-classical": "contemporary classical",
    "neoclassical": "contemporary classical",
    "neo-classical": "contemporary classical",
    "classical": "classical",
    "classic rock": "classic rock",
    "britpop": "britpop",
    "synthpop": "synthpop",
    "electropop": "electropop",
    "dance pop": "dance pop",
    "dance punk": "dance-punk",
    "dance-punk": "dance-punk",
    "electro rock": "electro-rock",
    "chillout": "chillout",
    "downtempo": "downtempo",
    "trip-hop": "trip-hop",
    "hip-hop": "hip-hop",
    "post-rock": "post-rock",
    "post punk": "post-punk",
    "post-punk": "post-punk",
    "proto-punk": "proto-punk",
    "art pop": "art pop",
    "art rock": "art rock",
    "psychedelic rock": "psychedelic rock",
    "psychedelic-rock": "psychedelic rock",
    "shoegaze": "shoegaze",
    "dream pop": "dream pop",
    "bedroom pop": "bedroom pop",
    "chamber music": "chamber music",
    "chamber folk": "chamber folk",
    "folk rock": "folk rock",
    "folk pop": "folk pop",
    "country folk": "country folk",
    "classic country": "classic country",
    "alternative rock": "alternative rock",
    "indie-rock": "indie-rock",
    "alt-country": "alt-country",
    "blues rock": "blues rock",
    "piano rock": "piano rock",
    "pop rock": "pop rock",
    "soft rock": "soft rock",
    "soul": "soul",
    "funk": "funk",
    "funk rock": "funk rock",
    "gospel": "gospel",
    "ambient": "ambient",
    "ambient-rock": "ambient-rock",
    "drone": "drone",
    "experimental": "experimental",
    "avant-garde": "avant-garde",
    "minimal": "minimal",
    "minimalism": "minimalism",
    "neoclassical": "contemporary classical",
    "new wave": "new wave",
    "synth": "synth",
    "synthpop": "synthpop",
    "electronic": "electronic",
    "electro": "electro",
    "idm": "idm",
    "techno": "techno",
    "trance": "trance",
    "house": "house",
    "electro house": "electro house",
    "ebm": "ebm",
    "industrial": "industrial",
    "noise pop": "noise pop",
    "nu metal": "nu metal",
    "heavy metal": "heavy metal",
    "alternative metal": "alternative metal",
    "grindcore": "grindcore",
    "hardcore": "hardcore",
    "punk rock": "punk rock",
    "pop punk": "pop punk",
    "emo": "emo",
    "emo rap": "emo rap",
    "melodic rap": "melodic rap",
    "narrative rap": "narrative rap",
    "trap": "trap",
    "cloud rap": "cloud rap",
    "lo-fi beat": "lo-fi beat",
    "chillhop": "chillhop",
    "lounge": "lounge",
    "bossa nova": "bossa nova",
    "afrobeat": "afrobeat",
    "afrobeats": "afrobeat",
    "reggaeton": "reggaeton",
    "disco": "disco",
    "funky": "funk",
    "groovy": "groove",
    "swing": "swing",
    "surf rock": "surf rock",
    "garage rock": "garage rock",
    "russian rock": "russian rock",
    "polish rock": "polish rock",
    "orchestral": "orchestral",
    "orchestra": "orchestral",
    "symphonic": "symphonic",
    "soundtrack": "soundtrack",
    "musical": "musical",
    "opera": "opera",
    "cinematic": "cinematic",
    "video game music": "video game music",
    "composer": "composer",
    "piano": "piano",
    "guitar": "guitar",
    "acoustic": "acoustic",
    "acoustic guitar": "acoustic",
    "pure-piano": "piano",
    "classical guitar": "classical guitar",
    "string": "strings",
    "balearic": "balearic",
    "shibuya-kei": "shibuya-kei",
    "shimokita-kei": "shimokita-kei",
    "jakarta": "jakarta",
    "taiwan": "taiwan",
    "hong kong": "hong kong",
    "cantonese": "cantonese",
    "mandarin": "mandarin",
    "chinese folk": "chinese folk",
    "taiwanese folk": "taiwanese folk",
    "korean folk": "korean folk",
    "宁波话 folk": "ningbo folk",
    "闽南": "minnan folk",
    "ballad": "ballad",
    "mellow": "mellow",
    "mellow pop": "mellow pop",
    "daydreaming": "daydreaming",
    "dreamy": "dreamy",
    "spokojne": "spokojne",
    "yearning": "yearning",
    "meow": "meow",
    "nya": "nya",
    "ziontwan": "ziontwan",
    "utrecht": "utrecht",
    "england": "united kingdom",
    "united kingdom": "united kingdom",
}

# ─── 明确剔除非风格标签 ─────────────────────────────────────────
# 这些是从 Last.fm 用户标签误入的人名、年份、收藏夹名
BLACKLIST = {
    # 艺人名
    "coldplay", "jay chou", "michael jackson", "frank sinatra",
    "johnny cash", "jim reeves", "mika", "andy tubman",
    "actress", "onerepublic", "glee", "nick toons",
    "nickelodeon", "spongebob", "pieater", "myf",
    # 年份 / 专辑状态
    "2017 releases", "2018 releases", "2025 albums", "2026 albums",
    "00s", "50s", "60s", "70s", "80s",
    # 收藏夹 / 播放列表名
    "albums i have listened", "albums i own on vinyl",
    "albumsdoudoune", "all", "beloved", "finished",
    "good ablum", "lesser known yet streamable artists",
    "literate", "mixtaperoom", "my private work station",
    "my top songs", "on the records",
    # 城市名（非音乐风格）
    "los angeles", "bejing", "jakarta",
    # 国家/地区名（这些已在 region 字段，不该出现在 geners）
    "england", "united kingdom",
    # 唱片公司/厂牌
    "fly the light records", "ark music factory",
    # 其他噪音
    "male vocalists", "boyband", "christian", "christian rock",
    "title is declararative", "classic country",  # 已在 synonym 里处理，双重保险
    "red (taylor's version)", "banda sonora",
    "klassische gitarre", "meow", "nya", "ziontwan",
    "utrecht", "yearning", "spokojne", "daydreaming",
    "downt",  # 明显是专辑名被误当标签
}

# ─── 清洗函数 ───────────────────────────────────────────────────

def clean_genre_tag(tag: str) -> str | None:
    """
    清洗单个标签：
    1. 转小写、去首尾空格
    2. 若在 BLACKLIST 中 → 返回 None（剔除）
    3. 若在 SYNONYM_MAP 中 → 返回规范名
    4. 否则返回小写形式
    """
    if not tag or not isinstance(tag, str):
        return None
    t = tag.strip().lower()
    if not t:
        return None
    # 黑名单检查
    if t in BLACKLIST:
        return None
    # 同义词合并
    if t in SYNONYM_MAP:
        return SYNONYM_MAP[t]
    return t


def clean_album_genres(album: dict) -> list[str]:
    """清洗单张专辑的 geners 字段，返回去重后的干净列表"""
    raw = album.get("genres", [])
    if not raw:
        return []
    seen = set()
    cleaned = []
    for g in raw:
        cg = clean_genre_tag(g)
        if cg is None:
            continue
        if cg not in seen:
            seen.add(cg)
            cleaned.append(cg)
    return cleaned


def main():
    # 1. 备份
    if not BACKUP_FILE.exists():
        shutil.copy2(ALBUMS_FILE, BACKUP_FILE)
        print(f"✓ 已备份到 {BACKUP_FILE}")
    else:
        print(f"· 备份已存在，跳过")

    # 2. 加载数据
    with open(ALBUMS_FILE, "r", encoding="utf-8") as f:
        albums = json.load(f)

    # 3. 统计清洗前状态
    before_counter = Counter()
    for a in albums:
        for g in a.get("genres", []):
            before_counter[g] += 1
    before_unique = len(before_counter)

    # 4. 清洗
    changed_count = 0
    removed_tags = []  # (album_name, old_tags, new_tags)

    after_counter = Counter()

    for album in albums:
        old = album.get("genres", [])
        new = clean_album_genres(album)
        album["genres"] = new
        for g in new:
            after_counter[g] += 1
        if old != new:
            changed_count += 1
            removed_tags.append((album["name"], old, new))

    after_unique = len(after_counter)

    # 5. 写回
    with open(ALBUMS_FILE, "w", encoding="utf-8") as f:
        json.dump(albums, f, ensure_ascii=False, indent=2)

    # 6. 报告
    print(f"\n{'='*50}")
    print(f"清洗完成")
    print(f"{'='*50}")
    print(f"处理专辑数：{len(albums)}")
    print(f"有变更的专辑：{changed_count}")
    print(f"清洗前风格种类：{before_unique}")
    print(f"清洗后风格种类：{after_unique}")
    print(f"减少种类数：{before_unique - after_unique}")

    # 分类统计变更情况
    blacklisted = set()   # 被黑名单剔除的
    synonym_changed = set()  # 被同义词合并的
    for name, old, new in removed_tags:
        old_set = set(old)
        new_set = set(new)
        # 旧标签中，既不在新标签里、也不在 synonym_map 的值里的 → 黑名单
        for t in old_set:
            tl = t.strip().lower() if isinstance(t, str) else ""
            if tl not in new_set:
                if tl in BLACKLIST:
                    blacklisted.add(t)
                elif tl in SYNONYM_MAP:
                    synonym_changed.add(f"{t} → {SYNONYM_MAP[tl]}")
                else:
                    # 大小写统一（如 Jazz → jazz）也属于 synonym 或 manual
                    pass

    if synonym_changed:
        print(f"\n同义词合并（部分示例，共 {len(synonym_changed)} 项）：")
        for item in sorted(synonym_changed)[:30]:
            print(f"  ↻ {item}")
    if blacklisted:
        print(f"\n黑名单剔除（共 {len(blacklisted)} 项）：")
        for tag in sorted(blacklisted):
            print(f"  ✗ {tag}")


if __name__ == "__main__":
    main()
