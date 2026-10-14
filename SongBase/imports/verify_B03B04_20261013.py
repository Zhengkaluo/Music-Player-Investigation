"""Verify the B03/B04 import, preserving old versions and labels; optional HTTP."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote
from urllib.request import Request, urlopen

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from build_song_tags_browser import build_payload
from build_combined_annotation_browser import build_combined_payload
NAME = "2026-10-13-歌单补充B03B04-116首"
SNAP = BASE / "archive/snapshots/playlist-expansion/2026-10-13-B03B04-116首入库前"
def read(p):
    return json.loads(Path(p).read_text())
def digest(p):
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for block in iter(lambda: f.read(1048576), b""):
            h.update(block)
    return h.hexdigest()
def verify():
    main = read(BASE / "song_base_by_artist.json")
    old = read(SNAP / "song_base_by_artist.json")
    ledger = read(BASE / "imports" / (NAME + "正式入档.json"))
    receipt = read(BASE / "imports" / (NAME + "交付凭据.json"))
    metadata = read(BASE / "imports" / (NAME + "元数据导入.json"))
    prep = read(BASE / "imports" / (NAME + "入库准备.json"))
    assert main["total_unique_songs"] == old["total_unique_songs"] + 116 == 1553
    for a in old["singers"]:
        current = next(x for x in main["singers"] if x["name"] == a["name"])
        assert all(song in current["songs"] for song in a["songs"]), a["name"]
    for name, sha in read(SNAP / "protected-hashes.json").items():
        assert digest(BASE / name) == sha, name
    for name, sha in read(SNAP / "original-audio-hashes.json").items():
        assert digest(BASE / "SongResources" / name) == sha, name
    for file in prep["original_files"]:
        assert digest(file["path"]) == file["sha256"], file["path"]
    assert len(ledger["tracks"]) == len(receipt["tracks"]) == len(metadata["tracks"]) == 116
    assert len({r["track_id"] for r in ledger["tracks"]}) == 116
    assert ledger["summary"]["automatic_accepted"] == 107
    assert ledger["summary"]["manual_approved_exceptions"] == 9
    assert ledger["summary"]["tail_trimmed"] == 6
    payload = build_payload(main, read(BASE / "song_tags.json"), read(BASE / "song_tag_candidates.json"))
    assert payload["audio"]["mapped_tracks"] == 1550
    songs = {t["id"]: t for t in payload["songs"]}
    pages = {}
    for name in ("song_tags_browser.html", "song_manual_tagging.html", "song_combined_annotation.html", "song_base_browser.html"):
        text = (BASE / name).read_text()
        scripts = "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", text, re.S))
        result = subprocess.run(["node", "--check"], input=scripts, text=True, capture_output=True)
        assert result.returncode == 0, (name, result.stderr)
        match = re.search(r"const\s+(?:DATA|LIBRARY)\s*=\s*", text)
        assert match, name
        embedded, _ = json.JSONDecoder().raw_decode(text[match.end():])
        pages[name] = embedded
    for entry, row, meta in zip(receipt["tracks"], ledger["tracks"], metadata["tracks"]):
        identity = "qq:" + entry["id"]
        assert row["track_id"] == meta["track_id"] == identity
        song = songs[identity]
        assert song["title"] == entry["title"] and song["full_singer"] == entry["artist"]
        assert song["album"] == meta["album"] and not song["tags"] and not song["candidate"]
        target = BASE / row["destination_relative_path"]
        stage = Path(receipt["destination"]) / entry["files"][0]["path"]
        assert digest(target) == digest(stage) == digest(row["source_recording"]) == row["sha256"] == entry["files"][0]["sha256"]
        assert (BASE / unquote(song["audio_url"])).resolve() == target.resolve()
        assert "补录2首-2026-10-13/raw" not in row["source_recording"]
        for name in ("song_tags_browser.html", "song_manual_tagging.html", "song_combined_annotation.html"):
            page_song = next(t for t in pages[name]["songs"] if t["id"] == identity)
            assert page_song["audio_url"] == song["audio_url"]
        if len(sys.argv) > 1:
            url = sys.argv[1].rstrip("/") + "/" + song["audio_url"]
            for byte_range in ("bytes=0-1023", "bytes=-1024"):
                with urlopen(Request(url, headers={"Range": byte_range}), timeout=10) as response:
                    assert response.status == 206 and len(response.read()) == 1024
                    assert response.headers["Accept-Ranges"] == "bytes"
    assert "qq:004a1aRp0WI3rt" not in songs
    assert songs["qq:000VIQsR1lXb5A"]["album"] == "Para Mi (Explicit)"
    assert songs["qq:003tLzbv0wmm8o"]["audio_url"] != songs["qq:000xLw2D0E5Xjm"]["audio_url"]
    pending = read(BASE / "待录制清单.json")
    assert not pending["recordable_tracks"] and pending["summary"]["recorded_awaiting_import"] == 0
    assert {t["track_id"] for t in pending["unavailable_tracks"]} == {t["id"] for t in payload["songs"] if not t["audio_url"]}
    progress = read(BASE / "reviews/468首候选曲目录制与入库进度-2026-10-12.json")
    assert progress["summary"]["imported_metadata_and_audio"] == 232
    assert progress["summary"]["remaining_not_recorded"] == 234
    result = dict(verified_at="2026-10-13", imported=116, automatic=107, manual_exceptions=9, trimmed=6,
                  library=1553, playable=1550, artist_groups=main["total_singers"], audio_files=payload["audio"]["local_files"],
                  formal_tags=sum(t["tags"] is not None for t in songs.values()), untagged=sum(t["tags"] is None for t in songs.values()),
                  combined_queue=len(build_combined_payload()["songs"]), old_data_and_audio_preserved=True,
                  http_range_verified=len(sys.argv)>1)
    print(json.dumps(result, ensure_ascii=False))
if __name__ == "__main__":
    verify()

