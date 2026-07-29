#!/usr/bin/env python3
"""下载 _pending_downloads.txt 中所有 YT 链接到 SongResources"""
import json, re, subprocess, time
from pathlib import Path

YTDLP = "/Users/kaluozheng/.workbuddy/skills/video-audio-to-mp3/venv/bin/yt-dlp"
FFMPEG = "/Users/kaluozheng/.workbuddy/skills/video-audio-to-mp3/venv/lib/python3.13/site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
NODE = "/Users/kaluozheng/.workbuddy/binaries/node/versions/22.22.2/bin/node"
OUT_DIR = Path("/Users/kaluozheng/Music-Player-Investigation/SongBase/SongResources")
TMP_DIR = Path("/tmp/yt_dl")
LOG_PATH = OUT_DIR / "_download_log.txt"
PENDING = Path("/Users/kaluozheng/Music-Player-Investigation/SongBase/_pending_downloads.txt")

def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")

def safe_name(name):
    return re.sub(r'[\\/:*?"<>|]', '', name).strip()

TMP_DIR.mkdir(exist_ok=True)

with open(PENDING) as f:
    lines = [l.strip().split("\t") for l in f if l.strip()]

tasks = [(name, artist, url) for name, artist, url in lines]

log(f"加载 {len(tasks)} 个下载任务")

success = 0
fail = 0
t0 = time.time()

for i, (name, artist, url) in enumerate(tasks, 1):
    target = OUT_DIR / f"{safe_name(name)} - {safe_name(artist)}.mp3"
    if target.exists() and target.stat().st_size > 0:
        log(f"[{i}/{len(tasks)}] {name} - {artist} (已存在，跳过)")
        continue

    log(f"[{i}/{len(tasks)}] {name} - {artist}")

    try:
        result = subprocess.run(
            [
                YTDLP, url,
                "--cookies-from-browser", "firefox",
                "--js-runtimes", f"node:{NODE}",
                "--ffmpeg-location", FFMPEG,
                "-f", "bestaudio",
                "--extract-audio", "--audio-format", "mp3",
                "--audio-quality", "192k",
                "-o", str(TMP_DIR / "%(title)s.%(ext)s"),
            ],
            capture_output=True, text=True, timeout=300,
        )

        if result.returncode != 0:
            err = (result.stderr or "") + (result.stdout or "")
            if "Video unavailable" in err or "Private video" in err:
                log(f"  ⏭ 跳过（视频不可用）")
                fail += 1
                continue
            else:
                log(f"  ❌ 下载失败")
                fail += 1
                continue

        # 找下载的 MP3
        downloaded = list(TMP_DIR.glob("*.mp3"))
        if not downloaded:
            log(f"  ❌ 未找到输出")
            fail += 1
            continue

        downloaded.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        src = downloaded[0]
        import shutil
        shutil.move(str(src), str(target))
        size_mb = target.stat().st_size / (1024 * 1024)
        log(f"  ✅ {size_mb:.1f}MB")
        success += 1

    except subprocess.TimeoutExpired:
        log(f"  ⏱ 超时")
        fail += 1
    except Exception as e:
        log(f"  ❌ {e}")
        fail += 1

    time.sleep(2)

elapsed = int(time.time() - t0)
log(f"\n{'='*50}")
log(f"完成! 成功:{success} 失败:{fail} 总计:{len(tasks)} 耗时:{elapsed}s")
log(f"输出: {OUT_DIR}")
