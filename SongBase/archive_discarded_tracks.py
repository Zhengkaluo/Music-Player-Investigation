#!/usr/bin/env python3
"""Archive discarded SongBase tracks and remove them from every main data store.

Single-track usage requires the stable ID plus an artist/title assertion:

    python3 SongBase/archive_discarded_tracks.py \
      --track-id qq:... --artist "Artist" --title "Title" --reason "人工舍弃"

For a batch, pass a JSON file containing a list (or ``{"tracks": [...]}``) of:

    {"id": "qq:...", "artist": "Artist", "title": "Title", "reason": "..."}
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path


BASE = Path(__file__).resolve().parent
LIBRARY_PATH = BASE / "song_base_by_artist.json"
TAGS_PATH = BASE / "song_tags.json"
CANDIDATES_PATH = BASE / "song_tag_candidates.json"
RESOURCES_DIR = BASE / "SongResources"
ARCHIVE_DIR = BASE / "archive" / "removed_tracks"
MANIFEST_PATH = ARCHIVE_DIR / "discarded_tracks.json"
QQ_MID_RE = re.compile(r"/songDetail/([A-Za-z0-9]+)")
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav"}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def track_id(song: dict) -> str:
    match = QQ_MID_RE.search(song.get("qq_music", ""))
    if not match:
        raise ValueError(f"歌曲缺少 QQ MID: {song.get('title', '未知歌曲')}")
    return "qq:" + match.group(1)


def normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).casefold().strip()


def compact(value: str) -> str:
    return "".join(char for char in normalized(value) if char.isalnum())


def clean_filename(value: str) -> str:
    value = unicodedata.normalize("NFC", str(value or ""))
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", value)
    return re.sub(r"\s+", " ", value).strip(" .") or "未命名"


def artist_variants(group_artist: str, full_singer: str) -> list[str]:
    result: list[str] = []
    for artist in (group_artist, full_singer):
        artist = str(artist or "").strip()
        if not artist:
            continue
        result.append(artist)
        for separator in (",", "，", "&", "、"):
            primary = artist.split(separator, 1)[0].strip()
            if primary:
                result.append(primary)
    return list(dict.fromkeys(result))


def find_audio_files(song: dict, group_artist: str) -> list[Path]:
    if not RESOURCES_DIR.exists():
        return []
    wanted = set()
    for artist in artist_variants(group_artist, song.get("full_singer", "")):
        wanted.add(compact(f"{clean_filename(song.get('title', ''))} - {clean_filename(artist)}"))
    return [
        path
        for path in RESOURCES_DIR.iterdir()
        if path.is_file()
        and path.suffix.casefold() in AUDIO_EXTENSIONS
        and compact(path.stem) in wanted
    ]


def default_manifest() -> dict:
    return {
        "schema_version": "songbase.discarded-tracks/v1",
        "updated_at": date.today().isoformat(),
        "policy": {
            "canonical_directory": "SongBase/archive/removed_tracks",
            "meaning": "归档舍弃：记录保留在本清单，且不得出现在主 SongBase、正式标签、候选或主浏览页中。",
            "stable_id": "QQ Music MID",
        },
        "tracks": {},
    }


def load_requests(args: argparse.Namespace) -> list[dict]:
    if args.batch:
        payload = load_json(args.batch)
        requests = payload.get("tracks", []) if isinstance(payload, dict) else payload
        if not isinstance(requests, list) or not requests:
            raise ValueError("批次文件必须是非空列表，或包含非空 tracks 列表")
    else:
        if not (args.track_id and args.artist and args.title):
            raise ValueError("单首舍弃必须同时提供 --track-id、--artist 和 --title")
        requests = [{"id": args.track_id, "artist": args.artist, "title": args.title, "reason": args.reason}]

    normalized_requests = []
    for request in requests:
        if not all(request.get(field) for field in ("id", "artist", "title")):
            raise ValueError(f"每条请求必须包含 id、artist、title: {request!r}")
        if not str(request["id"]).startswith("qq:"):
            raise ValueError(f"舍弃 ID 必须使用 qq:MID: {request['id']!r}")
        normalized_requests.append(
            {
                "id": str(request["id"]),
                "artist": str(request["artist"]),
                "title": str(request["title"]),
                "reason": str(request.get("reason") or args.reason or "人工复核舍弃"),
            }
        )
    ids = [request["id"] for request in normalized_requests]
    if len(ids) != len(set(ids)):
        raise ValueError("批次文件含重复 MID")
    return normalized_requests


def index_library(library: dict) -> dict[str, list[tuple[dict, dict]]]:
    result: dict[str, list[tuple[dict, dict]]] = {}
    for singer in library.get("singers", []):
        for song in singer.get("songs", []):
            result.setdefault(track_id(song), []).append((singer, song))
    return result


def write_markdown(library: dict) -> None:
    lines = [
        "# QQ 音乐曲库（按歌手索引）",
        f"> {library['total_singers']} 位艺人 · {library['total_unique_songs']} 首歌曲 · {library['export_date']}",
        f"> YouTube: {sum(s['youtube'] for s in library['singers'])} | Bilibili: {sum(s['bilibili'] for s in library['singers'])}",
        "",
    ]
    for singer in library["singers"]:
        flags = []
        if singer["youtube"]:
            flags.append(f"YT:{singer['youtube']}")
        if singer["bilibili"]:
            flags.append(f"BL:{singer['bilibili']}")
        suffix = f" · {', '.join(flags)}" if flags else ""
        lines.extend(
            [
                f"## {singer['name']} ({singer['song_count']}首{suffix})",
                "| # | 歌曲 | 专辑 | 时长 | QQ音乐 | YouTube |",
                "|---|------|------|------|--------|---------|",
            ]
        )
        for index, song in enumerate(singer["songs"], 1):
            seconds = int(song.get("duration") or 0)
            duration = f"{seconds // 60}:{seconds % 60:02d}"
            qq = f"[🔗]({song['qq_music']})" if song.get("qq_music") else "-"
            youtube = f"[▶️]({song['youtube']})" if song.get("youtube") else "-"
            lines.append(f"| {index} | {song['title']} | {song.get('album', '')} | {duration} | {qq} | {youtube} |")
        lines.append("")
    (BASE / "song_base_by_artist.md").write_text("\n".join(lines), encoding="utf-8")


def create_backups(timestamp: str) -> None:
    for path, stem in (
        (LIBRARY_PATH, "song_base"),
        (TAGS_PATH, "song_tags"),
        (CANDIDATES_PATH, "song_tag_candidates"),
    ):
        destination = BASE / "archive" / f"{stem}_before_discard_{timestamp}.json"
        shutil.copy2(path, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description="将曲目归档舍弃，并从所有主数据与浏览页移除")
    parser.add_argument("--track-id")
    parser.add_argument("--artist")
    parser.add_argument("--title")
    parser.add_argument("--batch", type=Path)
    parser.add_argument("--reason", default="人工复核舍弃")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    if args.batch and any((args.track_id, args.artist, args.title)):
        parser.error("--batch 不能与单首参数混用")

    requests = load_requests(args)
    library = load_json(LIBRARY_PATH)
    tags = load_json(TAGS_PATH)
    candidates = load_json(CANDIDATES_PATH)
    manifest = load_json(MANIFEST_PATH) if MANIFEST_PATH.exists() else default_manifest()
    if manifest.get("schema_version") != "songbase.discarded-tracks/v1":
        raise ValueError("舍弃归档清单 schema_version 无效")
    library_index = index_library(library)

    prepared = []
    for request in requests:
        matches = library_index.get(request["id"], [])
        if not matches:
            archived = manifest.get("tracks", {}).get(request["id"])
            if archived and normalized(archived.get("artist")) == normalized(request["artist"]) and normalized(archived.get("title")) == normalized(request["title"]):
                print(f"已在归档中，跳过: {request['id']} | {request['artist']} | {request['title']}")
                continue
            raise ValueError(f"主曲库中找不到 MID: {request['id']}")
        singer, song = matches[0]
        if normalized(singer.get("name")) != normalized(request["artist"]) or normalized(song.get("title")) != normalized(request["title"]):
            raise ValueError(
                f"艺人/曲名断言失败: {request['id']} 实际为 {singer.get('name')} — {song.get('title')}"
            )
        audio_files = find_audio_files(song, singer.get("name", ""))
        prepared.append((request, singer, song, audio_files))

    if not prepared:
        return 0
    for request, _singer, song, audio_files in prepared:
        print(
            f"{'预览' if args.dry_run else '归档'}: {request['id']} | {request['artist']} — {request['title']}"
            f" | 本地音频 {len(audio_files)}"
        )
    if args.dry_run:
        return 0

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    create_backups(timestamp)
    today = date.today().isoformat()

    request_by_id = {request["id"]: (request, singer, song, audio_files) for request, singer, song, audio_files in prepared}
    for singer in library.get("singers", []):
        singer["songs"] = [song for song in singer.get("songs", []) if track_id(song) not in request_by_id]
        singer["song_count"] = len(singer["songs"])
        singer["youtube"] = sum(bool(song.get("youtube")) for song in singer["songs"])
        singer["bilibili"] = sum(bool(song.get("bilibili")) for song in singer["songs"])
    library["singers"] = [singer for singer in library.get("singers", []) if singer.get("songs")]

    for mid, (request, singer, song, audio_files) in request_by_id.items():
        archived_audio = []
        for source in audio_files:
            destination = ARCHIVE_DIR / source.name
            if destination.exists() and destination.resolve() != source.resolve():
                raise FileExistsError(f"归档音频已存在，未覆盖: {destination}")
            if source.exists():
                shutil.move(str(source), str(destination))
            archived_audio.append(destination.name)
        manifest["tracks"][mid] = {
            "id": mid,
            "title": song.get("title", ""),
            "artist": singer.get("name", ""),
            "full_singer": song.get("full_singer", ""),
            "album": song.get("album", ""),
            "duration": song.get("duration", 0),
            "qq_music": song.get("qq_music", ""),
            "youtube": song.get("youtube", ""),
            "bilibili": song.get("bilibili", ""),
            "discarded_at": today,
            "reason": request["reason"],
            "source": "archive_discarded_tracks.py",
            "former_formal_tag": tags.get("tracks", {}).pop(mid, None),
            "former_candidate": candidates.get("tracks", {}).pop(mid, None),
            "archived_audio": archived_audio,
        }

    all_ids = {track_id(song) for singer in library.get("singers", []) for song in singer.get("songs", [])}
    library["total_unique_songs"] = len(all_ids)
    library["total_singers"] = len(library.get("singers", []))
    library["export_date"] = today
    tags["updated_at"] = today
    candidates.setdefault("sample", {})["size"] = len(candidates.get("tracks", {}))
    candidates["sample"]["population"] = len(candidates.get("tracks", {}))
    candidates["pruned_at"] = today
    manifest["updated_at"] = today

    if set(manifest["tracks"]) & all_ids:
        raise ValueError("归档 MID 仍残留在主曲库")
    if set(manifest["tracks"]) & set(tags.get("tracks", {})):
        raise ValueError("归档 MID 仍残留在正式标签")
    if set(manifest["tracks"]) & set(candidates.get("tracks", {})):
        raise ValueError("归档 MID 仍残留在候选标签")

    write_json(LIBRARY_PATH, library)
    write_json(TAGS_PATH, tags)
    write_json(CANDIDATES_PATH, candidates)
    write_json(MANIFEST_PATH, manifest)
    write_markdown(library)

    if not args.no_build:
        for script in (
            "build_song_base_browser.py",
            "build_song_tags_browser.py",
            "build_discarded_tracks_browser.py",
        ):
            subprocess.run([sys.executable, str(BASE / script)], cwd=BASE.parent, check=True)

    print(f"完成归档舍弃 {len(prepared)} 首；归档总数 {len(manifest['tracks'])} 首")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
