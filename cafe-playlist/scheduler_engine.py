"""
歌单编排核心引擎
- 时段划分
- 四维评分算法（噪音匹配 / 风格偏好 / 轮播新鲜度 / 风格一致性）
- 贪心填充 + 时长校验
- 输出每日歌单
"""

import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import album_db


# ─── 配置加载 ───

CONFIG_FILE = Path(__file__).parent / "scheduler_config.json"
PLAYLISTS_DIR = Path(__file__).parent / "playlists"


def load_config() -> dict:
    """加载编排配置"""
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"配置文件不存在: {CONFIG_FILE}")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_time(t: str) -> tuple[int, int]:
    """解析 HH:MM 时间字符串为 (hour, minute)"""
    parts = t.strip().split(":")
    return int(parts[0]), int(parts[1])


def _time_to_minutes(t: str) -> int:
    """HH:MM -> 从零点开始的分钟数"""
    h, m = _parse_time(t)
    return h * 60 + m


def _slot_duration_seconds(slot: dict) -> int:
    """计算时段的总秒数"""
    start = _time_to_minutes(slot["start"])
    end = _time_to_minutes(slot["end"])
    return (end - start) * 60


# ─── 评分函数 ───


def _noise_match_score(album_noise: float, target_range: list[float]) -> float:
    """
    噪音匹配评分。
    使用高斯距离：噪音落在 target_range 中间时得分最高。
    
    target_range: [low, high]，如 [2, 4]
    """
    low, high = target_range
    center = (low + high) / 2.0
    sigma = (high - low) / 2.0  # 标准差设为范围的一半
    
    if sigma <= 0:
        sigma = 1.0
    
    # 高斯函数，峰值为 1.0
    distance = abs(album_noise - center)
    score = math.exp(-(distance ** 2) / (2 * sigma ** 2))
    
    return score


def _style_preference_score(album_genres: list[str], preferences: list[str]) -> float:
    """
    风格偏好评分。
    专辑标签命中偏好风格数量越多得分越高。
    """
    if not preferences:
        return 0.5  # 无偏好时中性分
    
    # 大小写不敏感匹配
    pref_lower = {p.lower() for p in preferences}
    genre_lower = {g.lower() for g in album_genres}
    
    hits = len(pref_lower & genre_lower)
    
    if hits == 0:
        return 0.1  # 不命中也给点底分
    
    # 归一化到 [0, 1]
    return min(1.0, hits / max(1, len(preferences)))


def _freshness_score(last_played: Optional[str], today: str, max_days: int = 60) -> float:
    """
    轮播新鲜度评分。
    距离上次播放天数越多分数越高。从未播放的专辑得满分。
    """
    if not last_played:
        return 1.0  # 从未播放，最高分
    
    try:
        last_dt = datetime.strptime(last_played, "%Y-%m-%d")
        today_dt = datetime.strptime(today, "%Y-%m-%d")
        days = (today_dt - last_dt).days
        
        if days <= 0:
            return 0.0  # 今天刚播过
        
        # 线性映射到 [0, 1]，max_days 天以上都给满分
        return min(1.0, days / max_days)
    except ValueError:
        return 0.8  # 日期解析失败，给较高分


def _cohesion_score(album_genres: list[str], selected_genres: set[str]) -> float:
    """
    风格一致性评分。
    与当天已选专辑的风格标签交集越大得分越高。
    第一张专辑（没有已选）给中性分。
    """
    if not selected_genres:
        return 0.5  # 第一张专辑，中性分
    
    if not album_genres:
        return 0.2
    
    genre_set = {g.lower() for g in album_genres}
    selected_lower = {g.lower() for g in selected_genres}
    
    intersection = len(genre_set & selected_lower)
    union = len(genre_set | selected_lower)
    
    if union == 0:
        return 0.5
    
    # Jaccard 相似度
    return intersection / union


def compute_score(
    album: dict,
    slot: dict,
    config: dict,
    today: str,
    selected_genres: set[str],
    play_history: dict,
) -> float:
    """
    计算专辑的综合评分。
    
    score = w_noise * noise_match 
          + w_style * style_preference 
          + w_fresh * freshness 
          + w_cohesion * cohesion
    """
    weights = config.get("weights", {})
    w_noise = weights.get("noise", 0.35)
    w_style = weights.get("style", 0.25)
    w_fresh = weights.get("freshness", 0.25)
    w_cohesion = weights.get("cohesion", 0.15)
    
    # 获取上次播放日期（优先从播放历史中获取，其次从专辑数据中获取）
    last_played = _get_last_played(album["name"], play_history) or album.get("last_played")
    
    s_noise = _noise_match_score(
        album.get("noise_level", 4.0),
        slot.get("target_noise", [3, 5])
    )
    s_style = _style_preference_score(
        album.get("genres", []),
        config.get("style_preferences", [])
    )
    s_fresh = _freshness_score(last_played, today)
    s_cohesion = _cohesion_score(album.get("genres", []), selected_genres)
    
    total = (w_noise * s_noise 
             + w_style * s_style 
             + w_fresh * s_fresh 
             + w_cohesion * s_cohesion)
    
    return total


