"""
专辑数据库管理模块
- 从 Notion 导出的 CSV/JSON 导入专辑数据
- 字段标准化（标签拆分、数值默认值）
- albums.json 读写
- 专辑增删改查
"""

import json
import csv
import re
from pathlib import Path
from datetime import datetime
from typing import Optional


# 数据目录
DATA_DIR = Path(__file__).parent / "data"
ALBUMS_FILE = DATA_DIR / "albums.json"
HISTORY_FILE = DATA_DIR / "play_history.json"
CONFIG_FILE = Path(__file__).parent / "scheduler_config.json"


def _load_genre_noise_map() -> dict:
    """从 scheduler_config.json 加载风格→噪音映射表"""
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        m = cfg.get("genre_noise_map", {})
        # 过滤掉说明字段，只保留数值映射
        return {k: v for k, v in m.items() if isinstance(v, (int, float))}
    except (json.JSONDecodeError, IOError):
        return {}


def estimate_noise_from_genres(genres: list[str], genre_noise_map: dict = None) -> Optional[float]:
    """
    根据风格标签估算噪音程度。
    取所有匹配风格的平均值；无匹配则返回 None。
    """
    if genre_noise_map is None:
        genre_noise_map = _load_genre_noise_map()
    if not genres or not genre_noise_map:
        return None

    # 先精确匹配，再忽略大小写匹配
    lower_map = {k.lower(): v for k, v in genre_noise_map.items()}
    matched = []
    for g in genres:
        if g in genre_noise_map:
            matched.append(genre_noise_map[g])
        elif g.lower() in lower_map:
            matched.append(lower_map[g.lower()])

    if not matched:
        return None
    return round(sum(matched) / len(matched), 2)


