"""Simple-mode presets: map a few user choices onto the raw controller settings.

The numbers live in ``config/simple-presets.json`` so they can be tuned without code
changes. The file is re-read whenever it changes on disk.
"""

from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path

SCHEMA = "system-audio.simple-presets/v1"
SENSITIVITIES = ("low", "standard", "high")
SPEEDS = ("gentle", "standard", "fast")
PRESET_MODES = ("simple", "custom")
PRESET_KEYS = {"mode", "comfortLufs", "sensitivity", "speed", "maxReductionDb"}
# Raw settings owned by simple mode. Changing any of them by hand makes it "custom".
DERIVED_KEYS = {
    "triggerLufs", "targetLufs", "lowerSustainSeconds", "sustainRatio", "lowerGain",
    "maxLowerDbPerSecond", "maxAutoAttenuationDb", "minSystemVolume", "silenceGateDbfs",
    "manualOverrideSeconds", "minLowerStepDb", "recoverySustainSeconds", "recoveryPercentile",
    "recoveryHeadroomLu", "maxRaiseDbPerSecond", "recoveryCooldownSeconds", "songGapSeconds",
    "songHoldMaxSeconds", "fadeSlopeLuPerSecond",
}


def _num(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("简易换算表 %s 必须是数字" % name)
    return float(value)


def validate_table(table):
    if not isinstance(table, dict) or table.get("schemaVersion") != SCHEMA:
        raise ValueError("简易换算表 schemaVersion 必须是 %s" % SCHEMA)
    try:
        comfort = table["comfort"]
        for key in ("windowSeconds", "minSeconds", "min", "max"):
            _num(comfort[key], "comfort.%s" % key)
        if not comfort["min"] < comfort["max"]:
            raise ValueError("简易换算表 comfort.min 必须小于 comfort.max")
        low = _num(table["target"]["lowOffset"], "target.lowOffset")
        high = _num(table["target"]["highOffset"], "target.highOffset")
        if not low < high:
            raise ValueError("简易换算表 target.lowOffset 必须小于 highOffset")
        for name in SENSITIVITIES:
            item = table["sensitivity"][name]
            if _num(item["triggerOffset"], "sensitivity.%s.triggerOffset" % name) < high:
                raise ValueError("简易换算表 sensitivity.%s.triggerOffset 不能小于 target.highOffset" % name)
            _num(item["lowerSustainSeconds"], "sensitivity.%s.lowerSustainSeconds" % name)
            _num(item["sustainRatio"], "sensitivity.%s.sustainRatio" % name)
            if (_num(item["recoverySustainSeconds"], "sensitivity.%s.recoverySustainSeconds" % name)
                    < item["lowerSustainSeconds"]):
                raise ValueError("简易换算表 sensitivity.%s.recoverySustainSeconds 不能短于 lowerSustainSeconds" % name)
        for name in SPEEDS:
            item = table["speed"][name]
            _num(item["lowerGain"], "speed.%s.lowerGain" % name)
            _num(item["maxLowerDbPerSecond"], "speed.%s.maxLowerDbPerSecond" % name)
            if (_num(item["maxRaiseDbPerSecond"], "speed.%s.maxRaiseDbPerSecond" % name)
                    > item["maxLowerDbPerSecond"]):
                raise ValueError("简易换算表 speed.%s.maxRaiseDbPerSecond 不能快于 maxLowerDbPerSecond" % name)
        limits = table["maxReductionDb"]
        for key in ("min", "max", "step", "default"):
            _num(limits[key], "maxReductionDb.%s" % key)
        if not limits["min"] <= limits["default"] <= limits["max"]:
            raise ValueError("简易换算表 maxReductionDb.default 必须在 min..max 之间")
        for key in ("minSystemVolume", "silenceGateDbfs", "manualOverrideSeconds", "minLowerStepDb",
                    "recoveryCooldownSeconds", "recoveryPercentile", "recoveryHeadroomLu",
                    "songGapSeconds", "songHoldMaxSeconds", "fadeSlopeLuPerSecond"):
            _num(table["fixed"][key], "fixed.%s" % key)
    except (KeyError, TypeError) as error:
        raise ValueError("简易换算表缺少字段：%s" % error) from None
    return table


class PresetTable:
    def __init__(self, path):
        self.path = Path(path)
        self._mtime = None
        self._table = None

    def table(self):
        mtime = self.path.stat().st_mtime
        if self._table is None or mtime != self._mtime:
            with self.path.open("r", encoding="utf-8") as source:
                table = validate_table(json.load(source))
            self._table, self._mtime = table, mtime
        return self._table

    def public(self):
        """Labels and ranges for the UI (no internal comments)."""
        table = self.table()
        strip = lambda item: {k: v for k, v in item.items() if not k.startswith("_")}
        return {
            "comfort": strip(table["comfort"]),
            "target": strip(table["target"]),
            "sensitivity": {name: strip(table["sensitivity"][name]) for name in SENSITIVITIES},
            "speed": {name: strip(table["speed"][name]) for name in SPEEDS},
            "maxReductionDb": strip(table["maxReductionDb"]),
            "fixed": strip(table["fixed"]),
        }

    def validate_preset(self, preset):
        if not isinstance(preset, dict) or set(preset) != PRESET_KEYS:
            raise ValueError("preset 必须只包含 %s" % ", ".join(sorted(PRESET_KEYS)))
        if preset["mode"] not in PRESET_MODES:
            raise ValueError("preset.mode 必须是 simple 或 custom")
        if preset["sensitivity"] not in SENSITIVITIES:
            raise ValueError("灵敏度必须是 %s 之一" % "、".join(SENSITIVITIES))
        if preset["speed"] not in SPEEDS:
            raise ValueError("压低速度必须是 %s 之一" % "、".join(SPEEDS))
        table = self.table()
        comfort = _num(preset["comfortLufs"], "comfortLufs")
        if not table["comfort"]["min"] <= comfort <= table["comfort"]["max"]:
            raise ValueError("舒适音量 %.1f LUFS 超出可用范围 %s..%s" % (
                comfort, table["comfort"]["min"], table["comfort"]["max"]))
        limits = table["maxReductionDb"]
        reduction = _num(preset["maxReductionDb"], "maxReductionDb")
        if not limits["min"] <= reduction <= limits["max"]:
            raise ValueError("最多压低必须在 %s..%s dB 之间" % (limits["min"], limits["max"]))
        return preset

    def derive(self, preset):
        """Return the raw settings that simple mode implies for this preset."""
        self.validate_preset(preset)
        table = self.table()
        comfort = float(preset["comfortLufs"])
        sensitivity = table["sensitivity"][preset["sensitivity"]]
        speed = table["speed"][preset["speed"]]
        fixed = table["fixed"]
        rounded = lambda value: round(float(value), 1)
        return {
            "triggerLufs": rounded(comfort + sensitivity["triggerOffset"]),
            "targetLufs": {"low": rounded(comfort + table["target"]["lowOffset"]),
                           "high": rounded(comfort + table["target"]["highOffset"])},
            "lowerSustainSeconds": float(sensitivity["lowerSustainSeconds"]),
            "sustainRatio": float(sensitivity["sustainRatio"]),
            "lowerGain": float(speed["lowerGain"]),
            "maxLowerDbPerSecond": float(speed["maxLowerDbPerSecond"]),
            "maxAutoAttenuationDb": float(preset["maxReductionDb"]),
            "minSystemVolume": float(fixed["minSystemVolume"]),
            "silenceGateDbfs": float(fixed["silenceGateDbfs"]),
            "manualOverrideSeconds": float(fixed["manualOverrideSeconds"]),
            "minLowerStepDb": float(fixed["minLowerStepDb"]),
            "recoverySustainSeconds": float(sensitivity["recoverySustainSeconds"]),
            "maxRaiseDbPerSecond": float(speed["maxRaiseDbPerSecond"]),
            "recoveryCooldownSeconds": float(fixed["recoveryCooldownSeconds"]),
            "recoveryPercentile": float(fixed["recoveryPercentile"]),
            "recoveryHeadroomLu": float(fixed["recoveryHeadroomLu"]),
            "songGapSeconds": float(fixed["songGapSeconds"]),
            "songHoldMaxSeconds": float(fixed["songHoldMaxSeconds"]),
            "fadeSlopeLuPerSecond": float(fixed["fadeSlopeLuPerSecond"]),
        }


def legacy_preset(settings, table=None):
    """Settings saved before presets existed are treated as hand-tuned (custom)."""
    comfort = float(settings["targetLufs"]["high"]) - 1.0
    reduction = float(settings.get("maxAutoAttenuationDb", 12.0))
    if table is not None:
        comfort = min(max(comfort, table["comfort"]["min"]), table["comfort"]["max"])
        limits = table["maxReductionDb"]
        reduction = min(max(reduction, limits["min"]), limits["max"])
    return {"mode": "custom", "comfortLufs": round(comfort, 1), "sensitivity": "standard",
            "speed": "standard", "maxReductionDb": reduction}


def default_preset():
    return deepcopy({"mode": "simple", "comfortLufs": -18.0, "sensitivity": "standard",
                     "speed": "standard", "maxReductionDb": 12.0})
