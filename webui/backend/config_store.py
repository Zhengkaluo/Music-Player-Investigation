"""ConfigStore —— 配置读写，向后兼容旧的 music_display_config.json。

设计原则：
- 沿用现有 music_display_config.json 的字段语义（window/style/thumbnail/
  auto_update/manual_data/alignment）。
- 只新增字段（theme_id、custom_content），不破坏旧字段语义。
- 旧配置文件加载后自动补齐缺省值（迁移），并把旧的顶层 alignment
  收纳进 style.alignment，同时保留读取兼容。
- 深拷贝合并，避免默认值被引用污染。
"""

from __future__ import annotations

import copy
import json
import os
from typing import Any, Dict


DEFAULT_CONFIG: Dict[str, Any] = {
    "theme_id": "immersive",
    "window": {
        "width": 480,
        "height": 320,
        "x": None,
        "y": None,
        "alpha": 0.95,
        "topmost": True,
    },
    "style": {
        "font_family": "Microsoft YaHei UI",
        "title_size": 25,
        "artist_size": 19,
        "album_size": 14,
        "bg_color": "#1f1b2e",
        "text_color": "#ffffff",
        "accent_color": "#8f7fe0",
        "alignment": {
            "title": "left",
            "artist": "left",
            "album": "left",
            "status": "left",
        },
    },
    "thumbnail": {
        "show": True,
        "size": 400,
    },
    "auto_update": {
        "enabled": True,
        "interval": 5,
    },
    "manual_data": {
        "title": "Theme No. 1",
        "artist": "Balmorhea",
        "album": "Rivers Arms",
        "status": "正在播放",
    },
    "custom_content": {
        "enabled": False,
        "type": "text",          # "video" | "image" | "text"
        "source": "",            # 本地路径 / URL / 文本内容
        "follow_theme": True,    # 配色是否跟随封面主题色
        "fit": "cover",          # cover | contain | fill
        "position": "right",     # 预留：区域位置
        "size": {"w": 0, "h": 0},
    },
    # A+3 面板化布局
    "layout": {
        "mode": "grid",          # "grid"(自由面板) | "responsive"(三档自动重排)
        "grid": {"cols": 12, "rows": 8},
        "edit": False,           # 是否处于编辑态
        "snap": True,            # 自动吸附对齐
        "overlap": False,        # 禁止重叠
    },
    "panels": [
        {
            "id": "nowplaying", "type": "nowplaying", "visible": True,
            "grid": {"col": 0, "row": 0, "w": 7, "h": 4}, "locked": False,
        },
        {
            "id": "custom-1", "type": "custom", "visible": True,
            "grid": {"col": 7, "row": 0, "w": 5, "h": 4}, "locked": False,
            "content": {
                "kind": "text",     # "video" | "image" | "text"
                "source": "",
                "follow_theme": True,
                "fit": "cover",
            },
        },
    ],
}


def _find_panel(panels: list, panel_type: str) -> Dict[str, Any] | None:
    for p in panels:
        if p.get("type") == panel_type:
            return p
    return None


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """把 override 合并进 base 的深拷贝；仅对 dict 递归，其余直接覆盖。"""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class ConfigStore:
    """负责配置文件的加载、迁移、合并默认值与落盘。"""

    def __init__(self, path: str):
        self.path = path
        self._config: Dict[str, Any] = copy.deepcopy(DEFAULT_CONFIG)

    def load(self) -> Dict[str, Any]:
        """读取磁盘配置，做旧格式迁移后与默认值合并。文件不存在则用默认值。"""
        raw: Dict[str, Any] = {}
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    raw = json.load(f) or {}
            except (json.JSONDecodeError, OSError):
                raw = {}

        raw = self._migrate(raw)
        self._config = _deep_merge(DEFAULT_CONFIG, raw)
        self._sync_custom_content()
        return self._config

    def _migrate(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """把旧结构迁移到新结构（不改变语义，只搬位置/补键）。"""
        if not raw:
            return raw
        migrated = copy.deepcopy(raw)

        # 旧版把 alignment 放在顶层；新版收纳进 style.alignment。
        if "alignment" in migrated:
            style = migrated.setdefault("style", {})
            if "alignment" not in style or not isinstance(style.get("alignment"), dict):
                style["alignment"] = migrated["alignment"]
            migrated.pop("alignment", None)

        return migrated

    def _sync_custom_content(self) -> None:
        """保持旧字段 custom_content 与 panels 中 type:custom 板块同步（向后兼容）。

        规则：以 panels 里第一个 custom 板块为准渲染；custom_content 作为
        旧版单区镜像。若旧配置只有 custom_content 而 panels 缺 custom 板块，
        则把 custom_content 的 source/type/fit/follow_theme 灌进默认 custom 板块。
        """
        cfg = self._config
        panels = cfg.setdefault("panels", [])
        custom_panel = _find_panel(panels, "custom")
        cc = cfg.get("custom_content", {})

        if custom_panel is None:
            return

        content = custom_panel.setdefault("content", {})
        # 若板块 content 为空但旧 custom_content 有内容，则从旧字段回填一次。
        if not content.get("source") and cc.get("source"):
            content["kind"] = cc.get("type", content.get("kind", "text"))
            content["source"] = cc.get("source", "")
            content["follow_theme"] = cc.get("follow_theme", True)
            content["fit"] = cc.get("fit", "cover")
            custom_panel["visible"] = bool(cc.get("enabled", custom_panel.get("visible", True)))

        # 反向镜像回 custom_content，保证读取旧字段的代码仍拿到一致值。
        cfg["custom_content"] = {
            **cc,
            "enabled": bool(custom_panel.get("visible", False)),
            "type": content.get("kind", "text"),
            "source": content.get("source", ""),
            "follow_theme": content.get("follow_theme", True),
            "fit": content.get("fit", "cover"),
        }

    @property
    def config(self) -> Dict[str, Any]:
        return self._config

    def update(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        """用 patch 深合并到当前配置并立即落盘，返回最新配置。

        注意：panels 是数组，_deep_merge 对数组是整体替换（非逐元素合并），
        因此前端更新 panels 时应传完整数组。
        """
        self._config = _deep_merge(self._config, patch or {})
        self._sync_custom_content()
        self.save()
        return self._config

    def save(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._config, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)
