"""
从 song_base_by_artist.json 中提取有 YT 链接的新增专辑歌曲，写入 _pending_downloads.txt
"""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = BASE / "song_base_by_artist.json"
CONFIG = BASE / "new_albums_config.json"
OUT = BASE / "_pending_downloads.txt"

data = json.loads(SRC.read_text(encoding="utf-8"))

# 读取当前配置中的专辑
if CONFIG.exists():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    target_albums = {(c["artist"], c["album"]) for c in config}
else:
    target_albums = None

entries = []
for s in data["singers"]:
    for sg in s["songs"]:
        yt = sg.get("youtube", "").strip()
        if not yt:
            continue
        # 如果有限定专辑范围则过滤
        if target_albums and (sg["full_singer"], sg["album"]) not in target_albums:
            continue
        entries.append(f"{sg['title']}\t{sg['full_singer']}\t{yt}")

OUT.write_text("\n".join(entries) + "\n", encoding="utf-8")
print(f"已写入 {len(entries)} 首歌到 {OUT}")
