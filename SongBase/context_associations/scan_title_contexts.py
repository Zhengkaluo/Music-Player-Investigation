#!/usr/bin/env python3
"""Scan SongBase titles only; never approve associations or modify source data."""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import html
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
SONGBASE = BASE.parent
REPO = SONGBASE.parent
MID_RE = re.compile(r"/songDetail/([A-Za-z0-9]+)")
STRENGTH_LABELS = {"explicit": "明确标题关联", "indirect": "间接线索", "ambiguous": "语义待确认"}
STRENGTH_ORDER = {"explicit": 0, "indirect": 1, "ambiguous": 2}
CREDIT_MARKER = r"(?:feat(?:uring)?\.?|ft\.?)(?=\s|\()"
CREDIT_RE = re.compile(r"(?i)(?<![A-Za-z])" + CREDIT_MARKER)
VERSION_RE = re.compile(r"(?i)^(?:live\b|remaster(?:ed)?\b|explicit$|radio edit$|instrumental$|deluxe\b|.*\bremix$)")
MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
DAY_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "twelve": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19, "twentieth": 20, "twenty-first": 21, "twenty-second": 22, "twenty-third": 23, "twenty-fourth": 24, "twenty-fifth": 25, "twenty-sixth": 26, "twenty-seventh": 27, "twenty-eighth": 28, "twenty-ninth": 29, "thirtieth": 30, "thirty-first": 31}
CLOCK_RE = re.compile(r"(?<!\w)(?:(?P<prefix>am|pm)\s*)?(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<suffix>am|pm)?(?!\w)")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalize_with_map(text, pairs):
    result, offsets = [], []
    index = 0
    while index < len(text):
        end = index + 1
        while end < len(text) and unicodedata.combining(text[end]):
            end += 1
        normalized = unicodedata.normalize("NFKC", text[index:end]).casefold()
        for char in normalized:
            result.append(pairs.get(char, char))
            offsets.append((index, end))
        index = end
    return "".join(result), offsets


def title_view(original, pairs):
    ignored = []
    for bracket in re.finditer(r"\([^()]*\)|\[[^\[\]]*\]", original):
        content = bracket.group()[1:-1].strip()
        if CREDIT_RE.match(content):
            ignored.append({"kind": "artist_credit", "text": bracket.group(), "start": bracket.start(), "end": bracket.end()})
        elif VERSION_RE.match(content):
            ignored.append({"kind": "technical_version", "text": bracket.group(), "start": bracket.start(), "end": bracket.end()})
    masked = list(original)
    for segment in ignored:
        masked[segment["start"]:segment["end"]] = " " * (segment["end"] - segment["start"])
    remaining = "".join(masked)
    marker = CREDIT_RE.search(remaining)
    if marker:
        ignored.append({"kind": "artist_credit", "text": original[marker.start():], "start": marker.start(), "end": len(original)})
        masked[marker.start():] = " " * (len(original) - marker.start())
    text, offsets = normalize_with_map("".join(masked), pairs)
    return text, offsets, ignored


def alias_pattern(alias, mode, rule_id):
    escaped = re.escape(alias).replace(r"\ ", r"\s+")
    if mode == "exact":
        return r"^\s*" + escaped + r"\s*$"
    if rule_id.startswith("calendar.month") and re.search(r"[一二三四五六七八九十0-9]+月", alias):
        return r"(?<![0-9一二三四五六七八九十〇零])" + escaped
    if re.fullmatch(r"-?\d+°c", alias):
        return r"(?<![0-9])" + escaped
    is_word = mode == "word" or (mode == "mixed" and re.search(r"[a-zÀ-ÿ]", alias))
    if is_word:
        right = r"(?![^\W\d_])" if alias.endswith(".") else r"(?![^\W_])"
        return r"(?<![^\W_])" + escaped + right
    return escaped


