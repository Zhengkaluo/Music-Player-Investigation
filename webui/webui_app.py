"""Web 套壳入口 —— 启动 pywebview 窗口，装载前端并注入 Bridge。

运行：
    py webui/webui_app.py

关键点：
- 前端通过本地 HTTP 服务(no-store 头)加载，彻底避免 WebView2 对
  file:// 资源的强缓存，保证改动即时生效。
- 窗口无边框但通过前端自绘的缩放角 + 后端 resize 实现可调大小。
"""

from __future__ import annotations

import os
import re
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import webview

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_THIS_DIR)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from webui.backend.bridge import Bridge

CONFIG_PATH = os.path.join(_ROOT, "music_display_config.json")
FRONTEND_DIR = os.path.join(_THIS_DIR, "frontend")

# 每次启动生成唯一版本号，用于给前端资源加 ?v=，彻底击穿 WebView2 缓存。
_CACHE_BUST = str(int(time.time()))


class _NoCacheHandler(SimpleHTTPRequestHandler):
    """静态文件服务：强制 no-store，且给 index.html 内的 js/css 注入 ?v= 版本号。"""

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._serve_index()
            return
        super().do_GET()

    def _serve_index(self):
        index_path = os.path.join(FRONTEND_DIR, "index.html")
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                html = f.read()
            # 给本地 css/js 资源追加 ?v=<启动时间戳>
            html = re.sub(
                r'(href|src)="((?:css|js)/[^"?]+)"',
                lambda m: '%s="%s?v=%s"' % (m.group(1), m.group(2), _CACHE_BUST),
                html,
            )
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            super().do_GET()

    def log_message(self, *args):
        pass  # 静默


def _start_http_server() -> int:
    handler = partial(_NoCacheHandler, directory=FRONTEND_DIR)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)  # 0 = 系统分配空闲端口
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return port


def main() -> None:
    bridge = Bridge(CONFIG_PATH)
    win_cfg = bridge.store.config.get("window", {})

    width = int(win_cfg.get("width", 900) or 900)
    height = int(win_cfg.get("height", 560) or 560)
    if width < 480:
        width = 900
    if height < 320:
        height = 560

    x = win_cfg.get("x")
    y = win_cfg.get("y")
    if x is None or y is None or x < -100 or y < -100 or x > 10000 or y > 10000:
        x = None
        y = None

    port = _start_http_server()
    url = "http://127.0.0.1:%d/index.html" % port

    window = webview.create_window(
        title="正在播放",
        url=url,
        js_api=bridge,
        width=width,
        height=height,
        x=x,
        y=y,
        frameless=True,
        easy_drag=True,
        on_top=bool(win_cfg.get("topmost", True)),
        transparent=False,
        resizable=True,
        min_size=(320, 200),
    )

    bridge.attach_window(window)

    def _on_start():
        bridge.start_polling()

    def _on_closing():
        bridge.stop_polling()
        try:
            bridge.set_window_bounds({
                "width": window.width,
                "height": window.height,
                "x": window.x,
                "y": window.y,
            })
        except Exception:
            pass

    window.events.shown += _on_start
    window.events.closing += _on_closing

    # 调试模式：窗口内可右键“检查”打开开发者工具查看控制台/报错。
    debug = os.environ.get("NP_DEBUG", "0") == "1"
    webview.start(debug=debug)


if __name__ == "__main__":
    main()
