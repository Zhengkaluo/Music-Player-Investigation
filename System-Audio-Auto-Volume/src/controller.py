"""Pure state machine for monitor, shadow, and simulated volume control modes."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
import math


SETTINGS_SCHEMA = "system-audio.settings/v1"
STATE_SCHEMA = "system-audio.state/v1"
ACTION_SCHEMA = "system-audio.action/v1"
CONTROLLER_VERSION = "controller-m8a/v1"
MODES = {"monitor", "shadow", "lower-only", "automatic"}
CAPTURE_RESPONSES = {"unknown", "pre-volume", "post-volume", "unreliable"}


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
        "lowerGain": 0.7,
        "maxLowerDbPerSecond": 2.0,
        "minLowerStepDb": 0.25,
        "recoveryStepPercent": 1.0,
        "lowerSustainSeconds": 3.0,
        "sustainRatio": 0.8,
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


def classify_capture_response(before_lufs, after_lufs, applied_delta_db,
                              tolerance_lu=1.0):
    """Classify whether a capture follows a known endpoint attenuation change."""
    before = _number(before_lufs, "beforeLufs", -120, 20)
    after = _number(after_lufs, "afterLufs", -120, 20)
    delta = _number(applied_delta_db, "appliedDeltaDb", -60, 0)
    tolerance = _number(tolerance_lu, "toleranceLu", 0.1, 6)
    if delta > -1:
        raise ValueError("校准衰减至少需要 1 dB")
    observed = after - before
    if abs(observed - delta) <= tolerance:
        kind = "post-volume"
    elif abs(observed) <= tolerance:
        kind = "pre-volume"
    else:
        kind = "unreliable"
    return {"captureResponse": kind, "observedDeltaLu": round(observed, 3),
            "appliedDeltaDb": delta}


def effective_output_lufs(measured_lufs, capture_response,
                          output_attenuation_db=None):
    """Return device-path loudness only when the capture response is known."""
    if measured_lufs is None:
        return None
    measured = _number(measured_lufs, "measuredLufs", -120, 20)
    if capture_response == "post-volume":
        return measured
    if capture_response == "pre-volume" and output_attenuation_db is not None:
        attenuation = _number(output_attenuation_db, "outputAttenuationDb", -200, 20)
        return max(-120.0, min(20.0, measured + attenuation))
    return None


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
        ("lowerGain", 0.1, 1),
        ("maxLowerDbPerSecond", 0.1, 12),
        ("minLowerStepDb", 0.1, 3),
        ("recoveryStepPercent", 0.1, 10),
        ("lowerSustainSeconds", 0.25, 60),
        ("sustainRatio", 0.5, 1),
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
    result.setdefault("captureResponse", "unknown")
    result.setdefault("systemVolumeDb", None)
    result.setdefault("volumeDbMin", None)
    result.setdefault("volumeDbMax", None)
    result.setdefault("volumeDbStep", None)
    result.setdefault("outputAttenuationDb", None)
    result.setdefault("volumeDbSource", None)
    result.setdefault("volumeDbMappingReliable", False)
    result["timestampMs"] = _number(result["timestampMs"], "timestampMs", 0, 10**16)
    if result["systemVolume"] is not None:
        result["systemVolume"] = _number(result["systemVolume"], "systemVolume", 0, 100)
    if not isinstance(result["deviceId"], str) or not result["deviceId"]:
        raise ValueError("deviceId 必须是非空字符串")
    for key in ("shortTermLufs", "momentaryLufs", "rmsDbfs", "peakDbfs"):
        if result[key] is not None:
            result[key] = _number(result[key], key, -120, 20)
    for key in ("systemVolumeDb", "volumeDbMin", "volumeDbMax",
                "outputAttenuationDb"):
        if result[key] is not None:
            result[key] = _number(result[key], key, -200, 20)
    if result["volumeDbStep"] is not None:
        result["volumeDbStep"] = _number(result["volumeDbStep"], "volumeDbStep", 0, 100)
    if (result["volumeDbMin"] is not None and result["volumeDbMax"] is not None
            and result["volumeDbMin"] >= result["volumeDbMax"]):
        raise ValueError("volumeDbMin 必须小于 volumeDbMax")
    if result["volumeDbSource"] is not None and (
            not isinstance(result["volumeDbSource"], str)
            or not result["volumeDbSource"].strip()):
        raise ValueError("volumeDbSource 必须是非空字符串或 null")
    if not isinstance(result["volumeDbMappingReliable"], bool):
        raise ValueError("volumeDbMappingReliable 必须是 boolean")
    if result["volumeDbMappingReliable"]:
        required_db = ("systemVolumeDb", "volumeDbMin", "volumeDbMax",
                       "outputAttenuationDb", "volumeDbSource")
        if any(result[key] is None for key in required_db):
            raise ValueError("可靠 dB 映射缺少范围、衰减或来源")
        expected = result["systemVolumeDb"] - result["volumeDbMax"]
        if abs(result["outputAttenuationDb"] - expected) > 0.1:
            raise ValueError("outputAttenuationDb 与设备 dB 范围不一致")
    if result["captureResponse"] not in CAPTURE_RESPONSES:
        raise ValueError("captureResponse 不受支持")
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
        self.over_window = deque()
        self.lowering_active = False
        self.below_since_ms = None
        self.manual_until_ms = 0.0
        self.state = "MONITORING"
        self.last_timestamp_ms = None

    def update_settings(self, partial):
        merged = dict(partial)
        merged["updatedAt"] = iso_now()
        self.settings = validate_settings(merged, self.settings)
        self._reset_levels()
        return deepcopy(self.settings)

    def _action(self, observation, kind="none", reason="", recommended=None,
                execute=False, sustained=0.0, recommended_db=None,
                attenuation_db=None):
        return {
            "schemaVersion": ACTION_SCHEMA,
            "timestampMs": observation["timestampMs"],
            "state": self.state,
            "kind": kind,
            "reason": reason,
            "evidence": {
                "deviceId": observation["deviceId"],
                "shortTermLufs": observation["shortTermLufs"],
                "momentaryLufs": observation["momentaryLufs"],
                "rmsDbfs": observation["rmsDbfs"],
                "peakDbfs": observation["peakDbfs"],
                "captureResponse": observation["captureResponse"],
                "systemVolumeDb": observation["systemVolumeDb"],
                "outputAttenuationDb": observation["outputAttenuationDb"],
                "volumeDbMappingReliable": observation["volumeDbMappingReliable"],
                "effectiveLufs": effective_output_lufs(
                    observation["shortTermLufs"], observation["captureResponse"],
                    observation["outputAttenuationDb"]),
                "sustainedForSeconds": round(sustained, 3),
                "windowRatio": None,
                "windowSamples": 0,
            },
            "beforeVolume": observation["systemVolume"],
            "recommendedVolume": recommended,
            "beforeVolumeDb": observation["systemVolumeDb"],
            "recommendedVolumeDb": recommended_db,
            "recommendedAttenuationDb": attenuation_db,
            "appliedVolume": None,
            "appliedVolumeDb": None,
            "execute": bool(execute),
            "mode": self.settings["mode"],
            "controllerVersion": CONTROLLER_VERSION,
            "settingsUpdatedAt": self.settings["updatedAt"],
        }

    def _reset_levels(self):
        self.over_window.clear()
        self.lowering_active = False
        self.below_since_ms = None

    def _high_window(self, now, level, threshold):
        window_ms = self.settings["lowerSustainSeconds"] * 1000
        self.over_window.append((now, level > threshold))
        cutoff = now - window_ms
        while self.over_window and self.over_window[0][0] < cutoff:
            self.over_window.popleft()
        covered = ((now - self.over_window[0][0]) / 1000
                   if self.over_window else 0.0)
        ratio = (sum(over for _timestamp, over in self.over_window) / len(self.over_window)
                 if self.over_window else 0.0)
        return covered, ratio

    def step(self, raw_observation):
        observation = validate_observation(raw_observation)
        now = observation["timestampMs"]
        step_seconds = (0.25 if self.last_timestamp_ms is None else
                        max(0.05, min(1.0, (now - self.last_timestamp_ms) / 1000)))
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

        measured_level = observation["shortTermLufs"]
        if observation["isSilent"]:
            self._reset_levels()
            self.state = "AUTO_HOLDING" if mode != "shadow" else "SHADOW"
            return self._action(observation, "blocked", "系统静音或播放暂停，禁止调整")
        if measured_level is None:
            self._reset_levels()
            self.state = "SHADOW" if mode == "shadow" else "AUTO_HOLDING"
            return self._action(observation, "blocked", "Short-term 尚未预热或测量暂时缺失")
        level = effective_output_lufs(
            measured_level, observation["captureResponse"],
            observation["outputAttenuationDb"])
        if level is None:
            self._reset_levels()
            self.state = "SHADOW" if mode == "shadow" else "UNSUPPORTED"
            return self._action(observation, "blocked", "输出侧响度映射尚未校准，仅记录源响度")
        if observation["rmsDbfs"] is None:
            self._reset_levels()
            self.state = "AUTO_HOLDING" if mode != "shadow" else "SHADOW"
            return self._action(observation, "blocked", "RMS 测量暂时缺失，禁止调整")
        if observation["rmsDbfs"] <= self.settings["silenceGateDbfs"]:
            self._reset_levels()
            self.state = "AUTO_HOLDING" if mode != "shadow" else "SHADOW"
            return self._action(
                observation, "blocked",
                "当前 RMS %.1f dBFS 低于静音门 %.1f dBFS，禁止调整" % (
                    observation["rmsDbfs"], self.settings["silenceGateDbfs"]))

        target_high = self.settings["targetLufs"]["high"]
        if self.lowering_active and level <= target_high:
            self.over_window.clear()
            self.lowering_active = False

        threshold = target_high if self.lowering_active else self.settings["triggerLufs"]
        if self.lowering_active or level > threshold or self.over_window:
            self.below_since_ms = None
            sustained, ratio = self._high_window(now, level, threshold)
            has_high_sample = any(over for _timestamp, over in self.over_window)
            if not has_high_sample:
                self.over_window.clear()
            elif (sustained < self.settings["lowerSustainSeconds"]
                  or ratio < self.settings["sustainRatio"]):
                self.state = "OBSERVING_HIGH"
                action = self._action(
                    observation, reason="等待偏响证据窗口", sustained=sustained)
                action["evidence"].update(windowRatio=round(ratio, 3),
                                          windowSamples=len(self.over_window))
                return action
            else:
                sample_count = len(self.over_window)
                self.over_window.clear()
                self.lowering_active = True
                if (not observation["volumeDbMappingReliable"]
                        or observation["systemVolumeDb"] is None
                        or observation["volumeDbMin"] is None):
                    self.state = "SHADOW" if mode == "shadow" else "UNSUPPORTED"
                    return self._action(
                        observation, "blocked", "设备 dB 映射不可靠，拒绝生成音量目标",
                        sustained=sustained)
                error_db = max(0.0, level - target_high)
                desired_db = error_db * self.settings["lowerGain"]
                rate_cap = self.settings["maxLowerDbPerSecond"] * step_seconds
                step_db = min(desired_db, rate_cap)
                if desired_db >= self.settings["minLowerStepDb"]:
                    step_db = min(max(step_db, self.settings["minLowerStepDb"]), rate_cap)
                target_db = max(observation["volumeDbMin"],
                                observation["systemVolumeDb"] - step_db)
                actual_step_db = target_db - observation["systemVolumeDb"]
                if actual_step_db >= -0.01:
                    self.state = "AUTO_HOLDING"
                    return self._action(
                        observation, "blocked", "已经达到设备最低 dB", sustained=sustained)
                execute = mode in {"lower-only", "automatic"}
                self.state = "LOWERING" if execute else "SHADOW"
                action = self._action(
                    observation, "lower" if execute else "would-lower",
                    "持续偏响，建议按 dB 分步压低系统音量",
                    None, execute, sustained, round(target_db, 3),
                    round(actual_step_db, 3))
                action["evidence"].update(windowRatio=round(ratio, 3),
                                          windowSamples=sample_count,
                                          errorDb=round(error_db, 3),
                                          rateLimitDb=round(rate_cap, 3))
                return action

        target_low = self.settings["targetLufs"]["low"]
        if mode in {"shadow", "lower-only"} and level < target_low:
            self.below_since_ms = None
            self.state = "SHADOW" if mode == "shadow" else "AUTO_HOLDING"
            return self._action(
                observation, reason="输出估算低于目标区间；当前模式不生成升高建议")

        if mode == "automatic" and level < target_low:
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

        if not self.lowering_active and level > target_high:
            self.below_since_ms = None
            self.state = "SHADOW" if mode == "shadow" else "AUTO_HOLDING"
            return self._action(
                observation, reason="输出估算高于目标上沿，但尚未达到降低触发线")

        self.below_since_ms = None
        self.state = "SHADOW" if mode == "shadow" else "AUTO_HOLDING"
        return self._action(observation, reason="输出估算位于目标或回差区间")
