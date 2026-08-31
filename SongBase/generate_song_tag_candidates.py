#!/usr/bin/env python3
"""Sample untagged SongBase tracks and create review-only genre tag candidates.

Candidates never modify song_tags.json. The current first-pass source is Last.fm:
track tags, then album tags, then artist tags. Raw evidence is retained so that
mapping rules can be inspected before a candidate is approved.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE = Path(__file__).resolve().parent
LIBRARY_PATH = BASE / "song_base_by_artist.json"
TAGS_PATH = BASE / "song_tags.json"
MAPPING_PATH = BASE / "song_tag_mapping.json"
CANDIDATES_PATH = BASE / "song_tag_candidates.json"
REPORT_PATH = BASE / "song_tag_candidate_report.md"
LEGACY_LASTFM_CONFIG = BASE.parent / "cafe-playlist" / "lastfm_genre_tagger.py"
QQ_MID_RE = re.compile(r"/songDetail/([A-Za-z0-9]+)")
LEGACY_KEY_RE = re.compile(r'^API_KEY\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
LASTFM_URL = "https://ws.audioscrobbler.com/2.0/"
SECONDARY_MIN_SCORE = 2.0
SECONDARY_MIN_RELATIVE_SCORE = 0.45
SECONDARY_MAX_COUNT = 2

# SongBase 内部已经确认的常用艺人别名。它只影响外部平台查询，
# 不会改写曲库中的展示艺人名。
ARTIST_ALIASES = {
    "坂本龙一": "Ryuichi Sakamoto",
    "中村遥": "haruka nakamura",
    "吉村弘": "Hiroshi Yoshimura",
    "青葉市子": "Ichiko Aoba",
    "小濑村晶": "Akira Kosemura",
    "高木正胜": "Masakatsu Takagi",
    "北村英治": "Eiji Kitamura",
}

def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def lookup_artist(name: str) -> str:
    return ARTIST_ALIASES.get(name, name)


def track_id(song: dict) -> str:
    match = QQ_MID_RE.search(song.get("qq_music", ""))
    if not match:
        raise ValueError(f"缺少 QQ Music MID：{song.get('title', '未知歌曲')}")
    return f"qq:{match.group(1)}"


def get_api_key() -> str:
    key = os.environ.get("LASTFM_API_KEY", "").strip()
    if key:
        return key

    # Reuse the already configured project key without duplicating it into a
    # second source file. New installations should prefer LASTFM_API_KEY.
    if LEGACY_LASTFM_CONFIG.exists():
        match = LEGACY_KEY_RE.search(LEGACY_LASTFM_CONFIG.read_text(encoding="utf-8"))
        if match:
            return match.group(1)
    raise RuntimeError("缺少 Last.fm API key。请设置 LASTFM_API_KEY 后重试。")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_mapping(taxonomy: dict) -> dict:
    mapping = load_json(MAPPING_PATH)
    if mapping.get("schema_version") != "songbase.tag-mapping/v1":
        raise ValueError("song_tag_mapping.json 的 schema_version 无效")
    target_genres = set(taxonomy.get("genres", []))
    if set(mapping.get("genres", [])) != target_genres:
        raise ValueError("song_tag_mapping.json 与 song_tags.json 的目标风格清单不一致")
    for rule_type, condition_key in (("direct_rules", "match_any"), ("combination_rules", "match_all")):
        for rule in mapping.get(rule_type, []):
            if rule.get("target") not in target_genres:
                raise ValueError(f"映射规则 {rule.get('id', '未知')} 指向无效风格")
            if not rule.get(condition_key) or not isinstance(rule.get("score"), (int, float)):
                raise ValueError(f"映射规则 {rule.get('id', '未知')} 缺少 {condition_key} 或 score")
    for rule in mapping.get("artist_confidence_adjustments", []):
        if not rule.get("id") or not rule.get("artist_match_any"):
            raise ValueError("艺人置信度校准缺少 id 或 artist_match_any")
        if rule.get("target") not in target_genres:
            raise ValueError(f"艺人置信度校准 {rule.get('id', '未知')} 指向无效风格")
        if not isinstance(rule.get("confidence_delta"), (int, float)) or rule["confidence_delta"] <= 0:
            raise ValueError(f"艺人置信度校准 {rule.get('id', '未知')} 的 confidence_delta 必须大于 0")
        if not isinstance(rule.get("max_confidence"), (int, float)) or not 0 < rule["max_confidence"] <= 1:
            raise ValueError(f"艺人置信度校准 {rule.get('id', '未知')} 的 max_confidence 必须在 0–1 之间")
    for rule in mapping.get("artist_genre_calibrations", []):
        if not rule.get("id") or not rule.get("artist_match_any"):
            raise ValueError("艺人风格校准缺少 id 或 artist_match_any")
        if rule.get("target") not in target_genres:
            raise ValueError(f"艺人风格校准 {rule.get('id', '未知')} 指向无效风格")
        if not isinstance(rule.get("score_bonus"), (int, float)) or rule["score_bonus"] <= 0:
            raise ValueError(f"艺人风格校准 {rule.get('id', '未知')} 的 score_bonus 必须大于 0")
        if "album_match_any" in rule and not isinstance(rule["album_match_any"], list):
            raise ValueError(f"艺人风格校准 {rule.get('id', '未知')} 的 album_match_any 必须是列表")
    policy_ids: set[str] = set()
    valid_policy_actions = {"accepted", "boundary_accepted", "deferred"}
    for rule in mapping.get("artist_review_policies", []):
        name = rule.get("id", "未知")
        if not rule.get("id") or not rule.get("artist_match_any"):
            raise ValueError("艺人复核政策缺少 id 或 artist_match_any")
        if name in policy_ids:
            raise ValueError(f"艺人复核政策 {name} 的 id 重复")
        policy_ids.add(name)
        for field in ("accepted_genres", "rejected_genres"):
            if field in rule and (not isinstance(rule[field], list) or not set(rule[field]) <= target_genres):
                raise ValueError(f"艺人复核政策 {name} 的 {field} 包含无效风格")
        if not rule.get("accepted_genres") and not rule.get("rejected_genres"):
            raise ValueError(f"艺人复核政策 {name} 至少需要 accepted_genres 或 rejected_genres")
        if "on_accepted" in rule and rule["on_accepted"] not in valid_policy_actions:
            raise ValueError(f"艺人复核政策 {name} 的 on_accepted 无效")
        if "on_rejected" in rule and rule["on_rejected"] not in valid_policy_actions:
            raise ValueError(f"艺人复核政策 {name} 的 on_rejected 无效")
    return mapping


def flatten_library(library: dict) -> list[dict]:
    result: list[dict] = []
    seen: set[str] = set()
    for singer in library.get("singers", []):
        for song in singer.get("songs", []):
            key = track_id(song)
            if key in seen:
                continue
            seen.add(key)
            result.append({
                "id": key,
                "title": song.get("title", ""),
                "artist": singer.get("name", ""),
                "album": song.get("album", ""),
                "full_singer": song.get("full_singer", ""),
                "qq_music": song.get("qq_music", ""),
            })
    return result


def lastfm_request(
    api_key: str,
    method: str,
    request_timeout: float = 15,
    request_attempts: int = 3,
    **params: str,
) -> tuple[list[dict], str | None]:
    query = {"method": method, "api_key": api_key, "format": "json", "autocorrect": 1, **params}
    for attempt in range(request_attempts):
        try:
            request = Request(
                f"{LASTFM_URL}?{urlencode(query)}",
                headers={"User-Agent": "SongBaseTagCandidates/1.0"},
            )
            with urlopen(request, timeout=request_timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            if "error" in data:
                return [], data.get("message", "Last.fm API error")
            raw = data.get("toptags", {}).get("tag", [])
            if isinstance(raw, dict):
                raw = [raw]
            tags = []
            for item in raw:
                name = str(item.get("name", "")).strip()
                if name:
                    try:
                        count = int(item.get("count", 0))
                    except (TypeError, ValueError):
                        count = 0
                    tags.append({"name": name, "count": count})
            return tags, None
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            if attempt == request_attempts - 1:
                return [], str(exc)
            time.sleep(1 + attempt)
    return [], "unknown request failure"


def request_cache_key(method: str, params: dict[str, str]) -> str:
    return json.dumps({"method": method, "params": params}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load_request_cache(path: Path) -> dict[str, list[dict]]:
    if not path.exists():
        return {}
    data = load_json(path)
    requests = data.get("requests", {})
    if not isinstance(requests, dict) or not all(isinstance(tags, list) for tags in requests.values()):
        raise ValueError(f"Last.fm 缓存格式无效：{path}")
    return requests


def write_request_cache(path: Path, requests: dict[str, list[dict]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": "songbase.lastfm-cache/v1", "requests": requests}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def collect_evidence(
    api_key: str,
    song: dict,
    delay: float,
    request_timeout: float = 15,
    request_attempts: int = 3,
    request_cache: dict[str, list[dict]] | None = None,
    request_cache_lock: Lock | None = None,
) -> tuple[list[dict], list[str]]:
    query_artist = lookup_artist(song["artist"])
    checks = [
        ("lastfm_track", "track.getTopTags", {"artist": query_artist, "track": song["title"]}, 1.0),
        ("lastfm_album", "album.getTopTags", {"artist": query_artist, "album": song["album"]}, 0.7),
        ("lastfm_artist", "artist.getTopTags", {"artist": query_artist}, 0.35),
    ]
    evidence: list[dict] = []
    errors: list[str] = []
    for source, method, params, source_weight in checks:
        cache_key = request_cache_key(method, params)
        cached_tags = None
        if request_cache is not None:
            if request_cache_lock:
                with request_cache_lock:
                    cached_tags = request_cache.get(cache_key)
            else:
                cached_tags = request_cache.get(cache_key)
        if cached_tags is not None:
            tags, error = cached_tags, None
        else:
            tags, error = lastfm_request(
                api_key,
                method,
                request_timeout=request_timeout,
                request_attempts=request_attempts,
                **params,
            )
            if error is None and request_cache is not None:
                if request_cache_lock:
                    with request_cache_lock:
                        request_cache[cache_key] = tags
                else:
                    request_cache[cache_key] = tags
        if error:
            errors.append(f"{source}: {error}")
        elif tags:
            evidence.append({"source": source, "source_weight": source_weight, "raw_tags": tags[:12]})
            # Track-level tags are enough for this first pass; keep lower-level
            # sources only as fallback, so artist taste cannot dominate a song.
            if source == "lastfm_track":
                break
        time.sleep(delay)
    return evidence, errors


def artist_confidence_adjustment(mapping: dict, artist: str, genre: str) -> dict | None:
    normalized_artist = normalize(artist) if artist else ""
    matching_rules = [
        rule
        for rule in mapping.get("artist_confidence_adjustments", [])
        if rule.get("target") == genre
        and normalized_artist in {normalize(value) for value in rule.get("artist_match_any", [])}
    ]
    if not matching_rules:
        return None
    return max(matching_rules, key=lambda rule: rule["confidence_delta"])


def artist_genre_calibrations(mapping: dict, artist: str, album: str) -> list[dict]:
    normalized_artist = normalize(artist) if artist else ""
    normalized_album = normalize(album) if album else ""
    matching_rules = []
    for rule in mapping.get("artist_genre_calibrations", []):
        artist_matches = normalized_artist in {normalize(value) for value in rule.get("artist_match_any", [])}
        album_terms = rule.get("album_match_any", [])
        album_matches = not album_terms or normalized_album in {normalize(value) for value in album_terms}
        if artist_matches and album_matches:
            matching_rules.append(rule)
    return matching_rules


def artist_review_policy(mapping: dict, artist: str, genre: str | None) -> dict | None:
    if not genre:
        return None
    normalized_artist = normalize(artist) if artist else ""
    for rule in mapping.get("artist_review_policies", []):
        if rule.get("status") == "deprecated":
            continue
        aliases = {normalize(value) for value in rule.get("artist_match_any", [])}
        if normalized_artist not in aliases:
            continue
        if genre in rule.get("rejected_genres", []):
            return {
                "id": rule["id"],
                "disposition": rule.get("on_rejected", "deferred"),
                "accepted_genres": rule.get("accepted_genres", []),
                "rejected_genres": rule.get("rejected_genres", []),
                "status": rule.get("status", "unclassified"),
                "note": rule.get("note", ""),
            }
        if genre in rule.get("accepted_genres", []):
            return {
                "id": rule["id"],
                "disposition": rule.get("on_accepted", "accepted"),
                "accepted_genres": rule.get("accepted_genres", []),
                "rejected_genres": rule.get("rejected_genres", []),
                "status": rule.get("status", "unclassified"),
                "note": rule.get("note", ""),
            }
    return None


def apply_artist_review_policy(record: dict, mapping: dict) -> None:
    policy = artist_review_policy(mapping, record.get("artist", ""), record.get("genre_candidate"))
    previous_reason = record.get("status_reason")
    if policy:
        record["artist_review_policy"] = policy
        if policy["disposition"] == "deferred":
            record["status"] = "deferred"
            record["status_reason"] = "artist_review_policy"
        elif previous_reason == "artist_review_policy":
            record["status"] = "candidate"
            record.pop("status_reason", None)
        return
    record.pop("artist_review_policy", None)
    if previous_reason == "artist_review_policy":
        record["status"] = "candidate"
        record.pop("status_reason", None)


def classify(
    evidence: list[dict], mapping: dict, artist: str = "", album: str = ""
) -> tuple[str | None, float, list[dict], list[dict], bool | None, dict]:
    scores: Counter[str] = Counter()
    matches: list[dict] = []
    instrumental_signal = False
    observations: dict[str, list[dict]] = {}
    ignored_terms = {normalize(term) for term in mapping.get("ignored_terms", [])}

    for source in evidence:
        for raw in source["raw_tags"]:
            tag = normalize(raw["name"])
            observations.setdefault(tag, []).append({
                "source": source["source"],
                "source_weight": source["source_weight"],
                "raw_name": raw["name"],
                "count": raw["count"],
            })
            if tag in {"instrumental", "instrumentals"}:
                instrumental_signal = True
            if tag in ignored_terms:
                continue
            for rule in mapping.get("direct_rules", []):
                if tag not in {normalize(term) for term in rule["match_any"]}:
                    continue
                # Counts are inconsistent between Last.fm endpoints, so they
                # modestly break ties without letting popularity define genre.
                count_bonus = min(raw["count"], 100) / 100
                score = source["source_weight"] * (rule["score"] + count_bonus)
                scores[rule["target"]] += score
                matches.append({
                    "source": source["source"],
                    "source_weight": source["source_weight"],
                    "tag": raw["name"],
                    "genre": rule["target"],
                    "rule_id": rule["id"],
                    "rule_score": rule["score"],
                    "rule_status": rule.get("status", "unclassified"),
                    "count_bonus": round(count_bonus, 2),
                    "score": round(score, 2),
                })

    for rule in mapping.get("combination_rules", []):
        required_terms = {normalize(term) for term in rule["match_all"]}
        optional_terms = {normalize(term) for term in rule.get("require_any", [])}
        if not required_terms.issubset(observations) or (optional_terms and not optional_terms.intersection(observations)):
            continue
        related_terms = required_terms | optional_terms.intersection(observations)
        related = [item for term in related_terms for item in observations.get(term, [])]
        # A combination is only as reliable as its weakest contributing source.
        source_weight = min(item["source_weight"] for item in related)
        score = source_weight * rule["score"]
        scores[rule["target"]] += score
        matches.append({
            "source": "mapping_combination",
            "evidence_sources": sorted({item["source"] for item in related}),
            "source_weight": source_weight,
            "tag": " + ".join(sorted(required_terms)) + " + context",
            "genre": rule["target"],
            "rule_id": rule["id"],
            "rule_score": rule["score"],
            "rule_status": rule.get("status", "unclassified"),
            "count_bonus": 0,
            "score": round(score, 2),
        })

    applied_genre_calibrations: list[dict] = []
    # A calibration is an explicit human prior: it may change the winning
    # genre, but it never grants track/album-level source confidence by itself.
    if scores:
        for rule in artist_genre_calibrations(mapping, artist, album):
            score = rule["score_bonus"]
            scores[rule["target"]] += score
            scope = "artist + album" if rule.get("album_match_any") else "artist"
            applied_genre_calibrations.append({
                "id": rule["id"],
                "target": rule["target"],
                "score_bonus": score,
                "scope": scope,
                "status": rule.get("status", "unclassified"),
                "note": rule.get("note", ""),
            })
            matches.append({
                "source": "artist_genre_calibration",
                "evidence_sources": ["artist_genre_calibration"],
                "source_weight": 1.0,
                "tag": f"{artist} · {scope} prior",
                "genre": rule["target"],
                "rule_id": rule["id"],
                "rule_score": score,
                "rule_status": rule.get("status", "unclassified"),
                "count_bonus": 0,
                "score": round(score, 2),
            })

    if not scores:
        details = {
            "formula_version": "songbase.candidate-confidence/v4",
            "input_sources": [
                {"source": item["source"], "weight": item["source_weight"]}
                for item in evidence
            ],
            "reason": "没有原始标签命中任何风格映射规则",
            "final_confidence": 0.0,
        }
        return None, 0.0, [], [], True if instrumental_signal else None, details
    ranking = scores.most_common(2)
    winner, winning_score = ranking[0]
    runner_score = ranking[1][1] if len(ranking) > 1 else 0.0
    runner = ranking[1][0] if len(ranking) > 1 else None
    winner_matches = [item for item in matches if item["genre"] == winner]
    winner_sources = {
        source
        for item in winner_matches
        for source in item.get("evidence_sources", [item["source"]])
        if source != "artist_genre_calibration"
    }
    source_count = len(winner_sources)
    margin = winning_score / (winning_score + runner_score + 1)
    base_component = 0.36
    source_component = 0.17 * min(source_count, 2)
    separation_component = 0.42 * margin
    uncapped_confidence = min(0.94, base_component + source_component + separation_component)
    # A genre inferred only from artist-wide taste is a useful lead but not
    # evidence about this specific track. Keep the confidence honest so the
    # review queue prioritizes track and album-level candidates.
    if "lastfm_track" in winner_sources:
        cap = 0.88
    elif "lastfm_album" in winner_sources:
        cap = 0.80
    else:
        cap = 0.65
    base_confidence = min(uncapped_confidence, cap)
    calibration = artist_confidence_adjustment(mapping, artist, winner)
    effective_cap = cap
    confidence = base_confidence
    calibration_details = None
    if calibration:
        effective_cap = max(cap, calibration["max_confidence"])
        confidence = min(uncapped_confidence, base_confidence + calibration["confidence_delta"], effective_cap)
        calibration_details = {
            "id": calibration["id"],
            "artist": artist,
            "target": winner,
            "requested_delta": calibration["confidence_delta"],
            "applied_delta": round(confidence - base_confidence, 4),
            "base_confidence": round(base_confidence, 4),
            "cap_before": cap,
            "cap_after": effective_cap,
            "status": calibration.get("status", "unclassified"),
            "note": calibration.get("note", ""),
        }
    secondary_candidates: list[dict] = []
    for genre, score in scores.most_common():
        if genre == winner or len(secondary_candidates) >= SECONDARY_MAX_COUNT:
            continue
        relative_score = score / winning_score if winning_score else 0.0
        genre_matches = [
            item for item in matches
            if item["genre"] == genre and item.get("source") != "artist_genre_calibration"
        ]
        if score < SECONDARY_MIN_SCORE or relative_score < SECONDARY_MIN_RELATIVE_SCORE or not genre_matches:
            continue
        genre_sources = {
            source
            for item in genre_matches
            for source in item.get("evidence_sources", [item["source"]])
            if source != "artist_genre_calibration"
        }
        if "lastfm_track" in genre_sources:
            secondary_cap = 0.88
        elif "lastfm_album" in genre_sources:
            secondary_cap = 0.80
        else:
            secondary_cap = 0.65
        secondary_confidence = min(confidence, secondary_cap, 0.45 + 0.40 * relative_score)
        secondary_candidates.append({
            "genre": genre,
            "confidence": round(secondary_confidence, 2),
            "score": round(score, 2),
            "relative_score": round(relative_score, 4),
            "matched_rule_ids": list(dict.fromkeys(item["rule_id"] for item in genre_matches)),
            "matched_tags": [
                {
                    "tag": item["tag"],
                    "source": item["source"],
                    "rule_id": item["rule_id"],
                    "score": item["score"],
                }
                for item in sorted(genre_matches, key=lambda match: match["score"], reverse=True)
            ],
        })

    details = {
        "formula_version": "songbase.candidate-confidence/v4",
        "input_sources": [
            {"source": item["source"], "weight": item["source_weight"]}
            for item in evidence
        ],
        "winner": {
            "genre": winner,
            "score": round(winning_score, 2),
            "sources": sorted(winner_sources),
            "source_count": source_count,
        },
        "runner_up": {"genre": runner, "score": round(runner_score, 2)} if runner else None,
        "all_target_scores": [
            {"genre": genre, "score": round(score, 2)}
            for genre, score in scores.most_common()
        ],
        "margin": round(margin, 4),
        "components": {
            "base": base_component,
            "source_diversity": round(source_component, 4),
            "separation": round(separation_component, 4),
            "uncapped_confidence": round(uncapped_confidence, 4),
        },
        "source_cap": {
            "value": effective_cap,
            "basis": "lastfm_track" if cap == 0.88 else "lastfm_album" if cap == 0.80 else "lastfm_artist",
            "applied": uncapped_confidence > effective_cap,
            "base_value": cap,
        },
        "artist_genre_calibrations": applied_genre_calibrations,
        "artist_calibration": calibration_details,
        "secondary_candidates": secondary_candidates,
        "final_confidence": round(confidence, 2),
        "notes": [
            "规则 status 会被记录，但当前公式不会因 verified 或 proposed 而改变分数。",
            "Last.fm 标签热度仅作为 0–1 的小幅加分；主要权重来自来源层级与映射规则分数。",
            "副风格最多两个，要求得分不少于 2.0、达到主风格得分的 45%，且不能只由艺人先验产生。",
        ]
        + [f"已应用艺人 / 专辑风格先验：{item['id']}（+{item['score_bonus']:.2f} 分）。" for item in applied_genre_calibrations]
        + ([f"已应用艺人置信度校准：{calibration['id']}（+{calibration['confidence_delta']:.0%}，上限 {effective_cap:.0%}）。"] if calibration else []),
    }
    return winner, round(confidence, 2), secondary_candidates, sorted(winner_matches, key=lambda item: item["score"], reverse=True), True if instrumental_signal else None, details


def describe_candidate(candidate: dict) -> str:
    if candidate["genre_candidate"]:
        policy = candidate.get("artist_review_policy") or {}
        suffix = " · 边界可接受" if policy.get("disposition") == "boundary_accepted" else " · 艺人规则认可" if policy.get("disposition") == "accepted" else " · 艺人规则暂缓" if policy.get("disposition") == "deferred" else ""
        secondary = candidate.get("secondary_genre_candidates", [])
        secondary_text = " · 副：" + "、".join(f"{item['genre']}（{item['confidence']:.0%}）" for item in secondary) if secondary else ""
        return f"{candidate['genre_candidate']}（{candidate['confidence']:.0%}）{secondary_text}{suffix}"
    return "无可用风格候选"


def write_report(output: dict) -> None:
    records = list(output["tracks"].values())
    classified = [item for item in records if item["genre_candidate"]]
    high = [item for item in classified if item["confidence"] >= 0.75]
    failed = [item for item in records if not item["genre_candidate"]]
    distribution = Counter(item["genre_candidate"] for item in classified)
    sample = output["sample"]
    sample_context = "全量未入库歌曲" if sample.get("mode") == "all_untagged" else f"随机种子：`{sample['seed']}`"
    lines = [
        "# SongBase 首轮标签候选报告",
        "",
        f"> 抽样 {len(records)} 首 · 可分类 {len(classified)} 首 · 高置信候选（≥75%）{len(high)} 首 · 无候选 {len(failed)} 首",
        f"> {sample_context} · 映射版本：`{output.get('mapping_version', 'legacy')}` · 来源：Last.fm（曲目 → 专辑 → 艺人回退）",
        "",
        "## 风格候选分布",
        "",
        "| 风格 | 数量 |",
        "|---|---:|",
        *[f"| {genre} | {distribution[genre]} |" for genre in output["taxonomy"]["genres"]],
        "",
        "## 逐曲候选",
        "",
        "| 歌曲 | 艺人 | 候选 | 主要依据 |",
        "|---|---|---|---|",
    ]
    for item in sorted(records, key=lambda value: (value["confidence"], value["title"]), reverse=True):
        reason = "; ".join(f"{match['source']}: {match['tag']}" for match in item["matched_tags"][:3]) or "—"
        lines.append(f"| {item['title']} | {item['artist']} | {describe_candidate(item)} | {reason} |")
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def candidate_output(tag_data: dict, mapping: dict, sample_metadata: dict, records: dict[str, dict]) -> dict:
    return {
        "schema_version": "songbase.tag-candidates/v1",
        "generated_at": date.today().isoformat(),
        "sample": sample_metadata,
        "taxonomy": tag_data["taxonomy"],
        "mapping_version": mapping["version"],
        "sources": ["Last.fm track.getTopTags", "Last.fm album.getTopTags", "Last.fm artist.getTopTags"],
        "tracks": records,
    }


def write_checkpoint(path: Path, output: dict, complete: bool) -> None:
    snapshot = {
        **output,
        "checkpoint": {
            "complete": complete,
            "saved_at": date.today().isoformat(),
            "completed_records": len(output["tracks"]),
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 SongBase 的只读标签候选")
    parser.add_argument("--sample-size", type=int, default=50, help="抽样歌曲数，默认 50")
    parser.add_argument("--seed", type=int, default=20260807, help="可复现随机种子")
    parser.add_argument("--all-untagged", action="store_true", help="处理所有尚未进入正式标签的歌曲，而非随机抽样")
    parser.add_argument("--reuse-current-candidates", action="store_true", help="全量生成时保留当前候选 JSON 中仍未入库的记录，避免重复查询")
    parser.add_argument("--delay", type=float, default=0.25, help="Last.fm 请求间隔（秒）")
    parser.add_argument("--request-timeout", type=float, default=15, help="单次 Last.fm 请求超时（秒），默认 15")
    parser.add_argument("--request-attempts", type=int, default=3, help="单次 Last.fm 请求最大尝试次数，默认 3")
    parser.add_argument("--workers", type=int, default=1, help="并行查询数，默认 1；建议不超过 8")
    parser.add_argument("--checkpoint-path", type=Path, help="分段生成时保存进度的 JSON 路径")
    parser.add_argument("--lastfm-cache-path", type=Path, help="跨分段复用 Last.fm 成功响应的 JSON 缓存路径")
    parser.add_argument("--batch-size", type=int, help="本次最多处理多少首；与 checkpoint-path 一起使用可续跑")
    parser.add_argument("--resume", action="store_true", help="从 checkpoint-path 继续未完成批次")
    parser.add_argument("--dry-run", action="store_true", help="只列出抽样歌曲，不访问网络或写文件")
    parser.add_argument("--refresh-existing", action="store_true", help="用当前规则重算已有候选，不访问网络")
    args = parser.parse_args()
    if args.request_timeout <= 0:
        raise ValueError("request-timeout 必须大于 0")
    if args.request_attempts < 1:
        raise ValueError("request-attempts 必须至少为 1")
    if not 1 <= args.workers <= 8:
        raise ValueError("workers 必须在 1–8 之间")
    if args.batch_size is not None and args.batch_size < 1:
        raise ValueError("batch-size 必须至少为 1")
    if args.batch_size is not None and not args.checkpoint_path:
        raise ValueError("batch-size 需要同时提供 checkpoint-path，避免写出半批候选")
    if args.resume and not args.checkpoint_path:
        raise ValueError("resume 需要同时提供 checkpoint-path")
    if args.reuse_current_candidates and not args.all_untagged:
        raise ValueError("reuse-current-candidates 仅适用于 all-untagged")

    tag_data = load_json(TAGS_PATH)
    mapping = load_mapping(tag_data["taxonomy"])
    if args.refresh_existing:
        output = load_json(CANDIDATES_PATH)
        for record in output.get("tracks", {}).values():
            genre, confidence, secondary_genres, matches, instrumental, confidence_details = classify(
                record.get("evidence", []), mapping, record.get("artist", ""), record.get("album", "")
            )
            record["genre_candidate"] = genre
            record["secondary_genre_candidates"] = secondary_genres
            record["confidence"] = confidence
            record["confidence_details"] = confidence_details
            record["matched_tags"] = matches
            record["instrumental_candidate"] = instrumental
            apply_artist_review_policy(record, mapping)
        output["mapping_version"] = mapping["version"]
        output["rescored_at"] = date.today().isoformat()
        CANDIDATES_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_report(output)
        print(f"已用当前规则重算 {len(output.get('tracks', {}))} 条候选")
        return

    library = load_json(LIBRARY_PATH)
    tracks = flatten_library(library)
    existing = set(tag_data.get("tracks", {}))
    untagged = [song for song in tracks if song["id"] not in existing]
    if args.all_untagged:
        sample = untagged
        sample_metadata = {"size": len(sample), "mode": "all_untagged", "population": len(untagged)}
    else:
        if args.sample_size < 1 or args.sample_size > len(untagged):
            raise ValueError(f"sample-size 必须介于 1 与 {len(untagged)} 之间")
        sample = random.Random(args.seed).sample(untagged, args.sample_size)
        sample_metadata = {"size": args.sample_size, "seed": args.seed, "population": len(untagged)}

    if args.dry_run:
        for song in sample:
            print(f"{song['id']}\t{song['artist']} — {song['title']}")
        return

    if args.checkpoint_path and args.resume:
        if not args.checkpoint_path.exists():
            raise FileNotFoundError(f"找不到检查点：{args.checkpoint_path}")
        checkpoint = load_json(args.checkpoint_path)
        checkpoint_sample = checkpoint.get("sample", {})
        if checkpoint_sample != sample_metadata:
            raise ValueError("检查点的抽样参数与当前命令不一致，无法继续")
        records = checkpoint.get("tracks", {})
        if not isinstance(records, dict):
            raise ValueError("检查点的 tracks 必须是对象")
    else:
        if args.checkpoint_path and args.checkpoint_path.exists():
            raise FileExistsError(f"检查点已存在：{args.checkpoint_path}；如需继续请使用 --resume")
        records = {}
        if args.reuse_current_candidates:
            current_candidates = load_json(CANDIDATES_PATH).get("tracks", {})
            sample_ids = {song["id"] for song in sample}
            records = {track_id: record for track_id, record in current_candidates.items() if track_id in sample_ids}
            print(f"已保留 {len(records)} 条现有候选，开始查询其余歌曲。")

    request_cache = load_request_cache(args.lastfm_cache_path) if args.lastfm_cache_path else {}
    request_cache_lock = Lock()

    pending = [song for song in sample if song["id"] not in records]
    if args.batch_size is not None:
        pending = pending[:args.batch_size]
    if pending:
        api_key = get_api_key()
    sample_positions = {song["id"]: index for index, song in enumerate(sample, 1)}

    def save_record(song: dict, evidence: list[dict], errors: list[str]) -> None:
        genre, confidence, secondary_genres, matches, instrumental, confidence_details = classify(
            evidence, mapping, song["artist"], song["album"]
        )
        record = {
            "title": song["title"],
            "artist": song["artist"],
            "album": song["album"],
            "genre_candidate": genre,
            "secondary_genre_candidates": secondary_genres,
            "confidence": confidence,
            "confidence_details": confidence_details,
            "status": "candidate",
            "instrumental_candidate": instrumental,
            "evidence": evidence,
            "matched_tags": matches,
            "errors": errors,
        }
        apply_artist_review_policy(record, mapping)
        records[song["id"]] = record
        print(f"[{sample_positions[song['id']]}/{len(sample)}] {song['artist']} — {song['title']} → {genre or '无候选'} · {confidence:.0%}", flush=True)
        if args.checkpoint_path:
            write_checkpoint(
                args.checkpoint_path,
                candidate_output(tag_data, mapping, sample_metadata, records),
                complete=False,
            )

    def fetch_song(song: dict) -> tuple[list[dict], list[str]]:
        return collect_evidence(
            api_key,
            song,
            args.delay,
            request_timeout=args.request_timeout,
            request_attempts=args.request_attempts,
            request_cache=request_cache,
            request_cache_lock=request_cache_lock,
        )

    if args.workers == 1:
        for song in pending:
            evidence, errors = fetch_song(song)
            save_record(song, evidence, errors)
    elif pending:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(fetch_song, song): song for song in pending}
            for future in as_completed(futures):
                song = futures[future]
                try:
                    evidence, errors = future.result()
                except Exception as exc:  # Keep one unexpected provider failure from losing the batch.
                    evidence, errors = [], [f"unexpected collection error: {exc}"]
                save_record(song, evidence, errors)

    if args.lastfm_cache_path and pending:
        with request_cache_lock:
            write_request_cache(args.lastfm_cache_path, request_cache)

    if len(records) < len(sample):
        print(f"\n已完成 {len(records)}/{len(sample)} 首；进度已写入 {args.checkpoint_path}，请用 --resume 继续。")
        return

    output = candidate_output(tag_data, mapping, sample_metadata, records)
    CANDIDATES_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.checkpoint_path:
        write_checkpoint(args.checkpoint_path, output, complete=True)
    write_report(output)
    classified = sum(record["genre_candidate"] is not None for record in records.values())
    high = sum(record["confidence"] >= 0.75 for record in records.values() if record["genre_candidate"])
    print(f"\n已生成 {CANDIDATES_PATH.name} 与 {REPORT_PATH.name}")
    print(f"候选：{classified}/{len(records)} · 高置信：{high}")


if __name__ == "__main__":
    main()
