"""Pure state machine for monitor, shadow, and simulated volume control modes."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
import math


SETTINGS_SCHEMA = "system-audio.settings/v1"
STATE_SCHEMA = "system-audio.state/v1"
ACTION_SCHEMA = "system-audio.action/v1"
CONTROLLER_VERSION = "controller-m9/v2"
MODES = {"monitor", "shadow", "lower-only", "automatic"}
CAPTURE_RESPONSES = {"unknown", "pre-volume", "post-volume", "unreliable"}
# post-volume capture reflects a write only after the 3 s Short-term window refills.
POST_VOLUME_SETTLE_MS = 3500.0
# Fade-out guard: slope of effective loudness over this window.
FADE_WINDOW_MS = 4000.0
FADE_MIN_SAMPLES = 8
DEPRECATED_SETTINGS = ("recoveryRatio",)


def iso_now():
    return datetime.now(timezone.utc).isoformat()


def default_settings():
    # Must equal presets.derive(default_preset()) with config/simple-presets.json;
    # a test keeps the two in sync.
    return {
        "schemaVersion": SETTINGS_SCHEMA,
        "mode": "monitor",
        "preset": {"mode": "simple", "comfortLufs": -18.0, "sensitivity": "standard",
                   "speed": "standard", "maxReductionDb": 12.0},
        "triggerLufs": -15.0,
        "targetLufs": {"low": -21.0, "high": -17.0},
        "minSystemVolume": 5.0,
        # Deprecated (unused since M9; kept so older settings files still load):
        # maxSystemVolume, lowerStepPercent, recoveryStepPercent.
        "maxSystemVolume": 75.0,
        "lowerStepPercent": 3.0,
        "lowerGain": 0.7,
        "maxLowerDbPerSecond": 2.0,
        "minLowerStepDb": 0.25,
        "maxAutoAttenuationDb": 12.0,
        "recoveryStepPercent": 1.0,
        "lowerSustainSeconds": 2.5,
        "sustainRatio": 0.8,
        "recoverySustainSeconds": 20.0,
        "recoveryPercentile": 0.9,
        "recoveryHeadroomLu": 1.0,
        "maxRaiseDbPerSecond": 0.5,
        "recoveryCooldownSeconds": 20.0,
        "songGapSeconds": 1.5,
        "songHoldMaxSeconds": 240.0,
        "fadeSlopeLuPerSecond": 0.4,
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
    candidate = {key: value for key, value in candidate.items()
                 if key not in DEPRECATED_SETTINGS}
    allowed = set(result)
    unknown = set(candidate) - allowed
    if unknown:
        raise ValueError("未知设置字段：%s" % ", ".join(sorted(unknown)))
    result.update(deepcopy(candidate))
    if result.get("schemaVersion") != SETTINGS_SCHEMA:
        raise ValueError("不支持的 settings schemaVersion")
    if result.get("mode") not in MODES:
        raise ValueError("mode 必须是 monitor、shadow、lower-only 或 automatic")
    preset = result.get("preset")
    if (not isinstance(preset, dict)
            or set(preset) != {"mode", "comfortLufs", "sensitivity", "speed", "maxReductionDb"}):
        raise ValueError("preset 必须只包含 mode、comfortLufs、sensitivity、speed、maxReductionDb")
    if preset["mode"] not in {"simple", "custom"}:
        raise ValueError("preset.mode 必须是 simple 或 custom")
    if preset["sensitivity"] not in {"low", "standard", "high"}:
        raise ValueError("preset.sensitivity 必须是 low、standard 或 high")
    if preset["speed"] not in {"gentle", "standard", "fast"}:
        raise ValueError("preset.speed 必须是 gentle、standard 或 fast")
    preset["comfortLufs"] = _number(preset["comfortLufs"], "preset.comfortLufs", -70, 0)
    preset["maxReductionDb"] = _number(preset["maxReductionDb"], "preset.maxReductionDb", 1, 40)
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
        ("maxAutoAttenuationDb", 1, 40),
        ("recoveryStepPercent", 0.1, 10),
        ("lowerSustainSeconds", 0.25, 60),
        ("sustainRatio", 0.5, 1),
        ("recoverySustainSeconds", 0.5, 300),
        ("recoveryPercentile", 0.5, 1),
        ("recoveryHeadroomLu", 0, 6),
        ("maxRaiseDbPerSecond", 0.05, 6),
        ("recoveryCooldownSeconds", 0, 600),
        ("songGapSeconds", 0.5, 30),
        ("songHoldMaxSeconds", 30, 1800),
        ("fadeSlopeLuPerSecond", 0.05, 5),
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
        self.baseline_volume_db = None
        self.over_window = deque()
        self.lowering_active = False
        self.last_lower_ms = None
        self.last_raise_ms = None
        self.manual_until_ms = 0.0
        self.state = "MONITORING"
        self.last_timestamp_ms = None
        # M9 recovery ("debt" model, per-song hold).
        self.content_window = deque()   # (t, loudness at 0 dB attenuation)
        self.slope_window = deque()     # (t, effective loudness) for the fade guard
        self.song_lowered = False
        self.silence_since_ms = None
        # Shadow mode simulates its own suggestions on a virtual volume so that
        # lowering converges and recovery suggestions become observable.
        self.shadow_offset_db = 0.0
        self.diagnostics = None

    def set_baseline(self, observation):
        """Plan A ceiling: recovery never goes above this user-chosen level."""
        if observation is None:
            return
        self.baseline_volume = observation.get("systemVolume")
        self.baseline_volume_db = observation.get("systemVolumeDb")

    def update_settings(self, partial):
        merged = dict(partial)
        merged["updatedAt"] = iso_now()
        previous_mode = self.settings["mode"]
        self.settings = validate_settings(merged, self.settings)
        self._reset_levels()
        if self.settings["mode"] != previous_mode:
            self.shadow_offset_db = 0.0
            self.song_lowered = False
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
                "songLowered": self.song_lowered,
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

    def _new_song(self):
        self.song_lowered = False
        self.content_window.clear()
        self.slope_window.clear()

    def _note_silence(self, now):
        """A silence gap of songGapSeconds or longer is treated as a song change."""
        if self.silence_since_ms is None:
            self.silence_since_ms = now
        if now - self.silence_since_ms >= self.settings["songGapSeconds"] * 1000:
            self._new_song()

    def _note_sound(self, now, level, observation):
        self.silence_since_ms = None
        window_ms = self.settings["recoverySustainSeconds"] * 1000
        self.content_window.append((now, level - observation["outputAttenuationDb"]))
        while self.content_window and self.content_window[0][0] < now - window_ms:
            self.content_window.popleft()
        self.slope_window.append((now, level))
        while self.slope_window and self.slope_window[0][0] < now - FADE_WINDOW_MS:
            self.slope_window.popleft()

    def _slope(self):
        """Least-squares slope (LU/s) of effective loudness over the fade window."""
        if len(self.slope_window) < FADE_MIN_SAMPLES:
            return None
        start = self.slope_window[0][0]
        xs = [(t - start) / 1000 for t, _value in self.slope_window]
        ys = [value for _t, value in self.slope_window]
        mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
        spread = sum((x - mean_x) ** 2 for x in xs)
        if spread <= 0:
            return None
        return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / spread

    def _loud_part(self):
        values = sorted(value for _t, value in self.content_window)
        index = min(len(values) - 1, int(self.settings["recoveryPercentile"] * len(values)))
        return values[index]

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

    def _virtualize(self, observation):
        """Shadow mode: view the observation as if earlier suggestions had been applied."""
        offset = self.shadow_offset_db
        if (self.settings["mode"] != "shadow" or abs(offset) < 1e-9
                or observation["systemVolumeDb"] is None
                or observation["outputAttenuationDb"] is None):
            return observation
        virtual = dict(observation)
        virtual["systemVolumeDb"] = observation["systemVolumeDb"] + offset
        virtual["outputAttenuationDb"] = observation["outputAttenuationDb"] + offset
        if observation["captureResponse"] == "post-volume":
            # post-volume capture already contains the real attenuation.
            for key in ("shortTermLufs", "momentaryLufs"):
                if virtual[key] is not None:
                    virtual[key] = virtual[key] + offset
        return virtual

    def step(self, raw_observation):
        observation = validate_observation(raw_observation)
        if (observation["manualVolumeChanged"]
                or (self.device_id is not None and observation["deviceId"] != self.device_id)):
            self.shadow_offset_db = 0.0
        action = self._decide(self._virtualize(observation))
        if self.settings["mode"] == "shadow":
            if (action["kind"] in {"would-lower", "would-recover"}
                    and action["recommendedAttenuationDb"] is not None):
                self.shadow_offset_db = min(
                    0.0, self.shadow_offset_db + action["recommendedAttenuationDb"])
            action["evidence"]["shadowOffsetDb"] = round(self.shadow_offset_db, 3)
        self.diagnostics = self._diagnostics(self._virtualize(observation), action)
        return action

    def _diagnostics(self, observation, action):
        """Snapshot of what each side (lower / raise) is currently waiting for.

        Read-only: it never changes controller state, it only explains it.
        """
        settings = self.settings
        mode = settings["mode"]
        now = observation["timestampMs"]
        attenuation = observation["outputAttenuationDb"]
        level = effective_output_lufs(observation["shortTermLufs"],
                                      observation["captureResponse"], attenuation)
        high = settings["targetLufs"]["high"]
        threshold = high if self.lowering_active else settings["triggerLufs"]
        covered = ((now - self.over_window[0][0]) / 1000) if self.over_window else 0.0
        ratio = (sum(over for _t, over in self.over_window) / len(self.over_window)
                 if self.over_window else 0.0)
        debt = max(0.0, self._debt_db(observation, mode))
        lower = {
            "enabled": mode in {"shadow", "lower-only", "automatic"},
            "active": self.lowering_active,
            "levelLufs": level,
            "thresholdLufs": threshold,
            "above": level is not None and level > threshold,
            "windowSeconds": round(covered, 2),
            "requiredSeconds": settings["lowerSustainSeconds"],
            "ratio": round(ratio, 3),
            "requiredRatio": settings["sustainRatio"],
            "loweredDb": round(debt, 3),
            "maxDb": settings["maxAutoAttenuationDb"],
        }
        since_lower = None if self.last_lower_ms is None else (now - self.last_lower_ms) / 1000
        window = settings["recoverySustainSeconds"]
        span = ((self.content_window[-1][0] - self.content_window[0][0]) / 1000
                if self.content_window else 0.0)
        loud_now = (self._loud_part() + attenuation
                    if self.content_window and attenuation is not None else None)
        limit = high - settings["recoveryHeadroomLu"]
        slope = self._slope()
        silence = ((now - self.silence_since_ms) / 1000
                   if self.silence_since_ms is not None else 0.0)
        hold_left = None
        if self.song_lowered and since_lower is not None:
            hold_left = max(0.0, settings["songHoldMaxSeconds"] - since_lower)
        cooldown_left = (max(0.0, settings["recoveryCooldownSeconds"] - since_lower)
                         if since_lower is not None else 0.0)
        raise_side = {
            "enabled": mode in {"shadow", "automatic"},
            "debtDb": round(debt, 3),
            "songLowered": self.song_lowered,
            "silenceSeconds": round(silence, 2),
            "songGapSeconds": settings["songGapSeconds"],
            "holdLeftSeconds": None if hold_left is None else round(hold_left, 1),
            "cooldownLeftSeconds": round(cooldown_left, 1),
            "slopeLuPerSecond": None if slope is None else round(slope, 3),
            "fadeLimitLuPerSecond": -settings["fadeSlopeLuPerSecond"],
            "windowSeconds": round(span, 1),
            "requiredSeconds": round(window * 0.75, 1),
            "loudPartLufs": None if loud_now is None else round(loud_now, 2),
            "predictedFullLufs": None if loud_now is None else round(loud_now + debt, 2),
            "limitLufs": round(limit, 2),
            "roomDb": None if loud_now is None else round(limit - loud_now, 2),
        }
        return {"lower": lower, "raise": raise_side, "kind": action["kind"],
                "state": action["state"], "reason": action["reason"]}

    def _decide(self, observation):
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
            self.set_baseline(observation)
        elif observation["deviceId"] != self.device_id:
            self.device_id = observation["deviceId"]
            self.set_baseline(observation)
            self.manual_until_ms = 0
            self.last_lower_ms = self.last_raise_ms = None
            self._reset_levels()
            self._new_song()
            self.state = "RECALIBRATING"
            return self._action(observation, "device-change", "输出设备变化，等待重新校准")
        elif self.baseline_volume is None or self.baseline_volume_db is None:
            self.set_baseline(observation)

        if observation["manualVolumeChanged"] and observation["systemVolume"] is not None:
            self.set_baseline(observation)
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
            self._note_silence(now)
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
            self._note_silence(now)
            self.state = "AUTO_HOLDING" if mode != "shadow" else "SHADOW"
            return self._action(
                observation, "blocked",
                "当前 RMS %.1f dBFS 低于静音门 %.1f dBFS，禁止调整" % (
                    observation["rmsDbfs"], self.settings["silenceGateDbfs"]))
        self._note_sound(now, level, observation)

        target_high = self.settings["targetLufs"]["high"]
        if self.lowering_active and level <= target_high:
            self.over_window.clear()
            self.lowering_active = False

        threshold = target_high if self.lowering_active else self.settings["triggerLufs"]
        if self.lowering_active or level > threshold or self.over_window:
            sustained, ratio = self._high_window(now, level, threshold)
            # Samples spaced one tick apart can only span (window - tick); requiring the
            # full window would never be met with real-time jitter.
            required = max(min(self.settings["lowerSustainSeconds"], step_seconds),
                           self.settings["lowerSustainSeconds"] - step_seconds - 0.05)
            has_high_sample = any(over for _timestamp, over in self.over_window)
            if not has_high_sample:
                self.over_window.clear()
            elif (sustained < required
                  or ratio < self.settings["sustainRatio"]):
                self.state = "OBSERVING_HIGH"
                action = self._action(
                    observation, reason="等待偏响证据窗口", sustained=sustained)
                action["evidence"].update(windowRatio=round(ratio, 3),
                                          windowSamples=len(self.over_window))
                return action
            else:
                sample_count = len(self.over_window)
                # pre-volume: effective loudness already includes the endpoint
                # attenuation, so feedback is immediate and lowering can continue at
                # maxLowerDbPerSecond. post-volume capture lags by the 3 s window, so
                # collect fresh evidence after every step to avoid overshoot.
                if observation["captureResponse"] != "pre-volume":
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
                if desired_db < self.settings["minLowerStepDb"]:
                    self.over_window.clear()
                    self.lowering_active = False
                    self.state = "SHADOW" if mode == "shadow" else "AUTO_HOLDING"
                    return self._action(
                        observation,
                        reason="剩余偏差 %.2f dB 小于最小下降步长 %.2f dB，结束本轮压低" % (
                            desired_db, self.settings["minLowerStepDb"]),
                        sustained=sustained)
                rate_cap = self.settings["maxLowerDbPerSecond"] * step_seconds
                step_db = min(max(desired_db, self.settings["minLowerStepDb"]), rate_cap)
                floor_db = observation["volumeDbMin"]
                reference_db = (observation["systemVolumeDb"] - self.shadow_offset_db
                                if mode == "shadow" else self.baseline_volume_db)
                if reference_db is not None:
                    floor_db = max(floor_db, reference_db - self.settings["maxAutoAttenuationDb"])
                target_db = max(floor_db, observation["systemVolumeDb"] - step_db)
                actual_step_db = target_db - observation["systemVolumeDb"]
                if actual_step_db >= -0.01:
                    self.state = "SHADOW" if mode == "shadow" else "AUTO_HOLDING"
                    return self._action(
                        observation, "blocked",
                        "已达到本次最多压低 %.1f dB 或设备最低 dB" % (
                            self.settings["maxAutoAttenuationDb"]),
                        sustained=sustained)
                execute = mode in {"lower-only", "automatic"}
                self.state = "LOWERING" if execute else "SHADOW"
                self.last_lower_ms = now
                self.song_lowered = True
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
        repay = self._repay(observation, mode, now, level, step_seconds)
        if repay is not None:
            return repay

        if not self.lowering_active and level > target_high:
            self.state = "SHADOW" if mode == "shadow" else "AUTO_HOLDING"
            return self._action(
                observation, reason="输出估算高于目标上沿，但尚未达到降低触发线")

        self.state = "SHADOW" if mode == "shadow" else "AUTO_HOLDING"
        if level < target_low:
            return self._action(
                observation, reason="输出估算低于目标区间；没有被压低的音量，不会升到你设定的音量以上"
                if mode != "lower-only" else "输出估算低于目标区间；只自动压低模式不回升")
        return self._action(observation, reason="输出估算位于目标或回差区间")

    def _debt_db(self, observation, mode):
        """How much this program has taken away and may give back (plan A)."""
        if mode == "shadow":
            return -self.shadow_offset_db
        if self.baseline_volume_db is None or observation["systemVolumeDb"] is None:
            return 0.0
        return self.baseline_volume_db - observation["systemVolumeDb"]

    def _repay(self, observation, mode, now, level, step_seconds):
        """Give back lowered volume once it would not make the content loud again.

        Rules (M9 v2):
        * only the debt is repaid, never above the baseline;
        * after a lowering, the rest of that song keeps the lowered volume; a silence
          gap of songGapSeconds (song change) or songHoldMaxSeconds without one ends
          the hold;
        * the loud part (percentile) of the last recoverySustainSeconds, raised by the
          step, must stay recoveryHeadroomLu below the target upper edge;
        * no raise while loudness is still falling (fade-out).
        """
        if mode not in {"automatic", "shadow"}:
            return None
        debt = self._debt_db(observation, mode)
        if debt < 0.05:
            return None
        holding = "SHADOW" if mode == "shadow" else "AUTO_HOLDING"
        evidence = {"debtDb": round(debt, 3)}

        def hold(reason, state=holding):
            self.state = state
            action = self._action(observation, reason=reason)
            action["evidence"].update(evidence)
            return action

        if (not observation["volumeDbMappingReliable"]
                or observation["systemVolumeDb"] is None
                or observation["outputAttenuationDb"] is None):
            return hold("设备 dB 映射不可靠，不回升")
        hold_ms = self.settings["songHoldMaxSeconds"] * 1000
        since_lower = None if self.last_lower_ms is None else now - self.last_lower_ms
        if self.song_lowered and since_lower is not None and since_lower < hold_ms:
            return hold("本首歌压低过 %.1f dB，保持到换歌（静音 ≥ %.1f 秒）；最长保持 %.0f 秒" % (
                debt, self.settings["songGapSeconds"], self.settings["songHoldMaxSeconds"]))
        cooldown_ms = self.settings["recoveryCooldownSeconds"] * 1000
        if since_lower is not None and since_lower < cooldown_ms:
            return hold("刚压低过，%.0f 秒内不回升（还剩 %.0f 秒）" % (
                self.settings["recoveryCooldownSeconds"], (cooldown_ms - since_lower) / 1000))
        slope = self._slope()
        if slope is not None and slope < -self.settings["fadeSlopeLuPerSecond"]:
            evidence["slopeLuPerSecond"] = round(slope, 3)
            return hold("响度正在持续下滑（%.2f LU/秒，可能是淡出），暂不回升" % slope)
        window = self.settings["recoverySustainSeconds"]
        span = ((self.content_window[-1][0] - self.content_window[0][0]) / 1000
                if self.content_window else 0.0)
        if span < window * 0.75 - step_seconds:
            return hold("回升判定窗口未满（%.0f/%.0f 秒）" % (span, window * 0.75))
        if (observation["captureResponse"] != "pre-volume" and self.last_raise_ms is not None
                and now - self.last_raise_ms < POST_VOLUME_SETTLE_MS):
            return hold("等待上次回升反映到测量结果中", "RECOVERING")

        loud = self._loud_part() + observation["outputAttenuationDb"]
        limit = self.settings["targetLufs"]["high"] - self.settings["recoveryHeadroomLu"]
        room = limit - loud
        min_step = min(self.settings["minLowerStepDb"], debt)
        evidence.update(loudPartLufs=round(loud, 3), limitLufs=round(limit, 3),
                        roomDb=round(room, 3),
                        percentile=self.settings["recoveryPercentile"])
        if room < min_step:
            return hold("还回音量会让响部达到 %.1f LUFS（上限 %.1f），暂不回升" % (
                loud + min_step, limit))
        elapsed = (1.0 if self.last_raise_ms is None
                   else max(0.0, min(1.0, (now - self.last_raise_ms) / 1000)))
        allowed = self.settings["maxRaiseDbPerSecond"] * elapsed
        step_db = min(debt, room, allowed)
        if step_db < min_step - 1e-9:
            return hold("按每秒最多回升 %.2f dB 限速等待" % self.settings["maxRaiseDbPerSecond"],
                        "RECOVERING")
        target_db = observation["systemVolumeDb"] + step_db
        if observation["volumeDbMax"] is not None:
            target_db = min(target_db, observation["volumeDbMax"])
        actual_step_db = target_db - observation["systemVolumeDb"]
        if actual_step_db <= 0.01:
            return hold("已经回到基准音量")
        self.last_raise_ms = now
        execute = mode == "automatic"
        self.state = "RECOVERING" if execute else "SHADOW"
        action = self._action(
            observation, "recover" if execute else "would-recover",
            "还有 %.1f dB 压低未还；还回后响部仍低于上限，按 dB 缓慢回升" % debt,
            None, execute, 0.0, round(target_db, 3), round(actual_step_db, 3))
        evidence.update(rateLimitDb=round(allowed, 3))
        action["evidence"].update(evidence)
        return action