def _get_last_played(album_name: str, play_history: dict) -> Optional[str]:
    """从播放历史中获取专辑最后一次播放日期"""
    latest = None
    for date_str, entry in play_history.items():
        albums_played = entry if isinstance(entry, list) else entry.get("albums", [])
        for item in albums_played:
            name = item if isinstance(item, str) else item.get("name", "")
            if name == album_name:
                if latest is None or date_str > latest:
                    latest = date_str
    return latest


# ─── 歌单生成 ───


def generate_playlist(
    date_str: Optional[str] = None,
    style_overrides: Optional[list[str]] = None,
    seed: Optional[int] = None,
    verbose: bool = True,
) -> dict:
    """
    生成指定日期的歌单。
    
    Args:
        date_str: 目标日期 YYYY-MM-DD，默认今天
        style_overrides: 临时风格偏好覆盖
        seed: 随机种子（用于复现）
        verbose: 打印详细信息
    
    Returns:
        歌单字典，包含按时段排列的专辑列表
    """
    config = load_config()
    albums = album_db.load_albums()
    play_history = album_db.load_play_history()
    
    if not albums:
        raise ValueError("专辑库为空，请先导入数据")
    
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    # 应用风格偏好覆盖
    if style_overrides:
        config["style_preferences"] = style_overrides
    
    # 设置随机种子
    actual_seed = seed or config.get("seed")
    if actual_seed is not None:
        random.seed(actual_seed)
    
    # 获取排除列表
    exclude = set(config.get("exclude_albums", []))
    
    # 默认时长
    default_dur = config.get("default_duration", 2400)
    
    time_slots = config.get("time_slots", [])
    if not time_slots:
        raise ValueError("配置中没有定义时段 (time_slots)")
    
    # 跟踪已选专辑（全天去重）
    selected_names = set()
    selected_genres = set()
    
    playlist_slots = []
    
    for slot in time_slots:
        slot_name = slot.get("label", slot.get("name", "未知"))
        slot_duration = _slot_duration_seconds(slot)
        
        if verbose:
            print(f"\n📌 {slot_name} ({slot['start']}-{slot['end']}, 需要 {slot_duration // 60} 分钟)")
        
        # 候选专辑：未被选过、未被排除
        candidates = [
            a for a in albums
            if a["name"] not in selected_names
            and a["name"] not in exclude
        ]
        
        if not candidates:
            if verbose:
                print(f"  ⚠️ 没有可用的候选专辑了")
            continue
        
        # 为每个候选计算评分
        scored = []
        for album in candidates:
            score = compute_score(
                album, slot, config, date_str, selected_genres, play_history
            )
            # 加一点随机扰动，避免每次结果完全一样
            score += random.uniform(0, 0.05)
            scored.append((score, album))
        
        # 按评分降序排序
        scored.sort(key=lambda x: x[0], reverse=True)
        
        # 贪心填充
        filled_duration = 0
        slot_albums = []
        
        for score, album in scored:
            if filled_duration >= slot_duration:
                break
            
            dur = album.get("duration_seconds") or default_dur
            
            slot_albums.append({
                "name": album["name"],
                "genres": album.get("genres", []),
                "noise_level": album.get("noise_level"),
                "duration_seconds": dur,
                "duration_display": f"{dur // 60}:{dur % 60:02d}",
                "score": round(score, 4),
                "qq_music_url": album.get("qq_music_url"),
            })
            
            filled_duration += dur
            selected_names.add(album["name"])
            for g in album.get("genres", []):
                selected_genres.add(g)
            
            if verbose:
                dur_min = dur // 60
                print(f"  ✅ {album['name']} ({dur_min}分, 噪音{album.get('noise_level', '?')}, "
                      f"评分{score:.3f})")
        
        slot_entry = {
            "slot_name": slot_name,
            "start": slot["start"],
            "end": slot["end"],
            "target_noise": slot.get("target_noise"),
            "target_duration_seconds": slot_duration,
            "actual_duration_seconds": filled_duration,
            "albums": slot_albums,
        }
        playlist_slots.append(slot_entry)
        
        if verbose:
            fill_pct = (filled_duration / slot_duration * 100) if slot_duration > 0 else 0
            print(f"  📊 填充: {filled_duration // 60}分 / {slot_duration // 60}分 ({fill_pct:.0f}%)")
    
    # 汇总
    total_target = sum(_slot_duration_seconds(s) for s in time_slots)
    total_actual = sum(s["actual_duration_seconds"] for s in playlist_slots)
    total_albums = sum(len(s["albums"]) for s in playlist_slots)
    
    playlist = {
        "date": date_str,
        "generated_at": datetime.now().isoformat(),
        "config_snapshot": {
            "business_hours": config.get("business_hours"),
            "style_preferences": config.get("style_preferences", []),
            "weights": config.get("weights"),
        },
        "summary": {
            "total_albums": total_albums,
            "target_duration_seconds": total_target,
            "actual_duration_seconds": total_actual,
            "target_duration_display": f"{total_target // 3600}h{(total_target % 3600) // 60:02d}m",
            "actual_duration_display": f"{total_actual // 3600}h{(total_actual % 3600) // 60:02d}m",
            "fill_percentage": round(total_actual / total_target * 100, 1) if total_target > 0 else 0,
        },
        "slots": playlist_slots,
    }
    
    return playlist


