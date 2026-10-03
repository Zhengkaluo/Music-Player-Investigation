#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a self-contained, locally playable two-hour Flowset playlist report."""

from __future__ import annotations

import csv
import hashlib
import html
import json
from collections import defaultdict
from pathlib import Path

import build_transition_relationship_report as transition


HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SONGBASE = REPO / "SongBase"
OUT = HERE / "flowset_2h_playlist.html"


SECTIONS = [
    {
        "key": "ambient",
        "label": "第一幕 · 把听觉打开",
        "genre": "Ambient / Neo-Classical",
        "intent": "从极简、低噪音开始，逐步加入旋律、空间和轻微律动。",
        "track_ids": [
            "qq:002cBVub1Kncz5",  # Deep Breath
            "qq:002KkZUc09vxV7",  # Hicari
            "qq:001F8bj23GYo4t",  # Emancipation
            "qq:002jaefh3NZVjb",  # 夕阳消失之前
            "qq:00308O0k0f6qNj",  # sign
            "qq:0023U8im0EI3sM",  # Bee
            "qq:002kir4k1YoDFP",  # Dreams Today
            "qq:0001jtij4JXGMK",  # fragrance like home
            "qq:003V6m7u4eEihH",  # Luv(sic)pt2 - Acoustica -
        ],
    },
    {
        "key": "jazz",
        "label": "第二幕 · 节奏进入身体",
        "genre": "Jazz / Soul",
        "intent": "让节奏从柔和的 Soul 进入更明确的律动，最后用高纹理 Jazz 做转场。",
        "track_ids": [
            "qq:004eH7Lq4QsEN4",  # Last Hour
            "qq:002lo8SN1mOVC8",  # Red Moon
            "qq:0040UVDj4bZZ3N",  # Musicology
            "qq:004HO5WO2cxlhn",  # I Feel for You
            "qq:004XqfYg1mNSla",  # relive
            "qq:004Uf3pG1Wulnm",  # Utopia (feat. Marti Fischer)
            "qq:003iodBT3kKdAC",  # Chateau
        ],
    },
    {
        "key": "electronic",
        "label": "第三幕 · 纹理接管节拍",
        "genre": "Electronic",
        "intent": "用一次有依据的降噪转场重置耳朵，再逐首增加电子脉冲。",
        "track_ids": [
            "qq:001smf6l4Jw7Fx",  # 蝉
            "qq:002nfKLv28evOK",  # Looped
            "qq:004StP7u0GX8V2",  # Cœur croisé
            "qq:002G2Chc1MB9Gm",  # 数字天体
        ],
    },
    {
        "key": "postrock",
        "label": "第四幕 · 向远景展开",
        "genre": "Post-Rock / Cinematic",
        "intent": "把电子脉冲扩展成乐队动态，经过数次呼吸后抵达爆发，再柔和落地。",
        "track_ids": [
            "qq:000eNgNg1QWVlJ",  # レイテストナンバー
            "qq:001IfO1Y2pBPvg",  # 10th sentimen
            "qq:000gnR5f0L9CqV",  # SUNSET
            "qq:001neLbY2J9GCJ",  # Distance
            "qq:001PQRBd0hMLtT",  # The Beyond
            "qq:002OP9r71u0qbq",  # Empty Places, Smiling Faces
            "qq:0029bARE21ML6j",  # 南方
            "qq:0037LBhA4SfrM6",  # Utopia
            "qq:001nquQQ0q36G8",  # Hello goodbye
        ],
    },
]


