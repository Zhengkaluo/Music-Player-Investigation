"""Local-only simulator or platform read-only meter, API, and dashboard server."""

from __future__ import annotations

import argparse
from collections import deque
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import math
import os
from pathlib import Path
import signal
import threading
import time
from urllib.parse import urlsplit

from controller import (STATE_SCHEMA, VolumeController, default_settings,
                        effective_output_lufs, validate_settings)
from device_profiles import DeviceProfileStore, classify_points, stable_point
from executor import EXECUTOR_VERSION, LowerOnlyExecutor
from presets import DERIVED_KEYS, PRESET_KEYS, PresetTable, legacy_preset
from source_contract import validate_source


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui" / "index.html"
SCENARIOS = ROOT / "fixtures" / "scenarios.json"
PRESETS = ROOT / "config" / "simple-presets.json"
DEFAULT_SETTINGS_PATH = ROOT / "runtime" / "settings.json"
MAX_BODY = 64 * 1024
SHADOW_EVENT_GROUP_MS = 30_000
GROUPED_ACTION_KINDS = {"would-lower", "lower", "would-recover", "recover"}
EXECUTING_MODES = {"lower-only", "automatic"}
MODE_LABELS = {"monitor": "关闭", "shadow": "只提示", "lower-only": "自动压低",
               "automatic": "自动调节"}


def read_json(path):
    with Path(path).open("r", encoding="utf-8") as source:
        return json.load(source)


def write_json_atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(str(temporary), str(path))


class Simulator:
    platform = "simulator"
    simulated = True
    measurement_source = "simulated-unverified-loudness"

    def __init__(self, scenarios_path=SCENARIOS):
        document = read_json(scenarios_path)
        if document.get("schemaVersion") != "system-audio.simulation-scenarios/v1":
            raise ValueError("不支持的模拟场景 schemaVersion")
        scenarios = document.get("scenarios")
        if not isinstance(scenarios, list) or not scenarios:
            raise ValueError("模拟场景不能为空")
        self.scenarios = {item["id"]: item for item in scenarios}
        self.order = [item["id"] for item in scenarios]
        self.current_id = self.order[0]
        self.current_started = time.monotonic()
        self.forced_until = 0.0
        self.volume = 67.0
        self.device_id = "simulated-speakers"
        self.device_name = "模拟系统输出"
        self.manual_changed = False
        self.peak_guard_count = 0
        self.last_peak_trigger = None

    def select(self, scenario_id, seconds=10):
        if scenario_id not in self.scenarios:
            raise ValueError("未知模拟场景：%s" % scenario_id)
        self.current_id = scenario_id
        self.current_started = time.monotonic()
        self.forced_until = time.monotonic() + max(1.0, min(float(seconds), 60.0))
        if scenario_id == "peak":
            self._trigger_peak_guard()

    def set_manual_volume(self, volume):
        if isinstance(volume, bool) or not isinstance(volume, (int, float)) or not math.isfinite(volume):
            raise ValueError("volume 必须是有限数字")
        self.volume = max(0.0, min(100.0, float(volume)))
        self.manual_changed = True

    def switch_device(self):
        if self.device_id == "simulated-speakers":
            self.device_id, self.device_name, self.volume = "simulated-headphones", "模拟蓝牙耳机", 42.0
        else:
            self.device_id, self.device_name, self.volume = "simulated-speakers", "模拟系统输出", 67.0

    def apply_volume(self, volume):
        self.volume = max(0.0, min(100.0, float(volume)))
        return self.volume

    def recommended_volume(self, target_db):
        return max(0.0, min(100.0, (float(target_db) + 60.0) / 60.0 * 100.0))

    def close(self):
        pass

    def _trigger_peak_guard(self):
        self.peak_guard_count += 1
        self.last_peak_trigger = {
            "blockIndex": self.peak_guard_count * 100,
            "samplePeakDbfs": -0.8,
            "fastRmsDbfs": -7.0,
            "baselineRmsDbfs": -22.0,
            "relativeJumpDb": 15.0,
            "suggestedAttenuationDb": -12.0,
        }

    def _advance(self):
        now = time.monotonic()
        if now < self.forced_until:
            return
        current = self.scenarios[self.current_id]
        if now - self.current_started >= float(current["durationSeconds"]):
            index = (self.order.index(self.current_id) + 1) % len(self.order)
            self.current_id = self.order[index]
            self.current_started = now
            if self.current_id == "peak":
                self._trigger_peak_guard()

    def observe(self, timestamp_ms):
        self._advance()
        item = self.scenarios[self.current_id]
        # Small deterministic movement keeps the dashboard visibly alive without randomness.
        wave = math.sin(timestamp_ms / 1800.0) * 0.35
        manual = self.manual_changed
        self.manual_changed = False
        def shifted(name):
            return None if item[name] is None else round(float(item[name]) + wave, 3)
        peak_active = item["id"] == "peak"
        peak_guard = {
            "mode": "shadow",
            "state": "HOLD" if peak_active else "ARMED",
            "warmedUp": True,
            "samplePeakDbfs": shifted("peakDbfs"),
            "truePeakDbtp": None,
            "fastRmsDbfs": -7.0 if peak_active else shifted("rmsDbfs"),
            "baselineRmsDbfs": -22.0,
            "relativeJumpDb": 15.0 if peak_active else 0.0,
            "suggestedAttenuationDb": -12.0 if peak_active else 0.0,
            "triggerCount": self.peak_guard_count,
            "lastTrigger": deepcopy(self.last_peak_trigger),
            "execute": False,
        }
        system_db = -60.0 + self.volume / 100.0 * 60.0
        return {
            "timestampMs": float(timestamp_ms),
            "platform": self.platform,
            "deviceId": self.device_id,
            "deviceName": self.device_name,
            "environmentFingerprint": "simulator/v1",
            "deviceTransport": "simulated",
            "systemVolume": round(self.volume, 3),
            "systemVolumeDb": round(system_db, 3),
            "volumeDbMin": -60.0,
            "volumeDbMax": 0.0,
            "volumeDbStep": 0.1,
            "outputAttenuationDb": round(system_db, 3),
            "volumeDbSource": "simulated-linear-db",
            "volumeDbMappingReliable": True,
            "captureResponse": "post-volume",
            "shortTermLufs": shifted("shortTermLufs"),
            "momentaryLufs": shifted("momentaryLufs"),
            "rmsDbfs": shifted("rmsDbfs"),
            "peakDbfs": shifted("peakDbfs"),
            "isSilent": bool(item["isSilent"]),
            "captureAvailable": True,
            "volumeControllable": True,
            "manualVolumeChanged": manual,
            "scenarioId": item["id"],
            "scenarioLabel": item["label"],
            "peakGuard": peak_guard,
        }