def save_playlist(playlist: dict):
    """保存歌单到文件"""
    PLAYLISTS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = playlist["date"]
    filepath = PLAYLISTS_DIR / f"{date_str}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(playlist, f, ensure_ascii=False, indent=2)
    return filepath


def load_playlist(date_str: str) -> Optional[dict]:
    """加载指定日期的歌单"""
    filepath = PLAYLISTS_DIR / f"{date_str}.json"
    if not filepath.exists():
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def update_play_history(playlist: dict):
    """根据歌单更新播放历史"""
    history = album_db.load_play_history()
    date_str = playlist["date"]
    
    played_albums = []
    for slot in playlist.get("slots", []):
        for album in slot.get("albums", []):
            played_albums.append({
                "name": album["name"],
                "slot": slot["slot_name"],
                "duration_seconds": album["duration_seconds"],
            })
    
    history[date_str] = {
        "albums": played_albums,
        "generated_at": playlist.get("generated_at"),
    }
    
    album_db.save_play_history(history)
    
    # 同时更新专辑的 last_played 字段
    album_names = [a["name"] for a in played_albums]
    album_db.update_last_played(album_names, date_str)


# ─── 格式化输出 ───


def format_playlist(playlist: dict) -> str:
    """格式化歌单为美观的文本输出"""
    lines = []
    
    summary = playlist.get("summary", {})
    config_snap = playlist.get("config_snapshot", {})
    
    lines.append(f"\n{'='*60}")
    lines.append(f"☕ 咖啡店歌单 — {playlist['date']}")
    lines.append(f"{'='*60}")
    lines.append(f"  总专辑数: {summary.get('total_albums', 0)}")
    lines.append(f"  目标时长: {summary.get('target_duration_display', '?')}")
    lines.append(f"  实际时长: {summary.get('actual_duration_display', '?')} "
                 f"({summary.get('fill_percentage', 0)}%)")
    
    prefs = config_snap.get("style_preferences", [])
    if prefs:
        lines.append(f"  风格偏好: {', '.join(prefs)}")
    
    for slot in playlist.get("slots", []):
        lines.append(f"\n{'─'*50}")
        lines.append(f"🕐 {slot['slot_name']} ({slot['start']} - {slot['end']})")
        lines.append(f"   目标噪音: {slot.get('target_noise', '?')}")
        
        actual_dur = slot.get('actual_duration_seconds', 0)
        target_dur = slot.get('target_duration_seconds', 0)
        lines.append(f"   时长: {actual_dur // 60}分 / {target_dur // 60}分")
        lines.append(f"{'─'*50}")
        
        for i, album in enumerate(slot.get("albums", []), 1):
            genres = ", ".join(album.get("genres", [])[:3])
            lines.append(
                f"  {i:2d}. 🎵 {album['name']}"
                f"  [{genres}]"
                f"  噪音:{album.get('noise_level', '?')}"
                f"  {album.get('duration_display', '?')}"
            )
            if album.get("qq_music_url"):
                lines.append(f"      🔗 {album['qq_music_url']}")
    
    lines.append(f"\n{'='*60}")
    lines.append(f"⏱️  生成时间: {playlist.get('generated_at', '?')}")
    lines.append(f"{'='*60}\n")
    
    return "\n".join(lines)


if __name__ == "__main__":
    # 简单测试
    config = load_config()
    print(f"配置加载成功: {json.dumps(config.get('business_hours'), ensure_ascii=False)}")
    print(f"时段数: {len(config.get('time_slots', []))}")
