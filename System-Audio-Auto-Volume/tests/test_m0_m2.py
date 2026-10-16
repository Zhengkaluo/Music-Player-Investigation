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
from windows_monitor import PCMWindow, VolumeCurve, WindowsMonitor, default_loopback


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
            "lower-only", lowerSustainSeconds=1.0, sustainRatio=1.0))
        controller.step(observation(0, level=-12))
        self.assertEqual(controller.step(observation(1000, level=-12))["kind"],
                         "lower")
        controller.step(observation(2000, level=-16))
        self.assertEqual(controller.step(observation(3000, level=-16))["kind"],
                         "lower")
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
        controller = VolumeController(settings("shadow", recoveryCooldownSeconds=0))
        action = controller.step(observation(0, level=-27))
        self.assertEqual(action["kind"], "none")
        self.assertIn("低于目标区间", action["reason"])

    def test_shadow_explains_hysteresis_gap_before_trigger(self):
        controller = VolumeController(settings("shadow"))
        action = controller.step(observation(0, level=-16))
        self.assertEqual(action["kind"], "none")
        self.assertIn("尚未达到降低触发线", action["reason"])

    # --- M9 v2 recovery: debt repaid per song, bounded by the loud part -------------
    # Targets are -21..-17 (trigger -15); with pre-volume capture the effective output
    # loudness is source + endpoint dB, so a source of 2 at -20 dB is -18 LUFS.
    LOUD, NORMAL, QUIET = 8.0, 2.0, -10.0

    @staticmethod
    def pre_obs(timestamp, source, db):
        silent = source is None
        return observation(timestamp, level=None if silent else source, systemVolumeDb=db,
                           outputAttenuationDb=db, captureResponse="pre-volume",
                           isSilent=silent, momentaryLufs=None if silent else source,
                           rmsDbfs=-120.0 if silent else -18.0,
                           peakDbfs=None if silent else -3.0)

    def drive(self, controller, segments, db=-20.0, start=0, feed=True):
        rows, now = [], start
        for source, seconds in segments:
            for index in range(int(seconds * 4)):
                level = source(index / 4) if callable(source) else source
                action = controller.step(self.pre_obs(now, level, db))
                if feed and action["execute"] and action["recommendedVolumeDb"] is not None:
                    db = action["recommendedVolumeDb"]
                rows.append((now, action, db))
                now += 250
        return rows, db, now

    def recovery_settings(self, mode="automatic", **changes):
        return settings(mode, recoverySustainSeconds=20.0, **changes)

    def test_lowered_song_holds_then_repays_after_song_gap(self):
        controller = VolumeController(self.recovery_settings())
        rows, db, now = self.drive(controller, [(self.LOUD, 20), (self.NORMAL, 60)])
        self.assertAlmostEqual(db, -25.0, delta=0.3)
        lowered = db
        self.assertIn("保持到换歌", rows[-1][1]["reason"])
        self.assertFalse(any(action["kind"] == "recover" for _t, action, _db in rows))
        rows, db, _now = self.drive(controller, [(None, 2), (self.NORMAL, 40)], db, now)
        recovers = [action for _t, action, _db in rows if action["kind"] == "recover"]
        self.assertTrue(recovers)
        self.assertTrue(all(action["recommendedAttenuationDb"] > 0 for action in recovers))
        self.assertAlmostEqual(db, -20.0, places=2)
        self.assertLessEqual(max(value for _t, _a, value in rows), -20.0 + 1e-9)

    def test_repay_stops_where_the_loud_part_would_get_loud_again(self):
        controller = VolumeController(self.recovery_settings())
        _rows, db, now = self.drive(controller, [(self.LOUD, 20), (self.NORMAL, 10)])
        # Next song: loud part 5 -> full repay would give -15 LUFS; limit is -18.
        rows, db, _now = self.drive(controller, [(None, 2), (5.0, 40)], db, now)
        self.assertAlmostEqual(db, -23.0, delta=0.3)
        self.assertLessEqual(db, -23.0 + 1e-9)
        self.assertIn("响部", rows[-1][1]["reason"])

    def test_fade_out_never_triggers_recovery(self):
        controller = VolumeController(self.recovery_settings())
        _rows, db, now = self.drive(controller, [(self.LOUD, 20), (self.NORMAL, 10)])
        rows, after, _now = self.drive(
            controller, [(None, 2), (lambda second: self.NORMAL - second, 20)], db, now)
        self.assertEqual(after, db)
        self.assertFalse(any(action["kind"] == "recover" for _t, action, _db in rows))
        self.assertTrue(any("淡出" in action["reason"] for _t, action, _db in rows))

    def test_hold_max_repays_without_song_gap(self):
        controller = VolumeController(self.recovery_settings(songHoldMaxSeconds=30.0))
        rows, db, _now = self.drive(controller, [(self.LOUD, 20), (self.NORMAL, 70)])
        self.assertAlmostEqual(db, -20.0, places=2)
        self.assertTrue(any(action["kind"] == "recover" for _t, action, _db in rows))

    def test_recovery_never_raises_above_baseline_without_debt(self):
        controller = VolumeController(self.recovery_settings())
        rows, db, _now = self.drive(controller, [(self.QUIET, 60)])
        self.assertEqual(db, -20.0)
        self.assertTrue(all(action["recommendedVolumeDb"] is None for _t, action, _db in rows))
        self.assertIn("不会升到", rows[-1][1]["reason"])

    def test_lower_only_never_repays(self):
        controller = VolumeController(self.recovery_settings("lower-only"))
        _rows, db, now = self.drive(controller, [(self.LOUD, 20), (self.NORMAL, 10)])
        rows, after, _now = self.drive(controller, [(None, 2), (self.NORMAL, 40)], db, now)
        self.assertEqual(after, db)
        self.assertLess(db, -24.0)
        self.assertFalse(any(action["kind"] == "recover" for _t, action, _db in rows))

    def test_shadow_simulates_lowering_and_repayment_without_writing(self):
        controller = VolumeController(self.recovery_settings("shadow"))
        rows, db, now = self.drive(controller, [(self.LOUD, 20), (self.NORMAL, 10)], feed=False)
        self.assertEqual(db, -20.0)
        offsets = [action["evidence"]["shadowOffsetDb"] for _t, action, _db in rows]
        self.assertAlmostEqual(min(offsets), -5.0, delta=0.3)
        self.assertTrue(any(action["kind"] == "would-lower" for _t, action, _db in rows))
        rows, db, _now = self.drive(controller, [(None, 2), (self.NORMAL, 40)], db, now,
                                    feed=False)
        self.assertTrue(any(action["kind"] == "would-recover" for _t, action, _db in rows))
        self.assertFalse(any(action["execute"] for _t, action, _db in rows))
        self.assertEqual(rows[-1][1]["evidence"]["shadowOffsetDb"], 0.0)

    def test_short_silence_inside_a_song_keeps_the_hold(self):
        controller = VolumeController(self.recovery_settings())
        _rows, db, now = self.drive(controller, [(self.LOUD, 20), (self.NORMAL, 10)])
        rows, after, _now = self.drive(
            controller, [(None, 1), (self.NORMAL, 30)], db, now)
        self.assertEqual(after, db)
        self.assertIn("保持到换歌", rows[-1][1]["reason"])

    def test_diagnostics_report_lower_and_raise_progress(self):
        controller = VolumeController(self.recovery_settings(lowerSustainSeconds=3.0,
                                                             sustainRatio=0.8))
        # Loud but evidence window not yet full: lower side is "approaching".
        controller.step(self.pre_obs(0, self.LOUD, -20.0))
        controller.step(self.pre_obs(250, self.LOUD, -20.0))
        diag = controller.diagnostics
        self.assertTrue(diag["lower"]["above"])
        self.assertLess(diag["lower"]["windowSeconds"], diag["lower"]["requiredSeconds"])
        self.assertEqual(diag["raise"]["debtDb"], 0.0)
        # Drive through lowering, then a quiet tail: raise side holds for the song.
        _rows, db, now = self.drive(controller, [(self.LOUD, 20), (self.NORMAL, 10)], start=500)
        self.assertGreater(controller.diagnostics["raise"]["debtDb"], 0)
        self.assertTrue(controller.diagnostics["raise"]["songLowered"])
        self.assertIsNotNone(controller.diagnostics["raise"]["holdLeftSeconds"])

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
        self.assertIn("就用现在的音量", html)
        self.assertIn("高级设置", html)
        self.assertIn("恢复简易推荐", html)


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
                with self.assertRaisesRegex(ValueError, "尚未提供自动音量写入"):
                    app.set_mode({"mode": "lower-only"})
                with self.assertRaisesRegex(ValueError, "尚未提供自动音量写入"):
                    app.set_mode({"mode": "automatic"})
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
                self.assertEqual(state["controller"]["shadowOffsetDb"], -3.0)
                app.tick(started + 500)
                app.tick(started + 750)
                grouped = app.history()["actions"][0]
                self.assertEqual(grouped["eventWindow"]["occurrences"], 2)
                self.assertEqual(grouped["eventWindow"]["durationSeconds"], 0.5)
                # Shadow simulates its own suggestions: the second step starts from the
                # virtual -23 dB and the virtual loudness (-15) is closer to the target.
                self.assertEqual(grouped["eventWindow"]["recommendedVolumeDbMax"], -23.0)
                self.assertEqual(grouped["eventWindow"]["recommendedVolumeDbMin"], -24.4)
                self.assertEqual(grouped["recommendedVolumeDb"], -24.4)
                self.assertEqual(source.volume, 41)
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
        monitor, endpoint = fake_windows_monitor()
        lowered = monitor.manual_volume_test("lower", 1)
        self.assertAlmostEqual(lowered["appliedVolume"], 49)
        endpoint.volume = 0.6
        with self.assertRaisesRegex(RuntimeError, "用户修改"):
            monitor.manual_volume_test("restore")
        self.assertAlmostEqual(endpoint.volume, 0.6)

    def test_windows_volume_calls_use_multithreaded_com(self):
        monitor, _endpoint = fake_windows_monitor()
        monitor.manual_volume_test("lower", 1)
        self.assertEqual(FakeCOM.modes, [FakeCOM.COINIT_MULTITHREADED] * 2)

    def test_apply_volume_db_only_lowers_and_reads_back(self):
        monitor, endpoint = fake_windows_monitor()
        endpoint.set_db(-20.0)
        result = monitor.apply_volume_db(-22.0, "endpoint-1", -20.0, floor_percent=10)
        self.assertAlmostEqual(result["beforeVolumeDb"], -20.0)
        self.assertAlmostEqual(result["appliedVolumeDb"], -22.0)
        self.assertLess(result["appliedVolume"], result["beforeVolume"])
        with self.assertRaisesRegex(ValueError, "只允许降低"):
            monitor.apply_volume_db(-21.0, "endpoint-1", -22.0)
        with self.assertRaisesRegex(RuntimeError, "设备已切换"):
            monitor.apply_volume_db(-23.0, "other", -22.0)
        endpoint.set_db(-15.0)
        with self.assertRaisesRegex(RuntimeError, "不一致"):
            monitor.apply_volume_db(-23.0, "endpoint-1", -22.0)
        endpoint.set_db(-20.0)
        floored = monitor.apply_volume_db(-59.0, "endpoint-1", -20.0, floor_percent=30)
        self.assertTrue(floored["floored"])
        self.assertAlmostEqual(floored["appliedVolume"], 30, places=3)

    def test_idle_loopback_is_silence_not_failure(self):
        meter = PCMWindow(8000, 2)
        from array import array
        pcm = array("h", (round(v * 32767) for v in LoudnessMeterTests.tone(8000, 3, 0.1)))
        meter.consume(pcm.tobytes(), frame_count=8000 * 3, status=0,
                      callback_seconds=0.0, callback_at=1.0)
        self.assertIsNotNone(meter.take()["shortTermLufs"])
        idle = meter.idle_summary("endpoint-silent")
        self.assertTrue(idle["captureIdle"])
        self.assertIsNone(idle["shortTermLufs"])
        self.assertEqual(meter.loudness.snapshot()["loudnessBlocks"], 0)
        monitor = WindowsMonitor(start_worker=False)
        monitor.latest = {**idle, "timestampMs": 1000, "systemVolume": 30.0,
                          "volumeReadable": True, "volumeWritableCapability": True}
        monitor.last_device = {"deviceId": "endpoint-1", "deviceName": "Speakers"}
        value = monitor.observe(1200)
        self.assertTrue(value["captureAvailable"])
        self.assertTrue(value["isSilent"])
        self.assertTrue(value["captureIdle"])
        source = (ROOT / "src/windows_monitor.py").read_text(encoding="utf-8")
        self.assertIn("GetPeakValue", source)
        self.assertNotIn("回调超过 2 秒无数据", source)

    def test_volume_curve_converts_only_inside_measured_points(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "curve.json"
            curve = VolumeCurve(path)
            curve.add("dev", 50.0, -10.0)
            curve.add("dev", 45.0, -11.5)
            self.assertAlmostEqual(curve.percent_for_db("dev", -10.75, -65, 0), 47.5)
            self.assertIsNone(curve.percent_for_db("dev", -30.0, -65, 0))
            curve.save()
            reloaded = VolumeCurve(path)
            self.assertAlmostEqual(reloaded.percent_for_db("dev", -11.5, -65, 0), 45.0)
            curve.add("dev", 40.0, -9.0)
            self.assertIsNone(curve.percent_for_db("dev", -10.0, -65, 0))

    def test_windows_adapter_writes_only_through_two_audited_methods(self):
        source = (ROOT / "src/windows_monitor.py").read_text(encoding="utf-8")
        self.assertIn("GetMasterVolumeLevelScalar", source)
        self.assertIn("GetVolumeRange", source)
        self.assertIn("QueryHardwareSupport", source)
        self.assertIn("GetMute", source)
        self.assertEqual(source.count(".SetMasterVolumeLevelScalar("), 1)
        self.assertEqual(source.count(".SetMasterVolumeLevel("), 1)
        self.assertNotIn("SetMute", source)
        self.assertNotIn("CoInitialize()", source)


class FakeCOM:
    COINIT_MULTITHREADED = 0
    modes = []

    @classmethod
    def CoInitializeEx(cls, mode):
        cls.modes.append(mode)

    @staticmethod
    def CoUninitialize():
        pass


class FakeEndpoint:
    """Linear 0..100 % ↔ -60..0 dB endpoint."""

    def __init__(self, volume=0.5):
        self.volume = volume

    def set_db(self, db):
        self.volume = (db + 60) / 60

    def GetMasterVolumeLevelScalar(self):
        return self.volume

    def GetMasterVolumeLevel(self):
        return self.volume * 60 - 60

    def SetMasterVolumeLevelScalar(self, value, _context):
        self.volume = value

    def SetMasterVolumeLevel(self, db, _context):
        self.set_db(max(-60.0, min(0.0, db)))

    def GetVolumeRange(self):
        return (-60.0, 0.0, 0.5)

    def GetMute(self):
        return False


def fake_windows_monitor(volume=0.5):
    FakeCOM.modes = []
    endpoint = FakeEndpoint(volume)

    class Device:
        id = "endpoint-1"
        FriendlyName = "Speakers"
        EndpointVolume = endpoint

    class Utilities:
        @staticmethod
        def GetSpeakers():
            return Device()

    loader = lambda: (None, FakeCOM, Utilities, None, None)
    return WindowsMonitor(dependency_loader=loader, start_worker=False), endpoint


class FakeWritableSource:
    """Windows-like source with a linear endpoint and the M8b write interface."""

    platform = "windows"
    simulated = False
    measurement_source = "test-writable"

    def __init__(self, volume=0.9, level=-12.0):
        self.endpoint = FakeEndpoint(volume)
        self.level = level
        self.silent = False
        self.user_changed = False
        self.fail_with = None
        self.writes = []
        self.volume_test_session = None

    def observe(self, timestamp_ms):
        manual, self.user_changed = self.user_changed, False
        db = self.endpoint.GetMasterVolumeLevel()
        level = None if self.silent else self.level
        return observation(
            timestamp_ms, level=level, volume=self.endpoint.volume * 100,
            deviceId="endpoint-1", deviceName="Speakers", platform="windows",
            environmentFingerprint="windows:test", systemVolumeDb=db,
            volumeDbMin=-60.0, volumeDbMax=0.0, volumeDbStep=0.5,
            outputAttenuationDb=db, volumeDbSource="test-db",
            volumeDbMappingReliable=True, captureResponse="unknown",
            manualVolumeChanged=manual, momentaryLufs=level, isSilent=self.silent,
            rmsDbfs=-120.0 if self.silent else -16.0,
            peakDbfs=None if self.silent else -2.0, scenarioId=None, scenarioLabel="test")

    def close(self):
        pass

    def apply_volume_db(self, target_db, expected_device, expected_db, floor_percent=0.0):
        if self.fail_with:
            raise self.fail_with
        before, before_db = self.endpoint.volume * 100, self.endpoint.GetMasterVolumeLevel()
        if expected_device != "endpoint-1":
            raise RuntimeError("输出设备已切换")
        if abs(before_db - expected_db) > 0.6:
            raise RuntimeError("当前音量与决策时不一致")
        if target_db >= before_db - 0.01:
            raise ValueError("自动执行只允许降低音量")
        self.endpoint.SetMasterVolumeLevel(target_db, None)
        floored = self.endpoint.volume * 100 < floor_percent
        if floored:
            self.endpoint.volume = floor_percent / 100
        self.writes.append((before_db, self.endpoint.GetMasterVolumeLevel()))
        return {"deviceId": "endpoint-1", "beforeVolume": before, "beforeVolumeDb": before_db,
                "appliedVolume": self.endpoint.volume * 100,
                "appliedVolumeDb": self.endpoint.GetMasterVolumeLevel(), "floored": floored}

    def restore_volume(self, target_percent, expected_device, expected_percent):
        current = self.endpoint.volume * 100
        if abs(current - expected_percent) > 0.6:
            raise RuntimeError("音量已被用户修改，拒绝覆盖当前音量")
        self.endpoint.volume = target_percent / 100
        return {"deviceId": "endpoint-1", "beforeVolume": current,
                "appliedVolume": target_percent,
                "appliedVolumeDb": self.endpoint.GetMasterVolumeLevel()}


class FakeRaisingSource(FakeWritableSource):
    """Adds the M9 recovery write; the base class intentionally omits it."""

    def raise_volume_db(self, target_db, expected_device, expected_db, ceiling_percent):
        if self.fail_with:
            raise self.fail_with
        before, before_db = self.endpoint.volume * 100, self.endpoint.GetMasterVolumeLevel()
        if expected_device != "endpoint-1":
            raise RuntimeError("输出设备已切换")
        if abs(before_db - expected_db) > 0.6:
            raise RuntimeError("当前音量与决策时不一致")
        if target_db <= before_db + 0.01:
            raise ValueError("回升写入只允许升高音量")
        self.endpoint.SetMasterVolumeLevel(target_db, None)
        capped = self.endpoint.volume * 100 > ceiling_percent
        if capped:
            self.endpoint.volume = ceiling_percent / 100
        self.writes.append((before_db, self.endpoint.GetMasterVolumeLevel()))
        return {"deviceId": "endpoint-1", "beforeVolume": before, "beforeVolumeDb": before_db,
                "appliedVolume": self.endpoint.volume * 100,
                "appliedVolumeDb": self.endpoint.GetMasterVolumeLevel(), "capped": capped}


class SimplePresetTests(unittest.TestCase):
    TABLE = ROOT / "config" / "simple-presets.json"

    def test_default_settings_match_standard_preset(self):
        from presets import PresetTable, default_preset
        derived = PresetTable(self.TABLE).derive(default_preset())
        defaults = default_settings()
        self.assertEqual(defaults["preset"], default_preset())
        for key, value in derived.items():
            self.assertEqual(defaults[key], value, key)
        self.assertEqual(defaults["minSystemVolume"], 5.0)

    def test_every_preset_combination_produces_valid_settings(self):
        from presets import SENSITIVITIES, SPEEDS, PresetTable
        table = PresetTable(self.TABLE)
        limits = table.table()["comfort"]
        for comfort in (limits["min"], -40.0, limits["max"]):
            for sensitivity in SENSITIVITIES:
                for speed in SPEEDS:
                    preset = {"mode": "simple", "comfortLufs": comfort, "sensitivity": sensitivity,
                              "speed": speed, "maxReductionDb": 12.0}
                    merged = {**default_settings(), **table.derive(preset), "preset": preset}
                    value = validate_settings(merged)
                    self.assertGreaterEqual(value["triggerLufs"], value["targetLufs"]["high"])

    def test_table_rejects_trigger_below_target_high(self):
        from presets import validate_table
        table = json.loads(self.TABLE.read_text(encoding="utf-8"))
        table["sensitivity"]["high"]["triggerOffset"] = 0
        with self.assertRaisesRegex(ValueError, "triggerOffset"):
            validate_table(table)

    def make_app(self, folder, source=None):
        return AppState(settings_path=Path(folder) / "settings.json", source=source,
                        start_worker=False)

    def test_simple_choices_derive_raw_and_advanced_edit_marks_custom(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self.make_app(folder)
            try:
                value = app.update_settings({"preset": {"comfortLufs": -30.0, "sensitivity": "high",
                                                        "speed": "gentle", "maxReductionDb": 8}})
                self.assertEqual(value["preset"]["mode"], "simple")
                self.assertEqual(value["triggerLufs"], -28.0)
                self.assertEqual(value["targetLufs"], {"low": -33.0, "high": -29.0})
                self.assertEqual(value["lowerSustainSeconds"], 1.5)
                self.assertEqual(value["lowerGain"], 0.4)
                self.assertEqual(value["maxLowerDbPerSecond"], 1.0)
                self.assertEqual(value["maxAutoAttenuationDb"], 8.0)
                unchanged = app.update_settings({"triggerLufs": -28.0, "mode": "shadow"})
                self.assertEqual(unchanged["preset"]["mode"], "simple")
                custom = app.update_settings({"triggerLufs": -25.0})
                self.assertEqual(custom["preset"]["mode"], "custom")
                self.assertEqual(custom["triggerLufs"], -25.0)
                self.assertEqual(custom["preset"]["comfortLufs"], -30.0)
                restored = app.update_settings({"preset": {"mode": "simple"}})
                self.assertEqual(restored["preset"]["mode"], "simple")
                self.assertEqual(restored["triggerLufs"], -28.0)
                with self.assertRaisesRegex(ValueError, "灵敏度"):
                    app.update_settings({"preset": {"sensitivity": "extreme"}})
                with self.assertRaisesRegex(ValueError, "最多压低"):
                    app.update_settings({"preset": {"maxReductionDb": 30}})
                saved = json.loads(app.settings_path.read_text(encoding="utf-8"))
                self.assertEqual(saved["preset"]["mode"], "simple")
            finally:
                app.close()

    def test_comfort_capture_uses_recent_median_output_loudness(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self.make_app(folder)
            try:
                base = app.status()["timestampMs"]
                app.history_rows.clear()
                for index in range(40):
                    app.history_rows.append({"timestampMs": base + index * 250,
                                             "effectiveLufs": -40.0 + (index % 3),
                                             "isSilent": False})
                result = app.capture_comfort({"action": "capture"})
                self.assertEqual(result["comfortLufs"], -39.0)
                self.assertEqual(result["settings"]["targetLufs"]["high"], -38.0)
                self.assertEqual(result["settings"]["triggerLufs"], -36.0)
                app.history_rows.clear()
                app.history_rows.append({"timestampMs": base, "effectiveLufs": -40.0,
                                         "isSilent": False})
                with self.assertRaisesRegex(ValueError, "至少 5 秒"):
                    app.capture_comfort({"action": "capture"})
            finally:
                app.close()

    def test_legacy_settings_file_becomes_custom_and_keeps_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            legacy = default_settings()
            del legacy["preset"]
            legacy.update(triggerLufs=-40.0, targetLufs={"low": -47.0, "high": -43.0},
                          minSystemVolume=20.0)
            path.write_text(json.dumps(legacy), encoding="utf-8")
            app = AppState(settings_path=path, start_worker=False)
            try:
                value = app.get_settings()
                self.assertEqual(value["preset"]["mode"], "custom")
                self.assertEqual(value["preset"]["comfortLufs"], -44.0)
                self.assertEqual(value["triggerLufs"], -40.0)
                self.assertEqual(value["minSystemVolume"], 20.0)
                restored = app.update_settings({"preset": {"mode": "simple"}})
                self.assertEqual(restored["triggerLufs"], -41.0)
                self.assertEqual(restored["minSystemVolume"], 5.0)
            finally:
                app.close()

    def test_min_lower_step_ends_lowering_instead_of_micro_steps(self):
        controller = VolumeController(settings("lower-only", lowerSustainSeconds=1.0,
                                               sustainRatio=1.0, minLowerStepDb=0.5))
        controller.step(observation(0, level=-12))
        self.assertEqual(controller.step(observation(1000, level=-12))["kind"], "lower")
        for timestamp in (1250, 1500, 1750):
            controller.step(observation(timestamp, level=-16.5))
        action = controller.step(observation(2000, level=-16.5))
        self.assertEqual(action["kind"], "none")
        self.assertIn("最小下降步长", action["reason"])
        self.assertFalse(controller.lowering_active)


class LowerOnlyExecutorTests(unittest.TestCase):
    def make_app(self, folder, source):
        app = AppState(settings_path=Path(folder) / "settings.json", source=source,
                       start_worker=False)
        app.update_settings({"triggerLufs": -20.0, "targetLufs": {"low": -30.0, "high": -25.0},
                             "lowerSustainSeconds": 0.5, "maxLowerDbPerSecond": 2.0,
                             "maxAutoAttenuationDb": 6.0})
        return app

    def calibrate(self, app):
        app.profile_store.save(app.last_observation, {
            "captureResponse": "pre-volume", "confidence": "high",
            "evidenceSummary": {"method": "test"}})

    def run_ticks(self, app, start, count):
        for index in range(count):
            app.tick(start + index * 250)
        return start + count * 250

    def test_gate_requires_calibrated_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self.make_app(folder, FakeWritableSource())
            try:
                with self.assertRaisesRegex(ValueError, "三档校准"):
                    app.set_mode({"mode": "lower-only"})
                with self.assertRaisesRegex(ValueError, "自动回升写入"):
                    app.set_mode({"mode": "automatic"})
            finally:
                app.close()

    def test_lowers_with_rate_limit_and_session_cap_then_restores_on_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            source = FakeWritableSource(volume=0.9)
            app = self.make_app(folder, source)
            self.calibrate(app)
            start = app.status()["timestampMs"] + 250
            app.tick(start)
            self.assertEqual(app.set_mode({"mode": "lower-only"})["mode"], "lower-only")
            self.run_ticks(app, start + 250, 60)
            self.assertTrue(source.writes)
            for before, after in source.writes:
                self.assertLess(after, before)
                self.assertLessEqual(before - after, 0.5 + 1e-6)
            final_db = source.endpoint.GetMasterVolumeLevel()
            self.assertAlmostEqual(final_db, -12.0, places=3)
            state = app.status()
            self.assertEqual(state["settings"]["mode"], "lower-only")
            self.assertIn("最多压低", state["controller"]["lastAction"]["reason"])
            history = app.history()["actions"]
            self.assertTrue(any(item["kind"] == "lower" and item["appliedVolume"] is not None
                                for item in history))
            log = Path(folder, "windows-executor-events.jsonl").read_text(encoding="utf-8")
            self.assertIn('"status": "applied"', log)
            app.close()
            self.assertAlmostEqual(source.endpoint.volume * 100, 90.0, places=3)

    def test_user_override_ends_session_and_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            source = FakeWritableSource(volume=0.9)
            app = self.make_app(folder, source)
            self.calibrate(app)
            start = app.status()["timestampMs"] + 250
            app.tick(start)
            app.set_mode({"mode": "lower-only"})
            now = self.run_ticks(app, start + 250, 8)
            self.assertTrue(source.writes)
            source.endpoint.volume = 0.95
            source.user_changed = True
            writes = len(source.writes)
            now = self.run_ticks(app, now, 20)
            self.assertEqual(len(source.writes), writes)
            self.assertEqual(app.status()["controller"]["state"], "USER_OVERRIDE")
            app.set_mode({"mode": "shadow"})
            self.assertAlmostEqual(source.endpoint.volume, 0.95)
            app.close()
            self.assertAlmostEqual(source.endpoint.volume, 0.95)

    def test_restore_refused_when_volume_moved_and_platform_failure_disables(self):
        with tempfile.TemporaryDirectory() as folder:
            source = FakeWritableSource(volume=0.9)
            app = self.make_app(folder, source)
            self.calibrate(app)
            start = app.status()["timestampMs"] + 250
            app.tick(start)
            app.set_mode({"mode": "lower-only"})
            now = self.run_ticks(app, start + 250, 8)
            source.endpoint.volume = 0.5  # moved by someone else, not yet observed
            app.set_mode({"mode": "shadow"})
            self.assertAlmostEqual(source.endpoint.volume, 0.5)
            source.endpoint.volume = 0.9
            app.tick(now)
            app.set_mode({"mode": "lower-only"})
            source.fail_with = OSError("COM failure")
            self.run_ticks(app, now + 250, 8)
            state = app.status()
            self.assertEqual(state["settings"]["mode"], "shadow")
            self.assertIn("写入失败", state["executor"]["notice"])
            app.close()

    def test_startup_never_resumes_lower_only(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            saved = default_settings()
            saved["mode"] = "lower-only"
            path.write_text(json.dumps(saved), encoding="utf-8")
            app = AppState(settings_path=path, source=FakeWritableSource(), start_worker=False)
            try:
                self.assertEqual(app.status()["settings"]["mode"], "shadow")
                self.assertIn("不会自动恢复", app.status()["executor"]["notice"])
            finally:
                app.close()


class AutomaticRecoveryTests(unittest.TestCase):
    def make_app(self, folder, source, **overrides):
        app = AppState(settings_path=Path(folder) / "settings.json", source=source,
                       start_worker=False)
        app.profile_store.save(app.last_observation, {
            "captureResponse": "pre-volume", "confidence": "high",
            "evidenceSummary": {"method": "test"}})
        settings = {"triggerLufs": -20.0, "targetLufs": {"low": -30.0, "high": -25.0},
                    "lowerSustainSeconds": 0.5, "maxLowerDbPerSecond": 2.0,
                    "maxAutoAttenuationDb": 20.0, "recoverySustainSeconds": 0.5,
                    "maxRaiseDbPerSecond": 2.0, "recoveryCooldownSeconds": 0}
        settings.update(overrides)
        app.update_settings(settings)
        return app

    def run_ticks(self, app, start, count, **changes):
        source = app.source
        source.level = changes.get("level", source.level)
        source.silent = changes.get("silent", False)
        for index in range(count):
            app.tick(start + index * 250)
        return start + count * 250

    def test_automatic_mode_requires_raise_capability(self):
        with tempfile.TemporaryDirectory() as folder:
            app = self.make_app(folder, FakeWritableSource(volume=0.5))
            try:
                with self.assertRaisesRegex(ValueError, "自动回升写入"):
                    app.set_mode({"mode": "automatic"})
            finally:
                app.close()

    def test_muted_device_is_never_written(self):
        with tempfile.TemporaryDirectory() as folder:
            source = FakeRaisingSource(volume=0.6, level=5.0)
            original = source.observe
            source.observe = lambda timestamp: {**original(timestamp), "muted": True}
            app = self.make_app(folder, source)
            try:
                start = app.status()["timestampMs"] + 250
                app.tick(start)
                app.set_mode({"mode": "automatic"})
                self.run_ticks(app, start + 250, 24, level=5.0)
                self.assertFalse(source.writes)
                self.assertIn("静音", app.status()["executor"]["lastResult"]["reason"])
            finally:
                app.close()

    def test_recovery_raises_toward_baseline_but_never_above(self):
        with tempfile.TemporaryDirectory() as folder:
            source = FakeRaisingSource(volume=0.6, level=5.0)
            app = self.make_app(folder, source)
            try:
                start = app.status()["timestampMs"] + 250
                app.tick(start)
                self.assertEqual(app.set_mode({"mode": "automatic"})["mode"], "automatic")
                baseline_db = app.status()["volume"]["systemDb"]
                # Loud (effective well above trigger): lower so there is headroom to recover.
                now = self.run_ticks(app, start + 250, 24, level=5.0)
                lowered = source.endpoint.GetMasterVolumeLevel()
                self.assertLess(lowered, baseline_db)
                self.assertTrue(any(item["kind"] == "lower" for item in app.history()["actions"]))
                # Same song turns quiet: hold the lowered volume.
                now = self.run_ticks(app, now, 20, level=-55.0)
                self.assertEqual(source.endpoint.GetMasterVolumeLevel(), lowered)
                # Song change (silence gap), then quiet content: repay the debt.
                now = self.run_ticks(app, now, 8, silent=True)
                now = self.run_ticks(app, now, 80, level=-55.0)
                recovered = source.endpoint.GetMasterVolumeLevel()
                self.assertGreater(recovered, lowered)
                self.assertLessEqual(recovered, baseline_db + 0.6)
                self.assertGreater(app.status()["executor"]["raiseCount"], 0)
                self.assertTrue(any(item["kind"] == "recover" and item["appliedVolume"] is not None
                                    for item in app.history()["actions"]))
                raises = [item for item in app.history()["actions"] if item["kind"] == "recover"]
                for item in raises:
                    if item["appliedVolume"] is not None:
                        self.assertLessEqual(item["appliedVolume"], 60 + 0.6)
                log = Path(folder, "windows-executor-events.jsonl").read_text(encoding="utf-8")
                self.assertIn('"direction": "raise"', log)
            finally:
                app.close()

    def test_user_lowering_during_recovery_sets_new_ceiling(self):
        with tempfile.TemporaryDirectory() as folder:
            source = FakeRaisingSource(volume=0.6, level=5.0)
            app = self.make_app(folder, source)
            try:
                start = app.status()["timestampMs"] + 250
                app.tick(start)
                app.set_mode({"mode": "automatic"})
                now = self.run_ticks(app, start + 250, 16, level=5.0)
                # User turns it down; this becomes the new baseline/ceiling.
                source.endpoint.volume = 0.3
                source.user_changed = True
                app.tick(now); now += 250
                now = self.run_ticks(app, now, 80, level=-55.0)
                self.assertLessEqual(source.endpoint.volume, 0.3 + 0.01)
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