def compile_rules(config):
    compiled, ids, category_names = [], set(), config["categories"]
    pairs = config["normalization"]["traditional_pairs"]
    for rule in config["rules"]:
        if rule["id"] in ids or rule["category"] not in category_names:
            raise ValueError("规则 ID 重复或类别无效：" + rule["id"])
        if rule["strength"] not in STRENGTH_LABELS or not rule["aliases"]:
            raise ValueError("规则缺少有效强度或词表：" + rule["id"])
        ids.add(rule["id"])
        patterns = []
        for alias in rule["aliases"]:
            normalized, _ = normalize_with_map(alias, pairs)
            patterns.append((alias, re.compile(alias_pattern(normalized, rule["match_mode"], rule["id"]))))
        compiled.append((rule, patterns))
    return compiled


def match_evidence(title, text, offsets, match, alias, rule_id):
    start, end = match.span()
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    left, right = offsets[start][0], offsets[end - 1][1]
    return {"type": "title", "source_title": title, "matched_text": title[left:right], "span": [left, right], "matched_alias": alias, "rule_id": rule_id}


def candidate(tag, category, label, strength, evidence, reason, trigger=None):
    return {"tag": tag, "category": category, "label": label, "title_judgment": strength, "judgment_label": STRENGTH_LABELS[strength], "review_status": "pending", "auto_lock_allowed": False, "reason": reason, "evidence": evidence, "trigger_hint": trigger or {"enabled": False, "recurrence": "not_configured"}}


def date_matches(title, text, offsets, config):
    associations = []
    day_pattern = "|".join(re.escape(w) for w in sorted(DAY_WORDS, key=len, reverse=True))
    for month, name in enumerate(MONTH_NAMES, 1):
        short = "sept" if month == 9 else name[:3]
        month_pattern = re.escape(name) + "|" + re.escape(short) + r"\."
        if month == 4 and any("avril" in rule["aliases"] for rule in config["rules"] if rule["id"] == "calendar.month04"):
            month_pattern += "|avril"
        pattern = re.compile(r"(?<!\w)(?:" + month_pattern + r")\s*(?P<day>\d{1,2}(?:st|nd|rd|th)?|" + day_pattern + r")(?!\w)(?:\s*,?\s+(?P<year>\d{4})(?!\d))?")
        for match in pattern.finditer(text):
            raw_day = match["day"]
            day = DAY_WORDS.get(raw_day) or int(re.sub(r"\D", "", raw_day))
            year = int(match["year"]) if match["year"] else None
            try:
                date(year or 2000, month, day)
            except ValueError:
                continue
            value = f"{year:04d}-{month:02d}-{day:02d}" if year else f"{month:02d}-{day:02d}"
            label = f"{year} 年 {month} 月 {day} 日" if year else f"{month} 月 {day} 日"
            reason = "明确的标题日期，不是发行日期；未设定每年重复播放。"
            evidence = match_evidence(title, text, offsets, match, match.group(), "parser.calendar_date")
            hint = {"kind": "title_date", "year": year, "month": month, "day": day, "calendar": "gregorian_title_convention", "enabled": False, "recurrence": "not_configured"}
            associations.append(candidate("calendar.date." + value, "calendar", label, "explicit", [evidence], reason, hint))
    return associations


def clock_matches(title, text, offsets):
    associations = []
    for match in CLOCK_RE.finditer(text):
        marker = match["prefix"] or match["suffix"]
        hour, minute = int(match["hour"]), int(match["minute"] or 0)
        if not marker and not match["minute"]:
            continue
        if minute >= 60 or hour > (12 if marker else 23) or (marker and hour == 0):
            continue
        evidence = match_evidence(title, text, offsets, match, match.group().strip(), "parser.clock")
        if not marker:
            associations.append(candidate("time.clock_unspecified", "time_light", "无 AM／PM 的钟点候选", "ambiguous", [evidence], "数字可能是钟点、时长或编号，没有 AM／PM，不设置播放时段。"))
            continue
        hour24 = hour % 12 + (12 if marker == "pm" else 0)
        label = f"{hour24:02d}:{minute:02d}（标题钟点）"
        hint = {"kind": "clock_reference", "hour": hour24, "minute": minute, "timezone": "unset", "enabled": False}
        associations.append(candidate(f"time.clock.{hour24:02d}:{minute:02d}", "time_light", label, "explicit", [evidence], "明确 AM／PM 的标题钟点，不是歌曲时长，也不设置自动播放窗口。", hint))
    return associations


