"""Replay the M0 synthetic scenarios through the pure M1 controller."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path

from controller import VolumeController, default_settings, validate_settings


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIOS = ROOT / "fixtures" / "scenarios.json"


def read_json(path):
    with Path(path).open("r", encoding="utf-8") as source:
        return json.load(source)


def replay(document, settings, scenario_id=None, step_seconds=1.0, initial_volume=67.0):
    if document.get("schemaVersion") != "system-audio.simulation-scenarios/v1":
        raise ValueError("不支持的模拟场景 schemaVersion")
    scenarios = document.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("模拟场景不能为空")
    if scenario_id:
        scenarios = [item for item in scenarios if item.get("id") == scenario_id]
        if not scenarios:
            raise ValueError("未知模拟场景：%s" % scenario_id)
    if not 0.1 <= step_seconds <= 10:
        raise ValueError("step_seconds 必须在 0.1..10 之间")

    controller = VolumeController(validate_settings(settings))
    timestamp_ms = 0.0
    volume = float(initial_volume)
    rows = []
    for scenario in scenarios:
        sample_count = max(1, int(float(scenario["durationSeconds"]) / step_seconds) + 1)
        for _index in range(sample_count):
            observation = {
                "timestampMs": timestamp_ms,
                "deviceId": "offline-fixture",
                "systemVolume": volume,
                "shortTermLufs": scenario["shortTermLufs"],
                "momentaryLufs": scenario["momentaryLufs"],
                "rmsDbfs": scenario["rmsDbfs"],
                "peakDbfs": scenario["peakDbfs"],
                "isSilent": scenario["isSilent"],
                "captureAvailable": True,
                "volumeControllable": True,
                "manualVolumeChanged": False,
            }
            action = controller.step(observation)
            if action["execute"] and action["recommendedVolume"] is not None:
                volume = action["recommendedVolume"]
                action["appliedVolume"] = volume
            row = deepcopy(action)
            row["scenarioId"] = scenario["id"]
            rows.append(row)
            timestamp_ms += step_seconds * 1000
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument("--scenario")
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--mode", choices=("monitor", "shadow", "lower-only", "automatic"),
                        default="shadow")
    parser.add_argument("--step-seconds", type=float, default=1.0)
    parser.add_argument("--initial-volume", type=float, default=67.0)
    args = parser.parse_args()

    settings = read_json(args.settings) if args.settings else default_settings()
    settings["mode"] = args.mode
    rows = replay(read_json(args.scenarios), settings, args.scenario,
                  args.step_seconds, args.initial_volume)
    for row in rows:
        print(json.dumps(row, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
