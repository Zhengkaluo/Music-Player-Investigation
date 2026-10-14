"""Build and supervise the native read-only macOS system-audio meter."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import platform
import shutil
import subprocess
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(__file__).with_suffix(".swift")
PLIST = Path(__file__).with_suffix(".plist")
APP = ROOT / "runtime" / "SystemAudioMonitor.app"
BINARY = APP / "Contents" / "MacOS" / "SystemAudioMonitor"
SCHEMA = "system-audio.native-meter/v1"


def build_helper():
    if platform.system() != "Darwin":
        raise RuntimeError("macOS 真实监控只能在 macOS 14.4 或更高版本运行")
    newest_source = max(SOURCE.stat().st_mtime, PLIST.stat().st_mtime)
    if BINARY.exists() and BINARY.stat().st_mtime >= newest_source:
        return BINARY
    BINARY.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PLIST, APP / "Contents" / "Info.plist")
    cache = ROOT / "runtime" / ".swift-cache"
    subprocess.run(["xcrun", "swiftc", "-swift-version", "5", "-O",
                    "-module-cache-path", str(cache), str(SOURCE), "-o", str(BINARY)],
                   check=True)
    subprocess.run(["codesign", "--force", "--sign", "-", str(APP)],
                   check=True, capture_output=True)
    return BINARY


class MacOSMonitor:
    platform = "macos"
    simulated = False
    measurement_source = "coreaudio-process-tap-read-only"

    def __init__(self, command=None, start_worker=True):
        self.command = list(command) if command else [str(build_helper())]
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.process = None
        self.latest = None
        self.last_device = {"deviceId": "macos-pending", "deviceName": "等待 Core Audio"}
        self.error = None
        self.volume_test_session = None
        self.last_observed_volume = None
        self.last_program_volume = None
        self.last_program_at = 0.0
        self.worker = None
        if start_worker:
            self.worker = threading.Thread(target=self._supervise, name="macos-audio-monitor", daemon=True)
            self.worker.start()

    def close(self):
        if self.volume_test_session:
            try:
                self.manual_volume_test("restore")
            except RuntimeError:
                pass
        self.stop_event.set()
        with self.lock:
            process = self.process
        if process and process.poll() is None:
            try:
                process.stdin.write("stop\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
        if self.worker:
            self.worker.join(timeout=3)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    def _supervise(self):
        while not self.stop_event.is_set():
            process = None
            try:
                process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, text=True, bufsize=1)
                with self.lock:
                    self.process = process
                    self.error = None
                for line in process.stdout:
                    if self.stop_event.is_set():
                        break
                    try:
                        message = json.loads(line)
                        if message.get("schemaVersion") != SCHEMA:
                            raise ValueError("未知原生 meter schema")
                        with self.lock:
                            if message.get("deviceId"):
                                self.last_device = {
                                    "deviceId": message["deviceId"],
                                    "deviceName": message.get("deviceName", message["deviceId"]),
                                }
                            if message.get("event") in {"ready", "meter"}:
                                self.latest = message
                            elif message.get("event") == "device-changed":
                                self.latest = None
                                self.error = "输出设备变化，正在重新连接"
                            elif message.get("event") == "error":
                                self.latest = None
                                self.error = message.get("message", "Core Audio 监控失败")
                    except (ValueError, TypeError, KeyError) as error:
                        with self.lock:
                            self.error = "无法解析原生监控输出：%s" % error
                process.wait(timeout=2)
                if not self.stop_event.is_set() and process.returncode:
                    with self.lock:
                        self.latest = None
                        self.error = self.error or "Core Audio 监控意外退出（%s）" % process.returncode
            except (OSError, subprocess.SubprocessError) as error:
                with self.lock:
                    self.latest = None
                    self.error = str(error)
            finally:
                with self.lock:
                    if self.process is process:
                        self.process = None
            self.stop_event.wait(1)

    def observe(self, timestamp_ms):
        with self.lock:
            message = deepcopy(self.latest)
            device = deepcopy(self.last_device)
            error = self.error
            volume = None if message is None else message.get("systemVolume")
            manual_changed = (volume is not None and self.last_observed_volume is not None
                              and abs(volume - self.last_observed_volume) > 0.05
                              and not (self.last_program_volume is not None
                                       and abs(volume - self.last_program_volume) <= 0.6
                                       and time.monotonic() - self.last_program_at <= 2))
            if volume is not None:
                self.last_observed_volume = volume
        stale = (message is None or
                 float(timestamp_ms) - float(message.get("timestampMs", 0)) > 2000)
        return {
            "timestampMs": float(timestamp_ms),
            "platform": self.platform,
            "deviceId": device["deviceId"],
            "deviceName": device["deviceName"],
            "environmentFingerprint": "macos:%s" % platform.mac_ver()[0],
            "deviceTransport": None if message is None else message.get("deviceTransport"),
            "systemVolume": volume,
            "systemVolumeDb": None if message is None else message.get("systemVolumeDb"),
            "volumeDbMin": None if message is None else message.get("volumeDbMin"),
            "volumeDbMax": None if message is None else message.get("volumeDbMax"),
            "volumeDbStep": None if message is None else message.get("volumeDbStep"),
            "outputAttenuationDb": None if message is None else message.get("outputAttenuationDb"),
            "volumeDbSource": None if message is None else message.get("volumeDbSource"),
            "volumeDbMappingReliable": False if message is None else bool(message.get("volumeDbMappingReliable")),
            "captureResponse": "unknown",
            "shortTermLufs": None if message is None else message.get("shortTermLufs"),
            "momentaryLufs": None if message is None else message.get("momentaryLufs"),
            "rmsDbfs": None if message is None or message.get("event") != "meter" else message.get("rmsDbfs"),
            "peakDbfs": None if message is None or message.get("event") != "meter" else message.get("peakDbfs"),
            "isSilent": message is not None and message.get("rmsDbfs", 0) <= -90,
            "captureAvailable": not stale,
            "volumeControllable": False if message is None else bool(message.get("volumeWritableCapability")),
            "manualVolumeChanged": manual_changed,
            "scenarioId": None,
            "scenarioLabel": "真实系统输出",
            "volumeReadable": False if message is None else bool(message.get("volumeReadable")),
            "volumeWritableCapability": False if message is None else bool(message.get("volumeWritableCapability")),
            "muted": None if message is None else message.get("muted"),
            "sampleRate": None if message is None else message.get("sampleRate"),
            "channels": None if message is None else message.get("channels"),
            "callbacks": None if message is None else message.get("callbacks"),
            "droppedFrames": None if message is None else message.get("droppedFrames"),
            "maxCallbackSeconds": None if message is None else message.get("maxCallbackSeconds"),
            "maxCallbackIntervalSeconds": None if message is None else message.get("maxCallbackIntervalSeconds"),
            "peakGuard": None if message is None else message.get("peakGuard"),
            "error": "等待第一批音频数据" if message is None and error is None else error,
        }

    def _volume_command(self, *arguments):
        result = subprocess.run([self.command[0], *map(str, arguments)], capture_output=True,
                                text=True, timeout=5)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        message = json.loads(lines[-1]) if lines else {}
        if message.get("schemaVersion") != SCHEMA:
            raise RuntimeError("未知 macOS 音量命令响应")
        if result.returncode or message.get("event") == "error":
            raise RuntimeError(message.get("message") or result.stderr.strip()
                               or "macOS 音量命令失败")
        return message

    def recommended_volume(self, target_db):
        result = self._volume_command("--volume-convert-db", target_db)
        return float(result["targetVolume"])

    def manual_volume_test(self, action, step=1.0):
        with self.lock:
            if action == "lower":
                if self.volume_test_session:
                    raise RuntimeError("上一次测试音量尚未恢复")
                result = self._volume_command("--volume-lower", step)
                self.volume_test_session = {
                    "deviceId": result["deviceId"],
                    "baseline": result["beforeVolume"],
                    "written": result["appliedVolume"],
                }
                self.last_program_volume = result["appliedVolume"]
                self.last_program_at = time.monotonic()
                return result
            if action == "restore":
                if not self.volume_test_session:
                    raise RuntimeError("没有待恢复的测试音量")
                session = self.volume_test_session
                try:
                    result = self._volume_command(
                        "--volume-restore", session["baseline"], session["written"],
                        "--device", session["deviceId"])
                finally:
                    self.volume_test_session = None
                self.last_program_volume = result["appliedVolume"]
                self.last_program_at = time.monotonic()
                return result
            raise ValueError("未知音量测试动作")