def merge_candidate(found, item):
    """Keep a single canonical tag without losing evidence or semantic judgments."""
    tag = item["tag"]
    if tag not in found:
        found[tag] = item
        return
    current = found[tag]
    for key in ("evidence", "source_associations", "scoring_groups", "weather_changes"):
        current.setdefault(key, [])
        current[key].extend(x for x in item.get(key, []) if x not in current[key])
    if STRENGTH_ORDER[item["title_judgment"]] < STRENGTH_ORDER[current["title_judgment"]]:
        current["title_judgment"] = item["title_judgment"]
        current["judgment_label"] = item["judgment_label"]
    current["reason"] = "；".join(dict.fromkeys([current["reason"], item["reason"]]))


def apply_store_policy(items, config):
    policy = config.get("policy", {})
    blocked = set(policy.get("excluded_tags", []))
    aliases = config.get("tag_aliases", {})
    groups = config.get("association_groups", {})
    changes = config.get("weather_changes", {})
    venue = config.get("venue", {})
    periods = venue.get("periods", [])
    minutes = lambda clock: sum(int(n) * factor for n, factor in zip(clock.split(":"), (60, 1)))
    clock_spans = [e["span"] for a in items if a["tag"].startswith("time.clock.") for e in a["evidence"]]
    shared_spans = [(a["tag"], e["span"]) for a in items if a["tag"] in changes or a["tag"].startswith("calendar.date.") for e in a["evidence"]]
    weekday_tags = {"calendar." + name for name in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "weekend")}
    found, filtered = {}, []
    for original in items:
        item = copy.deepcopy(original)
        raw_tag = item["tag"]
        if raw_tag in blocked:
            filtered.append(dict(item, exclusion_reason="门店已移出的情境关联。"))
            continue
        tag = aliases.get(raw_tag, raw_tag)
        if raw_tag.startswith("time.clock.") and periods:
            clock = minutes(raw_tag.removeprefix("time.clock."))
            period = next((p for p in periods if minutes(p["start"]) <= clock < minutes(p["end"])), None)
            if period is None:
                filtered.append(dict(item, exclusion_reason="标题钟点不在门店 08:00–18:00 营业区间。"))
                continue
            tag = period["tag"]
        elif raw_tag.startswith("time.") and clock_spans:
            # A marker in "7 PM" must not re-enter as a generic afternoon candidate.
            item["evidence"] = [e for e in item["evidence"] if not any(left <= e["span"][0] and e["span"][1] <= right for left, right in clock_spans)]
            if not item["evidence"]:
                continue
        item["source_associations"] = [{k: copy.deepcopy(item[k]) for k in ("tag", "label", "title_judgment", "reason", "trigger_hint", "evidence")}]
        item["scoring_groups"] = []
        for evidence in item["evidence"]:
            evidence["source_tag"] = raw_tag
            evidence["source_judgment"] = item["title_judgment"]
            span = evidence["span"]
            shared = next(((source, bounds) for source, bounds in shared_spans if bounds[0] <= span[0] and span[1] <= bounds[1]), None)
            key = f"{shared[0]}:{shared[1]}" if shared else f"title:{span}"
            if tag in weekday_tags:
                key = "calendar:weekday_and_weekend"
            if key not in item["scoring_groups"]:
                item["scoring_groups"].append(key)
        if raw_tag in changes:
            item["weather_changes"] = [dict(changes[raw_tag], source_tag=raw_tag)]
        for target in changes.get(raw_tag, {}).get("components", [tag]):
            if target in blocked:
                continue
            result = copy.deepcopy(item)
            result["tag"] = target
            group = groups.get(target, {})
            result.update({k: group[k] for k in ("label", "category") if k in group})
            if "trigger_hint" in group:
                result["trigger_hint"] = dict(group["trigger_hint"], enabled=False)
            merge_candidate(found, result)
    return list(found.values()), filtered


