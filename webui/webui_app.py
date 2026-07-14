"""Web 套壳入口 —— 启动 pywebview 窗口，装载前端并注入 Bridge。

运行：
    python webui/webui_app.py

Windows 上会通过 SMTC 取真实播放数据；其他平台无数据源时
自动用 config.manual_data 预览界面。
"""

from __future__ import annotations

import os
import sys

import webview

# 允许以脚本方式直接运行（把项目根加入 sys.path 以便 import webui.backend）
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_THIS_DIR)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from webui.backend.bridge import Bridge

CONFIG_PATH = os.path.join(_ROOT, "music_display_config.json")
FRONTEND_INDEX = os.path.join(_THIS_DIR, "frontend", "index.html")


def main() -> None:
    bridge = Bridge(CONFIG_PATH)
    win_cfg = bridge.store.config.get("window", {})

    window = webview.create_window(
        title="正在播放",
        url=FRONTEND_INDEX,
        js_api=bridge,
        width=int(win_cfg.get("width", 480) or 480),
        height=int(win_cfg.get("height", 320) or 320),
        x=win_cfg.get("x"),
        y=win_cfg.get("y"),
        frameless=True,
        easy_drag=True,
        on_top=bool(win_cfg.get("topmost", True)),
        transparent=False,
        min_size=(240, 120),
    )

    bridge.attach_window(window)

    def _on_start():
        bridge.start_polling()

    def _on_closing():
        bridge.stop_polling()
        # 关闭前持久化最终窗口尺寸/位置
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

    webview.start(debug=False)


if __name__ == "__main__":
    main()
