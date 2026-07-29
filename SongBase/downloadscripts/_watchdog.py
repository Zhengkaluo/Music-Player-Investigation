#!/usr/bin/env python3
"""下载看门狗 — 每 60 秒检查一次，卡住超 5 分钟则自动跳过+重启"""
import json, os, re, subprocess, time
from pathlib import Path
from datetime import datetime

LOG_PATH = Path("/Users/kaluozheng/Music-Player-Investigation/SongResources/_download_log.txt")
RESOURCES = Path("/Users/kaluozheng/Music-Player-Investigation/SongResources")
BATCH_SCRIPT = "/Users/kaluozheng/Music-Player-Investigation/SongBase/batch_download_youtube.py"
PYTHON = "/Users/kaluozheng/.workbuddy/binaries/python/envs/default/bin/python3"

STALL_SECONDS = 300  # 5 分钟无动静 = 卡住
WATCHDOG_LOG = RESOURCES / "_watchdog_log.txt"

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(WATCHDOG_LOG, "a") as f:
        f.write(line + "\n")

def parse_last_log_time():
    """解析日志中最后一条带时间戳的行的时间"""
    if not LOG_PATH.exists():
        return None
    lines = LOG_PATH.read_text(errors="replace").strip().split("\n")
    for line in reversed(lines):
        m = re.match(r'^\[(\d{2}:\d{2}:\d{2})\]\s+(.*)', line)
        if m:
            ts = m.group(1)
            h, mi, s = map(int, ts.split(":"))
            now = datetime.now()
            t = now.replace(hour=h, minute=mi, second=s, microsecond=0)
            return t, m.group(2)
    return None

def count_mp3():
    return len(list(RESOURCES.glob("*.mp3")))

def parse_stuck_song(text):
    """从日志行提取卡住的歌名-歌手"""
    m = re.search(r'\[(\d+)/452\]\s+(.+?)\s+[—–-]\s+(.+)', text)
    if m:
        song_name = m.group(2).strip()
        singer = m.group(3).strip()
        return f"{song_name} - {singer}"
    return None

def kill_downloaders():
    subprocess.run(["pkill", "-9", "-f", "batch_download_youtube"], capture_output=True)
    subprocess.run(["pkill", "-9", "-f", "video_audio.py"], capture_output=True)
    subprocess.run(["pkill", "-9", "-f", "yt-dlp"], capture_output=True)
    time.sleep(2)

def restart_download():
    subprocess.Popen(
        [PYTHON, BATCH_SCRIPT],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        cwd=str(Path(BATCH_SCRIPT).parent),
    )

def check_and_fix_http():
    """检查 HTTP 8766 是否响应，挂了则重启"""
    import urllib.request
    try:
        urllib.request.urlopen("http://localhost:8766/monitor.html", timeout=3)
        return True
    except:
        subprocess.Popen(
            [PYTHON, "-m", "http.server", "8766"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=str(RESOURCES),
        )
        log("  🌐 HTTP:8766 已重启")
        return False

def check_and_fix_monitors():
    """确保监控数据生成器在运行"""
    monitors = [
        ("_monitor_server.py", "下载监控生成器"),
        ("_pl_monitor.py", "歌单监控生成器"),
    ]
    for script, name in monitors:
        script_path = RESOURCES / script
        # 检查进程
        result = subprocess.run(["pgrep", "-f", script], capture_output=True, text=True)
        if not result.stdout.strip():
            subprocess.Popen(
                [PYTHON, str(script_path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            log(f"  📊 {name} 已重启")


log("看门狗启动，每 60 秒巡检（含 HTTP:8766 + 监控守护）")

while True:
    try:
        # 1. 检查 HTTP 和监控
        check_and_fix_http()
        check_and_fix_monitors()

        # 2. 检查下载
        result = parse_last_log_time()
        mp3_count = count_mp3()

        if result is None:
            time.sleep(60)
            continue

        last_time, last_text = result
        elapsed = (datetime.now() - last_time).total_seconds()

        if elapsed > STALL_SECONDS:
            log(f"检测到卡住（{int(elapsed)}秒无动静），自动重启...")

            kill_downloaders()

            # 跳过当前卡住的歌
            stuck = parse_stuck_song(last_text)
            if stuck:
                stuck_file = RESOURCES / f"{stuck}.mp3"
                if not stuck_file.exists():
                    stuck_file.touch()
                    log(f"  跳过: {stuck}")

            restart_download()
            log(f"  下载已重启，当前 {mp3_count}/452")
            time.sleep(120)  # 重启后等 2 分钟再检查
        else:
            log(f"正常 {mp3_count}/452 (最后活动 {int(elapsed)}秒前)")

    except Exception as e:
        log(f"错误: {e}")

    time.sleep(60)
