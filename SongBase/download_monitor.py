"""
下载进度监控面板。启动后在浏览器打开 http://localhost:8766
读取 SongResources 的 MP3 数量和下载日志，每 5 秒自动刷新。
"""
import json
import re
import time
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

BASE = Path(__file__).resolve().parent
SONG_DIR = BASE / "SongResources"
LOG_PATH = SONG_DIR / "_download_log.txt"
PENDING_PATH = BASE / "_pending_downloads.txt"

HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="5">
<title>下载进度监控</title>
<style>
:root{--bg:#0d1117;--panel:#161b22;--line:#30363d;--text:#c9d1d9;--muted:#8b949e;--green:#3fb950;--red:#f85149;--amber:#d29922;--accent:#58a6ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 ui-sans-serif,sans-serif;padding:24px}
h1{font-size:20px;margin:0 0 4px;display:flex;align-items:center;gap:8px}
h1 .dot{width:10px;height:10px;border-radius:50%;background:var(--green);animation:pulse 1.5s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.sub{color:var(--muted);font-size:12px;margin:0 0 20px}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:20px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.kpi .v{font-size:26px;font-weight:700}.kpi .l{color:var(--muted);font-size:12px}
.bar-wrap{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:16px}
.bar-outer{height:12px;background:var(--bg);border-radius:6px;overflow:hidden}
.bar-inner{height:100%;border-radius:6px;transition:width .5s;background:linear-gradient(90deg,var(--accent),var(--green))}
.bar-stats{display:flex;justify-content:space-between;margin-top:8px;font-size:12px;color:var(--muted)}
.logs{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px;max-height:500px;overflow:auto}
.logs pre{font:12px/1.6 ui-monospace,monospace;margin:0;white-space:pre-wrap;word-break:break-all}
.logs h3{margin:0 0 10px;font-size:14px;color:var(--muted)}
.ok{color:var(--green)}.err{color:var(--red)}.skip{color:var(--amber)}
</style></head><body>
<h1><span class="dot"></span>MP3 下载进度</h1>
<p class="sub">自动每 5 秒刷新 · 读取 SongResources/_download_log.txt</p>
<div class="kpis" id="kpis">__KPIS__</div>
<div class="bar-wrap">
  <div class="bar-outer"><div class="bar-inner" id="bar" style="width:0%"></div></div>
  <div class="bar-stats"><span id="barText"></span><span id="rate"></span></div>
</div>
<div class="logs"><h3>最近日志</h3><pre id="log">__LOGS__</pre></div>
<script>
fetch('/data').then(r=>r.json()).then(d=>{
  var pct=d.pending?Math.round(d.done/(d.done+d.pending)*100):0;
  document.getElementById('kpis').innerHTML=[
    ['已下载',d.done,'个 MP3'],
    ['待下载',d.pending,'首 · _pending_downloads.txt'],
    ['失败/跳过',d.skipped||0,'首']
  ].map(function(x){return '<div class="kpi"><div class="v">'+x[1]+'</div><div class="l">'+x[0]+'<br>'+x[2]+'</div></div>'}).join('');
  document.getElementById('bar').style.width=pct+'%';
  document.getElementById('barText').textContent=d.done+' / '+(d.done+d.pending);
  document.getElementById('rate').textContent=pct+'%';
  document.getElementById('log').innerHTML=d.logs;
});
</script></body></html>"""

def build_data():
    # MP3 数量
    mp3_count = len(list(SONG_DIR.glob("*.mp3"))) if SONG_DIR.exists() else 0

    # pending 数量
    pending = 0
    if PENDING_PATH.exists():
        pending = len([l for l in PENDING_PATH.read_text().splitlines() if l.strip()])

    # 日志最后 40 行
    logs = ""
    if LOG_PATH.exists():
        lines = LOG_PATH.read_text().splitlines()[-40:]
        for l in lines:
            l2 = l.strip()
            if "✅" in l2: logs += f'<span class="ok">{l2}</span>\n'
            elif "❌" in l2 or "⏱" in l2: logs += f'<span class="err">{l2}</span>\n'
            elif "⏭" in l2: logs += f'<span class="skip">{l2}</span>\n'
            else: logs += l2 + "\n"

    return {"done": mp3_count, "pending": pending, "skipped": 0, "logs": logs or "暂无日志"}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/data":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(build_data(), ensure_ascii=False).encode())
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            d = build_data()
            pct = d["pending"] and round(d["done"] / (d["done"] + d["pending"]) * 100) or 0
            kpis = f'<div class="kpi"><div class="v">{d["done"]}</div><div class="l">已下载<br>MP3</div></div><div class="kpi"><div class="v">{d["pending"]}</div><div class="l">待下载<br>_pending_downloads.txt</div></div><div class="kpi"><div class="v">{pct}%</div><div class="l">完成度</div></div>'
            h = HTML.replace("__KPIS__", kpis).replace("__LOGS__", d["logs"])
            self.wfile.write(h.encode())

    def log_message(self, *a): pass

def main():
    port = 8766
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"📊 下载监控: http://localhost:{port}")
    print(f"   Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋")

if __name__ == "__main__":
    main()
