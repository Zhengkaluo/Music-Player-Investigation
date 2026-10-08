#!/usr/bin/env python3
"""Build the seventh ZMPD batch: 95 gap-closing tracks plus 5 blind anchors."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "Flowset-个人审美打标-Demo"
SONGBASE = ROOT / "SongBase"
GAP_CSV = SONGBASE / "Flow衔接与ZMPD补标缺口清单.csv"
TAGS_JSON = SONGBASE / "song_tags.json"
MANIFEST = ROOT / "ZMPD-模型预测开发" / "manifests" / "training-manifest.json"
OUTPUT_DIR = DEMO / "音乐第七波测试"
OUTPUT_CSV = DEMO / "第七波测试清单.csv"
ANCHOR_AUDIT = DEMO / "第七波锚点审计.json"

COUNT = 100
NEW_COUNT = 95
ANCHOR_COUNT = 5

DEFERRED_TRACK_IDS = {
    "qq:000TwCQn1LrW4g",  # 3+1 — Hotel New Tokyo
    "qq:0046lNIa2q0FRB",  # 東京ワルツ — Hotel New Tokyo
}

ANCHOR_FILENAMES = [
    "Sagu Palm's Song - 青葉市子.mp3",
    "Detective Lungmen - 塞壬唱片-MSR, 顾忠山, Damien Banzigou.mp3",
    "The edge of everything - Sleepmakeswaves.mp3",
    "Borderlines - Vraell.mp3",
    "ライフワーク - OGRE YOU A**HOLE.mp3",
]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_audio(filename: str) -> Path:
    path = SONGBASE / "SongResources" / filename
    if not path.is_file():
        raise FileNotFoundError(f"找不到 SongBase 音频：{filename}")
    return path


def main() -> None:
    with GAP_CSV.open(encoding="utf-8-sig", newline="") as handle:
        gap_rows = list(csv.DictReader(handle))
    tags = load_json(TAGS_JSON)["tracks"]
    manifest = load_json(MANIFEST)
    manifest_by_filename = {track["filename"]: track for track in manifest["tracks"]}
    gap_by_filename = {row["audio_files"]: row for row in gap_rows if row["audio_status"] == "unique"}

    eligible = [
        row for row in gap_rows
        if row["readiness"] == "可立即补标"
        and row["needs"] == "ZMPD"
    ]
    if len(eligible) != 97:
        raise RuntimeError(f"预期 97 首只缺 ZMPD 的候选，实际 {len(eligible)} 首；请重新审查抽样策略")

    new_rows = [row for row in eligible if row["track_id"] not in DEFERRED_TRACK_IDS]
    if len(new_rows) != NEW_COUNT:
        raise RuntimeError(f"预期 {NEW_COUNT} 首新增歌曲，实际 {len(new_rows)} 首")
    if {row["track_id"] for row in eligible} - {row["track_id"] for row in new_rows} != DEFERRED_TRACK_IDS:
        raise RuntimeError("暂缓歌曲与候选池不一致")

    selected: list[dict] = []
    for row in new_rows:
        path = source_audio(row["audio_files"])
        selected.append({
            "track_id": row["track_id"],
            "title": row["title"],
            "artist": row["artist"],
            "genre": tags[row["track_id"]]["genre"],
            "filename": path.name,
            "path": path,
            "role": "new",
            "source_batch": "",
        })

    anchor_audit = []
    for filename in ANCHOR_FILENAMES:
        previous = manifest_by_filename.get(filename)
        gap = gap_by_filename.get(filename)
        if previous is None or gap is None:
            raise RuntimeError(f"锚点无法连接 manifest/缺口表：{filename}")
        path = Path(previous["audioPath"])
        if not path.is_file():
            raise FileNotFoundError(f"找不到锚点历史音频：{path}")
        if previous["audioFileSize"] != path.stat().st_size or previous["audioSha256"] != sha256(path):
            raise RuntimeError(f"锚点历史音频身份变化：{filename}")
        genre = tags.get(gap["track_id"], {}).get("genre", "UNKNOWN")
        selected.append({
            "track_id": gap["track_id"],
            "title": gap["title"],
            "artist": gap["artist"],
            "genre": genre,
            "filename": path.name,
            "path": path,
            "role": "anchor",
            "source_batch": previous["batchFile"],
        })
        anchor_audit.append({
            "track_id": gap["track_id"],
            "filename": filename,
            "title": gap["title"],
            "artist": gap["artist"],
            "genre": genre,
            "source_batch": previous["batchFile"],
            "source_annotation_id": previous["sourceAnnotationId"],
            "audio_sha256": previous["audioSha256"],
            "previous_confidence": previous.get("confidence"),
            "previous_selections": previous["selections"],
        })

    if len(selected) != COUNT or len({row["filename"] for row in selected}) != COUNT:
        raise RuntimeError("第七波必须包含 100 个文件名唯一的样本")

    for row in selected:
        row["sha256"] = sha256(row["path"])
    if len({row["sha256"] for row in selected}) != COUNT:
        raise RuntimeError("第七波内部存在音频内容重复")

    selected.sort(key=lambda row: row["filename"].casefold())
    OUTPUT_DIR.mkdir(exist_ok=True)
    expected = {row["filename"] for row in selected}
    existing = {path.name for path in OUTPUT_DIR.iterdir() if path.is_file()}
    unexpected = existing - expected
    if unexpected:
        raise RuntimeError(f"输出目录有不属于本批次的文件：{sorted(unexpected)[:5]}")

    for row in selected:
        destination = OUTPUT_DIR / row["filename"]
        if destination.exists():
            if destination.stat().st_size != row["path"].stat().st_size or sha256(destination) != row["sha256"]:
                raise RuntimeError(f"现有目标与来源不一致：{destination.name}")
        else:
            os.link(row["path"], destination)

    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "order", "track_id", "title", "artist", "genre", "filename", "sample_role",
            "source_batch", "file_size", "sha256", "source_path", "storage",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for order, row in enumerate(selected, 1):
            writer.writerow({
                "order": order,
                "track_id": row["track_id"],
                "title": row["title"],
                "artist": row["artist"],
                "genre": row["genre"],
                "filename": row["filename"],
                "sample_role": row["role"],
                "source_batch": row["source_batch"],
                "file_size": row["path"].stat().st_size,
                "sha256": row["sha256"],
                "source_path": str(row["path"].resolve()),
                "storage": "hard-link",
            })

    positions = {row["filename"]: index for index, row in enumerate(selected, 1)}
    audit = {
        "schemaVersion": "zmpd.anchor-audit/v1",
        "batchId": "wave7-gap-close-95-anchor-5",
        "policy": {
            "totalTracks": COUNT,
            "newTracks": NEW_COUNT,
            "blindAnchors": ANCHOR_COUNT,
            "newSelection": "all immediately-ready tracks with needs=ZMPD except two deferred same-artist low-evidence tracks",
            "deferredTrackIds": sorted(DEFERRED_TRACK_IDS),
            "anchorHandling": "preserve both old and new records; do not overwrite before drift analysis",
        },
        "anchors": [dict(item, order=positions[item["filename"]]) for item in anchor_audit],
    }
    ANCHOR_AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    genre_counts = Counter(row["genre"] for row in selected if row["role"] == "new")
    anchor_positions = [positions[name] for name in ANCHOR_FILENAMES]
    print(f"已生成第七波：{NEW_COUNT} 首新增 + {ANCHOR_COUNT} 首盲测锚点 = {COUNT} 首")
    print(f"输出目录：{OUTPUT_DIR}")
    print(f"新增风格：{dict(sorted(genre_counts.items()))}")
    print(f"锚点位置：{sorted(anchor_positions)}")
    print("内部音频哈希重复：0；音频使用硬链接。")


if __name__ == "__main__":
    main()
