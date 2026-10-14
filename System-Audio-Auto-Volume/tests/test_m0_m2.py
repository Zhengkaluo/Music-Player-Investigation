import json
import math
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from controller import (VolumeController, classify_capture_response, default_settings,
                        effective_output_lufs, validate_observation, validate_settings)
from device_profiles import DeviceProfileStore, classify_points, stable_point
from loudness_meter import LoudnessMeter, PeakGuard, k_weighting_coefficients
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
        "systemVolumeDb": -20.0,
        "volumeDbMin": -60.0,
        "volumeDbMax": 0.0,
        "volumeDbStep": 0.1,
        "outputAttenuationDb": -20.0,
        "volumeDbSource": "test-db",
        "volumeDbMappingReliable": True,
        "captureResponse": "post-volume",
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
    def test_m8_feedback_classification_and_effective_loudness(self):
        post = classify_capture_response(-18, -21.1, -3)
        self.assertEqual(post["captureResponse"], "post-volume")
        pre = classify_capture_response(-18, -18.2, -3)
        self.assertEqual(pre["captureResponse"], "pre-volume")
        bad = classify_capture_response(-18, -25, -3)
        self.assertEqual(bad["captureResponse"], "unreliable")
        self.assertEqual(effective_output_lufs(-14, "pre-volume", -9), -23)
        self.assertEqual(effective_output_lufs(-14, "post-volume"), -14)
        self.assertIsNone(effective_output_lufs(-14, "unknown"))

    def test_m8_db_mapping_contract_uses_attenuation_from_device_maximum(self):
        value = validate_observation(observation(
            0, systemVolumeDb=-18.5, volumeDbMin=-96.0, volumeDbMax=0.0,
            volumeDbStep=0.5, outputAttenuationDb=-18.5,
            volumeDbSource="endpoint", volumeDbMappingReliable=True))
        self.assertEqual(value["outputAttenuationDb"], -18.5)
        with self.assertRaisesRegex(ValueError, "不一致"):
            validate_observation(observation(
                0, systemVolumeDb=-18.5, volumeDbMin=-96.0, volumeDbMax=0.0,
                outputAttenuationDb=-10.0, volumeDbSource="endpoint",
                volumeDbMappingReliable=True))

    def test_real_control_requires_calibrated_output_loudness(self):
        controller = VolumeController(settings("lower-only"))
        action = controller.step(observation(0, captureResponse="unknown"))
        self.assertEqual(action["kind"], "blocked")
        self.assertEqual(action["state"], "UNSUPPORTED")

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
        self.assertEqual(action["recommendedVolumeDb"], -22)
        self.assertEqual(action["recommendedAttenuationDb"], -2)
        self.assertIsNone(action["recommendedVolume"])
        self.assertFalse(action["execute"])

    def test_m8_window_allows_one_brief_dip(self):
        controller = VolumeController(settings(
            "shadow", lowerSustainSeconds=3.0, sustainRatio=0.75))
        controller.step(observation(0, level=-12))
        controller.step(observation(1000, level=-12))
        controller.step(observation(2000, level=-18))
        action = controller.step(observation(3000, level=-12))
        self.assertEqual(action["kind"], "would-lower")
        self.assertEqual(action["evidence"]["windowRatio"], 0.75)

    def test_m8_hysteresis_continues_below_trigger_until_target_high(self):
        controller = VolumeController(settings(
            "shadow", lowerSustainSeconds=1.0, sustainRatio=1.0))
        controller.step(observation(0, level=-12))
        self.assertEqual(controller.step(observation(1000, level=-12))["kind"],
                         "would-lower")
        controller.step(observation(2000, level=-16))
        self.assertEqual(controller.step(observation(3000, level=-16))["kind"],
                         "would-lower")
        self.assertEqual(controller.step(observation(4000, level=-17))["kind"], "none")

    def test_lower_only_executes_bounded_step(self):
        controller = VolumeController(settings("lower-only"))
        controller.step(observation(0))
        action = controller.step(observation(2000))
        self.assertEqual(action["kind"], "lower")
        self.assertEqual(action["recommendedVolumeDb"], -22)
        self.assertTrue(action["execute"])

    def test_silence_and_fade_cannot_recover(self):
        controller = VolumeController(settings("automatic"))
        controller.step(observation(0, level=-19, volume=60))
        silent = observation(1000, level=None, volume=50, isSilent=True, rmsDbfs=-90, peakDbfs=None)
        action = controller.step(silent)
        self.assertEqual(action["kind"], "blocked")
        self.assertIsNone(action["recommendedVolume"])
        self.assertIn("系统静音", action["reason"])

    def test_silence_gate_reason_includes_measured_values(self):
        controller = VolumeController(settings("shadow", silenceGateDbfs=-30))
        action = controller.step(observation(0, rmsDbfs=-31))
        self.assertEqual(action["kind"], "blocked")
        self.assertIn("-31.0 dBFS", action["reason"])
        self.assertIn("-30.0 dBFS", action["reason"])

    def test_shadow_explains_when_effective_loudness_is_below_target(self):
        controller = VolumeController(settings("shadow"))
        action = controller.step(observation(0, level=-27))
        self.assertEqual(action["kind"], "none")
        self.assertIn("不生成升高建议", action["reason"])

    def test_shadow_explains_hysteresis_gap_before_trigger(self):
        controller = VolumeController(settings("shadow"))
        action = controller.step(observation(0, level=-16))
        self.assertEqual(action["kind"], "none")
        self.assertIn("尚未达到降低触发线", action["reason"])

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
        self.assertEqual(set(schema["$defs"]),
                         {"settings", "state", "action", "peakGuardEvent", "nullableLevel"})

    def test_offline_replay_uses_fixture_without_platform_dependencies(self):
        scenarios = json.loads((ROOT / "fixtures/scenarios.json").read_text(encoding="utf-8"))
        rows = replay(scenarios, settings("shadow"), scenario_id="loud", step_seconds=1)
        self.assertGreater(len(rows), 2)
        self.assertTrue(any(row["kind"] == "would-lower" for row in rows))
        self.assertTrue(all(row["scenarioId"] == "loud" for row in rows))


