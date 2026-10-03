#!/usr/bin/env python3
"""Build a provenance-safe, genre-balanced sixth ZMPD annotation batch."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import random
from collections import Counter, defaultdict
from pathlib import Path

from build_flowset_tag_report import GENRES, build_song_index, compact


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "Flowset-个人审美打标-Demo"
SONGBASE = ROOT / "SongBase"
MANIFEST = ROOT / "ZMPD-模型预测开发" / "manifests" / "training-manifest.json"
OUTPUT_DIR = DEMO / "音乐第六波测试"
OUTPUT_CSV = DEMO / "第六波测试清单.csv"
COUNT = 100
SEED = 20261003
PREFERRED_MAX_PER_ARTIST = 2


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def genre_quotas(existing: Counter[str], count: int) -> Counter[str]:
    """Water-fill the seven formal genres toward equal final sample counts."""
    totals = Counter(existing)
    quotas: Counter[str] = Counter()
    for _ in range(count):
        genre = min(GENRES, key=lambda value: (totals[value], GENRES.index(value)))
        totals[genre] += 1
        quotas[genre] += 1
    return quotas


def main() -> None:
    manifest = load_json(MANIFEST)
    tags = load_json(SONGBASE / "song_tags.json")["tracks"]
    song_index, metadata = build_song_index()
    used_names = {track["filename"] for track in manifest["tracks"]}
    used_hashes = {track["audioSha256"] for track in manifest["tracks"]}

    existing: Counter[str] = Counter()
    pools: dict[str, list[dict]] = defaultdict(list)
    for path in sorted((SONGBASE / "SongResources").glob("*.mp3")):
        ids = sorted(track_id for track_id in song_index.get(compact(path.stem), set()) if track_id in tags)
        if len(ids) != 1:
            continue
        track_id = ids[0]
        genre = tags[track_id]["genre"]
        if path.name in used_names:
            existing[genre] += 1
            continue
        pools[genre].append({
            "track_id": track_id,
            "title": metadata[track_id]["title"],
            "artist": metadata[track_id]["artist"],
            "group_artist": metadata[track_id]["group_artist"],
            "genre": genre,
            "path": path,
        })

    quotas = genre_quotas(existing, COUNT)
    rng = random.Random(SEED)
    for pool in pools.values():
        rng.shuffle(pool)

    selected: list[dict] = []
    selected_hashes: set[str] = set()
    artist_counts: Counter[str] = Counter()

    def take(genre: str, limit_artists: bool) -> dict | None:
        for index in range(len(pools[genre]) - 1, -1, -1):
            row = pools[genre][index]
            if limit_artists and artist_counts[row["group_artist"]] >= PREFERRED_MAX_PER_ARTIST:
                continue
            pools[genre].pop(index)
            digest = sha256(row["path"])
            if digest in used_hashes or digest in selected_hashes:
                continue
            row["sha256"] = digest
            return row
        return None

    for genre in GENRES:
        needed = quotas[genre]
        for _ in range(needed):
            row = take(genre, True) or take(genre, False)
            if row is None:
                raise RuntimeError(f"{genre} 没有足够的合格音频来满足 {needed} 首配额")
            selected.append(row)
            selected_hashes.add(row["sha256"])
            artist_counts[row["group_artist"]] += 1

    if len(selected) != COUNT:
        raise RuntimeError(f"应选 {COUNT} 首，实际选到 {len(selected)} 首")

    OUTPUT_DIR.mkdir(exist_ok=True)
    existing_outputs = {path.name for path in OUTPUT_DIR.iterdir() if path.is_file()}
    expected_outputs = {row["path"].name for row in selected}
    unexpected = existing_outputs - expected_outputs
    if unexpected:
        raise RuntimeError(f"输出目录已有不属于本批次的文件：{sorted(unexpected)[:3]}")

    for row in selected:
        destination = OUTPUT_DIR / row["path"].name
        if destination.exists():
            if destination.stat().st_size != row["path"].stat().st_size or sha256(destination) != row["sha256"]:
                raise RuntimeError(f"现有目标文件与来源不一致：{destination.name}")
        else:
            os.link(row["path"], destination)

    selected.sort(key=lambda row: row["path"].name.casefold())
    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "order", "track_id", "title", "artist", "genre", "filename",
            "file_size", "sha256", "source_path", "storage",
        ])
        writer.writeheader()
        for order, row in enumerate(selected, 1):
            writer.writerow({
                "order": order,
                "track_id": row["track_id"],
                "title": row["title"],
                "artist": row["artist"],
                "genre": row["genre"],
                "filename": row["path"].name,
                "file_size": row["path"].stat().st_size,
                "sha256": row["sha256"],
                "source_path": str(row["path"].resolve()),
                "storage": "hard-link",
            })

    counts = Counter(row["genre"] for row in selected)
    print(f"已生成 {len(selected)} 首：{OUTPUT_DIR}")
    for genre in GENRES:
        print(f"  {genre}: 新增 {counts[genre]}，前五批正式匹配 {existing[genre]}，合计 {counts[genre] + existing[genre]}")
    print(f"优先限制同一艺人 {PREFERRED_MAX_PER_ARTIST} 首，配额回填后实际最多 {max(artist_counts.values())} 首；音频哈希重复 0；音频使用硬链接。")


if __name__ == "__main__":
    main()
