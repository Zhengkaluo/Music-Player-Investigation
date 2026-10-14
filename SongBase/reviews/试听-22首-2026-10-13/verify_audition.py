"""Verify 22 audition identities, original hashes and seekable HTTP audio."""
import hashlib
import json
from pathlib import Path
import sys
import wave
from urllib.parse import quote
from urllib.request import Request, urlopen

root = Path(__file__).resolve().parent
data = json.loads((root / "试听清单.json").read_text())
html = (root / "试听-22首.html").read_text()
assert len(data["tracks"]) == len({t["id"] for t in data["tracks"]}) == 22
assert html.count("<audio ") == 22
assert sum(t["reason"] == "suspected_loop_tail" for t in data["tracks"]) == 13
assert sum(t["format"] == "wav" for t in data["tracks"]) == 9
assert sum(t["trimmed_tail_seconds"] == 1 for t in data["tracks"]) == 6
assert sum(t["review_status"] == "approved-full" for t in data["tracks"]) == 16
assert sum(t.get("manual_acceptance_status") == "manual-approved-exception" for t in data["tracks"]) == 9
for track in data["tracks"]:
    audio = root / track["audio"]
    assert hashlib.sha256(Path(track["source"]).read_bytes()).hexdigest() == track["source_sha256"]
    assert audio.resolve() == Path(track.get("current_source", track["source"])).resolve()
    assert audio.resolve().is_relative_to(Path(data["batch"]).resolve())
    assert hashlib.sha256(audio.read_bytes()).hexdigest() == track.get("current_source_sha256", track["source_sha256"])
    assert 'src="' + track["audio"] + '"' in html
    if track["trimmed_tail_seconds"]:
        evidence = track["trim_evidence"]
        original = Path(evidence["source_wav"])
        derived = Path(evidence["derived_wav"])
        assert hashlib.sha256(original.read_bytes()).hexdigest() == evidence["source_wav_sha256"]
        assert hashlib.sha256(derived.read_bytes()).hexdigest() == evidence["derived_wav_sha256"]
        with wave.open(str(original), "rb") as a, wave.open(str(derived), "rb") as b:
            assert a.getparams()[:3] == b.getparams()[:3]
            assert a.getnframes() - b.getnframes() == a.getframerate() == 44100
            assert b.getnframes() == evidence["derived_frames"]
            assert abs(b.getnframes() / b.getframerate() - track["duration_seconds"]) < 0.001
            remaining = b.getnframes()
            while remaining:
                count = min(32768, remaining)
                assert a.readframes(count) == b.readframes(count)
                remaining -= count
        assert evidence["mp3"]["decodePassed"] and evidence["mp3"]["peakDbFS"] <= 0
        assert abs(evidence["mp3"]["durationSeconds"] - track["duration_seconds"]) < 0.1
    if track["format"] == "wav":
        assert track["recording_status"] == "failed"
        with wave.open(str(audio), "rb") as wav:
            assert abs(wav.getnframes() / wav.getframerate() - track["duration_seconds"]) < 0.001
    if len(sys.argv) > 1:
        url = sys.argv[1].rstrip("/") + "/" + quote(track["audio"])
        for byte_range in ("bytes=0-1023", "bytes=-1024"):
            with urlopen(Request(url, headers={"Range": byte_range}), timeout=10) as response:
                assert response.status == 206
                assert response.headers["Accept-Ranges"] == "bytes"
                assert len(response.read()) == 1024
print("PASS: 22 human decisions, 6 exact one-second trims with unchanged PCM prefix, 16 full approvals including 9 manual exceptions; original hashes unchanged; HTTP Range verified when URL supplied.")

