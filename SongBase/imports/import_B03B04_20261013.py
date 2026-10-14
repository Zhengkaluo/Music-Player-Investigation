#!/usr/bin/env python3
"""One-off B03/B04 preflight and apply, reusing SongBase's verified audio importer."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
import wave
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parents[1]
FLOW = Path("/Users/kaluozheng/MusicPlayer-FlowSystem")
sys.path[:0] = [str(BASE), str(FLOW / "tools")]
from import_recording_delivery import digest, write_json
from publish_qq_recordings import copy_verified, flat_filenames, validate_take
from record_system_audio import inspect_wave, inspect_mp3
from manage_albums import recompute_stats
from build_song_tags_browser import clean_filename
NAME = "2026-10-13-歌单补充B03B04-116首"
BATCH = FLOW / "workspace/recordings/歌单补充-B03-B04-116首-2026-10-12"
RETRY = FLOW / "workspace/recordings/歌单补充-B03B04-2首无回音重录-2026-10-13"
REJECTED = FLOW / "workspace/recordings/歌单补充-B03B04-补录2首-2026-10-13"
STAGE = BASE / "imports" / (NAME + "验收音源")
PRE = BASE / "imports" / (NAME + "入库准备.json")
RECEIPT = BASE / "imports" / (NAME + "交付凭据.json")
LEDGER = BASE / "imports" / (NAME + "正式入档.json")
SNAP = BASE / "archive/snapshots/playlist-expansion/2026-10-13-B03B04-116首入库前"
PROGRESS = BASE / "reviews/468首候选曲目录制与入库进度-2026-10-12.json"
PLAN = BASE / "reviews/468首候选曲目录制计划-2026-10-11.json"
REVIEW = BASE / "reviews/试听-22首-2026-10-13/试听清单.json"
def read(p):
    return json.loads(Path(p).read_text())
def now():
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
def checked(files):
    for f in files:
        assert digest(Path(f["path"])) == f["sha256"], f["path"]
def prepare():
    library = read(BASE / "song_base_by_artist.json")
    assert library["total_unique_songs"] == 1437, "主库已变化，先重新核对"
    main_ids = {z["qq_music"].rsplit("/", 1)[-1] for a in library["singers"] for z in a["songs"]}
    manifest = read(BATCH / "manifest.json")["tracks"]
    rows = [r for r in read(PLAN)["tracks"] if r["batch_id"] in ("B03", "B04")]
    assert len(rows) == len(manifest) == 116
    by_mid = {r["song_mid"]: r for r in rows}
    state = read(BATCH / "status.json")["tracks"]
    retry_state = read(RETRY / "status.json")["tracks"]
    retry_manifest = read(RETRY / "manifest.json")
    replacement = retry_manifest["versionReplacement"]
    assert replacement["authorization"] == "改录 Para Mi 专辑版（推荐）"
    assert replacement["originalSongMid"] == "004a1aRp0WI3rt"
    assert replacement["actualSongMid"] == "000VIQsR1lXb5A"
    reject = read(REJECTED / "人工拒绝交付-2026-10-13.json")
    assert reject["status"] == "superseded-do-not-deliver"
    reviewed = {t["id"]: t for t in read(REVIEW)["tracks"]}
    decisions = {t["id"]: t for t in read(BATCH / "dashboard-review-decisions.json")["decisions"]}
    exceptions = {t["id"]: t for t in read(BATCH / "manual-delivery-exceptions.json")["manualExceptions"]}
    playlists = read(BASE / "qqmusic_playlists.json")[-2:]
    groups = {a["name"].casefold(): a["name"] for a in library["singers"]}
    originals = []
    tasks = []
    for target in manifest:
        original = target["id"]
        r = copy.deepcopy(by_mid[original])
        assert (target["title"], target["artist"], target["duration"]) == (r["title"], r["artist"], r["duration_seconds"])
        source = next(s for p in playlists for s in p["songs"] if s["song_mid"] == original)
        assert (source["name"], source["singer"], source["album"], source["interval"]) == (r["title"], r["artist"], r["album"], r["duration_seconds"])
        artists = source["artists"]
        if original == replacement["originalSongMid"]:
            selected = replacement["selected"]
            assert selected["artists"] == ["Cuco", "Jean Carter"] and selected["duration_seconds"] == 201
            r.update(song_mid=selected["song_mid"], song_id=selected["song_id"], song_type=selected["song_type"], album=selected["album"], url=selected["url"])
            r["version_replacement"] = replacement
            artists = selected["artists"]
        ident = r["song_mid"]
        assert ident not in main_ids
        group = groups.get(artists[0].casefold(), artists[0])
        r.update(group_artist=group, artists=artists, original_song_mid=original)
        if original in ("003j9c1S33TtSQ", "004a1aRp0WI3rt"):
            item = retry_state[ident]
            assert item["status"] == "accepted"
            files = item["files"]
            checked(files)
            take_path = next(Path(f["path"]) for f in files if f["path"].endswith(".json"))
            wav = next(Path(f["path"]) for f in files if f["path"].endswith(".wav"))
            mp3 = next(Path(f["path"]) for f in files if f["path"].endswith(".mp3"))
            take = read(take_path)
            track = next(t for t in retry_manifest["tracks"] if t["id"] == ident)
            d = read(RETRY / "delivery-flat-mp3.json")
            entry = next(t for t in d["tracks"] if t["id"] == ident)
            assert entry["status"] == "accepted"
            assert digest(Path(d["destination"]) / entry["files"][0]["path"]) == digest(mp3) == entry["files"][0]["sha256"]
            status = "accepted"
        elif original in exceptions:
            ex = exceptions[original]
            assert ex["status"] == "manual-approved-exception" and decisions[original]["decision"] == "approved-full"
            item = state[original]
            assert item["status"] == "failed"
            take_path = Path(item["attempts"][-1])
            take = read(take_path)
            wav = Path(ex["source"])
            assert wav == Path(take["quality"]["wav"]) and digest(wav) == ex["sourceSha256"]
            mp3 = BATCH / "reviewed/2026-10-13/manual-export" / (ident + ".mp3")
            files = [dict(path=str(wav), sha256=digest(wav)), dict(path=str(take_path), sha256=digest(take_path))]
            track = target
            status = "manual-approved-exception"
        else:
            item = state[original]
            assert item["status"] == "accepted"
            files = item["files"]
            checked(files)
            take_path = next(Path(f["path"]) for f in files if f["path"].endswith(".json"))
            take = read(take_path)
            track = target
            wav = next(Path(f["path"]) for f in files if f["path"].endswith(".wav"))
            mp3 = next(Path(f["path"]) for f in files if f["path"].endswith(".mp3"))
            status = "accepted"
        assert (take["track"]["id"], take["track"]["title"], take["track"]["artist"]) == (ident, r["title"], r["artist"])
        if status == "accepted":
            validate_take(take, track, take["quality"])
        else:
            assert take["playback"]["ended"] and take["playback"]["maxTime"] >= r["duration_seconds"] - 2
            assert take["playback"]["error"] == take["quality"]["error"] == "Capture is clipped or too quiet"
            assert not take["quality"]["capture"].get("error") and take["quality"]["capture"]["droppedFrames"] == 0
            assert take["quality"]["capture"]["elapsedSeconds"] - take["quality"]["durationSeconds"] < .5
        trim = decisions.get(original, {}).get("trimmedTailSeconds", 0)
        if trim:
            evidence = reviewed[original]["trim_evidence"]
            assert digest(wav) == evidence["source_wav_sha256"]
            wav = Path(evidence["derived_wav"])
            mp3 = Path(reviewed[original]["current_source"])
            assert digest(wav) == evidence["derived_wav_sha256"]
            assert digest(mp3) == reviewed[original]["current_source_sha256"]
            assert evidence["source_frames"] - evidence["derived_frames"] == evidence["sample_rate"] == 44100
        filename = flat_filenames([dict(id=ident, title=r["title"], artist=r["artist"])])[ident]
        destination = BASE / "SongResources" / filename
        if destination.exists():
            r["filename_conflict"] = dict(existing_path=str(destination), existing_sha256=digest(destination),
                                          policy="保留旧版本，用浏览器已有的曲名[专辑]-完整歌手命名规则隔离新版本")
            filename = f'{clean_filename(r["title"])} [{clean_filename(r["album"])}] - {clean_filename(r["artist"])}.mp3'
            destination = BASE / "SongResources" / filename
        assert not destination.exists(), str(destination)
        assert not mp3.is_relative_to(REJECTED)
        r.update(recording_status=status, source_wav=str(wav), source_mp3=str(mp3), sha256=digest(mp3),
                 original_take_files=files, take_path=str(take_path), trimmed_tail_seconds=trim, filename=filename,
                 destination_relative_path="SongResources/" + filename, user_reviewed=original in decisions)
        originals.extend(files)
        tasks.append(r)
    assert len({t["song_mid"] for t in tasks}) == len({t["filename"].casefold() for t in tasks}) == 116
    def qa(r):
        w = inspect_wave(Path(r["source_wav"]))
        m = inspect_mp3(Path(r["source_mp3"]))
        assert not w["silent"] and w["rmsDbFS"] >= -45
        assert r["duration_seconds"] - 1 <= w["durationSeconds"] <= r["duration_seconds"] + 5
        assert abs(m["durationSeconds"] - w["durationSeconds"]) < .1
        if r["recording_status"] == "accepted":
            assert w["clippedSamples"] == 0
        else:
            assert w["clippedSamples"] == exceptions[r["song_mid"]]["originalClippedSamples"]
        r["quality"] = dict(w, mp3=m)
        return r
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = list(pool.map(qa, tasks))
    result = dict(schema_version="songbase.recording-import-preflight/v1", date="2026-10-13", source_batch=str(BATCH),
                  retry_batch=str(RETRY), rejected_batch=str(REJECTED), staging=str(STAGE),
                  summary=dict(tracks=116, automatic=107, manual_exceptions=9, trimmed=6, replacements=1),
                  original_files=originals, tracks=tasks)
    assert sum(r["recording_status"] == "manual-approved-exception" for r in tasks) == 9
    assert sum(r["trimmed_tail_seconds"] == 1 for r in tasks) == 6
    write_json(PRE, result)
    print(json.dumps(result["summary"], ensure_ascii=False), flush=True)

def apply():
    data = read(PRE)
    assert not SNAP.exists() and not LEDGER.exists(), "已执行过或有同名快照，拒绝重复覆盖"
    library = read(BASE / "song_base_by_artist.json")
    assert library["total_unique_songs"] == 1437
    checked(data["original_files"])
    assert all(digest(Path(t["source_mp3"])) == t["sha256"] for t in data["tracks"])
    paths = [p for pattern in ("*.json", "*.md", "*.html") for p in BASE.glob(pattern)] + [PLAN, PROGRESS]
    SNAP.mkdir(parents=True)
    for p in paths:
        copy_verified(p, SNAP / p.relative_to(BASE), digest(p))
    for p in (REVIEW, BATCH / "dashboard-review-decisions.json", BATCH / "manual-delivery-exceptions.json"):
        copy_verified(p, SNAP / "recording-review" / p.name, digest(p))
    protected = {p.name: digest(p) for p in BASE.glob("*.json") if p.name not in ("song_base_by_artist.json", "待录制清单.json")}
    training = BASE.parent / "ZMPD-模型预测开发/manifests/training-manifest.json"
    protected["../ZMPD-模型预测开发/manifests/training-manifest.json"] = digest(training)
    write_json(SNAP / "protected-hashes.json", protected)
    old_audio = {p.name: digest(p) for p in (BASE / "SongResources").iterdir() if p.is_file()}
    write_json(SNAP / "original-audio-hashes.json", old_audio)
    receipt = dict(schemaVersion="flowset.qq-recording-delivery/v1", deliveryMode="flat-mp3",
                   destination=str(STAGE), expected=116, accepted=107, manualApprovedExceptions=9, tracks=[])
    metadata = []
    pending = read(BASE / "待录制清单.json")
    assert pending["recordable_tracks"] == []
    groups = {a["name"]: a for a in library["singers"]}
    for i, t in enumerate(data["tracks"], 1):
        source = Path(t["source_mp3"])
        copy_verified(source, STAGE / t["filename"], t["sha256"])
        receipt["tracks"].append(dict(id=t["song_mid"], title=t["title"], artist=t["artist"], status=t["recording_status"],
                                     files=[dict(path=t["filename"], sha256=t["sha256"])], quality=t["quality"],
                                     original_song_mid=t["original_song_mid"], source=str(source), take_path=t["take_path"],
                                     trimmedTailSeconds=t["trimmed_tail_seconds"], version_replacement=t.get("version_replacement")))
        song = dict(title=t["title"], full_singer=t["artist"], album=t["album"], duration=t["duration_seconds"],
                    qq_music=t["url"], youtube="", bilibili="")
        if t["group_artist"] not in groups:
            groups[t["group_artist"]] = dict(name=t["group_artist"], song_count=0, youtube=0, bilibili=0, songs=[])
            library["singers"].append(groups[t["group_artist"]])
        groups[t["group_artist"]]["songs"].append(song)
        metadata.append(dict(track_id="qq:" + t["song_mid"], title=t["title"], full_singer=t["artist"],
                             group_artist=t["group_artist"], artists=t["artists"], album=t["album"],
                             duration_seconds=t["duration_seconds"], song_id=t["song_id"], song_type=t["song_type"],
                             qq_music=t["url"], source_playlists=t["source_playlists"], original_song_mid=t["original_song_mid"],
                             version_replacement=t.get("version_replacement"), action="added",
                             destination_relative_path=t["destination_relative_path"]))
        pending["recordable_tracks"].append(dict(t, track_id="qq:" + t["song_mid"], full_singer=t["artist"],
                                                sequence=i, recording_batch=3 if t["batch_id"] == "B03" else 4,
                                                playlist_position=t["sequence_in_batch"], target_relative_path=t["destination_relative_path"]))
    recompute_stats(library)
    assert library["total_unique_songs"] == 1553
    write_json(RECEIPT, receipt)
    meta = dict(schema_version="songbase.playlist-track-import/v1", date="2026-10-13",
                source_playlists=["咖啡厅", "可以放"], scope="B03/B04 only; 116 additions, one authorized album-version replacement",
                summary=dict(metadata_added=116, audio_imported=116, formal_tags_added=0, zmpd_annotations_added=0),
                audio_manifest=LEDGER.name, snapshot_directory=str(SNAP.relative_to(BASE)), tracks=metadata)
    write_json(BASE / "imports" / (NAME + "元数据导入.json"), meta)
    write_json(BASE / "song_base_by_artist.json", library)
    write_json(BASE / "待录制清单.json", pending)
    command = [sys.executable, str(BASE / "import_recording_delivery.py"), "--receipt", str(RECEIPT), "--staging", str(STAGE),
               "--batch-name", NAME + "正式入档", "--review-decisions", str(BATCH / "dashboard-review-decisions.json")]
    subprocess.run(command, check=True)
    ledger = read(LEDGER)
    for entry, t in zip(ledger["tracks"], data["tracks"]):
        entry.update(original_song_mid=t["original_song_mid"], original_take_files=t["original_take_files"],
                     source_recording=t["source_mp3"], take_path=t["take_path"], quality=t["quality"],
                     version_replacement=t.get("version_replacement"))
    write_json(LEDGER, ledger)
    for command in (["manage_albums.py", "rebuild"], ["build_song_base_browser.py"], ["build_song_tags_browser.py"]):
        subprocess.run([sys.executable, str(BASE / command[0]), *command[1:]], check=True)
    print("APPLIED: 116 metadata and audio additions; refresh progress and docs next", flush=True)


def finalize():
    data = read(PRE)
    rows = {r["song_mid"]: r for r in data["tracks"]}
    original_rows = {r["original_song_mid"]: r for r in data["tracks"]}
    main = read(BASE / "song_base_by_artist.json")
    pending = read(BASE / "待录制清单.json")
    pending["updated_at"] = "2026-10-13"
    pending["summary"].update(remaining_to_record=0, recorded_awaiting_import=0, imported_this_batch=116)
    pending["source"]["playlist_import"] = "imports/" + NAME + "元数据导入.json"
    pending["recording_progress"] = dict(updated_at="2026-10-13", batch_directory=str(BATCH),
        retry_batch_directory=str(RETRY), delivery_receipt="imports/" + RECEIPT.name,
        recorded_awaiting_import=0, remaining_to_record=0, unavailable_tracks=3,
        excluded_unavailable_candidates=2, formal_import_status="complete", imported_tracks=116,
        import_manifest="imports/" + LEDGER.name)
    replacement = next(r["version_replacement"] for r in rows.values() if r.get("version_replacement"))
    pending["replaced_unavailable_candidates"] = [replacement]
    write_json(BASE / "待录制清单.json", pending)
    progress = read(PROGRESS)
    progress["updated_at"] = "2026-10-13"
    progress["summary"].update(imported_metadata_and_audio=232, remaining_not_recorded=234,
        queued_this_run=0, remaining_not_started=234, third_fourth_imported=116,
        replaced_unavailable_links=1, unavailable_not_imported=2)
    previous_manifest = progress["import_manifest"]
    progress["import_manifest"] = "../imports/" + LEDGER.name
    progress["import_manifests"] = [previous_manifest, progress["import_manifest"]]
    for row in progress["tracks"]:
        t = original_rows.get(row["song_mid"])
        if t:
            row.update(status="imported_replacement" if t.get("version_replacement") else "imported",
                imported_track_id="qq:" + t["song_mid"], import_manifest=progress["import_manifest"],
                destination_relative_path=t["destination_relative_path"], sha256=t["sha256"],
                trimmed_tail_seconds=t["trimmed_tail_seconds"], recording_status=t["recording_status"])
            if t.get("version_replacement"):
                row["version_replacement"] = t["version_replacement"]
    for batch in progress["batches"]:
        if batch["batch_id"] in ("B03", "B04"):
            batch.update(imported=batch["track_count"], unavailable=0, not_recorded=0)
    progress["active_recording"].update(status="complete_and_imported", imported_at=now(),
        retry_batch_directory=str(RETRY), latest_dashboard="http://127.0.0.1:8767/",
        import_manifest=progress["import_manifest"], note="原始启动信息保留；116首已经完成并正式入库，一首经用户确认换专辑版。")
    write_json(PROGRESS, progress)
    plan = read(PLAN)
    plan["latest_progress"] = dict(updated_at="2026-10-13", imported=232, unavailable=2, not_recorded=234,
        replaced_unavailable_links=1, progress_file=PROGRESS.name)
    plan["scope"] = "Original 468-MID candidate plan; execution status in latest_progress, original version evidence retained."
    write_json(PLAN, plan)
    exceptions = read(BATCH / "manual-delivery-exceptions.json")
    for ex in exceptions["manualExceptions"]:
        t = rows[ex["id"]]
        ex.update(deliveryStatus="verified", mainLibraryImported=True, destination=str(BASE / t["destination_relative_path"]),
                  destinationSha256=t["sha256"], derivedMp3=t["source_mp3"], derivedMp3Sha256=t["sha256"],
                  mp3=t["quality"]["mp3"], importManifest=str(LEDGER), importedAt=now())
    write_json(BATCH / "manual-delivery-exceptions.json", exceptions)
    decisions = read(BATCH / "dashboard-review-decisions.json")
    for decision in decisions["decisions"]:
        t = rows[decision["id"]]
        decision.update(mainLibraryImported=True, destination=str(BASE / t["destination_relative_path"]),
                        destinationSha256=t["sha256"], importManifest=str(LEDGER))
    write_json(BATCH / "dashboard-review-decisions.json", decisions)
    review = read(REVIEW)
    review["review_summary"]["main_library_imported"] = True
    review["formal_import"] = dict(date="2026-10-13", manifest="imports/" + LEDGER.name, tracks=22)
    for track in review["tracks"]:
        t = rows[track["id"]]
        track.update(main_library_imported=True, destination_relative_path=t["destination_relative_path"],
                     destination_sha256=t["sha256"])
    write_json(REVIEW, review)
    write_json(BASE / "imports" / (NAME + "人工复核.json"), decisions)
    for command in ("update_report_snapshots.py", "build_annotation_gap_report.py"):
        subprocess.run([sys.executable, str(BASE / command)], check=True)
    print(json.dumps(dict(library=main["total_unique_songs"], artist_groups=main["total_singers"],
                         imported=116, remaining_candidates=234), ensure_ascii=False), flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    finalize() if args.finalize else (apply() if args.apply else prepare())