class LoudnessMeterTests(unittest.TestCase):
    @staticmethod
    def tone(sample_rate, seconds, amplitude):
        return [sample for frame in range(round(sample_rate * seconds))
                for sample in [math.sin(2 * math.pi * 1000 * frame / sample_rate) * amplitude] * 2]

    def test_48khz_coefficients_match_bs1770_tables(self):
        shelf, high_pass = k_weighting_coefficients(48000)
        expected_shelf = (1.53512485958697, -2.69169618940638, 1.19839281085285,
                          -1.69065929318241, 0.73248077421585)
        expected_high_pass = (1, -2, 1, -1.99004745483398, 0.99007225036621)
        for actual, expected in zip(shelf, expected_shelf):
            self.assertAlmostEqual(actual, expected, places=12)
        for actual, expected in zip(high_pass, expected_high_pass):
            self.assertAlmostEqual(actual, expected, places=12)

    def test_windows_are_warmed_up_before_lufs_is_reported(self):
        meter = LoudnessMeter(8000, 2)
        meter.consume(self.tone(8000, 0.3, 0.1))
        self.assertIsNone(meter.snapshot()["momentaryLufs"])
        meter.consume(self.tone(8000, 0.1, 0.1))
        self.assertIsNotNone(meter.snapshot()["momentaryLufs"])
        self.assertIsNone(meter.snapshot()["shortTermLufs"])
        meter.consume(self.tone(8000, 2.6, 0.1))
        self.assertIsNotNone(meter.snapshot()["shortTermLufs"])

    def test_doubling_amplitude_adds_six_lu(self):
        quiet = LoudnessMeter(8000, 2)
        loud = LoudnessMeter(8000, 2)
        quiet.consume(self.tone(8000, 3, 0.1))
        loud.consume(self.tone(8000, 3, 0.2))
        difference = loud.snapshot()["shortTermLufs"] - quiet.snapshot()["shortTermLufs"]
        self.assertAlmostEqual(difference, 6.0206, places=3)