def scan_title(title, artist, config, compiled, reviews):
    text, offsets, ignored = title_view(title, config["normalization"]["traditional_pairs"])
    found = {}
    for rule, patterns in compiled:
        evidence = []
        for alias, pattern in patterns:
            for match in pattern.finditer(text):
                if match.end() > match.start():
                    item = match_evidence(title, text, offsets, match, alias, rule["id"])
                    if not any(e["span"] == item["span"] for e in evidence):
                        evidence.append(item)
        if not evidence:
            continue
        tag = rule.get("tag", rule["id"])
        reason = rule.get("note") or "标题明确出现该词语或短语；只认定标题意象，不推断歌词、情绪或播放适配。"
        if tag in found:
            found[tag]["evidence"].extend(evidence)
        else:
            found[tag] = candidate(tag, rule["category"], rule["label"], rule["strength"], evidence, reason)
        if rule.get("suppresses"):
            found[tag]["suppresses"] = rule["suppresses"]
    for item in date_matches(title, text, offsets, config) + clock_matches(title, text, offsets):
        found[item["tag"]] = item
    suppressed = {tag for item in found.values() for tag in item.pop("suppresses", [])}
    excluded = []
    for tag in suppressed:
        if tag in found:
            excluded.append(dict(found.pop(tag), exclusion_reason="被更具体的时间短语替代，避免误解或重复标签。"))
    for review in reviews["reviews"]:
        if review["title"] != title or review["artist"] != artist:
            continue
        item = found.get(review["tag"])
        if item is None:
            continue
        if review["action"] == "exclude":
            excluded.append(dict(found.pop(review["tag"]), exclusion_reason=review["reason"], agent_review=True))
            continue
        item["title_judgment"] = review["action"]
        item["judgment_label"] = STRENGTH_LABELS[review["action"]]
        item["reason"] = review["reason"]
        item["agent_review"] = True
        if review.get("trigger_hint"):
            item["trigger_hint"] = review["trigger_hint"]
        for addition in review.get("add", []):
            raw = addition["matched_text"]
            start = title.find(raw)
            if start < 0:
                raise ValueError("语义附加项证据不在原始标题：" + title)
            ev = {"type": "title", "source_title": title, "matched_text": raw, "span": [start, start + len(raw)], "rule_id": "agent_title_phrase_review"}
            found[addition["tag"]] = candidate(addition["tag"], addition["category"], addition["label"], addition["strength"], [ev], addition["note"])
    excluded_tags = set(config.get("policy", {}).get("excluded_tags", []))
    associations, store_filtered = apply_store_policy(list(found.values()), config)
    excluded = [item for item in excluded if item["tag"] not in excluded_tags]
    safeguards = [x["reason"] for x in reviews["title_safeguards"] if x["title"] == title and x["artist"] == artist]
    return associations, excluded, {"source_title": title, "search_title": text.strip(), "ignored_segments": ignored, "safeguards": safeguards, "store_filtered": store_filtered}


def load_tracks(library):
    tracks, rows = {}, 0
    for singer in library["singers"]:
        for song in singer["songs"]:
            rows += 1
            match = MID_RE.search(song.get("qq_music", ""))
            if not match:
                raise ValueError("缺少稳定 QQ MID：" + song.get("title", "未知歌曲"))
            tid = "qq:" + match.group(1)
            artist = song.get("full_singer") or singer["name"]
            record = {"title": song["title"], "artist": artist, "album": song.get("album", ""), "source_artist": singer["name"]}
            if tid not in tracks:
                tracks[tid] = {"track_id": tid, "title": song["title"], "artist": artist, "album": song.get("album", ""), "qq_music": song.get("qq_music", ""), "source_records": [], "associations": [], "excluded_associations": [], "title_audit": []}
            tracks[tid]["source_records"].append(record)
    return tracks, rows