REASON_NOTES = {
    "qq:002cBVub1Kncz5": "用 40 秒极简片段清空前序听觉；噪音、摇摆、负担均为 1，是整条曲线的零点。",
    "qq:002KkZUc09vxV7": "保持同一主 Tag 和低噪音，只把负担从 1 提到 2，让开场有轻微纵深。",
    "qq:001F8bj23GYo4t": "噪音与摇摆仍维持 1，负担回落到 1；在短曲之后把空间真正铺开。",
    "qq:002jaefh3NZVjb": "同为平静，噪音、摇摆各上升 1，负担仅升到 2，开始把旋律推到前景。",
    "qq:00308O0k0f6qNj": "噪音和摇摆同步升到 3，但负担降到 1；听感更清晰活跃而不压迫。",
    "qq:0023U8im0EI3sM": "短暂回落到 2/2/1，作为进入渐进段之前的呼吸点。",
    "qq:002kir4k1YoDFP": "同主 Tag 的实测连接；从平静进入渐进，而三个数值维度几乎不跳变。",
    "qq:0001jtij4JXGMK": "保持渐进、噪音 2 和摇摆 2，仅把负担提高 1，延长推进感。",
    "qq:003V6m7u4eEihH": "噪音不变、摇摆从 2 提到 4、负担反而下降，为进入 Jazz/Soul 提前建立节拍。",
    "qq:004eH7Lq4QsEN4": "跨主 Tag 但 Flowset 很接近：噪音同为 2、负担同为 1，摇摆只下降 1；用柔和 Soul 承接木质氛围。",
    "qq:002lo8SN1mOVC8": "留在 Jazz/Soul 内，将能量从平静推到有冲劲；负担只从 1 升到 2。",
    "qq:0040UVDj4bZZ3N": "同能量下把噪音与摇摆一起推高，完成从松弛 Soul 到明确 Groove 的转换。",
    "qq:004HO5WO2cxlhn": "摇摆保持 4，噪音略降、负担略升；增加密度但不突然加速。",
    "qq:004XqfYg1mNSla": "同主 Tag 的高分实测连接；噪音与摇摆各升 1，负担下降 1，推进自然。",
    "qq:004Uf3pG1Wulnm": "保持有冲劲和噪音 5，摇摆小幅回落、负担升 1，让强度集中而不继续加速。",
    "qq:003iodBT3kKdAC": "仍在 Jazz/Soul 内，把噪音和摇摆推到本幕最高；铜管与 Funk 纹理承担跨入电子段的桥。",
    "qq:001smf6l4Jw7Fx": "这是刻意的章节重置：Flowset 数值明显回落，但该组合实测 cost/risk 很低，适合让耳朵重新聚焦。",
    "qq:002nfKLv28evOK": "同主 Tag，从平静进入渐进；噪音和摇摆各升 1，负担下降 1。",
    "qq:004StP7u0GX8V2": "从渐进进入有冲劲，噪音只升 1、摇摆与负担不变，让节拍自然显形。",
    "qq:002G2Chc1MB9Gm": "维持有冲劲，摇摆从 4 升到 5；用更大的电子结构为乐队段落蓄力。",
    "qq:000eNgNg1QWVlJ": "实测被选中的跨 Tag 连接；电子副风格为 Post-Rock 打开入口，摇摆保持 5。",
    "qq:001IfO1Y2pBPvg": "同为渐进，噪音和摇摆各升 1，但负担从 5 降到 2；把张力换成更开阔的推进。",
    "qq:000gnR5f0L9CqV": "同主 Tag 的实测连接；能量进入有冲劲，摇摆回落，避免连续堆高造成疲劳。",
    "qq:001neLbY2J9GCJ": "保持有冲劲和噪音 4，摇摆由 4 升到 6，进入本幕的第一轮加速。",
    "qq:001PQRBd0hMLtT": "本轮最高分的实测衔接之一；数值适度回落但负担不变，让高强度获得空间。",
    "qq:002OP9r71u0qbq": "继续保持有冲劲，噪音回升 1、负担下降 1，重新聚拢乐队动态。",
    "qq:0029bARE21ML6j": "实测被选中且 cost/risk 很低；噪音、摇摆、负担都下降 1，作为高潮前的呼吸。",
    "qq:0037LBhA4SfrM6": "从有冲劲进入爆发，三个数值维度同时上升，是全歌单唯一一次有意的大幅抬升。",
    "qq:001nquQQ0q36G8": "实测低风险收尾；从爆发回到有冲劲，噪音和负担各降 1，保留速度感但不戛然而止。",
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fmt_time(seconds: int):
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def songbase_by_id():
    payload = load_json(SONGBASE / "song_base_by_artist.json")
    result = {}
    for singer in payload["singers"]:
        for song in singer["songs"]:
            url = song.get("qq_music", "")
            if "/songDetail/" not in url:
                continue
            mid = url.rsplit("/songDetail/", 1)[1].split("?", 1)[0].strip("/")
            result["qq:" + mid] = song
    return result


def annotation_index():
    by_date_name = {}
    by_digest = {}
    for date, folder_name, export_name in transition.FLOWSET_WAVES:
        payload = load_json(HERE / export_name)
        for track in payload["tracks"]:
            path = HERE / folder_name / track["file"]["name"]
            if not path.is_file() or path.stat().st_size == 0:
                continue
            item = {"date": date, "folder": folder_name, "track": track, "path": path}
            by_date_name[(date, track["file"]["name"])] = item
            by_digest[sha256(path)] = item
    return by_date_name, by_digest


def build_tracks():
    data = transition.load_rows()
    songbase = songbase_by_id()
    metadata = dict(data["track_meta"])
    with (HERE / "flowset_tag_matched.csv").open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            metadata.setdefault(row["track_id"], {
                "title": row["title"], "artist": row["artist"], "filename": row["filename"]
            })
    by_date_name, by_digest = annotation_index()

    pair_rows = defaultdict(list)
    for row in data["rows"]:
        if row["status"] == "primary":
            pair_rows[(row["source_id"], row["target_id"])].append(row)

    tracks = []
    cumulative = 0
    global_order = 0
    for section in SECTIONS:
        for section_order, track_id in enumerate(section["track_ids"], start=1):
            global_order += 1
            if track_id not in data["flowset"] or track_id not in data["tags"] or track_id not in songbase:
                raise KeyError(f"Incomplete playlist source data: {track_id}")
            flow = data["flowset"][track_id]
            meta = metadata[track_id]
            annotation = by_date_name.get((flow["date"], meta["filename"]))
            resource = SONGBASE / "SongResources" / meta["filename"]
            if annotation is None and resource.is_file():
                annotation = by_digest.get(sha256(resource))
            if annotation is None:
                raise FileNotFoundError(f"Cannot resolve annotated audio for {track_id}: {meta['filename']}")

            duration = int(songbase[track_id]["duration"])
            cumulative += duration
            selections = {item["dimension"]: item["labels"] for item in annotation["track"]["selections"]}
            tag = data["tags"][track_id]
            empirical = None
            if tracks:
                observations = pair_rows.get((tracks[-1]["track_id"], track_id), [])
                if observations:
                    empirical = {
                        "n": len(observations),
                        "rating": sum(row["rating"] for row in observations) / len(observations),
                        "selected": sum(row["selected"] for row in observations) / len(observations),
                        "cost": sum(row["cost"] for row in observations) / len(observations),
                        "risk": sum(row["risk"] for row in observations) / len(observations),
                        "bridge": transition.BRIDGE_LABELS[observations[0]["bridge_class"]],
                    }
            if empirical:
                choice = "被选中" if empirical["selected"] > 0.5 else "平局" if empirical["selected"] == 0.5 else "未被选中"
                evidence_prefix = (
                    f"实测：评分 {empirical['rating']:.1f}/5，{choice}，"
                    f"cost {empirical['cost']:.3f}、risk {empirical['risk']:.3f}。"
                )
                evidence = "实测"
            elif tracks:
                evidence_prefix = "设计判断："
                evidence = "设计"
            else:
                evidence_prefix = "开场："
                evidence = "开场"

            tracks.append({
                "order": global_order,
                "section_order": section_order,
                "section": section["key"],
                "section_label": section["label"],
                "track_id": track_id,
                "title": meta["title"],
                "artist": meta["artist"],
                "duration": duration,
                "duration_label": fmt_time(duration),
                "cumulative": cumulative,
                "cumulative_label": fmt_time(cumulative),
                "audio": annotation["path"].relative_to(HERE).as_posix(),
                "genre": tag["genre"],
                "secondary": tag.get("secondary_genres") or [],
                "energy": selections["能量状态"][0],
                "noise": int(selections["噪音程度"][0]),
                "swing": int(selections["摇摆速率"][0]),
                "burden": int(selections["负担程度"][0]),
                "confidence": annotation["track"].get("confidence"),
                "note": annotation["track"].get("note"),
                "evidence": evidence,
                "empirical": empirical,
                "reason": evidence_prefix + REASON_NOTES[track_id],
            })
    return tracks


def build_document(tracks):
    total = sum(item["duration"] for item in tracks)
    empirical_count = sum(item["evidence"] == "实测" for item in tracks)
    cursor = 0
    sections = []
    for section in SECTIONS:
        items = [item for item in tracks if item["section"] == section["key"]]
        duration = sum(item["duration"] for item in items)
        sections.append({
            **{key: section[key] for key in ("key", "label", "genre", "intent")},
            "start": cursor,
            "start_label": fmt_time(cursor),
            "duration": duration,
            "duration_label": fmt_time(duration),
            "end": cursor + duration,
            "end_label": fmt_time(cursor + duration),
            "tracks": len(items),
            "share": duration / total * 100,
        })
        cursor += duration

    payload = json.dumps({
        "title": "从静水到远景",
        "subtitle": "一条不依赖时段标签的四幕式两小时歌单",
        "total": total,
        "totalLabel": fmt_time(total),
        "empiricalCount": empirical_count,
        "sections": sections,
        "tracks": tracks,
    }, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    document = TEMPLATE.replace("__DATA__", payload)
    return document


TEMPLATE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>从静水到远景 · 两小时 Flowset 歌单</title>
<style>
:root{--bg:#f3f1ec;--panel:#fffefa;--ink:#1c2524;--sub:#6e7773;--line:#dfe2dd;--accent:#315f59;--soft:#e5eeeb;--ambient:#698aa0;--jazz:#b36b48;--electronic:#7866a8;--postrock:#3f6f64;--tested:#287259;--designed:#8b7046;--shadow:0 10px 30px rgba(39,49,46,.07)}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.55;padding-bottom:104px}.wrap{max-width:1180px;margin:auto;padding:34px 22px 48px}.hero{padding:24px 0 22px}.eyebrow{font-size:12px;letter-spacing:.12em;color:var(--accent);font-weight:700;text-transform:uppercase}.hero h1{font-size:34px;line-height:1.18;margin:7px 0 8px}.hero p{margin:0;color:var(--sub);font-size:14px}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0 22px}.stat{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:15px 17px;box-shadow:var(--shadow)}.stat b{font-size:24px;display:block}.stat span{font-size:11.5px;color:var(--sub)}section{background:var(--panel);border:1px solid var(--line);border-radius:17px;padding:21px 23px;margin-bottom:18px;box-shadow:var(--shadow)}section h2{font-size:18px;margin:0 0 5px}section>.desc{font-size:12.5px;color:var(--sub);margin:0 0 16px}.principles{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.principle h3{font-size:14px;margin:0 0 4px}.principle p{font-size:12px;color:var(--sub);margin:0}.timeline{display:flex;height:74px;border-radius:12px;overflow:hidden;background:#e7e8e4}.timeline-part{min-width:0;padding:10px 12px;color:#fff;display:flex;flex-direction:column;justify-content:space-between}.timeline-part b{font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.timeline-part span{font-size:10.5px;opacity:.86}.ambient{background:var(--ambient)}.jazz{background:var(--jazz)}.electronic{background:var(--electronic)}.postrock{background:var(--postrock)}.acts{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:12px}.act{padding:10px 2px}.act b{font-size:12.5px;display:block}.act span{font-size:11px;color:var(--sub)}.energy-chart{width:100%;height:auto;display:block}.energy-chart text{font-family:inherit;fill:var(--sub);font-size:10px}.energy-chart .grid{stroke:var(--line);stroke-width:1}.energy-chart .path{fill:none;stroke:var(--accent);stroke-width:3;stroke-linejoin:round}.energy-chart .point{stroke:var(--panel);stroke-width:2}.legend{display:flex;gap:15px;flex-wrap:wrap;font-size:11px;color:var(--sub);margin-top:7px}.legend i{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:5px}.playlist{display:flex;flex-direction:column;gap:8px}.track{display:grid;grid-template-columns:42px 36px minmax(190px,1.1fr) 115px 152px minmax(270px,1.6fr);gap:10px;align-items:center;padding:11px 12px;border:1px solid var(--line);border-radius:12px;background:#fff;transition:.15s}.track.playing{border-color:var(--accent);box-shadow:0 0 0 2px rgba(49,95,89,.12);background:#fbfffd}.play{border:0;width:34px;height:34px;border-radius:50%;background:var(--soft);color:var(--accent);font-weight:700;cursor:pointer}.play:hover{background:var(--accent);color:#fff}.num{font-size:12px;color:var(--sub);text-align:center}.song b{font-size:13.5px;display:block}.song span,.timing span{font-size:11px;color:var(--sub)}.timing b{font-size:12px;display:block}.tags{display:flex;gap:4px;flex-wrap:wrap}.tag{font-size:10px;padding:2px 6px;border-radius:999px;background:#edf0ed;color:#53605c}.tag.energy{background:var(--soft);color:var(--accent)}.tag.tested{background:#e4f3ec;color:var(--tested)}.tag.designed{background:#f5eee2;color:var(--designed)}.reason{font-size:11.5px;color:#4f5b57}.reason b{font-size:10px;margin-right:5px}.section-break{margin-top:14px;padding:13px 14px;border-radius:12px;color:#fff;display:flex;justify-content:space-between;gap:18px;align-items:center}.section-break h3{font-size:14px;margin:0 0 2px}.section-break p{font-size:11px;margin:0;opacity:.88}.section-break .clock{text-align:right;white-space:nowrap;font-size:11px}.method{font-size:12px;color:var(--sub)}.method strong{color:var(--ink)}#playerbar{position:fixed;z-index:50;left:0;right:0;bottom:0;min-height:84px;background:rgba(255,254,250,.96);backdrop-filter:blur(12px);border-top:1px solid var(--line);box-shadow:0 -8px 28px rgba(34,45,42,.09);display:flex;align-items:center;gap:13px;padding:10px 22px}.pcontrols{display:flex;gap:7px}.pbtn{border:0;width:38px;height:38px;border-radius:50%;background:var(--soft);color:var(--accent);font-size:14px;cursor:pointer}.pbtn.primary{background:var(--accent);color:#fff}.pinfo{width:270px;min-width:0}.pinfo b,.pinfo span{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.pinfo b{font-size:12.5px}.pinfo span{font-size:10.5px;color:var(--sub)}.seek{flex:1;display:flex;align-items:center;gap:9px}.seek input{flex:1;accent-color:var(--accent)}.ptime{font-size:10.5px;color:var(--sub);font-variant-numeric:tabular-nums;min-width:39px;text-align:center}.autoplay{font-size:11px;color:var(--sub);display:flex;gap:5px;align-items:center;white-space:nowrap}.autoplay input{accent-color:var(--accent)}@media(max-width:950px){.stats{grid-template-columns:repeat(2,1fr)}.principles,.acts{grid-template-columns:repeat(2,1fr)}.track{grid-template-columns:42px 30px minmax(170px,1fr) 95px minmax(220px,1.5fr)}.tags{display:none}.pinfo{width:190px}}@media(max-width:680px){.wrap{padding:22px 12px 34px}.hero h1{font-size:27px}.stats,.principles,.acts{grid-template-columns:1fr 1fr}section{padding:17px 14px}.timeline{height:auto;flex-direction:column}.timeline-part{height:58px}.track{grid-template-columns:38px 28px 1fr 75px}.reason{grid-column:3 / 5}.tags{display:flex;grid-column:3 / 5}.pinfo{width:120px}.autoplay{display:none}#playerbar{padding:9px}.pcontrols .pbtn:first-child{display:none}}@media(max-width:430px){.stats,.principles,.acts{grid-template-columns:1fr}.seek .ptime{display:none}.track{grid-template-columns:36px 25px 1fr}.timing{display:none}.reason,.tags{grid-column:3 / 4}}
</style>
</head>
<body>
<div class="wrap">
  <header class="hero"><div class="eyebrow">Flowset playlist study · 4 acts</div><h1>从静水到远景</h1><p>一条不依赖早晚时段标签、由个人听感与真实衔接测试共同组织的两小时歌单。</p></header>
  <div class="stats" id="stats"></div>
  <section><h2>设计思路</h2><p class="desc">先以主 Tag 形成稳定段落，再把真正困难的跨 Tag 转换集中到三个边界处理。</p><div class="principles"><div class="principle"><h3>段落，而不是随机穿插</h3><p>同主 Tag 衔接整体更稳定，因此用四幕形成清晰叙事，避免每首歌都换风格。</p></div><div class="principle"><h3>实测优先，Flowset 辅助</h3><p>真实评分、选择结果和 cost/risk 决定关键连接；Flowset 用于控制能量与听感突变。</p></div><div class="principle"><h3>一次主高潮，一次落地</h3><p>前三幕逐步增加节奏与纹理，第四幕扩大动态，只在倒数第二首进入爆发，最后收束。</p></div></div></section>
  <section><h2>四幕时间结构</h2><p class="desc">完整歌曲顺播总长；没有把时段标签作为选曲条件。</p><div class="timeline" id="timeline"></div><div class="acts" id="acts"></div></section>
  <section><h2>能量曲线</h2><p class="desc">纵轴来自 Flowset 能量状态；颜色表示主 Tag 段落。曲线只表达段落设计，不代表客观声压。</p><div id="energyChart"></div><div class="legend" id="legend"></div></section>
  <section><h2>完整歌单与逐首衔接原因</h2><p class="desc">绿色“实测”表示这对相邻歌曲在风格衔接测试中出现过；棕色“设计”表示依据 Tag、Flowset 和段落目标作出的新组合。</p><div class="playlist" id="playlist"></div></section>
  <section><h2>解读边界</h2><div class="method"><strong>Flowset 不是自动审美分。</strong> 现有交叉验证没有证明它能在 Tag 基础上提升样本外预测，因此这里把它当作能量与听感连续性的软约束。没有实测过的相邻关系会明确标注为“设计判断”，建议优先试听三个跨 Tag 边界和所有标注为设计的连接。</div></section>
</div>
<audio id="audio" preload="metadata"></audio>
<div id="playerbar">
  <div class="pcontrols"><button class="pbtn" id="prev" aria-label="上一首">◀</button><button class="pbtn primary" id="toggle" aria-label="播放或暂停">▶</button><button class="pbtn" id="next" aria-label="下一首">▶|</button></div>
  <div class="pinfo"><b id="nowTitle">选择一首开始试听</b><span id="nowMeta">29 首 · 119:57</span></div>
  <div class="seek"><span class="ptime" id="curTime">0:00</span><input id="seek" type="range" min="0" max="1000" value="0" aria-label="播放进度"><span class="ptime" id="durTime">0:00</span></div>
  <label class="autoplay"><input id="autoNext" type="checkbox" checked> 连续播放</label>
</div>
<script id="playlistData" type="application/json">__DATA__</script>
<script>
const DATA=JSON.parse(document.getElementById('playlistData').textContent);
const $=id=>document.getElementById(id);
const COLORS={ambient:'#698aa0',jazz:'#b36b48',electronic:'#7866a8',postrock:'#3f6f64'};
const ENERGY={平静:1,渐进:2,有冲劲:3,爆发:4};
const fmt=s=>{if(!Number.isFinite(s))return'0:00';const m=Math.floor(s/60),ss=Math.floor(s%60);return`${m}:${ss<10?'0':''}${ss}`};

function renderHeader(){
  const stats=[['总时长',DATA.totalLabel],['曲目',DATA.tracks.length+' 首'],['主 Tag',DATA.sections.length+' 种'],['实测相邻关系',DATA.empiricalCount+' 组']];
  $('stats').innerHTML=stats.map(([label,value])=>`<div class="stat"><b>${value}</b><span>${label}</span></div>`).join('');
  $('timeline').innerHTML=DATA.sections.map(s=>`<div class="timeline-part ${s.key}" style="flex:${s.duration}"><b>${s.genre}</b><span>${s.start_label}–${s.end_label} · ${s.duration_label}</span></div>`).join('');
  $('acts').innerHTML=DATA.sections.map(s=>`<div class="act"><b>${s.label}</b><span>${s.tracks} 首 · ${s.duration_label}<br>${s.intent}</span></div>`).join('');
}

function renderEnergy(){
  const w=1000,h=235,left=72,right=24,top=20,bottom=38,innerW=w-left-right,innerH=h-top-bottom;
  const x=i=>left+i/(DATA.tracks.length-1)*innerW,y=v=>top+(4-v)/3*innerH;
  const labels=['爆发','有冲劲','渐进','平静'];
  const grid=labels.map((label,i)=>{const yy=top+i/3*innerH;return`<line class="grid" x1="${left}" y1="${yy}" x2="${w-right}" y2="${yy}"/><text x="${left-10}" y="${yy+4}" text-anchor="end">${label}</text>`}).join('');
  const points=DATA.tracks.map((t,i)=>`${x(i)},${y(ENERGY[t.energy])}`).join(' ');
  const dots=DATA.tracks.map((t,i)=>`<circle class="point" cx="${x(i)}" cy="${y(ENERGY[t.energy])}" r="5" fill="${COLORS[t.section]}"><title>${t.order}. ${t.title} · ${t.energy}</title></circle>`).join('');
  const ticks=DATA.tracks.filter((_,i)=>i===0||i===DATA.tracks.length-1||DATA.sections.some(s=>s.start===DATA.tracks[i].cumulative-DATA.tracks[i].duration)).map(t=>`<text x="${x(t.order-1)}" y="${h-10}" text-anchor="middle">${t.cumulative===t.duration?'0:00':fmt(t.cumulative-t.duration)}</text>`).join('');
  $('energyChart').innerHTML=`<svg class="energy-chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="29 首歌曲的 Flowset 能量曲线"><polyline class="path" points="${points}"/>${grid}${dots}${ticks}</svg>`;
  $('legend').innerHTML=DATA.sections.map(s=>`<span><i style="background:${COLORS[s.key]}"></i>${s.genre}</span>`).join('');
}

function renderPlaylist(){
  let currentSection='';let out='';
  DATA.tracks.forEach((t,i)=>{
    if(t.section!==currentSection){const s=DATA.sections.find(x=>x.key===t.section);out+=`<div class="section-break ${s.key}"><div><h3>${s.label}</h3><p>${s.genre} · ${s.intent}</p></div><div class="clock">${s.start_label}–${s.end_label}<br>${s.tracks} 首</div></div>`;currentSection=t.section;}
    const ev=t.evidence==='实测'?'tested':t.evidence==='设计'?'designed':'';
    out+=`<article class="track" id="track-${i}"><button class="play" data-i="${i}" aria-label="播放 ${t.title}">▶</button><div class="num">${String(t.order).padStart(2,'0')}</div><div class="song"><b>${t.title}</b><span>${t.artist}</span></div><div class="timing"><b>${t.duration_label}</b><span>累计 ${t.cumulative_label}</span></div><div class="tags"><span class="tag energy">${t.energy}</span><span class="tag">噪 ${t.noise}</span><span class="tag">摇 ${t.swing}</span><span class="tag">负 ${t.burden}</span></div><div class="reason"><b class="tag ${ev}">${t.evidence}</b>${t.reason}</div></article>`;
  });
  $('playlist').innerHTML=out;
  document.querySelectorAll('.play').forEach(btn=>btn.addEventListener('click',()=>playTrack(+btn.dataset.i)));
}

const audio=$('audio');let current=-1;
function syncHighlight(){document.querySelectorAll('.track').forEach((row,i)=>row.classList.toggle('playing',i===current));document.querySelectorAll('.play').forEach((b,i)=>b.textContent=i===current&&!audio.paused?'Ⅱ':'▶');}
function playTrack(index){if(index<0||index>=DATA.tracks.length)return;current=index;const t=DATA.tracks[index];audio.src=encodeURI(t.audio);$('nowTitle').textContent=`${t.order}. ${t.title}`;$('nowMeta').textContent=`${t.artist} · ${t.section_label}`;audio.play().catch(()=>{});syncHighlight();document.getElementById(`track-${index}`).scrollIntoView({behavior:'smooth',block:'center'});}
function toggle(){if(current<0){playTrack(0);return}audio.paused?audio.play().catch(()=>{}):audio.pause()}
$('toggle').addEventListener('click',toggle);$('prev').addEventListener('click',()=>playTrack(Math.max(0,current-1)));$('next').addEventListener('click',()=>playTrack(Math.min(DATA.tracks.length-1,current+1)));
audio.addEventListener('play',()=>{$('toggle').textContent='Ⅱ';syncHighlight()});audio.addEventListener('pause',()=>{$('toggle').textContent='▶';syncHighlight()});
audio.addEventListener('loadedmetadata',()=>{$('durTime').textContent=fmt(audio.duration)});audio.addEventListener('timeupdate',()=>{if(audio.duration){$('seek').value=Math.round(audio.currentTime/audio.duration*1000);$('curTime').textContent=fmt(audio.currentTime)}});$('seek').addEventListener('input',()=>{if(audio.duration)audio.currentTime=+$('seek').value/1000*audio.duration});
audio.addEventListener('ended',()=>{if($('autoNext').checked&&current<DATA.tracks.length-1)playTrack(current+1);else{$('toggle').textContent='▶';syncHighlight()}});
renderHeader();renderEnergy();renderPlaylist();
</script>
</body>
</html>'''


def main():
    tracks = build_tracks()
    document = build_document(tracks)
    OUT.write_text(document, encoding="utf-8")
    total = sum(item["duration"] for item in tracks)
    print(json.dumps({
        "report": str(OUT),
        "tracks": len(tracks),
        "duration_seconds": total,
        "duration": fmt_time(total),
        "empirical_transitions": sum(item["evidence"] == "实测" for item in tracks),
        "audio_missing": sum(not (HERE / item["audio"]).is_file() for item in tracks),
        "audio_empty": sum((HERE / item["audio"]).stat().st_size == 0 for item in tracks),
        "sections": [
            {"label": section["label"], "tracks": len([t for t in tracks if t["section"] == section["key"]]),
             "duration": fmt_time(sum(t["duration"] for t in tracks if t["section"] == section["key"]))}
            for section in SECTIONS
        ],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
