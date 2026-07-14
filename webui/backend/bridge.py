"""Bridge —— pywebview 的 js_api，前后端唯一通信入口。

职责：
- 组装统一数据契约 state = {track, theme, config}。
- 提供 get_state / update_config / set_window_bounds 等给前端 JS 调用。
- 后台线程按 auto_update.interval 轮询 SMTC 数据；数据变化时缓存，
  前端通过 get_state 拉取（也可由后端 evaluate_js 主动推送）。
- 数据源层 get_music_powershell.py 原样调用，不改其逻辑。
"""

from __future__ import annotations

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