def build_scan(library_path, config, reviews):
    library = load_json(library_path)
    tracks, row_count = load_tracks(library)
    compiled = compile_rules(config)
    for track in tracks.values():
        seen_titles = set()
        for record in track["source_records"]:
            identity = (record["title"], record["artist"])
            if identity in seen_titles:
                continue
            seen_titles.add(identity)
            associations, exclusions, audit = scan_title(*identity, config, compiled, reviews)
            by_tag = {a["tag"]: a for a in track["associations"]}
            for association in associations:
                if association["tag"] in by_tag:
                    merge_candidate(by_tag, association)
                else:
                    track["associations"].append(association)
                    by_tag[association["tag"]] = association
            track["excluded_associations"].extend(exclusions)
            track["title_audit"].append(audit)
        track["scan_status"] = "has_title_candidates" if track["associations"] else "no_title_match"
    candidate_tracks = [t for t in tracks.values() if t["associations"]]
    counts = Counter(a["title_judgment"] for t in tracks.values() for a in t["associations"])
    summary = {"input_rows": row_count, "unique_tracks_scanned": len(tracks), "duplicate_rows_collapsed": row_count - len(tracks), "tracks_with_candidates": len(candidate_tracks), "tracks_without_candidates": len(tracks) - len(candidate_tracks), "total_associations": sum(counts.values()), "associations_by_judgment": dict(counts), "tracks_with_explicit_candidates": sum(any(a["title_judgment"] == "explicit" for a in t["associations"]) for t in tracks.values()), "tracks_only_indirect_or_ambiguous": sum(not any(a["title_judgment"] == "explicit" for a in t["associations"]) for t in candidate_tracks), "excluded_associations": sum(len(t["excluded_associations"]) for t in tracks.values()), "categories": {key: {"label": label, "tracks": sum(any(a["category"] == key for a in t["associations"]) for t in tracks.values()), "associations": sum(a["category"] == key for t in tracks.values() for a in t["associations"])} for key, label in config["categories"].items()}}
    return {"schema_version": "songbase.context-title-scan/v1", "generated_at": datetime.now().astimezone().isoformat(), "rule_version": config["rule_version"], "semantic_review_version": reviews["review_version"], "scope": "full_library_song_titles_only", "approval_status": "all_candidates_pending_user_review", "source": {"path": str(Path(library_path).resolve()), "sha256": digest(library_path), "declared_unique_songs": library.get("total_unique_songs")}, "policy": config["policy"], "venue": config.get("venue"), "summary": summary, "tracks": tracks}


def category_rows(scan, category):
    rows = [(track, item) for track in scan["tracks"].values() for item in track["associations"] if item["category"] == category]
    return sorted(rows, key=lambda pair: (STRENGTH_ORDER[pair[1]["title_judgment"]], pair[1]["label"], pair[0]["artist"].casefold(), pair[0]["title"].casefold()))


