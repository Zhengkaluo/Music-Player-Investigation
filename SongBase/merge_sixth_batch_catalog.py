#!/usr/bin/env python3
"""Merge Wave 6 human ZMPD truth into already transition-complete catalog tracks."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
INVESTIGATION = ROOT.parent
CATALOG = ROOT / "歌曲特征.json"
ALIASES = ROOT / "song_identity_aliases.json"
ANNOTATIONS = (
    INVESTIGATION
    / "Flowset-个人审美打标-Demo"
    / "Flowset-个人审美样本·第六波均衡补标100首-郑卡罗-2026-10-03.json"
)
SONG_RESOURCES = ROOT / "SongResources"
AUDIT = ROOT / "第六批ZMPD合并审计.json"

DIMENSIONS = {
    "噪音程度": "noise",
    "摇摆速率": "swing",
    "负担程度": "burden",
}
ENERGY_OPTIONS = ("平静", "渐进", "有冲劲", "爆发")
TIME_OPTIONS = ("8-11", "11-14", "14-17", "17-20")


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def title_artist(filename: str) -> tuple[str, str]:
    stem = Path(filename).stem
    return tuple(part.strip() for part in stem.rsplit(" - ", 1)) if " - " in stem else (stem, "未知歌手")


def main() -> None:
    catalog = read(CATALOG)
    labels = read(ANNOTATIONS)
    aliases = read(ALIASES)
    filename_aliases = aliases["filenameAliases"]
    artist_aliases = aliases["artistAliases"]

    canonicalized = []
    for track in catalog["tracks"]:
        previous = track["filename"]
        track["filename"] = filename_aliases.get(previous, previous)
        title, artist = title_artist(track["filename"])
        track["title"] = title
        track["artist"] = artist_aliases.get(artist, artist)
        if previous != track["filename"]:
            canonicalized.append({"from": previous, "to": track["filename"]})

    by_filename = {track["filename"]: track for track in catalog["tracks"]}
    if len(by_filename) != len(catalog["tracks"]):
        raise ValueError("身份规范化后 catalog 出现重复 filename")

    merged = []
    pending = []
    for annotation in labels["tracks"]:
        if not annotation.get("completed"):
            continue
        filename = filename_aliases.get(annotation["file"]["name"], annotation["file"]["name"])
        selections = {item["dimension"]: item["labels"] for item in annotation["selections"]}
        audio = SONG_RESOURCES / filename
        if not audio.is_file():
            raise ValueError(f"SongResources 缺少规范文件名音频：{filename}")
        target = by_filename.get(filename)
        if target is None:
            pending.append(filename)
            continue
        target["aesthetics"] = {
            curve: float(selections[dimension][0]) for dimension, curve in DIMENSIONS.items()
        }
        energy = selections["能量状态"][0]
        times = set(selections["适合的时段"])
        target["energyLabel"] = energy
        target["energyScores"] = {option: 1.0 if option == energy else 0.0 for option in ENERGY_OPTIONS}
        target["timeScores"] = {option: 1.0 if option in times else 0.0 for option in TIME_OPTIONS}
        target["personalStyleProvenance"] = {
            "type": "human-ground-truth",
            "wave": "wave6-balanced-100",
            "annotationFile": ANNOTATIONS.name,
            "exportedAt": labels.get("exportedAt"),
        }
        merged.append({
            "filename": filename,
            "trackId": target["trackId"],
            "audioSha256": sha256(audio),
        })

    catalog.setdefault("catalogue", {})["humanGroundTruthZmpd"] = {
        "wave6MergedTracks": len(merged),
        "wave6PendingNewTracks": len(pending),
        "source": ANNOTATIONS.name,
    }
    if len(catalog["tracks"]) != len(catalog["transitions"]):
        raise ValueError("catalog track 与 transition 行数不一致")
    if any(len(row) != len(catalog["tracks"]) for row in catalog["transitions"]):
        raise ValueError("catalog transition 不是完整方阵")

    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audit = {
        "schemaVersion": "flowset.wave6-catalog-merge-audit/v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceAnnotation": str(ANNOTATIONS),
        "sourceAnnotationSha256": sha256(ANNOTATIONS),
        "catalog": str(CATALOG),
        "catalogTracks": len(catalog["tracks"]),
        "qualifiedWave6Tracks": sum(bool(item.get("completed")) for item in labels["tracks"]),
        "mergedExistingTransitionCompleteTracks": len(merged),
        "pendingNewTracksNeedingFullBidirectionalTransitions": len(pending),
        "canonicalizedCatalogIdentities": canonicalized,
        "merged": merged,
        "pending": sorted(pending, key=str.casefold),
    }
    AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: audit[key] for key in (
        "catalogTracks", "qualifiedWave6Tracks", "mergedExistingTransitionCompleteTracks",
        "pendingNewTracksNeedingFullBidirectionalTransitions",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
