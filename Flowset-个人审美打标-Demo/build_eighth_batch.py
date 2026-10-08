#!/usr/bin/env python3
"""Build the eighth ZMPD batch: 96 balanced new tracks plus 4 blind anchors."""

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
OUTPUT_DIR = DEMO / "音乐第八波测试"
OUTPUT_CSV = DEMO / "第八波测试清单.csv"
ANCHOR_AUDIT = DEMO / "第八波锚点审计.json"

COUNT = 100
NEW_COUNT = 96
ANCHOR_COUNT = 4
GENRE_QUOTAS = {
    "Ambient / Neo-Classical": 14,
    "Post-Rock / Cinematic": 14,
    "Electronic": 12,
    "Jazz / Soul": 14,
    "Folk / Singer-Songwriter": 14,
    "Rock / Alternative": 14,
    "Hip-Hop / R&B": 14,
}
ANCHOR_FILENAMES = [
    "Deep Breath - Paniyolo.mp3",
    "Fort - GoGo Penguin.mp3",
    "Distance - Fayzz.mp3",
    "蝉 - iimmune.mp3",
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


def choose_genre(rows: list[dict], quota: int, artist_counts: Counter, artist_cap: int) -> list[dict]:
    """Prefer ZMPD-only, then current-catalog tracks; relax artist cap only if needed."""
    selected: list[dict] = []
    pools = [
        [row for row in rows if row["needs"] == "ZMPD"],
        [row for row in rows if row["needs"] != "ZMPD" and row["in_catalog"] == "True"],
        [row for row in rows if row["needs"] != "ZMPD" and row["in_catalog"] != "True"],
    ]
    for pool in pools:
        pool.sort(key=lambda row: (row["group_artist"].casefold(), row["title"].casefold(), row["track_id"]))
        for row in pool:
            if len(selected) == quota:
                return selected
            if artist_counts[row["group_artist"]] >= artist_cap:
                continue
            selected.append(row)
            artist_counts[row["group_artist"]] += 1
    for pool in pools:
        for row in pool:
            if len(selected) == quota:
                return selected
            if row in selected:
                continue
            selected.append(row)
            artist_counts[row["group_artist"]] += 1
    if len(selected) != quota:
        raise RuntimeError(f"风格候选不足：需要 {quota}，实际 {len(selected)}")
    return selected


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
        and row["needs"] in {"ZMPD", "Flow衔接 + ZMPD"}
        and row["track_id"] in tags
        and row["audio_status"] == "unique"
    ]
    by_genre: dict[str, list[dict]] = {genre: [] for genre in GENRE_QUOTAS}
    for row in eligible:
        genre = tags[row["track_id"]]["genre"]
        if genre in by_genre:
            by_genre[genre].append(row)

    artist_counts: Counter = Counter()
    new_rows: list[dict] = []
    for genre, quota in GENRE_QUOTAS.items():
        artist_cap = 4 if genre == "Electronic" else 2
        new_rows.extend(choose_genre(by_genre[genre], quota, artist_counts, artist_cap))
    if len(new_rows) != NEW_COUNT or len({row["track_id"] for row in new_rows}) != NEW_COUNT:
        raise RuntimeError("第八波新增样本数量或身份不唯一")

    selected: list[dict] = []
    for row in new_rows:
        path = source_audio(row["audio_files"])
        selected.append({
            "track_id": row["track_id"],
            "title": row["title"],
            "artist": row["artist"],
            "selection_artist": row["group_artist"],
            "genre": tags[row["track_id"]]["genre"],
            "filename": path.name,
            "path": path,
            "role": "new",
            "source_batch": "",
            "gap_before": row["needs"],
            "in_catalog": row["in_catalog"],
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
        genre = tags[gap["track_id"]]["genre"]
        selected.append({
            "track_id": gap["track_id"],
            "title": gap["title"],
            "artist": gap["artist"],
            "selection_artist": gap["group_artist"],
            "genre": genre,
            "filename": path.name,
            "path": path,
            "role": "anchor",
            "source_batch": previous["batchFile"],
            "gap_before": "已标锚点",
            "in_catalog": gap["in_catalog"],
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
        raise RuntimeError("第八波必须包含 100 个文件名唯一的样本")
    for row in selected:
        row["sha256"] = sha256(row["path"])
    if len({row["sha256"] for row in selected}) != COUNT:
        raise RuntimeError("第八波内部存在音频内容重复")

    selected.sort(key=lambda row: row["filename"].casefold())
    OUTPUT_DIR.mkdir(exist_ok=True)
    expected = {row["filename"] for row in selected}
    existing = {path.name for path in OUTPUT_DIR.iterdir() if path.is_file()}
    if existing - expected:
        raise RuntimeError(f"输出目录有不属于本批次的文件：{sorted(existing - expected)[:5]}")
    for row in selected:
        destination = OUTPUT_DIR / row["filename"]
        if destination.exists():
            if destination.stat().st_size != row["path"].stat().st_size or sha256(destination) != row["sha256"]:
                raise RuntimeError(f"现有目标与来源不一致：{destination.name}")
        else:
            os.link(row["path"], destination)

    fields = [
        "order", "track_id", "title", "artist", "genre", "filename", "sample_role",
        "source_batch", "gap_before", "in_catalog", "file_size", "sha256", "source_path", "storage",
    ]
    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
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
                "gap_before": row["gap_before"],
                "in_catalog": row["in_catalog"],
                "file_size": row["path"].stat().st_size,
                "sha256": row["sha256"],
                "source_path": str(row["path"].resolve()),
                "storage": "hard-link",
            })

    positions = {row["filename"]: index for index, row in enumerate(selected, 1)}
    new_selected = [row for row in selected if row["role"] == "new"]
    audit = {
        "schemaVersion": "zmpd.anchor-audit/v1",
        "batchId": "wave8-balanced-96-anchor-4",
        "policy": {
            "totalTracks": COUNT,
            "newTracks": NEW_COUNT,
            "blindAnchors": ANCHOR_COUNT,
            "newSelection": "latest ready gap list; include both remaining ZMPD-only tracks, then prioritize current catalog and artist diversity within fixed genre quotas",
            "genreQuotas": GENRE_QUOTAS,
            "selectedByPriorGap": dict(Counter(row["gap_before"] for row in new_selected)),
            "selectedCurrentCatalogTracks": sum(row["in_catalog"] == "True" for row in new_selected),
            "anchorHandling": "preserve old and new records; do not overwrite training truth before drift analysis",
        },
        "anchors": [dict(item, order=positions[item["filename"]]) for item in anchor_audit],
    }
    ANCHOR_AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    genre_counts = Counter(row["genre"] for row in new_selected)
    anchor_positions = [positions[name] for name in ANCHOR_FILENAMES]
    print(json.dumps({
        "newTracks": len(new_selected),
        "anchors": ANCHOR_COUNT,
        "genreCounts": dict(sorted(genre_counts.items())),
        "priorGaps": dict(Counter(row["gap_before"] for row in new_selected)),
        "currentCatalogTracks": sum(row["in_catalog"] == "True" for row in new_selected),
        "maxTracksPerArtist": max(Counter(row["selection_artist"] for row in new_selected).values()),
        "anchorPositions": sorted(anchor_positions),
        "output": str(OUTPUT_CSV),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
