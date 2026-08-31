#!/usr/bin/env python3
"""下载进度监控 — 每 5 秒更新 _dl_progress.json"""
import json, time, re
from pathlib import Path

LOG = Path("/Users/kaluozheng/Music-Player-Investigation/SongBase/SongResources/_download_log.txt")
JSON_OUT = Path("/Users/kaluozheng/Music-Player-Investigation/SongBase/_search_progress.json")
PENDING = Path("/Users/kaluozheng/Music-Player-Investigation/SongBase/_pending_downloads.txt")

# 总数
total = len([l for l in PENDING.read_text().strip().split("\n") if l.strip()])

while True:
    try:
        completed = 0
        failed = 0
        if LOG.exists():
            for line in LOG.read_text().split("\n"):
                if "✅" in line:
                    completed += 1
                elif "❌" in line or "⏭" in line:
                    failed += 1

        # 当前正在下载的
        current = ""
        if LOG.exists():
            lines = LOG.read_text().strip().split("\n")
            for line in reversed(lines):
                m = re.match(r'^\[\d{2}:\d{2}:\d{2}\] \[(\d+)/\d+\] (.+)', line)
                if m:
                    current = m.group(2)
                    break

        progress = {
            "total": total,
            "completed": completed,
            "failed": failed,
            "pending": total - completed - failed,
            "pct": round(completed / max(total, 1) * 100, 1),
            "current": current,
            "updated": time.strftime("%H:%M:%S"),
        }
        JSON_OUT.write_text(json.dumps(progress, ensure_ascii=False))
    except:
        pass
    time.sleep(5)
