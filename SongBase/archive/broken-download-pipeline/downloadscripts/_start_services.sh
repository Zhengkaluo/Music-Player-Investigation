#!/bin/bash
# 常驻服务启动脚本 — 由 launchd 管理
cd /Users/kaluozheng/Music-Player-Investigation/SongResources

PY_BIN=/Users/kaluozheng/.workbuddy/binaries/python/versions/3.13.12/bin/python3
PY_ENV=/Users/kaluozheng/.workbuddy/binaries/python/envs/default/bin/python3

# 清理旧进程
pkill -f "http.server 8766" 2>/dev/null
pkill -f "_monitor_server.py" 2>/dev/null
pkill -f "_pl_monitor.py" 2>/dev/null

sleep 1

# 启动 HTTP
$PY_BIN -m http.server 8766 &
HTTP_PID=$!

# 启动监控
$PY_ENV _monitor_server.py &
MON_PID=$!
$PY_ENV _pl_monitor.py &
PL_PID=$!

echo "Services started: HTTP:$HTTP_PID MON:$MON_PID PL:$PL_PID"

# 等待并保活
wait
