#!/usr/bin/env python3
"""Validate and import a combined SongBase Tag + ZMPD review export."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

from build_song_tags_browser import BASE, SONGS_PATH, TAGS_PATH, build_payload, load_json


ROOT = BASE.parent
ANNOTATION_DIR = ROOT / "Flowset-个人审美打标-Demo"
ZMPD_DIR = ROOT / "ZMPD-模型预测开发"
REFERENCE_ANNOTATION = ANNOTATION_DIR / "Flowset-个人审美样本·第七波闭环补标100首-郑卡罗-2026-10-05.json"
GENRES = {
    "Ambient / Neo-Classical", "Post-Rock / Cinematic", "Electronic", "Jazz / Soul",
    "Folk / Singer-Songwriter", "Rock / Alternative", "Hip-Hop / R&B",
}
TIME_VALUES = {"8-11", "11-14", "14-17", "17-20"}
ENERGY_VALUES = {"平静", "渐进", "有冲劲", "爆发", "不确定"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_assignments(values: list[str], caster) -> dict[str, object]:
    result = {}
    for value in values:
        track_id, separator, raw = value.partition("=")
        if not separator:
            raise ValueError(f"修正参数必须是 track_id=value：{value}")
        result[track_id] = caster(raw)
    return result


def validate_and_prepare(source: Path, confidence: dict, instrumental: dict) -> tuple[dict, list[dict], dict]:
    payload = load_json(source)
    if payload.get("schema_version") != "songbase.combined-annotations/v1":
        raise ValueError("不是 songbase.combined-annotations/v1")
    tags = load_json(TAGS_PATH)
    library_payload = build_payload(load_json(SONGS_PATH), tags, None)
    library = {song["id"]: song for song in library_payload["songs"]}
    reference = load_json(REFERENCE_ANNOTATION)
    dimensions = reference["dimensions"]
    dimensions_by_name = {item["name"]: item for item in dimensions}
    prepared = []
    seen = set()

    for review in payload.get("reviews", []):
        track_id = review.get("track_id")
        if track_id in seen or track_id not in library:
            raise ValueError(f"重复或不存在的曲目身份：{track_id}")
        seen.add(track_id)
        if review.get("requirements") != {"tag": True, "zmpd": True} or not review.get("completed"):
            raise ValueError(f"{track_id} 不是已完成的 Tag + ZMPD 双缺口记录")
        if track_id in tags["tracks"]:
            raise ValueError(f"{track_id} 已有正式 Tag，拒绝覆盖")

        tag = review["tag_review"]["resolved_tags"]
        secondary = tag.get("secondary_genres", [])
        if tag.get("genre") not in GENRES or len(secondary) > 2 or len(secondary) != len(set(secondary)):
            raise ValueError(f"{track_id} Tag 无效")
        if tag["genre"] in secondary or not set(secondary) <= GENRES:
            raise ValueError(f"{track_id} 副 Tag 无效")
        if track_id in instrumental:
            tag["instrumental"] = instrumental[track_id]

        zmpd = review["zmpd_review"]
        selections = zmpd["selections"]
        if not selections.get("time_scene") or not set(selections["time_scene"]) <= TIME_VALUES:
            raise ValueError(f"{track_id} 时段无效")
        if selections.get("energy_state") not in ENERGY_VALUES:
            raise ValueError(f"{track_id} 能量无效")
        if any(not isinstance(selections.get(key), int) or not 1 <= selections[key] <= 10 for key in ("noise", "swing", "burden")):
            raise ValueError(f"{track_id} 数值 ZMPD 无效")
        if track_id in confidence:
            zmpd["confidence"] = confidence[track_id]
        if zmpd.get("confidence") is not None and not 1 <= zmpd["confidence"] <= 5:
            raise ValueError(f"{track_id} 把握程度无效")

        song = library[track_id]
        relative_audio = unquote(song.get("audio_url") or "")
        audio = BASE / relative_audio
        if not relative_audio or not audio.is_file() or audio.stat().st_size <= 0:
            raise ValueError(f"{track_id} 缺少唯一本地音源")
        if (song["title"], song["artist"]) != (review["song"]["title"], review["song"]["artist"]):
            raise ValueError(f"{track_id} 标题/艺人与当前 SongBase 不一致")

        label_sets = {
            "适合的时段": selections["time_scene"],
            "能量状态": [selections["energy_state"]],
            "噪音程度": [str(selections["noise"])],
            "摇摆速率": [str(selections["swing"])],
            "负担程度": [str(selections["burden"])],
        }
        flowset_selections = []
        for name, labels in label_sets.items():
            dimension = dimensions_by_name[name]
            option_ids = {option["label"]: option["id"] for option in dimension["options"]}
            flowset_selections.append({
                "dimensionId": dimension["id"], "dimension": name,
                "optionIds": [option_ids[label] for label in labels], "labels": labels,
            })
        prepared.append({
            "track_id": track_id, "song": song, "tag": tag, "tag_note": review["tag_review"].get("note", ""),
            "zmpd": zmpd, "audio": audio, "flowset_selections": flowset_selections,
        })
    if set(confidence) - seen or set(instrumental) - seen:
        raise ValueError("修正参数包含本批次不存在的 track_id")
    return payload, prepared, {"tags": tags, "dimensions": dimensions}


def apply_import(source: Path, payload: dict, prepared: list[dict], context: dict) -> None:
    now = datetime.now(timezone.utc)
    date = now.astimezone().date().isoformat()
    stamp = now.astimezone().strftime("%Y-%m-%d_%H%M%S")
    snapshot = BASE / "archive" / "snapshots" / "song_tags" / f"song_tags_before_combined_import_{stamp}.json"
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TAGS_PATH, snapshot)

    tags = context["tags"]
    for item in prepared:
        tags["tracks"][item["track_id"]] = {
            **item["tag"],
            "source": "human_combined_tag_zmpd_review",
            "updated_at": date,
            "note": item["tag_note"] or "Tag + ZMPD 联合标注确认入档。",
        }
    tags["updated_at"] = date
    TAGS_PATH.write_text(json.dumps(tags, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    annotation_name = f"Flowset-个人审美样本·Tag-ZMPD联合标注{len(prepared)}首-郑卡罗-{date}.json"
    annotation_path = ANNOTATION_DIR / annotation_name
    if annotation_path.exists():
        raise ValueError(f"标注批次已存在，拒绝覆盖：{annotation_path.name}")
    tracks = []
    for order, item in enumerate(prepared, 1):
        audio = item["audio"]
        tracks.append({
            "order": order,
            "file": {
                "name": audio.name,
                "relativePath": f"../SongBase/SongResources/{audio.name}",
                "size": audio.stat().st_size,
                "lastModified": int(audio.stat().st_mtime * 1000),
                "type": "audio/mpeg" if audio.suffix.lower() == ".mp3" else "audio/*",
            },
            "selections": item["flowset_selections"],
            "confidence": item["zmpd"].get("confidence"),
            "note": item["zmpd"].get("note") or None,
            "completed": True,
        })
    annotation = {
        "schemaVersion": "flowset.annotations/v1",
        "exportedAt": now.isoformat(),
        "app": {"name": "SongBase Tag + ZMPD 联合标注", "version": "1"},
        "annotator": {"id": "郑卡罗"},
        "dataset": {"name": f"SongBase Tag + ZMPD 联合标注 {date}", "trackCount": len(tracks)},
        "dimensions": context["dimensions"],
        "tracks": tracks,
        "summary": {"completedTracks": len(tracks), "incompleteTracks": 0},
    }
    annotation_path.write_text(json.dumps(annotation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = {
        "schema_version": "songbase.combined-annotation-import/v1",
        "imported_at": now.isoformat(),
        "source_file": str(source),
        "source_sha256": sha256(source),
        "source_exported_at": payload.get("exported_at"),
        "tag_snapshot": str(snapshot.relative_to(BASE)),
        "zmpd_annotation": str(annotation_path.relative_to(ROOT)),
        "summary": {"formal_tags_added": len(prepared), "zmpd_annotations_added": len(prepared)},
        "tracks": [{
            "track_id": item["track_id"], "title": item["song"]["title"], "artist": item["song"]["artist"],
            "audio_filename": item["audio"].name, "audio_size": item["audio"].stat().st_size,
            "audio_sha256": sha256(item["audio"]), "tag": item["tag"],
            "zmpd": item["zmpd"],
        } for item in prepared],
    }
    report_path = BASE / "imports" / f"{date}-Tag-ZMPD联合标注{len(prepared)}首正式入档.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    subprocess.run([sys.executable, str(ZMPD_DIR / "build_training_manifest.py")], check=True)
    subprocess.run([sys.executable, str(BASE / "manage_albums.py"), "rebuild"], check=True)
    subprocess.run([sys.executable, str(BASE / "build_song_base_browser.py")], check=True)
    subprocess.run([sys.executable, str(BASE / "build_song_tags_browser.py")], check=True)
    subprocess.run([sys.executable, str(BASE / "update_report_snapshots.py")], check=True)
    subprocess.run([sys.executable, str(BASE / "build_annotation_gap_report.py")], check=True)
    print(json.dumps({"import_report": str(report_path), **report["summary"]}, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--set-confidence", action="append", default=[], metavar="TRACK_ID=1..5")
    parser.add_argument("--set-instrumental", action="append", default=[], metavar="TRACK_ID=true|false")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    confidence = parse_assignments(args.set_confidence, int)
    instrumental = parse_assignments(args.set_instrumental, lambda value: {"true": True, "false": False}[value.lower()])
    payload, prepared, context = validate_and_prepare(args.source, confidence, instrumental)
    print(json.dumps({"validated": len(prepared), "apply": args.apply}, ensure_ascii=False))
    if args.apply:
        apply_import(args.source, payload, prepared, context)


if __name__ == "__main__":
    main()
