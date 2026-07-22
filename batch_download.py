#!/usr/bin/env python3
"""批量下载 YouTube 音频，输出为 歌曲 - 歌手.mp3"""
import json
import os
import re
import subprocess
import sys
import time

# 配置
JSON_FILE = "/Users/kaluozheng/Music-Player-Investigation/outputs/youtube_links.json"
OUTPUT_DIR = "/Users/kaluozheng/Music-Player-Investigation/Flowset-个人审美打标-Demo/音乐第二波测试"
VIDEO_AUDIO_SCRIPT = "/Users/kaluozheng/.workbuddy/skills/video-audio-to-mp3/video_audio.py"
PYTHON = "/Users/kaluozheng/.workbuddy/skills/video-audio-to-mp3/venv/bin/python3"
SCRIPT_DIR = "/Users/kaluozheng/.workbuddy/skills/video-audio-to-mp3"

def sanitize(name):
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()

# 读取歌曲列表
with open(JSON_FILE, 'r', encoding='utf-8') as f:
    songs = json.load(f)

os.makedirs(OUTPUT_DIR, exist_ok=True)

# 检查已完成的歌曲
existing = set(os.listdir(OUTPUT_DIR))
pending = []
for s in songs:
    fname = f"{sanitize(s['title'])} - {sanitize(s['artist'])}.mp3"
    if fname in existing:
        print(f"[skip] 已存在: {fname}")
    else:
        pending.append(s)

print(f"\n总计: {len(songs)} 首, 已完成: {len(songs) - len(pending)}, 待下载: {len(pending)}\n")

if not pending:
    print("全部完成!")
    sys.exit(0)

# 逐个下载
failed = []
for i, s in enumerate(pending):
    fname = f"{sanitize(s['title'])} - {sanitize(s['artist'])}.mp3"
    print(f"[{i+1}/{len(pending)}] {s['title']} - {s['artist']}")
    print(f"  URL: {s['yt_url']}")
    
    # 先下载到临时目录
    import tempfile
    tmpdir = tempfile.mkdtemp(prefix="batch_dl_")
    
    try:
        result = subprocess.run(
            [PYTHON, VIDEO_AUDIO_SCRIPT, s['yt_url'], "--bitrate", "192", "--out", tmpdir],
            capture_output=True, text=True, timeout=600,
            cwd=SCRIPT_DIR
        )
        output = result.stdout + result.stderr
        print(f"  {output.strip()[-200:]}")
        
        # 找到生成的 MP3 文件
        mp3_files = [f for f in os.listdir(tmpdir) if f.endswith('.mp3')]
        if mp3_files:
            src = os.path.join(tmpdir, mp3_files[0])
            dst = os.path.join(OUTPUT_DIR, fname)
            os.rename(src, dst)
            size_mb = os.path.getsize(dst) / 1_048_576
            print(f"  [ok] => {fname} ({size_mb:.1f} MB)")
        else:
            print(f"  [error] 未找到生成的 MP3 文件!")
            failed.append(s)
            
            # 列出 tmpdir 内容
            print(f"  tmpdir 内容: {os.listdir(tmpdir)}")
            
    except subprocess.TimeoutExpired:
        print(f"  [error] 超时 (10分钟)")
        failed.append(s)
    except Exception as e:
        print(f"  [error] {e}")
        failed.append(s)
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
    
    # 间歇冷却，避免被限流
    if i < len(pending) - 1:
        time.sleep(3)
    print()

# 汇总
print("=" * 60)
print(f"完成: {len(songs) - len(failed)}/{len(songs)}")
if failed:
    print("失败列表:")
    for s in failed:
        print(f"  {s['num']}. {s['title']} - {s['artist']} => {s['yt_url']}")
