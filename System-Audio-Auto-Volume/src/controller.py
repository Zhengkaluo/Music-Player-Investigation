"""Pure state machine for monitor, shadow, and simulated volume control modes."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math


SETTINGS_SCHEMA = "system-audio.settings/v1"
STATE_SCHEMA = "system-audio.state/v1"
ACTION_SCHEMA = "system-audio.action/v1"
CONTROLLER_VERSION = "controller-m0-m2/v1"
MODES = {"monitor", "shadow", "lower-only", "automatic"}


def iso_now():
    return datetime.now(timezone.utc).isoformat()


def default_settings():
    return {
        "schemaVersion": SETTINGS_SCHEMA,
        "mode": "monitor",
        "triggerLufs": -15.0,
        "targetLufs": {"low": -21.0, "high": -17.0},
        "minSystemVolume": 20.0,
        "maxSystemVolume": 75.0,
        "lowerStepPercent": 3.0,
        "recoveryStepPercent": 1.0,
        "lowerSustainSeconds": 3.0,
        "recoverySustainSeconds": 12.0,
        "manualOverrideSeconds": 30.0,
        "silenceGateDbfs": -55.0,
        "updatedAt": iso_now(),
    }


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("%s 必须是有限数字" % name)
    value = float(value)
    if not low <= value <= high:
        raise ValueError("%s 必须在 %s..%s 之间" % (name, low, high))
    return value


def validate_settings(candidate, base=None):
    """Merge and validate a full or partial settings object."""
    if not isinstance(candidate, dict):
        raise ValueError("设置必须是 JSON object")
    result = deepcopy(base if base is not None else default_settings())
    allowed = set(result)
    unknown = set(candidate) - allowed
    if unknown:
        raise ValueError("未知设置字段：%s" % ", ".join(sorted(unknown)))
    result.update(deepcopy(candidate))
    if result.get("schemaVersion") != SETTINGS_SCHEMA:
        raise ValueError("不支持的 settings schemaVersion")
    if result.get("mode") not in MODES:
        raise ValueError("mode 必须是 monitor、shadow、lower-only 或 automatic")
    target = result.get("targetLufs")
    if not isinstance(target, dict) or set(target) != {"low", "high"}:
        raise ValueError("targetLufs 必须只包含 low 和 high")
    target["low"] = _number(target["low"], "targetLufs.low", -70, 0)
    target["high"] = _number(target["high"], "targetLufs.high", -70, 0)
    if target["low"] >= target["high"]:
        raise ValueError("targetLufs.low 必须小于 targetLufs.high")
    result["triggerLufs"] = _number(result["triggerLufs"], "triggerLufs", -70, 0)
    if result["triggerLufs"] < target["high"]:
        raise ValueError("triggerLufs 不能低于目标区间上沿")
    result["minSystemVolume"] = _number(result["minSystemVolume"], "minSystemVolume", 0, 100)
    result["maxSystemVolume"] = _number(result["maxSystemVolume"], "maxSystemVolume", 0, 100)
    if result["minSystemVolume"] >= result["maxSystemVolume"]:
        raise ValueError("minSystemVolume 必须小于 maxSystemVolume")
    for key, low, high in (
        ("lowerStepPercent", 0.1, 20),
        ("recoveryStepPercent", 0.1, 10),
        ("lowerSustainSeconds", 0.25, 60),
        ("recoverySustainSeconds", 1, 300),
        ("manualOverrideSeconds", 0, 600),
        ("silenceGateDbfs", -100, -20),
    ):
        result[key] = _number(result[key], key, low, high)
    updated = result.get("updatedAt")
    if not isinstance(updated, str) or not updated.strip():
        raise ValueError("updatedAt 必须是非空字符串")
    return result


def validate_observation(value):
    required = {
        "timestampMs", "deviceId", "systemVolume", "shortTermLufs", "momentaryLufs",
        "rmsDbfs", "peakDbfs", "isSilent", "captureAvailable", "volumeControllable",
        "manualVolumeChanged",
    }
    if not isinstance(value, dict) or not required.issubset(value):
        missing = sorted(required - set(value if isinstance(value, dict) else {}))
        raise ValueError("监测数据缺少字段：%s" % ", ".join(missing))
    result = deepcopy(value)
    result["timestampMs"] = _number(result["timestampMs"], "timestampMs", 0, 10**16)
    if result["systemVolume"] is not None:
        result["systemVolume"] = _number(result["systemVolume"], "systemVolume", 0, 100)
    if not isinstance(result["deviceId"], str) or not result["deviceId"]:
        raise ValueError("deviceId 必须是非空字符串")
    for key in ("shortTermLufs", "momentaryLufs", "rmsDbfs", "peakDbfs"):
        if result[key] is not None:
            result[key] = _number(result[key], key, -120, 20)
    for key in ("isSilent", "captureAvailable", "volumeControllable", "manualVolumeChanged"):
        if not isinstance(result[key], bool):
            raise ValueError("%s 必须是 boolean" % key)
    return result


class VolumeController:
    """Small deterministic controller. It recommends; platform adapters execute."""

    def __init__(self, settings=None):
        self.settings = validate_settings(settings or default_settings())
        self.device_id = None
        self.baseline_volume = None
        self.over_since_ms = None
        self.below_since_ms = None
        self.manual_until_ms = 0.0
        self.state = "MONITORING"
        self.last_timestamp_ms = None

    def update_settings(self, partial):
        merged = dict(partial)
        merged["updatedAt"] = iso_now()
        self.settings = validate_settings(merged, self.settings)
        return deepcopy(self.settings)

    def _action(self, observation, kind="none", reason="", recommended=None,
                execute=False, sustained=0.0):
        return {
            "schemaVersion": ACTION_SCHEMA,
            "timestampMs": observation["timestampMs"],
            "state": self.state,
            "kind": kind,
            "reason": reason,
            "evidence": {
                "shortTermLufs": observation["shortTermLufs"],
                "momentaryLufs": observation["momentaryLufs"],
                "rmsDbfs": observation["rmsDbfs"],
                "peakDbfs": observation["peakDbfs"],
                "sustainedForSeconds": round(sustained, 3),
            },
            "beforeVolume": observation["systemVolume"],
            "recommendedVolume": recommended,
            "appliedVolume": None,
            "execute": bool(execute),
            "mode": self.settings["mode"],
            "controllerVersion": CONTROLLER_VERSION,
            "settingsUpdatedAt": self.settings["updatedAt"],
        }

    def _reset_levels(self):
        self.over_since_ms = None
        self.below_since_ms = None

    def step(self, raw_observation):
        observation = validate_observation(raw_observation)
        now = observation["timestampMs"]
        if self.last_timestamp_ms is not None and now < self.last_timestamp_ms:
            raise ValueError("timestampMs 不能倒退")
        self.last_timestamp_ms = now

        if not observation["captureAvailable"]:
            self._reset_levels()
            self.state = "SUSPENDED"
            return self._action(observation, "suspended", "系统音频捕获不可用")

        if self.device_id is None:
            self.device_id = observation["deviceId"]
            self.baseline_volume = observation["systemVolume"]
        elif observation["deviceId"] != self.device_id:
            self.device_id = observation["deviceId"]
            self.baseline_volume = observation["systemVolume"]
            self.manual_until_ms = 0
            self._reset_levels()
            self.state = "RECALIBRATING"
            return self._action(observation, "device-change", "输出设备变化，等待重新校准")

        if observation["manualVolumeChanged"] and observation["systemVolume"] is not None:
            self.baseline_volume = observation["systemVolume"]
            self.manual_until_ms = now + self.settings["manualOverrideSeconds"] * 1000
            self._reset_levels()
            self.state = "USER_OVERRIDE"
            return self._action(observation, "manual-override", "检测到用户手动调整系统音量")

        mode = self.settings["mode"]
        if mode == "monitor":
            self._reset_levels()
            self.state = "MONITORING"
            return self._action(observation, reason="只监控模式，不生成音量动作")

        if now < self.manual_until_ms:
            self._reset_levels()
            self.state = "USER_OVERRIDE"
            return self._action(observation, "blocked", "用户接管期间暂停自动控制")

        if not observation["volumeControllable"]:
            self._reset_levels()
            self.state = "UNSUPPORTED"
            return self._action(observation, "blocked", "当前设备不支持可靠的系统音量控制")

        if observation["systemVolume"] is None:
            self._reset_levels()
            self.state = "UNSUPPORTED"
            return self._action(observation, "blocked", "当前设备无法读取系统音量")

        level = observation["shortTermLufs"]
        silent = (observation["isSilent"] or observation["rmsDbfs"] is None
                  or observation["rmsDbfs"] <= self.settings["silenceGateDbfs"])
        if level is None or silent:
            self._reset_levels()
            self.state = "AUTO_HOLDING" if mode != "shadow" else "SHADOW"
            return self._action(observation, "blocked", "静音、暂停或测量缺失时禁止调整")

        if level > self.settings["triggerLufs"]:
            self.below_since_ms = None
            if self.over_since_ms is None:
                self.over_since_ms = now
            sustained = max(0.0, (now - self.over_since_ms) / 1000)
            if sustained < self.settings["lowerSustainSeconds"]:
                self.state = "OBSERVING_HIGH"
                return self._action(observation, reason="等待持续偏响证据", sustained=sustained)
            self.over_since_ms = None
            recommended = max(self.settings["minSystemVolume"],
                              observation["systemVolume"] - self.settings["lowerStepPercent"])
            if recommended >= observation["systemVolume"]:
                self.state = "AUTO_HOLDING"
                return self._action(observation, "blocked", "已经达到最低系统音量", sustained=sustained)
            execute = mode in {"lower-only", "automatic"}
            self.state = "LOWERING" if execute else "SHADOW"
            return self._action(observation, "lower" if execute else "would-lower",
                                "持续偏响，建议分步压低系统音量", recommended, execute, sustained)

        self.over_since_ms = None
        if mode == "automatic" and level < self.settings["targetLufs"]["low"]:
            if self.below_since_ms is None:
                self.below_since_ms = now
            sustained = max(0.0, (now - self.below_since_ms) / 1000)
            if sustained < self.settings["recoverySustainSeconds"]:
                self.state = "OBSERVING_LOW"
                return self._action(observation, reason="等待持续偏轻证据", sustained=sustained)
            self.below_since_ms = None
            ceiling = min(self.settings["maxSystemVolume"], self.baseline_volume)
            recommended = min(ceiling, observation["systemVolume"] + self.settings["recoveryStepPercent"])
            if recommended <= observation["systemVolume"]:
                self.state = "AUTO_HOLDING"
                return self._action(observation, "blocked", "已经达到用户基准或最高音量", sustained=sustained)
            self.state = "RECOVERING"
            return self._action(observation, "recover", "持续偏轻，缓慢恢复系统音量",
                                recommended, True, sustained)

        self.below_since_ms = None
        self.state = "SHADOW" if mode == "shadow" else "AUTO_HOLDING"
        return self._action(observation, reason="当前位于保持区间")
