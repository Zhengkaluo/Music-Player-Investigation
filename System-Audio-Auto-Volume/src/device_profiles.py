"""Small persistent device feedback profiles for M8a calibration."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from statistics import median


SCHEMA = "system-audio.device-profiles/v1"
RESPONSES = {"pre-volume", "post-volume", "unreliable"}
CONFIDENCE = {"low", "medium", "high"}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def classify_points(points, tolerance_lu=1.5):
    """Classify three stable volume/loudness points without retaining PCM."""
    if not isinstance(points, list) or len(points) < 3:
        raise ValueError("校准至少需要三个音量档位")
    clean = []
    for point in points:
        try:
            db = float(point["systemVolumeDb"])
            lufs = float(point["shortTermLufs"])
            count = int(point["sampleCount"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("校准点字段不完整") from error
        if not all(map(math.isfinite, (db, lufs))) or count < 3:
            raise ValueError("校准点必须包含至少三个有效样本")
        clean.append({**deepcopy(point), "systemVolumeDb": db,
                      "shortTermLufs": lufs, "sampleCount": count})
    clean.sort(key=lambda item: item["systemVolumeDb"])
    db_span = clean[-1]["systemVolumeDb"] - clean[0]["systemVolumeDb"]
    if db_span < 6:
        raise ValueError("三个校准档位的设备 dB 跨度至少需要 6 dB")
    source_values = [item["shortTermLufs"] for item in clean]
    normalized_values = [item["shortTermLufs"] - item["systemVolumeDb"]
                         for item in clean]
    pre_spread = max(source_values) - min(source_values)
    post_spread = max(normalized_values) - min(normalized_values)
    if pre_spread <= tolerance_lu and pre_spread <= post_spread:
        response, residual = "pre-volume", pre_spread
    elif post_spread <= tolerance_lu:
        response, residual = "post-volume", post_spread
    else:
        response, residual = "unreliable", min(pre_spread, post_spread)
    if response == "unreliable":
        confidence = "low"
    elif residual <= 0.75 and min(item["sampleCount"] for item in clean) >= 8:
        confidence = "high"
    else:
        confidence = "medium"
    return {
        "captureResponse": response,
        "confidence": confidence,
        "evidenceSummary": {
            "method": "three-level-short-term-median",
            "points": clean,
            "dbSpan": round(db_span, 3),
            "preVolumeSpreadLu": round(pre_spread, 3),
            "postVolumeSpreadLu": round(post_spread, 3),
            "toleranceLu": float(tolerance_lu),
        },
    }


class DeviceProfileStore:
    def __init__(self, path):
        self.path = Path(path)
        self.document = self._load()

    def _load(self):
        if not self.path.exists():
            return {"schemaVersion": SCHEMA, "profiles": []}
        with self.path.open("r", encoding="utf-8") as source:
            value = json.load(source)
        if (not isinstance(value, dict) or value.get("schemaVersion") != SCHEMA
                or not isinstance(value.get("profiles"), list)):
            raise ValueError("不支持的设备反馈档案格式")
        for profile in value["profiles"]:
            self._validate_profile(profile)
        return value

    @staticmethod
    def _validate_profile(profile):
        required = {"platform", "deviceId", "captureResponse", "confidence",
                    "volumeDbSource", "volumeDbMin", "volumeDbMax",
                    "mappingReliable", "environmentFingerprint", "calibratedAt",
                    "evidenceSummary"}
        if not isinstance(profile, dict) or not required.issubset(profile):
            raise ValueError("设备反馈档案字段不完整")
        if profile["captureResponse"] not in RESPONSES:
            raise ValueError("设备反馈档案 captureResponse 无效")
        if profile["confidence"] not in CONFIDENCE:
            raise ValueError("设备反馈档案 confidence 无效")
        if not isinstance(profile["mappingReliable"], bool):
            raise ValueError("设备反馈档案 mappingReliable 无效")
        return profile

    def _write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(self.document, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        os.replace(str(temporary), str(self.path))

    def match(self, observation):
        profile = next((item for item in self.document["profiles"]
                        if item["platform"] == observation.get("platform")
                        and item["deviceId"] == observation.get("deviceId")), None)
        if profile is None:
            return None, "missing"
        checks = (
            (profile["environmentFingerprint"] == observation.get("environmentFingerprint"),
             "environment-changed"),
            (profile["volumeDbSource"] == observation.get("volumeDbSource"),
             "db-source-changed"),
            (observation.get("volumeDbMin") is not None
             and abs(profile["volumeDbMin"] - observation["volumeDbMin"]) <= 0.1,
             "db-range-changed"),
            (observation.get("volumeDbMax") is not None
             and abs(profile["volumeDbMax"] - observation["volumeDbMax"]) <= 0.1,
             "db-range-changed"),
        )
        for valid, reason in checks:
            if not valid:
                return profile, reason
        if profile["captureResponse"] == "unreliable":
            return profile, "unreliable"
        return profile, "valid"

    def apply(self, observation):
        result = deepcopy(observation)
        profile, status = self.match(result)
        result["profileStatus"] = status
        result["captureConfidence"] = None
        if profile is not None:
            result["captureConfidence"] = profile["confidence"]
        if status == "valid":
            result["captureResponse"] = profile["captureResponse"]
        else:
            result["captureResponse"] = "unreliable" if status == "unreliable" else "unknown"
        return result, deepcopy(profile)

    def save(self, observation, classification):
        profile = {
            "platform": observation["platform"],
            "deviceId": observation["deviceId"],
            "deviceName": observation.get("deviceName"),
            "captureResponse": classification["captureResponse"],
            "confidence": classification["confidence"],
            "volumeDbSource": observation.get("volumeDbSource"),
            "volumeDbMin": observation.get("volumeDbMin"),
            "volumeDbMax": observation.get("volumeDbMax"),
            "volumeDbStep": observation.get("volumeDbStep"),
            "mappingReliable": bool(observation.get("volumeDbMappingReliable")),
            "environmentFingerprint": observation.get("environmentFingerprint"),
            "calibratedAt": utc_now(),
            "evidenceSummary": deepcopy(classification["evidenceSummary"]),
        }
        self._validate_profile(profile)
        self.document["profiles"] = [
            item for item in self.document["profiles"]
            if not (item["platform"] == profile["platform"]
                    and item["deviceId"] == profile["deviceId"])
        ] + [profile]
        self._write()
        return deepcopy(profile)


def stable_point(rows, device_id, seconds=4):
    candidates = [row for row in rows
                  if row.get("deviceId") == device_id
                  and row.get("shortTermLufs") is not None
                  and row.get("systemVolumeDb") is not None
                  and not row.get("isSilent")]
    if not candidates:
        raise ValueError("最近没有可用于校准的 Short-term 数据")
    newest = candidates[-1]["timestampMs"]
    candidates = [row for row in candidates
                  if newest - row["timestampMs"] <= seconds * 1000]
    if len(candidates) < 3:
        raise ValueError("请保持当前音量和同一稳定片段至少 3 秒")
    db_values = [row["systemVolumeDb"] for row in candidates]
    if max(db_values) - min(db_values) > 0.3:
        raise ValueError("采样窗口内系统音量发生变化，请保持稳定后重试")
    return {
        "systemVolume": round(median(row["systemVolume"] for row in candidates), 3),
        "systemVolumeDb": round(median(db_values), 3),
        "shortTermLufs": round(median(row["shortTermLufs"] for row in candidates), 3),
        "sampleCount": len(candidates),
        "windowSeconds": round((newest - candidates[0]["timestampMs"]) / 1000, 3),
    }
