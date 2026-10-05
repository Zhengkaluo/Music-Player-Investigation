import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from controller import VolumeController, default_settings, validate_settings
from macos_monitor import MacOSMonitor
from replay import replay
from service import AppState, Simulator, build_server
from source_contract import validate_source
from windows_monitor import PCMWindow, WindowsMonitor, default_loopback


def observation(timestamp_ms, level=-12.0, volume=50.0, **changes):
    value = {
        "timestampMs": timestamp_ms,
        "deviceId": "speakers",
        "systemVolume": volume,
        "shortTermLufs": level,
        "momentaryLufs": level,
        "rmsDbfs": -18.0,
        "peakDbfs": -3.0,
        "isSilent": False,
        "captureAvailable": True,
        "volumeControllable": True,
        "manualVolumeChanged": False,
    }
    value.update(changes)
    return value


def settings(mode, **changes):
    value = default_settings()
    value.update({"mode": mode, "lowerSustainSeconds": 2.0,
                  "recoverySustainSeconds": 2.0})
    value.update(changes)
    return value


class ControllerTests(unittest.TestCase):
    def test_settings_reject_unknown_and_unsafe_ranges(self):
        with self.assertRaisesRegex(ValueError, "未知设置字段"):
            validate_settings({"extra": True})
        with self.assertRaisesRegex(ValueError, "minSystemVolume"):
            validate_settings({"minSystemVolume": 80, "maxSystemVolume": 70})
        with self.assertRaisesRegex(ValueError, "triggerLufs"):
            validate_settings({"triggerLufs": -30})

    def test_monitor_never_recommends_or_executes(self):
        controller = VolumeController(settings("monitor"))
        action = controller.step(observation(0))
        self.assertEqual(action["state"], "MONITORING")
        self.assertEqual(action["kind"], "none")
        self.assertFalse(action["execute"])

    def test_monitor_allows_missing_hardware_volume(self):
        controller = VolumeController(settings("monitor"))
        action = controller.step(observation(0, systemVolume=None, volumeControllable=False))
        self.assertEqual(action["state"], "MONITORING")
        self.assertIsNone(action["beforeVolume"])

    def test_shadow_reports_without_execution(self):
        controller = VolumeController(settings("shadow"))
        controller.step(observation(0))
        action = controller.step(observation(2000))
        self.assertEqual(action["kind"], "would-lower")
        self.assertEqual(action["recommendedVolume"], 47)
        self.assertFalse(action["execute"])

    def test_lower_only_executes_bounded_step(self):
        controller = VolumeController(settings("lower-only", minSystemVolume=49.0))
        controller.step(observation(0))
        action = controller.step(observation(2000))
        self.assertEqual(action["kind"], "lower")
        self.assertEqual(action["recommendedVolume"], 49)
        self.assertTrue(action["execute"])

    def test_silence_and_fade_cannot_recover(self):
        controller = VolumeController(settings("automatic"))
        controller.step(observation(0, level=-19, volume=60))
        silent = observation(1000, level=None, volume=50, isSilent=True, rmsDbfs=-90, peakDbfs=None)
        action = controller.step(silent)
        self.assertEqual(action["kind"], "blocked")
        self.assertIsNone(action["recommendedVolume"])

    def test_automatic_recovery_stops_at_user_baseline(self):
        controller = VolumeController(settings("automatic"))
        controller.step(observation(0, level=-19, volume=60))
        controller.step(observation(1000, level=-27, volume=50))
        action = controller.step(observation(3000, level=-27, volume=50))
        self.assertEqual(action["kind"], "recover")
        self.assertEqual(action["recommendedVolume"], 51)
        self.assertTrue(action["execute"])

    def test_manual_override_and_device_change_block_control(self):
        controller = VolumeController(settings("lower-only", manualOverrideSeconds=30.0))
        controller.step(observation(0))
        manual = controller.step(observation(1000, volume=44, manualVolumeChanged=True))
        self.assertEqual(manual["state"], "USER_OVERRIDE")
        blocked = controller.step(observation(10000, volume=44))
        self.assertEqual(blocked["kind"], "blocked")
        switched = controller.step(observation(40000, volume=42, deviceId="headphones"))
        self.assertEqual(switched["kind"], "device-change")
        self.assertEqual(switched["state"], "RECALIBRATING")

    def test_fixture_and_contract_versions_are_frozen(self):
        scenarios = json.loads((ROOT / "fixtures/scenarios.json").read_text(encoding="utf-8"))
        self.assertEqual(scenarios["schemaVersion"], "system-audio.simulation-scenarios/v1")
        self.assertEqual({item["id"] for item in scenarios["scenarios"]},
                         {"normal", "loud", "quiet", "peak", "fade", "silence"})
        schema = json.loads((ROOT / "contracts/system-audio-contracts-v1.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(schema["$defs"]), {"settings", "state", "action", "nullableLevel"})

    def test_offline_replay_uses_fixture_without_platform_dependencies(self):
        scenarios = json.loads((ROOT / "fixtures/scenarios.json").read_text(encoding="utf-8"))
        rows = replay(scenarios, settings("shadow"), scenario_id="loud", step_seconds=1)
        self.assertGreater(len(rows), 2)
        self.assertTrue(any(row["kind"] == "would-lower" for row in rows))
        self.assertTrue(all(row["scenarioId"] == "loud" for row in rows))


class SourceContractTests(unittest.TestCase):
    def test_simulator_and_platform_source_share_one_contract(self):
        self.assertIsInstance(validate_source(Simulator()), Simulator)
        source = FakeMacSource()
        self.assertIs(validate_source(source), source)

    def test_incomplete_source_is_rejected(self):
        class MissingObserve:
            platform = "macos"
            simulated = False
            measurement_source = "broken"

            def close(self):
                pass

        with self.assertRaisesRegex(TypeError, "AudioSource"):
            validate_source(MissingObserve())

    def test_platform_entry_points_do_not_import_each_other(self):
        macos_entry = (ROOT / "src/run_macos.py").read_text(encoding="utf-8")
        windows_entry = (ROOT / "src/run_windows.py").read_text(encoding="utf-8")
        shared_service = (ROOT / "src/service.py").read_text(encoding="utf-8")
        self.assertNotIn("windows_monitor", macos_entry)
        self.assertNotIn("macos_monitor", windows_entry)
        self.assertNotIn("macos_monitor", shared_service)
        self.assertNotIn("windows_monitor", shared_service)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.folder.name) / "settings.json"
        self.app = AppState(settings_path=self.settings_path, start_worker=False)
        self.server = build_server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%s" % self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.app.close()
        self.thread.join(timeout=2)
        self.folder.cleanup()

    def request(self, path, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {} if data is None else {"Content-Type": "application/json"}
        request = Request(self.base + path, data=data, headers=headers)
        with urlopen(request, timeout=3) as response:
            return response.status, json.load(response)

    def test_status_settings_history_and_simulation_api(self):
        status_code, state = self.request("/api/status")
        self.assertEqual(status_code, 200)
        self.assertTrue(state["simulated"])
        self.assertEqual(state["platform"], "simulator")

        _, changed = self.request("/api/settings", {"mode": "shadow", "triggerLufs": -14})
        self.assertEqual(changed["mode"], "shadow")
        self.assertEqual(changed["triggerLufs"], -14)
        self.assertTrue(self.settings_path.is_file())

        _, simulated = self.request("/api/simulate", {"action": "scenario", "id": "loud", "seconds": 10})
        self.assertEqual(simulated["measurement"]["scenarioId"], "loud")
        _, history = self.request("/api/history")
        self.assertGreaterEqual(len(history["rows"]), 2)

    def test_invalid_settings_are_rejected_and_ui_is_served(self):
        with self.assertRaises(HTTPError) as captured:
            self.request("/api/settings", {"minSystemVolume": 90, "maxSystemVolume": 20})
        self.assertEqual(captured.exception.code, 400)
        with urlopen(self.base + "/", timeout=3) as response:
            html = response.read().decode("utf-8")
        self.assertIn("M0–M2 模拟模式", html)
        self.assertIn("最近控制事件", html)


class FakeMacSource:
    platform = "macos"
    simulated = False
    measurement_source = "coreaudio-process-tap-read-only"

    def observe(self, timestamp_ms):
        return observation(timestamp_ms, level=None, systemVolume=41.0,
                           deviceId="mac-device", deviceName="Mac 扬声器",
                           momentaryLufs=None, rmsDbfs=-24.0, peakDbfs=-8.0,
                           volumeControllable=False, scenarioId=None,
                           scenarioLabel="真实系统输出", volumeReadable=True,
                           volumeWritableCapability=True, muted=False,
                           sampleRate=48000, channels=2, callbacks=10,
                           droppedFrames=0, maxCallbackSeconds=0.001,
                           maxCallbackIntervalSeconds=0.02, error=None)

    def close(self):
        pass


class MacReadOnlyTests(unittest.TestCase):
    def test_real_source_is_exposed_but_control_is_locked(self):
        with tempfile.TemporaryDirectory() as folder:
            app = AppState(settings_path=Path(folder) / "settings.json",
                           source=FakeMacSource(), start_worker=False)
            try:
                state = app.status()
                self.assertFalse(state["simulated"])
                self.assertEqual(state["platform"], "macos")
                self.assertEqual(state["measurement"]["rmsDbfs"], -24)
                self.assertEqual(state["volume"]["system"], 41)
                with self.assertRaisesRegex(ValueError, "固定为 monitor"):
                    app.set_mode({"mode": "shadow"})
                with self.assertRaisesRegex(ValueError, "不提供模拟动作"):
                    app.simulate({"action": "switch-device"})
            finally:
                app.close()

    def test_native_message_maps_to_nullable_lufs_observation(self):
        monitor = MacOSMonitor(command=["unused"], start_worker=False)
        monitor.latest = {
            "schemaVersion": "system-audio.native-meter/v1", "event": "meter",
            "timestampMs": 1000, "deviceId": "built-in", "deviceName": "Mac 扬声器",
            "systemVolume": 35.0, "volumeReadable": True,
            "volumeWritableCapability": True, "muted": False,
            "rmsDbfs": -26.0, "peakDbfs": -7.0, "sampleRate": 48000,
            "channels": 2, "callbacks": 12, "droppedFrames": 0,
            "maxCallbackSeconds": 0.001, "maxCallbackIntervalSeconds": 0.02,
        }
        monitor.last_device = {"deviceId": "built-in", "deviceName": "Mac 扬声器"}
        value = monitor.observe(1500)
        self.assertTrue(value["captureAvailable"])
        self.assertIsNone(value["shortTermLufs"])
        self.assertEqual(value["rmsDbfs"], -26)
        self.assertFalse(value["volumeControllable"])

    def test_swift_helper_contains_no_recording_or_volume_write(self):
        source = (ROOT / "src/macos_monitor.swift").read_text(encoding="utf-8")
        self.assertIn("AudioHardwareCreateProcessTap", source)
        self.assertIn("rmsDbfs", source)
        self.assertNotIn("ExtAudioFile", source)
        self.assertNotIn("AudioObjectSetPropertyData", source)


class WindowsReadOnlyTests(unittest.TestCase):
    def test_default_output_matches_identical_devices_by_wasapi_order(self):
        class Audio:
            def get_host_api_info_by_type(self, _kind):
                return {"defaultOutputDevice": 9}

            def get_device_info_generator_by_host_api(self, **_kwargs):
                return iter([
                    {"index": 8, "name": "Monitor", "maxOutputChannels": 2},
                    {"index": 9, "name": "Monitor", "maxOutputChannels": 2},
                    {"index": 11, "name": "Monitor [Loopback]", "maxOutputChannels": 0,
                     "isLoopbackDevice": True},
                    {"index": 12, "name": "Monitor [Loopback]", "maxOutputChannels": 0,
                     "isLoopbackDevice": True},
                ])

        class API:
            paWASAPI = 13

        output, loopback = default_loopback(Audio(), API())
        self.assertEqual(output["index"], 9)
        self.assertEqual(loopback["index"], 12)

    def test_pcm_window_reports_rms_peak_and_driver_status(self):
        import struct
        meter = PCMWindow()
        data = struct.pack("<4h", 0, 16384, -16384, 32767)
        meter.consume(data, frame_count=2, status=1,
                      callback_seconds=0.002, callback_at=10.0)
        value = meter.take()
        self.assertAlmostEqual(value["peakDbfs"], 0, places=2)
        self.assertLess(value["rmsDbfs"], 0)
        self.assertEqual(value["droppedFrames"], 2)
        self.assertEqual(value["callbacks"], 1)

    def test_windows_message_uses_shared_read_only_contract(self):
        monitor = WindowsMonitor(start_worker=False)
        monitor.latest = {
            "timestampMs": 1000, "deviceId": "endpoint-1", "deviceName": "Speakers",
            "systemVolume": 28.0, "volumeReadable": True,
            "volumeWritableCapability": True, "muted": False,
            "rmsDbfs": -22.0, "peakDbfs": -5.0, "sampleRate": 48000,
            "channels": 2, "callbacks": 11, "droppedFrames": 0,
            "maxCallbackSeconds": 0.001, "maxCallbackIntervalSeconds": 0.03,
        }
        monitor.last_device = {"deviceId": "endpoint-1", "deviceName": "Speakers"}
        value = monitor.observe(1500)
        self.assertTrue(value["captureAvailable"])
        self.assertEqual(value["systemVolume"], 28)
        self.assertEqual(value["rmsDbfs"], -22)
        self.assertFalse(value["volumeControllable"])

    def test_windows_adapter_contains_no_volume_write(self):
        source = (ROOT / "src/windows_monitor.py").read_text(encoding="utf-8")
        self.assertIn("GetMasterVolumeLevelScalar", source)
        self.assertIn("GetMute", source)
        self.assertNotIn("SetMasterVolume", source)
        self.assertNotIn("SetMute", source)


if __name__ == "__main__":
    unittest.main()
