#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Merge SongBase metadata and sparse song tags into an offline HTML browser."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path


BASE = Path(__file__).resolve().parent
SONGS_PATH = BASE / "song_base_by_artist.json"
TAGS_PATH = BASE / "song_tags.json"
CANDIDATES_PATH = BASE / "song_tag_candidates.json"
RESOURCES_DIR = BASE / "SongResources"
OUTPUT_PATH = BASE / "song_tags_browser.html"
DISCARDED_PATH = BASE / "archive" / "removed_tracks" / "discarded_tracks.json"

QQ_MID_RE = re.compile(r"/songDetail/([A-Za-z0-9]+)")
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav"}


def track_id(song: dict) -> str:
    match = QQ_MID_RE.search(song.get("qq_music", ""))
    if not match:
        raise ValueError(f"歌曲缺少可识别的 QQ Music MID: {song.get('title', '未知歌曲')}")
    return f"qq:{match.group(1)}"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def clean_filename(value: str) -> str:
    value = unicodedata.normalize("NFC", str(value or ""))
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", value)
    return re.sub(r"\s+", " ", value).strip(" .") or "未命名"


def normalized_stem(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return "".join(char for char in value if char.isalnum())


def artist_variants(group_artist: str, full_singer: str) -> list[str]:
    values: list[str] = []
    for artist in (group_artist, full_singer):
        artist = str(artist or "").strip()
        if not artist:
            continue
        values.append(artist)
        for separator in (",", "，", "&", "、"):
            primary = artist.split(separator, 1)[0].strip()
            if primary:
                values.append(primary)
    return list(dict.fromkeys(values))


def build_audio_index(resources_dir: Path) -> tuple[dict[str, Path], dict[str, Path], int]:
    exact: dict[str, Path] = {}
    compact: dict[str, Path] = {}
    count = 0
    if not resources_dir.exists():
        return exact, compact, count
    for path in resources_dir.iterdir():
        if not path.is_file() or path.suffix.casefold() not in AUDIO_EXTENSIONS:
            continue
        if path.stat().st_size <= 0:
            continue
        count += 1
        exact.setdefault(unicodedata.normalize("NFC", path.stem).casefold(), path)
        compact.setdefault(normalized_stem(path.stem), path)
    return exact, compact, count


def find_local_audio(
    title: str,
    group_artist: str,
    full_singer: str,
    exact_audio: dict[str, Path],
    compact_audio: dict[str, Path],
) -> str | None:
    for artist in artist_variants(group_artist, full_singer):
        stem = f"{clean_filename(title)} - {clean_filename(artist)}"
        path = exact_audio.get(unicodedata.normalize("NFC", stem).casefold())
        if path is None:
            path = compact_audio.get(normalized_stem(stem))
        if path is not None:
            return path.resolve().as_uri()
    return None


def validate_tags(tags: dict, valid_ids: set[str]) -> list[str]:
    errors: list[str] = []
    taxonomy = tags.get("taxonomy", {})
    genres = set(taxonomy.get("genres", []))
    languages = set(taxonomy.get("languages", []))

    if tags.get("schema_version") != "songbase.tags/v1":
        errors.append("schema_version 必须为 songbase.tags/v1")

    for key, value in tags.get("tracks", {}).items():
        if key not in valid_ids:
            errors.append(f"标签记录在 SongBase 中不存在: {key}")
        if value.get("genre") not in genres:
            errors.append(f"{key} 的 genre 无效: {value.get('genre')!r}")
        secondary_genres = value.get("secondary_genres", [])
        if not isinstance(secondary_genres, list):
            errors.append(f"{key} 的 secondary_genres 必须是列表")
        elif len(secondary_genres) > 2:
            errors.append(f"{key} 的 secondary_genres 最多只能有两个")
        elif len(secondary_genres) != len(set(secondary_genres)):
            errors.append(f"{key} 的 secondary_genres 不可重复")
        elif value.get("genre") in secondary_genres:
            errors.append(f"{key} 的副风格不可与主风格相同")
        elif not set(secondary_genres) <= genres:
            errors.append(f"{key} 的 secondary_genres 含有无效风格: {secondary_genres!r}")
        language = value.get("language")
        if language is not None and language not in languages:
            errors.append(f"{key} 的 language 无效: {language!r}")
        instrumental = value.get("instrumental")
        if instrumental is not None and not isinstance(instrumental, bool):
            errors.append(f"{key} 的 instrumental 必须是 true、false 或 null")
    return errors


def build_payload(library: dict, tags: dict, candidates: dict | None) -> dict:
    by_id: dict[str, dict] = {}
    duplicate_count = 0
    exact_audio, compact_audio, local_audio_files = build_audio_index(RESOURCES_DIR)
    for singer in library.get("singers", []):
        for song in singer.get("songs", []):
            key = track_id(song)
            if key in by_id:
                duplicate_count += 1
                continue
            by_id[key] = {
                "id": key,
                "title": song.get("title", ""),
                "artist": singer.get("name", ""),
                "full_singer": song.get("full_singer", ""),
                "album": song.get("album", ""),
                "duration": song.get("duration", 0),
                "qq_music": song.get("qq_music", ""),
                "youtube": song.get("youtube", ""),
                "bilibili": song.get("bilibili", ""),
                "audio_url": find_local_audio(
                    song.get("title", ""),
                    singer.get("name", ""),
                    song.get("full_singer", ""),
                    exact_audio,
                    compact_audio,
                ),
                "tags": tags.get("tracks", {}).get(key),
                "candidate": None,
            }

    errors = validate_tags(tags, set(by_id))
    if errors:
        raise ValueError("song_tags.json 校验失败:\n- " + "\n- ".join(errors))

    candidate_tracks = (candidates or {}).get("tracks", {})
    for key, record in candidate_tracks.items():
        if key not in by_id:
            continue
        by_id[key]["candidate"] = {
            "genre": record.get("genre_candidate"),
            "secondary_genres": record.get("secondary_genre_candidates", []),
            "confidence": record.get("confidence"),
            "status": record.get("status", "candidate"),
            "confidence_details": record.get("confidence_details"),
            "instrumental": record.get("instrumental_candidate"),
            "matched_tags": record.get("matched_tags", []),
            "review_policy": record.get("artist_review_policy"),
            "evidence": record.get("evidence", []),
            "errors": record.get("errors", []),
        }

    songs = list(by_id.values())
    return {
        "library_date": library.get("export_date"),
        "tags_updated_at": tags.get("updated_at"),
        "taxonomy_version": tags.get("taxonomy_version"),
        "taxonomy": tags.get("taxonomy", {}),
        "duplicate_song_records": duplicate_count,
        "audio": {
            "local_files": local_audio_files,
            "mapped_tracks": sum(song["audio_url"] is not None for song in songs),
        },
        "candidates": {
            "available": bool(candidates),
            "generated_at": (candidates or {}).get("generated_at"),
            "mapping_version": (candidates or {}).get("mapping_version"),
            "sample": (candidates or {}).get("sample", {}),
        },
        "songs": songs,
    }


TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>SongBase 标签浏览器</title>
  <style>
    :root{--bg:#0e1412;--panel:#17201d;--panel2:#1d2925;--line:#304039;--text:#edf3ee;--muted:#9aaca3;--accent:#c9dd87;--accentInk:#18210d;--warm:#e9b88c;--radius:15px}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}button,input,select{font:inherit}button,select{cursor:pointer}a{color:inherit}.shell{width:min(1440px,calc(100% - 32px));margin:auto;padding:30px 0 50px}.eyebrow{margin:0 0 7px;color:var(--accent);font-size:12px;letter-spacing:.13em;text-transform:uppercase}h1{margin:0;font-size:clamp(28px,4vw,42px);letter-spacing:-.035em}.subhead{margin:7px 0 24px;color:var(--muted)}
    .metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-bottom:18px}.metric{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:14px 16px}.metric strong{display:block;font-size:23px}.metric span{color:var(--muted);font-size:13px}.coverage{height:8px;background:var(--panel2);border-radius:99px;overflow:hidden;margin-top:8px}.coverage i{display:block;height:100%;background:var(--accent)}
    .overview{display:grid;grid-template-columns:1.5fr 1fr;gap:10px;margin-bottom:18px}.chart,.taxonomy{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:15px}.chart h2,.taxonomy h2{font-size:14px;margin:0 0 11px}.genre-row{display:grid;grid-template-columns:minmax(150px,1fr) 3fr;gap:10px;align-items:center;margin:10px 0}.genre-name{color:var(--muted);font-size:12px}.genre-bars{display:grid;gap:5px}.genre-barline{display:grid;grid-template-columns:22px minmax(80px,1fr) 36px;gap:7px;align-items:center}.genre-barline>span,.genre-barline>b{color:var(--muted);font-size:11px;font-weight:500}.genre-barline>b{text-align:right}.bar{height:8px;background:var(--panel2);border-radius:99px;overflow:hidden}.bar i{display:block;height:100%;background:var(--accent);border-radius:99px}.bar.secondary i{background:#9fc8dc}.chips{display:flex;flex-wrap:wrap;gap:6px}.chip{border:1px solid var(--line);border-radius:999px;padding:3px 8px;font-size:12px;color:var(--muted)}
    .view-tabs{display:flex;gap:8px;margin:0 0 18px}.tab{text-decoration:none;color:var(--muted);background:transparent;border:1px solid var(--line);border-radius:999px;padding:8px 13px}.tab[aria-selected="true"]{color:var(--accentInk);background:var(--accent);border-color:var(--accent);font-weight:700}.view-panel[hidden]{display:none}.toolbar{display:grid;grid-template-columns:minmax(230px,2fr) repeat(5,minmax(120px,1fr)) auto;gap:9px;padding:13px;background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);margin-bottom:14px}input,select,textarea{width:100%;color:var(--text);background:var(--panel2);border:1px solid var(--line);border-radius:9px;padding:9px 11px;outline:none}textarea{resize:vertical;min-height:58px}input:focus,select:focus,textarea:focus{border-color:var(--accent)}.button{color:var(--muted);background:transparent;border:1px solid var(--line);border-radius:9px;padding:9px 12px}.button:hover{border-color:var(--muted);color:var(--text)}.button:disabled{cursor:not-allowed;opacity:.48}.button.primary{color:var(--accentInk);background:var(--accent);border-color:var(--accent);font-weight:700}.export-toggle{font-size:12px;padding:6px 8px}.export-toggle.selected{color:var(--accentInk);background:var(--accent);border-color:var(--accent);font-weight:700}.commit{font-size:12px;padding:6px 8px}.commit.ready{color:var(--accentInk);background:var(--accent);border-color:var(--accent);font-weight:700}.play{color:var(--accent);border-color:rgba(201,221,135,.5);padding:5px 8px;font-size:12px;white-space:nowrap}.play.active{background:var(--accent);border-color:var(--accent);color:var(--accentInk);font-weight:700}.resultbar{display:flex;justify-content:space-between;align-items:center;color:var(--muted);margin:0 2px 10px}.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:var(--radius)}table{width:100%;border-collapse:collapse;background:var(--panel)}th,td{text-align:left;padding:10px 12px;border-bottom:1px solid rgba(48,64,57,.75);vertical-align:top}th{position:sticky;top:0;background:var(--panel2);color:var(--muted);font-size:12px;font-weight:600}tr:last-child td{border:0}.song{font-weight:600}.meta{color:var(--muted);font-size:12px}.tag{display:inline-block;margin:1px 4px 1px 0;padding:2px 7px;border-radius:999px;border:1px solid rgba(201,221,135,.38);color:var(--accent);font-size:12px;white-space:nowrap}.tag.secondary{color:#9fc8dc;border-color:rgba(159,200,220,.42)}.tag.language{color:var(--warm);border-color:rgba(233,184,140,.38)}.untagged{color:var(--muted)}.link{text-decoration:none;color:var(--muted);border:1px solid var(--line);border-radius:7px;padding:3px 6px;font-size:12px;white-space:nowrap}.empty{text-align:center;color:var(--muted);padding:46px}.footer{color:var(--muted);font-size:12px;margin-top:18px}.review-intro{display:flex;align-items:start;justify-content:space-between;gap:18px;background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:16px;margin-bottom:12px}.review-intro h2{font-size:18px;margin:0 0 5px}.review-intro p{max-width:720px;color:var(--muted);margin:0;font-size:13px}.review-actions{display:flex;flex-wrap:wrap;gap:8px;justify-content:end}.formal-file-state{flex-basis:100%;color:var(--muted);font-size:11px;text-align:right}.formal-file-state.ready{color:var(--accent)}.review-toolbar{display:grid;grid-template-columns:minmax(230px,2fr) repeat(2,minmax(160px,1fr));gap:9px;padding:13px;background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);margin-bottom:14px}.confidence-filter{display:grid;gap:4px;color:var(--muted);font-size:12px}.confidence-filter span{display:flex;justify-content:space-between;gap:8px}.confidence-filter strong{color:var(--accent)}.confidence-filter input[type="range"]{accent-color:var(--accent);background:transparent;border:0;padding:0;height:22px}.confidence-filter small{font-size:11px}.review-list{display:grid;gap:11px}.review-card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:14px}.review-head{display:flex;gap:16px;justify-content:space-between;align-items:start;margin-bottom:12px}.review-head h3{margin:0;font-size:16px}.candidate{color:var(--accent);font-size:13px;font-weight:600}.signals{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}.signal{border:1px solid var(--line);border-radius:999px;padding:2px 7px;color:var(--muted);font-size:11px}.signal.policy{color:var(--accent);border-color:rgba(201,221,135,.38)}.signal.warning{color:var(--warm);border-color:rgba(233,184,140,.55)}.confidence-details{margin:0 0 13px;border:1px solid var(--line);border-radius:10px;background:var(--panel2)}.confidence-details summary{cursor:pointer;padding:9px 11px;color:var(--accent);font-size:12px;font-weight:600}.confidence-body{padding:0 11px 11px}.confidence-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px}.confidence-cell{padding:8px;background:rgba(14,20,18,.42);border:1px solid rgba(48,64,57,.8);border-radius:8px}.confidence-cell b{display:block;color:var(--text);font-size:13px}.confidence-cell span{display:block;color:var(--muted);font-size:11px}.confidence-rules{margin-top:9px}.confidence-rules strong{font-size:12px}.confidence-rule{margin-top:4px;color:var(--muted);font-size:11px}.confidence-note{margin:8px 0 0;color:var(--muted);font-size:11px}.secondary-candidates{display:grid;gap:7px;margin:0 0 13px}.secondary-candidate{padding:10px 11px;border:1px solid rgba(159,200,220,.38);border-radius:10px;background:rgba(159,200,220,.06)}.secondary-candidate-head{display:flex;justify-content:space-between;gap:12px;color:#9fc8dc;font-size:12px;font-weight:700}.secondary-candidate-meta{margin-top:3px;color:var(--muted);font-size:11px}.secondary-candidate-rules{display:flex;flex-wrap:wrap;gap:5px;margin-top:7px}.review-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}.review-grid .field label{display:block;color:var(--muted);font-size:12px;margin:0 0 4px}.review-grid .full{grid-column:1/-1}.secondary-options{display:flex;flex-wrap:wrap;gap:7px}.secondary-option{display:flex!important;align-items:center;gap:5px;margin:0!important;padding:6px 9px;border:1px solid var(--line);border-radius:999px;color:var(--text)!important}.secondary-option input{width:auto;accent-color:var(--accent);padding:0}.secondary-option.disabled{opacity:.45}.review-status{font-size:12px;color:var(--muted);margin-top:9px}.player{position:fixed;z-index:20;left:50%;bottom:18px;width:min(720px,calc(100% - 24px));transform:translateX(-50%);display:grid;grid-template-columns:auto minmax(140px,1fr) 72px auto;gap:10px;align-items:center;padding:10px 12px;background:rgba(23,32,29,.97);border:1px solid var(--line);border-radius:14px;box-shadow:0 12px 35px rgba(0,0,0,.35)}.player[hidden]{display:none}.player-title{min-width:0}.player-title strong,.player-title span{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.player-title span{color:var(--muted);font-size:12px}.player-progress{accent-color:var(--accent);padding:0}.player-time{color:var(--muted);font-size:12px;white-space:nowrap}.toast{position:fixed;z-index:30;right:20px;bottom:20px;max-width:min(440px,calc(100% - 40px));padding:11px 14px;background:var(--panel2);border:1px solid var(--line);border-radius:10px;box-shadow:0 10px 35px rgba(0,0,0,.25);opacity:0;transform:translateY(8px);pointer-events:none;transition:.18s}.toast.show{opacity:1;transform:translateY(0)}.toast.error{color:var(--warm);border-color:var(--warm)}
    @media(max-width:900px){.metrics{grid-template-columns:repeat(2,1fr)}.overview{grid-template-columns:1fr}.toolbar{grid-template-columns:1fr 1fr}.toolbar input{grid-column:1/-1}.toolbar .button{grid-column:1/-1}.review-grid,.confidence-grid{grid-template-columns:1fr 1fr}.review-intro{display:block}.review-actions{justify-content:start;margin-top:12px}}@media(max-width:620px){.shell{width:calc(100% - 20px);padding-top:20px}.genre-row{grid-template-columns:1fr}.genre-bars{margin-left:4px}th:nth-child(3),td:nth-child(3){display:none}.review-grid,.review-toolbar,.confidence-grid{grid-template-columns:1fr}.review-head{display:block}.candidate{margin-top:4px}.player{grid-template-columns:auto minmax(100px,1fr) auto}.player-progress{grid-column:1/-1;grid-row:2}}
  </style>
</head>
<body>
  <main class="shell">
    <p class="eyebrow">SongBase taxonomy</p>
    <h1>歌曲标签浏览器</h1>
    <p class="subhead" id="subhead"></p>
    <nav class="view-tabs" aria-label="标签浏览器页面">
      <button class="tab" id="browseTab" type="button" aria-selected="true">标签浏览</button>
      <button class="tab" id="reviewTab" type="button" aria-selected="false">候选纠错 <span id="candidateCount"></span></button>
      <a class="tab" href="song_manual_tagging.html">无候选手动标注 <span id="manualCount"></span></a>
    </nav>
    <section class="view-panel" id="browseView">
    <section class="metrics" aria-label="标签进度">
      <div class="metric"><strong id="total">—</strong><span>曲库歌曲</span></div>
      <div class="metric"><strong id="tagged">—</strong><span>已标注</span></div>
      <div class="metric"><strong id="untagged">—</strong><span>待标注</span></div>
      <div class="metric"><strong id="rate">—</strong><span>完成率</span><div class="coverage"><i id="coverage"></i></div></div>
    </section>
    <section class="overview">
      <div class="chart"><h2>风格覆盖（主 Tag / 副 Tag）</h2><div id="genreChart"></div></div>
      <div class="taxonomy"><h2>当前标签体系</h2><div class="chips" id="taxonomy"></div></div>
    </section>
    <section class="toolbar" aria-label="筛选标签">
      <input id="search" type="search" placeholder="搜索歌曲、艺人或专辑…">
      <select id="status"><option value="all">全部进度</option><option value="tagged">已标注</option><option value="untagged">待标注</option></select>
      <select id="genre"><option value="all">全部风格</option></select>
      <select id="genreScope"><option value="any">主或副风格</option><option value="primary">仅主风格</option></select>
      <select id="language"><option value="all">全部语言</option><option value="default">中文 / 英文默认</option></select>
      <select id="form"><option value="all">全部形式</option><option value="instrumental">Instrumental</option><option value="vocal">非器乐</option></select>
      <button class="button" id="clear" type="button">清除筛选</button>
    </section>
    <div class="resultbar"><span id="resultCount"></span><span id="activeFilters"></span></div>
    <section id="results" aria-live="polite"></section>
    <p class="footer">标签来自 song_tags.json；歌曲信息来自 song_base_by_artist.json。修改 JSON 后重新运行构建程序即可刷新。</p>
    </section>
    <section class="view-panel" id="reviewView" hidden>
      <section class="review-intro">
        <div>
          <h2>候选纠错工作台</h2>
          <p>逐首确认或修正主风格与最多两个副风格，也可补充语言、器乐性和“映射规则是否可靠”的反馈。连接正式标签文件后，可将一首已确认的当前结果直接写入正式标签；导出纠错仍适合需要批量复盘或规则反馈的曲目。</p>
        </div>
        <div class="review-actions">
          <button class="button primary" id="connectFormalFile" type="button">连接正式 song_tags.json</button>
          <button class="button" id="downloadFormalBackup" type="button" disabled>下载正式标签副本</button>
          <button class="button primary" id="exportFormalUpdates" type="button" disabled>导出待正式更新</button>
          <button class="button primary" id="exportCorrections" type="button">导出选中纠错 JSON</button>
          <button class="button" id="clearCorrections" type="button">清空本机纠错</button>
          <span class="formal-file-state" id="formalFileState">未连接正式标签文件；单曲入库按钮暂不可用。</span>
          <input id="formalFileInput" type="file" accept="application/json,.json" hidden>
        </div>
      </section>
      <section class="review-toolbar" aria-label="筛选候选纠错">
        <input id="reviewSearch" type="search" placeholder="搜索候选歌曲、艺人或专辑…">
        <label class="confidence-filter" for="reviewConfidence"><span>置信度阈值 <strong id="reviewConfidenceValue">≥ 65%</strong></span><input id="reviewConfidence" type="range" min="0" max="100" step="5" value="65" list="reviewConfidenceTicks"><small>0%=全部；可设 55 / 65 / 75 / 85 / 95%</small></label><datalist id="reviewConfidenceTicks"><option value="0"></option><option value="55"></option><option value="65"></option><option value="75"></option><option value="85"></option><option value="95"></option></datalist>
        <select id="reviewStatus"><option value="all">全部复核状态</option><option value="pending">未复核</option><option value="reviewed">已记录反馈</option></select>
      </section>
      <div class="resultbar"><span id="reviewCount"></span><span id="reviewProgress"></span></div>
      <section class="review-list" id="reviewResults" aria-live="polite"></section>
      <p class="footer">“确认并入库”会尝试写入当前连接的 <code>song_tags.json</code>。若浏览器不允许原位写入，曲目会先暂存到本次会话，最后在顶部一次性导出合并后的完整 JSON 供手动替换。页面当前会立即反映变更；重新打开页面前仍需重新构建本 HTML，才能嵌入新正式标签。</p>
    </section>
  </main>
  <div class="toast" id="toast" role="status"></div>
  <section class="player" id="player" hidden aria-label="正在播放">
    <button class="button play" id="playerToggle" type="button" aria-label="暂停或继续播放">▶</button>
    <div class="player-title"><strong id="playerTitle">—</strong><span id="playerArtist">—</span></div>
    <input class="player-progress" id="playerProgress" type="range" min="0" max="100" value="0" aria-label="播放进度">
    <span class="player-time" id="playerTime">0:00 / 0:00</span>
  </section>
  <script>
    const DATA=__PAYLOAD__;
    const $=id=>document.getElementById(id);
    const browseState={search:'',status:'all',genre:'all',genreScope:'any',language:'all',form:'all'};
    const reviewState={search:'',minimum:0.65,status:'all'};
    const REVIEW_STORAGE_KEY='songbase.tag-corrections.v1';
    const FORMAL_SCHEMA='songbase.tags/v1';
    let reviews=loadReviews();
    const formalState={data:null,fileHandle:null,fileName:'',stagedCount:0};
    const esc=value=>String(value??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
    const duration=seconds=>`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;
    const audio=new Audio();
    audio.preload='metadata';
    let activeSongId=null;
    const today=()=>new Date().toISOString().slice(0,10);
    const option=(value,label,selected)=>`<option value="${esc(value)}"${value===selected?' selected':''}>${esc(label)}</option>`;
    function toast(message,error=false){const node=$('toast');node.textContent=message;node.className=`toast show${error?' error':''}`;clearTimeout(toast.timer);toast.timer=setTimeout(()=>node.className='toast',3600)}
    function sameList(left,right){return Array.isArray(left)&&Array.isArray(right)&&left.length===right.length&&left.every((value,index)=>value===right[index])}
    function validateFormalTags(data){if(!data||data.schema_version!==FORMAL_SCHEMA)throw new Error('请选择 schema_version 为 songbase.tags/v1 的正式标签 JSON。');if(!data.taxonomy||!sameList(data.taxonomy.genres,DATA.taxonomy.genres)||!sameList(data.taxonomy.languages,DATA.taxonomy.languages)||!sameList(data.taxonomy.forms,DATA.taxonomy.forms))throw new Error('正式标签文件的标签体系与当前 SongBase 页面不一致。');if(!data.tracks||Array.isArray(data.tracks)||typeof data.tracks!=='object')throw new Error('正式标签 JSON 缺少 tracks 对象。');for(const [id,tags] of Object.entries(data.tracks)){const secondary=tags.secondary_genres??[];if(!Array.isArray(secondary)||secondary.length>2||new Set(secondary).size!==secondary.length||secondary.includes(tags.genre)||secondary.some(genre=>!DATA.taxonomy.genres.includes(genre)))throw new Error(`${id} 的 secondary_genres 无效：最多两个、不可重复或与主风格相同。`)}}
    function formalWriteAvailable(){return Boolean(formalState.data&&formalState.fileHandle)}
    function updateFormalFileState(){const state=$('formalFileState'),backup=$('downloadFormalBackup'),exportUpdates=$('exportFormalUpdates');backup.disabled=!formalState.data;exportUpdates.disabled=!formalState.data||formalState.stagedCount===0;exportUpdates.textContent=formalState.stagedCount?`导出 ${formalState.stagedCount} 条待正式更新`:'导出待正式更新';if(!formalState.data){state.textContent='未连接正式标签文件；单曲入库按钮暂不可用。';state.className='formal-file-state';return}if(formalState.stagedCount){state.textContent=`已暂存 ${formalState.stagedCount} 条正式更新；继续确认其他曲目，最后一次性导出并替换 ${formalState.fileName}。`;state.className='formal-file-state ready';return}if(formalState.fileHandle){state.textContent=`已连接 ${formalState.fileName}；将尝试直接写入正式标签。`;state.className='formal-file-state ready';return}state.textContent=`已载入 ${formalState.fileName}；当前浏览器只能暂存更新，最后一次性下载完整副本。`;state.className='formal-file-state'}
    function downloadFormalData(filename=`song_tags_${today()}.json`){if(!formalState.data)return;const url=URL.createObjectURL(new Blob([JSON.stringify(formalState.data,null,2)+'\n'],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
    function syncFormalTags(){if(!formalState.data)return;DATA.tags_updated_at=formalState.data.updated_at||DATA.tags_updated_at;DATA.songs.forEach(song=>{song.tags=formalState.data.tracks[song.id]||null});$('candidateCount').textContent=`(${candidateSongs().length})`;renderSummary();renderBrowse();renderReview()}
    async function loadFormalFile(file,handle=null){const data=JSON.parse(await file.text());validateFormalTags(data);formalState.data=data;formalState.fileHandle=handle;formalState.fileName=file.name||'song_tags.json';formalState.stagedCount=0;updateFormalFileState();syncFormalTags();toast(handle?'已连接正式标签文件，可直接入库。':'已载入正式标签文件；确认曲目会先暂存，最后统一导出。',false)}
    async function connectFormalFile(){if('showOpenFilePicker' in window){try{const [handle]=await window.showOpenFilePicker({multiple:false,types:[{description:'SongBase 正式标签 JSON',accept:{'application/json':['.json']}}]});await loadFormalFile(await handle.getFile(),handle);return}catch(error){if(error?.name==='AbortError')return;toast('浏览器无法取得原位写入权限，已切换到普通文件选择。',false)}}$('formalFileInput').click()}
    async function persistFormalData(){if(!formalState.data)throw new Error('请先连接正式 song_tags.json。');if(!formalState.fileHandle)return 'staged';try{const writable=await formalState.fileHandle.createWritable();await writable.write(JSON.stringify(formalState.data,null,2)+'\n');await writable.close();return 'written'}catch(error){formalState.fileHandle=null;updateFormalFileState();return 'staged'}}
    function activeSong(){return DATA.songs.find(song=>song.id===activeSongId)||null}
    function playButton(song){const isActive=song.id===activeSongId;const isPlaying=isActive&&!audio.paused;const label=song.audio_url?(isPlaying?'Ⅱ 暂停':isActive?'▶ 继续':'▶ 播放'):'↗ 外部播放';return `<button class="button play${isPlaying?' active':''}" type="button" data-play-id="${esc(song.id)}">${label}</button>`}
    function displayTime(value){return Number.isFinite(value)&&value>0?duration(Math.floor(value)):'0:00'}
    function refreshPlayer(){const song=activeSong();if(!song)return;$('player').hidden=false;$('playerTitle').textContent=song.title;$('playerArtist').textContent=song.artist;$('playerToggle').textContent=audio.paused?'▶':'Ⅱ';$('playerToggle').classList.toggle('active',!audio.paused);const total=Number.isFinite(audio.duration)?audio.duration:0;$('playerProgress').value=total?String(audio.currentTime/total*100):'0';$('playerTime').textContent=`${displayTime(audio.currentTime)} / ${displayTime(total)}`;document.querySelectorAll('[data-play-id]').forEach(button=>{const target=DATA.songs.find(song=>song.id===button.dataset.playId);if(!target)return;const active=target.id===activeSongId&&!audio.paused;button.textContent=target.audio_url?(active?'Ⅱ 暂停':target.id===activeSongId?'▶ 继续':'▶ 播放'):'↗ 外部播放';button.classList.toggle('active',active)})}
    function wirePlayButtons(root){root.querySelectorAll('[data-play-id]').forEach(button=>button.addEventListener('click',()=>playSong(button.dataset.playId)))}
    function playSong(id){const song=DATA.songs.find(item=>item.id===id);if(!song)return;if(!song.audio_url){const external=song.youtube||song.bilibili||song.qq_music;if(!external){toast('这首歌暂时没有可用的本地音频或外部播放链接。',true);return}window.open(external,'_blank','noopener');toast('本地音频未同步，已打开外部播放页。');return}if(activeSongId===id){if(audio.paused)audio.play().catch(()=>toast('无法播放本地音频，请确认浏览器允许访问 SongResources。',true));else audio.pause();refreshPlayer();return}activeSongId=id;audio.src=song.audio_url;audio.currentTime=0;audio.play().catch(()=>toast('无法播放本地音频，请确认浏览器允许访问 SongResources。',true));refreshPlayer()}
    function loadReviews(){try{const stored=JSON.parse(localStorage.getItem(REVIEW_STORAGE_KEY)||'{}');return stored&&typeof stored==='object'?stored:{}}catch(error){return {}}}
    function saveReviews(){try{localStorage.setItem(REVIEW_STORAGE_KEY,JSON.stringify(reviews))}catch(error){toast('浏览器无法长期保存本机纠错；请及时导出 JSON。',true)}}
    function blankReview(){return {decision:'pending',genre_mode:'candidate',secondary_genres:null,language_mode:'unreviewed',instrumental_mode:'unreviewed',mapping_feedback:'unspecified',note:'',export_selected:false}}
    function getReview(id){return {...blankReview(),...(reviews[id]||{})}}
    function isReviewed(review){return review.decision!=='pending'||review.genre_mode!=='candidate'||review.secondary_genres!==null||review.language_mode!=='unreviewed'||review.instrumental_mode!=='unreviewed'||review.mapping_feedback!=='unspecified'||Boolean(review.note?.trim())}
    function candidateSongs(){return DATA.songs.filter(song=>song.candidate?.genre&&!song.tags)}
    function matches(song){const q=browseState.search.trim().toLocaleLowerCase();if(q&&![song.title,song.artist,song.full_singer,song.album].join(' ').toLocaleLowerCase().includes(q))return false;if(browseState.status==='tagged'&&!song.tags)return false;if(browseState.status==='untagged'&&song.tags)return false;if(browseState.genre!=='all'){const primary=song.tags?.genre===browseState.genre,secondary=(song.tags?.secondary_genres||[]).includes(browseState.genre);if(!primary&&(browseState.genreScope==='primary'||!secondary))return false}if(browseState.language==='default'&&(!song.tags||song.tags.language!==null))return false;if(browseState.language!=='all'&&browseState.language!=='default'&&song.tags?.language!==browseState.language)return false;if(browseState.form==='instrumental'&&song.tags?.instrumental!==true)return false;if(browseState.form==='vocal'&&(!song.tags||song.tags.instrumental!==false))return false;return true}
    function renderTags(tags){if(!tags)return '<span class="untagged">待标注</span>';const parts=[`<span class="tag">主 · ${esc(tags.genre)}</span>`,...(tags.secondary_genres||[]).map(genre=>`<span class="tag secondary">副 · ${esc(genre)}</span>`)];if(tags.language)parts.push(`<span class="tag language">${esc(tags.language)}</span>`);if(tags.instrumental)parts.push('<span class="tag">Instrumental</span>');return parts.join('')}
    function renderBrowse(){const songs=DATA.songs.filter(matches);$('resultCount').textContent=`显示 ${songs.length.toLocaleString()} / ${DATA.songs.length.toLocaleString()} 首`;$('activeFilters').textContent=Object.values(browseState).filter(v=>v&&v!=='all').length?'筛选中':'';$('results').innerHTML=songs.length?`<div class="tablewrap"><table><thead><tr><th>歌曲</th><th>艺人</th><th>专辑</th><th>标签</th><th>播放</th><th>来源</th></tr></thead><tbody>${songs.map(song=>`<tr><td><div class="song">${esc(song.title)}</div><div class="meta">${duration(song.duration)} · ${esc(song.id)}</div></td><td>${esc(song.artist)}</td><td>${esc(song.album||'未标注专辑')}</td><td>${renderTags(song.tags)}</td><td>${playButton(song)}</td><td><a class="link" href="${esc(song.qq_music)}" target="_blank" rel="noopener">QQ</a>${song.youtube?` <a class="link" href="${esc(song.youtube)}" target="_blank" rel="noopener">YT</a>`:''}</td></tr>`).join('')}</tbody></table></div>`:'<div class="empty">没有符合条件的歌曲。</div>';wirePlayButtons($('results'))}
    function candidateSignal(candidate){const matched=candidate.matched_tags||[],policy=candidate.review_policy;const signals=matched.slice(0,4).map(match=>`<span class="signal">${esc(match.tag)} → ${esc(match.genre)} · ${esc(match.rule_id)}</span>`);if(policy?.disposition==='boundary_accepted')signals.push(`<span class="signal policy">艺人边界可接受：${esc((policy.accepted_genres||[]).join(' / '))}</span>`);if(policy?.disposition==='accepted')signals.push(`<span class="signal policy">艺人规则认可：${esc((policy.accepted_genres||[]).join(' / '))}</span>`);if(policy?.disposition==='deferred')signals.push(`<span class="signal warning">艺人规则暂缓：${esc(candidate.genre)} 不可接受，需复核</span>`);return signals.join('')||'<span class="signal">没有命中映射规则</span>'}
    function candidateForm(candidate){if(candidate.instrumental===true)return '候选：Instrumental';if(candidate.instrumental===false)return '候选：非器乐';return '器乐性未判定'}
    function score(value){const number=Number(value);return Number.isFinite(number)?number.toFixed(2):'—'}
    function confidenceDetails(candidate){const details=candidate.confidence_details;if(!details)return '<details class="confidence-details"><summary>置信细节暂不可用</summary><div class="confidence-body"><p class="confidence-note">请用当前候选脚本重新计算已有候选。</p></div></details>';const winner=details.winner||{},runner=details.runner_up,components=details.components||{},cap=details.source_cap||{},sources=(details.input_sources||[]).map(item=>`${item.source.replace('lastfm_','Last.fm ')} × ${score(item.weight)}`).join('；')||'无';const targetScores=(details.all_target_scores||[]).map(item=>`${item.genre} ${score(item.score)}`).join(' · ')||'无';const winnerRules=(candidate.matched_tags||[]).filter(item=>item.genre===winner.genre);const rules=winnerRules.length?winnerRules.map(item=>`<div class="confidence-rule">${esc(item.tag)} → ${esc(item.genre)} · ${esc(item.rule_id)} · ${esc(item.rule_status||'未标记')} · +${score(item.score)}</div>`).join(''):'<div class="confidence-rule">没有命中该候选的规则</div>';const capText=cap.value===undefined?'—':`${Math.round(Number(cap.value)*100)}% · ${esc(String(cap.basis||'未知').replace('lastfm_','Last.fm '))}${cap.applied?'（已封顶）':'（未触及）'}`;return `<details class="confidence-details"><summary>查看置信细节 · ${Math.round((Number(details.final_confidence)||0)*100)}%</summary><div class="confidence-body"><div class="confidence-grid"><div class="confidence-cell"><span>候选总分</span><b>${esc(winner.genre||'—')} · ${score(winner.score)}</b></div><div class="confidence-cell"><span>第二名 / 竞争分</span><b>${runner?`${esc(runner.genre)} · ${score(runner.score)}`:'无竞争项'}</b></div><div class="confidence-cell"><span>领先度</span><b>${Math.round((Number(details.margin)||0)*100)}%</b></div><div class="confidence-cell"><span>原始证据</span><b>${esc(sources)}</b></div><div class="confidence-cell"><span>来源加分</span><b>${score(components.source_diversity)}（${winner.source_count||0} 类）</b></div><div class="confidence-cell"><span>来源封顶</span><b>${capText}</b></div></div><p class="confidence-note">公式：基础 ${score(components.base)} + 来源 ${score(components.source_diversity)} + 领先 ${score(components.separation)} = 未封顶 ${Math.round((Number(components.uncapped_confidence)||0)*100)}%；最终 ${Math.round((Number(details.final_confidence)||0)*100)}%。</p><p class="confidence-note">各目标累计分：${esc(targetScores)}</p><div class="confidence-rules"><strong>支撑 ${esc(winner.genre||'候选')} 的命中规则</strong>${rules}</div>${(details.notes||[]).map(note=>`<p class="confidence-note">${esc(note)}</p>`).join('')}</div></details>`}
    function secondaryCandidateDetails(candidate){const items=candidate.secondary_genres||[];if(!items.length)return '';return `<section class="secondary-candidates" aria-label="副 Tag 候选详情">${items.map((item,index)=>{const rules=(item.matched_tags||[]).slice(0,4).map(match=>`<span class="signal">${esc(match.tag)} · ${esc(match.source.replace('lastfm_','Last.fm '))} · ${esc(match.rule_id)} · +${score(match.score)}</span>`).join('')||(item.matched_rule_ids||[]).map(rule=>`<span class="signal">${esc(rule)}</span>`).join('')||'<span class="signal">暂无规则明细</span>';return `<div class="secondary-candidate"><div class="secondary-candidate-head"><span>副候选 ${index+1} · ${esc(item.genre)}</span><span>${Math.round((Number(item.confidence)||0)*100)}%</span></div><div class="secondary-candidate-meta">累计分 ${score(item.score)} · 相对主候选 ${Math.round((Number(item.relative_score)||0)*100)}%</div><div class="secondary-candidate-rules">${rules}</div></div>`}).join('')}</section>`}
    function candidateSecondaryGenres(candidate){return (candidate.secondary_genres||[]).map(item=>typeof item==='string'?item:item.genre).filter(genre=>DATA.taxonomy.genres.includes(genre))}
    function resolvedSecondaryGenres(candidate,review,primary){const source=review.secondary_genres===null?candidateSecondaryGenres(candidate):review.secondary_genres;return [...new Set(source||[])].filter(genre=>DATA.taxonomy.genres.includes(genre)&&genre!==primary).slice(0,2)}
    function reviewCard(song){const candidate=song.candidate;const review=getReview(song.id);const resolved=reviewTags(candidate,review);const genreOptions=[option('candidate',`沿用候选：${candidate.genre}`,review.genre_mode),option('none','不写入风格',review.genre_mode),...DATA.taxonomy.genres.map(genre=>option(genre,genre,review.genre_mode))].join('');const secondaryOptions=DATA.taxonomy.genres.map(genre=>{const disabled=genre===resolved.genre.value,checked=resolved.secondary_genres.includes(genre);return `<label class="secondary-option${disabled?' disabled':''}"><input type="checkbox" data-secondary-genre="${esc(genre)}"${checked?' checked':''}${disabled?' disabled':''}>${esc(genre)}</label>`}).join('');const resetSecondary=review.secondary_genres===null?'<span class="meta">当前沿用自动副风格候选</span>':'<button class="button" type="button" data-secondary-reset="true">恢复自动副风格</button>';const languageOptions=[option('unreviewed','尚未判断',review.language_mode),option('default','默认（中文 / 英文）',review.language_mode),...DATA.taxonomy.languages.map(language=>option(language,language,review.language_mode))].join('');const instrumentalOptions=[option('unreviewed','尚未判断',review.instrumental_mode),option('instrumental','Instrumental',review.instrumental_mode),option('vocal','非器乐',review.instrumental_mode)].join('');const feedbackText=isReviewed(review)?'已记录反馈':'尚未记录反馈';const exportText=review.export_selected?'已选择在下次导出':'未选择导出';const exportButton=`<button class="button export-toggle${review.export_selected?' selected':''}" type="button" data-export-toggle="${esc(song.id)}" aria-pressed="${String(Boolean(review.export_selected))}">${review.export_selected?'✓ 已选择导出':'＋ 选择导出'}</button>`;const deferred=candidate.status==='deferred';const canCommit=Boolean(formalState.data&&!deferred&&resolved.genre.value);const commitLabel=!formalState.data?'连接正式文件后可入库':deferred?'暂缓候选不可入库':!resolved.genre.value?'请先选择风格结果':formalWriteAvailable()?'✓ 确认并入库':'＋ 加入待正式导出';const commitButton=`<button class="button commit${canCommit&&formalWriteAvailable()?' ready':''}" type="button" data-commit-id="${esc(song.id)}"${canCommit?'':' disabled'} title="${esc(commitLabel)}">${esc(commitLabel)}</button>`;const deferredText=deferred?' · 暂缓入库':'';const candidateSecondary=(candidate.secondary_genres||[]).map(item=>`${item.genre} ${Math.round((Number(item.confidence)||0)*100)}%`).join('、')||'无';return `<article class="review-card" data-review-id="${esc(song.id)}"><div class="review-head"><div><h3>${esc(song.title)}</h3><div class="meta">${esc(song.artist)} · ${esc(song.album||'未标注专辑')} · ${esc(song.id)}</div><div class="signals">${candidateSignal(candidate)}</div></div><div><div class="candidate">主：${esc(candidate.genre)} · ${(Number(candidate.confidence)||0).toLocaleString(undefined,{style:'percent',maximumFractionDigits:0})}${deferredText}<div class="meta">副候选：${esc(candidateSecondary)} · ${candidateForm(candidate)}</div></div><p>${playButton(song)} ${exportButton} ${commitButton}</p></div></div>${confidenceDetails(candidate)}${secondaryCandidateDetails(candidate)}<div class="review-grid"><div class="field"><label>复核结论</label><select data-review-field="decision">${option('pending','暂不判断',review.decision)}${option('confirm','确认候选正确',review.decision)}${option('correct','修正候选',review.decision)}${option('exclude','不建议写入',review.decision)}</select></div><div class="field"><label>主风格结果</label><select data-review-field="genre_mode">${genreOptions}</select></div><div class="field"><label>语言</label><select data-review-field="language_mode">${languageOptions}</select></div><div class="field full"><label>副风格（可选，最多两个）</label><div class="secondary-options">${secondaryOptions}</div>${resetSecondary}</div><div class="field"><label>器乐性</label><select data-review-field="instrumental_mode">${instrumentalOptions}</select></div><div class="field"><label>对映射规则的反馈</label><select data-review-field="mapping_feedback">${option('unspecified','暂不判断',review.mapping_feedback)}${option('mapping_correct','映射正确',review.mapping_feedback)}${option('over_broad','词太宽泛 / 需降权',review.mapping_feedback)}${option('wrong_target','映射目标错误',review.mapping_feedback)}${option('missing_rule','缺少组合或例外规则',review.mapping_feedback)}${option('source_unreliable','平台来源不可靠',review.mapping_feedback)}${option('other','其他',review.mapping_feedback)}</select></div><div class="field full"><label>说明（可选，交给 agent 解释规则调整的原因）</label><textarea data-review-field="note" rows="2" placeholder="例如：Shoegaze 在这首歌只是弱影响，主风格仍应是…">${esc(review.note)}</textarea></div></div><div class="review-status">${exportText} · ${feedbackText}</div></article>`}
    function updateReview(id,field,value,rerender=true){reviews[id]={...getReview(id),[field]:value};saveReviews();if(rerender)renderReview()}
    function toggleExportSelection(id){const review=getReview(id);reviews[id]={...review,export_selected:!review.export_selected};saveReviews();renderReview()}
    function toggleSecondaryGenre(id,genre,checked){const song=DATA.songs.find(item=>item.id===id);if(!song)return;const review=getReview(id),primary=review.genre_mode==='candidate'?song.candidate.genre:review.genre_mode==='none'?null:review.genre_mode;let values=review.secondary_genres===null?candidateSecondaryGenres(song.candidate):[...(review.secondary_genres||[])];values=values.filter(value=>value!==primary);if(checked&&!values.includes(genre)){if(values.length>=2){toast('副风格最多选择两个。',true);renderReview();return}values.push(genre)}else if(!checked)values=values.filter(value=>value!==genre);reviews[id]={...review,secondary_genres:values};saveReviews();renderReview()}
    function updateConfidenceFilter(value){const percentage=Number(value);reviewState.minimum=percentage/100;$('reviewConfidenceValue').textContent=percentage===0?'全部候选':`≥ ${percentage}%`;renderReview()}
    function matchesReview(song){const q=reviewState.search.trim().toLocaleLowerCase();const review=getReview(song.id);if(q&&![song.title,song.artist,song.album].join(' ').toLocaleLowerCase().includes(q))return false;if((Number(song.candidate.confidence)||0)<reviewState.minimum)return false;if(reviewState.status==='pending'&&isReviewed(review))return false;if(reviewState.status==='reviewed'&&!isReviewed(review))return false;return true}
    function renderReview(){const all=candidateSongs(),songs=all.filter(matchesReview).sort((a,b)=>(b.candidate.confidence-a.candidate.confidence)||a.title.localeCompare(b.title));const reviewed=all.filter(song=>isReviewed(getReview(song.id))).length,selected=all.filter(song=>getReview(song.id).export_selected).length;$('reviewCount').textContent=`显示 ${songs.length} / ${all.length} 条风格候选`;$('reviewProgress').textContent=`已选择导出 ${selected} 条 · 已记录反馈 ${reviewed} 条`;$('reviewResults').innerHTML=songs.length?songs.map(reviewCard).join(''):'<div class="empty">当前筛选没有可复核的风格候选。</div>';document.querySelectorAll('[data-review-field]').forEach(node=>{const id=node.closest('[data-review-id]').dataset.reviewId;const field=node.dataset.reviewField;if(field==='note'){node.addEventListener('input',event=>updateReview(id,field,event.target.value,false));node.addEventListener('change',()=>renderReview())}else node.addEventListener('change',event=>updateReview(id,field,event.target.value))});document.querySelectorAll('[data-secondary-genre]').forEach(node=>{const id=node.closest('[data-review-id]').dataset.reviewId;node.addEventListener('change',event=>toggleSecondaryGenre(id,node.dataset.secondaryGenre,event.target.checked))});document.querySelectorAll('[data-secondary-reset]').forEach(button=>{const id=button.closest('[data-review-id]').dataset.reviewId;button.addEventListener('click',()=>updateReview(id,'secondary_genres',null))});document.querySelectorAll('[data-export-toggle]').forEach(button=>button.addEventListener('click',()=>toggleExportSelection(button.dataset.exportToggle)));document.querySelectorAll('[data-commit-id]').forEach(button=>button.addEventListener('click',()=>{const song=DATA.songs.find(item=>item.id===button.dataset.commitId);if(song)commitCandidate(song)}));wirePlayButtons($('reviewResults'))}
    function reviewTags(candidate,review){const genre=review.genre_mode==='candidate'?candidate.genre:review.genre_mode==='none'?null:review.genre_mode;const secondary_genres=resolvedSecondaryGenres(candidate,review,genre);const language=review.language_mode==='default'?null:review.language_mode==='unreviewed'?null:review.language_mode;const instrumental=review.instrumental_mode==='instrumental'?true:review.instrumental_mode==='vocal'?false:null;return {genre:{value:genre,mode:review.genre_mode},secondary_genres,language:{value:language,reviewed:review.language_mode!=='unreviewed'},instrumental:{value:instrumental,reviewed:review.instrumental_mode!=='unreviewed'}}}
    function formalRecord(song){const candidate=song.candidate,review=getReview(song.id),resolved=reviewTags(candidate,review);if(!resolved.genre.value)throw new Error('请先选择一个有效的主风格结果。');const instrumental=resolved.instrumental.reviewed?resolved.instrumental.value:(candidate.instrumental===true?true:null);const confidence=Math.round((Number(candidate.confidence)||0)*100);const genreOrigin=resolved.genre.mode==='candidate'?'确认当前候选':'采用当前修正结果';const secondaryText=resolved.secondary_genres.length?`副风格：${resolved.secondary_genres.join('、')}。`:'无副风格。';const languageText=resolved.language.reviewed?(resolved.language.value||'默认（中文 / 英文）'):'未人工判断，按默认不标语言';const formText=resolved.instrumental.reviewed?(instrumental?'人工确认 Instrumental':'人工确认非器乐'):(instrumental?'沿用候选 Instrumental':'器乐性未判断，保持未知');const noteParts=[`候选纠错页${genreOrigin}：主风格 ${resolved.genre.value}（${confidence}%）。`,secondaryText,languageText,formText];if(review.note?.trim())noteParts.push(`复核说明：${review.note.trim()}`);return {genre:resolved.genre.value,secondary_genres:resolved.secondary_genres,language:resolved.language.value,instrumental,source:'human_candidate_confirmed',updated_at:today(),note:noteParts.join(' ')} }
    async function commitCandidate(song){if(!formalState.data){toast('请先连接正式 song_tags.json。',true);return}if(song.candidate.status==='deferred'){toast('这首曲目已标为暂缓入库，不能直接写入正式标签。',true);return}let record;try{record=formalRecord(song)}catch(error){toast(error.message||'无法生成正式标签记录。',true);return}const action=formalWriteAvailable()?'写入正式文件':'加入待正式导出';const formLabel=record.instrumental===true?'Instrumental':record.instrumental===false?'非器乐':'未知';if(!confirm(`确认${action}？\n\n${song.title} — ${song.artist}\n主风格：${record.genre}\n副风格：${record.secondary_genres.join('、')||'无'}\n语言：${record.language||'默认（中文 / 英文）'}\n器乐性：${formLabel}\n\n候选置信度：${Math.round((Number(song.candidate.confidence)||0)*100)}%`))return;const previous=formalState.data.tracks[song.id],previousUpdatedAt=formalState.data.updated_at;formalState.data.tracks[song.id]=record;formalState.data.updated_at=previousUpdatedAt;let result;try{formalState.data.updated_at=today();result=await persistFormalData()}catch(error){if(previous)formalState.data.tracks[song.id]=previous;else delete formalState.data.tracks[song.id];formalState.data.updated_at=previousUpdatedAt;toast(`无法暂存正式标签：${error.message||error}`,true);return}if(result==='staged')formalState.stagedCount+=1;updateFormalFileState();const review=getReview(song.id);reviews[song.id]={...review,decision:review.decision==='pending'?'confirm':review.decision,export_selected:false};saveReviews();syncFormalTags();toast(result==='written'?`已写入正式标签：${song.title}`:`已暂存正式更新：${song.title}；继续确认其他曲目，最后一次性导出。`,false)}
    function exportFormalUpdates(){if(!formalState.data||!formalState.stagedCount){toast('当前没有待导出的正式更新。',true);return}downloadFormalData(`song_tags_formal_updates_${today()}.json`);toast(`已导出包含 ${formalState.stagedCount} 条待正式更新的完整 JSON；请替换原 song_tags.json。`)}
    function exportCorrections(){const all=candidateSongs();const selected=all.filter(song=>getReview(song.id).export_selected);if(!selected.length){toast('请先在曲目卡片点击“选择导出”，再导出 JSON。',true);return}const entries=selected.map(song=>{const review=getReview(song.id),candidate=song.candidate;return {track_id:song.id,song:{title:song.title,artist:song.artist,album:song.album},candidate:{genre:candidate.genre,secondary_genres:candidate.secondary_genres,confidence:candidate.confidence,confidence_details:candidate.confidence_details,instrumental:candidate.instrumental,matched_tags:candidate.matched_tags,evidence:candidate.evidence,errors:candidate.errors},review:{selected_for_export:true,decision:review.decision,resolved_tags:reviewTags(candidate,review),mapping_feedback:review.mapping_feedback,note:review.note.trim()}}});const counts={pending:entries.filter(entry=>entry.review.decision==='pending').length,confirm:entries.filter(entry=>entry.review.decision==='confirm').length,correct:entries.filter(entry=>entry.review.decision==='correct').length,exclude:entries.filter(entry=>entry.review.decision==='exclude').length};const payload={schema_version:'songbase.tag-corrections/v1',exported_at:today(),purpose:'Human review feedback for improving SongTag mappings. This file does not update song_tags.json by itself.',source:{browser:'song_tags_browser.html',candidate_file:'song_tag_candidates.json',candidate_generated_at:DATA.candidates?.generated_at||null,mapping_version:DATA.candidates?.mapping_version||null,taxonomy_version:DATA.taxonomy_version||null},summary:{candidate_total:all.length,selected_for_export:entries.length,feedback_entries:entries.length,decisions:counts},reviews:entries};const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)+'\n'],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download=`song_tag_corrections_${today()}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast(`已导出 ${entries.length} 条已选择的纠错反馈。`)}
    function switchView(view){const review=view==='review';$('browseView').hidden=review;$('reviewView').hidden=!review;$('browseTab').setAttribute('aria-selected',String(!review));$('reviewTab').setAttribute('aria-selected',String(review));if(review)renderReview()}
    function initPlayer(){audio.addEventListener('loadedmetadata',refreshPlayer);audio.addEventListener('timeupdate',refreshPlayer);audio.addEventListener('play',refreshPlayer);audio.addEventListener('pause',refreshPlayer);audio.addEventListener('ended',refreshPlayer);audio.addEventListener('error',()=>toast('本地音频无法读取；可尝试 QQ 或 YouTube 链接。',true));$('playerToggle').addEventListener('click',()=>{if(activeSongId)playSong(activeSongId)});$('playerProgress').addEventListener('input',event=>{if(!Number.isFinite(audio.duration)||audio.duration<=0)return;audio.currentTime=audio.duration*Number(event.target.value)/100;refreshPlayer()})}
    function renderSummary(){const tagged=DATA.songs.filter(song=>song.tags),total=DATA.songs.length,rate=total?tagged.length/total*100:0;$('total').textContent=total.toLocaleString();$('tagged').textContent=tagged.length.toLocaleString();$('untagged').textContent=(total-tagged.length).toLocaleString();$('rate').textContent=`${rate.toFixed(1)}%`;$('coverage').style.width=`${rate}%`;$('subhead').textContent=`曲库 ${DATA.library_date||'—'} · 标签 ${DATA.tags_updated_at||'—'} · 本地可播 ${DATA.audio?.mapped_tracks||0} 首 · 体系 ${DATA.taxonomy_version||'—'}`;const counts=new Map(DATA.taxonomy.genres.map(genre=>[genre,{primary:0,secondary:0}]));tagged.forEach(song=>{counts.get(song.tags.genre).primary+=1;(song.tags.secondary_genres||[]).forEach(genre=>{if(counts.has(genre))counts.get(genre).secondary+=1})});const max=Math.max(1,...[...counts.values()].flatMap(value=>[value.primary,value.secondary]));$('genreChart').innerHTML=[...counts].map(([name,value])=>`<div class="genre-row"><span class="genre-name">${esc(name)}</span><div class="genre-bars"><div class="genre-barline"><span>主</span><div class="bar"><i style="width:${value.primary/max*100}%"></i></div><b>${value.primary}</b></div><div class="genre-barline"><span>副</span><div class="bar secondary"><i style="width:${value.secondary/max*100}%"></i></div><b>${value.secondary}</b></div></div></div>`).join('')}
    function init(){initPlayer();renderSummary();
      $('taxonomy').innerHTML=[...DATA.taxonomy.genres,...DATA.taxonomy.languages,...DATA.taxonomy.forms].map(tag=>`<span class="chip">${esc(tag)}</span>`).join('');
      $('genre').innerHTML+=[...DATA.taxonomy.genres].map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');$('language').innerHTML+=[...DATA.taxonomy.languages].map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');['search','status','genre','genreScope','language','form'].forEach(id=>$(id).addEventListener(id==='search'?'input':'change',event=>{browseState[id]=event.target.value;renderBrowse()}));$('clear').addEventListener('click',()=>{Object.assign(browseState,{search:'',status:'all',genre:'all',genreScope:'any',language:'all',form:'all'});$('search').value='';['status','genre','language','form'].forEach(id=>$(id).value='all');$('genreScope').value='any';renderBrowse()});$('candidateCount').textContent=`(${candidateSongs().length})`;$('manualCount').textContent=`(${DATA.songs.filter(song=>!song.tags&&(!song.candidate||!song.candidate.genre)).length})`;$('browseTab').addEventListener('click',()=>switchView('browse'));$('reviewTab').addEventListener('click',()=>switchView('review'));$('reviewSearch').addEventListener('input',event=>{reviewState.search=event.target.value;renderReview()});$('reviewConfidence').addEventListener('input',event=>updateConfidenceFilter(event.target.value));$('reviewStatus').addEventListener('change',event=>{reviewState.status=event.target.value;renderReview()});$('connectFormalFile').addEventListener('click',connectFormalFile);$('downloadFormalBackup').addEventListener('click',()=>downloadFormalData(`song_tags_backup_${today()}.json`));$('exportFormalUpdates').addEventListener('click',exportFormalUpdates);$('formalFileInput').addEventListener('change',async event=>{const file=event.target.files?.[0];if(!file)return;try{await loadFormalFile(file)}catch(error){toast(error.message||'正式标签文件无法载入。',true)}finally{event.target.value=''}});$('exportCorrections').addEventListener('click',exportCorrections);$('clearCorrections').addEventListener('click',()=>{if(!confirm('清空本机浏览器内保存的全部纠错记录吗？已导出的 JSON 不受影响。'))return;reviews={};try{localStorage.removeItem(REVIEW_STORAGE_KEY)}catch(error){}renderReview();toast('已清空本机纠错记录。')});updateFormalFileState();renderBrowse()}
    init();
  </script>
