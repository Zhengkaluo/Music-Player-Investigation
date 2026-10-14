"""Check recovered identities, source hashes, page data and desktop mirrors."""
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from build_song_tags_browser import build_payload
from build_combined_annotation_browser import build_combined_payload

def read(path):
    return json.loads(path.read_text())

def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1048576), b""):
            h.update(block)
    return h.hexdigest()

def verify():
    parsed = 0
    for path in BASE.rglob("*.json"):
        read(path)
        parsed += 1
    main = read(BASE / "song_base_by_artist.json")
    tags = read(BASE / "song_tags.json")
    candidates = read(BASE / "song_tag_candidates.json")
    payload = build_payload(main, tags, candidates)
    songs = {s["id"]: s for s in payload["songs"]}
    assert len(songs) == len(payload["songs"]) == main["total_unique_songs"] == 1553
    assert len(tags["tracks"]) == 1215 and set(tags["tracks"]) <= songs.keys()
    assert not candidates["tracks"]
    assert sum(s["tags"] is None for s in songs.values()) == 338
    assert payload["audio"] == {"local_files": 1574, "mapped_tracks": 1550}
    for song in songs.values():
        if song["audio_url"]:
            path = (BASE / unquote(song["audio_url"])).resolve()
            assert path.is_relative_to((BASE / "SongResources").resolve())
            assert path.is_file() and path.stat().st_size > 0
    assert {s["title"] for s in songs.values() if not s["audio_url"]} == {
        "自己做决定 feat.陈绮贞", "Prisoner", "寒心寺"}
    checked = []
    for stem in ("2026-10-12-歌单补充116首", "2026-10-13-歌单补充B03B04-116首"):
        ledger = read(BASE / "imports" / (stem + "正式入档.json"))
        receipt = read(BASE / "imports" / (stem + "交付凭据.json"))
        metadata = read(BASE / "imports" / (stem + "元数据导入.json"))
        receipts = {"qq:" + x["id"]: x for x in receipt["tracks"]}
        metas = {x["track_id"]: x for x in metadata["tracks"]}
        assert len(ledger["tracks"]) == len(receipts) == len(metas) == 116
        for row in ledger["tracks"]:
            identity = row["track_id"]
            song, entry, meta = songs[identity], receipts[identity], metas[identity]
            assert song["title"] == entry["title"] and song["full_singer"] == entry["artist"]
            assert song["album"] == meta["album"]
            destination = BASE / row["destination_relative_path"]
            stage = Path(receipt["destination"]) / entry["files"][0]["path"]
            assert digest(destination) == digest(stage) == row["sha256"] == entry["files"][0]["sha256"]
            assert (BASE / unquote(song["audio_url"])).resolve() == destination.resolve()
            checked.append(identity)
    assert len(checked) == len(set(checked)) == 232
    combined = build_combined_payload()
    assert len(combined["songs"]) == 1122
    assert combined["zmpd_source"]["matched_songbase_tracks"] == 435
    assert Counter(s["gap_type"] for s in combined["songs"]) == {"both": 334, "tag": 4, "zmpd": 784}
    pages = {}
    for name, expected in (("song_tags_browser.html", 1553), ("song_base_browser.html", 1553),
                           ("song_manual_tagging.html", 338), ("song_combined_annotation.html", 1122)):
        text = (BASE / name).read_text()
        scripts = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", text, re.S))
        result = subprocess.run(["node", "--check"], input=scripts, text=True, capture_output=True)
        assert result.returncode == 0, (name, result.stderr)
        match = re.search(r"const\s+(?:DATA|LIBRARY)\s*=\s*", text)
        embedded, _ = json.JSONDecoder().raw_decode(text[match.end():])
        if name == "song_base_browser.html":
            assert embedded == main
        else:
            assert len(embedded["songs"]) == expected
            for song in embedded["songs"]:
                assert song["audio_url"] == songs[song["id"]]["audio_url"]
                assert song["tags"] == songs[song["id"]]["tags"]
            assert all(identity in {s["id"] for s in embedded["songs"]} for identity in checked)
        pages[name] = {"tracks": expected, "javascript_syntax": "passed", "data": "passed"}
    progress = read(BASE / "reviews/468首候选曲目录制与入库进度-2026-10-12.json")
    assert progress["summary"]["imported_metadata_and_audio"] == 232
    assert progress["summary"]["remaining_not_recorded"] == 234
    pending = read(BASE / "待录制清单.json")
    assert pending["summary"]["local_playable_tracks"] == 1550
    assert not pending["recordable_tracks"]
    for name in ("song_base_by_artist.md", "曲库风格与语种报告.md", "README.md"):
        assert "1,553" in (BASE / name).read_text() or "1553" in (BASE / name).read_text()
    mirror = Path("/Users/kaluozheng/Desktop/SongBase 歌曲标签库")
    for name in ("song_base_by_artist.json", "song_tags.json", "song_tag_candidates.json", "song_tag_mapping.json"):
        assert (mirror / "数据" / name).read_bytes() == (BASE / name).read_bytes()
    for name in pages:
        assert (mirror / "工具" / name).read_bytes() == (BASE / name).read_bytes()
    assert (mirror / "工具/SongResources").resolve() == (BASE / "SongResources").resolve()
    return {"json_files_parsed": parsed, "library": 1553, "formal_tags": 1215,
            "untagged": 338, "playable": 1550, "new_import_hashes_verified": len(checked),
            "matched_human_zmpd": 435, "remaining_candidates_not_recorded": 234,
            "pages": pages, "desktop_mirror": "passed", "audio_files_modified": 0}

if __name__ == "__main__":
    result = verify()
    if "--save" in sys.argv:
        target = BASE / "imports/2026-10-13-曲库版本恢复.json"
        audit = read(target)
        audit["verification"] = result
        target.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
