"""ColorExtractor —— 用 Pillow 从封面提取主题色。

输入：封面图的 base64 字符串（来自 SMTC 的 thumbnail_base64）。
输出：theme dict —— primary/accent/bg/fg/muted/palette/is_dark，
供前端注入 CSS 变量，实现"封面取色自适应"。

算法：缩略图 + 量化取主色调色板，选覆盖占比最高的若干色；
按亮度决定 is_dark 与前景文字色，保证对比度可读。
"""

from __future__ import annotations

import base64
import io
from typing import Any, Dict, List, Tuple

from PIL import Image


# 无封面 / 提色失败时的兜底主题（深色沉浸基调）
FALLBACK_THEME: Dict[str, Any] = {
    "primary": "#6d5ec9",
    "accent": "#8f7fe0",
    "bg": "#1f1b2e",
    "fg": "#ffffff",
    "muted": "#c9c4ec",
    "palette": ["#6d5ec9", "#4a3f9e", "#2a2440"],
    "is_dark": True,
}


def _decode_image(cover_base64: str) -> Image.Image:
    raw = base64.b64decode(cover_base64)
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    return img


def _relative_luminance(rgb: Tuple[int, int, int]) -> float:
    """感知亮度 (0~255 空间的加权)，用于判断明暗与选前景色。"""
    r, g, b = rgb
    return 0.299 * r + 0.587 * g + 0.114 * b


def _hex(rgb: Tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(c))) for c in rgb))


def _clamp(v: float) -> int:
    return max(0, min(255, int(round(v))))


def _scale(rgb: Tuple[int, int, int], factor: float) -> Tuple[int, int, int]:
    """按比例调整明度：factor<1 变暗，>1 变亮。"""
    return tuple(_clamp(c * factor) for c in rgb)


def _mix(rgb: Tuple[int, int, int], target: Tuple[int, int, int], t: float) -> Tuple[int, int, int]:
    return tuple(_clamp(c * (1 - t) + tc * t) for c, tc in zip(rgb, target))


def _dominant_colors(img: Image.Image, count: int = 5) -> List[Tuple[int, int, int]]:
    """缩略后量化，返回按占比降序的主色列表。"""
    small = img.copy()
    small.thumbnail((96, 96))
    # 量化到有限调色板，统计每个簇的像素数。
    quant = small.quantize(colors=max(count * 3, 8), method=Image.Quantize.FASTOCTREE)
    palette = quant.getpalette()  # [r,g,b, r,g,b, ...]
    color_counts = quant.getcolors()  # [(count, palette_index), ...]
    if not color_counts or not palette:
        return []
    color_counts.sort(reverse=True)  # 占比高的在前
    result: List[Tuple[int, int, int]] = []
    for _cnt, idx in color_counts:
        base = idx * 3
        rgb = (palette[base], palette[base + 1], palette[base + 2])
        result.append(rgb)
        if len(result) >= count:
            break
    return result


def extract_theme(cover_base64: str | None) -> Dict[str, Any]:
    """从封面 base64 计算主题色；任何失败都回退到 FALLBACK_THEME。"""
    if not cover_base64:
        return dict(FALLBACK_THEME)
    try:
        img = _decode_image(cover_base64)
        colors = _dominant_colors(img, count=5)
        if not colors:
            return dict(FALLBACK_THEME)

        primary = colors[0]
        # accent：优先选与主色亮度差异较大的次色，否则由主色提亮。
        accent = None
        for c in colors[1:]:
            if abs(_relative_luminance(c) - _relative_luminance(primary)) > 40:
                accent = c
                break
        if accent is None:
            accent = _scale(primary, 1.35)

        lum = _relative_luminance(primary)
        is_dark = lum < 130

        if is_dark:
            bg = _scale(primary, 0.45)          # 更深的背景
            fg = (255, 255, 255)
            muted = _mix(primary, (255, 255, 255), 0.6)
        else:
            bg = _mix(primary, (255, 255, 255), 0.55)  # 更浅的背景
            fg = (26, 24, 32)
            muted = _mix(primary, (0, 0, 0), 0.45)

        return {
            "primary": _hex(primary),
            "accent": _hex(accent),
            "bg": _hex(bg),
            "fg": _hex(fg),
            "muted": _hex(muted),
            "palette": [_hex(c) for c in colors],
            "is_dark": is_dark,
        }
    except Exception:
        return dict(FALLBACK_THEME)