</body>
</html>'''


def main() -> None:
    library = load_json(SONGS_PATH)
    tags = load_json(TAGS_PATH)
    candidates = load_json(CANDIDATES_PATH) if CANDIDATES_PATH.exists() else None
    if DISCARDED_PATH.exists():
        discarded_ids = set(load_json(DISCARDED_PATH).get("tracks", {}))
        library_ids = {
            track_id(song)
            for singer in library.get("singers", [])
            for song in singer.get("songs", [])
        }
        overlaps = {
            "主曲库": sorted(discarded_ids & library_ids),
            "正式标签": sorted(discarded_ids & set(tags.get("tracks", {}))),
            "候选标签": sorted(discarded_ids & set((candidates or {}).get("tracks", {}))),
        }
        errors = [f"{name}: {', '.join(ids)}" for name, ids in overlaps.items() if ids]
        if errors:
            raise ValueError("归档舍弃数据仍残留在主数据中:\n- " + "\n- ".join(errors))
    if candidates and candidates.get("schema_version") != "songbase.tag-candidates/v1":
        raise ValueError("song_tag_candidates.json 的 schema_version 必须为 songbase.tag-candidates/v1")
    payload = build_payload(library, tags, candidates)
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    OUTPUT_PATH.write_text(TEMPLATE.replace("__PAYLOAD__", encoded), encoding="utf-8")
    tagged = sum(song["tags"] is not None for song in payload["songs"])
    candidate_records = sum(song["candidate"] is not None for song in payload["songs"])
    genre_candidates = sum(bool(song["candidate"] and song["candidate"].get("genre")) for song in payload["songs"])
    print(
        f"Built {OUTPUT_PATH.name}: {len(payload['songs'])} songs, {tagged} tagged, "
        f"{candidate_records} candidate records, {genre_candidates} genre candidates, "
        f"{payload['audio']['mapped_tracks']} local-playable"
    )
    subprocess.run([sys.executable, str(BASE / "build_manual_tagging_browser.py")], check=True)


if __name__ == "__main__":
    main()
