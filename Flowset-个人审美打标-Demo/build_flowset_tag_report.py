#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a self-contained Flowset × SongBase tag relationship report."""

from __future__ import annotations

import csv
import html
import json
import math
import random
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "Flowset-个人审美打标-Demo"
SONGBASE = ROOT / "SongBase"
OUT = DEMO / "flowset_tag_relationship_report.html"
MATCHED_CSV = DEMO / "flowset_tag_matched.csv"
AUDIT_CSV = DEMO / "flowset_tag_match_audit.csv"

WAVES = [
    ("0716", "第一波 · 07-16", "2026-07-16"),
    ("0722", "第二波 · 07-22", "2026-07-22"),
    ("0728", "第三波 · 07-28", "2026-07-28"),
    ("0925", "第四波 · 09-25", "2026-09-25"),
]

GENRES = [
    "Ambient / Neo-Classical",
    "Post-Rock / Cinematic",
    "Electronic",
    "Jazz / Soul",
    "Folk / Singer-Songwriter",
    "Rock / Alternative",
    "Hip-Hop / R&B",
]
GENRE_SHORT = {
    "Ambient / Neo-Classical": "Ambient / Neo-Classical",
    "Post-Rock / Cinematic": "Post-Rock / Cinematic",
    "Electronic": "Electronic",
    "Jazz / Soul": "Jazz / Soul",
    "Folk / Singer-Songwriter": "Folk / Singer-Songwriter",
    "Rock / Alternative": "Rock / Alternative",
    "Hip-Hop / R&B": "Hip-Hop / R&B",
}
TIME_ORDER = ["8-11", "11-14", "14-17", "17-20"]
ENERGY_ORDER = ["平静", "渐进", "有冲劲", "爆发", "不确定"]
DIM_IDS = {
    "noise": "噪音程度",
    "swing": "摇摆速率",
    "burden": "负担程度",
}
QQ_MID_RE = re.compile(r"/songDetail/([A-Za-z0-9]+)")
SEED = 20260925


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def clean_filename(value: str) -> str:
    value = unicodedata.normalize("NFC", str(value or ""))
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", value)
    return re.sub(r"\s+", " ", value).strip(" .") or "未命名"


