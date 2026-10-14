#!/usr/bin/env python3
"""Merge qualified Wave 7 ZMPD truth without overwriting blind-anchor truth."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
INVESTIGATION = ROOT.parent
DEMO = INVESTIGATION / "Flowset-个人审美打标-Demo"
CATALOG = ROOT / "歌曲特征.json"
ALIASES = ROOT / "song_identity_aliases.json"
ANNOTATIONS = DEMO / "Flowset-个人审美样本·第七波闭环补标100首-郑卡罗-2026-10-05.json"
BATCH_LIST = DEMO / "第七波测试清单.csv"
ANCHOR_AUDIT = DEMO / "第七波锚点审计.json"
SONG_RESOURCES = ROOT / "SongResources"
TEST_AUDIO = DEMO / "音乐第七波测试"
AUDIT = ROOT / "第七批ZMPD合并审计.json"

DIMENSIONS = {"噪音程度": "noise", "摇摆速率": "swing", "负担程度": "burden"}
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


def selection_map(track: dict) -> dict[str, list[str]]:
    return {item["dimension"]: item["labels"] for item in track.get("selections", [])}


def main() -> None:
    catalog = read(CATALOG)
    labels = read(ANNOTATIONS)
    aliases = read(ALIASES)
    filename_aliases = aliases["filenameAliases"]
    artist_aliases = aliases["artistAliases"]
    anchor_audit = read(ANCHOR_AUDIT)
    anchor_by_name = {item["filename"]: item for item in anchor_audit["anchors"]}
    with BATCH_LIST.open(encoding="utf-8-sig", newline="") as source:
        batch_rows = {row["filename"]: row for row in csv.DictReader(source)}

    if set(batch_rows) != {item["file"]["name"] for item in labels["tracks"]}:
        raise ValueError("第七波测试清单与导出 JSON 的文件集合不一致")

    for track in catalog["tracks"]:
        track["filename"] = filename_aliases.get(track["filename"], track["filename"])
        track["title"], artist = title_artist(track["filename"])
        track["artist"] = artist_aliases.get(artist, artist)
    by_filename = {track["filename"]: track for track in catalog["tracks"]}
    if len(by_filename) != len(catalog["tracks"]):
        raise ValueError("身份规范化后 catalog 出现重复 filename")

    merged, pending, anchors, manual_discarded = [], [], [], []
    for annotation in labels["tracks"]:
        raw_filename = annotation["file"]["name"]
        filename = filename_aliases.get(raw_filename, raw_filename)
        row = batch_rows[raw_filename]
        tested_audio = TEST_AUDIO / raw_filename
        if not tested_audio.is_file():
            raise ValueError(f"第七波测试目录缺少音频：{raw_filename}")
        if tested_audio.stat().st_size != int(row["file_size"]) or sha256(tested_audio) != row["sha256"]:
            raise ValueError(f"第七波音频身份校验失败：{filename}")
        target = by_filename.get(filename)

        if not annotation.get("completed"):
            manual_discarded.append({
                "trackId": row["track_id"],
                "filename": filename,
                "reason": "user-declared-archive-discard-before-zmpd-labeling",
                "inCatalog": target is not None,
            })
            continue

        selections = selection_map(annotation)
        if raw_filename in anchor_by_name:
            previous = anchor_by_name[raw_filename]["previous_selections"]
            anchors.append({
                "trackId": row["track_id"],
                "filename": filename,
                "audioSha256": row["sha256"],
                "previousSourceAnnotationId": anchor_by_name[raw_filename]["source_annotation_id"],
                "previousSelections": previous,
                "repeatSelections": selections,
                "numericDelta": {
                    dimension: int(selections[dimension][0]) - int(previous[dimension][0])
                    for dimension in DIMENSIONS
                },
                "trainingTruthPolicy": "preserve-previous-selection",
            })
            continue

        audio = SONG_RESOURCES / filename
        if not audio.is_file() or audio.stat().st_size != int(row["file_size"]) or sha256(audio) != row["sha256"]:
            raise ValueError(f"新增真值与当前 SongResources 音频身份不一致：{filename}")

        record = {"trackId": row["track_id"], "filename": filename, "audioSha256": row["sha256"]}
        if target is None:
            pending.append(record)
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
            "wave": "wave7-gap-close-93-new-5-anchor-2-discarded",
            "annotationFile": ANNOTATIONS.name,
            "exportedAt": labels.get("exportedAt"),
        }
        record["catalogTrackId"] = target["trackId"]
        merged.append(record)

    if (len(merged), len(pending), len(anchors), len(manual_discarded)) != (70, 23, 5, 2):
        raise ValueError("第七波合并分组数量偏离已审核的 70/23/5/2")
    if len(catalog["tracks"]) != len(catalog["transitions"]) or any(
        len(row) != len(catalog["tracks"]) for row in catalog["transitions"]
    ):
        raise ValueError("catalog transition 不是完整方阵")

    truth = catalog.setdefault("catalogue", {}).setdefault("humanGroundTruthZmpd", {})
    truth.update({
        "wave7MergedTracks": len(merged),
        "wave7PendingNewTracks": len(pending),
        "wave7AnchorRepeatTracks": len(anchors),
        "wave7ManualDiscardedTracks": len(manual_discarded),
        "wave7Source": ANNOTATIONS.name,
    })
    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    audit = {
        "schemaVersion": "flowset.wave7-catalog-merge-audit/v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceAnnotation": str(ANNOTATIONS),
        "sourceAnnotationSha256": sha256(ANNOTATIONS),
        "batchList": str(BATCH_LIST),
        "batchListSha256": sha256(BATCH_LIST),
        "catalogTracks": len(catalog["tracks"]),
        "exportedTracks": len(labels["tracks"]),
        "completedTracks": sum(bool(item.get("completed")) for item in labels["tracks"]),
        "qualifiedNewTracks": len(merged) + len(pending),
        "mergedExistingTransitionCompleteTracks": len(merged),
        "pendingNewTracksNeedingFullBidirectionalTransitions": len(pending),
        "blindAnchorRepeats": len(anchors),
        "manualDiscardedBeforeLabeling": len(manual_discarded),
        "merged": sorted(merged, key=lambda item: item["filename"].casefold()),
        "pending": sorted(pending, key=lambda item: item["filename"].casefold()),
        "anchors": sorted(anchors, key=lambda item: item["filename"].casefold()),
        "manualDiscarded": sorted(manual_discarded, key=lambda item: item["filename"].casefold()),
    }
    AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: audit[key] for key in (
        "catalogTracks", "completedTracks", "qualifiedNewTracks",
        "mergedExistingTransitionCompleteTracks", "pendingNewTracksNeedingFullBidirectionalTransitions",
        "blindAnchorRepeats", "manualDiscardedBeforeLabeling",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