def ensure_data_dir():
    """确保数据目录存在"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _parse_genres(raw: str) -> list[str]:
    """
    解析音乐类型标签字符串为列表。
    支持 Notion 导出的多种格式：
    - 逗号分隔: "math-rock, indie-rock"
    - 已经是列表: ["math-rock", "indie-rock"]
    - 空值
    """
    if not raw:
        return []
    if isinstance(raw, list):
        return [g.strip() for g in raw if g.strip()]
    # 逗号分隔字符串
    return [g.strip() for g in raw.split(",") if g.strip()]


def _parse_float(raw, default=None) -> Optional[float]:
    """安全解析浮点数"""
    if raw is None or raw == "" or raw == "null":
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


def _parse_date(raw) -> Optional[str]:
    """
    解析日期字段为 ISO 格式字符串 (YYYY-MM-DD)。
    支持多种输入格式。
    """
    if not raw or raw == "null":
        return None
    if isinstance(raw, str):
        raw = raw.strip()
        # 尝试常见日期格式
        for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", 
                     "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d %H:%M:%S"]:
            try:
                dt = datetime.strptime(raw[:len("2026-04-22T00:00:00.000Z")], fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        # 如果已经是 YYYY-MM-DD 格式直接返回
        if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
            return raw
    return None


def _clean_str(val) -> Optional[str]:
    """清理字符串值，空值/None/"None" 返回 None"""
    if val is None:
        return None
    s = str(val).strip()
    if s == "" or s.lower() == "none" or s.lower() == "null":
        return None
    return s


def _normalize_album(raw: dict) -> dict:
    """
    将原始导入数据标准化为统一的专辑记录格式。
    兼容 Notion CSV 导出的各种字段名。
    """
    # Notion 列名映射（中文 -> 标准字段名）
    name_map = {
        "专辑名": "name",
        "name": "name",
        "Name": "name",
        "歌手/乐队": "artist",
        "歌手": "artist",
        "乐队": "artist",
        "艺人": "artist",
        "artist": "artist",
        "Artist": "artist",
        "音乐类型+特点": "genres",
        "音乐类型": "genres",
        "genres": "genres",
        "地区": "region",
        "region": "region",
        "噪音程度": "noise_level",
        "noise_level": "noise_level",
        "摇摆速率": "swing_rate",
        "swing_rate": "swing_rate",
        "负担程度": "burden_level",
        "burden_level": "burden_level",
        "上一轮店里放": "last_played",
        "last_played": "last_played",
        "URL": "qq_music_url",
        "url": "qq_music_url",
        "qq_music_url": "qq_music_url",
    }

    # 先做字段名映射
    mapped = {}
    for k, v in raw.items():
        std_key = name_map.get(k.strip(), k.strip())
        mapped[std_key] = v

    album = {
        "name": str(mapped.get("name", "")).strip(),
        "artist": _clean_str(mapped.get("artist")) or "",
        "genres": _parse_genres(mapped.get("genres", "")),
        "region": _clean_str(mapped.get("region")) or "未知",
        "noise_level": _parse_float(mapped.get("noise_level")),
        "noise_source": "manual",  # manual=手动填写, estimated=风格估算, default=兜底默认
        "swing_rate": _parse_float(mapped.get("swing_rate")),
        "burden_level": _parse_float(mapped.get("burden_level")),
        "last_played": _parse_date(mapped.get("last_played")),
        "qq_music_url": _clean_str(mapped.get("qq_music_url")),
        "qq_music_album_mid": None,
        "duration_seconds": _parse_float(mapped.get("duration_seconds")),
        "tracks": mapped.get("tracks") if isinstance(mapped.get("tracks"), list) else None,
    }

    # 噪音程度缺失时：先尝试风格估算，再用默认值 4.0 兜底
    if album["noise_level"] is None:
        estimated = estimate_noise_from_genres(album["genres"])
        if estimated is not None:
            album["noise_level"] = estimated
            album["noise_source"] = "estimated"
        else:
            album["noise_level"] = 4.0
            album["noise_source"] = "default"

    # 尝试从 URL 提取 album mid
    if album["qq_music_url"]:
        album["qq_music_album_mid"] = extract_album_mid(album["qq_music_url"])

    return album


def extract_album_mid(url: str) -> Optional[str]:
    """
    从 QQ 音乐专辑 URL 中提取 album mid。
    支持格式：
    - https://y.qq.com/n/ryqq/albumDetail/XXXXX
    - https://c6.y.qq.com/base/fcgi-bin/u?__=XXXXX
    - 直接是 mid 字符串
    """
    if not url:
        return None
    
    # albumDetail/XXXXX
    m = re.search(r"albumDetail/(\w+)", url)
    if m:
        return m.group(1)
    
    # 短链接中的参数
    m = re.search(r"[?&]__=(\w+)", url)
    if m:
        return m.group(1)
    
    # 如果本身就像个 mid（纯字母数字，6-20位）
    if re.match(r"^[a-zA-Z0-9]{6,20}$", url.strip()):
        return url.strip()
    
    return None


# ─── 数据库读写 ───


def load_albums() -> list[dict]:
    """读取专辑数据库"""
    ensure_data_dir()
    if not ALBUMS_FILE.exists():
        return []
    try:
        with open(ALBUMS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError):
        return []


def save_albums(albums: list[dict]):
    """保存专辑数据库"""
    ensure_data_dir()
    with open(ALBUMS_FILE, "w", encoding="utf-8") as f:
        json.dump(albums, f, ensure_ascii=False, indent=2)


def load_play_history() -> dict:
    """读取播放历史"""
    ensure_data_dir()
    if not HISTORY_FILE.exists():
        return {}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_play_history(history: dict):
    """保存播放历史"""
    ensure_data_dir()
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


# ─── 导入功能 ───


def _merge_preserve_fetched(new_album: dict, old_album: dict) -> dict:
    """
    合并时保留旧记录中已抓取的 QQ 音乐数据。
    CSV 中一般不带这些字段，不能覆盖为空。
    """
    # 需要保留的「抓取型」字段：CSV 里没有就沿用旧值
    fetched_fields = [
        "qq_music_url",
        "qq_music_album_mid",
        "duration_seconds",
        "tracks",
    ]
    for field in fetched_fields:
        if not new_album.get(field) and old_album.get(field):
            new_album[field] = old_album[field]
    return new_album


def import_from_csv(csv_path: str, merge: bool = True) -> tuple[int, int, int]:
    """
    从 Notion 导出的 CSV 导入专辑数据。
    
    Args:
        csv_path: CSV 文件路径
        merge: True 则与现有数据合并（按专辑名去重），False 则覆盖
    
    Returns:
        (new_count, updated_count, removed_count)
        - merge=True:  新增 / 更新(保留URL+时长) / CSV中不存在而被移除的
        - merge=False: 导入总数 / 0 / 0
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV 文件不存在: {csv_path}")
    
    # 读取 CSV
    imported = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            album = _normalize_album(row)
            if album["name"]:  # 跳过空名称
                imported.append(album)
    
    if not merge:
        save_albums(imported)
        return len(imported), 0, 0
    
    # 合并模式：按名称去重
    existing = load_albums()
    existing_map = {a["name"]: a for a in existing}
    imported_names = set()
    
    new_count = 0
    updated_count = 0
    
    # 构建合并后的有序列表（保持 CSV 顺序）
    merged = []
    
    for album in imported:
        imported_names.add(album["name"])
        if album["name"] in existing_map:
            # 更新：保留已有的抓取数据
            old = existing_map[album["name"]]
            album = _merge_preserve_fetched(album, old)
            updated_count += 1
        else:
            new_count += 1
        merged.append(album)
    
    # 统计被移除的（在旧数据中有但 CSV 里没有的）
    removed_count = 0
    for name in existing_map:
        if name not in imported_names:
            removed_count += 1
    
    save_albums(merged)
    return new_count, updated_count, removed_count


