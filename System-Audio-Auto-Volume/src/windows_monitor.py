"""Windows WASAPI meter with explicit M6 manual EndpointVolume calibration."""

from __future__ import annotations

from array import array
from copy import deepcopy
import math
import platform as system_platform
import sys
import threading
import time

from loudness_meter import LoudnessMeter, PeakGuard


def default_loopback(audio, api):
    """Match the default render endpoint without unsafe title-only fallback."""
    default_index = audio.get_host_api_info_by_type(api.paWASAPI)["defaultOutputDevice"]
    devices = list(audio.get_device_info_generator_by_host_api(host_api_type=api.paWASAPI))
    outputs = [item for item in devices if item["maxOutputChannels"] > 0]
    loopbacks = [item for item in devices if item.get("isLoopbackDevice")]
    if len(outputs) == len(loopbacks):
        for output, loopback in zip(outputs, loopbacks):
            if (output["index"] == default_index
                    and loopback["name"] == output["name"] + " [Loopback]"):
                return output, loopback
    raise RuntimeError("无法可靠匹配 Windows 默认输出与 loopback；拒绝按设备名猜测")


def dbfs(amplitude):
    return max(-120.0, 20 * math.log10(amplitude)) if amplitude > 0 else -120.0


class PCMWindow:
    def __init__(self, sample_rate=None, channels=None):
        self.squares = 0
        self.samples = 0
        self.peak = 0
        self.frames = 0
        self.callbacks = 0
        self.dropped_frames = 0
        self.max_callback_seconds = 0.0
        self.max_callback_interval_seconds = 0.0
        self.last_callback = None
        self.loudness = (LoudnessMeter(sample_rate, channels)
                         if sample_rate is not None and channels is not None else None)
        self.peak_guard = (PeakGuard(sample_rate, channels)
                           if sample_rate is not None and channels is not None else None)

    def consume(self, data, frame_count, status, callback_seconds, callback_at):
        values = array("h", data)
        if sys.byteorder != "little":
            values.byteswap()
        if self.last_callback is not None:
            self.max_callback_interval_seconds = max(
                self.max_callback_interval_seconds, callback_at - self.last_callback)
        self.last_callback = callback_at
        self.squares += sum(value * value for value in values)
        self.samples += len(values)
        self.peak = max(self.peak, max(map(abs, values), default=0))
        if self.loudness:
            self.loudness.consume(values, scale=1 / 32768)
            self.peak_guard.consume(values, scale=1 / 32768)
        self.frames += frame_count
        self.callbacks += 1
        if status:
            self.dropped_frames += frame_count
        self.max_callback_seconds = max(self.max_callback_seconds, callback_seconds)

    def take(self):
        if not self.samples:
            return None
        rms = math.sqrt(self.squares / self.samples) / 32768
        result = {
            "rmsDbfs": dbfs(rms),
            "peakDbfs": dbfs(self.peak / 32768),
            "frames": self.frames,
            "callbacks": self.callbacks,
            "droppedFrames": self.dropped_frames,
            "maxCallbackSeconds": self.max_callback_seconds,
            "maxCallbackIntervalSeconds": self.max_callback_interval_seconds,
        }
        if self.loudness:
            result.update(self.loudness.snapshot())
            result["peakGuard"] = self.peak_guard.snapshot()
        self.squares = self.samples = self.peak = self.frames = self.callbacks = 0
        self.dropped_frames = 0
        self.max_callback_seconds = self.max_callback_interval_seconds = 0.0
        return result


def load_dependencies():
    if sys.platform != "win32":
        raise RuntimeError("Windows 真实监控只能在 Windows 10/11 运行")
    try:
        import pyaudiowpatch
        sys.coinit_flags = 0  # pycaw callbacks require COM multi-threaded apartment.
        import comtypes
        from pycaw.callbacks import AudioEndpointVolumeCallback, MMNotificationClient
        from pycaw.utils import AudioUtilities
    except ImportError as error:
        raise RuntimeError(
            "缺少 Windows 依赖；请安装 requirements-windows.txt") from error
    return pyaudiowpatch, comtypes, AudioUtilities, AudioEndpointVolumeCallback, MMNotificationClient


