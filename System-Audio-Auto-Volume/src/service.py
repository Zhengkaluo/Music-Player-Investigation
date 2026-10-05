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

from controller import STATE_SCHEMA, VolumeController, default_settings, validate_settings
from source_contract import validate_source


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui" / "index.html"
SCENARIOS = ROOT / "fixtures" / "scenarios.json"
DEFAULT_SETTINGS_PATH = ROOT / "runtime" / "settings.json"
MAX_BODY = 64 * 1024


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

    def select(self, scenario_id, seconds=10):
        if scenario_id not in self.scenarios:
            raise ValueError("未知模拟场景：%s" % scenario_id)
        self.current_id = scenario_id
        self.current_started = time.monotonic()
        self.forced_until = time.monotonic() + max(1.0, min(float(seconds), 60.0))

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

    def close(self):
        pass

    def _advance(self):
        now = time.monotonic()
        if now < self.forced_until:
            return
        current = self.scenarios[self.current_id]
        if now - self.current_started >= float(current["durationSeconds"]):
            index = (self.order.index(self.current_id) + 1) % len(self.order)
            self.current_id = self.order[index]
            self.current_started = now

    def observe(self, timestamp_ms):
        self._advance()
        item = self.scenarios[self.current_id]
        # Small deterministic movement keeps the dashboard visibly alive without randomness.
        wave = math.sin(timestamp_ms / 1800.0) * 0.35
        manual = self.manual_changed
        self.manual_changed = False
        def shifted(name):
            return None if item[name] is None else round(float(item[name]) + wave, 3)
        return {
            "timestampMs": float(timestamp_ms),
            "deviceId": self.device_id,
            "deviceName": self.device_name,
            "systemVolume": round(self.volume, 3),
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
        }


class AppState:
    def __init__(self, settings_path=DEFAULT_SETTINGS_PATH, scenarios_path=SCENARIOS,
                 tick_seconds=0.25, start_worker=True, source=None):
        self.settings_path = Path(settings_path)
        self.tick_seconds = float(tick_seconds)
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.source = validate_source(source or Simulator(scenarios_path))
        self.simulator = self.source if self.source.simulated else None
        self.settings = self._load_settings()
        if not self.source.simulated:
            self.settings["mode"] = "monitor"
        self.controller = VolumeController(self.settings)
        self.history_rows = deque(maxlen=max(4, int(60 / self.tick_seconds)))
        self.actions = deque(maxlen=100)
        self.last_action_event_key = None
        self.snapshot = None
        self.worker = None
        self.tick()
        if start_worker:
            self.worker = threading.Thread(target=self._run, name="audio-state", daemon=True)
            self.worker.start()

    def _load_settings(self):
        if not self.settings_path.exists():
            return default_settings()
        return validate_settings(read_json(self.settings_path))

    def close(self):
        self.stop_event.set()
        if self.worker:
            self.worker.join(timeout=2)
        close = getattr(self.source, "close", None)
        if close:
            close()

    def _run(self):
        while not self.stop_event.wait(self.tick_seconds):
            self.tick()

    def tick(self, timestamp_ms=None):
        with self.lock:
            timestamp_ms = float(timestamp_ms if timestamp_ms is not None else time.time() * 1000)
            observation = self.source.observe(timestamp_ms)
            action = self.controller.step(observation)
            if self.simulator and action["execute"] and action["recommendedVolume"] is not None:
                action["appliedVolume"] = round(self.simulator.apply_volume(action["recommendedVolume"]), 3)
            if action["kind"] == "none":
                self.last_action_event_key = None
            else:
                event_key = (action["kind"], action["reason"], action["state"],
                             action["beforeVolume"], action["recommendedVolume"],
                             action["appliedVolume"])
                if event_key != self.last_action_event_key:
                    self.actions.appendleft(deepcopy(action))
                    self.last_action_event_key = event_key
            volume = observation["systemVolume"]
            if self.simulator:
                volume = self.simulator.volume
            baseline = self.controller.baseline_volume
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
                    "error": observation.get("error"),
                },
                "measurement": {
                    "source": self.source.measurement_source,
                    "scenarioId": observation["scenarioId"],
                    "scenarioLabel": observation["scenarioLabel"],
                    "shortTermLufs": observation["shortTermLufs"],
                    "momentaryLufs": observation["momentaryLufs"],
                    "rmsDbfs": observation["rmsDbfs"],
                    "peakDbfs": observation["peakDbfs"],
                    "isSilent": observation["isSilent"],
                    "sampleRate": observation.get("sampleRate"),
                    "channels": observation.get("channels"),
                    "callbacks": observation.get("callbacks"),
                    "droppedFrames": observation.get("droppedFrames"),
                    "maxCallbackSeconds": observation.get("maxCallbackSeconds"),
                    "maxCallbackIntervalSeconds": observation.get("maxCallbackIntervalSeconds"),
                },
                "volume": {
                    "system": round(volume, 3) if volume is not None else None,
                    "baseline": round(baseline, 3) if baseline is not None else None,
                    "correctionPercentPoints": round(volume - baseline, 3)
                    if volume is not None and baseline is not None else None,
                },
                "controller": {
                    "state": action["state"],
                    "lastAction": deepcopy(action),
                },
                "settings": deepcopy(self.settings),
            }
            self.history_rows.append({
                "timestampMs": timestamp_ms,
                "shortTermLufs": observation["shortTermLufs"],
                "momentaryLufs": observation["momentaryLufs"],
                "systemVolume": round(volume, 3) if volume is not None else None,
                "rmsDbfs": observation["rmsDbfs"],
                "peakDbfs": observation["peakDbfs"],
                "state": action["state"],
                "action": action["kind"],
            })
            return deepcopy(self.snapshot)

    def status(self):
        with self.lock:
            return deepcopy(self.snapshot)

    def history(self):
        with self.lock:
            return {"rows": list(self.history_rows), "actions": list(self.actions)}

    def get_settings(self):
        with self.lock:
            return deepcopy(self.settings)

    def update_settings(self, partial):
        with self.lock:
            if not self.source.simulated and partial.get("mode", "monitor") != "monitor":
                raise ValueError("真实监控固定为 monitor，不允许自动控制")
            self.settings = self.controller.update_settings(partial)
            write_json_atomic(self.settings_path, self.settings)
            return deepcopy(self.settings)

    def set_mode(self, body):
        if set(body) != {"mode"}:
            raise ValueError("mode 接口只接受 mode 字段")
        return self.update_settings({"mode": body["mode"]})

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
            }
            if path not in routes:
                return self.reply(404, {"error": "Not found"})
            return self.reply(200, routes[path](body))
        except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
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
