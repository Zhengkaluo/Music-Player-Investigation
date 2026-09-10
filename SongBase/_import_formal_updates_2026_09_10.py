#!/usr/bin/env python3
"""Import the validated five-track formal update export."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path


BASE = Path(__file__).resolve().parent
EXPORT_PATH = Path("/Users/kaluozheng/Downloads/song_tags_formal_updates_2026-09-10.json")
EXPECTED_IDS = {
    "qq:000afH2Z0gIzbI",
    "qq:000bR3XJ0iICzQ",
    "qq:002aplaD2uRp5x",
    "qq:0038Vq2C02uayk",
    "qq:0048buGv2Ed4db",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    current = load(BASE / "song_tags.json")
    exported = load(EXPORT_PATH)
    candidates = load(BASE / "song_tag_candidates.json")

    assert exported.get("schema_version") == "songbase.tags/v1"
    assert exported.get("taxonomy_version") == current.get("taxonomy_version")
    assert exported.get("taxonomy") == current.get("taxonomy")
    current_ids = set(current["tracks"])
    exported_ids = set(exported["tracks"])
    assert exported_ids - current_ids == EXPECTED_IDS
    assert not (current_ids - exported_ids)
    assert all(current["tracks"][mid] == exported["tracks"][mid] for mid in current_ids)

    for mid in EXPECTED_IDS:
        candidate = candidates["tracks"].get(mid)
        assert candidate is not None, f"candidate missing: {mid}"
        assert mid not in current["tracks"]
        del candidates["tracks"][mid]

    today = date.today().isoformat()
    candidates.setdefault("sample", {})["size"] = len(candidates["tracks"])
    candidates["sample"]["population"] = len(candidates["tracks"])
    candidates["pruned_at"] = today
    write(BASE / "song_tags.json", exported)
    write(BASE / "song_tag_candidates.json", candidates)
    print(f"imported={len(EXPECTED_IDS)} formal_total={len(exported['tracks'])} candidates={len(candidates['tracks'])}")


if __name__ == "__main__":
    main()
