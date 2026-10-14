#!/usr/bin/env python3
"""Build an exact SongBase-level Flow-transition and human-ZMPD gap inventory."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
INVESTIGATION = ROOT.parent
FLOWSET = INVESTIGATION / "Flowset-个人审美打标-Demo"
ZMPD = INVESTIGATION / "ZMPD-模型预测开发"
TRANSITION = Path("/Users/kaluozheng/Desktop/SongBase 歌曲标签库/风格衔接测试")
OUTPUT_MD = ROOT / "Flow衔接与ZMPD补标缺口清单.md"
OUTPUT_CSV = ROOT / "Flow衔接与ZMPD补标缺口清单.csv"

QQ_MID = re.compile(r"/songDetail/([A-Za-z0-9]+)")
AUDIO_SUFFIXES = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac"}
EXCLUDED_REVIEW_MARKERS = ("fifth-test", "eighth-test")
KNOWN_AUDIO_MISMATCH_QUESTIONS = {
    "style-transition-016",
    "style-transition-034",
    "style-transition-054",
    "style-transition-096",
    "style-transition-034-cross-session-10",
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def text_key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def split_filename(filename: str) -> tuple[str, str]:
    stem = Path(filename).stem
    return tuple(part.strip() for part in stem.rsplit(" - ", 1)) if " - " in stem else (stem, "")


def track_id(url: str) -> str:
    match = QQ_MID.search(str(url or ""))
    if not match:
        raise ValueError(f"SongBase 条目缺少 QQ MID：{url}")
    return f"qq:{match.group(1)}"


def markdown(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def load_songbase() -> dict[str, dict]:
    result: dict[str, dict] = {}
    for singer in read_json(ROOT / "song_base_by_artist.json")["singers"]:
        for song in singer["songs"]:
            identity = track_id(song["qq_music"])
            row = {
                "track_id": identity,
                "title": song["title"],
                "artist": song.get("full_singer") or singer["name"],
                "group_artist": singer["name"],
            }
            previous = result.get(identity)
            if previous and (previous["title"], previous["artist"]) != (row["title"], row["artist"]):
                raise ValueError(f"QQ MID 对应多个身份：{identity}")
            result[identity] = row
    return result


def identity_index(songs: dict[str, dict], artist_aliases: dict[str, str]) -> dict[tuple[str, str], set[str]]:
    index: dict[tuple[str, str], set[str]] = defaultdict(set)
    for identity, song in songs.items():
        artists = {song["artist"], song["group_artist"]}
        for artist in artists:
            artist = artist_aliases.get(artist, artist)
            index[(text_key(song["title"]), text_key(artist))].add(identity)
    return index


def audio_matches(
    songs: dict[str, dict], index: dict[tuple[str, str], set[str]], artist_aliases: dict[str, str]
) -> tuple[dict[str, list[str]], list[str]]:
    matches: dict[str, list[str]] = defaultdict(list)
    unmatched = []
    for path in sorted(ROOT.joinpath("SongResources").iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file() or path.suffix.lower() not in AUDIO_SUFFIXES:
            continue
        title, artist = split_filename(path.name)
        artist = artist_aliases.get(artist, artist)
        ids = index.get((text_key(title), text_key(artist)), set())
        if len(ids) == 1:
            matches[next(iter(ids))].append(path.name)
        else:
            unmatched.append(path.name)

    # Import manifests carry exact QQ identities and are authoritative when the
    # destination file still exists. This avoids unsafe title-only fallbacks.
    for path in sorted((ROOT / "imports").glob("*.json")):
        payload = read_json(path)
        recording_import = payload.get("schema_version") == "songbase.qq-recording-audio-import/v1"
        items = payload.get("tracks", []) if recording_import else payload.get("imported", [])
        if not isinstance(items, list):
            if recording_import:
                raise ValueError(f"入档音源清单 tracks 必须为列表：{path}")
            continue  # Final audit files may use imported for a numeric count.
        for item in items:
            identity = item.get("track_id")
            destination = ROOT / str(item.get("destination_relative_path", ""))
            if recording_import and identity in songs and destination.is_file():
                if not destination.resolve().is_relative_to((ROOT / "SongResources").resolve()):
                    raise ValueError(f"入档音源路径越界：{identity}")
                if hashlib.sha256(destination.read_bytes()).hexdigest() != item.get("sha256"):
                    raise ValueError(f"入档音源哈希不符：{identity}")
            if identity in songs and destination.is_file() and destination.name not in matches[identity]:
                matches[identity].append(destination.name)
    return matches, unmatched


def zmpd_tracks(
    songs: dict[str, dict], index: dict[tuple[str, str], set[str]], aliases: dict
) -> tuple[set[str], list[str]]:
    manifest = read_json(ZMPD / "manifests" / "training-manifest.json")
    selected_filenames = {item["filename"] for item in manifest["tracks"]}
    found: set[str] = set()
    unmatched = []
    for item in manifest["tracks"]:
        filename = aliases["filenameAliases"].get(item["filename"], item["filename"])
        title, artist = split_filename(filename)
        artist = aliases["artistAliases"].get(artist, artist)
        ids = index.get((text_key(title), text_key(artist)), set())
        if len(ids) == 1:
            found.add(next(iter(ids)))
        else:
            unmatched.append(filename)
    # Batch provenance CSVs carry explicit SongBase IDs and close benign spelling
    # variation without weakening the strict title+artist rule above.
    for filename in ("第六波测试清单.csv", "第七波测试清单.csv"):
        with (FLOWSET / filename).open(encoding="utf-8-sig", newline="") as source:
            for row in csv.DictReader(source):
                if row["track_id"] in songs and row["filename"] in selected_filenames:
                    found.add(row["track_id"])
    return found, unmatched


def transition_counts(songs: dict[str, dict]) -> tuple[Counter, Counter, list[str], int]:
    # Use the relationship analysis's canonical, audited primary rows so that
    # question-file candidate IDs and review-file schemas cannot lose evidence.
    outgoing: Counter = Counter()
    incoming: Counter = Counter()
    batches: set[str] = set()
    questions: set[tuple[str, str]] = set()
    seen: set[tuple[str, str, str]] = set()
    path = FLOWSET / "flowset_transition_analysis_rows.csv"
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {"status", "batch", "question_id", "slot", "source_id", "target_id"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"衔接分析 CSV 缺少必要字段：{path}")
        for row in reader:
            if row["status"] != "primary":
                continue
            source_id, target_id = row["source_id"], row["target_id"]
            if source_id not in songs or target_id not in songs:
                raise ValueError(f"主分析衔接身份不在 SongBase：{source_id} → {target_id}")
            key = (row["batch"], row["question_id"], row["slot"])
            if key in seen:
                raise ValueError(f"重复的主分析候选记录：{key}")
            seen.add(key)
            batches.add(row["batch"])
            questions.add((row["batch"], row["question_id"]))
            outgoing[source_id] += 1
            incoming[target_id] += 1
    if not seen:
        raise ValueError("衔接分析 CSV 没有有效主分析记录")
    return outgoing, incoming, sorted(batches), len(questions)


def catalog_ids(index: dict[tuple[str, str], set[str]], aliases: dict) -> set[str]:
    result = set()
    for track in read_json(ROOT / "歌曲特征.json")["tracks"]:
        artist = aliases["artistAliases"].get(track["artist"], track["artist"])
        ids = index.get((text_key(track["title"]), text_key(artist)), set())
        identity = track.get("songBaseId") or track.get("trackId", "")
        if identity.startswith("qq:"):
            if identity not in ids:
                raise ValueError(f"catalog QQ 身份与 title + artist 冲突：{identity}")
            result.add(identity)
        elif len(ids) == 1:
            result.add(next(iter(ids)))
    return result


def table(rows: list[dict]) -> list[str]:
    lines = [
        "| SongBase ID | 歌曲 | 艺人 | 当前 catalog | 缺什么 |",
        "|---|---|---|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['track_id']} | {markdown(row['title'])} | {markdown(row['artist'])} | "
            f"{'是' if row['in_catalog'] else '否'} | {row['needs']} |"
        )
    return lines


def main() -> None:
    aliases = read_json(ROOT / "song_identity_aliases.json")
    songs = load_songbase()
    index = identity_index(songs, aliases["artistAliases"])
    audio, unmatched_audio = audio_matches(songs, index, aliases["artistAliases"])
    zmpd, unmatched_zmpd = zmpd_tracks(songs, index, aliases)
    outgoing, incoming, review_files, response_count = transition_counts(songs)
    tags = read_json(ROOT / "song_tags.json")["tracks"]
    catalog = catalog_ids(index, aliases)
    wave7_audit = read_json(ROOT / "第七批ZMPD合并审计.json")
    pending_rerecording_ids = set(read_json(ROOT / "待重录清单.json")["tracks"])
    manual_discarded_ids = set(read_json(ROOT / "待舍弃归档清单.json")["tracks"]) - pending_rerecording_ids

    rows = []
    for identity, song in songs.items():
        audio_count = len(audio.get(identity, []))
        formal_tag = identity in tags
        stp = outgoing[identity] + incoming[identity] > 0
        has_zmpd = identity in zmpd
        manual_discarded = identity in manual_discarded_ids
        pending_rerecording = identity in pending_rerecording_ids
        needs = []
        if not manual_discarded and not stp:
            needs.append("Flow衔接")
        if not manual_discarded and not has_zmpd:
            needs.append("ZMPD")
        readiness = "待归档舍弃" if manual_discarded else "可立即补标"
        blockers = ["待重录"] if pending_rerecording else []
        if audio_count != 1:
            blockers.append("音频身份" if audio_count == 0 else "多音频版本")
        if not formal_tag:
            blockers.append("正式Tag")
        if blockers and not manual_discarded:
            readiness = "先修：" + " + ".join(blockers)
        rows.append({
            **song,
            "formal_tag": formal_tag,
            "audio_status": "unique" if audio_count == 1 else ("missing" if audio_count == 0 else "multiple"),
            "audio_files": " | ".join(audio.get(identity, [])),
            "in_catalog": identity in catalog,
            "stp_outgoing": outgoing[identity],
            "stp_incoming": incoming[identity],
            "stp_labeled": stp,
            "zmpd_labeled": has_zmpd,
            "manual_discarded": manual_discarded,
            "pending_rerecording": pending_rerecording,
            "needs": "归档舍弃" if manual_discarded else (" + ".join(needs) if needs else "无需补标"),
            "readiness": readiness,
        })
    rows.sort(key=lambda row: (row["readiness"] != "可立即补标", row["needs"], text_key(row["artist"]), text_key(row["title"])))

    fieldnames = list(rows[0])
    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    ready_gaps = [row for row in rows if row["readiness"] == "可立即补标" and row["needs"] != "无需补标"]
    categories = {
        name: [row for row in ready_gaps if row["needs"] == name]
        for name in ("Flow衔接 + ZMPD", "Flow衔接", "ZMPD")
    }
    blocked = [
        row for row in rows
        if row["readiness"] not in {"可立即补标", "待归档舍弃"} and row["needs"] != "无需补标"
    ]
    complete = [row for row in rows if row["needs"] == "无需补标"]
    manual_discarded = [row for row in rows if row["manual_discarded"]]
    pending_wave6 = read_json(ROOT / "第六批ZMPD合并审计.json")["pending"]
    pending_wave7 = wave7_audit["pending"]

    lines = [
        "# Flow 衔接与 ZMPD 补标缺口清单",
        "",
        f"> 生成时间：{datetime.now(timezone.utc).isoformat()}。SongBase 身份总数：{len(songs)}。",
        "",
        "## 口径",
        "",
        "- **ZMPD 已标**：进入训练 manifest 的完整人工五维标注；模型预测不算人工已标。",
        "- 上述 ZMPD 是歌曲级历史覆盖，不保证当前重录版本有人工真值；当前特征库以音频 SHA-256 匹配，历史标注未匹配的新版本保留预测，详见 `歌曲特征库-1204首升级说明.md`。",
        "- **Flow 衔接已标**：至少一次出现在有效的方向性 A→B 测试中（前曲或候选曲）。第五组、第八组按此前约定排除；已知错音频题也排除。第 11–13 组已纳入新版关系分析与本清单。",
        "- **可立即补标**：SongBase 身份唯一、恰有一个可播放本地音频、已有正式 Tag。候选 Tag 不算正式 Tag；待重录曲目先修音源，不进入可立即补标队列。",
        "- Flow 衔接的完整单位是“有方向的歌曲对”。这里的歌曲级“已标”只表示已有至少一条直接证据，不代表它和全库其他歌曲的组合都测过。",
        "",
        "## 汇总",
        "",
        "| 指标 | 数量 |",
        "|---|---:|",
        f"| SongBase 唯一歌曲 | {len(songs)} |",
        f"| 正式 Tag | {sum(row['formal_tag'] for row in rows)} |",
        f"| 唯一音频身份 | {sum(row['audio_status'] == 'unique' for row in rows)} |",
        f"| 当前 catalog 可确认身份 | {len(catalog)} |",
        f"| 已有人工 ZMPD | {sum(row['zmpd_labeled'] for row in rows)} |",
        f"| 已有直接 Flow 衔接证据 | {sum(row['stp_labeled'] for row in rows)} |",
        f"| 两项都已有 | {len(complete)} |",
        f"| 可立即补标且仍有缺口 | {len(ready_gaps)} |",
        f"| 有缺口但要先修 Tag/音频（含待重录） | {len(blocked)} |",
        f"| 当前待重录 | {len(pending_rerecording_ids & songs.keys())} |",
        f"| 已决定归档舍弃（不再推荐补标） | {len(manual_discarded)} |",
        "",
        "## 第六批合并结果",
        "",
        "- 第六批 100 首均通过完整标注与唯一音频身份校验。",
        "- 其中 32 首已在 480 首 catalog，已用人工 ZMPD 真值覆盖旧预测。",
        f"- 历史 480 首快照另有 {len(pending_wave6)} 首待扩库；当前是否入库以本清单的 catalog 列为准，历史名单见 `第六批ZMPD合并审计.json`。",
        "",
        "## 第七批合并结果",
        "",
        "- 第七批导出 100 首：98 首完成，其中 5 首是盲测锚点、93 首是新增真值；另 2 首由用户明确决定归档舍弃。",
        f"- 历史 480 首快照中，93 首新增真值的 {wave7_audit['mergedExistingTransitionCompleteTracks']} 首已入库、另 {len(pending_wave7)} 首待扩库；当前是否入库以本清单的 catalog 列为准。",
        "- 5 首锚点完整保留重复测量，但训练真值继续采用第七波之前的标注，避免用归一化样本覆盖基准。",
        f"- 上述为历史审计口径；当前任务以独立清单为准：待舍弃 {len(manual_discarded)} 首、待重录 {len(pending_rerecording_ids & songs.keys())} 首。",
        "",
        "## 可立即补标名单",
        "",
    ]
    for name, subset in categories.items():
        lines.extend([f"### 还缺 {name}（{len(subset)} 首）", ""])
        lines.extend(table(subset) if subset else ["无。"])
        lines.append("")
    lines.extend([
        "## 暂不能直接补标",
        "",
        f"共有 {len(blocked)} 首仍有标注缺口，但应先解决正式 Tag、音频身份或待重录任务。完整逐曲状态在 [Flow衔接与ZMPD补标缺口清单.csv](Flow衔接与ZMPD补标缺口清单.csv)。",
        "",
        "## 待重录",
        "",
    ])
    lines.extend(table([row for row in rows if row["pending_rerecording"]]) or ["无。"])
    lines.extend(["", "## 待归档舍弃", ""])
    lines.extend(table(manual_discarded) if manual_discarded else ["无。"])
    lines.extend([
        "",
        "## 数据质量附注",
        "",
        f"- 纳入 Flow 衔接覆盖统计的 review：{len(review_files)} 份、{response_count} 道有效回答。",
        f"- 无法按严格 title + artist 唯一映射的本地音频：{len(unmatched_audio)} 个；未自动用 title-only 猜测。",
        f"- 仍无法唯一映射到 SongBase 的人工 ZMPD 文件名：{len(unmatched_zmpd)} 个；保留在训练 manifest，但不误记到某个 SongBase ID。",
        "- 全部逐曲状态、前曲/后曲直接证据次数、音频文件名与阻塞原因都在 CSV。",
        "",
    ])
    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({
        "songbaseTracks": len(songs),
        "humanZmpdTracks": len(zmpd),
        "directTransitionTracks": sum(row["stp_labeled"] for row in rows),
        "readyGaps": len(ready_gaps),
        "blockedGaps": len(blocked),
        "outputMarkdown": str(OUTPUT_MD),
        "outputCsv": str(OUTPUT_CSV),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