def markdown_report(scan):
    s = scan["summary"]
    lines = ["# 歌曲标题情境扫描", "", "全库标题扫描；所有关联仍待用户复核，未写入正式曲库、正式标签或歌单。", "", f"扫描：{s['input_rows']} 条源记录 → {s['unique_tracks_scanned']} 首唯一歌曲。", f"候选：{s['tracks_with_candidates']} 首歌曲、{s['total_associations']} 条关联；无标题命中：{s['tracks_without_candidates']} 首。", f"明确标题关联：{s['tracks_with_explicit_candidates']} 首；仅有间接／歧义线索：{s['tracks_only_indirect_or_ambiguous']} 首。", "", "这里只解释标题，不解释歌词、作品主题、情绪或适合播放的天气；没有命中不等于没有内容关联。", ""]
    esc = lambda value: str(value).replace("|", "\\|").replace("\n", " ")
    for category, stats in s["categories"].items():
        lines.extend(["## " + stats["label"], "", f"{stats['tracks']} 首歌曲，{stats['associations']} 条关联。不同类别可重叠。", ""])
        rows = category_rows(scan, category)
        if not rows:
            lines.extend(["本次词表与标题审阅未发现候选；不是已证实曲库没有这类主题。", ""])
            continue
        lines.extend(["| 歌曲 | 艺人 | 情境 | 判断 | 命中依据 | 理由 |", "|---|---|---|---|---|---|"])
        for track, item in rows:
            fields = [track["title"], track["artist"], item["label"], item["judgment_label"], " / ".join(dict.fromkeys(e["matched_text"] for e in item["evidence"])), item["reason"]]
            lines.append("| " + " | ".join(map(esc, fields)) + " |")
        lines.append("")
    lines.extend(["## 语义排除与防误命中", "", "以下为 Agent 的标题初审，不是用户已确认的永久否决。", ""])
    for track in scan["tracks"].values():
        reasons = [item["exclusion_reason"] for item in track["excluded_associations"]]
        reasons.extend(reason for audit in track["title_audit"] for reason in audit["safeguards"])
        if reasons:
            lines.append(f"- {track['title']} · {track['artist']}：" + "；".join(dict.fromkeys(reasons)))
    lines.extend(["", "## 数据边界", "", "- 同一 QQ MID 合并扫描，原始重复记录保留在 JSON 中；不去重或改写主数据。", "- 所有候选 review_status=pending，auto_lock_allowed=false；后续人工确认不应直接编辑扫描产物。", "- 标题日期保留年份，年度复现未配置；标题日期不是发行日期。", "- 不从月份推季节、从雪推圣诞、从月亮推满月、从雨推悲伤。", "- JSON 保存全部歌曲及无命中审计；CSV 一行一条候选关联。", "- 日期解析覆盖英语月份日期、Avril 日期与常见中文／日文月份词；没有承诺所有语言日期覆盖。", ""])
    lines.extend(["- 门店：深圳景田，东经 114.04°、北纬 22.56°，Asia/Shanghai，08:00–18:00。", "- 日出为开店意象；傍晚天光仍需运行时核对与营业时间的交集。", "- source_associations 保留合并前词义与判断，scoring_groups 标明共享依据；关联条数不等于独立加分次数。", "- 咖啡／茶仅为手动主题；未实现天气采集、运行时匹配、排名加分或自动锁曲。", ""])
    return "\n".join(lines)


