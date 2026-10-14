#!/usr/bin/env python3
"""Safely import the verified 2026-09-21 supplemental SongBase audio batch.

The script is deliberately batch-specific: it accepts only recordings whose
normalized ``title - full_singer`` identity appears exactly once in the active
SongBase library, excludes records already archived as discarded, and refuses
to overwrite a non-identical local file.  It writes JSON and Markdown manifests
so the origin of every imported recording remains auditable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


BASE = Path(__file__).resolve().parent
LIBRARY_PATH = BASE / "song_base_by_artist.json"
DISCARDED_PATH = BASE / "archive" / "removed_tracks" / "discarded_tracks.json"
TARGET_DIR = BASE / "SongResources"
IMPORT_SOURCE_ROOT = BASE / "imports" / "2026-09-21-补录来源"
SOURCE_DIRS = (
    IMPORT_SOURCE_ROOT / "另一台 补录",
    IMPORT_SOURCE_ROOT / "郑灏澜 MacBook 补录",
)
MANIFEST_DIR = BASE / "imports"
EXPECTED_ARCHIVED = 2


@dataclass(frozen=True)
class Track:
    track_id: str
    title: str
    artist: str
    group_artist: str
    album: str


def clean_filename(value: str) -> str:
    value = unicodedata.normalize("NFC", str(value or ""))
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", value)
    return re.sub(r"\s+", " ", value).strip(" .") or "未命名"


def exact_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def compact_key(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in value if character.isalnum())


def track_stem(title: str, artist: str) -> str:
    return f"{clean_filename(title)} - {clean_filename(artist)}"


def qq_id(song: dict[str, Any]) -> str:
    url = str(song.get("qq_music", "") or "")
    marker = "/songDetail/"
    if marker not in url:
        raise ValueError(f"缺少 QQ Music MID：{song.get('title', '')}")
    return "qq:" + url.split(marker, 1)[1].split("?", 1)[0].split("#", 1)[0]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def add_track(index: dict[str, list[Track]], key: str, track: Track) -> None:
    """Index every distinct QQ MID; defer an ambiguity decision to a source file."""
    records = index.setdefault(key, [])
    if all(current.track_id != track.track_id for current in records):
        records.append(track)


def build_library_index(library: dict[str, Any]) -> tuple[dict[str, list[Track]], dict[str, list[Track]]]:
    exact: dict[str, list[Track]] = {}
    compact: dict[str, list[Track]] = {}
    for singer in library.get("singers", []):
        group_artist = str(singer.get("name", "") or "").strip()
        for song in singer.get("songs", []):
            artist = str(song.get("full_singer", "") or "").strip() or group_artist
            track = Track(
                track_id=qq_id(song),
                title=str(song.get("title", "") or "").strip(),
                artist=artist,
                group_artist=group_artist,
                album=str(song.get("album", "") or "").strip(),
            )
            stem = track_stem(track.title, track.artist)
            add_track(exact, exact_key(stem), track)
            add_track(compact, compact_key(stem), track)
    return exact, compact


def build_discarded_index(payload: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    exact: dict[str, dict[str, Any]] = {}
    compact: dict[str, dict[str, Any]] = {}
    for track in payload.get("tracks", {}).values():
        title = str(track.get("title", "") or "").strip()
        artist = str(track.get("full_singer", "") or track.get("artist", "") or "").strip()
        stem = track_stem(title, artist)
        exact[exact_key(stem)] = track
        compact[compact_key(stem)] = track
    return exact, compact


def identify(
    source: Path,
    library_exact: dict[str, list[Track]],
    library_compact: dict[str, list[Track]],
    discarded_exact: dict[str, dict[str, Any]],
    discarded_compact: dict[str, dict[str, Any]],
) -> tuple[str, Track | dict[str, Any] | None]:
    stem = source.stem
    tracks = library_exact.get(exact_key(stem)) or library_compact.get(compact_key(stem))
    if tracks:
        if len(tracks) == 1:
            return "import", tracks[0]
        return "ambiguous", None
    discarded = discarded_exact.get(exact_key(stem)) or discarded_compact.get(compact_key(stem))
    if discarded is not None:
        return "archived", discarded
    return "unmatched", None


def relative(path: Path) -> str:
    return str(path.relative_to(BASE))


def manifest_markdown(manifest: dict[str, Any]) -> str:
    lines = [
        f"# {manifest['batch_name']} 音源导入清单",
        "",
        f"- 导入时间：{manifest['created_at']}",
        f"- 导入音源：{manifest['summary']['imported_or_verified']} 首",
        f"- 来源目录：{', '.join(manifest['source_directories'])}",
        "- 匹配规则：规范化后的 `曲名 - 完整歌手`；不以仅同名作为依据。",
        "- 归档舍弃曲目未导入 SongResources。",
        "",
        "## 已导入或已验证存在",
        "",
        "| # | QQ MID | 曲目 | 完整歌手 | 来源 | SHA-256 | 状态 |",
        "|---:|---|---|---|---|---|---|",
    ]
    for number, item in enumerate(manifest["imported"], 1):
        lines.append(
            "| {number} | {track_id} | {title} | {artist} | `{source}` | `{digest}` | {action} |".format(
                number=number,
                track_id=item["track_id"],
                title=item["title"].replace("|", "\\|"),
                artist=item["artist"].replace("|", "\\|"),
                source=item["source_relative_path"].replace("|", "\\|"),
                digest=item["sha256"],
                action="已复制" if item["action"] == "copied" else "已存在且哈希一致",
            )
        )
    lines.extend([
        "",
        "## 已排除的归档舍弃曲目",
        "",
        "| QQ MID | 曲目 | 歌手 | 来源 | 原因 |",
        "|---|---|---|---|---|",
    ])
    for item in manifest["excluded_archived"]:
        lines.append(
            "| {track_id} | {title} | {artist} | `{source}` | 已存在于 `archive/removed_tracks/discarded_tracks.json` |".format(
                track_id=item["track_id"],
                title=item["title"].replace("|", "\\|"),
                artist=item["artist"].replace("|", "\\|"),
                source=item["source_relative_path"].replace("|", "\\|"),
            )
        )
    return "\n".join(lines) + "\n"


def write_manifest(manifest: dict[str, Any], stem: str) -> tuple[Path, Path]:
    MANIFEST_DIR.mkdir(exist_ok=True)
    manifest_json = MANIFEST_DIR / f"{stem}.json"
    manifest_md = MANIFEST_DIR / f"{stem}.md"
    json_temp = manifest_json.with_suffix(".json.tmp")
    md_temp = manifest_md.with_suffix(".md.tmp")
    json_temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_temp.write_text(manifest_markdown(manifest), encoding="utf-8")
    json_temp.replace(manifest_json)
    md_temp.replace(manifest_md)
    return manifest_json, manifest_md


def rebase_manifest_source_paths(stem: str) -> tuple[Path, Path]:
    """Update an existing manifest after its retained source folders are moved."""
    manifest_json = MANIFEST_DIR / f"{stem}.json"
    if not manifest_json.is_file():
        raise FileNotFoundError(f"找不到导入清单：{manifest_json}")
    manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
    manifest.setdefault("batch_name", stem)
    prefixes = {"另一台 补录", "郑灏澜 MacBook 补录"}
    for section in ("imported", "excluded_archived"):
        for item in manifest.get(section, []):
            old = Path(item["source_relative_path"])
            if not old.parts or old.parts[0] not in prefixes:
                raise ValueError(f"无法识别清单来源路径：{old}")
            item["source_relative_path"] = relative(IMPORT_SOURCE_ROOT / old.parts[0] / old.name)
    manifest["source_directories"] = [relative(path) for path in SOURCE_DIRS]
    manifest["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    return write_manifest(manifest, stem)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="执行复制并写入导入清单")
    parser.add_argument(
        "--only-missing-targets",
        action="store_true",
        help="仅导入 SongResources 中尚不存在的匹配补录文件",
    )
    parser.add_argument(
        "--manifest-stem",
        default="2026-09-21-补录音源导入",
        help="imports/ 下生成的 JSON 与 Markdown 文件名（不含扩展名）",
    )
    parser.add_argument(
        "--rebase-manifest-source-paths",
        action="store_true",
        help="在保留来源目录迁移后，更新现有清单中的来源相对路径",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.rebase_manifest_source_paths:
        manifest_json, manifest_md = rebase_manifest_source_paths(args.manifest_stem)
        print(f"已更新来源路径：{manifest_json.name}、{manifest_md.name}")
        return 0
    library = json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))
    discarded = json.loads(DISCARDED_PATH.read_text(encoding="utf-8"))
    library_exact, library_compact = build_library_index(library)
    discarded_exact, discarded_compact = build_discarded_index(discarded)

    import_rows: list[tuple[Path, Track]] = []
    archived_rows: list[tuple[Path, dict[str, Any]]] = []
    unmatched: list[Path] = []
    ambiguous: list[Path] = []
    seen_track_ids: set[str] = set()
    for source_dir in SOURCE_DIRS:
        if not source_dir.is_dir():
            raise FileNotFoundError(f"补录目录不存在：{source_dir}")
        for source in sorted(source_dir.glob("*.mp3")):
            status, record = identify(
                source,
                library_exact,
                library_compact,
                discarded_exact,
                discarded_compact,
            )
            if status == "import":
                assert isinstance(record, Track)
                if record.track_id in seen_track_ids:
                    raise ValueError(f"同一曲库条目在补录目录中出现多次：{record.track_id}")
                seen_track_ids.add(record.track_id)
                import_rows.append((source, record))
            elif status == "archived":
                assert isinstance(record, dict)
                archived_rows.append((source, record))
            elif status == "ambiguous":
                ambiguous.append(source)
            else:
                unmatched.append(source)

    if len(archived_rows) != EXPECTED_ARCHIVED or unmatched or ambiguous:
        details = [
            f"身份匹配={len(import_rows)}",
            f"归档排除={len(archived_rows)}（预期 {EXPECTED_ARCHIVED}）",
            f"未匹配={len(unmatched)}",
            f"身份歧义={len(ambiguous)}",
        ]
        if unmatched:
            details.append("未匹配文件：" + ", ".join(path.name for path in unmatched))
        if ambiguous:
            details.append("身份歧义文件：" + ", ".join(path.name for path in ambiguous))
        raise ValueError("补录批次预检失败；拒绝复制。" + "；".join(details))

    existing_rows = [(source, track) for source, track in import_rows if (TARGET_DIR / source.name).exists()]
    selected_rows = (
        [(source, track) for source, track in import_rows if not (TARGET_DIR / source.name).exists()]
        if args.only_missing_targets
        else import_rows
    )

    if not args.apply:
        print(
            f"预检通过：身份匹配 {len(import_rows)} 首，"
            f"目标已存在 {len(existing_rows)} 首，"
            f"本次将处理 {len(selected_rows)} 首，"
            f"归档排除 {len(archived_rows)} 首。传入 --apply 执行复制。"
        )
        return 0

    TARGET_DIR.mkdir(exist_ok=True)
    imported: list[dict[str, Any]] = []
    for source, track in selected_rows:
        destination = TARGET_DIR / source.name
        source_hash = sha256(source)
        action = "copied"
        if destination.exists():
            if sha256(destination) != source_hash:
                raise FileExistsError(f"目标存在但内容不同，拒绝覆盖：{destination}")
            action = "already_present_verified"
        else:
            shutil.copy2(source, destination)
            if sha256(destination) != source_hash:
                destination.unlink()
                raise IOError(f"复制后的哈希不一致，已移除目标文件：{destination}")
        imported.append({
            "track_id": track.track_id,
            "title": track.title,
            "artist": track.artist,
            "group_artist": track.group_artist,
            "album": track.album,
            "source_relative_path": relative(source),
            "destination_relative_path": relative(destination),
            "size_bytes": source.stat().st_size,
            "sha256": source_hash,
            "action": action,
        })

    excluded_archived = []
    for source, record in archived_rows:
        excluded_archived.append({
            "track_id": record["id"],
            "title": record["title"],
            "artist": record.get("full_singer") or record["artist"],
            "source_relative_path": relative(source),
            "sha256": sha256(source),
        })

    manifest = {
        "schema_version": "songbase.supplemental-audio-import/v1",
        "batch_name": args.manifest_stem,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_directories": [relative(path) for path in SOURCE_DIRS],
        "target_directory": relative(TARGET_DIR),
        "identity_rule": "normalized title plus full_singer; no title-only matches",
        "summary": {
            "source_identity_matches": len(import_rows),
            "source_targets_already_present": len(existing_rows),
            "imported_or_verified": len(imported),
            "copied": sum(item["action"] == "copied" for item in imported),
            "already_present_verified": sum(item["action"] == "already_present_verified" for item in imported),
            "excluded_archived": len(excluded_archived),
        },
        "imported": imported,
        "excluded_archived": excluded_archived,
    }
    manifest_json, manifest_md = write_manifest(manifest, args.manifest_stem)
    print(
        f"已处理 {manifest['summary']['imported_or_verified']} 首："
        f"复制 {manifest['summary']['copied']} 首，"
        f"归档排除 {manifest['summary']['excluded_archived']} 首。"
    )
    print(f"清单：{manifest_json.name}、{manifest_md.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