class DeviceProfileTests(unittest.TestCase):
    def test_three_level_classification_covers_pre_post_and_unreliable(self):
        def points(levels):
            return [{"systemVolume": 25 + index * 25,
                     "systemVolumeDb": db, "shortTermLufs": level,
                     "sampleCount": 12, "windowSeconds": 3}
                    for index, (db, level) in enumerate(zip((-30, -20, -10), levels))]

        self.assertEqual(classify_points(points((-20, -20.2, -19.9)))["captureResponse"],
                         "pre-volume")
        self.assertEqual(classify_points(points((-40, -30, -20)))["captureResponse"],
                         "post-volume")
        self.assertEqual(classify_points(points((-25, -34, -21)))["captureResponse"],
                         "unreliable")

    def test_profile_invalidates_when_environment_or_db_range_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            store = DeviceProfileStore(Path(folder) / "profiles.json")
            observed = observation(0, platform="macos", deviceId="speaker",
                                   deviceName="Speaker", environmentFingerprint="macos:test")
            profile = store.save(observed, {
                "captureResponse": "pre-volume", "confidence": "high",
                "evidenceSummary": {"method": "test"},
            })
            self.assertEqual(profile["captureResponse"], "pre-volume")
            self.assertEqual(store.match(observed)[1], "valid")
            self.assertEqual(store.match({**observed, "volumeDbMin": -70})[1],
                             "db-range-changed")
            self.assertEqual(store.match({**observed, "environmentFingerprint": "macos:new"})[1],
                             "environment-changed")

    def test_stable_point_uses_recent_medians_and_rejects_volume_changes(self):
        rows = [{"timestampMs": index * 1000, "deviceId": "speaker",
                 "systemVolume": 50, "systemVolumeDb": -20 + index * 0.01,
                 "shortTermLufs": -18 + index * 0.1, "isSilent": False}
                for index in range(4)]
        value = stable_point(rows, "speaker")
        self.assertEqual(value["sampleCount"], 4)
        with self.assertRaisesRegex(ValueError, "音量发生变化"):
            stable_point(rows + [{**rows[-1], "timestampMs": 4000,
                                  "systemVolumeDb": -18}], "speaker")