def import_from_json(json_path: str, merge: bool = True) -> tuple[int, int, int]:
    """
    从 JSON 文件导入专辑数据。
    JSON 应为数组格式 [{...}, {...}, ...]
    
    Returns:
        (new_count, updated_count, removed_count)
    """
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"JSON 文件不存在: {json_path}")
    
    with open(path, "r", encoding="utf-8") as f:
        raw_list = json.load(f)
    
    if not isinstance(raw_list, list):
        raise ValueError("JSON 文件应为数组格式")
    
    imported = []
    for raw in raw_list:
        album = _normalize_album(raw)
        if album["name"]:
            imported.append(album)
    
    if not merge:
        save_albums(imported)
        return len(imported), 0, 0
    
    existing = load_albums()
    existing_map = {a["name"]: a for a in existing}
    imported_names = set()
    
    new_count = 0
    updated_count = 0
    merged = []
    
    for album in imported:
        imported_names.add(album["name"])
        if album["name"] in existing_map:
            old = existing_map[album["name"]]
            album = _merge_preserve_fetched(album, old)
            updated_count += 1
        else:
            new_count += 1
        merged.append(album)
    
    removed_count = sum(1 for name in existing_map if name not in imported_names)
    
    save_albums(merged)
    return new_count, updated_count, removed_count


# ─── 查询功能 ───


def find_album(name: str) -> Optional[dict]:
    """按名称查找专辑"""
    albums = load_albums()
    for a in albums:
        if a["name"] == name:
            return a
    return None


def find_albums_by_genre(genre: str) -> list[dict]:
    """按风格标签查找专辑"""
    albums = load_albums()
    genre_lower = genre.lower()
    return [a for a in albums if any(g.lower() == genre_lower for g in a.get("genres", []))]


def get_albums_without_duration() -> list[dict]:
    """获取没有时长数据的专辑列表"""
    albums = load_albums()
    return [a for a in albums if not a.get("duration_seconds")]


def get_album_stats() -> dict:
    """获取专辑库统计信息"""
    albums = load_albums()
    if not albums:
        return {"total": 0}
    
    genres = set()
    regions = set()
    with_duration = 0
    with_url = 0
    noise_sources = {"manual": 0, "estimated": 0, "default": 0}
    
    for a in albums:
        for g in a.get("genres", []):
            genres.add(g)
        if a.get("region"):
            regions.add(a["region"])
        if a.get("duration_seconds"):
            with_duration += 1
        if a.get("qq_music_url"):
            with_url += 1
        src = a.get("noise_source", "manual")
        noise_sources[src] = noise_sources.get(src, 0) + 1
    
    return {
        "total": len(albums),
        "genres": sorted(genres),
        "genre_count": len(genres),
        "regions": sorted(regions),
        "with_duration": with_duration,
        "without_duration": len(albums) - with_duration,
        "with_qq_url": with_url,
        "noise_sources": noise_sources,
    }


# ─── 更新功能 ───


def update_album(name: str, updates: dict) -> bool:
    """
    更新指定专辑的字段。
    
    Args:
        name: 专辑名
        updates: 要更新的字段字典
    
    Returns:
        是否找到并更新成功
    """
    albums = load_albums()
    for i, a in enumerate(albums):
        if a["name"] == name:
            albums[i].update(updates)
            save_albums(albums)
            return True
    return False


def update_album_duration(name: str, duration_seconds: int, tracks: list[dict] = None) -> bool:
    """更新专辑时长（由 duration_fetcher 调用）"""
    updates = {"duration_seconds": duration_seconds}
    if tracks:
        updates["tracks"] = tracks
    return update_album(name, updates)


def update_last_played(album_names: list[str], date_str: str):
    """批量更新专辑的上次播放日期"""
    albums = load_albums()
    name_set = set(album_names)
    for a in albums:
        if a["name"] in name_set:
            a["last_played"] = date_str
    save_albums(albums)


if __name__ == "__main__":
    # 简单测试
    stats = get_album_stats()
    print(f"专辑库统计: {json.dumps(stats, ensure_ascii=False, indent=2)}")
