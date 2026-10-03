#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the offline Tag/Flowset -> transition preference analysis report.

The report deliberately excludes the fifth and eighth transition-review
exports.  It uses the current formal SongBase tags, all five deduplicated
Flowset annotation waves, and questionSetId-verified question/review pairs.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SONGBASE = REPO / "SongBase"
TRANSITION_DIR = Path("/Users/kaluozheng/Desktop/SongBase 歌曲标签库/风格衔接测试")
OUT_HTML = HERE / "flowset_transition_relationship_report.html"
OUT_ROWS = HERE / "flowset_transition_analysis_rows.csv"
OUT_PRIORITY = HERE / "flowset_transition_flowset_priority.csv"


PAIRS = [
    ("flowset-style-transition-review-first-test.json", "题目-第1组.json", "初始覆盖 1", "initial"),
    ("flowset-style-transition-review-second-test.json", "题目-第2组.json", "初始覆盖 2", "initial"),
    ("flowset-style-transition-review-third-test.json", "题目-第3组.json", "初始覆盖 3", "initial"),
    ("flowset-style-transition-review-fourth-test.json", "题目-第4组.json", "初始覆盖 4", "initial"),
    ("flowset-style-transition-review-sixth-test.json", "题目-第6组.json", "矩阵补全 2", "matrix"),
    ("flowset-style-transition-review- seventh-test.json", "题目-第7组.json", "矩阵补全 3", "matrix"),
    ("flowset-style-transition-review-ninth test.json", "题目-第9组-桥接方向.json", "桥接方向", "direction"),
    ("flowset-style-transition-review-tenth test.json", "题目-第10组-cost-risk校准.json", "声学校准", "acoustic"),
]

# These responses were made against a wrong/ambiguous recording in the historical
# package.  The full question is excluded because either candidate can affect the
# comparative judgement.
KNOWN_AUDIO_MISMATCH_QUESTIONS = {
    "style-transition-016",
    "style-transition-034",
    "style-transition-054",
    "style-transition-096",
    "style-transition-034-cross-session-10",
}

FAMILY_LABELS = {
    "initial": "初始覆盖",
    "matrix": "矩阵补全",
    "direction": "桥接方向",
    "acoustic": "声学校准",
}

FLOWSET_WAVES = [
    ("2026-07-16", "音乐第一波测试", "Flowset-个人审美样本-郑卡罗-2026-07-16.json"),
    ("2026-07-22", "音乐第二波测试", "Flowset-个人审美样本-郑卡罗-2026-07-22.json"),
    ("2026-07-28", "音乐第三波测试", "Flowset-个人审美样本-郑卡罗-2026-07-28.json"),
    ("2026-09-25", "音乐第四波测试", "Flowset-个人审美样本-郑卡罗-2026-09-25.json"),
    ("2026-09-26", "音乐第五波测试", "Flowset-个人审美样本·第五波高价值补标-anonymous-2026-09-26.json"),
]

_HASH_CACHE = {}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path):
    key = (str(path), path.stat().st_size, path.stat().st_mtime_ns)
    if key in _HASH_CACHE:
        return _HASH_CACHE[key]
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    _HASH_CACHE[key] = value
    return value


def mean(values):
    values = list(values)
    return sum(values) / len(values) if values else None


def median(values):
    values = list(values)
    return statistics.median(values) if values else None


def rounded(value, digits=3):
    return None if value is None or not math.isfinite(value) else round(value, digits)


def rankdata(values):
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and values[order[j]] == values[order[i]]:
            j += 1
        rank = (i + j - 1) / 2 + 1
        for k in range(i, j):
            ranks[order[k]] = rank
        i = j
    return ranks


def pearson(xs, ys):
    if len(xs) < 3:
        return None
    mx, my = mean(xs), mean(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    den = math.sqrt(sum(x * x for x in dx) * sum(y * y for y in dy))
    return sum(a * b for a, b in zip(dx, dy)) / den if den else None


def spearman(xs, ys):
    return pearson(rankdata(xs), rankdata(ys)) if len(xs) >= 3 else None


def stable_hash(text):
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], 16)


def track_id(track):
    if "track" in track:
        track = track["track"]
    return track.get("songbaseTrackId") or track.get("trackId") or track.get("id")


def track_payload(item):
    return item.get("track", item)


def bridge_class(source_tag, target_tag):
    sg = source_tag["genre"]
    tg = target_tag["genre"]
    ss = set(source_tag.get("secondary_genres") or [])
    ts = set(target_tag.get("secondary_genres") or [])
    if sg == tg:
        return "same_main"
    source_opens = tg in ss
    target_echoes = sg in ts
    if source_opens and target_echoes:
        return "bidirectional"
    if source_opens:
        return "source_opens"
    if target_echoes:
        return "target_echoes"
    if ss & ts:
        return "shared_secondary"
    return "no_overlap"


BRIDGE_LABELS = {
    "same_main": "同主风格",
    "bidirectional": "双向桥接",
    "source_opens": "前曲副风格包含后曲",
    "target_echoes": "后曲副风格回应前曲",
    "shared_secondary": "共享副风格",
    "no_overlap": "无 Tag 重叠",
}


def load_flowset():
    latest = {}
    with (HERE / "flowset_tag_matched.csv").open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            current = {
                "track_id": row["track_id"],
                "energy": row["energy"],
                "noise": int(row["noise"]),
                "swing": int(row["swing"]),
                "burden": int(row["burden"]),
                "timeslots": [item.strip() for item in row["timeslots"].split("|") if item.strip()],
                "wave": row["wave_label"],
                "date": row["date"],
            }
            previous = latest.get(row["track_id"])
            if previous is None or current["date"] >= previous["date"]:
                latest[row["track_id"]] = current
    return latest


def load_flowset_by_audio_hash():
    """Recover labels missed by title/artist matching using exact audio identity."""
    latest = {}
    for wave_order, (date, folder_name, export_name) in enumerate(FLOWSET_WAVES, start=1):
        payload = load_json(HERE / export_name)
        audio_dir = HERE / folder_name
        for track in payload["tracks"]:
            audio_path = audio_dir / track["file"]["name"]
            if not audio_path.is_file():
                continue
            selections = {item["dimension"]: item["labels"] for item in track.get("selections", [])}
            required = {"能量状态", "噪音程度", "摇摆速率", "负担程度", "适合的时段"}
            if not required.issubset(selections):
                continue
            observation = {
                "track_id": "",
                "energy": selections["能量状态"][0],
                "noise": int(selections["噪音程度"][0]),
                "swing": int(selections["摇摆速率"][0]),
                "burden": int(selections["负担程度"][0]),
                "timeslots": selections["适合的时段"],
                "wave": folder_name,
                "date": date,
                "wave_order": wave_order,
                "matched_by": "audio_sha256",
            }
            digest = file_sha256(audio_path)
            previous = latest.get(digest)
            if previous is None or observation["wave_order"] >= previous["wave_order"]:
                latest[digest] = observation
    return latest