class PeakGuardTests(unittest.TestCase):
    @staticmethod
    def feed(meter, seconds, amplitude):
        samples = LoudnessMeterTests.tone(8000, seconds, amplitude)
        meter.consume(samples)
        return samples

    def test_sustained_full_scale_burst_records_shadow_suggestion(self):
        meter = PeakGuard(8000, 2)
        self.feed(meter, 1, 0.05)
        burst = self.feed(meter, 0.03, 1.0)
        value = meter.snapshot()
        self.assertEqual(value["triggerCount"], 1)
        self.assertEqual(value["state"], "HOLD")
        self.assertLess(value["suggestedAttenuationDb"], 0)
        self.assertFalse(value["execute"])
        self.assertIsNone(value["truePeakDbtp"])
        self.assertEqual(burst, LoudnessMeterTests.tone(8000, 0.03, 1.0))

    def test_single_ten_millisecond_peak_is_ignored(self):
        meter = PeakGuard(8000, 2)
        self.feed(meter, 1, 0.05)
        self.feed(meter, 0.01, 1.0)
        self.assertEqual(meter.snapshot()["triggerCount"], 0)

    def test_first_second_is_baseline_warmup(self):
        meter = PeakGuard(8000, 2)
        self.feed(meter, 0.5, 1.0)
        value = meter.snapshot()
        self.assertFalse(value["warmedUp"])
        self.assertEqual(value["triggerCount"], 0)

    def test_hold_and_release_return_to_armed_without_execution(self):
        meter = PeakGuard(8000, 2)
        self.feed(meter, 1, 0.05)
        self.feed(meter, 0.03, 1.0)
        self.feed(meter, 2.6, 0.05)
        value = meter.snapshot()
        self.assertEqual(value["state"], "ARMED")
        self.assertEqual(value["suggestedAttenuationDb"], 0)
        self.assertFalse(value["execute"])


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
        _, peak = self.request("/api/simulate", {"action": "scenario", "id": "peak", "seconds": 10})
        self.assertEqual(peak["measurement"]["peakGuard"]["triggerCount"], 1)
        self.assertFalse(peak["measurement"]["peakGuard"]["execute"])
        _, history = self.request("/api/history")
        self.assertGreaterEqual(len(history["rows"]), 2)
        self.assertEqual(history["peakGuardEvents"][0]["schemaVersion"],
                         "system-audio.peak-guard-event/v1")
        self.assertFalse(history["peakGuardEvents"][0]["execute"])

    def test_invalid_settings_are_rejected_and_ui_is_served(self):
        with self.assertRaises(HTTPError) as captured:
            self.request("/api/settings", {"minSystemVolume": 90, "maxSystemVolume": 20})
        self.assertEqual(captured.exception.code, 400)
        with urlopen(self.base + "/", timeout=3) as response:
            html = response.read().decode("utf-8")
        self.assertIn("M0–M2 模拟模式", html)
        self.assertIn("最近建议与控制事件", html)
        self.assertIn("输出估算（控制依据）", html)
        self.assertIn("row.effectiveLufs", html)
        self.assertIn("按最近 15 秒生成起始参数", html)