def compact(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(char for char in value if char.isalnum())


def artist_variants(group_artist: str, full_singer: str) -> list[str]:
    result: list[str] = []
    for artist in (group_artist, full_singer):
        artist = str(artist or "").strip()
        if not artist:
            continue
        result.append(artist)
        for separator in (",", "，", "&", "、"):
            primary = artist.split(separator, 1)[0].strip()
            if primary:
                result.append(primary)
    return list(dict.fromkeys(result))


def mean(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def quantile(values: list[float], probability: float) -> float | None:
    """Linear-interpolated quantile, matching the report's descriptive use."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def bh_adjust(p_values: list[float]) -> list[float]:
    """Benjamini-Hochberg correction, returned in original order."""
    count = len(p_values)
    ranked = sorted(enumerate(p_values), key=lambda item: item[1])
    adjusted = [1.0] * count
    running = 1.0
    for reverse_index in range(count - 1, -1, -1):
        original_index, p_value = ranked[reverse_index]
        rank = reverse_index + 1
        running = min(running, p_value * count / rank)
        adjusted[original_index] = min(1.0, running)
    return adjusted


def rankdata(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    pos = 0
    while pos < len(order):
        end = pos + 1
        while end < len(order) and values[order[end]] == values[order[pos]]:
            end += 1
        avg_rank = (pos + 1 + end) / 2
        for j in range(pos, end):
            ranks[order[j]] = avg_rank
        pos = end
    return ranks


def pearson(x: list[float], y: list[float]) -> float:
    if len(x) < 2:
        return 0.0
    mx, my = mean(x), mean(y)
    numerator = sum((a - mx) * (b - my) for a, b in zip(x, y))
    dx = sum((a - mx) ** 2 for a in x)
    dy = sum((b - my) ** 2 for b in y)
    return numerator / math.sqrt(dx * dy) if dx and dy else 0.0


def spearman(x: list[float], y: list[float]) -> float:
    return pearson(rankdata(x), rankdata(y))


def kruskal_h(values: list[float], groups: list[str]) -> tuple[float, float]:
    ranks = rankdata(values)
    grouped: dict[str, list[float]] = defaultdict(list)
    for rank, group in zip(ranks, groups):
        grouped[group].append(rank)
    n = len(values)
    h = 12 / (n * (n + 1)) * sum(sum(rs) ** 2 / len(rs) for rs in grouped.values()) - 3 * (n + 1)
    ties = Counter(values)
    correction = 1 - sum(count ** 3 - count for count in ties.values()) / (n ** 3 - n) if n > 1 else 1
    h = h / correction if correction else 0.0
    k = len(grouped)
    epsilon_sq = max(0.0, (h - k + 1) / (n - k)) if n > k else 0.0
    return h, epsilon_sq


def permutation_kruskal(values: list[float], groups: list[str], rounds: int = 3000) -> tuple[float, float, float]:
    observed_h, effect = kruskal_h(values, groups)
    rng = random.Random(SEED + len(values))
    shuffled = groups[:]
    exceed = 0
    for _ in range(rounds):
        rng.shuffle(shuffled)
        h, _ = kruskal_h(values, shuffled)
        if h >= observed_h - 1e-12:
            exceed += 1
    return observed_h, effect, (exceed + 1) / (rounds + 1)


def cramers_v(rows: list[str], cols: list[str]) -> tuple[float, float]:
    row_levels = list(dict.fromkeys(rows))
    col_levels = list(dict.fromkeys(cols))
    counts = {(r, c): 0 for r in row_levels for c in col_levels}
    for r, c in zip(rows, cols):
        counts[(r, c)] += 1
    n = len(rows)
    row_totals = Counter(rows)
    col_totals = Counter(cols)
    chi2 = 0.0
    for r in row_levels:
        for c in col_levels:
            expected = row_totals[r] * col_totals[c] / n
            if expected:
                chi2 += (counts[(r, c)] - expected) ** 2 / expected
    # Bias-corrected Cramér's V (Bergsma/Wicher correction). This matters for
    # small genre cells such as Electronic.
    row_count, col_count = len(row_levels), len(col_levels)
    phi2 = chi2 / n if n else 0.0
    phi2_corrected = max(0.0, phi2 - ((col_count - 1) * (row_count - 1)) / (n - 1)) if n > 1 else 0.0
    row_corrected = row_count - ((row_count - 1) ** 2) / (n - 1) if n > 1 else row_count
    col_corrected = col_count - ((col_count - 1) ** 2) / (n - 1) if n > 1 else col_count
    denominator = min(row_corrected - 1, col_corrected - 1)
    v = math.sqrt(phi2_corrected / denominator) if denominator > 0 else 0.0
    return chi2, v


def permutation_cramers(rows: list[str], cols: list[str], rounds: int = 3000) -> tuple[float, float, float]:
    chi2, v = cramers_v(rows, cols)
    rng = random.Random(SEED + len(rows) + len(set(cols)))
    shuffled = cols[:]
    exceed = 0
    for _ in range(rounds):
        rng.shuffle(shuffled)
        stat, _ = cramers_v(rows, shuffled)
        if stat >= chi2 - 1e-12:
            exceed += 1
    return chi2, v, (exceed + 1) / (rounds + 1)


def permute_within_strata(values: list, strata: list[str], rng: random.Random) -> list:
    shuffled = values[:]
    positions: dict[str, list[int]] = defaultdict(list)
    for index, stratum in enumerate(strata):
        positions[stratum].append(index)
    for indices in positions.values():
        local = [shuffled[index] for index in indices]
        rng.shuffle(local)
        for index, value in zip(indices, local):
            shuffled[index] = value
    return shuffled


def stratified_permutation_kruskal(
    values: list[float], groups: list[str], strata: list[str], rounds: int = 3000
) -> float:
    observed_h, _ = kruskal_h(values, groups)
    rng = random.Random(SEED + len(values) + 101)
    exceed = 0
    for _ in range(rounds):
        shuffled = permute_within_strata(values, strata, rng)
        h, _ = kruskal_h(shuffled, groups)
        exceed += h >= observed_h - 1e-12
    return (exceed + 1) / (rounds + 1)


def stratified_permutation_cramers(
    rows: list[str], cols: list[str], strata: list[str], rounds: int = 3000
) -> float:
    observed_chi2, _ = cramers_v(rows, cols)
    rng = random.Random(SEED + len(rows) + 211)
    exceed = 0
    for _ in range(rounds):
        shuffled = permute_within_strata(cols, strata, rng)
        chi2, _ = cramers_v(rows, shuffled)
        exceed += chi2 >= observed_chi2 - 1e-12
    return (exceed + 1) / (rounds + 1)


def cliffs_delta(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    greater = sum(x > y for x in a for y in b)
    lower = sum(x < y for x in a for y in b)
    return (greater - lower) / (len(a) * len(b))


def permutation_mean_diff(a: list[float], b: list[float], rounds: int = 3000) -> float:
    observed = abs(mean(a) - mean(b))
    joined = a + b
    rng = random.Random(SEED + len(joined))
    exceed = 0
    for _ in range(rounds):
        rng.shuffle(joined)
        diff = abs(mean(joined[: len(a)]) - mean(joined[len(a) :]))
        if diff >= observed - 1e-12:
            exceed += 1
    return (exceed + 1) / (rounds + 1)


def mode(values: list[str]) -> str:
    counts = Counter(values)
    return max(counts, key=lambda value: (counts[value], -values.index(value)))


def build_song_index() -> tuple[dict[str, set[str]], dict[str, dict]]:
    library = load_json(SONGBASE / "song_base_by_artist.json")
    index: dict[str, set[str]] = defaultdict(set)
    metadata: dict[str, dict] = {}
    for singer in library["singers"]:
        for song in singer["songs"]:
            match = QQ_MID_RE.search(song.get("qq_music", ""))
            if not match:
                continue
            track_id = "qq:" + match.group(1)
            metadata[track_id] = {
                "title": song.get("title", ""),
                "artist": song.get("full_singer") or singer["name"],
                "group_artist": singer["name"],
                "album": song.get("album", ""),
            }
            for artist in artist_variants(singer["name"], song.get("full_singer", "")):
                stem = f"{clean_filename(song.get('title', ''))} - {clean_filename(artist)}"
                index[compact(stem)].add(track_id)
    return index, metadata


def read_flowset() -> list[dict]:
    observations: list[dict] = []
    for wave_order, (wave_key, wave_label, date) in enumerate(WAVES, start=1):
        payload = load_json(DEMO / f"Flowset-个人审美样本-郑卡罗-{date}.json")
        for track in payload["tracks"]:
            selections = {item["dimension"]: item["labels"] for item in track["selections"]}
            observations.append(
                {
                    "wave_key": wave_key,
                    "wave_label": wave_label,
                    "wave_order": wave_order,
                    "date": date,
                    "order": track["order"],
                    "filename": track["file"]["name"],
                    "match_key": compact(Path(track["file"]["name"]).stem),
                    "energy": selections["能量状态"][0],
                    "noise": int(selections["噪音程度"][0]),
                    "swing": int(selections["摇摆速率"][0]),
                    "burden": int(selections["负担程度"][0]),
                    "timeslots": selections["适合的时段"],
                    "confidence": track.get("confidence"),
                    "note": track.get("note") or "",
                }
            )
    return observations


def match_data(observations: list[dict]) -> tuple[list[dict], list[dict]]:
    song_index, metadata = build_song_index()
    tag_payload = load_json(SONGBASE / "song_tags.json")
    tags = tag_payload["tracks"]
    audit: list[dict] = []
    matched: list[dict] = []
    for row in observations:
        ids = sorted(song_index.get(row["match_key"], set()))
        formal = [track_id for track_id in ids if track_id in tags]
        if len(formal) == 1:
            status = "formal_tag"
            track_id = formal[0]
            tag = tags[track_id]
            merged = {
                **row,
                "track_id": track_id,
                **metadata[track_id],
                "genre": tag["genre"],
                "secondary_genres": tag.get("secondary_genres", []),
                "instrumental": tag.get("instrumental"),
                "language": tag.get("language"),
                "tag_source": tag.get("source", ""),
            }
            matched.append(merged)
        elif len(formal) > 1:
            status = "ambiguous_formal_tag"
            track_id = " | ".join(formal)
        elif ids:
            status = "songbase_without_formal_tag"
            track_id = " | ".join(ids)
        else:
            status = "not_matched_to_songbase"
            track_id = ""
        audit.append(
            {
                "wave": row["wave_label"],
                "filename": row["filename"],
                "status": status,
                "track_id": track_id,
            }
        )
    return matched, audit


def dedupe_latest(rows: list[dict]) -> list[dict]:
    latest: dict[str, dict] = {}
    for row in rows:
        previous = latest.get(row["track_id"])
        if previous is None or (row["wave_order"], row["order"]) > (previous["wave_order"], previous["order"]):
            latest[row["track_id"]] = row
    return sorted(latest.values(), key=lambda row: (row["wave_order"], row["order"]))


def dedupe_flow_latest(rows: list[dict]) -> list[dict]:
    latest: dict[str, dict] = {}
    for row in rows:
        previous = latest.get(row["match_key"])
        if previous is None or (row["wave_order"], row["order"]) > (previous["wave_order"], previous["order"]):
            latest[row["match_key"]] = row
    return sorted(latest.values(), key=lambda row: (row["wave_order"], row["order"]))


def flowset_only_summary(rows: list[dict]) -> dict:
    correlations = []
    for first, second in (("noise", "swing"), ("noise", "burden"), ("swing", "burden")):
        correlations.append(
            {
                "a": first,
                "b": second,
                "rho": round(spearman([row[first] for row in rows], [row[second] for row in rows]), 3),
            }
        )
    return {"n": len(rows), "correlations": correlations}


def summarize_scope(rows: list[dict]) -> dict:
    genre_profiles = []
    for genre in GENRES:
        subset = [row for row in rows if row["genre"] == genre]
        if not subset:
            continue
        profile = {
                "genre": genre,
                "label": GENRE_SHORT[genre],
                "n": len(subset),
                "noise": round(mean([row["noise"] for row in subset]), 3),
                "swing": round(mean([row["swing"] for row in subset]), 3),
                "burden": round(mean([row["burden"] for row in subset]), 3),
                "noise_median": median([row["noise"] for row in subset]),
                "swing_median": median([row["swing"] for row in subset]),
                "burden_median": median([row["burden"] for row in subset]),
                "energy": {energy: sum(row["energy"] == energy for row in subset) for energy in ENERGY_ORDER},
                "times": {slot: round(sum(slot in row["timeslots"] for row in subset) / len(subset), 4) for slot in TIME_ORDER},
                "instrumental_rate": round(sum(row["instrumental"] is True for row in subset) / len(subset), 4),
                "avg_confidence": round(mean([row["confidence"] for row in subset if row["confidence"] is not None]) or 0, 3),
        }
        for dimension in ("noise", "swing", "burden"):
            values = [row[dimension] for row in subset]
            profile[f"{dimension}_q1"] = round(quantile(values, 0.25), 3)
            profile[f"{dimension}_q3"] = round(quantile(values, 0.75), 3)
            profile[f"{dimension}_min"] = min(values)
            profile[f"{dimension}_max"] = max(values)
        genre_profiles.append(profile)

    contrasts = []
    profile_by_genre = {profile["genre"]: profile for profile in genre_profiles}
    for genre in profile_by_genre:
        for dimension in ("noise", "swing", "burden"):
            inside = [row[dimension] for row in rows if row["genre"] == genre]
            outside = [row[dimension] for row in rows if row["genre"] != genre]
            contrasts.append(
                {
                    "genre": genre,
                    "dimension": dimension,
                    "delta": round(cliffs_delta(inside, outside), 3),
                    "p": permutation_mean_diff(inside, outside),
                }
            )
    for contrast, q_value in zip(contrasts, bh_adjust([item["p"] for item in contrasts])):
        contrast["p"] = round(contrast["p"], 4)
        contrast["q"] = round(q_value, 4)
        profile_by_genre[contrast["genre"]].setdefault("contrasts", {})[contrast["dimension"]] = {
            "delta": contrast["delta"],
            "p": contrast["p"],
            "q": contrast["q"],
        }

    numeric_tests = {}
    for dimension in ("noise", "swing", "burden"):
        h, effect, p = permutation_kruskal([row[dimension] for row in rows], [row["genre"] for row in rows])
        p_wave = stratified_permutation_kruskal(
            [row[dimension] for row in rows],
            [row["genre"] for row in rows],
            [row["wave_key"] for row in rows],
        )
        numeric_tests[dimension] = {
            "h": round(h, 3),
            "effect": round(effect, 3),
            "p": round(p, 4),
            "p_wave": round(p_wave, 4),
        }
    for dimension, q_value in zip(numeric_tests, bh_adjust([item["p"] for item in numeric_tests.values()])):
        numeric_tests[dimension]["q"] = round(q_value, 4)

    energy_test = permutation_cramers([row["genre"] for row in rows], [row["energy"] for row in rows])
    energy_p_wave = stratified_permutation_cramers(
        [row["genre"] for row in rows],
        [row["energy"] for row in rows],
        [row["wave_key"] for row in rows],
    )
    timeslot_tests = {}
    for slot in TIME_ORDER:
        test = permutation_cramers([row["genre"] for row in rows], ["yes" if slot in row["timeslots"] else "no" for row in rows])
        p_wave = stratified_permutation_cramers(
            [row["genre"] for row in rows],
            ["yes" if slot in row["timeslots"] else "no" for row in rows],
            [row["wave_key"] for row in rows],
        )
        timeslot_tests[slot] = {
            "chi2": round(test[0], 3),
            "effect": round(test[1], 3),
            "p": round(test[2], 4),
            "p_wave": round(p_wave, 4),
        }
    for slot, q_value in zip(timeslot_tests, bh_adjust([item["p"] for item in timeslot_tests.values()])):
        timeslot_tests[slot]["q"] = round(q_value, 4)

    correlations = []
    for a, b in (("noise", "swing"), ("noise", "burden"), ("swing", "burden")):
        value = spearman([row[a] for row in rows], [row[b] for row in rows])
        correlations.append({"a": a, "b": b, "rho": round(value, 3)})

    instrumental_rows = [row for row in rows if isinstance(row["instrumental"], bool)]
    instrumental = {}
    for dimension in ("noise", "swing", "burden"):
        yes = [row[dimension] for row in instrumental_rows if row["instrumental"]]
        no = [row[dimension] for row in instrumental_rows if not row["instrumental"]]
        instrumental[dimension] = {
            "true_n": len(yes),
            "false_n": len(no),
            "true_mean": round(mean(yes), 3),
            "false_mean": round(mean(no), 3),
            "delta": round(cliffs_delta(yes, no), 3),
            "p": round(permutation_mean_diff(yes, no), 4),
        }
    for dimension, q_value in zip(instrumental, bh_adjust([item["p"] for item in instrumental.values()])):
        instrumental[dimension]["q"] = round(q_value, 4)

    overall = {
        "noise": round(mean([row["noise"] for row in rows]), 3),
        "swing": round(mean([row["swing"] for row in rows]), 3),
        "burden": round(mean([row["burden"] for row in rows]), 3),
        "energy": {energy: sum(row["energy"] == energy for row in rows) for energy in ENERGY_ORDER},
        "times": {slot: round(sum(slot in row["timeslots"] for row in rows) / len(rows), 4) for slot in TIME_ORDER},
    }
    return {
        "n": len(rows),
        "profiles": genre_profiles,
        "numeric_tests": numeric_tests,
        "energy_test": {
            "chi2": round(energy_test[0], 3),
            "effect": round(energy_test[1], 3),
            "p": round(energy_test[2], 4),
            "p_wave": round(energy_p_wave, 4),
        },
        "timeslot_tests": timeslot_tests,
        "correlations": correlations,
        "instrumental": instrumental,
        "overall": overall,
    }


def cross_validated_predictability(rows: list[dict]) -> dict:
    """Leave-one-out estimates: genre-mean model versus global-mean baseline."""
    numeric = {}
    for dimension in ("noise", "swing", "burden"):
        actual, predictions, baselines = [], [], []
        for index, row in enumerate(rows):
            train = rows[:index] + rows[index + 1 :]
            global_prediction = mean([item[dimension] for item in train])
            genre_values = [item[dimension] for item in train if item["genre"] == row["genre"]]
            prediction = mean(genre_values) if genre_values else global_prediction
            actual.append(row[dimension])
            predictions.append(prediction)
            baselines.append(global_prediction)
        model_mae = mean([abs(value - prediction) for value, prediction in zip(actual, predictions)])
        baseline_mae = mean([abs(value - prediction) for value, prediction in zip(actual, baselines)])
        overall_mean = mean(actual)
        residual_ss = sum((value - prediction) ** 2 for value, prediction in zip(actual, predictions))
        total_ss = sum((value - overall_mean) ** 2 for value in actual)
        numeric[dimension] = {
            "model_mae": round(model_mae, 3),
            "baseline_mae": round(baseline_mae, 3),
            "improvement": round((baseline_mae - model_mae) / baseline_mae, 3) if baseline_mae else 0,
            "cv_r2": round(1 - residual_ss / total_ss, 3) if total_ss else 0,
        }

    model_correct, baseline_correct = 0, 0
    timeslot_brier = {slot: {"model": [], "baseline": []} for slot in TIME_ORDER}
    for index, row in enumerate(rows):
        train = rows[:index] + rows[index + 1 :]
        global_mode = mode([item["energy"] for item in train])
        genre_energy = [item["energy"] for item in train if item["genre"] == row["genre"]]
        model_mode = mode(genre_energy) if genre_energy else global_mode
        model_correct += model_mode == row["energy"]
        baseline_correct += global_mode == row["energy"]
        genre_train = [item for item in train if item["genre"] == row["genre"]]
        for slot in TIME_ORDER:
            actual = 1 if slot in row["timeslots"] else 0
            baseline_probability = sum(slot in item["timeslots"] for item in train) / len(train)
            model_probability = (
                sum(slot in item["timeslots"] for item in genre_train) / len(genre_train)
                if genre_train
                else baseline_probability
            )
            timeslot_brier[slot]["model"].append((actual - model_probability) ** 2)
            timeslot_brier[slot]["baseline"].append((actual - baseline_probability) ** 2)
    timeslots = {}
    for slot, scores in timeslot_brier.items():
        model_score, baseline_score = mean(scores["model"]), mean(scores["baseline"])
        timeslots[slot] = {
            "model_brier": round(model_score, 3),
            "baseline_brier": round(baseline_score, 3),
            "skill": round(1 - model_score / baseline_score, 3) if baseline_score else 0,
        }
    return {
        "method": "leave-one-out genre-mean versus global-mean",
        "numeric": numeric,
        "energy": {
            "model_accuracy": round(model_correct / len(rows), 3),
            "baseline_accuracy": round(baseline_correct / len(rows), 3),
        },
        "timeslots": timeslots,
    }


def repeated_track_summary(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["match_key"]].append(row)
    result = []
    for match_key, items in grouped.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda row: row["wave_order"])
        first, last = items[0], items[-1]
        stem = Path(last["filename"]).stem
        title, separator, artist = stem.rpartition(" - ")
        if not separator:
            title, artist = stem, ""
        result.append(
            {
                "track_id": match_key,
                "title": title,
                "artist": artist,
                "waves": " → ".join(row["wave_label"].split(" · ")[0] for row in items),
                "energy_same": first["energy"] == last["energy"],
                "time_exact": set(first["timeslots"]) == set(last["timeslots"]),
                "time_jaccard": round(
                    len(set(first["timeslots"]) & set(last["timeslots"]))
                    / len(set(first["timeslots"]) | set(last["timeslots"])),
                    2,
                ),
                "noise_diff": abs(first["noise"] - last["noise"]),
                "swing_diff": abs(first["swing"] - last["swing"]),
                "burden_diff": abs(first["burden"] - last["burden"]),
            }
        )
    return result


def most_unusual_tracks(rows: list[dict], limit: int = 12) -> list[dict]:
    medians = {
        genre: {
            dimension: median([row[dimension] for row in rows if row["genre"] == genre])
            for dimension in ("noise", "swing", "burden")
        }
        for genre in GENRES
    }
    ranked = []
    for row in rows:
        deviations = {dimension: row[dimension] - medians[row["genre"]][dimension] for dimension in medians[row["genre"]]}
        ranked.append(
            {
                "title": row["title"],
                "artist": row["artist"],
                "genre": row["genre"],
                "noise": row["noise"],
                "swing": row["swing"],
                "burden": row["burden"],
                "deviations": deviations,
                "distance": sum(abs(value) for value in deviations.values()),
            }
        )
    return sorted(ranked, key=lambda item: (-item["distance"], item["title"]))[:limit]


def summarize_secondary_genres(rows: list[dict]) -> list[dict]:
    labels = sorted({label for row in rows for label in row["secondary_genres"]})
    profiles = []
    contrasts = []
    for label in labels:
        inside_rows = [row for row in rows if label in row["secondary_genres"]]
        if len(inside_rows) < 10:
            continue
        profile = {
            "genre": label,
            "n": len(inside_rows),
            "energy_test": {},
            "numeric": {},
        }
        for dimension in ("noise", "swing", "burden"):
            inside = [row[dimension] for row in inside_rows]
            outside = [row[dimension] for row in rows if label not in row["secondary_genres"]]
            item = {
                "profile": profile,
                "dimension": dimension,
                "mean": round(mean(inside), 3),
                "delta": round(cliffs_delta(inside, outside), 3),
                "p": permutation_mean_diff(inside, outside),
            }
            contrasts.append(item)
        chi2, effect, p_value = permutation_cramers(
            ["yes" if label in row["secondary_genres"] else "no" for row in rows],
            [row["energy"] for row in rows],
        )
        profile["energy_test"] = {
            "effect": round(effect, 3),
            "p": round(p_value, 4),
        }
        profiles.append(profile)
    for item, q_value in zip(contrasts, bh_adjust([item["p"] for item in contrasts])):
        item["profile"]["numeric"][item["dimension"]] = {
            "mean": item["mean"],
            "delta": item["delta"],
            "p": round(item["p"], 4),
            "q": round(q_value, 4),
        }
    energy_q = bh_adjust([profile["energy_test"]["p"] for profile in profiles])
    for profile, q_value in zip(profiles, energy_q):
        profile["energy_test"]["q"] = round(q_value, 4)
    return sorted(profiles, key=lambda profile: (-profile["n"], profile["genre"]))


def write_csvs(primary: list[dict], audit: list[dict]) -> None:
    fields = [
        "track_id", "title", "artist", "filename", "wave_label", "date", "genre", "secondary_genres",
        "instrumental", "language", "tag_source", "energy", "noise", "swing", "burden", "timeslots",
        "confidence", "note",
    ]
    with MATCHED_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in primary:
            output = {field: row.get(field) for field in fields}
            output["secondary_genres"] = " | ".join(row["secondary_genres"])
            output["timeslots"] = " | ".join(row["timeslots"])
            writer.writerow(output)
    with AUDIT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["wave", "filename", "status", "track_id"])
        writer.writeheader()
        writer.writerows(audit)


def build_report() -> None:
    observations = read_flowset()
    matched_observations, audit = match_data(observations)
    primary = dedupe_latest(matched_observations)
    wave4 = dedupe_latest([row for row in matched_observations if row["wave_key"] == "0925"])
    pre4 = dedupe_latest([row for row in matched_observations if row["wave_key"] != "0925"])
    flow_unique = dedupe_flow_latest(observations)
    write_csvs(primary, audit)

    audit_counts = Counter(row["status"] for row in audit)
    songbase_unique_ids = {
        row["track_id"]
        for row in audit
        if row["status"] in {"formal_tag", "songbase_without_formal_tag"} and row["track_id"]
    }
    genre_counts = Counter(row["genre"] for row in primary)
    source_counts = Counter(row["tag_source"] for row in primary)
    formal_tags = load_json(SONGBASE / "song_tags.json")["tracks"]
    formal_pool = Counter(tag["genre"] for tag in formal_tags.values())
    sampling_plan = [
        {
            "genre": genre,
            "tested": genre_counts.get(genre, 0),
            "untested_formal": formal_pool.get(genre, 0) - genre_counts.get(genre, 0),
            "to_target_20": max(0, 20 - genre_counts.get(genre, 0)),
        }
        for genre in GENRES
    ]
    coverage_by_wave = []
    for wave_key, wave_label, _ in WAVES:
        wave_rows = [row for row in audit if row["wave"] == wave_label]
        wave_counts = Counter(row["status"] for row in wave_rows)
        coverage_by_wave.append(
            {
                "wave_key": wave_key,
                "wave": wave_label,
                "total": len(wave_rows),
                "formal": wave_counts.get("formal_tag", 0),
                "songbase_no_tag": wave_counts.get("songbase_without_formal_tag", 0),
                "unmatched": wave_counts.get("not_matched_to_songbase", 0),
            }
        )
    report = {
        "generated": "2026-09-25",
        "coverage": {
            "flow_observations": len(observations),
            "flow_unique_filenames": len({row["match_key"] for row in observations}),
            "matched_observations": len(matched_observations),
            "songbase_matched_observations": len(observations) - audit_counts.get("not_matched_to_songbase", 0),
            "songbase_matched_unique": len(songbase_unique_ids),
            "matched_unique": len(primary),
            "wave4_matched": len(wave4),
            "pre4_matched": len(pre4),
            "formal_observation_rate": round(len(matched_observations) / len(observations), 4),
            "formal_unique_rate": round(len(primary) / len(flow_unique), 4),
            "audit": dict(audit_counts),
            "genre_counts": {genre: genre_counts.get(genre, 0) for genre in GENRES},
            "source_counts": dict(source_counts),
            "by_wave": coverage_by_wave,
        },
        "scopes": {
            "all": summarize_scope(primary),
            "pre4": summarize_scope(pre4),
            "wave4": summarize_scope(wave4),
        },
        "flowset": flowset_only_summary(flow_unique),
        "predictability": cross_validated_predictability(primary),
        "secondary_genres": summarize_secondary_genres(primary),
        "repeats": repeated_track_summary(observations),
        "outliers": most_unusual_tracks(primary),
        "sampling_plan": sampling_plan,
        "unmatched": [row for row in audit if row["status"] != "formal_tag"],
        "scope_rows": {"all": primary, "pre4": pre4, "wave4": wave4},
    }

    profiles = report["scopes"]["all"]["profiles"]
    ambient = next(profile for profile in profiles if profile["genre"] == "Ambient / Neo-Classical")
    post_rock = next(profile for profile in profiles if profile["genre"] == "Post-Rock / Cinematic")
    jazz = next(profile for profile in profiles if profile["genre"] == "Jazz / Soul")
    pred = report["predictability"]["numeric"]
    flow_correlations = {
        (item["a"], item["b"]): item["rho"] for item in report["flowset"]["correlations"]
    }

    static_summary = f"""
      <div class="finding primary"><span class="eyebrow">稳定信号</span><h3>Ambient 是低刺激、低负担区域</h3><p>{ambient['n']} 首中平静能量占 {ambient['energy']['平静']/ambient['n']:.0%}；对其余风格的噪音 / 摇摆 / 负担 Cliff’s δ = {ambient['contrasts']['noise']['delta']:.3f} / {ambient['contrasts']['swing']['delta']:.3f} / {ambient['contrasts']['burden']['delta']:.3f}。</p></div>
      <div class="finding"><span class="eyebrow">稳定信号</span><h3>Post-Rock 是当前高刺激边界</h3><p>对其余风格的噪音 / 摇摆 / 负担 Cliff’s δ = {post_rock['contrasts']['noise']['delta']:.3f} / {post_rock['contrasts']['swing']['delta']:.3f} / {post_rock['contrasts']['burden']['delta']:.3f}。</p></div>
      <div class="finding"><span class="eyebrow">维度不同义</span><h3>Jazz / Soul 的负担偏高</h3><p>负担 δ = {jazz['contrasts']['burden']['delta']:.3f}，但噪音与摇摆未同幅偏高；“负担”不是声音强度的同义词。</p></div>
      <div class="finding"><span class="eyebrow">仍需个人标注</span><h3>8–11 与 14–17 未观察到可复用的主风格关联</h3><p>两个时段的 FDR 校正后 q 分别为 {report['scopes']['all']['timeslot_tests']['8-11']['q']:.3f} / {report['scopes']['all']['timeslot_tests']['14-17']['q']:.3f}，不宜用 Tag 代替。</p></div>
      <div class="finding"><span class="eyebrow">量表优化线索</span><h3>噪音与摇摆高度重叠</h3><p>全部 {report['flowset']['n']} 首唯一曲目中 Spearman ρ = {flow_correlations[('noise','swing')]:.3f}；负担仍保留更多独立信息。</p></div>
      <div class="finding"><span class="eyebrow">可预测性边界</span><h3>Tag 适合粗筛，不适合代打标</h3><p>留一交叉验证中，噪音 / 摇摆 / 负担 MAE 仅改善 {pred['noise']['improvement']:.0%} / {pred['swing']['improvement']:.0%} / {pred['burden']['improvement']:.0%}。</p></div>
    """

    data_json = json.dumps(report, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = HTML_TEMPLATE.replace("__REPORT_DATA__", data_json).replace("__STATIC_SUMMARY__", static_summary)
    OUT.write_text(page, encoding="utf-8")
    print(f"written: {OUT} ({OUT.stat().st_size} bytes)")
    print(f"matched observations: {len(matched_observations)}/{len(observations)}")
    print(f"primary unique tracks: {len(primary)}; fourth-wave matched: {len(wave4)}")
    print(f"csv: {MATCHED_CSV.name}, audit: {AUDIT_CSV.name}")


HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Flowset × SongTag 联合分析报告</title>
<style>
:root{--bg:#f4f6f8;--panel:#fff;--ink:#18212c;--sub:#687483;--line:#dfe5ec;--accent:#3867f4;--accent2:#21a179;--warn:#bb6b16;--bad:#c9485b;--s1:#3867f4;--s2:#21a179;--s3:#e49a33;--s4:#a36ae2;--s5:#df5d74;--s6:#4f91a8;--s7:#7f8b99}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.55}button,input{font:inherit}.wrap{max-width:1240px;margin:auto;padding:30px 22px 54px}.top{display:flex;justify-content:space-between;gap:24px;align-items:flex-end;margin-bottom:18px}.top h1{font-size:27px;margin:0 0 5px}.top p{margin:0;color:var(--sub);font-size:13px}.scope{display:flex;background:#e9edf3;border-radius:10px;padding:3px;gap:3px}.scope button{border:0;background:transparent;padding:7px 12px;border-radius:8px;color:#52606e;cursor:pointer;font-size:12px;font-weight:650}.scope button.active{background:#fff;color:var(--accent);box-shadow:0 1px 4px #1d2b3a1b}.notice{border:1px solid #f0d4a8;background:#fff8eb;color:#795016;border-radius:12px;padding:11px 14px;font-size:12.5px;margin-bottom:18px}.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:18px}.kpi,.finding{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:15px 17px}.kpi b{display:block;font-size:25px}.kpi span{font-size:12px;color:var(--sub)}section{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px 22px;margin-bottom:18px}section h2{font-size:17px;margin:0 0 3px}section>.desc{font-size:12.5px;color:var(--sub);margin:0 0 17px}.findings{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px;margin-bottom:18px}.finding.primary{border-color:#b9c8ff;background:#f7f9ff}.finding h3{font-size:15px;margin:4px 0 5px}.finding p{margin:0;color:var(--sub);font-size:12px}.eyebrow{font-size:10.5px;color:var(--accent);font-weight:700;text-transform:uppercase;letter-spacing:.04em}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:22px}.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.chart h3{font-size:13px;margin:0 0 8px}.chart-note{color:var(--sub);font-size:11.5px;margin-top:7px}.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:11px;color:var(--sub);margin-top:8px}.legend span{display:flex;align-items:center;gap:5px}.sw{width:9px;height:9px;border-radius:2px;display:inline-block}svg{display:block;width:100%;height:auto}.tablewrap{overflow:auto;border:1px solid var(--line);border-radius:10px;max-height:520px}table{border-collapse:collapse;width:100%;font-size:11.5px}th,td{border-bottom:1px solid var(--line);padding:8px 9px;text-align:center;white-space:nowrap}th{position:sticky;top:0;background:#f8fafc;color:var(--sub);z-index:2}td.left{text-align:left}.pill{display:inline-block;padding:2px 7px;border-radius:999px;background:#edf2ff;color:#3458bd;font-size:10px}.signal{display:inline-block;border-radius:999px;padding:2px 7px;font-size:10px;font-weight:700}.signal.stable{background:#e8f6ef;color:#14724d}.signal.hint{background:#fff3df;color:#9a5a0a}.signal.none{background:#eef1f5;color:#647180}.muted{color:var(--sub)}.effect{display:flex;align-items:center;gap:8px}.effect-track{width:90px;height:7px;background:#edf0f4;border-radius:8px;overflow:hidden}.effect-track i{display:block;height:100%;background:var(--accent);border-radius:8px}.warning{color:var(--warn)}.bad{color:var(--bad)}.method{font-size:12px;color:var(--sub)}details{border-top:1px solid var(--line);padding:12px 0}details:first-child{border-top:0}summary{cursor:pointer;color:var(--ink);font-weight:650}.footer{text-align:center;color:var(--sub);font-size:11.5px;margin-top:22px}.tooltip{position:fixed;opacity:0;pointer-events:none;background:#16202b;color:#fff;padding:7px 9px;border-radius:7px;font-size:11px;max-width:260px;z-index:99;box-shadow:0 5px 15px #0003}.small-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:10px}.mini{border:1px solid var(--line);border-radius:10px;padding:10px}.mini b{font-size:18px;display:block}.mini span{font-size:11px;color:var(--sub)}
@media(max-width:900px){.kpis,.findings{grid-template-columns:repeat(2,1fr)}.grid2,.grid3{grid-template-columns:1fr}.top{align-items:flex-start;flex-direction:column}}@media(max-width:520px){.kpis,.findings{grid-template-columns:1fr}.wrap{padding:18px 12px}.scope{width:100%;flex-wrap:wrap}}
</style>
</head>
<body>
<div class="wrap">
  <header class="top"><div><h1>Flowset × SongTag 联合分析</h1><p>个人听感维度与正式人工音乐标签的关系 · 去重主分析 · 离线报告</p></div><div class="scope" id="scope"><button class="active" data-scope="all">主分析</button><button data-scope="pre4">前三波</button><button data-scope="wave4">第四波</button></div></header>
  <div class="notice">本报告描述“你如何感知不同类型音乐”，并不直接等同于喜欢／不喜欢。关联不代表因果；样本少于 10 首的风格仅作探索性观察。</div>
  <div class="notice" style="border-color:#cdd8ff;background:#f6f8ff;color:#40507f">顶部范围切换会更新主风格样本构成、数值、能量、时段、Instrumental 和曲目明细。总体结论、186 首全量相关、预测、重测、异常与补样模块固定使用各自标明的口径。</div>
  <div class="kpis" id="kpis"></div>
  <p class="desc" style="margin:0 0 8px;color:var(--sub);font-size:12px">总体主结论（固定使用 131 首主分析样本）</p><div class="findings">__STATIC_SUMMARY__</div>

  <section><h2>决策摘要：Tag 可以做什么</h2><p class="desc">把结果转成选曲与打标决策，而不只是看相关系数。</p><div class="tablewrap"><table><thead><tr><th>级别</th><th>可用于</th><th>不应用于</th><th>当前证据</th></tr></thead><tbody><tr><td><span class="signal stable">可粗筛</span></td><td class="left">用主风格预判大致刺激度，尤其 Ambient / Post-Rock 两端</td><td class="left">直接代填 1–10 分</td><td>数值维度 ε² = .34–.41</td></tr><tr><td><span class="signal hint">仅作先验</span></td><td class="left">能量、11–14、17–20 的选曲提示</td><td class="left">认为同风格内听感相同</td><td>能量 V 约 .28，时段受第四波放大</td></tr><tr><td><span class="signal none">必须保留 Flowset</span></td><td class="left">个人负担、8–11、14–17、风格内异常曲目</td><td class="left">用 Tag 直接替代个人判断</td><td>时段交叉验证接近无增益</td></tr></tbody></table></div></section>

  <section><h2>1. 数据覆盖与分析边界</h2><p class="desc">正式主分析只使用 SongBase 中已人工确认的 Tag。重复歌曲采用最新一次 Flowset 标注，重复记录单独用于稳定性检查。</p><div class="grid3"><div class="chart"><h3>观察记录匹配</h3><div id="observationCoverageChart"></div></div><div class="chart"><h3>唯一曲目匹配</h3><div id="uniqueCoverageChart"></div></div><div class="chart"><h3>正式标签样本构成</h3><div id="genreCountChart"></div><div class="chart-note">Electronic 仅 5 首，标为探索性样本；n&lt;10 不生成强结论。</div></div></div><h3 style="font-size:13px;margin:18px 0 8px">按波次的匹配审计</h3><div id="waveCoverage" class="tablewrap"></div></section>

  <section><h2>2. 风格与三个主观数值维度</h2><p class="desc">箱体表示 Q1–Q3，粗线是中位数，细线是范围，圆点是均值。1–10 为序数量表，推断采用秩检验与置换检验。</p><div class="grid3"><div class="chart"><h3>噪音程度</h3><div id="noiseChart"></div></div><div class="chart"><h3>摇摆速率</h3><div id="swingChart"></div></div><div class="chart"><h3>负担程度</h3><div id="burdenChart"></div></div></div><div id="numericEffects" class="tablewrap" style="margin-top:15px"></div><h3 style="font-size:13px;margin:18px 0 8px">波次稳健性</h3><div id="robustnessTable" class="tablewrap"></div><div class="chart-note">前三波 n=52，第四波 n=83；4 首跨波重复曲会同时出现在两个稳健性范围中，但主分析仅保留它们的最新标注。第四波主要放大已有数值方向，没有将 Ambient / Post-Rock 的主方向反转；时段关联则明显更受第四波驱动。</div></section>

  <section><h2>3. 风格与能量状态</h2><p class="desc">每条横条为该风格内部的能量构成。Cramér’s V 衡量类别关联强度。</p><div id="energyChart"></div><div class="legend"><span><i class="sw" style="background:#4f91d9"></i>平静</span><span><i class="sw" style="background:#2eae86"></i>渐进</span><span><i class="sw" style="background:#e69a36"></i>有冲劲</span><span><i class="sw" style="background:#d94f63"></i>爆发</span><span><i class="sw" style="background:#8c96a3"></i>不确定</span></div><div id="energyEffect" class="chart-note"></div></section>

  <section><h2>4. 风格与适合时段</h2><p class="desc">单曲可命中多个时段；格内显示该风格中命中对应时段的比例。</p><div id="timeHeatmap"></div><div id="timeEffects" class="tablewrap" style="margin-top:15px"></div></section>

  <section><h2>5. 副风格的探索性增量关系</h2><p class="desc">固定使用 131 首主分析样本。副风格可多选，表中是“命中该副风格 vs 未命中”的 one-vs-rest 比较；仅展示 n≥10，不与主风格效应直接相加。</p><div id="secondaryTable" class="tablewrap"></div></section>

  <section><h2>6. 维度互相关与纯音乐效应</h2><p class="desc">相关矩阵固定使用全部 186 首唯一 Flowset 曲目，避免 Tag 缺失造成偏差；纯音乐比较会随顶部范围切换，仅使用 instrumental 明确为 true / false 的曲目。</p><div class="grid2"><div class="chart"><h3>三个数值维度的 Spearman 相关</h3><div id="corrChart"></div></div><div class="chart"><h3>纯音乐 vs 非纯音乐</h3><div id="instrumentalChart"></div></div></div></section>

  <section><h2>7. 主风格能预测多少 Flowset？</h2><p class="desc">固定使用 131 首主分析样本的探索性留一估计：每次隐藏一首，只用余下曲目的主风格均值预测，与无 Tag 全局均值基线比较。未按艺人分组，也未把波次直接纳入预测模型，因此改善幅度应视为上限线索。</p><div id="predictionChart"></div></section>

  <section><h2>8. 重复标注稳定性</h2><p class="desc">固定使用全部 191 次标注识别跨波重复。同一首歌跨波重复出现，是检查个人标注一致性的自然测试；样本只有 5 首，仅用于质检。</p><div id="repeatTable" class="tablewrap"></div></section>

  <section><h2>9. 曲目明细与风格内异常</h2><p class="desc">下方曲目明细会随顶部范围切换；异常榜固定使用 131 首主分析样本。异常是指在同一主风格中，三个数值维度偏离该风格中位数较大的曲目。</p><h3 style="font-size:13px;margin:0 0 8px">偏离最大的 12 首</h3><div id="outlierTable" class="tablewrap" style="margin-bottom:16px"></div><input id="search" type="search" placeholder="搜索当前范围的曲名、艺人或风格" style="width:100%;border:1px solid var(--line);border-radius:9px;padding:9px 11px;margin-bottom:10px"><div id="detailTable" class="tablewrap"></div></section>

  <section><h2>10. 下一波补样优先级</h2><p class="desc">固定基于 131 首主分析样本。若要把主风格组间比较做得更稳，先把不足 20 首的类别补起来；下表仅是数据设计建议，不会自动改曲库。</p><div id="samplingTable" class="tablewrap"></div></section>

  <section><h2>11. 方法、风险与待补数据</h2><div class="method"><details open><summary>当前最可靠的使用方式</summary><p>将结果用于建立“风格先验”：Tag 可以帮助粗筛，但负担、适合时段等个人化维度应保留 Flowset 标注。主结果使用 131 首唯一曲目；前三波 52 首与第四波 83 首分开显示，两者含 4 首跨波重复曲。</p></details><details><summary>统计口径</summary><p>风格与 1–10 维度使用 Kruskal–Wallis H、ε² 效应量和 3,000 次置换检验；类别关系使用偏差校正 Cramér’s V；同时在波次内打乱做控制波次的稳健性检查。同一家族的检验用 Benjamini–Hochberg 校正。</p></details><details><summary>副风格与其他 Tag</summary><p>81/131 首主样本有副风格，因此本版已加入 n≥10 的 one-vs-rest 探索分析。Instrumental 保留 true / false / null 三态；语言的显式非默认标签仅 11 首，暂不做语言效应推断。</p></details><details><summary>匹配与音频身份风险</summary><p>主分析仅接受“规范化曲名 + 艺人唯一命中”，不使用只看曲名的模糊匹配。3 首明确别名可作人工 override，但本保守版未纳入。第一波 Cœur croisé 与第二波 fu uh 存在历史音频身份风险，本报告不将文件名等同于已确认音频身份。</p></details><details><summary>仍需补齐的数据</summary><p>24 次 Flowset 记录可匹配到 SongBase 但尚无正式 Tag；32 次无法可靠匹配到当前 SongBase。完整清单见同目录的 flowset_tag_match_audit.csv。</p></details></div></section>
  <div class="footer">数据来源：Flowset 四波个人标注 + SongBase 正式人工 Tag · 报告生成于 2026-09-25</div>
</div>
<div class="tooltip" id="tip"></div>
<script id="report-data" type="application/json">__REPORT_DATA__</script>
<script>
const REPORT=JSON.parse(document.getElementById('report-data').textContent);
const $=s=>document.querySelector(s);let scopeKey='all';
const COLORS=['#3867f4','#21a179','#e49a33','#a36ae2','#df5d74','#4f91a8','#7f8b99'];
const GENRE_COLORS={'Ambient / Neo-Classical':'#3867f4','Post-Rock / Cinematic':'#21a179','Electronic':'#e49a33','Jazz / Soul':'#a36ae2','Folk / Singer-Songwriter':'#df5d74','Rock / Alternative':'#4f91a8','Hip-Hop / R&B':'#7f8b99'};
const ENERGY_COLORS={'平静':'#4f91d9','渐进':'#2eae86','有冲劲':'#e69a36','爆发':'#d94f63','不确定':'#8c96a3'};
const DIM_CN={noise:'噪音',swing:'摇摆',burden:'负担'};
const tip=$('#tip');function showTip(text,e){tip.innerHTML=text;tip.style.opacity=1;tip.style.left=Math.min(e.clientX+12,innerWidth-275)+'px';tip.style.top=Math.min(e.clientY+12,innerHeight-120)+'px'}function hideTip(){tip.style.opacity=0}
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function scope(){return REPORT.scopes[scopeKey]}
function pText(p){return p<.001?'p < 0.001':`p = ${p.toFixed(3)}`}
function qText(q){return q<.001?'q < 0.001':`q = ${q.toFixed(3)}`}
function effectWord(v){return v<.06?'弱':v<.14?'中等':'较强'}
function signal(q){return q<.05?'<span class="signal stable">检测到关联</span>':q<.10?'<span class="signal hint">提示</span>':'<span class="signal none">证据不足</span>'}
function renderKpis(){const s=scope(),c=REPORT.coverage,names={all:'去重主分析',pre4:'前三波样本',wave4:'第四波样本'};$('#kpis').innerHTML=[['Flowset 标注',c.flow_observations,`${c.flow_unique_filenames} 首唯一曲目`],['正式 Tag 主样本',c.matched_unique,`${Math.round(c.formal_unique_rate*100)}% 唯一曲覆盖`],[names[scopeKey],s.n,'首曲目'],['风格种类',s.profiles.length,'个主标签']].map(x=>`<div class="kpi"><b>${x[1]}</b><span>${x[0]} · ${x[2]}</span></div>`).join('')}
function svgBarChart(items,opt={}){const W=560,row=31,left=190,right=48,H=items.length*row+22,max=opt.max||Math.max(...items.map(x=>x.value),1),avg=opt.avg;let svg=`<svg viewBox="0 0 ${W} ${H}" aria-label="${esc(opt.label||'bar chart')}">`;if(avg!=null){const ax=left+(W-left-right)*avg/max;svg+=`<line x1="${ax}" x2="${ax}" y1="2" y2="${H-18}" stroke="#c34f62" stroke-dasharray="4 3"/>`}items.forEach((x,i)=>{const y=i*row+6,w=(W-left-right)*x.value/max;svg+=`<text x="${left-8}" y="${y+13}" text-anchor="end" font-size="11" fill="#46515e">${esc(x.label)}</text><rect x="${left}" y="${y}" width="${Math.max(w,1)}" height="18" rx="4" fill="${x.color||COLORS[i%COLORS.length]}" opacity=".86"/><text x="${Math.min(left+w+6,W-28)}" y="${y+13}" font-size="11" fill="#202a35" font-weight="650">${opt.percent?(x.value*100).toFixed(0)+'%':x.value.toFixed(opt.decimals??1)}</text>`});return svg+'</svg>'}
function renderCoverage(){const c=REPORT.coverage;$('#observationCoverageChart').innerHTML=svgBarChart([{label:'Flowset 观察',value:c.flow_observations},{label:'SongBase 可匹配',value:c.songbase_matched_observations},{label:'有正式 Tag',value:c.matched_observations}],{max:c.flow_observations,decimals:0});$('#uniqueCoverageChart').innerHTML=svgBarChart([{label:'Flowset 唯一曲',value:c.flow_unique_filenames},{label:'SongBase 可匹配',value:c.songbase_matched_unique},{label:'有正式 Tag',value:c.matched_unique}],{max:c.flow_unique_filenames,decimals:0});const s=scope();$('#genreCountChart').innerHTML=svgBarChart(s.profiles.map(p=>({label:p.label+(p.n<10?' · 探索性':''),value:p.n,color:GENRE_COLORS[p.genre]})),{decimals:0});$('#waveCoverage').innerHTML='<table><thead><tr><th>波次</th><th>总标注</th><th>正式 Tag</th><th>SongBase 无正式 Tag</th><th>未匹配</th></tr></thead><tbody>'+c.by_wave.map(x=>`<tr><td>${esc(x.wave)}</td><td>${x.total}</td><td>${x.formal}</td><td>${x.songbase_no_tag}</td><td>${x.unmatched}</td></tr>`).join('')+'</tbody></table>'}
function svgBoxPlot(profiles,dim){const W=570,left=205,right=30,row=37,H=profiles.length*row+36,x=v=>left+(v-1)/9*(W-left-right);let svg=`<svg viewBox="0 0 ${W} ${H}" aria-label="${DIM_CN[dim]} 箱线图">`;[1,5,10].forEach(v=>svg+=`<text x="${x(v)}" y="${H-4}" text-anchor="middle" font-size="10" fill="#7a8591">${v}</text><line x1="${x(v)}" x2="${x(v)}" y1="2" y2="${H-20}" stroke="#edf0f4"/>`);profiles.forEach(p=>{const y=profiles.indexOf(p)*row+7,cy=y+11,color=GENRE_COLORS[p.genre];svg+=`<text x="${left-8}" y="${y+15}" text-anchor="end" font-size="10.5" fill="#46515e">${esc(p.label)} · n=${p.n}${p.n<10?'*':''}</text><line x1="${x(p[dim+'_min'])}" x2="${x(p[dim+'_max'])}" y1="${cy}" y2="${cy}" stroke="#8692a0"/><rect x="${x(p[dim+'_q1'])}" y="${y+2}" width="${Math.max(2,x(p[dim+'_q3'])-x(p[dim+'_q1']))}" height="18" rx="4" fill="${color}" opacity=".34"/><line x1="${x(p[dim+'_median'])}" x2="${x(p[dim+'_median'])}" y1="${y}" y2="${y+22}" stroke="${color}" stroke-width="3"/><circle cx="${x(p[dim])}" cy="${cy}" r="3" fill="${color}"/>`});return svg+'</svg>'}
function renderNumeric(){const s=scope();['noise','swing','burden'].forEach(dim=>{$('#'+dim+'Chart').innerHTML=svgBoxPlot(s.profiles,dim)});$('#numericEffects').innerHTML='<table><thead><tr><th>维度</th><th>H</th><th>ε²</th><th>效应</th><th>FDR</th><th>波次内置换</th></tr></thead><tbody>'+['noise','swing','burden'].map(dim=>{const t=s.numeric_tests[dim];return `<tr><td>${DIM_CN[dim]}</td><td>${t.h.toFixed(2)}</td><td>${t.effect.toFixed(3)}</td><td>${effectWord(t.effect)}</td><td>${qText(t.q)}</td><td>${pText(t.p_wave)}</td></tr>`}).join('')+'</tbody></table>';const scopes=[['all','主分析'],['pre4','前三波'],['wave4','第四波']];$('#robustnessTable').innerHTML='<table><thead><tr><th>范围</th><th>n</th><th>噪音 ε²</th><th>摇摆 ε²</th><th>负担 ε²</th><th>能量 V</th></tr></thead><tbody>'+scopes.map(([k,label])=>{const x=REPORT.scopes[k];return `<tr><td>${label}</td><td>${x.n}</td><td>${x.numeric_tests.noise.effect.toFixed(3)}</td><td>${x.numeric_tests.swing.effect.toFixed(3)}</td><td>${x.numeric_tests.burden.effect.toFixed(3)}</td><td>${x.energy_test.effect.toFixed(3)}</td></tr>`}).join('')+'</tbody></table>'}
function renderEnergy(){const s=scope(),W=900,left=205,right=45,row=34,H=s.profiles.length*row+28,totalW=W-left-right;let svg=`<svg viewBox="0 0 ${W} ${H}">`;s.profiles.forEach((p,i)=>{const y=i*row+6,total=Object.values(p.energy).reduce((a,b)=>a+b,0);svg+=`<text x="${left-9}" y="${y+15}" text-anchor="end" font-size="11">${esc(p.label)} · n=${p.n}</text>`;let x=left;Object.entries(p.energy).forEach(([e,n])=>{if(!n)return;const w=totalW*n/total;svg+=`<rect x="${x}" y="${y}" width="${w}" height="21" fill="${ENERGY_COLORS[e]}" data-tip="${esc(e)} ${n} 首（${Math.round(n/total*100)}%）"></rect>`;if(w>42)svg+=`<text x="${x+w/2}" y="${y+15}" text-anchor="middle" fill="#fff" font-size="10">${Math.round(n/total*100)}%</text>`;x+=w})});svg+='</svg>';$('#energyChart').innerHTML=svg;$('#energyChart').querySelectorAll('[data-tip]').forEach(el=>{el.addEventListener('mousemove',e=>showTip(el.dataset.tip,e));el.addEventListener('mouseleave',hideTip)});const t=s.energy_test;$('#energyEffect').innerHTML=`风格 × 能量：偏差校正 Cramér’s V = <b>${t.effect.toFixed(3)}</b>，${pText(t.p)}；波次内置换 ${pText(t.p_wave)}。`}
function heatColor(v){const a=.10+.72*v;return `rgba(56,103,244,${a})`}
function renderTimes(){const s=scope(),W=850,left=220,top=36,cw=145,ch=34,H=top+s.profiles.length*ch+12;let svg=`<svg viewBox="0 0 ${W} ${H}">`;['8-11','11-14','14-17','17-20'].forEach((slot,j)=>svg+=`<text x="${left+j*cw+cw/2}" y="22" text-anchor="middle" font-size="11" fill="#687483">${slot}</text>`);s.profiles.forEach((p,i)=>{svg+=`<text x="${left-8}" y="${top+i*ch+21}" text-anchor="end" font-size="11">${esc(p.label)} · n=${p.n}</text>`;['8-11','11-14','14-17','17-20'].forEach((slot,j)=>{const v=p.times[slot],x=left+j*cw,y=top+i*ch;svg+=`<rect x="${x+2}" y="${y+2}" width="${cw-4}" height="${ch-4}" rx="5" fill="${heatColor(v)}"/><text x="${x+cw/2}" y="${y+22}" text-anchor="middle" font-size="11" fill="${v>.55?'#fff':'#26313d'}" font-weight="650">${Math.round(v*100)}%</text>`})});$('#timeHeatmap').innerHTML=svg+'</svg>';$('#timeEffects').innerHTML='<table><thead><tr><th>时段</th><th>校正 V</th><th>FDR</th><th>结论级别</th><th>波次内置换</th></tr></thead><tbody>'+['8-11','11-14','14-17','17-20'].map(slot=>{const t=s.timeslot_tests[slot];return `<tr><td>${slot}</td><td>${t.effect.toFixed(3)}</td><td>${qText(t.q)}</td><td>${signal(t.q)}</td><td>${pText(t.p_wave)}</td></tr>`}).join('')+'</tbody></table>'}
function renderSecondary(){const rows=REPORT.secondary_genres;$('#secondaryTable').innerHTML='<table><thead><tr><th>副风格</th><th>n</th><th>噪音 δ / q</th><th>摇摆 δ / q</th><th>负担 δ / q</th><th>能量校正 V / q</th></tr></thead><tbody>'+rows.map(x=>`<tr><td class="left">${esc(x.genre)}</td><td>${x.n}</td><td>${x.numeric.noise.delta.toFixed(3)} / ${x.numeric.noise.q.toFixed(3)}</td><td>${x.numeric.swing.delta.toFixed(3)} / ${x.numeric.swing.q.toFixed(3)}</td><td>${x.numeric.burden.delta.toFixed(3)} / ${x.numeric.burden.q.toFixed(3)}</td><td>${x.energy_test.effect.toFixed(3)} / ${x.energy_test.q.toFixed(3)}</td></tr>`).join('')+'</tbody></table>'}
function renderRelations(){const s=scope(),dims=['noise','swing','burden'],map={};REPORT.flowset.correlations.forEach(x=>{map[x.a+'|'+x.b]=x.rho;map[x.b+'|'+x.a]=x.rho});let svg='<svg viewBox="0 0 420 300">';dims.forEach((a,i)=>{svg+=`<text x="105" y="${75+i*65}" text-anchor="end" font-size="12">${DIM_CN[a]}</text><text x="${155+i*75}" y="32" text-anchor="middle" font-size="12">${DIM_CN[a]}</text>`;dims.forEach((b,j)=>{const v=a===b?1:map[a+'|'+b],x=120+j*75,y=48+i*65,alpha=.12+.72*Math.abs(v);svg+=`<rect x="${x}" y="${y}" width="67" height="57" rx="6" fill="rgba(${v>=0?'56,103,244':'217,79,99'},${alpha})"/><text x="${x+33.5}" y="${y+34}" text-anchor="middle" fill="${Math.abs(v)>.5?'#fff':'#1f2933'}" font-size="12" font-weight="700">${v.toFixed(2)}</text>`})});$('#corrChart').innerHTML=svg+'</svg>';const rows=['noise','swing','burden'].map(d=>{const x=s.instrumental[d];return {label:DIM_CN[d],value:x.true_mean,second:x.false_mean,delta:x.delta,p:x.p,q:x.q,n1:x.true_n,n0:x.false_n}});let out='<table><thead><tr><th>维度</th><th>纯音乐均值</th><th>非纯音乐均值</th><th>Cliff’s δ</th><th>FDR</th></tr></thead><tbody>'+rows.map(r=>`<tr><td>${r.label}</td><td>${r.value.toFixed(2)} (n=${r.n1})</td><td>${r.second.toFixed(2)} (n=${r.n0})</td><td>${r.delta.toFixed(3)}</td><td>${qText(r.q)}</td></tr>`).join('')+'</tbody></table>';$('#instrumentalChart').innerHTML='<div class="tablewrap">'+out+'</div>'}
function renderPrediction(){const p=REPORT.predictability,n=p.numeric;const numericCards=['noise','swing','burden'].map(d=>`<div class="mini"><span>${DIM_CN[d]} · 留一 MAE</span><b>${n[d].model_mae.toFixed(2)}</b><span>基线 ${n[d].baseline_mae.toFixed(2)} · 改善 ${(n[d].improvement*100).toFixed(0)}% · CV-R² ${n[d].cv_r2.toFixed(2)}</span></div>`).join('');const timeCards=['8-11','11-14','14-17','17-20'].map(slot=>{const x=p.timeslots[slot];return `<div class="mini"><span>${slot} · Brier skill</span><b>${x.skill>0?'+':''}${x.skill.toFixed(2)}</b><span>0 = 与无 Tag 基线一样；负值 = 更差</span></div>`}).join('');$('#predictionChart').innerHTML=`<div class="small-grid">${numericCards}<div class="mini"><span>能量状态 · 准确率</span><b>${(p.energy.model_accuracy*100).toFixed(0)}%</b><span>无 Tag 基线 ${(p.energy.baseline_accuracy*100).toFixed(0)}% · 仅提升 ${((p.energy.model_accuracy-p.energy.baseline_accuracy)*100).toFixed(1)}pp</span></div>${timeCards}</div>`}
function renderRepeats(){const r=REPORT.repeats;$('#repeatTable').innerHTML='<table><thead><tr><th>曲目</th><th>波次</th><th>能量一致</th><th>时段 Jaccard</th><th>噪音差</th><th>摇摆差</th><th>负担差</th></tr></thead><tbody>'+r.map(x=>`<tr><td class="left">${esc(x.title)}<br><span class="muted">${esc(x.artist)}</span></td><td>${esc(x.waves)}</td><td>${x.energy_same?'是':'否'}</td><td>${x.time_jaccard.toFixed(2)}</td><td>${x.noise_diff}</td><td>${x.swing_diff}</td><td>${x.burden_diff}</td></tr>`).join('')+'</tbody></table>'}
function currentRows(){return REPORT.scope_rows[scopeKey]}
function renderDetails(){const q=$('#search').value.trim().toLowerCase(),rows=currentRows().filter(r=>!q||[r.title,r.artist,r.genre].join(' ').toLowerCase().includes(q));$('#detailTable').innerHTML='<table><thead><tr><th>曲目</th><th>风格</th><th>能量</th><th>噪音</th><th>摇摆</th><th>负担</th><th>时段</th><th>波次</th></tr></thead><tbody>'+rows.map(r=>`<tr><td class="left">${esc(r.title)}<br><span class="muted">${esc(r.artist)}</span></td><td><span class="pill">${esc(r.genre)}</span></td><td>${esc(r.energy)}</td><td>${r.noise}</td><td>${r.swing}</td><td>${r.burden}</td><td>${r.timeslots.join(' / ')}</td><td>${esc(r.wave_label.split(' · ')[0])}</td></tr>`).join('')+'</tbody></table>'}
function signed(v){return `${v>0?'+':''}${v}`}
function renderOutliers(){const r=REPORT.outliers;$('#outlierTable').innerHTML='<table><thead><tr><th>曲目</th><th>风格</th><th>噪音偏离</th><th>摇摆偏离</th><th>负担偏离</th><th>总偏离</th></tr></thead><tbody>'+r.map(x=>`<tr><td class="left">${esc(x.title)}<br><span class="muted">${esc(x.artist)}</span></td><td>${esc(x.genre)}</td><td>${signed(x.deviations.noise)}</td><td>${signed(x.deviations.swing)}</td><td>${signed(x.deviations.burden)}</td><td>${x.distance.toFixed(1)}</td></tr>`).join('')+'</tbody></table>'}
function renderSampling(){const rows=REPORT.sampling_plan.slice().sort((a,b)=>b.to_target_20-a.to_target_20);$('#samplingTable').innerHTML='<table><thead><tr><th>主风格</th><th>已测唯一曲</th><th>建议补至 20</th><th>SongBase 中尚未测正式 Tag</th><th>优先级</th></tr></thead><tbody>'+rows.map(x=>`<tr><td class="left">${esc(x.genre)}</td><td>${x.tested}</td><td>${x.to_target_20}</td><td>${x.untested_formal}</td><td>${x.tested<10?'<span class="signal hint">高</span>':x.to_target_20?'中':'已达标'}</td></tr>`).join('')+'</tbody></table>'}
function render(){renderKpis();renderCoverage();renderNumeric();renderEnergy();renderTimes();renderSecondary();renderRelations();renderPrediction();renderRepeats();renderOutliers();renderSampling();renderDetails()}
$('#scope').querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{scopeKey=b.dataset.scope;$('#scope').querySelectorAll('button').forEach(x=>x.classList.toggle('active',x===b));render()}));$('#search').addEventListener('input',renderDetails);render();
</script>
</body></html>'''


if __name__ == "__main__":
    build_report()
