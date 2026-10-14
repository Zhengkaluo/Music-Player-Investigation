"""Verify 13 audition identities, original hashes, native players and HTTP Range."""
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import quote
from urllib.request import Request, urlopen

root = Path(__file__).resolve().parent
data = json.loads((root / "试听清单.json").read_text())
html = (root / "试听-13首.html").read_text()
assert len(data["tracks"]) == len({t["id"] for t in data["tracks"]}) == 13
assert html.count("<audio ") == 13
assert sum(t["reason"] == "suspected_loop_tail" for t in data["tracks"]) == 10
assert sum(t["format"] == "wav" for t in data["tracks"]) == 3
for track in data["tracks"]:
    audio = root / track["audio"]
    assert hashlib.sha256(Path(track["source"]).read_bytes()).hexdigest() == track["source_sha256"]
    assert audio.resolve() == Path(track.get("current_source", track["source"])).resolve()
    assert hashlib.sha256(audio.read_bytes()).hexdigest() == track.get("current_source_sha256", track["source_sha256"])
    if "trim_evidence" in track:
        import wave
        evidence = track["trim_evidence"]
        with wave.open(evidence["source_wav"], "rb") as original, wave.open(evidence["derived_wav"], "rb") as trimmed:
            assert original.getframerate() == trimmed.getframerate()
            assert original.getnframes() - trimmed.getnframes() == original.getframerate()
            remaining = trimmed.getnframes()
            while remaining:
                frames = min(32768, remaining)
                assert original.readframes(frames) == trimmed.readframes(frames)
                remaining -= frames
    assert 'src="' + track["audio"] + '"' in html
    if len(sys.argv) > 1:
        request = Request(sys.argv[1].rstrip("/") + "/" + quote(track["audio"]), headers={"Range": "bytes=0-1023"})
        with urlopen(request, timeout=10) as response:
            assert response.status == 206
            assert response.headers["Accept-Ranges"] == "bytes"
            assert len(response.read()) == 1024
assert sum(t.get("trimmed_tail_seconds") == 1 for t in data["tracks"]) == 4
assert all(t["review_status"] in {"approved-full", "approved-with-tail-trim"} for t in data["tracks"])
print("PASS: 13 reviewed tracks; 4 exact one-second trims with unchanged PCM prefix; originals preserved; HTTP Range verified when URL supplied.")

