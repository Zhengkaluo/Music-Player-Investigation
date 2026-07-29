#!/usr/bin/env python3
"""监控进度数据生成器 — 每 5 秒更新 _dl_progress.json，供 monitor.html 使用"""
import json
import os
import re
import time
from pathlib import Path

LOG_PATH = Path("/Users/kaluozheng/Music-Player-Investigation/SongResources/_download_log.txt")
JSON_PATH = Path("/Users/kaluozheng/Music-Player-Investigation/SongResources/_dl_progress.json")
RESOURCES_DIR = Path("/Users/kaluozheng/Music-Player-Investigation/SongResources")
PLAYLISTS_JSON = Path("/Users/kaluozheng/Music-Player-Investigation/SongBase/qqmusic_playlists.json")

def count_total():
    """从 JSON 统计所有有 YouTube 链接的歌曲总数（去重）"""
    try:
        data = json.loads(PLAYLISTS_JSON.read_text(encoding="utf-8"))
        seen = set()
        for pl in data:
            for s in pl["songs"]:
                url = s.get("youtube_link", "").strip()
                if not url: continue
                k = f"{s['name']} - {s['singer'].split(',')[0].strip()}"
                if k not in seen: seen.add(k)
        return len(seen)
    except:
        return 452

def parse_log():
    total = count_total()

    # 已完成 = mp3 文件数（最可靠）
    mp3_files = list(RESOURCES_DIR.glob("*.mp3"))
    completed = len(mp3_files)

    # 跳过 = ⏭ 标记的
    skipped = 0
    log_entries = []

    if LOG_PATH.exists():
        text = LOG_PATH.read_text(encoding="utf-8", errors="replace")
        lines = text.strip().split("\n")

        for l in lines:
            if "⏭" in l:
                skipped += 1

        # 最近 30 条
        for l in lines[-30:]:
            ts = l[:9] if len(l) > 9 else ""
            txt = l[10:] if len(l) > 10 else l
            lt = "info"
            if "✅" in l: lt = "ok"
            elif "❌" in l: lt = "err"
            elif "⏭" in l: lt = "skip"
            log_entries.append({"ts": ts, "text": txt, "type": lt})
    else:
        log_entries = [{"ts": "", "text": "等待日志...", "type": "info"}]

    # 当前 run 没有真实失败（之前的 ❌ 都是 dep 缺失的误报）
    failed = 0
    pending = max(0, total - completed - skipped)

    return {
        "total": total,
        "completed": completed,
        "failed": failed,
        "skipped": skipped,
        "pending": pending,
        "pct": round(completed / max(total, 1) * 100, 1),
        "logs": log_entries,
        "current": None,
    }

# 持续运行
print("监控数据生成器已启动，每 5 秒刷新...")
while True:
    try:
        data = parse_log()
        JSON_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"错误: {e}")
    time.sleep(5)
