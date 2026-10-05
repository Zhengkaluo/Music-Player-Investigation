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
        self.worker = None
        if start_worker:
            self.worker = threading.Thread(target=self._supervise, name="macos-audio-monitor", daemon=True)
            self.worker.start()

    def close(self):
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
        stale = (message is None or
                 float(timestamp_ms) - float(message.get("timestampMs", 0)) > 2000)
        volume = None if message is None else message.get("systemVolume")
        return {
            "timestampMs": float(timestamp_ms),
            "deviceId": device["deviceId"],
            "deviceName": device["deviceName"],
            "systemVolume": volume,
            "shortTermLufs": None,
            "momentaryLufs": None,
            "rmsDbfs": None if message is None or message.get("event") != "meter" else message.get("rmsDbfs"),
            "peakDbfs": None if message is None or message.get("event") != "meter" else message.get("peakDbfs"),
            "isSilent": message is not None and message.get("rmsDbfs", 0) <= -90,
            "captureAvailable": not stale,
            "volumeControllable": False,
            "manualVolumeChanged": False,
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
            "error": "等待第一批音频数据" if message is None and error is None else error,
        }
