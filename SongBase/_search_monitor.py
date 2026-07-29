#!/usr/bin/env python3
"""YT/BL 搜索进度监控 — 每 5 秒更新 _search_progress.json"""
import json, time, re
from pathlib import Path

JSON_SRC = Path("/Users/kaluozheng/Music-Player-Investigation/SongBase/song_base_by_artist.json")
JSON_OUT = JSON_SRC.parent / "_search_progress.json"
SEARCH_LOG = JSON_SRC.parent / "_search_live.txt"

def read_current():
    """读取当前正在搜索的曲目"""
    if SEARCH_LOG.exists():
        line = SEARCH_LOG.read_text().strip()
        if line:
            return line
    return ""

while True:
    try:
        d = json.loads(JSON_SRC.read_text(encoding="utf-8"))
        total = d['total_unique_songs']
        yt_total = sum(1 for singer in d['singers'] for s in singer['songs'] if s.get('youtube'))
        bl_total = sum(1 for singer in d['singers'] for s in singer['songs'] if s.get('bilibili'))

        progress = {
            "total": total,
            "yt": yt_total,
            "bl": bl_total,
            "pending": max(0, total - yt_total),
            "pct_yt": round(yt_total / max(total, 1) * 100, 1),
            "pct_bl": round(bl_total / max(total, 1) * 100, 1),
            "updated_at": time.strftime("%H:%M:%S"),
            "singers_total": d['total_singers'],
            "current": read_current(),
        }
        JSON_OUT.write_text(json.dumps(progress, ensure_ascii=False))
    except Exception as e:
        print(f"错误: {e}")
    time.sleep(5)
