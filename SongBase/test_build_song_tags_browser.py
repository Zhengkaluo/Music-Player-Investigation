#!/usr/bin/env python3

from build_song_tags_browser import BASE, find_local_audio, normalized_stem
from build_combined_annotation_browser import merge_annotation_requirements


def test_album_disambiguates_duplicate_title() -> None:
    generic = BASE / "SongResources" / "Lamp - 中村遥.mp3"
    album = BASE / "SongResources" / "Lamp [Grace] - haruka nakamura.mp3"
    compact = {
        normalized_stem(generic.stem): generic,
        normalized_stem(album.stem): album,
    }
    result = find_local_audio("Lamp", "中村遥", "haruka nakamura", "Grace", {}, compact)
    assert result == "SongResources/Lamp%20%5BGrace%5D%20-%20haruka%20nakamura.mp3"


def test_manual_page_has_local_audio_filter() -> None:
    source = (BASE / "build_manual_tagging_browser.py").read_text(encoding="utf-8")
    assert '<option value="local">只看有本地音源</option>' in source
    assert "if(state.status==='local'&&!song.audio_url)return false" in source


def test_combined_queue_keeps_each_missing_side_separate() -> None:
    payload = {
        "songs": [
            {"id": "both", "tags": None},
            {"id": "tag-only", "tags": None},
            {"id": "zmpd-only", "tags": {"genre": "Jazz / Soul"}},
            {"id": "complete", "tags": {"genre": "Electronic"}},
        ]
    }
    merged = merge_annotation_requirements(payload, {"tag-only", "complete"})
    assert {song["id"]: song["gap_type"] for song in merged["songs"]} == {
        "both": "both",
        "tag-only": "tag",
        "zmpd-only": "zmpd",
    }


if __name__ == "__main__":
    test_album_disambiguates_duplicate_title()
    test_manual_page_has_local_audio_filter()
    test_combined_queue_keeps_each_missing_side_separate()
