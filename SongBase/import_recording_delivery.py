#!/usr/bin/env python3
"""Import one verified flat-MP3 recording delivery into SongBase."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

from build_song_tags_browser import build_payload, load_json, SONGS_PATH, TAGS_PATH, CANDIDATES_PATH


BASE = Path(__file__).resolve().parent
RESOURCES = BASE / "SongResources"
PENDING_JSON = BASE / "待录制清单.json"
PENDING_MD = BASE / "待录制清单.md"


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def write_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def duration(seconds: int) -> str:
    hours, remainder = divmod(int(seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"0:{minutes:02d}:{seconds:02d}"


def pending_markdown(payload: dict) -> str:
    summary = payload["summary"]
    lines = [
        "# SongBase 当前待录制清单", "",
        f"> 生成时间：{payload['created_at']}",
        "> 核对口径：QQ MID + 当前 SongBase 元数据；本地音源使用标签浏览器同一套解析器。",
        "> 本清单只整理任务，不代表 QQ 链接已经完成实时播放验证，也没有启动录制。", "",
        "## 汇总", "",
        f"- 当前主库：{summary['library_tracks']:,} 首",
        f"- 可匹配本地音源：{summary['local_playable_tracks']:,} 首",
        f"- 缺本地音源：{summary['missing_total']:,} 首",
        f"- 可进入新一轮 QQ 录制：{summary['recordable_tracks']:,} 首，曲目总时长 {duration(summary['recordable_duration_seconds'])}",
        f"- 已确认下架、不进入录制：{summary['unavailable_tracks']} 首",
        f"- 可录制曲目涉及艺人：{summary['recordable_artist_count']} 位", "",
        "## 建议分批", "", "| 批次 | 曲目数 | 曲目时长 |", "|---:|---:|---:|",
    ]
    lines.extend(f"| {row['batch']} | {row['tracks']} | {duration(row['duration_seconds'])} |" for row in payload["batches"])
    lines.extend(["", f"这 {len(payload['batches'])} 批按原 QQ 歌单顺序划分；实际录制还会包含切歌、加载和验收时间。", "",
                  "## 已确认下架", "", "| QQ MID | 曲目 | 艺人 | 原因 |", "|---|---|---|---|"])
    for row in payload["unavailable_tracks"]:
        lines.append(f"| `{row['track_id']}` | {row['title']} | {row['artist']} | {row['reason']} |")
    lines.extend(["", "## 可录制曲目", "", "| # | 批次 | 原歌单序号 | QQ MID | 曲目 | 艺人 | 专辑 | 时长 |", "|---:|---:|---:|---|---|---|---|---:|"])
    for row in payload["recordable_tracks"]:
        values = [str(row["sequence"]), str(row["recording_batch"]), str(row["playlist_position"]),
                  f"`{row['track_id']}`", row["title"], row["full_singer"] or row["artist"], row["album"], duration(row["duration_seconds"])]
        lines.append("| " + " | ".join(value.replace("|", "\\|") for value in values) + " |")
    return "\n".join(lines) + "\n"


def import_markdown(manifest: dict) -> str:
    summary = manifest["summary"]
    lines = [
        f"# {manifest['batch_name']}", "",
        f"- 入档时间：{manifest['created_at']}",
        f"- 曲目：{summary['tracks']} 首（自动验收 {summary['automatic_accepted']} 首，人工豁免 {summary['manual_approved_exceptions']} 首）",
        f"- 尾部裁剪 1 秒：{summary['tail_trimmed']} 首",
        f"- 来源凭据：`{manifest['recording_receipt']}`",
        "- 身份规则：QQ MID + SongBase 正式曲名与完整歌手；不使用仅曲名匹配。", "",
        "| # | QQ MID | 曲目 | 完整歌手 | 录制状态 | 尾部处理 | SHA-256 |",
        "|---:|---|---|---|---|---|---|",
    ]
    for number, row in enumerate(manifest["tracks"], 1):
        trim = "去掉最后 1 秒" if row.get("tail_trim_seconds") else "保留全长"
        title, artist = row["title"].replace("|", "\\|"), row["artist"].replace("|", "\\|")
        lines.append(f"| {number} | `{row['track_id']}` | {title} | {artist} | {row['recording_status']} | {trim} | `{row['sha256']}` |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--batch-name", required=True)
    parser.add_argument("--review-decisions", type=Path)
    args = parser.parse_args()

    receipt = load_json(args.receipt)
    pending = load_json(PENDING_JSON)
    rows = {row["song_mid"]: row for row in pending["recordable_tracks"]}
    decisions = {row["id"]: row for row in load_json(args.review_decisions).get("decisions", [])} if args.review_decisions else {}
    imported = []
    for entry in receipt["tracks"]:
        if entry["status"] not in {"accepted", "manual-approved-exception"}:
            continue
        row = rows.get(entry["id"])
        if row is None or row["title"] != entry["title"] or row["full_singer"] != entry["artist"]:
            raise ValueError(f"SongBase 身份核对失败：{entry['id']}")
        if len(entry.get("files", [])) != 1:
            raise ValueError(f"交付文件数量异常：{entry['id']}")
        source = args.staging / entry["files"][0]["path"]
        target = BASE / row["target_relative_path"]
        expected = entry["files"][0]["sha256"]
        if digest(source) != expected:
            raise ValueError(f"交付哈希不符：{entry['id']}")
        if target.exists() and digest(target) != expected:
            raise FileExistsError(f"拒绝覆盖不同文件：{target}")
        if not target.exists():
            target.parent.mkdir(exist_ok=True)
            with source.open("rb") as src, target.open("xb") as dst:
                shutil.copyfileobj(src, dst)
        if digest(target) != expected:
            raise AssertionError(f"入库哈希不符：{entry['id']}")
        imported.append({
            "track_id": f"qq:{entry['id']}", "title": entry["title"], "artist": entry["artist"],
            "recording_status": entry["status"],
            "tail_trim_seconds": decisions.get(entry["id"], {}).get("trimmedTailSeconds", 0),
            "source_relative_path": str(source.relative_to(BASE)),
            "destination_relative_path": str(target.relative_to(BASE)),
            "size_bytes": target.stat().st_size, "sha256": expected,
            "action": "copied_or_verified",
        })
    if len(imported) != receipt["expected"]:
        raise AssertionError(f"应入库 {receipt['expected']} 首，实际 {len(imported)} 首")

    imported_ids = {row["track_id"].removeprefix("qq:") for row in imported}
    remaining = [row for row in pending["recordable_tracks"] if row["song_mid"] not in imported_ids]
    old_batches = sorted({row["recording_batch"] for row in remaining})
    batch_map = {old: number for number, old in enumerate(old_batches, 1)}
    for sequence, row in enumerate(remaining, 1):
        row["sequence"] = sequence
        row["recording_batch"] = batch_map[row["recording_batch"]]

    library = load_json(SONGS_PATH)
    tags = load_json(TAGS_PATH)
    candidates = load_json(CANDIDATES_PATH) if CANDIDATES_PATH.exists() else None
    payload = build_payload(library, tags, candidates)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    pending["created_at"] = now
    pending["updated_at"] = now[:10]
    pending["recordable_tracks"] = remaining
    pending["batches"] = [
        {"batch": batch, "tracks": sum(row["recording_batch"] == batch for row in remaining),
         "duration_seconds": sum(row["duration_seconds"] for row in remaining if row["recording_batch"] == batch)}
        for batch in sorted(set(batch_map.values()))
    ]
    pending["summary"] = {
        "library_tracks": len(payload["songs"]), "local_playable_tracks": payload["audio"]["mapped_tracks"],
        "missing_total": len(remaining) + len(pending["unavailable_tracks"]), "recordable_tracks": len(remaining),
        "unavailable_tracks": len(pending["unavailable_tracks"]),
        "recordable_duration_seconds": sum(row["duration_seconds"] for row in remaining),
        "recordable_artist_count": len({row["artist"] for row in remaining}), "planned_batches": len(pending["batches"]),
    }

    manifest = {
        "schema_version": "songbase.qq-recording-audio-import/v1", "batch_name": args.batch_name,
        "created_at": now, "recording_receipt": str(args.receipt.resolve()),
        "review_decisions": str(args.review_decisions.resolve()) if args.review_decisions else None,
        "staging_directory": str(args.staging.relative_to(BASE)), "target_directory": "SongResources",
        "identity_rule": "QQ MID + SongBase 正式曲名与完整歌手；不使用仅曲名匹配",
        "summary": {"tracks": len(imported),
                    "automatic_accepted": sum(row["recording_status"] == "accepted" for row in imported),
                    "manual_approved_exceptions": sum(row["recording_status"] == "manual-approved-exception" for row in imported),
                    "tail_trimmed": sum(bool(row["tail_trim_seconds"]) for row in imported),
                    "copied_or_verified_to_song_resources": len(imported)},
        "tracks": imported,
    }
    manifest_json = BASE / "imports" / f"{args.batch_name}.json"
    manifest_md = manifest_json.with_suffix(".md")
    write_json(manifest_json, manifest)
    manifest_md.write_text(import_markdown(manifest), encoding="utf-8")
    write_json(PENDING_JSON, pending)
    PENDING_MD.write_text(pending_markdown(pending), encoding="utf-8")
    print(json.dumps({"imported": len(imported), "localPlayable": payload["audio"]["mapped_tracks"],
                      "remainingRecordable": len(remaining)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
