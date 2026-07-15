"""Bridge —— pywebview 的 js_api，前后端唯一通信入口。

职责：
- 组装统一数据契约 state = {track, theme, config}。
- 提供 get_state / update_config / set_window_bounds 等给前端 JS 调用。
- 后台线程按 auto_update.interval 轮询 SMTC 数据；数据变化时缓存，
  前端通过 get_state 拉取（也可由后端 evaluate_js 主动推送）。
- 数据源层 get_music_powershell.py 原样调用，不改其逻辑。
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any, Dict, Optional

from .config_store import ConfigStore
from . import color_extractor


def _import_data_source():
    """导入冻结的数据源层。允许在非 Windows 环境缺失（用 manual_data 预览）。"""
    try:
        import os
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if root not in sys.path:
            sys.path.insert(0, root)
        from get_music_powershell import get_playing_music_with_thumbnail
        return get_playing_music_with_thumbnail
    except Exception:
        return None


class Bridge:
    """暴露给前端 JS 的 API 对象。方法名即前端 pywebview.api.<name>()。"""

    def __init__(self, config_path: str):
        self.store = ConfigStore(config_path)
        self.store.load()
        self._data_source = _import_data_source()
        self._lock = threading.Lock()
        self._cached_track: Dict[str, Any] = self._empty_track()
        self._cached_theme: Dict[str, Any] = dict(color_extractor.FALLBACK_THEME)
        self._last_cover_sig: Optional[str] = None
        self._window = None            # pywebview window，稍后注入
        self._poll_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # ---- 生命周期 ----
    def attach_window(self, window) -> None:
        self._window = window

    def start_polling(self) -> None:
        if self._poll_thread and self._poll_thread.is_alive():
            return
        self._stop.clear()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def stop_polling(self) -> None:
        self._stop.set()

    # ---- 前端可调用的 API ----
    def get_state(self) -> Dict[str, Any]:
        """返回完整数据契约 state。前端首帧与每次轮询都调它。"""
        with self._lock:
            return {
                "track": dict(self._cached_track),
                "theme": dict(self._cached_theme),
                "config": self.store.config,
            }

    def update_config(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        """前端改设置（切主题/自定义内容/样式微调）时调用，落盘并回传最新 config。"""
        cfg = self.store.update(patch or {})
        return cfg

    def set_window_bounds(self, bounds: Dict[str, Any]) -> Dict[str, Any]:
        """A+1：窗口尺寸/位置变化时持久化到 config.window。"""
        window_patch = {}
        for key in ("width", "height", "x", "y"):
            if key in bounds and bounds[key] is not None:
                window_patch[key] = int(bounds[key])
        if window_patch:
            self.store.update({"window": window_patch})
        return self.store.config.get("window", {})

    def resize_window(self, width: int, height: int) -> Dict[str, Any]:
        """由前端缩放角调用：即时调整窗口大小并持久化。"""
        try:
            width = max(320, int(width))
            height = max(200, int(height))
        except (TypeError, ValueError):
            return self.store.config.get("window", {})
        if self._window is not None:
            try:
                self._window.resize(width, height)
            except Exception:
                pass
        self.store.update({"window": {"width": width, "height": height}})
        return self.store.config.get("window", {})

    def set_window_opacity(self, alpha: float) -> Dict[str, Any]:
        """设置窗口透明度并持久化。alpha 0.2~1.0。

        注意：pywebview 的透明度在窗口创建时通过 transparent 参数决定，
        运行时逐级调整能力依平台而定；此处始终持久化，下次启动生效，
        运行时若平台支持则尝试即时应用。
        """
        try:
            alpha = max(0.2, min(1.0, float(alpha)))
        except (TypeError, ValueError):
            return self.store.config.get("window", {})
        self.store.update({"window": {"alpha": alpha}})
        return self.store.config.get("window", {})

    def set_topmost(self, on: bool) -> Dict[str, Any]:
        """设置窗口置顶并持久化。"""
        on = bool(on)
        self.store.update({"window": {"topmost": on}})
        if self._window is not None:
            try:
                self._window.on_top = on
            except Exception:
                pass
        return self.store.config.get("window", {})

    def pick_file(self, kind: str = "all") -> str:
        """打开原生文件选择框，返回所选文件路径（取消返回空串）。

        kind: "video" | "image" | "all"，用于过滤文件类型。
        供自定义内容区选择本地视频/图片。
        """
        if self._window is None:
            return ""
        try:
            import webview
            filters_map = {
                "video": ("视频文件 (*.mp4;*.webm;*.mov;*.mkv)",),
                "image": ("图片文件 (*.png;*.jpg;*.jpeg;*.gif;*.webp;*.bmp)",),
            }
            file_types = filters_map.get(kind, ("所有文件 (*.*)",))
            result = self._window.create_file_dialog(
                webview.OPEN_DIALOG, allow_multiple=False, file_types=file_types
            )
            if result:
                return result[0] if isinstance(result, (list, tuple)) else str(result)
        except Exception:
            pass
        return ""

    def resolve_media(self, source: str) -> str:
        """把本地文件路径解析为前端可加载的形式。

        WebView2 出于安全策略无法直接用 <img src="E:\\x.jpg"> 加载本地绝对路径。
        - 若 source 已是 http(s)/data/file URL，原样返回。
        - 若是本地存在的文件，读为 data URL（base64）返回，供 <img>/<video> 直接用。
        - 其余原样返回。
        图片/小视频用 data URL 足够；超大视频建议后续改用本地 http 静态服务。
        """
        if not source:
            return ""
        low = source.strip().lower()
        if low.startswith(("http://", "https://", "data:", "file://")):
            return source
        try:
            if os.path.exists(source):
                import base64 as _b64
                import mimetypes
                mime, _ = mimetypes.guess_type(source)
                mime = mime or "application/octet-stream"
                with open(source, "rb") as f:
                    data = f.read()
                b64 = _b64.b64encode(data).decode("ascii")
                return "data:%s;base64,%s" % (mime, b64)
        except Exception:
            pass
        return source

    def refresh_now(self) -> Dict[str, Any]:
        """前端手动请求立即刷新一次。"""
        self._refresh_once()
        return self.get_state()

    # ---- 内部 ----
    @staticmethod
    def _empty_track() -> Dict[str, Any]:
        return {
            "title": "", "artist": "", "album": "", "status": "",
            "cover_base64": None, "position": None, "duration": None,
            "app_name": "", "is_playing": False,
        }

    def _manual_track(self) -> Dict[str, Any]:
        md = self.store.config.get("manual_data", {})
        t = self._empty_track()
        t.update({
            "title": md.get("title", ""),
            "artist": md.get("artist", ""),
            "album": md.get("album", ""),
            "status": md.get("status", ""),
            "is_playing": md.get("status", "") == "正在播放",
        })
        return t

    def _normalize(self, info: Dict[str, Any]) -> Dict[str, Any]:
        """把数据源返回的 dict 归一到 track 契约。"""
        t = self._empty_track()
        t.update({
            "title": info.get("title") or "",
            "artist": info.get("artist") or "",
            "album": info.get("album_title") or info.get("album") or "",
            "status": info.get("playback_status") or "",
            "cover_base64": info.get("thumbnail_base64"),
            "app_name": info.get("app_name") or "",
            "is_playing": info.get("playback_status_code") == 4,
        })
        return t

    def _refresh_once(self) -> None:
        auto = self.store.config.get("auto_update", {})
        info = None
        if auto.get("enabled", True) and self._data_source is not None:
            try:
                info = self._data_source()
            except Exception:
                info = None

        if info and info.get("status") == "success":
            track = self._normalize(info)
        else:
            # 无数据源 / 非 Windows / 无媒体 → 用 manual_data 预览
            track = self._manual_track()

        # 仅当封面变化时才重新提色（提色相对耗时）。
        cover = track.get("cover_base64")
        sig = (cover[:64] if cover else None)
        with self._lock:
            self._cached_track = track
            if sig != self._last_cover_sig:
                self._last_cover_sig = sig
                self._cached_theme = color_extractor.extract_theme(cover)

        self._push_to_front()

    def _push_to_front(self) -> None:
        """主动通知前端有新数据（前端定义 window.onStatePush）。"""
        if self._window is None:
            return
        try:
            self._window.evaluate_js(
                "window.onStatePush && window.onStatePush();"
            )
        except Exception:
            pass

    def _poll_loop(self) -> None:
        # 首帧立即刷新
        self._refresh_once()
        while not self._stop.is_set():
            interval = self.store.config.get("auto_update", {}).get("interval", 5)
            try:
                interval = max(1, int(interval))
            except (TypeError, ValueError):
                interval = 5
            if self._stop.wait(interval):
                break
            self._refresh_once()