class WindowsMonitor:
    platform = "windows"
    simulated = False
    measurement_source = "wasapi-loopback-read-only"

    def __init__(self, dependency_loader=load_dependencies, start_worker=True):
        self.dependency_loader = dependency_loader
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.reconfigure_event = threading.Event()
        self.latest = None
        self.last_device = {"deviceId": "windows-pending", "deviceName": "等待 WASAPI"}
        self.error = None
        self.volume_test_session = None
        self.last_observed_volume = None
        self.last_program_volume = None
        self.last_program_at = 0.0
        self.worker = None
        if start_worker:
            self.worker = threading.Thread(target=self._supervise,
                                           name="windows-audio-monitor", daemon=True)
            self.worker.start()

    def close(self):
        if self.volume_test_session:
            try:
                self.manual_volume_test("restore")
            except RuntimeError:
                pass
        self.stop_event.set()
        self.reconfigure_event.set()
        if self.worker:
            self.worker.join(timeout=3)

    def _supervise(self):
        while not self.stop_event.is_set():
            self.reconfigure_event.clear()
            try:
                self._monitor_default_device()
            except Exception as error:
                with self.lock:
                    self.latest = None
                    self.error = str(error) or type(error).__name__
            self.stop_event.wait(1)

    def _monitor_default_device(self):
        api, comtypes, audio_utilities, volume_callback_base, device_callback_base = (
            self.dependency_loader())
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        audio = enumerator = endpoint = stream = None
        volume_callback = device_callback = None
        meter_lock = threading.Lock()
        volume_state = {"value": None, "db": None, "dbMin": None, "dbMax": None,
                        "dbStep": None, "muted": None, "hardwareSupport": None}
        monitor = self

        class VolumeCallback(volume_callback_base):
            def on_notify(self, new_volume, new_mute, _context, _channels, _channel_volumes):
                with monitor.lock:
                    volume_state["value"] = float(new_volume) * 100
                    volume_state["muted"] = bool(new_mute)

        class DeviceCallback(device_callback_base):
            def on_default_device_changed(self, flow, _flow_id, role, _role_id, _device_id):
                if flow == "eRender" and role in {"eConsole", "eMultimedia"}:
                    monitor.reconfigure_event.set()

            def on_device_removed(self, removed_device_id):
                if removed_device_id == monitor.last_device["deviceId"]:
                    monitor.reconfigure_event.set()

            def on_device_state_changed(self, device_id, new_state, _new_state_id):
                if device_id == monitor.last_device["deviceId"] and new_state != "Active":
                    monitor.reconfigure_event.set()

        try:
            audio = api.PyAudio()
            output, loopback = default_loopback(audio, api)
            device = audio_utilities.GetSpeakers()
            endpoint = device.EndpointVolume
            device_id = str(getattr(device, "id", None) or device.GetId())
            device_name = str(getattr(device, "FriendlyName", None) or output["name"])
            volume_state.update(value=float(endpoint.GetMasterVolumeLevelScalar()) * 100,
                                db=float(endpoint.GetMasterVolumeLevel()),
                                muted=bool(endpoint.GetMute()))
            try:
                db_min, db_max, db_step = endpoint.GetVolumeRange()
                volume_state.update(dbMin=float(db_min), dbMax=float(db_max),
                                    dbStep=float(db_step))
            except Exception:
                volume_state.update(dbMin=None, dbMax=None, dbStep=None)
            try:
                volume_state["hardwareSupport"] = bool(
                    int(endpoint.QueryHardwareSupport()) & 0x1)
            except Exception:
                volume_state["hardwareSupport"] = None
            with self.lock:
                self.last_device = {"deviceId": device_id, "deviceName": device_name}
                self.error = None

            volume_callback = VolumeCallback()
            endpoint.RegisterControlChangeNotify(volume_callback)
            enumerator = audio_utilities.GetDeviceEnumerator()
            device_callback = DeviceCallback()
            enumerator.RegisterEndpointNotificationCallback(device_callback)

            rate = int(loopback["defaultSampleRate"])
            channels = int(loopback["maxInputChannels"])
            meter = PCMWindow(rate, channels)

            def callback(data, frame_count, _time_info, status):
                started = time.perf_counter()
                with meter_lock:
                    meter.consume(data, frame_count, status, 0.0, started)
                    meter.max_callback_seconds = max(
                        meter.max_callback_seconds, time.perf_counter() - started)
                return None, api.paContinue

            stream = audio.open(format=api.paInt16, channels=channels, rate=rate,
                                input=True, input_device_index=int(loopback["index"]),
                                frames_per_buffer=1024, stream_callback=callback, start=False)
            stream.start_stream()
            while not self.stop_event.wait(0.25) and not self.reconfigure_event.is_set():
                if not stream.is_active():
                    raise RuntimeError(
                        "WASAPI loopback 已停止；设备可能断开或被独占模式占用")
                with meter_lock:
                    values = meter.take()
                    last_callback = meter.last_callback
                if last_callback is not None and time.perf_counter() - last_callback > 2:
                    raise RuntimeError(
                        "WASAPI 回调超过 2 秒无数据；请检查设备断开或 exclusive-mode 播放")
                if values is None:
                    continue
                try:
                    volume_state["db"] = float(endpoint.GetMasterVolumeLevel())
                except Exception:
                    volume_state["db"] = None
                db_values = (volume_state["db"], volume_state["dbMin"],
                             volume_state["dbMax"])
                db_reliable = (all(value is not None and math.isfinite(value)
                                   for value in db_values)
                               and volume_state["dbMin"] < volume_state["dbMax"])
                with self.lock:
                    values.update({
                        "timestampMs": time.time() * 1000,
                        "deviceId": device_id,
                        "deviceName": device_name,
                        "systemVolume": volume_state["value"],
                        "systemVolumeDb": volume_state["db"],
                        "volumeDbMin": volume_state["dbMin"],
                        "volumeDbMax": volume_state["dbMax"],
                        "volumeDbStep": volume_state["dbStep"],
                        "outputAttenuationDb": (volume_state["db"] - volume_state["dbMax"]
                                                if db_reliable else None),
                        "volumeDbSource": "windows-endpointvolume" if db_reliable else None,
                        "volumeDbMappingReliable": db_reliable,
                        "volumeHardwareSupport": volume_state["hardwareSupport"],
                        "volumeReadable": volume_state["value"] is not None,
                        "volumeWritableCapability": True,
                        "muted": volume_state["muted"],
                        "sampleRate": rate,
                        "channels": channels,
                        "loopbackDeviceIndex": int(loopback["index"]),
                    })
                    self.latest = values
                    self.error = None
            if self.reconfigure_event.is_set() and not self.stop_event.is_set():
                with self.lock:
                    self.latest = None
                    self.error = "默认输出或设备状态变化，正在重新连接"
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            if endpoint is not None and volume_callback is not None:
                try:
                    endpoint.UnregisterControlChangeNotify(volume_callback)
                except Exception:
                    pass
            if enumerator is not None and device_callback is not None:
                try:
                    enumerator.UnregisterEndpointNotificationCallback(device_callback)
                except Exception:
                    pass
            if audio is not None:
                audio.terminate()
            comtypes.CoUninitialize()

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
            "environmentFingerprint": "windows:%s" % system_platform.version(),
            "deviceTransport": "windows-render-endpoint",
            "systemVolume": None if message is None else message.get("systemVolume"),
            "systemVolumeDb": None if message is None else message.get("systemVolumeDb"),
            "volumeDbMin": None if message is None else message.get("volumeDbMin"),
            "volumeDbMax": None if message is None else message.get("volumeDbMax"),
            "volumeDbStep": None if message is None else message.get("volumeDbStep"),
            "outputAttenuationDb": None if message is None else message.get("outputAttenuationDb"),
            "volumeDbSource": None if message is None else message.get("volumeDbSource"),
            "volumeDbMappingReliable": False if message is None else bool(message.get("volumeDbMappingReliable")),
            "volumeHardwareSupport": None if message is None else message.get("volumeHardwareSupport"),
            "captureResponse": "unknown",
            "shortTermLufs": None if message is None else message.get("shortTermLufs"),
            "momentaryLufs": None if message is None else message.get("momentaryLufs"),
            "rmsDbfs": None if message is None else message.get("rmsDbfs"),
            "peakDbfs": None if message is None else message.get("peakDbfs"),
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

    def _volume_operation(self, target=None, expected_device=None, expected_volume=None):
        _api, comtypes, audio_utilities, _volume_callback, _device_callback = (
            self.dependency_loader())
        comtypes.CoInitialize()
        try:
            device = audio_utilities.GetSpeakers()
            endpoint = device.EndpointVolume
            device_id = str(getattr(device, "id", None) or device.GetId())
            device_name = str(getattr(device, "FriendlyName", None) or device_id)
            current = float(endpoint.GetMasterVolumeLevelScalar()) * 100
            if expected_device is not None and device_id != expected_device:
                raise RuntimeError("输出设备已切换，拒绝恢复测试音量")
            if expected_volume is not None and abs(current - expected_volume) > 0.6:
                raise RuntimeError("测试后音量已被用户修改，拒绝覆盖当前音量")
            if target is not None:
                endpoint.SetMasterVolumeLevelScalar(max(0, min(100, target)) / 100, None)
            actual = float(endpoint.GetMasterVolumeLevelScalar()) * 100
            return {"deviceId": device_id, "deviceName": device_name,
                    "beforeVolume": current, "appliedVolume": actual,
                    "muted": bool(endpoint.GetMute())}
        finally:
            comtypes.CoUninitialize()

    def manual_volume_test(self, action, step=1.0):
        with self.lock:
            if action == "lower":
                if self.volume_test_session:
                    raise RuntimeError("上一次测试音量尚未恢复")
                if not 0.1 <= float(step) <= 3:
                    raise ValueError("测试步长必须在 0.1..3 个百分点")
                current = self._volume_operation()
                result = self._volume_operation(
                    target=max(0, current["beforeVolume"] - float(step)),
                    expected_device=current["deviceId"],
                    expected_volume=current["beforeVolume"])
                self.volume_test_session = {
                    "deviceId": result["deviceId"],
                    "baseline": current["beforeVolume"],
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
                    result = self._volume_operation(
                        target=session["baseline"], expected_device=session["deviceId"],
                        expected_volume=session["written"])
                finally:
                    self.volume_test_session = None
                self.last_program_volume = result["appliedVolume"]
                self.last_program_at = time.monotonic()
                return result
            raise ValueError("未知音量测试动作")
