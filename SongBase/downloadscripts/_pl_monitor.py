#!/usr/bin/env python3
"""歌单更新进度监控 — 读取 JSON 统计新歌单 YouTube 搜索进度"""
import json, time
from pathlib import Path

JSON_PATH = Path("/Users/kaluozheng/Music-Player-Investigation/SongBase/qqmusic_playlists.json")
OUT_PATH = Path("/Users/kaluozheng/Music-Player-Investigation/SongResources/_pl_progress.json")

NEW_PLAYLIST_NAMES = ["车里听 perhaps早上", "早上超级缓着听", "Piano"]

while True:
    try:
        if JSON_PATH.exists():
            data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
            # 取最后 3 个歌单（新加的）
            new_pls = [p for p in data if p["name"] in NEW_PLAYLIST_NAMES]
            if len(new_pls) < 3:
                # fallback: 取最后 3 个
                new_pls = data[-3:]

            playlists_info = []
            total = total_yt = 0
            for pl in new_pls:
                cnt = pl["song_count"]
                yt = sum(1 for s in pl["songs"] if s.get("youtube_link"))
                playlists_info.append({
                    "name": pl["name"],
                    "total": cnt,
                    "yt": yt,
                    "link": pl["link"],
                })
                total += cnt
                total_yt += yt

            pct = round(total_yt / max(total, 1) * 100, 1)
            progress = {
                "total_songs": total,
                "yt_matched": total_yt,
                "pct": pct,
                "playlists": playlists_info,
                "all_playlists_count": len(data),
                "all_songs_count": sum(p["song_count"] for p in data),
                "all_yt_count": sum(1 for p in data for s in p["songs"] if s.get("youtube_link")),
                "updated_at": time.strftime("%H:%M:%S"),
                "status": "完成" if pct > 90 else "搜索中...",
            }
        else:
            progress = {"status": "等待数据...", "total_songs": 364, "yt_matched": 0, "pct": 0, "playlists": []}

        OUT_PATH.write_text(json.dumps(progress, ensure_ascii=False))
    except Exception as e:
        print(f"错误: {e}")

    time.sleep(5)