class FakeMacSource:
    platform = "macos"
    simulated = False
    measurement_source = "coreaudio-process-tap-read-only"

    def __init__(self):
        self.volume = 41.0
        self.volume_test_session = None

    def observe(self, timestamp_ms):
        return observation(timestamp_ms, level=None, systemVolume=self.volume,
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

    def manual_volume_test(self, action, step=1.0):
        before = self.volume
        if action == "lower":
            self.volume_test_session = {"baseline": before, "written": before - step}
            self.volume -= step
        elif action == "restore":
            self.volume = self.volume_test_session["baseline"]
            self.volume_test_session = None
        return {"deviceId": "mac-device", "beforeVolume": before,
                "appliedVolume": self.volume}


class FakeShadowSource(FakeMacSource):
    def __init__(self):
        super().__init__()
        self.silent = False

    def observe(self, timestamp_ms):
        value = super().observe(timestamp_ms)
        value.update(shortTermLufs=-12.0, momentaryLufs=-11.5,
                     rmsDbfs=-16.0, peakDbfs=-2.0,
                     isSilent=self.silent, volumeControllable=True)
        return value


class FakeCalibrationSource(FakeShadowSource):
    def __init__(self):
        super().__init__()
        self.db = -30.0

    def observe(self, timestamp_ms):
        value = super().observe(timestamp_ms)
        value.update(platform="macos", environmentFingerprint="macos:test",
                     systemVolumeDb=self.db, volumeDbMin=-60.0, volumeDbMax=0.0,
                     volumeDbStep=None, outputAttenuationDb=self.db,
                     volumeDbSource="test-db", volumeDbMappingReliable=True,
                     shortTermLufs=-20.0, momentaryLufs=-20.0)
        return value


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
                self.assertEqual(app.set_mode({"mode": "shadow"})["mode"], "shadow")
                with self.assertRaisesRegex(ValueError, "自动控制尚未开放"):
                    app.set_mode({"mode": "lower-only"})
                with self.assertRaisesRegex(ValueError, "不提供模拟动作"):
                    app.simulate({"action": "switch-device"})
            finally:
                app.close()

    def test_real_shadow_recommends_and_persists_without_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            source = FakeShadowSource()
            path = Path(folder) / "settings.json"
            app = AppState(settings_path=path, source=source, start_worker=False)
            try:
                app.profile_store.save(app.last_observation, {
                    "captureResponse": "post-volume", "confidence": "high",
                    "evidenceSummary": {"method": "test"},
                })
                app.update_settings({"mode": "shadow", "lowerSustainSeconds": 0.25,
                                     "maxLowerDbPerSecond": 12.0})
                started = app.status()["timestampMs"] + 100
                app.tick(started)
                state = app.tick(started + 250)
                action = state["controller"]["lastAction"]
                self.assertEqual(action["kind"], "would-lower")
                self.assertFalse(action["execute"])
                self.assertEqual(state["volume"]["system"], 41)
                self.assertEqual(state["volume"]["recommendedDb"], -23.0)
                self.assertIsNone(state["volume"]["recommended"])
                self.assertEqual(source.volume, 41)
                log = path.with_name("macos-shadow-events.jsonl").read_text(encoding="utf-8")
                self.assertIn('"kind": "would-lower"', log)
                source_level = -14.0
                original_observe = source.observe
                source.observe = lambda timestamp: {
                    **original_observe(timestamp),
                    "shortTermLufs": source_level,
                    "momentaryLufs": source_level,
                }
                app.tick(started + 500)
                app.tick(started + 750)
                grouped = app.history()["actions"][0]
                self.assertEqual(grouped["eventWindow"]["occurrences"], 2)
                self.assertEqual(grouped["eventWindow"]["durationSeconds"], 0.5)
                self.assertEqual(grouped["eventWindow"]["recommendedVolumeDbMin"], -23.0)
                self.assertEqual(grouped["eventWindow"]["recommendedVolumeDbMax"], -22.1)
                self.assertEqual(grouped["recommendedVolumeDb"], -22.1)
                log = path.with_name("macos-shadow-events.jsonl").read_text(encoding="utf-8")
                self.assertEqual(len(log.splitlines()), 1)
                app.tick(started + 31000)
                app.tick(started + 31250)
                self.assertEqual(len(app.history()["actions"]), 2)
                log = path.with_name("macos-shadow-events.jsonl").read_text(encoding="utf-8")
                self.assertEqual(len(log.splitlines()), 2)
                source.silent = True
                blocked = app.tick(started + 31500)["controller"]["lastAction"]
                self.assertEqual(blocked["kind"], "blocked")
                self.assertIsNone(blocked["recommendedVolume"])
            finally:
                app.close()

    def test_guided_calibration_saves_pre_volume_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            source = FakeCalibrationSource()
            app = AppState(settings_path=Path(folder) / "settings.json",
                           source=source, start_worker=False)
            try:
                base = app.status()["timestampMs"]
                app.calibration({"action": "start"})
                for point_index, db in enumerate((-30.0, -20.0, -10.0)):
                    source.db = db
                    source.volume = 25 + point_index * 25
                    start = base + point_index * 6000
                    for sample in range(21):
                        app.tick(start + sample * 250)
                    captured = app.calibration({"action": "capture"})
                    self.assertEqual(len(captured["session"]["points"]), point_index + 1)
                result = app.calibration({"action": "finish"})
                self.assertEqual(result["classification"]["captureResponse"], "pre-volume")
                app.tick(base + 19000)
                self.assertEqual(app.status()["measurement"]["captureResponse"], "pre-volume")
                self.assertEqual(app.status()["device"]["profileStatus"], "valid")
            finally:
                app.close()

    def test_manual_volume_api_is_explicit_and_reversible(self):
        with tempfile.TemporaryDirectory() as folder:
            source = FakeMacSource()
            app = AppState(settings_path=Path(folder) / "settings.json",
                           source=source, start_worker=False)
            try:
                lowered = app.volume_test({"action": "lower", "stepPercentPoints": 1})
                self.assertEqual(lowered["kind"], "manual-test-lower")
                self.assertEqual(lowered["beforeVolume"], 41)
                self.assertEqual(lowered["appliedVolume"], 40)
                self.assertTrue(app.status()["manualVolumeTestPending"])
                restored = app.volume_test({"action": "restore"})
                self.assertEqual(restored["kind"], "manual-test-restore")
                self.assertEqual(restored["appliedVolume"], 41)
                self.assertFalse(app.status()["manualVolumeTestPending"])
            finally:
                app.close()

    def test_native_message_maps_to_nullable_lufs_observation(self):
        monitor = MacOSMonitor(command=["unused"], start_worker=False)
        monitor.latest = {
            "schemaVersion": "system-audio.native-meter/v1", "event": "meter",
            "timestampMs": 1000, "deviceId": "built-in", "deviceName": "Mac 扬声器",
            "systemVolume": 35.0, "volumeReadable": True,
            "systemVolumeDb": -20.5, "volumeDbMin": -96.0, "volumeDbMax": 0.0,
            "volumeDbStep": None, "outputAttenuationDb": -20.5,
            "volumeDbSource": "coreaudio-volume-decibels",
            "volumeDbMappingReliable": True,
            "volumeWritableCapability": True, "muted": False,
            "momentaryLufs": -20.0, "shortTermLufs": -21.0,
            "rmsDbfs": -26.0, "peakDbfs": -7.0, "sampleRate": 48000,
            "channels": 2, "callbacks": 12, "droppedFrames": 0,
            "maxCallbackSeconds": 0.001, "maxCallbackIntervalSeconds": 0.02,
            "peakGuard": {"mode": "shadow", "state": "ARMED",
                          "suggestedAttenuationDb": 0, "triggerCount": 0,
                          "lastTrigger": None, "execute": False},
        }
        monitor.last_device = {"deviceId": "built-in", "deviceName": "Mac 扬声器"}
        value = monitor.observe(1500)
        self.assertTrue(value["captureAvailable"])
        self.assertEqual(value["shortTermLufs"], -21)
        self.assertEqual(value["momentaryLufs"], -20)
        self.assertEqual(value["rmsDbfs"], -26)
        self.assertEqual(value["outputAttenuationDb"], -20.5)
        self.assertTrue(value["volumeDbMappingReliable"])
        self.assertEqual(value["peakGuard"]["state"], "ARMED")
        self.assertTrue(value["volumeControllable"])
        monitor.latest["systemVolume"] = 36
        self.assertTrue(monitor.observe(1600)["manualVolumeChanged"])
        monitor.last_program_volume = 37
        monitor.last_program_at = time.monotonic()
        monitor.latest["systemVolume"] = 37
        self.assertFalse(monitor.observe(1700)["manualVolumeChanged"])

    def test_swift_helper_limits_writes_to_manual_calibration_command(self):
        source = (ROOT / "src/macos_monitor.swift").read_text(encoding="utf-8")
        self.assertIn("AudioHardwareCreateProcessTap", source)
        self.assertIn("rmsDbfs", source)
        self.assertIn("momentaryLufs", source)
        self.assertIn("kAudioDevicePropertyVolumeRangeDecibels", source)
        self.assertIn("kAudioDevicePropertyVolumeScalarToDecibels", source)
        self.assertIn("kAudioDevicePropertyVolumeDecibelsToScalar", source)
        self.assertIn("--volume-convert-db", source)
        self.assertNotIn("ExtAudioFile", source)
        self.assertEqual(source.count("AudioObjectSetPropertyData"), 1)
        self.assertIn("--volume-lower", source)
        self.assertIn("refusing restore", source)


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

    def test_pcm_window_reports_calibrated_loudness(self):
        from array import array
        rate = 8000
        samples = LoudnessMeterTests.tone(rate, 3, 0.1)
        pcm = array("h", (round(value * 32767) for value in samples))
        meter = PCMWindow(rate, 2)
        meter.consume(pcm.tobytes(), frame_count=rate * 3, status=0,
                      callback_seconds=0.01, callback_at=10.0)
        value = meter.take()
        self.assertIsNotNone(value["momentaryLufs"])
        self.assertIsNotNone(value["shortTermLufs"])

    def test_windows_message_uses_shared_read_only_contract(self):
        monitor = WindowsMonitor(start_worker=False)
        monitor.latest = {
            "timestampMs": 1000, "deviceId": "endpoint-1", "deviceName": "Speakers",
            "systemVolume": 28.0, "volumeReadable": True,
            "systemVolumeDb": -18.5,
            "volumeDbMin": -96.0, "volumeDbMax": 0.0, "volumeDbStep": 0.5,
            "outputAttenuationDb": -18.5,
            "volumeDbSource": "windows-endpointvolume",
            "volumeDbMappingReliable": True,
            "volumeWritableCapability": True, "muted": False,
            "momentaryLufs": -18.0, "shortTermLufs": -19.0,
            "rmsDbfs": -22.0, "peakDbfs": -5.0, "sampleRate": 48000,
            "channels": 2, "callbacks": 11, "droppedFrames": 0,
            "maxCallbackSeconds": 0.001, "maxCallbackIntervalSeconds": 0.03,
            "peakGuard": {"mode": "shadow", "state": "ARMED",
                          "suggestedAttenuationDb": 0, "triggerCount": 0,
                          "lastTrigger": None, "execute": False},
        }
        monitor.last_device = {"deviceId": "endpoint-1", "deviceName": "Speakers"}
        value = monitor.observe(1500)
        self.assertTrue(value["captureAvailable"])
        self.assertEqual(value["systemVolume"], 28)
        self.assertEqual(value["systemVolumeDb"], -18.5)
        self.assertEqual(value["volumeDbMin"], -96)
        self.assertEqual(value["outputAttenuationDb"], -18.5)
        self.assertTrue(value["volumeDbMappingReliable"])
        self.assertEqual(value["shortTermLufs"], -19)
        self.assertEqual(value["rmsDbfs"], -22)
        self.assertEqual(value["peakGuard"]["state"], "ARMED")
        self.assertTrue(value["volumeControllable"])
        monitor.latest["systemVolume"] = 27
        self.assertTrue(monitor.observe(1600)["manualVolumeChanged"])
        monitor.last_program_volume = 26
        monitor.last_program_at = time.monotonic()
        monitor.latest["systemVolume"] = 26
        self.assertFalse(monitor.observe(1700)["manualVolumeChanged"])

    def test_manual_windows_restore_refuses_user_override(self):
        class COM:
            @staticmethod
            def CoInitialize(): pass
            @staticmethod
            def CoUninitialize(): pass

        class Endpoint:
            volume = 0.5
            def GetMasterVolumeLevelScalar(self): return self.volume
            def SetMasterVolumeLevelScalar(self, value, _context): self.volume = value
            def GetMute(self): return False

        endpoint = Endpoint()

        class Device:
            id = "endpoint-1"
            FriendlyName = "Speakers"
            EndpointVolume = endpoint

        class Utilities:
            @staticmethod
            def GetSpeakers(): return Device()

        loader = lambda: (None, COM, Utilities, None, None)
        monitor = WindowsMonitor(dependency_loader=loader, start_worker=False)
        lowered = monitor.manual_volume_test("lower", 1)
        self.assertAlmostEqual(lowered["appliedVolume"], 49)
        endpoint.volume = 0.6
        with self.assertRaisesRegex(RuntimeError, "用户修改"):
            monitor.manual_volume_test("restore")
        self.assertAlmostEqual(endpoint.volume, 0.6)

    def test_windows_adapter_contains_only_manual_volume_write(self):
        source = (ROOT / "src/windows_monitor.py").read_text(encoding="utf-8")
        self.assertIn("GetMasterVolumeLevelScalar", source)
        self.assertIn("GetVolumeRange", source)
        self.assertIn("QueryHardwareSupport", source)
        self.assertIn("GetMute", source)
        self.assertEqual(source.count("SetMasterVolumeLevelScalar"), 1)
        self.assertNotIn("SetMute", source)


if __name__ == "__main__":
    unittest.main()
