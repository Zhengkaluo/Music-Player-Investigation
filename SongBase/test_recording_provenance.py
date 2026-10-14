"""Recording import provenance must resolve sanitized names by MID and hash."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_annotation_gap_report as report


class RecordingProvenanceTest(unittest.TestCase):
    def test_final_audit_count_is_not_an_audio_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "SongResources").mkdir()
            (root / "imports").mkdir()
            (root / "imports" / "final-audit.json").write_text(json.dumps({
                "schema_version": "songbase.recording-import-final-audit/v1",
                "imported": 116,
            }))
            with patch.object(report, "ROOT", root):
                matches, unmatched = report.audio_matches({}, {}, {})
            self.assertEqual(dict(matches), {})
            self.assertEqual(unmatched, [])

    def test_recording_receipt_requires_matching_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "SongResources").mkdir()
            (root / "imports").mkdir()
            audio = root / "SongResources" / "Where Do We Go_ - ODIE.mp3"
            audio.write_bytes(b"recording-test")
            identity = "qq:0041Ll4K3yOLk1"
            songs = {identity: {"title": "Where Do We Go?", "artist": "ODIE", "group_artist": "ODIE"}}
            index = report.identity_index(songs, {})
            item = {"track_id": identity, "destination_relative_path": "SongResources/" + audio.name,
                    "sha256": hashlib.sha256(audio.read_bytes()).hexdigest()}
            receipt = {"schema_version": "songbase.qq-recording-audio-import/v1", "tracks": [item]}
            receipt_path = root / "imports" / "recording.json"
            receipt_path.write_text(json.dumps(receipt))
            with patch.object(report, "ROOT", root):
                matches, _ = report.audio_matches(songs, index, {})
                self.assertEqual(matches[identity], [audio.name])
                item["sha256"] = "0" * 64
                receipt_path.write_text(json.dumps(receipt))
                with self.assertRaises(ValueError):
                    report.audio_matches(songs, index, {})


if __name__ == "__main__":
    unittest.main()