class AppState:
    def __init__(self, settings_path=DEFAULT_SETTINGS_PATH, scenarios_path=SCENARIOS,
                 tick_seconds=0.25, start_worker=True, source=None, profiles_path=None,
                 presets_path=None):
        self.settings_path = Path(settings_path)
        self.tick_seconds = float(tick_seconds)
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.source = validate_source(source or Simulator(scenarios_path))
        self.simulator = self.source if self.source.simulated else None
        self.profile_store = DeviceProfileStore(
            profiles_path or self.settings_path.with_name("device-profiles.json"))
        self.calibration_session = None
        self.active_profile = None
        self.last_observation = None
        self.presets = PresetTable(presets_path or PRESETS)
        self.settings = self._load_settings()
        self.executor = None if self.source.simulated else LowerOnlyExecutor(self.source)
        self.executor_notice = None
        if not self.source.simulated and self.settings["mode"] not in {"monitor", "shadow"}:
            # Automatic writes never resume by themselves after a restart.
            previous_mode = self.settings["mode"]
            self.settings["mode"] = "shadow"
            self.executor_notice = "启动时不会自动恢复“%s”；需要时请重新开启" % MODE_LABELS[previous_mode]
        self.controller = VolumeController(self.settings)
        self.shadow_log_path = self.settings_path.with_name(
            "%s-shadow-events.jsonl" % self.source.platform)
        self.executor_log_path = self.settings_path.with_name(
            "%s-executor-events.jsonl" % self.source.platform)
        self.shadow_event_count = 0
        self.shadow_log_error = None
        if self.shadow_log_path.exists():
            try:
                with self.shadow_log_path.open("r", encoding="utf-8") as source_file:
                    self.shadow_event_count = sum(1 for line in source_file if line.strip())
            except OSError as error:
                self.shadow_log_error = str(error)
        self.history_rows = deque(maxlen=max(4, int(60 / self.tick_seconds)))
        self.actions = deque(maxlen=100)
        self.peak_guard_events = deque(maxlen=100)
        self.last_action_event_key = None
        self.last_peak_guard_count = 0
        self.snapshot = None
        self.worker = None
        self.tick()
        if start_worker:
            self.worker = threading.Thread(target=self._run, name="audio-state", daemon=True)
            self.worker.start()

    def _load_settings(self):
        if not self.settings_path.exists():
            return default_settings()
        raw = read_json(self.settings_path)
        if isinstance(raw, dict) and "preset" not in raw:
            merged = {**default_settings(), **raw}
            try:
                table = self.presets.table()
            except (OSError, ValueError):
                table = None
            raw = {**raw, "preset": legacy_preset(merged, table)}
        settings = validate_settings(raw)
        if settings["preset"]["mode"] == "simple":
            try:
                settings = validate_settings(self.presets.derive(settings["preset"]), settings)
            except (OSError, ValueError):
                pass
        return settings

    def close(self):
        self.stop_event.set()
        if self.worker:
            self.worker.join(timeout=2)
        if self.executor is not None:
            with self.lock:
                result = self.executor.restore("服务退出")
                if result:
                    self._log_executor(result)
        close = getattr(self.source, "close", None)
        if close:
            close()

    def _log_executor(self, result):
        record = {"schemaVersion": "system-audio.executor-event/v1",
                  "timestampMs": time.time() * 1000, **deepcopy(result)}
        try:
            self.executor_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.executor_log_path.open("a", encoding="utf-8") as target:
                target.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _executor_event(self, timestamp_ms, kind, reason, result=None):
        event = {
            "schemaVersion": "system-audio.action/v1",
            "timestampMs": timestamp_ms,
            "state": "MONITORING",
            "kind": kind,
            "reason": reason,
            "evidence": {"deviceId": None if not self.last_observation
                         else self.last_observation.get("deviceId"),
                         "executor": deepcopy(result)},
            "beforeVolume": None if not result else result.get("beforeVolume"),
            "recommendedVolume": None,
            "beforeVolumeDb": None if not result else result.get("beforeVolumeDb"),
            "recommendedVolumeDb": None,
            "recommendedAttenuationDb": None,
            "appliedVolume": None if not result else result.get("appliedVolume"),
            "appliedVolumeDb": None if not result else result.get("appliedVolumeDb"),
            "execute": bool(result and result.get("status") == "restored"),
            "mode": self.settings["mode"],
            "controllerVersion": EXECUTOR_VERSION,
            "settingsUpdatedAt": self.settings["updatedAt"],
        }
        self.actions.appendleft(event)
        self.last_action_event_key = None
        self._log_executor({"status": kind, "reason": reason, "result": deepcopy(result)})

    def _leave_lower_only(self, reason, timestamp_ms):
        """Stop automatic writes, restore if still ours, and fall back to shadow."""
        restored = self.executor.restore(reason)
        self.settings = self.controller.update_settings({"mode": "shadow"})
        write_json_atomic(self.settings_path, self.settings)
        self.executor_notice = reason
        self._executor_event(timestamp_ms, "executor-stopped", reason, restored)

    def _run(self):
        while not self.stop_event.wait(self.tick_seconds):
            self.tick()

    def tick(self, timestamp_ms=None):
        with self.lock:
            timestamp_ms = float(timestamp_ms if timestamp_ms is not None else time.time() * 1000)
            observation = self.source.observe(timestamp_ms)
            observation.setdefault("platform", self.source.platform)
            if self.source.simulated:
                observation.setdefault("profileStatus", "simulated")
                observation.setdefault("captureConfidence", "high")
                self.active_profile = None
            else:
                observation, self.active_profile = self.profile_store.apply(observation)
            self.last_observation = deepcopy(observation)
            action = self.controller.step(observation)
            if action["recommendedVolumeDb"] is not None:
                converter = getattr(self.source, "recommended_volume", None)
                if callable(converter):
                    try:
                        action["recommendedVolume"] = round(
                            converter(action["recommendedVolumeDb"]), 3)
                    except (ValueError, RuntimeError, OSError):
                        action["recommendedVolume"] = None
            if self.executor is not None:
                if action["kind"] in {"manual-override", "device-change"}:
                    self.executor.interrupt(action["reason"])
                if self.settings["mode"] in EXECUTING_MODES:
                    mode_label = MODE_LABELS[self.settings["mode"]]
                    problem = (self.executor.disabled_reason
                               or self.executor.gate(observation, self.settings["mode"]))
                    if problem:
                        action["execute"] = False
                        self._leave_lower_only("%s已停止：%s" % (mode_label, problem), timestamp_ms)
                    elif action["execute"] and action["kind"] in {"lower", "recover"}:
                        result = self.executor.execute(action, observation, self.settings,
                                                       timestamp_ms)
                        action["evidence"]["executor"] = result
                        if result["status"] == "applied":
                            action["appliedVolume"] = round(result["appliedVolume"], 3)
                            if result.get("appliedVolumeDb") is not None:
                                action["appliedVolumeDb"] = round(result["appliedVolumeDb"], 3)
                        else:
                            action["execute"] = False
                        if result["status"] in {"applied", "failed"}:
                            self._log_executor(result)
                        if self.executor.disabled_reason:
                            self._leave_lower_only(
                                "%s已停止：%s" % (mode_label, self.executor.disabled_reason),
                                timestamp_ms)
                    elif action["execute"]:
                        action["execute"] = False
            peak_guard = deepcopy(observation.get("peakGuard"))
            if peak_guard:
                trigger_count = int(peak_guard.get("triggerCount") or 0)
                if trigger_count < self.last_peak_guard_count:
                    self.last_peak_guard_count = 0
            if (peak_guard and peak_guard.get("lastTrigger")
                    and trigger_count > self.last_peak_guard_count):
                trigger = peak_guard["lastTrigger"]
                self.peak_guard_events.appendleft({
                    "schemaVersion": "system-audio.peak-guard-event/v1",
                    "timestampMs": timestamp_ms,
                    "kind": "peak-guard",
                    "state": "ATTACK",
                    "reason": "检测到短时峰值与基线突增，仅记录建议衰减",
                    "evidence": deepcopy(trigger),
                    "suggestedAttenuationDb": trigger["suggestedAttenuationDb"],
                    "execute": False,
                    "mode": "shadow",
                })
            if peak_guard:
                self.last_peak_guard_count = trigger_count
            if self.simulator and action["execute"] and action["recommendedVolume"] is not None:
                action["appliedVolume"] = round(self.simulator.apply_volume(action["recommendedVolume"]), 3)
            if action["kind"] == "none":
                self.last_action_event_key = None
            else:
                event_key = (action["kind"], action["reason"], action["state"],
                             action["evidence"]["deviceId"])
                grouped_kind = action["kind"] in GROUPED_ACTION_KINDS
                if not grouped_kind:
                    event_key += (action["beforeVolumeDb"], action["recommendedVolumeDb"],
                                  action["appliedVolume"])
                grouped = False
                if grouped_kind and self.actions:
                    previous = self.actions[0]
                    window = previous.get("eventWindow")
                    previous_key = (previous["kind"], previous["reason"], previous["state"],
                                    previous["evidence"]["deviceId"])
                    if (window and previous_key == event_key
                            and timestamp_ms - window["firstTimestampMs"] <= SHADOW_EVENT_GROUP_MS):
                        window["lastTimestampMs"] = timestamp_ms
                        window["durationSeconds"] = round(
                            (timestamp_ms - window["firstTimestampMs"]) / 1000, 3)
                        window["occurrences"] += 1
                        targets = [value for value in (
                            window.get("recommendedVolumeDbMin"),
                            window.get("recommendedVolumeDbMax"),
                            action["recommendedVolumeDb"],
                        ) if value is not None]
                        if targets:
                            window["recommendedVolumeDbMin"] = min(targets)
                            window["recommendedVolumeDbMax"] = max(targets)
                        previous["timestampMs"] = timestamp_ms
                        previous["evidence"] = deepcopy(action["evidence"])
                        previous["beforeVolume"] = action["beforeVolume"]
                        previous["beforeVolumeDb"] = action["beforeVolumeDb"]
                        previous["recommendedVolume"] = action["recommendedVolume"]
                        previous["recommendedVolumeDb"] = action["recommendedVolumeDb"]
                        previous["recommendedAttenuationDb"] = action["recommendedAttenuationDb"]
                        if action["appliedVolume"] is not None:
                            previous["appliedVolume"] = action["appliedVolume"]
                            previous["appliedVolumeDb"] = action["appliedVolumeDb"]
                        grouped = True
                if not grouped and event_key != self.last_action_event_key:
                    event = deepcopy(action)
                    if grouped_kind:
                        event["eventWindow"] = {
                            "firstTimestampMs": timestamp_ms,
                            "lastTimestampMs": timestamp_ms,
                            "durationSeconds": 0.0,
                            "occurrences": 1,
                            "recommendedVolumeDbMin": action["recommendedVolumeDb"],
                            "recommendedVolumeDbMax": action["recommendedVolumeDb"],
                        }
                    self.actions.appendleft(event)
                    self.last_action_event_key = event_key
                    if not self.source.simulated and action["mode"] == "shadow":
                        try:
                            self.shadow_log_path.parent.mkdir(parents=True, exist_ok=True)
                            with self.shadow_log_path.open("a", encoding="utf-8") as target:
                                target.write(json.dumps(event, ensure_ascii=False) + "\n")
                            self.shadow_event_count += 1
                            self.shadow_log_error = None
                        except OSError as error:
                            self.shadow_log_error = str(error)
            volume = observation["systemVolume"]
            if self.simulator:
                volume = self.simulator.volume
            baseline = self.controller.baseline_volume
            effective_lufs = effective_output_lufs(
                observation["shortTermLufs"], observation.get("captureResponse", "unknown"),
                observation.get("outputAttenuationDb"))
            self.snapshot = {
                "schemaVersion": STATE_SCHEMA,
                "timestampMs": timestamp_ms,
                "platform": self.source.platform,
                "simulated": self.source.simulated,
                "device": {
                    "id": observation["deviceId"],
                    "name": observation["deviceName"],
                    "captureAvailable": observation["captureAvailable"],
                    "volumeControllable": observation["volumeControllable"],
                    "volumeReadable": observation.get("volumeReadable", True),
                    "volumeWritableCapability": observation.get("volumeWritableCapability", True),
                    "muted": observation.get("muted"),
                    "transport": observation.get("deviceTransport"),
                    "environmentFingerprint": observation.get("environmentFingerprint"),
                    "profileStatus": observation.get("profileStatus"),
                    "captureConfidence": observation.get("captureConfidence"),
                    "volumeHardwareSupport": observation.get("volumeHardwareSupport"),
                    "error": observation.get("error"),
                },
                "measurement": {
                    "source": self.source.measurement_source,
                    "scenarioId": observation["scenarioId"],
                    "scenarioLabel": observation["scenarioLabel"],
                    "shortTermLufs": observation["shortTermLufs"],
                    "effectiveLufs": effective_lufs,
                    "captureResponse": observation.get("captureResponse", "unknown"),
                    "momentaryLufs": observation["momentaryLufs"],
                    "rmsDbfs": observation["rmsDbfs"],
                    "peakDbfs": observation["peakDbfs"],
                    "isSilent": observation["isSilent"],
                    "captureIdle": observation.get("captureIdle", False),
                    "idleReason": observation.get("idleReason"),
                    "sampleRate": observation.get("sampleRate"),
                    "channels": observation.get("channels"),
                    "callbacks": observation.get("callbacks"),
                    "droppedFrames": observation.get("droppedFrames"),
                    "maxCallbackSeconds": observation.get("maxCallbackSeconds"),
                    "maxCallbackIntervalSeconds": observation.get("maxCallbackIntervalSeconds"),
                    "peakGuard": peak_guard,
                },
                "volume": {
                    "system": round(volume, 3) if volume is not None else None,
                    "systemDb": observation.get("systemVolumeDb"),
                    "dbMin": observation.get("volumeDbMin"),
                    "dbMax": observation.get("volumeDbMax"),
                    "dbStep": observation.get("volumeDbStep"),
                    "outputAttenuationDb": observation.get("outputAttenuationDb"),
                    "dbSource": observation.get("volumeDbSource"),
                    "dbMappingReliable": observation.get("volumeDbMappingReliable", False),
                    "baseline": round(baseline, 3) if baseline is not None else None,
                    "correctionPercentPoints": round(volume - baseline, 3)
                    if volume is not None and baseline is not None else None,
                    "recommended": action["recommendedVolume"],
                    "recommendedDb": action["recommendedVolumeDb"],
                    "recommendedAttenuationDb": action["recommendedAttenuationDb"],
                    "recommendedCorrectionPercentPoints": round(
                        action["recommendedVolume"] - volume, 3)
                    if action["recommendedVolume"] is not None and volume is not None else None,
                },
                "controller": {
                    "state": action["state"],
                    "lastAction": deepcopy(action),
                    "shadowOffsetDb": round(self.controller.shadow_offset_db, 3),
                    "songLowered": self.controller.song_lowered,
                    "debtDb": action["evidence"].get("debtDb"),
                    "diagnostics": deepcopy(self.controller.diagnostics),
                },
                "manualVolumeTestPending": bool(
                    getattr(self.source, "volume_test_session", None)),
                "calibration": self.calibration_status(),
                "shadow": {
                    "enabled": self.settings["mode"] == "shadow",
                    "eventCount": self.shadow_event_count,
                    "logError": self.shadow_log_error,
                },
                "executor": None if self.executor is None else {
                    **self.executor.status(),
                    "enabled": self.settings["mode"] in EXECUTING_MODES,
                    "gate": self.executor.gate(observation),
                    "automaticGate": self.executor.gate(observation, "automatic"),
                    "notice": self.executor_notice,
                },
                "settings": deepcopy(self.settings),
            }
            self.history_rows.append({
                "timestampMs": timestamp_ms,
                "deviceId": observation["deviceId"],
                "shortTermLufs": observation["shortTermLufs"],
                "effectiveLufs": effective_lufs,
                "momentaryLufs": observation["momentaryLufs"],
                "systemVolume": round(volume, 3) if volume is not None else None,
                "systemVolumeDb": observation.get("systemVolumeDb"),
                "isSilent": observation["isSilent"],
                "rmsDbfs": observation["rmsDbfs"],
                "peakDbfs": observation["peakDbfs"],
                "state": action["state"],
                "action": action["kind"],
                "peakGuardState": None if peak_guard is None else peak_guard.get("state"),
                "suggestedAttenuationDb": None if peak_guard is None else peak_guard.get("suggestedAttenuationDb"),
                "recommendedVolume": action["recommendedVolume"],
                "recommendedVolumeDb": action["recommendedVolumeDb"],
                "execute": action["execute"],
                "debtDb": (self.controller.diagnostics or {}).get("raise", {}).get("debtDb"),
                "predictedRepayLufs": (self.controller.diagnostics or {}).get("raise", {}).get(
                    "predictedFullLufs"),
            })
            return deepcopy(self.snapshot)

    def status(self):
        with self.lock:
            return deepcopy(self.snapshot)

    def history(self):
        with self.lock:
            return {"rows": list(self.history_rows), "actions": list(self.actions),
                    "peakGuardEvents": list(self.peak_guard_events)}

    def get_settings(self):
        with self.lock:
            return deepcopy(self.settings)

    def calibration_status(self):
        profile = deepcopy(self.active_profile)
        return {
            "active": self.calibration_session is not None,
            "session": deepcopy(self.calibration_session),
            "profile": profile,
            "status": (None if self.last_observation is None else
                       self.last_observation.get("profileStatus")),
        }

    def calibration(self, body):
        if self.source.simulated:
            raise ValueError("模拟模式不保存真实设备校准")
        if not isinstance(body, dict) or body.get("action") not in {
                "start", "capture", "finish", "cancel"}:
            raise ValueError("校准 action 必须是 start、capture、finish 或 cancel")
        if set(body) != {"action"}:
            raise ValueError("校准接口只接受 action 字段")
        with self.lock:
            observation = self.last_observation
            if observation is None or not observation.get("captureAvailable"):
                raise ValueError("当前没有可用的系统音频数据")
            if body["action"] == "cancel":
                self.calibration_session = None
                return self.calibration_status()
            if body["action"] == "start":
                if not observation.get("volumeDbMappingReliable"):
                    raise ValueError("当前设备没有可靠的 dB 映射，不能开始校准")
                self.calibration_session = {
                    "deviceId": observation["deviceId"],
                    "deviceName": observation.get("deviceName"),
                    "startedAtMs": observation["timestampMs"],
                    "points": [],
                    "instruction": "播放同一稳定片段；手动设置三个相差明显的音量档位，每档稳定至少 3 秒后记录",
                }
                return self.calibration_status()
            if self.calibration_session is None:
                raise ValueError("请先开始校准")
            if observation["deviceId"] != self.calibration_session["deviceId"]:
                self.calibration_session = None
                raise ValueError("输出设备已切换，校准已取消")
            if body["action"] == "capture":
                point = stable_point(list(self.history_rows), observation["deviceId"])
                if any(abs(item["systemVolumeDb"] - point["systemVolumeDb"]) < 1
                       for item in self.calibration_session["points"]):
                    raise ValueError("该音量档位已经记录，请至少再调整 1 dB")
                self.calibration_session["points"].append(point)
                return self.calibration_status()
            classification = classify_points(self.calibration_session["points"])
            profile = self.profile_store.save(observation, classification)
            self.calibration_session = None
            self.active_profile = profile
            result = self.calibration_status()
            result["classification"] = classification
            return result

    def _apply_preset_rules(self, partial):
        """Expand simple-mode choices into raw settings, or mark hand edits as custom."""
        partial = deepcopy(partial)
        current = self.settings["preset"]
        patch = partial.pop("preset", None)
        if patch is not None:
            if not isinstance(patch, dict):
                raise ValueError("preset 必须是 JSON object")
            unknown = set(patch) - PRESET_KEYS
            if unknown:
                raise ValueError("未知 preset 字段：%s" % ", ".join(sorted(unknown)))
            preset = {**current, **patch}
            if preset["mode"] == "simple":
                partial.update(self.presets.derive(preset))
            else:
                self.presets.validate_preset(preset)
            partial["preset"] = preset
        elif current["mode"] == "simple":
            edited = [key for key in partial
                      if key in DERIVED_KEYS and partial[key] != self.settings[key]]
            if edited:
                partial["preset"] = {**current, "mode": "custom"}
        return partial

    def update_settings(self, partial):
        with self.lock:
            if not isinstance(partial, dict):
                raise ValueError("设置必须是 JSON object")
            partial = self._apply_preset_rules(partial)
            requested = partial.get("mode", self.settings["mode"])
            previous = self.settings["mode"]
            if not self.source.simulated and requested != previous:
                if requested not in MODE_LABELS:
                    raise ValueError("未知模式：%s" % requested)
                if requested in EXECUTING_MODES:
                    problem = self.executor.gate(self.last_observation, requested)
                    if problem:
                        raise ValueError("不能开启%s：%s" % (MODE_LABELS[requested], problem))
            self.settings = self.controller.update_settings(partial)
            write_json_atomic(self.settings_path, self.settings)
            if self.executor is not None and requested != previous:
                timestamp_ms = time.time() * 1000
                if requested in EXECUTING_MODES and previous not in EXECUTING_MODES:
                    self.executor.begin(self.last_observation)
                    self.controller.set_baseline(self.last_observation)
                    self.executor_notice = None
                    self._executor_event(timestamp_ms, "executor-started",
                                         "开启%s，记录当前音量为本次基准" % MODE_LABELS[requested])
                elif requested in EXECUTING_MODES:
                    self._executor_event(timestamp_ms, "executor-mode",
                                         "切换为%s，沿用本次基准" % MODE_LABELS[requested])
                elif previous in EXECUTING_MODES:
                    restored = self.executor.restore("用户关闭%s" % MODE_LABELS[previous])
                    self.executor_notice = None
                    self._executor_event(timestamp_ms, "executor-stopped",
                                         "用户关闭%s" % MODE_LABELS[previous], restored)
            return deepcopy(self.settings)

    def preset_table(self):
        return self.presets.public()

    def capture_comfort(self, body):
        """Use the median output loudness of the last few seconds as comfort level C."""
        if set(body) != {"action"} or body.get("action") != "capture":
            raise ValueError("舒适音量接口只接受 {\"action\": \"capture\"}")
        table = self.presets.table()
        window_ms = float(table["comfort"]["windowSeconds"]) * 1000
        with self.lock:
            rows = list(self.history_rows)
            if not rows:
                raise ValueError("还没有监测数据")
            newest = rows[-1]["timestampMs"]
            levels = sorted(row["effectiveLufs"] for row in rows
                            if newest - row["timestampMs"] <= window_ms
                            and row.get("effectiveLufs") is not None
                            and not row.get("isSilent"))
            needed = int(float(table["comfort"]["minSeconds"]) / self.tick_seconds)
            if not levels:
                observation = self.last_observation or {}
                if observation.get("captureResponse") in {None, "unknown", "unreliable"}:
                    raise ValueError("当前设备还没有有效的校准档案，无法得到输出估算；请先完成设备校准")
                raise ValueError("最近没有可用的播放数据，请先播放一段音量舒适的内容")
            if len(levels) < needed:
                raise ValueError("请先以舒适的音量连续播放至少 %s 秒（当前只有 %.1f 秒有效数据）" % (
                    table["comfort"]["minSeconds"], len(levels) * self.tick_seconds))
            middle = len(levels) // 2
            median_level = (levels[middle] if len(levels) % 2
                            else (levels[middle - 1] + levels[middle]) / 2)
            comfort = round(median_level, 1)
            settings = self.update_settings({"preset": {"comfortLufs": comfort, "mode": "simple"}})
            return {"comfortLufs": comfort, "seconds": round(len(levels) * self.tick_seconds, 2),
                    "settings": settings}

    def set_mode(self, body):
        if set(body) != {"mode"}:
            raise ValueError("mode 接口只接受 mode 字段")
        return self.update_settings({"mode": body["mode"]})

    def volume_test(self, body):
        if self.source.simulated:
            raise ValueError("模拟模式不提供真实音量测试")
        if not isinstance(body, dict) or body.get("action") not in {"lower", "restore"}:
            raise ValueError("音量测试 action 必须是 lower 或 restore")
        if body["action"] == "lower":
            if set(body) - {"action", "stepPercentPoints"}:
                raise ValueError("音量测试包含未知字段")
            step = body.get("stepPercentPoints", 1.0)
            if isinstance(step, bool) or not isinstance(step, (int, float)) or not 0.1 <= step <= 3:
                raise ValueError("stepPercentPoints 必须在 0.1..3 之间")
        elif set(body) != {"action"}:
            raise ValueError("恢复动作只接受 action 字段")
        method = getattr(self.source, "manual_volume_test", None)
        if not callable(method):
            raise ValueError("当前平台不支持人工音量测试")
        with self.lock:
            result = method(body["action"], body.get("stepPercentPoints", 1.0))
            timestamp_ms = time.time() * 1000
            lowered = body["action"] == "lower"
            event = {
                "schemaVersion": "system-audio.action/v1",
                "timestampMs": timestamp_ms,
                "state": "MONITORING",
                "kind": "manual-test-lower" if lowered else "manual-test-restore",
                "reason": "人工触发小幅音量校准" if lowered else "人工触发安全恢复",
                "evidence": {"deviceId": result["deviceId"],
                             "stepPercentPoints": body.get("stepPercentPoints") if lowered else None},
                "beforeVolume": result["beforeVolume"],
                "recommendedVolume": result["appliedVolume"],
                "beforeVolumeDb": None,
                "recommendedVolumeDb": None,
                "recommendedAttenuationDb": None,
                "appliedVolume": result["appliedVolume"],
                "appliedVolumeDb": None,
                "execute": True,
                "mode": "monitor",
                "controllerVersion": "manual-volume-test-m6/v1",
                "settingsUpdatedAt": self.settings["updatedAt"],
            }
            self.actions.appendleft(event)
            if self.snapshot:
                self.snapshot["manualVolumeTestPending"] = bool(
                    getattr(self.source, "volume_test_session", None))
                self.snapshot["volume"]["system"] = round(result["appliedVolume"], 3)
            return deepcopy(event)

    def simulate(self, body):
        if self.simulator is None:
            raise ValueError("真实监控模式不提供模拟动作")
        if not isinstance(body, dict):
            raise ValueError("模拟请求必须是 JSON object")
        action = body.get("action")
        with self.lock:
            if action == "scenario" and set(body) <= {"action", "id", "seconds"}:
                self.simulator.select(body.get("id"), body.get("seconds", 10))
            elif action == "manual-volume" and set(body) == {"action", "volume"}:
                self.simulator.set_manual_volume(body["volume"])
            elif action == "switch-device" and set(body) == {"action"}:
                self.simulator.switch_device()
            else:
                raise ValueError("未知或字段不完整的模拟动作")
            return self.tick()


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, value, content_type="application/json; charset=utf-8"):
        data = value if isinstance(value, bytes) else json.dumps(
            value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                         "style-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def trusted(self):
        port = self.server.server_port
        hosts = {"localhost:%s" % port, "127.0.0.1:%s" % port}
        origins = {"http://%s" % host for host in hosts}
        try:
            local = ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            local = False
        return (local and len(self.headers.get_all("Host", [])) == 1
                and self.headers.get("Host") in hosts
                and len(self.headers.get_all("Origin", [])) <= 1
                and self.headers.get("Origin") in origins | {None}
                and self.headers.get("Sec-Fetch-Site") != "cross-site")

    def do_GET(self):
        if not self.trusted():
            return self.reply(403, {"error": "仅允许本机同源请求"})
        path = urlsplit(self.path).path
        if path == "/":
            try:
                return self.reply(200, UI.read_bytes(), "text/html; charset=utf-8")
            except FileNotFoundError:
                return self.reply(503, {"error": "监控界面尚未安装"})
        routes = {
            "/api/status": self.server.app.status,
            "/api/history": self.server.app.history,
            "/api/settings": self.server.app.get_settings,
            "/api/calibration": self.server.app.calibration_status,
            "/api/presets": self.server.app.preset_table,
        }
        if path in routes:
            return self.reply(200, routes[path]())
        return self.reply(404, {"error": "Not found"})

    def do_POST(self):
        self.close_connection = True
        if not self.trusted():
            return self.reply(403, {"error": "仅允许本机同源请求"})
        if self.headers.get_content_type() != "application/json":
            return self.reply(415, {"error": "必须使用 application/json"})
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
            return self.reply(400, {"error": "需要唯一 Content-Length"})
        try:
            length = int(self.headers["Content-Length"])
            if not 0 < length <= MAX_BODY:
                return self.reply(413, {"error": "请求体上限 64KB"})
            self.connection.settimeout(5)
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("请求体不完整")
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValueError("请求必须是 JSON object")
            path = urlsplit(self.path).path
            routes = {
                "/api/settings": self.server.app.update_settings,
                "/api/mode": self.server.app.set_mode,
                "/api/simulate": self.server.app.simulate,
                "/api/volume-test": self.server.app.volume_test,
                "/api/calibration": self.server.app.calibration,
                "/api/comfort": self.server.app.capture_comfort,
            }
            if path not in routes:
                return self.reply(404, {"error": "Not found"})
            return self.reply(200, routes[path](body))
        except (ValueError, KeyError, TypeError, OSError, RuntimeError, json.JSONDecodeError) as error:
            return self.reply(400, {"error": str(error)})

    def log_message(self, *_args):
        pass


def build_server(app, port):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.app = app
    return server


def serve(source, settings_path, port, banner):
    source = validate_source(source)
    app = AppState(settings_path=settings_path, source=source)
    server = build_server(app, port)
    print("http://127.0.0.1:%s" % port, flush=True)
    print(banner, flush=True)

    def stop_requested(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop_requested)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, stop_requested)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.close()
        server.server_close()
    return 0


def main():
    parser = argparse.ArgumentParser(description="运行跨平台共享服务的模拟入口")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--settings", type=Path)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("--port 必须在 1024..65535 之间")
    return serve(
        Simulator(),
        args.settings or DEFAULT_SETTINGS_PATH,
        args.port,
        "M0-M2 模拟模式：不会读取或修改真实系统音量。",
    )


if __name__ == "__main__":
    raise SystemExit(main())