def html_report(scan):
    groups = []
    for key, stats in scan["summary"]["categories"].items():
        rows = []
        for track, item in category_rows(scan, key):
            terms = " / ".join(dict.fromkeys(e["matched_text"] for e in item["evidence"]))
            searchable = " ".join([track["title"], track["artist"], item["label"], item["reason"], terms]).casefold()
            e = html.escape
            rows.append(f'<tr data-kind="{item["title_judgment"]}" data-search="{e(searchable, quote=True)}"><td><b>{e(track["title"])}</b><small>{e(track["track_id"])}</small></td><td>{e(track["artist"])}</td><td>{e(item["label"])}</td><td><span class="badge {item["title_judgment"]}">{e(item["judgment_label"])}</span></td><td>{e(terms)}</td><td>{e(item["reason"])}</td></tr>')
        body = "".join(rows) or '<tr class="empty"><td colspan="6">标题扫描未发现候选，不代表歌词或作品背景没有这类关联。</td></tr>'
        groups.append(f'<section class="category" data-category="{key}"><header><h2>{html.escape(stats["label"])}</h2><span>{stats["tracks"]} 首 / {stats["associations"]} 条关联</span></header><div class="table-scroll"><table><thead><tr><th>歌曲</th><th>艺人</th><th>情境</th><th>标题判断</th><th>命中依据</th><th>判断理由</th></tr></thead><tbody>{body}</tbody></table></div></section>')
    audit_rows = []
    for track in scan["tracks"].values():
        reasons = [a["exclusion_reason"] for a in track["excluded_associations"]]
        reasons.extend(r for a in track["title_audit"] for r in a["safeguards"])
        if reasons:
            audit_rows.append('<li><b>' + html.escape(track["title"] + " · " + track["artist"]) + '</b><p>' + html.escape("；".join(dict.fromkeys(reasons))) + '</p></li>')
    template = (BASE / "title_context_report_template.html").read_text(encoding="utf-8")
    values = {"@@GROUPS@@": "".join(groups), "@@AUDIT@@": "".join(audit_rows), "@@TOTAL@@": str(scan["summary"]["unique_tracks_scanned"]), "@@TRACKS@@": str(scan["summary"]["tracks_with_candidates"]), "@@ASSOCIATIONS@@": str(scan["summary"]["total_associations"]), "@@EXPLICIT@@": str(scan["summary"]["tracks_with_explicit_candidates"]), "@@VERSION@@": html.escape(scan["rule_version"]), "@@GENERATED@@": html.escape(scan["generated_at"])}
    values["@@CATEGORY_OPTIONS@@"] = "".join('<option value="' + html.escape(key, quote=True) + '">' + html.escape(stats["label"]) + '</option>' for key, stats in scan["summary"]["categories"].items())
    for token, value in values.items():
        template = template.replace(token, value)
    return template


def write_outputs(scan, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "title_context_candidates.json"
    json_path.write_text(json.dumps(scan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = ["track_id", "title", "artist", "category", "tag", "label", "title_judgment", "review_status", "auto_lock_allowed", "matched_text", "reason", "trigger_hint_json"]
    with (output_dir / "title_context_candidates.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for track in scan["tracks"].values():
            for item in track["associations"]:
                row = {k: item[k] for k in ["category", "tag", "label", "title_judgment", "review_status", "auto_lock_allowed", "reason"]}
                row.update({k: track[k] for k in ["track_id", "title", "artist"]})
                row["matched_text"] = " / ".join(dict.fromkeys(e["matched_text"] for e in item["evidence"]))
                row["trigger_hint_json"] = json.dumps(item["trigger_hint"], ensure_ascii=False)
                writer.writerow(row)
    (output_dir / "title_context_report.md").write_text(markdown_report(scan), encoding="utf-8")
    (output_dir / "title_context_report.html").write_text(html_report(scan), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, default=SONGBASE / "song_base_by_artist.json")
    parser.add_argument("--output-dir", type=Path, default=BASE / "scans" / date.today().isoformat())
    parser.add_argument("--dry-run", action="store_true", help="只打印统计，不写候选与报告")
    args = parser.parse_args()
    protected = [SONGBASE / name for name in ["song_base_by_artist.json", "song_tags.json", "song_tag_candidates.json", "song_tag_mapping.json"]]
    protected += [REPO / "cafe-playlist" / "data" / name for name in ["albums.json", "play_history.json"]]
    before = {str(path): digest(path) for path in protected if path.exists()}
    config = load_json(BASE / "title_context_rules.json")
    reviews = load_json(BASE / "title_context_semantic_reviews.json")
    scan = build_scan(args.library, config, reviews)
    after = {str(path): digest(path) for path in protected if path.exists()}
    if before != after:
        raise RuntimeError("正式源数据在扫描期间发生变化，停止输出。")
    scan["source_integrity"] = {"protected_files_unchanged": True, "protected_file_count": len(before)}
    if not args.dry_run:
        write_outputs(scan, args.output_dir.resolve())
    print(json.dumps({"summary": scan["summary"], "source_integrity": scan["source_integrity"], "output_dir": None if args.dry_run else str(args.output_dir.resolve())}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