def load_rows():
    tag_doc = load_json(SONGBASE / "song_tags.json")
    tags = tag_doc["tracks"]
    flowset = load_flowset()
    flowset_by_hash = load_flowset_by_audio_hash()
    rows = []
    questions = {}
    responses = {}
    pairing_audit = []
    track_meta = {}
    tag_drift = {}

    def resolve_flow(track_identifier, metadata):
        if track_identifier in flowset:
            return flowset[track_identifier]
        filename = metadata.get("filename")
        audio_path = SONGBASE / "SongResources" / filename if filename else None
        if not audio_path or not audio_path.is_file():
            return None
        matched = flowset_by_hash.get(file_sha256(audio_path))
        if not matched:
            return None
        resolved = dict(matched)
        resolved["track_id"] = track_identifier
        flowset[track_identifier] = resolved
        return resolved

    for review_name, question_name, batch_label, family in PAIRS:
        review = load_json(TRANSITION_DIR / review_name)
        question_set = load_json(TRANSITION_DIR / question_name)
        if review["questionSetId"] != question_set["questionSetId"]:
            raise ValueError(f"questionSetId mismatch: {review_name} <> {question_name}")
        qmap = {item["questionId"]: item for item in question_set["questions"]}
        pairing_audit.append({
            "batch": batch_label,
            "review": review_name,
            "questions": question_name,
            "question_set_id": review["questionSetId"],
            "responses": len(review["responses"]),
            "complete": len(review["responses"]) == review.get("answeredCount") == review.get("totalQuestionCount"),
        })
        for response in review["responses"]:
            qid = response["questionId"]
            if qid not in qmap:
                raise KeyError(f"Missing question {qid} in {question_name}")
            question = qmap[qid]
            questions[qid] = question
            responses[qid] = response
            source = question["source"]
            source_id = track_id(source)
            if source_id not in tags:
                raise KeyError(f"No formal Tag for source {source_id}")
            track_meta[source_id] = {
                "title": source.get("title", source_id),
                "artist": source.get("artist", ""),
                "filename": source.get("filename", ""),
            }
            current_source_tag = tags[source_id]
            if source.get("genre") and source["genre"] != current_source_tag["genre"]:
                tag_drift[(source_id, source.get("genre"), current_source_tag["genre"])] = track_meta[source_id]

            variants = {item["slot"]: item for item in response["variants"]}
            if set(variants) != {"left", "right"}:
                raise ValueError(f"Unexpected variants for {qid}")
            for slot in ("left", "right"):
                target = track_payload(question[slot])
                target_id = track_id(target)
                if target_id not in tags:
                    raise KeyError(f"No formal Tag for target {target_id}")
                track_meta[target_id] = {
                    "title": target.get("title", target_id),
                    "artist": target.get("artist", ""),
                    "filename": target.get("filename", ""),
                }
                current_target_tag = tags[target_id]
                if target.get("genre") and target["genre"] != current_target_tag["genre"]:
                    tag_drift[(target_id, target.get("genre"), current_target_tag["genre"])] = track_meta[target_id]
                variant = variants[slot]
                transition = variant.get("transition") or question[slot].get("transition") or {}
                repeat_of = question.get("repeatOf") or response.get("repeatOf")
                status = "repeat" if repeat_of else "primary"
                if qid in KNOWN_AUDIO_MISMATCH_QUESTIONS:
                    status = "audio_mismatch"
                row = {
                    "question_id": qid,
                    "repeat_of": repeat_of,
                    "status": status,
                    "batch": batch_label,
                    "family": family,
                    "family_label": FAMILY_LABELS[family],
                    "sample_kind": question.get("sampleKind") or response.get("sampleKind") or "",
                    "slot": slot,
                    "preference": response["preference"],
                    "selected": 0.5 if response["preference"] == "tie" else int(response["preference"] == slot),
                    "rating": int(variant["qualityRating"]),
                    "is_wow": bool(variant.get("isWow")),
                    "cost": float(transition.get("cost", 0)),
                    "risk": float(transition.get("risk", 0)),
                    "strategy": transition.get("strategy", ""),
                    "source_id": source_id,
                    "source_title": track_meta[source_id]["title"],
                    "source_artist": track_meta[source_id]["artist"],
                    "source_genre": current_source_tag["genre"],
                    "source_secondary": current_source_tag.get("secondary_genres") or [],
                    "source_instrumental": current_source_tag.get("instrumental"),
                    "source_language": current_source_tag.get("language"),
                    "target_id": target_id,
                    "target_title": track_meta[target_id]["title"],
                    "target_artist": track_meta[target_id]["artist"],
                    "target_genre": current_target_tag["genre"],
                    "target_secondary": current_target_tag.get("secondary_genres") or [],
                    "target_instrumental": current_target_tag.get("instrumental"),
                    "target_language": current_target_tag.get("language"),
                    "source_flow": resolve_flow(source_id, source),
                    "target_flow": resolve_flow(target_id, target),
                    "contrast_type": question.get("contrastType", ""),
                }
                row["bridge_class"] = bridge_class(current_source_tag, current_target_tag)
                rows.append(row)

    return {
        "rows": rows,
        "questions": questions,
        "responses": responses,
        "tags": tags,
        "flowset": flowset,
        "track_meta": track_meta,
        "pairing_audit": pairing_audit,
        "tag_drift": [
            {"track_id": key[0], "old": key[1], "current": key[2], **meta}
            for key, meta in sorted(tag_drift.items())
        ],
        "tag_updated_at": tag_doc.get("updated_at", ""),
    }


def aggregate(rows, key_func):
    buckets = defaultdict(list)
    for row in rows:
        buckets[key_func(row)].append(row)
    result = []
    for key, items in buckets.items():
        result.append({
            "key": key,
            "n": len(items),
            "questions": len({row["question_id"] for row in items}),
            "mean_rating": rounded(mean(row["rating"] for row in items), 3),
            "median_rating": rounded(median(row["rating"] for row in items), 2),
            "win_score": rounded(mean(row["selected"] for row in items), 3),
            "mean_cost": rounded(mean(row["cost"] for row in items), 3),
            "mean_risk": rounded(mean(row["risk"] for row in items), 3),
        })
    return result


def feature_dict(row, mode):
    values = {
        "num:cost": row["cost"],
        "num:risk": row["risk"],
        "num:cost_x_risk": row["cost"] * row["risk"],
        "cat:slot=" + row["slot"]: 1.0,
        "cat:batch=" + row["batch"]: 1.0,
        "cat:sample=" + row["sample_kind"]: 1.0,
    }
    if mode in {"tag", "source_flow", "target_flow", "both_flow"}:
        values.update({
            "cat:source_genre=" + row["source_genre"]: 1.0,
            "cat:target_genre=" + row["target_genre"]: 1.0,
            "cat:genre_pair=" + row["source_genre"] + " → " + row["target_genre"]: 1.0,
            "cat:bridge=" + row["bridge_class"]: 1.0,
            "num:same_main": float(row["source_genre"] == row["target_genre"]),
            "cat:source_instrumental=" + str(row["source_instrumental"]): 1.0,
            "cat:target_instrumental=" + str(row["target_instrumental"]): 1.0,
        })
    if mode in {"source_flow", "both_flow"}:
        flow = row["source_flow"]
        values.update({
            "cat:source_energy=" + flow["energy"]: 1.0,
            "num:source_noise": flow["noise"],
            "num:source_swing": flow["swing"],
            "num:source_burden": flow["burden"],
        })
        for slot in flow["timeslots"]:
            values["cat:source_time=" + slot] = 1.0
    if mode in {"target_flow", "both_flow"}:
        flow = row["target_flow"]
        values.update({
            "cat:target_energy=" + flow["energy"]: 1.0,
            "num:target_noise": flow["noise"],
            "num:target_swing": flow["swing"],
            "num:target_burden": flow["burden"],
        })
        for slot in flow["timeslots"]:
            values["cat:target_time=" + slot] = 1.0
    if mode == "both_flow":
        source = row["source_flow"]
        target = row["target_flow"]
        source_times = set(source["timeslots"])
        target_times = set(target["timeslots"])
        union_times = source_times | target_times
        values.update({
            "cat:energy_transition=" + source["energy"] + " → " + target["energy"]: 1.0,
            "num:same_energy": float(source["energy"] == target["energy"]),
            "num:noise_delta": target["noise"] - source["noise"],
            "num:swing_delta": target["swing"] - source["swing"],
            "num:burden_delta": target["burden"] - source["burden"],
            "num:noise_gap": abs(target["noise"] - source["noise"]),
            "num:swing_gap": abs(target["swing"] - source["swing"]),
            "num:burden_gap": abs(target["burden"] - source["burden"]),
            "num:time_overlap": len(source_times & target_times),
            "num:time_jaccard": len(source_times & target_times) / len(union_times) if union_times else 0.0,
        })
    return values


def assign_folds(rows, group_key, k=5):
    counts = Counter(row[group_key] for row in rows)
    groups = sorted(counts, key=lambda g: (-counts[g], stable_hash(g)))
    loads = [0] * min(k, max(2, len(groups)))
    mapping = {}
    for group in groups:
        fold = min(range(len(loads)), key=lambda i: (loads[i], i))
        mapping[group] = fold
        loads[fold] += counts[group]
    return [mapping[row[group_key]] for row in rows], len(loads)


