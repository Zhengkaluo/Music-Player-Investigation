#!/usr/bin/env python3
"""
批量下载 YouTube 音频 → MP3，按「歌名 - 歌手」命名。
从 SongBase/qqmusic_playlists.json 读取已有的 YouTube 链接，
调用 video-audio-to-mp3 skill 逐个下载。
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

SKILL_VENV = "/Users/kaluozheng/.workbuddy/skills/video-audio-to-mp3/venv"
YTDLP_BIN = f"{SKILL_VENV}/bin/yt-dlp"
FFMPEG_BIN = f"{SKILL_VENV}/lib/python3.13/site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
NODE_BIN = "/Users/kaluozheng/.workbuddy/binaries/node/versions/22.22.2/bin/node"
JSON_PATH = "/Users/kaluozheng/Music-Player-Investigation/SongBase/qqmusic_playlists.json"
OUT_DIR = Path("/Users/kaluozheng/Music-Player-Investigation/SongResources")
LOG_PATH = OUT_DIR / "_download_log.txt"

def sanitize_filename(name: str) -> str:
    """清洗文件名，去掉非法字符"""
    name = re.sub(r'[\\/:*?"<>|]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    # 限制长度
    if len(name) > 180:
        name = name[:180]
    return name

def load_tasks():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        playlists = json.load(f)

    tasks = []
    seen = set()
    for pl in playlists:
        for s in pl["songs"]:
            url = s.get("youtube_link", "").strip()
            if not url:
                continue
            name = sanitize_filename(s["name"])
            singer = sanitize_filename(s["singer"].split(",")[0].strip())  # 只取第一个歌手
            filename = f"{name} - {singer}.mp3"
            if filename in seen:
                continue  # 跳过完全重名的（同一首歌在不同歌单出现）
            seen.add(filename)
            tasks.append({
                "url": url,
                "filename": filename,
                "song_name": s["name"],
                "singer": s["singer"],
                "playlist": pl["name"],
            })
    return tasks

def log(msg: str):
    timestamp = time.strftime("%H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    tasks = load_tasks()
    # 去掉已存在的文件
    pending = []
    for t in tasks:
        target = OUT_DIR / t["filename"]
        if target.exists():
            continue
        pending.append(t)

    total = len(tasks)
    done = total - len(pending)
    log(f"加载 {total} 个任务，已完成 {done}，待下载 {len(pending)}")

    if not pending:
        log("全部已完成！")
        return

    success = 0
    fail = 0

    for i, t in enumerate(pending):
        idx = done + i + 1
        target = OUT_DIR / t["filename"]
        log(f"[{idx}/{total}] {t['song_name']} — {t['singer']}")

        try:
            # 下载到 /tmp 避免沙箱删除限制
            tmp_dir = Path("/tmp/yt_dl")
            tmp_dir.mkdir(exist_ok=True)

            result = subprocess.run(
                [
                    YTDLP_BIN,
                    "--cookies-from-browser", "firefox",
                    "--js-runtimes", f"node:{NODE_BIN}",
                    "--ffmpeg-location", FFMPEG_BIN,
                    "-f", "bestaudio",
                    "--extract-audio",
                    "--audio-format", "mp3",
                    "--audio-quality", "192k",
                    "-o", str(tmp_dir / "%(title)s.%(ext)s"),
                    t["url"],
                ],
                capture_output=True, text=True, timeout=300,
            )

            if result.returncode != 0:
                # 检查已知的软失败
                stderr = result.stderr or ""
                stdout = result.stdout or ""
                combined = stderr + stdout
                if "Video unavailable" in combined or "Private video" in combined:
                    log(f"  ⏭ 跳过（视频不可用）")
                    # 标记为已处理，不再重试
                    target.touch()  # 创建空文件标记
                    fail += 1
                    time.sleep(3)
                    continue
                elif "Sign in to confirm" in combined:
                    log(f"  ⚠ YouTube bot 检测，需要浏览器登录")
                    fail += 1
                    time.sleep(10)
                    continue
                else:
                    log(f"  ❌ 下载失败: {stderr[-200:] if stderr else '未知错误'}")
                    fail += 1
                    time.sleep(5)
                    continue

            # 在临时目录找刚下载的 MP3
            downloaded = list(tmp_dir.glob("*.mp3"))
            if not downloaded:
                log(f"  ❌ 未找到下载文件")
                fail += 1
                continue

            # 取最新的文件
            downloaded.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            src = downloaded[0]

            # 移动到目标位置
            import shutil
            shutil.move(str(src), str(target))
            # /tmp 残留不清理，避免触发沙箱删除限制

            size_mb = target.stat().st_size / (1024 * 1024)
            log(f"  ✅ {size_mb:.1f}MB")
            success += 1

        except subprocess.TimeoutExpired:
            log(f"  ❌ 超时（5分钟）")
            fail += 1
        except Exception as e:
            log(f"  ❌ {type(e).__name__}: {e}")
            fail += 1

        # YouTube 限速保护
        delay = 8 if success > 0 and success % 5 == 0 else 3
        time.sleep(delay)

    # 清理临时目录
    tmp_dir = OUT_DIR / "_tmp"
    if tmp_dir.exists():
        for f in tmp_dir.glob("*"):
            try:
                f.unlink()
            except:
                pass
        try:
            tmp_dir.rmdir()
        except:
            pass

    log(f"\n{'='*50}")
    log(f"完成! 成功: {success} | 失败: {fail} | 总计: {total}")
    log(f"输出目录: {OUT_DIR}")

if __name__ == "__main__":
    main()
