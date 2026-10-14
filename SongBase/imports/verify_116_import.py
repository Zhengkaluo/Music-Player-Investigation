"""Re-run the 116-track import identity/hash/page checks; optional local HTTP."""
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote
from urllib.request import Request, urlopen

base = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(base))
from build_song_tags_browser import build_payload
def read(path):
    return json.loads(path.read_text())
def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1048576), b""):
            h.update(block)
    return h.hexdigest()
snapshot = base / "archive/snapshots/playlist-expansion/2026-10-12-116首入库前"
old = read(snapshot / "song_base_by_artist.json")
main = read(base / "song_base_by_artist.json")
receipt = read(base / "imports/2026-10-12-歌单补充116首交付凭据.json")
ledger = read(base / "imports/2026-10-12-歌单补充116首正式入档.json")
assert main["total_unique_songs"] == old["total_unique_songs"] + 116 == 1437
for artist in old["singers"]:
    current = next(a for a in main["singers"] if a["name"] == artist["name"])
    assert all(song in current["songs"] for song in artist["songs"])
for name, sha in read(snapshot / "protected-hashes.json").items():
    assert digest(base / name) == sha, name
assert len(receipt["tracks"]) == len(ledger["tracks"]) == 116
assert len({t["id"] for t in receipt["tracks"]}) == 116
assert sum(t["status"] == "manual-approved-exception" for t in receipt["tracks"]) == 3
assert sum(t["tail_trim_seconds"] == 1 for t in ledger["tracks"]) == 4
payload = build_payload(main, read(base / "song_tags.json"), read(base / "song_tag_candidates.json"))
songs = {t["id"]: t for t in payload["songs"]}
assert payload["audio"]["mapped_tracks"] == 1434
for entry, row in zip(receipt["tracks"], ledger["tracks"]):
    identity = "qq:" + entry["id"]
    assert row["track_id"] == identity
    song = songs[identity]
    assert song["title"] == entry["title"] and song["full_singer"] == entry["artist"]
    assert not song["tags"] and not song["candidate"]
    target = base / row["destination_relative_path"]
    stage = Path(receipt["destination"]) / entry["files"][0]["path"]
    assert digest(target) == digest(stage) == row["sha256"] == entry["files"][0]["sha256"]
    assert (base / unquote(song["audio_url"])).resolve() == target.resolve()
    for page in ("song_tags_browser.html", "song_manual_tagging.html", "song_combined_annotation.html"):
        text = (base / page).read_text()
        assert identity in text and song["audio_url"] in text, (identity, page)
    if len(sys.argv) > 1:
        with urlopen(Request(sys.argv[1].rstrip("/") + "/" + song["audio_url"], headers={"Range": "bytes=0-1023"}), timeout=10) as response:
            assert response.status == 206 and len(response.read()) == 1024
assert "qq:0011BLZM0ZTHx3" not in songs and "qq:000n0SUH3RFLVo" not in songs
assert {t["track_id"] for t in read(base / "待录制清单.json")["unavailable_tracks"]} == {t["id"] for t in payload["songs"] if not t["audio_url"]}
print("PASS: 116 imported identities/hash pairs, 4 trims, 3 manual exceptions; 1437 tracks / 1434 playable; old data and protected labels/catalog preserved.")