def solve_linear(matrix, vector):
    n = len(vector)
    augmented = [list(matrix[i]) + [vector[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(augmented[row][col]))
        if abs(augmented[pivot][col]) < 1e-12:
            continue
        augmented[col], augmented[pivot] = augmented[pivot], augmented[col]
        scale = augmented[col][col]
        augmented[col] = [value / scale for value in augmented[col]]
        for row in range(n):
            if row == col:
                continue
            factor = augmented[row][col]
            if abs(factor) < 1e-14:
                continue
            augmented[row] = [
                current - factor * reference
                for current, reference in zip(augmented[row], augmented[col])
            ]
    return [augmented[i][-1] for i in range(n)]


def fit_ridge(train_rows, mode, lam, names=None):
    feature_rows = [feature_dict(row, mode) for row in train_rows]
    if names is None:
        names = sorted({name for values in feature_rows for name in values})
    means = []
    scales = []
    for name in names:
        column = [values.get(name, 0.0) for values in feature_rows]
        mu = mean(column)
        variance = mean((value - mu) ** 2 for value in column)
        means.append(mu)
        scales.append(math.sqrt(variance) if variance and variance > 1e-12 else 1.0)
    design = []
    for values in feature_rows:
        design.append([1.0] + [(values.get(name, 0.0) - mu) / scale for name, mu, scale in zip(names, means, scales)])
    y = [row["rating"] for row in train_rows]
    p = len(names) + 1
    xtx = [[0.0] * p for _ in range(p)]
    xty = [0.0] * p
    for xrow, target in zip(design, y):
        for i in range(p):
            xty[i] += xrow[i] * target
            for j in range(i, p):
                xtx[i][j] += xrow[i] * xrow[j]
    for i in range(p):
        for j in range(i):
            xtx[i][j] = xtx[j][i]
        if i:
            xtx[i][i] += lam
    coef = solve_linear(xtx, xty)
    return {"mode": mode, "names": names, "means": means, "scales": scales, "coef": coef}


def predict_ridge(model, rows):
    predictions = []
    for row in rows:
        values = feature_dict(row, model["mode"])
        xrow = [1.0] + [
            (values.get(name, 0.0) - mu) / scale
            for name, mu, scale in zip(model["names"], model["means"], model["scales"])
        ]
        value = sum(a * b for a, b in zip(model["coef"], xrow))
        predictions.append(min(5.0, max(1.0, value)))
    return predictions


def mae(actual, predicted):
    return mean(abs(a - p) for a, p in zip(actual, predicted))


def choose_lambda(rows, mode, group_key, names, lambdas=(0.3, 1.0, 3.0, 10.0, 30.0)):
    folds, fold_count = assign_folds(rows, group_key, k=4)
    scores = []
    for lam in lambdas:
        actual, predicted = [], []
        for fold in range(fold_count):
            train = [row for row, value in zip(rows, folds) if value != fold]
            test = [row for row, value in zip(rows, folds) if value == fold]
            if not train or not test:
                continue
            model = fit_ridge(train, mode, lam, names)
            actual.extend(row["rating"] for row in test)
            predicted.extend(predict_ridge(model, test))
        scores.append((mae(actual, predicted), lam))
    return min(scores)[1]


def cross_validate(rows, mode, group_key):
    names = sorted({name for row in rows for name in feature_dict(row, mode)})
    folds, fold_count = assign_folds(rows, group_key, k=5)
    predictions = [None] * len(rows)
    chosen = []
    for fold in range(fold_count):
        train_indices = [i for i, value in enumerate(folds) if value != fold]
        test_indices = [i for i, value in enumerate(folds) if value == fold]
        train = [rows[i] for i in train_indices]
        test = [rows[i] for i in test_indices]
        lam = choose_lambda(train, mode, group_key, names)
        chosen.append(lam)
        model = fit_ridge(train, mode, lam, names)
        for index, prediction in zip(test_indices, predict_ridge(model, test)):
            predictions[index] = prediction
    actual = [row["rating"] for row in rows]
    return {
        "n": len(rows),
        "groups": len({row[group_key] for row in rows}),
        "features": len(names),
        "mae": rounded(mae(actual, predictions), 4),
        "predictions": predictions,
        "lambda": rounded(median(chosen), 2),
        "folds": fold_count,
    }


def preference_accuracy(rows, predictions):
    by_question = defaultdict(list)
    for row, prediction in zip(rows, predictions):
        by_question[row["question_id"]].append((row, prediction))
    scores = []
    for items in by_question.values():
        if len(items) != 2 or items[0][0]["preference"] == "tie":
            continue
        predicted = max(items, key=lambda item: item[1])[0]["slot"]
        if abs(items[0][1] - items[1][1]) < 1e-10:
            scores.append(0.5)
        else:
            scores.append(float(predicted == items[0][0]["preference"]))
    return {"n": len(scores), "accuracy": rounded(mean(scores), 4)}


def model_comparison(rows, base_mode, extended_mode, group_key):
    baseline = cross_validate(rows, base_mode, group_key)
    extended = cross_validate(rows, extended_mode, group_key)
    result = {
        "n": len(rows),
        "groups": extended["groups"],
        "group_key": group_key,
        "baseline_mae": baseline["mae"],
        "extended_mae": extended["mae"],
        "improvement": rounded((baseline["mae"] - extended["mae"]) / baseline["mae"], 4),
        "baseline_features": baseline["features"],
        "extended_features": extended["features"],
        "folds": extended["folds"],
    }
    if group_key == "source_id" and {row["slot"] for row in rows} == {"left", "right"}:
        base_choice = preference_accuracy(rows, baseline["predictions"])
        ext_choice = preference_accuracy(rows, extended["predictions"])
        result["baseline_preference_accuracy"] = base_choice["accuracy"]
        result["extended_preference_accuracy"] = ext_choice["accuracy"]
        result["preference_n"] = ext_choice["n"]
    return result


def repeat_reliability(data):
    rows = data["rows"]
    by_q_slot = {(row["question_id"], row["slot"]): row for row in rows}
    usable_pairs = []
    excluded = []
    for qid, question in data["questions"].items():
        original = question.get("repeatOf")
        if not original:
            continue
        if qid in KNOWN_AUDIO_MISMATCH_QUESTIONS or original in KNOWN_AUDIO_MISMATCH_QUESTIONS:
            excluded.append({"question_id": qid, "reason": "已知音频身份问题"})
            continue
        repeat_rows = [by_q_slot.get((qid, slot)) for slot in ("left", "right")]
        original_rows = [by_q_slot.get((original, slot)) for slot in ("left", "right")]
        if any(row is None for row in repeat_rows + original_rows):
            excluded.append({"question_id": qid, "reason": "原始题不在本次纳入组别"})
            continue
        # Compare by stable target identity, not display side.
        original_by_target = {row["target_id"]: row for row in original_rows}
        if set(original_by_target) != {row["target_id"] for row in repeat_rows}:
            excluded.append({"question_id": qid, "reason": "候选曲目不一致"})
            continue
        rating_diffs = [
            abs(row["rating"] - original_by_target[row["target_id"]]["rating"])
            for row in repeat_rows
        ]
        def selected_target(question_rows):
            preference = question_rows[0]["preference"]
            if preference == "tie":
                return "tie"
            return next(row["target_id"] for row in question_rows if row["slot"] == preference)
        usable_pairs.append({
            "question_id": qid,
            "original": original,
            "rating_diffs": rating_diffs,
            "preference_match": selected_target(repeat_rows) == selected_target(original_rows),
        })
    diffs = [value for pair in usable_pairs for value in pair["rating_diffs"]]
    return {
        "presented_repeats": sum(bool(q.get("repeatOf")) for q in data["questions"].values()),
        "usable_repeat_pairs": len(usable_pairs),
        "excluded_repeat_pairs": len(excluded),
        "preference_agreement": rounded(mean(pair["preference_match"] for pair in usable_pairs), 3),
        "rating_exact": rounded(mean(value == 0 for value in diffs), 3),
        "rating_within_one": rounded(mean(value <= 1 for value in diffs), 3),
        "rating_mae": rounded(mean(diffs), 3),
        "excluded": excluded,
    }


def acoustic_summary(rows):
    by_question = defaultdict(list)
    for row in rows:
        by_question[row["question_id"]].append(row)
    cost_scores = []
    risk_scores = []
    ties = 0
    for items in by_question.values():
        if items[0]["preference"] == "tie":
            ties += 1
            continue
        selected = next(row for row in items if row["selected"] == 1)
        other = next(row for row in items if row["selected"] == 0)
        cost_scores.append(1 if selected["cost"] < other["cost"] else 0.5 if selected["cost"] == other["cost"] else 0)
        risk_scores.append(1 if selected["risk"] < other["risk"] else 0.5 if selected["risk"] == other["risk"] else 0)
    return {
        "non_tie_questions": len(cost_scores),
        "tie_questions": ties,
        "lower_cost_chosen": rounded(mean(cost_scores), 3),
        "lower_risk_chosen": rounded(mean(risk_scores), 3),
        "cost_rating_rho": rounded(spearman([r["cost"] for r in rows], [r["rating"] for r in rows]), 3),
        "risk_rating_rho": rounded(spearman([r["risk"] for r in rows], [r["rating"] for r in rows]), 3),
    }


def flowset_role_summary(rows, role):
    key = role + "_flow"
    subset = [row for row in rows if row[key]]
    dimensions = []
    for dimension in ("noise", "swing", "burden"):
        xs = [row[key][dimension] for row in subset]
        ys = [row["rating"] for row in subset]
        dimensions.append({
            "dimension": dimension,
            "rho": rounded(spearman(xs, ys), 3),
            "n": len(subset),
        })
    energy = aggregate(subset, lambda row: row[key]["energy"])
    for item in energy:
        item["label"] = item.pop("key")
    return {"n": len(subset), "tracks": len({row[role + "_id"] for row in subset}), "dimensions": dimensions, "energy": energy}


def two_sided_flowset(rows):
    subset = [row for row in rows if row["source_flow"] and row["target_flow"]]
    detail = []
    for row in subset:
        source = row["source_flow"]
        target = row["target_flow"]
        common_times = sorted(set(source["timeslots"]) & set(target["timeslots"]))
        detail.append({
            "question_id": row["question_id"],
            "source": row["source_title"],
            "target": row["target_title"],
            "rating": row["rating"],
            "selected": row["selected"],
            "genre_pair": row["source_genre"] + " → " + row["target_genre"],
            "energy": source["energy"] + " → " + target["energy"],
            "noise_delta": target["noise"] - source["noise"],
            "swing_delta": target["swing"] - source["swing"],
            "burden_delta": target["burden"] - source["burden"],
            "time_overlap": " / ".join(common_times) if common_times else "无",
        })
    correlations = []
    for dimension in ("noise", "swing", "burden"):
        signed = [item[dimension + "_delta"] for item in detail]
        absolute = [abs(value) for value in signed]
        ratings = [item["rating"] for item in detail]
        correlations.append({
            "dimension": dimension,
            "signed_rho": rounded(spearman(signed, ratings), 3),
            "absolute_rho": rounded(spearman(absolute, ratings), 3),
        })
    return {"n": len(subset), "questions": len({row["question_id"] for row in subset}), "correlations": correlations, "rows": detail}


def flowset_priority(rows, flowset, track_meta, limit=24):
    source_count = Counter(row["source_id"] for row in rows)
    target_count = Counter(row["target_id"] for row in rows)
    pair_gain = Counter()
    for row in rows:
        if row["source_id"] not in flowset and row["target_id"] in flowset:
            pair_gain[row["source_id"]] += 1
        if row["target_id"] not in flowset and row["source_id"] in flowset:
            pair_gain[row["target_id"]] += 1
    candidates = []
    for tid in (set(source_count) | set(target_count)) - set(flowset):
        total = source_count[tid] + target_count[tid]
        meta = track_meta.get(tid, {"title": tid, "artist": ""})
        candidates.append({
            "track_id": tid,
            "title": meta["title"],
            "artist": meta["artist"],
            "source_appearances": source_count[tid],
            "target_appearances": target_count[tid],
            "total_appearances": total,
            "two_sided_gain": pair_gain[tid],
            "priority_score": pair_gain[tid] * 10 + total,
        })
    return sorted(candidates, key=lambda item: (-item["priority_score"], -item["total_appearances"], item["title"]))[:limit]


def song_profiles(rows, role, minimum=4, limit=12):
    key = role + "_id"
    buckets = defaultdict(list)
    for row in rows:
        buckets[row[key]].append(row)
    prior = mean(row["rating"] for row in rows)
    result = []
    for tid, items in buckets.items():
        if len(items) < minimum:
            continue
        title_key = role + "_title"
        artist_key = role + "_artist"
        genre_key = role + "_genre"
        smoothed = (sum(row["rating"] for row in items) + prior * 5) / (len(items) + 5)
        result.append({
            "track_id": tid,
            "title": items[0][title_key],
            "artist": items[0][artist_key],
            "genre": items[0][genre_key],
            "n": len(items),
            "mean_rating": rounded(mean(row["rating"] for row in items), 3),
            "win_score": rounded(mean(row["selected"] for row in items), 3),
            "smoothed_rating": rounded(smoothed, 3),
        })
    ranked = sorted(result, key=lambda item: (-item["smoothed_rating"], -item["n"], item["title"]))
    return {"high": ranked[:limit], "low": list(reversed(ranked[-limit:])), "eligible": len(ranked), "minimum": minimum}


def build_analysis(data):
    all_rows = data["rows"]
    primary_before_audio = [row for row in all_rows if not row["repeat_of"]]
    primary = [row for row in all_rows if row["status"] == "primary"]
    repeats = [row for row in all_rows if row["status"] == "repeat"]
    invalid = [row for row in all_rows if row["status"] == "audio_mismatch"]
    unique_tracks = {row["source_id"] for row in primary} | {row["target_id"] for row in primary}
    genres = sorted({row["source_genre"] for row in primary} | {row["target_genre"] for row in primary})

    matrix = aggregate(primary, lambda row: (row["source_genre"], row["target_genre"]))
    for item in matrix:
        item["source"], item["target"] = item.pop("key")
    bridge = aggregate(primary, lambda row: row["bridge_class"])
    for item in bridge:
        item["code"] = item.pop("key")
        item["label"] = BRIDGE_LABELS[item["code"]]
    same_cross = aggregate(primary, lambda row: "same" if row["source_genre"] == row["target_genre"] else "cross")
    for item in same_cross:
        item["code"] = item.pop("key")
        item["label"] = "同主风格" if item["code"] == "same" else "跨主风格"

    matrix_map = {(item["source"], item["target"]): item for item in matrix}
    asymmetry = []
    for source in genres:
        for target in genres:
            if source >= target:
                continue
            forward = matrix_map.get((source, target))
            reverse = matrix_map.get((target, source))
            if forward and reverse and forward["n"] >= 3 and reverse["n"] >= 3:
                asymmetry.append({
                    "a": source,
                    "b": target,
                    "ab_n": forward["n"],
                    "ba_n": reverse["n"],
                    "ab_rating": forward["mean_rating"],
                    "ba_rating": reverse["mean_rating"],
                    "delta": rounded(forward["mean_rating"] - reverse["mean_rating"], 3),
                })
    asymmetry.sort(key=lambda item: -abs(item["delta"]))

    family_stats = aggregate(primary, lambda row: row["family"])
    for item in family_stats:
        item["family"] = item.pop("key")
        item["label"] = FAMILY_LABELS[item["family"]]
        qids = {row["question_id"] for row in primary if row["family"] == item["family"]}
        item["ties"] = sum(data["responses"][qid]["preference"] == "tie" for qid in qids)

    tag_model = model_comparison(primary, "baseline", "tag", "source_id")
    source_flow_rows = [row for row in primary if row["source_flow"]]
    target_flow_rows = [row for row in primary if row["target_flow"]]
    both_flow_rows = [row for row in primary if row["source_flow"] and row["target_flow"]]
    source_flow_model = model_comparison(source_flow_rows, "tag", "source_flow", "source_id") if len(source_flow_rows) >= 30 else None
    target_flow_model = model_comparison(target_flow_rows, "tag", "target_flow", "target_id") if len(target_flow_rows) >= 30 else None
    both_flow_model = model_comparison(both_flow_rows, "tag", "both_flow", "source_id") if len(both_flow_rows) >= 60 else None

    latest_flowset_date = FLOWSET_WAVES[-1][0]
    source_before_latest = [
        row for row in primary
        if row["source_flow"] and row["source_flow"].get("date") != latest_flowset_date
    ]
    target_before_latest = [
        row for row in primary
        if row["target_flow"] and row["target_flow"].get("date") != latest_flowset_date
    ]
    both_before_latest = [
        row for row in primary
        if row["source_flow"] and row["target_flow"]
        and row["source_flow"].get("date") != latest_flowset_date
        and row["target_flow"].get("date") != latest_flowset_date
    ]

    rating_counts = Counter(row["rating"] for row in primary)
    question_preferences = Counter(
        data["responses"][qid]["preference"]
        for qid in {row["question_id"] for row in primary}
    )
    wow_count = sum(row["is_wow"] for row in primary)

    invalid_by_question = defaultdict(list)
    for row in invalid:
        invalid_by_question[row["question_id"]].append(row)
    audio_exclusions = [
        {
            "question_id": qid,
            "repeat_of": items[0]["repeat_of"] or "",
            "source": items[0]["source_title"],
            "targets": " / ".join(row["target_title"] for row in items),
            "scope": "复测题" if items[0]["repeat_of"] else "主题",
        }
        for qid, items in sorted(invalid_by_question.items())
    ]

    priority = flowset_priority(primary, data["flowset"], data["track_meta"])
    two_sided = two_sided_flowset(primary)
    reliability = repeat_reliability(data)
    acoustic = acoustic_summary(primary)

    strongest = sorted([item for item in matrix if item["n"] >= 6], key=lambda item: (-item["mean_rating"], -item["n"]))
    weakest = sorted([item for item in matrix if item["n"] >= 6], key=lambda item: (item["mean_rating"], -item["n"]))

    return {
        "meta": {
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "tag_updated_at": data["tag_updated_at"],
            "included_review_files": len(PAIRS),
            "excluded_review_files": ["fifth-test", "eighth-test"],
            "presented_questions": len({row["question_id"] for row in all_rows}),
            "repeat_questions": len({row["question_id"] for row in all_rows if row["repeat_of"]}),
            "primary_questions_before_audio_qa": len({row["question_id"] for row in primary_before_audio}),
            "audio_mismatch_questions": len({row["question_id"] for row in invalid if not row["repeat_of"]}),
            "audio_mismatch_repeat_questions": len({row["question_id"] for row in invalid if row["repeat_of"]}),
            "analysis_questions": len({row["question_id"] for row in primary}),
            "candidate_rows": len(primary),
            "unique_tracks": len(unique_tracks),
            "source_tracks": len({row["source_id"] for row in primary}),
            "target_tracks": len({row["target_id"] for row in primary}),
            "formal_tag_rows": sum(row["source_id"] in data["tags"] and row["target_id"] in data["tags"] for row in primary),
            "source_flow_rows": len(source_flow_rows),
            "target_flow_rows": len(target_flow_rows),
            "two_sided_flow_rows": two_sided["n"],
            "two_sided_flow_questions": two_sided["questions"],
            "flowset_waves": len(FLOWSET_WAVES),
            "latest_flowset_date": latest_flowset_date,
            "source_flow_rows_before_latest": len(source_before_latest),
            "target_flow_rows_before_latest": len(target_before_latest),
            "two_sided_flow_rows_before_latest": len(both_before_latest),
            "source_flow_rows_latest_gain": len(source_flow_rows) - len(source_before_latest),
            "target_flow_rows_latest_gain": len(target_flow_rows) - len(target_before_latest),
            "two_sided_flow_rows_latest_gain": len(both_flow_rows) - len(both_before_latest),
            "wow_count": wow_count,
        },
        "genres": genres,
        "rating_distribution": [{"rating": rating, "n": rating_counts.get(rating, 0)} for rating in range(1, 6)],
        "preference_distribution": [
            {"label": "左边", "code": "left", "n": question_preferences.get("left", 0)},
            {"label": "右边", "code": "right", "n": question_preferences.get("right", 0)},
            {"label": "平局", "code": "tie", "n": question_preferences.get("tie", 0)},
        ],
        "pairing_audit": data["pairing_audit"],
        "audio_exclusions": audio_exclusions,
        "tag_drift": data["tag_drift"],
        "family_stats": family_stats,
        "matrix": matrix,
        "bridge": sorted(bridge, key=lambda item: -item["n"]),
        "same_cross": same_cross,
        "asymmetry": asymmetry,
        "strongest_pairs": strongest[:8],
        "weakest_pairs": weakest[:8],
        "models": {
            "tag": tag_model,
            "source_flow": source_flow_model,
            "target_flow": target_flow_model,
            "both_flow": both_flow_model,
        },
        "acoustic": acoustic,
        "reliability": reliability,
        "flowset": {
            "source": flowset_role_summary(primary, "source"),
            "target": flowset_role_summary(primary, "target"),
            "two_sided": two_sided,
            "priority": priority,
        },
        "songs": {
            "outgoing": song_profiles(primary, "source"),
            "incoming": song_profiles(primary, "target"),
        },
        "audit_rows": [
            {
                "question_id": row["question_id"],
                "batch": row["batch"],
                "slot": row["slot"],
                "source": row["source_title"],
                "target": row["target_title"],
                "source_genre": row["source_genre"],
                "target_genre": row["target_genre"],
                "bridge": BRIDGE_LABELS[row["bridge_class"]],
                "rating": row["rating"],
                "selected": row["selected"],
                "cost": rounded(row["cost"], 4),
                "risk": rounded(row["risk"], 4),
                "source_flow": bool(row["source_flow"]),
                "target_flow": bool(row["target_flow"]),
            }
            for row in primary
        ],
    }


def write_csvs(data, analysis):
    rows = data["rows"]
    fields = [
        "question_id", "repeat_of", "status", "batch", "family", "slot", "preference", "selected", "rating",
        "cost", "risk", "source_id", "source_title", "source_artist", "source_genre", "target_id", "target_title",
        "target_artist", "target_genre", "bridge_class", "source_flow_available", "target_flow_available",
    ]
    with OUT_ROWS.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            export = {field: row.get(field, "") for field in fields}
            export["source_flow_available"] = bool(row["source_flow"])
            export["target_flow_available"] = bool(row["target_flow"])
            writer.writerow(export)
    priority_fields = [
        "track_id", "title", "artist", "source_appearances", "target_appearances", "total_appearances", "two_sided_gain", "priority_score"
    ]
    with OUT_PRIORITY.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=priority_fields)
        writer.writeheader()
        writer.writerows(analysis["flowset"]["priority"])


HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tag × Flowset × 风格衔接偏好报告</title>
<style>
:root{--bg:#f3f5f8;--panel:#fff;--ink:#18222e;--sub:#677586;--line:#dce3eb;--accent:#315ee8;--accent-soft:#edf2ff;--good:#147a58;--good-soft:#e8f6ef;--warn:#a6620a;--warn-soft:#fff4df;--bad:#bf4055;--bad-soft:#fdeef1;--purple:#7956c8;--cyan:#2e8399;--shadow:0 7px 24px rgba(28,42,59,.06)}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.58}.wrap{max-width:1280px;margin:auto;padding:28px 22px 56px}.hero{display:flex;justify-content:space-between;align-items:flex-end;gap:20px;margin-bottom:18px}.hero h1{font-size:28px;line-height:1.25;margin:0 0 6px;font-weight:750}.hero p{margin:0;color:var(--sub);font-size:13px}.stamp{font-size:11.5px;color:var(--sub);text-align:right}.notice{border:1px solid #cdd7f8;background:#f6f8ff;color:#3d4c78;border-radius:12px;padding:11px 14px;font-size:12.5px;margin-bottom:14px}.notice.warn{border-color:#ecd5ad;background:#fff9ed;color:#77501b}.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:11px;margin-bottom:17px}.kpi,.finding{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px;box-shadow:var(--shadow)}.kpi b{font-size:24px;display:block;line-height:1.25}.kpi span{font-size:11.5px;color:var(--sub)}.findings{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:18px}.finding{box-shadow:none}.finding.primary{background:#f7f9ff;border-color:#bdcaf8}.finding.caution{background:var(--warn-soft);border-color:#ecd5ad}.finding h3{font-size:15px;margin:4px 0 5px}.finding p{font-size:12px;color:var(--sub);margin:0}.eyebrow{font-size:10.5px;color:var(--accent);font-weight:750;letter-spacing:.05em;text-transform:uppercase}.eyebrow.warn{color:var(--warn)}section{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px 22px;margin-bottom:17px;box-shadow:var(--shadow)}section h2{font-size:18px;margin:0 0 4px}section>.desc{font-size:12.5px;color:var(--sub);margin:0 0 17px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:20px}.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.chart h3,.subhead{font-size:13.5px;margin:0 0 9px}.chart-note,.footnote{font-size:11.5px;color:var(--sub);margin-top:8px}.tablewrap{overflow:auto;border:1px solid var(--line);border-radius:10px;max-height:520px}table{border-collapse:collapse;width:100%;font-size:11.5px}th,td{padding:8px 9px;border-bottom:1px solid var(--line);text-align:center;white-space:nowrap}th{position:sticky;top:0;background:#f8fafc;color:var(--sub);z-index:2;font-weight:650}td.left,th.left{text-align:left}.tag{display:inline-block;padding:2px 7px;border-radius:999px;background:var(--accent-soft);color:#3455b4;font-size:10.5px}.tag.good{background:var(--good-soft);color:var(--good)}.tag.warn{background:var(--warn-soft);color:var(--warn)}.tag.bad{background:var(--bad-soft);color:var(--bad)}.muted{color:var(--sub)}.bar-row{display:grid;grid-template-columns:minmax(100px,1.3fr) 3fr 52px;gap:9px;align-items:center;margin:8px 0;font-size:11.5px}.bar-track{height:11px;border-radius:999px;background:#edf0f4;overflow:hidden}.bar-fill{height:100%;border-radius:999px;background:var(--accent)}.bar-fill.good{background:var(--good)}.bar-fill.warn{background:#d98b2c}.bar-fill.purple{background:var(--purple)}.compare{display:grid;grid-template-columns:minmax(120px,1.2fr) 2.3fr 64px;align-items:center;gap:10px;margin:10px 0;font-size:11.5px}.compare-track{height:18px;background:#eef1f5;border-radius:4px;position:relative;overflow:hidden}.compare-track i{height:100%;display:block;background:var(--accent);opacity:.85}.model-card{border-left:3px solid var(--accent);padding:3px 0 3px 13px;margin-bottom:14px}.model-card.good{border-left-color:var(--good)}.model-card.warn{border-left-color:#d98b2c}.model-card h3{font-size:14px;margin:0 0 4px}.model-card p{font-size:12px;color:var(--sub);margin:0}.metric-line{display:flex;gap:15px;flex-wrap:wrap;margin-top:7px;font-size:11.5px}.metric-line b{font-size:14px}.matrix-controls{display:flex;gap:5px;margin:0 0 10px;flex-wrap:wrap}.matrix-controls button{border:1px solid var(--line);background:#fff;border-radius:8px;padding:6px 10px;font-size:11.5px;color:var(--sub);cursor:pointer}.matrix-controls button.active{background:var(--accent);border-color:var(--accent);color:#fff}.matrix-wrap{overflow:auto}.matrix{border-collapse:separate;border-spacing:3px;width:auto;min-width:850px}.matrix th{position:static;background:transparent;border:0;font-size:10.5px;max-width:120px;white-space:normal;line-height:1.25}.matrix td{border:0;border-radius:5px;min-width:95px;height:57px;padding:5px;position:relative;background:#f0f2f6}.matrix td.empty{background:#f6f7f9;color:#9da7b2}.matrix .v{font-size:15px;font-weight:750;display:block}.matrix .n{font-size:9.5px;color:inherit;opacity:.72}.legend-scale{display:flex;gap:8px;align-items:center;font-size:10.5px;color:var(--sub);margin-top:8px}.gradient{height:8px;width:150px;border-radius:999px;background:linear-gradient(90deg,#f3f5f8,#b9c9fa,#315ee8)}.corr{display:grid;grid-template-columns:78px 1fr 48px;align-items:center;gap:8px;margin:9px 0;font-size:11.5px}.corr-track{height:10px;background:linear-gradient(90deg,#f5dbe1 0 49.5%,#d9dee6 49.5% 50.5%,#dce8ff 50.5%);position:relative;border-radius:4px}.corr-track i{position:absolute;top:0;height:100%;background:var(--accent);border-radius:4px}.corr-track i.neg{background:var(--bad)}.funnel{display:flex;align-items:stretch;gap:7px;flex-wrap:wrap}.funnel-step{background:#f7f9fc;border:1px solid var(--line);padding:10px 12px;border-radius:9px;min-width:135px;flex:1}.funnel-step b{font-size:19px;display:block}.funnel-step span{font-size:10.5px;color:var(--sub)}.arrow{align-self:center;color:#9aa5b2}.tabs{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:12px}.tabs button{border:0;background:#edf1f6;color:#5d6b7a;border-radius:8px;padding:7px 11px;font-size:11.5px;cursor:pointer}.tabs button.active{background:var(--ink);color:#fff}.profile-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.searchbar{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin-bottom:10px}.searchbar input,.searchbar select{border:1px solid var(--line);background:#fff;border-radius:8px;padding:7px 9px;font:inherit;font-size:12px;color:var(--ink)}.searchbar input{min-width:260px;flex:1}.method{font-size:12px;color:var(--sub)}details{border-top:1px solid var(--line);padding:12px 0}details:first-child{border-top:0}summary{cursor:pointer;font-weight:650;font-size:13px}.footer{text-align:center;color:var(--sub);font-size:11.5px;margin-top:22px}.good-text{color:var(--good)}.warn-text{color:var(--warn)}.bad-text{color:var(--bad)}
.mini-kpis{grid-template-columns:repeat(4,1fr)}
@media(max-width:1000px){.kpis{grid-template-columns:repeat(3,1fr)}.mini-kpis{grid-template-columns:repeat(4,1fr)}.findings{grid-template-columns:1fr 1fr}.grid3{grid-template-columns:1fr}.profile-grid{grid-template-columns:1fr}}@media(max-width:760px){.grid2{grid-template-columns:1fr}.hero{align-items:flex-start;flex-direction:column}.stamp{text-align:left}.kpis,.mini-kpis{grid-template-columns:1fr 1fr}.findings{grid-template-columns:1fr}.wrap{padding:18px 12px 42px}section{padding:17px 14px}.arrow{display:none}}@media(max-width:450px){.kpis,.mini-kpis{grid-template-columns:1fr}.bar-row,.compare{grid-template-columns:90px 1fr 44px}.searchbar input{min-width:100%}}
</style>
</head>
<body>
<div class="wrap">
  <header class="hero"><div><h1>Tag × Flowset × 风格衔接偏好</h1><p>从“哪种风格分高”转向“什么样的 A → B 更适合你”</p></div><div class="stamp" id="stamp"></div></header>
  <div class="notice warn">风格衔接测试的第五、第八份 review 仍完全排除（与本次新增的 Flowset 第五波不是同一数据）；已知错音频题不进入主分析。本报告说明关联与预测增量，不把非随机测试数据解释为因果。</div>
  <div class="kpis" id="kpis"></div>
  <div class="findings" id="findings"></div>

  <section><h2>1. 数据口径与可用性</h2><p class="desc">先回答“什么数据真的进了分析”。Tag 分析使用当前正式 SongBase Tag；Flowset 使用每首歌最新一次个人打标。</p><div class="funnel" id="funnel"></div><div class="grid2" style="margin-top:18px"><div class="chart"><h3>质量评分分布</h3><div id="ratingDist"></div></div><div class="chart"><h3>左／右／平局</h3><div id="preferenceDist"></div></div></div><h3 class="subhead" style="margin-top:18px">各类测试样本</h3><div class="tablewrap" id="familyTable"></div></section>

  <section><h2>2. Tag 与有方向的衔接</h2><p class="desc">行是前一首，列是后一首。点击指标可切换平均评分、被选中率和样本量；每个格子都保留 n，避免小样本高分被当成稳定规律。</p><div class="matrix-controls" id="matrixControls"><button class="active" data-metric="mean_rating">平均评分</button><button data-metric="win_score">被选中率</button><button data-metric="n">样本量</button></div><div class="matrix-wrap" id="genreMatrix"></div><div class="legend-scale"><span>低</span><i class="gradient"></i><span>高</span><span>· 颜色只表示当前指标，不表示统计显著性</span></div><div class="grid2" style="margin-top:20px"><div><h3 class="subhead">Tag 重叠／桥接关系</h3><div id="bridgeTable" class="tablewrap"></div></div><div><h3 class="subhead">主风格方向不对称</h3><div id="asymmetryTable" class="tablewrap"></div><div class="footnote">这里比较的是风格层面 A→B 和 B→A，不是同两首歌倒放顺序的因果实验。</div></div></div></section>

  <section><h2>3. Tag 是否带来额外判断力</h2><p class="desc">用按前曲分组的 5 折交叉验证，确保同一前曲不同时出现在训练和验证中。基准只看 cost、risk、批次和位置；扩展模型再加入前后 Tag 及桥接关系。</p><div id="tagModel"></div><div class="grid2" style="margin-top:17px"><div><h3 class="subhead">声学基线与人的选择</h3><div id="acousticSummary"></div></div><div><h3 class="subhead">平均分高／低的风格方向</h3><div class="tabs" id="pairTabs"><button class="active" data-view="high">高分</button><button data-view="low">低分</button></div><div id="pairRank"></div></div></div></section>

  <section><h2>4. Flowset：第五波补标后的衔接分析</h2><p class="desc">先分别观察前曲和后曲的听感属性，再在两端都有 Flowset 的候选上检验“听感变化量”是否带来额外预测信息。结论仍是关联，不解释为因果。</p><div class="grid2"><div><h3 class="subhead">前曲 Flowset 与后接评分</h3><div id="sourceFlow"></div></div><div><h3 class="subhead">后曲 Flowset 与前接评分</h3><div id="targetFlow"></div></div></div><hr style="border:0;border-top:1px solid var(--line);margin:19px 0"><div id="flowModels"></div><h3 class="subhead" style="margin-top:19px">两端均有 Flowset：有方向的听感变化</h3><div id="twoSidedFlow" class="tablewrap"></div><div id="twoSidedNote" class="footnote"></div></section>

  <section><h2>5. 哪些歌曲在“承上”和“启下”上更稳</h2><p class="desc">歌曲层面使用向总体均值收缩的分数，并且只显示至少出现 4 次的曲目。这是定位歌单角色的描述性线索，不是歌曲的永久属性。</p><div class="tabs" id="songTabs"><button class="active" data-view="outgoing">作为前曲：启下</button><button data-view="incoming">作为后曲：承上</button></div><div class="profile-grid"><div><h3 class="subhead">较高</h3><div id="songHigh" class="tablewrap"></div></div><div><h3 class="subhead">较低</h3><div id="songLow" class="tablewrap"></div></div></div></section>

  <section><h2>6. 复测稳定性</h2><p class="desc">复测题只用于评估你的打分和偏好是否稳定，不再当成新的独立证据。风格衔接测试的第五、第八份 review 仍然完全不使用。</p><div id="reliability"></div></section>

  <section><h2>7. 下一轮 Flowset 补标的最高价值清单</h2><p class="desc">优先级同时考虑曲目在测试中的出现次数，以及补标后能立即新增多少条“前后两端都有 Flowset”的衔接。</p><div id="priorityTable" class="tablewrap"></div></section>

  <section><h2>8. 数据审计</h2><p class="desc">主分析的每一条候选衔接都可以在这里回查。</p><div class="searchbar"><input id="auditSearch" type="search" placeholder="搜索题号、歌名或风格"><select id="auditBatch"><option value="">全部批次</option></select><span class="muted" id="auditCount"></span></div><div id="auditTable" class="tablewrap"></div><details style="margin-top:15px"><summary>题目文件与 review 配对</summary><div id="pairingTable" class="tablewrap" style="margin-top:10px"></div></details><details><summary>已排除的错音频题</summary><div id="audioExclusions" class="tablewrap" style="margin-top:10px"></div></details><details><summary>历史题目 Tag 与当前正式 Tag 的变化</summary><div id="tagDrift" class="tablewrap" style="margin-top:10px"></div></details></section>

  <section><h2>9. 方法与解读边界</h2><div class="method"><details open><summary>分析单位</summary><p>主分析单位是有方向的候选衔接 A→B。同一题的左右候选共享同一前曲，因此不完全独立。模型交叉验证按歌曲分组，而不是随机拆行。</p></details><details><summary>模型口径</summary><p>1–5 分暂按近似等距数值用嵌套交叉验证的岭回归比较 MAE。这个模型用于比较新特征是否增加预测信息，不是把系数解释成因果效应。</p></details><details><summary>Flowset 局限</summary><p>第五波让两端均有 Flowset 的覆盖足以进入分组交叉验证，但样本来自定向补标、曲目会重复出现，也不是随机实验。因此变化量和模型增量可作为当前题库内的关联证据，不能直接外推为稳定因果规律；报告仍不填补、不用 Tag 推测个人 Flowset。</p></details><details><summary>样本外推</summary><p>这些题目是按风格覆盖、矩阵补全和校准目标有意选的，并非从全曲库随机抽样。结论首先有效于已测风格空间和你当时的主观判断。</p></details></div></section>
  <div class="footer">完全离线报告 · 数据和脚本均已内嵌 · 不依赖外部 CDN 或本地 fetch</div>
</div>
<script>
const DATA=__REPORT_DATA__;
const $=id=>document.getElementById(id);
const pct=v=>v==null?'—':`${Math.round(v*100)}%`;
const num=(v,d=2)=>v==null?'—':Number(v).toFixed(d);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const table=(headers,rows)=>`<table><thead><tr>${headers.map(h=>`<th class="${h.left?'left':''}">${h.label}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${headers.map(h=>`<td class="${h.left?'left':''}">${h.render?h.render(row):esc(row[h.key])}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
const bars=(rows,valueKey,labelKey,maxValue,color='')=>rows.map(row=>`<div class="bar-row"><span>${esc(row[labelKey])}</span><div class="bar-track"><div class="bar-fill ${color}" style="width:${Math.max(1,row[valueKey]/maxValue*100)}%"></div></div><b>${esc(row[valueKey])}</b></div>`).join('');

function renderHeader(){
  const m=DATA.meta;
  $('stamp').innerHTML=`生成于 ${esc(m.generated_at.replace('T',' '))}<br>正式 Tag 更新：${esc(m.tag_updated_at||'未记录')}`;
  const kpis=[['有效问题',m.analysis_questions],['候选衔接',m.candidate_rows],['正式 Tag 覆盖',pct(m.formal_tag_rows/m.candidate_rows)],['前后均有 Flowset',m.two_sided_flow_rows],['唯一曲目',m.unique_tracks]];
  $('kpis').innerHTML=kpis.map(([label,value])=>`<div class="kpi"><b>${value}</b><span>${label}</span></div>`).join('');
  const tm=DATA.models.tag, sf=DATA.models.source_flow, tf=DATA.models.target_flow, bf=DATA.models.both_flow;
  const tagGain=tm.improvement;
  const flowText=(sf&&tf)?`前曲 ${Math.round(sf.improvement*100)}%／后曲 ${Math.round(tf.improvement*100)}%${bf?`／双端 ${Math.round(bf.improvement*100)}%`:''}`:'样本不足';
  const flowImproved=[sf,tf,bf].filter(Boolean).some(x=>x.improvement>.02);
  const flowConclusion=flowImproved?'至少一个 Flowset 口径出现了正向样本外增量，仍需复测确认。':'三个 Flowset 口径都没有降低样本外 MAE，当前不应直接把这些维度写成衔接加权规则。';
  const tagConclusion=tagGain>0.02?`Tag 使评分 MAE 改善 ${Math.round(tagGain*100)}%，存在额外预测信息。`:`Tag 对未见前曲的 MAE 改善仅 ${Math.round(tagGain*100)}%，当前更适合解释而非单独预测。`;
  const same=DATA.bridge.find(x=>x.code==='same_main'), none=DATA.bridge.find(x=>x.code==='no_overlap'), asym=DATA.asymmetry[0];
  $('findings').innerHTML=`
    <div class="finding primary"><span class="eyebrow">数据可用性</span><h3>Tag 主分析可以完整开展</h3><p>${m.candidate_rows} 条有效候选的前后曲都有当前正式 Tag，无需候选标签或模糊匹配。</p></div>
    <div class="finding"><span class="eyebrow">增量信息</span><h3>Tag 必须和声学基线分开看</h3><p>${tagConclusion}</p></div>
    <div class="finding"><span class="eyebrow">直接模式</span><h3>同主风格明显强于无 Tag 重叠</h3><p>同主风格均分 ${num(same.mean_rating)}、被选中 ${pct(same.win_score)}；无重叠为 ${num(none.mean_rating)} 和 ${pct(none.win_score)}。</p></div>
    <div class="finding"><span class="eyebrow">方向性线索</span><h3>${esc(asym.a)} ⇄ ${esc(asym.b)} 不对称</h3><p>A→B 均分 ${num(asym.ab_rating)} (n=${asym.ab_n})，B→A ${num(asym.ba_rating)} (n=${asym.ba_n})；样本小，需定向复验。</p></div>
    <div class="finding"><span class="eyebrow">声学边界</span><h3>低 cost／低 risk 不等于你会选</h3><p>非平局题中，更低 cost 只被选 ${pct(DATA.acoustic.lower_cost_chosen)}，更低 risk 只被选 ${pct(DATA.acoustic.lower_risk_chosen)}。</p></div>
    <div class="finding primary"><span class="eyebrow">第五波增量</span><h3>覆盖够检验，预测增量暂未成立</h3><p>双端完整 ${m.two_sided_flow_rows_before_latest} → ${m.two_sided_flow_rows} 条（+${m.two_sided_flow_rows_latest_gain}）；MAE 增量：${flowText}。${flowConclusion}</p></div>`;
}

function renderCoverage(){
  const m=DATA.meta;
  const steps=[['8 份 review',m.presented_questions+'题'],['去掉复测',m.primary_questions_before_audio_qa+'题'],['音频 QA',m.analysis_questions+'题'],['候选衔接',m.candidate_rows+'条'],['两端 Flowset',m.two_sided_flow_rows+'条']];
  $('funnel').innerHTML=steps.map((s,i)=>`${i?'<span class="arrow">→</span>':''}<div class="funnel-step"><b>${esc(s[1])}</b><span>${esc(s[0])}</span></div>`).join('');
  $('ratingDist').innerHTML=bars(DATA.rating_distribution,'n','rating',Math.max(...DATA.rating_distribution.map(x=>x.n)));
  [...$('ratingDist').querySelectorAll('.bar-row span')].forEach((node,i)=>node.textContent=`${DATA.rating_distribution[i].rating} 分`);
  $('preferenceDist').innerHTML=bars(DATA.preference_distribution,'n','label',Math.max(...DATA.preference_distribution.map(x=>x.n)),'purple');
  $('familyTable').innerHTML=table([
    {label:'类型',key:'label',left:true},{label:'候选',key:'n'},{label:'问题',key:'questions'},{label:'平均分',key:'mean_rating',render:r=>num(r.mean_rating)},{label:'平局题',key:'ties'},{label:'平均 cost',key:'mean_cost',render:r=>num(r.mean_cost,3)},{label:'平均 risk',key:'mean_risk',render:r=>num(r.mean_risk,3)}
  ],DATA.family_stats);
}

let matrixMetric='mean_rating';
function renderMatrix(){
  const genres=DATA.genres, lookup=new Map(DATA.matrix.map(x=>[`${x.source}\u0000${x.target}`,x]));
  const ranges={mean_rating:[1,5],win_score:[0,1],n:[0,Math.max(...DATA.matrix.map(x=>x.n))]};
  const [lo,hi]=ranges[matrixMetric];
  let out='<table class="matrix"><thead><tr><th>前曲 ↓／后曲 →</th>'+genres.map(g=>`<th>${esc(g)}</th>`).join('')+'</tr></thead><tbody>';
  genres.forEach(source=>{out+=`<tr><th>${esc(source)}</th>`;genres.forEach(target=>{const d=lookup.get(`${source}\u0000${target}`);if(!d){out+='<td class="empty">—</td>';return;}const v=d[matrixMetric], strength=Math.max(0,Math.min(1,(v-lo)/(hi-lo||1))), alpha=.08+strength*.78;const display=matrixMetric==='mean_rating'?num(v):matrixMetric==='win_score'?pct(v):v;out+=`<td style="background:rgba(49,94,232,${alpha})${strength>.58?';color:#fff':''}" data-tip="${esc(source)} → ${esc(target)} · 均分 ${num(d.mean_rating)} · 被选中 ${pct(d.win_score)} · n=${d.n}"><span class="v">${display}</span><span class="n">n=${d.n}</span></td>`;});out+='</tr>';});out+='</tbody></table>';$('genreMatrix').innerHTML=out;
  $('genreMatrix').querySelectorAll('[data-tip]').forEach(td=>td.addEventListener('click',()=>alert(td.dataset.tip)));
}

function renderTag(){
  renderMatrix();
  $('matrixControls').addEventListener('click',event=>{const button=event.target.closest('button[data-metric]');if(!button)return;matrixMetric=button.dataset.metric;$('matrixControls').querySelectorAll('button').forEach(b=>b.classList.toggle('active',b===button));renderMatrix();});
  $('bridgeTable').innerHTML=table([{label:'关系',key:'label',left:true},{label:'n',key:'n'},{label:'均分',key:'mean_rating',render:r=>num(r.mean_rating)},{label:'被选中',key:'win_score',render:r=>pct(r.win_score)},{label:'均 cost',key:'mean_cost',render:r=>num(r.mean_cost,3)}],DATA.bridge);
  $('asymmetryTable').innerHTML=table([{label:'风格对',key:'a',left:true,render:r=>`${esc(r.a)} ⇄ ${esc(r.b)}`},{label:'A→B',key:'ab_rating',render:r=>`${num(r.ab_rating)} (n=${r.ab_n})`},{label:'B→A',key:'ba_rating',render:r=>`${num(r.ba_rating)} (n=${r.ba_n})`},{label:'方向差',key:'delta',render:r=>`<b class="${Math.abs(r.delta)>=.5?'warn-text':''}">${r.delta>0?'+':''}${num(r.delta)}</b>`}],DATA.asymmetry.slice(0,14));
}

function modelCard(title,model,kind){
  const improved=model.improvement>0;const cls=model.improvement>.02?'good':model.improvement<0?'warn':'';const delta=`${model.improvement>=0?'+':''}${Math.round(model.improvement*100)}%`;
  let preference='';if(model.extended_preference_accuracy!=null)preference=`<span>偏好方向命中 <b>${pct(model.baseline_preference_accuracy)} → ${pct(model.extended_preference_accuracy)}</b> (n=${model.preference_n})</span>`;
  return `<div class="model-card ${cls}"><h3>${esc(title)}</h3><p>${esc(kind)}，n=${model.n}，${model.groups} 个分组单位，${model.folds} 折嵌套交叉验证。</p><div class="metric-line"><span>MAE <b>${num(model.baseline_mae,3)} → ${num(model.extended_mae,3)}</b></span><span>相对改善 <b class="${improved?'good-text':'warn-text'}">${delta}</b></span>${preference}</div></div>`;
}

function renderModels(){
  const m=DATA.models.tag;
  $('tagModel').innerHTML=modelCard('Tag 相对声学基线的增量',m,'基准为 cost / risk / 批次 / 位置；扩展后加前后主风格、方向组合、副风格桥接及器乐属性');
  const a=DATA.acoustic;
  $('acousticSummary').innerHTML=`<div class="compare"><span>更低 cost 被选</span><div class="compare-track"><i style="width:${a.lower_cost_chosen*100}%"></i></div><b>${pct(a.lower_cost_chosen)}</b></div><div class="compare"><span>更低 risk 被选</span><div class="compare-track"><i style="width:${a.lower_risk_chosen*100}%"></i></div><b>${pct(a.lower_risk_chosen)}</b></div><p class="footnote">cost 与评分 Spearman ρ=${num(a.cost_rating_rho,3)}；risk 与评分 ρ=${num(a.risk_rating_rho,3)}。共 ${a.non_tie_questions} 道非平局题，${a.tie_questions} 道平局题。</p>`;
  const renderPairs=view=>{const rows=view==='high'?DATA.strongest_pairs:DATA.weakest_pairs;$('pairRank').innerHTML=table([{label:'方向',key:'source',left:true,render:r=>`${esc(r.source)} → ${esc(r.target)}`},{label:'n',key:'n'},{label:'均分',key:'mean_rating',render:r=>num(r.mean_rating)},{label:'被选中',key:'win_score',render:r=>pct(r.win_score)},{label:'cost',key:'mean_cost',render:r=>num(r.mean_cost,3)}],rows)};
  renderPairs('high');$('pairTabs').addEventListener('click',e=>{const b=e.target.closest('button[data-view]');if(!b)return;$('pairTabs').querySelectorAll('button').forEach(x=>x.classList.toggle('active',x===b));renderPairs(b.dataset.view)});
}

function corrChart(summary){
  const dimensions=summary.dimensions.map(d=>{const v=d.rho??0;const width=Math.abs(v)*50;const left=v>=0?50:50-width;return `<div class="corr"><span>${({noise:'噪音',swing:'摇摆',burden:'负担'})[d.dimension]}</span><div class="corr-track"><i class="${v<0?'neg':''}" style="left:${left}%;width:${width}%"></i></div><b>${num(v,2)}</b></div>`}).join('');
  const energy=summary.energy.slice().sort((a,b)=>b.mean_rating-a.mean_rating).map(row=>`<div class="bar-row"><span>${esc(row.label)}</span><div class="bar-track"><div class="bar-fill good" style="width:${row.mean_rating/5*100}%"></div></div><b>${num(row.mean_rating,1)}</b></div>`).join('');
  return dimensions+`<div class="footnote">Spearman ρ；n=${summary.n} 条候选，${summary.tracks} 首有 Flowset 的歌。</div><h4 class="subhead" style="margin-top:14px">按能量状态的平均衔接分</h4>`+energy;
}

function renderFlowset(){
  $('sourceFlow').innerHTML=corrChart(DATA.flowset.source);$('targetFlow').innerHTML=corrChart(DATA.flowset.target);
  const sf=DATA.models.source_flow,tf=DATA.models.target_flow,bf=DATA.models.both_flow;
  $('flowModels').innerHTML=(sf?modelCard('在已有 Tag 基础上加前曲 Flowset',sf,'按前曲分组验证'):'')+(tf?modelCard('在已有 Tag 基础上加后曲 Flowset',tf,'按后曲分组验证'):'')+(bf?modelCard('在已有 Tag 基础上加前后两端 Flowset 与变化量',bf,'按前曲分组验证；含能量转移、数值差值与绝对差、时段重合'):'');
  const rows=DATA.flowset.two_sided.rows;
  $('twoSidedFlow').innerHTML=table([{label:'前曲',key:'source',left:true},{label:'后曲',key:'target',left:true},{label:'方向',key:'genre_pair',left:true},{label:'分',key:'rating'},{label:'能量',key:'energy'},{label:'Δ噪音',key:'noise_delta',render:r=>(r.noise_delta>0?'+':'')+r.noise_delta},{label:'Δ摇摆',key:'swing_delta',render:r=>(r.swing_delta>0?'+':'')+r.swing_delta},{label:'Δ负担',key:'burden_delta',render:r=>(r.burden_delta>0?'+':'')+r.burden_delta},{label:'时段交集',key:'time_overlap'}],rows);
  const cs=DATA.flowset.two_sided.correlations.map(x=>`${({noise:'噪音',swing:'摇摆',burden:'负担'})[x.dimension]}：有向Δ ρ=${num(x.signed_rho,2)}，绝对差 ρ=${num(x.absolute_rho,2)}`).join('；');
  $('twoSidedNote').textContent=`共 ${DATA.flowset.two_sided.n} 条候选、${DATA.flowset.two_sided.questions} 道问题。相关系数是描述性关联，并与上方分组交叉验证结合解读：${cs}。`;
}

function renderSongs(){
  const draw=view=>{const d=DATA.songs[view];const headers=[{label:'歌曲',key:'title',left:true,render:r=>`<b>${esc(r.title)}</b><br><span class="muted">${esc(r.artist)}</span>`},{label:'风格',key:'genre',left:true},{label:'n',key:'n'},{label:'原均分',key:'mean_rating',render:r=>num(r.mean_rating)},{label:'收缩分',key:'smoothed_rating',render:r=>num(r.smoothed_rating)},{label:'被选中',key:'win_score',render:r=>pct(r.win_score)}];$('songHigh').innerHTML=table(headers,d.high);$('songLow').innerHTML=table(headers,d.low)};
  draw('outgoing');$('songTabs').addEventListener('click',e=>{const b=e.target.closest('button[data-view]');if(!b)return;$('songTabs').querySelectorAll('button').forEach(x=>x.classList.toggle('active',x===b));draw(b.dataset.view)});
}

function renderReliability(){const r=DATA.reliability;$('reliability').innerHTML=`<div class="kpis mini-kpis" style="margin-bottom:10px"><div class="kpi"><b>${r.usable_repeat_pairs}</b><span>可比复测对</span></div><div class="kpi"><b>${pct(r.preference_agreement)}</b><span>偏好对象一致</span></div><div class="kpi"><b>${num(r.rating_mae,2)}</b><span>复测评分 MAE</span></div><div class="kpi"><b>${pct(r.rating_within_one)}</b><span>评分差不超过 1</span></div></div><p class="footnote">原始共 ${r.presented_repeats} 道复测题；${r.excluded_repeat_pairs} 道因原始题在被排除的风格衔接第五份 review，或涉及已知错音频，没有用于稳定性计算。评分完全相同率 ${pct(r.rating_exact)}。</p>`;}

function renderPriority(){$('priorityTable').innerHTML=table([{label:'顺位',key:'rank',render:(r,i)=>''},{label:'歌曲',key:'title',left:true,render:r=>`<b>${esc(r.title)}</b><br><span class="muted">${esc(r.artist)}</span>`},{label:'作为前曲',key:'source_appearances'},{label:'作为后曲',key:'target_appearances'},{label:'总出现',key:'total_appearances'},{label:'立即补全两端',key:'two_sided_gain',render:r=>`<span class="tag ${r.two_sided_gain?'good':''}">${r.two_sided_gain} 条</span>`}],DATA.flowset.priority.map((x,i)=>({...x,rank:i+1})));const cells=$('priorityTable').querySelectorAll('tbody tr');cells.forEach((tr,i)=>tr.cells[0].textContent=i+1);}

function renderAudit(){
  const batches=[...new Set(DATA.audit_rows.map(x=>x.batch))];$('auditBatch').innerHTML+=batches.map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join('');
  const draw=()=>{const term=$('auditSearch').value.trim().toLowerCase(),batch=$('auditBatch').value;const rows=DATA.audit_rows.filter(r=>(!batch||r.batch===batch)&&(!term||Object.values(r).some(v=>String(v).toLowerCase().includes(term))));$('auditCount').textContent=`${rows.length} / ${DATA.audit_rows.length} 条`;$('auditTable').innerHTML=table([{label:'题号',key:'question_id',left:true},{label:'批次',key:'batch'},{label:'前曲',key:'source',left:true},{label:'后曲',key:'target',left:true},{label:'Tag 方向',key:'source_genre',left:true,render:r=>`${esc(r.source_genre)} → ${esc(r.target_genre)}`},{label:'桥接',key:'bridge'},{label:'分',key:'rating'},{label:'选中',key:'selected',render:r=>r.selected===1?'<span class="tag good">是</span>':r.selected===.5?'<span class="tag">平局</span>':'否'},{label:'cost',key:'cost'},{label:'risk',key:'risk'},{label:'F前/F后',key:'source_flow',render:r=>`${r.source_flow?'✓':'—'} / ${r.target_flow?'✓':'—'}`}],rows)};$('auditSearch').addEventListener('input',draw);$('auditBatch').addEventListener('change',draw);draw();
  $('pairingTable').innerHTML=table([{label:'批次',key:'batch',left:true},{label:'review',key:'review',left:true},{label:'题目',key:'questions',left:true},{label:'questionSetId',key:'question_set_id',left:true},{label:'作答',key:'responses'},{label:'完整',key:'complete',render:r=>r.complete?'<span class="tag good">是</span>':'<span class="tag bad">否</span>'}],DATA.pairing_audit);
  $('audioExclusions').innerHTML=table([{label:'范围',key:'scope'},{label:'题号',key:'question_id',left:true},{label:'原始题',key:'repeat_of',left:true,render:r=>esc(r.repeat_of||'—')},{label:'前曲',key:'source',left:true},{label:'候选后曲',key:'targets',left:true}],DATA.audio_exclusions);
  $('tagDrift').innerHTML=DATA.tag_drift.length?table([{label:'歌曲',key:'title',left:true,render:r=>`<b>${esc(r.title)}</b><br><span class="muted">${esc(r.artist)}</span>`},{label:'题目当时',key:'old',left:true},{label:'当前正式',key:'current',left:true}],DATA.tag_drift):'<p class="footnote" style="padding:0 10px">题目内嵌主风格与当前正式 Tag 无变化。</p>';
}

renderHeader();renderCoverage();renderTag();renderModels();renderFlowset();renderSongs();renderReliability();renderPriority();renderAudit();
</script>
</body></html>'''


def build_report():
    data = load_rows()
    analysis = build_analysis(data)
    write_csvs(data, analysis)
    payload = json.dumps(analysis, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    document = HTML_TEMPLATE.replace("__REPORT_DATA__", payload)
    OUT_HTML.write_text(document, encoding="utf-8")
    print(json.dumps({
        "report": str(OUT_HTML),
        "rows_csv": str(OUT_ROWS),
        "priority_csv": str(OUT_PRIORITY),
        "bytes": OUT_HTML.stat().st_size,
        "meta": analysis["meta"],
        "models": analysis["models"],
        "reliability": analysis["reliability"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build_report()
