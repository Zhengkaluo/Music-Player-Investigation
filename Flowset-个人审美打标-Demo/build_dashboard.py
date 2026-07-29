#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读取多份 Flowset 个人审美打标 JSON，生成带音频试听的自包含可视化仪表盘。"""
import json, os, glob, unicodedata, html, math

DEMO = "/Users/kaluozheng/Music-Player-Investigation/Flowset-个人审美打标-Demo"
OUT = os.path.join(DEMO, "flowset_visualization.html")

# 批次定义：label / 文件 / 波次文件夹(用于匹配音频)
BATCHES = [
    {"key":"0716","label":"第一波 · 07-16","file":"Flowset-个人审美样本-郑卡罗-2026-07-16.json"},
    {"key":"0722","label":"第二波 · 07-22","file":"Flowset-个人审美样本-郑卡罗-2026-07-22.json"},
    {"key":"0728","label":"第三波 · 07-28","file":"Flowset-个人审美样本-郑卡罗-2026-07-28.json"},
]
WAVE_DIRS = ["音乐第一波测试","音乐第二波测试","音乐第三波测试"]

# ---- 建立 mp3 文件名 -> 相对路径 映射 ----
def norm(s): return unicodedata.normalize('NFC', s).strip().lower()
file_map = {}
for d in WAVE_DIRS:
    dp = os.path.join(DEMO, d)
    if not os.path.isdir(dp): continue
    for p in glob.glob(os.path.join(dp, "**", "*.mp3"), recursive=True):
        file_map[norm(os.path.basename(p))] = os.path.relpath(p, DEMO).replace(os.sep, "/")

def find_audio(name):
    n = norm(name)
    if n in file_map: return file_map[n]
    n2 = n.replace(" ", "").replace("'", "")
    for k, v in file_map.items():
        if k.replace(" ", "").replace("'", "") == n2: return v
    return None

# ---- 组装各批次数据 ----
datasets = []
coverage = []
for b in BATCHES:
    with open(os.path.join(DEMO, b["file"]), encoding="utf-8") as f:
        d = json.load(f)
    miss = 0
    tracks = []
    for t in d["tracks"]:
        audio = find_audio(t["file"]["name"])
        if audio is None: miss += 1
        tracks.append({
            "order": t["order"],
            "name": t["file"]["name"],
            "size": t["file"].get("size"),
            "sel": [{"dimensionId": s["dimensionId"], "labels": s["labels"]} for s in t["selections"]],
            "confidence": t.get("confidence"),
            "note": t.get("note"),
            "audio": audio,
        })
    datasets.append({"key": b["key"], "label": b["label"],
                     "date": d.get("exportedAt", "")[:10], "tracks": tracks})
    coverage.append((b["label"], len(tracks), miss))

print("音频覆盖情况：")
for lab, tot, miss in coverage:
    print(f"  {lab}: {tot} 首，缺音频 {miss} 首")

APP = {"datasets": datasets,
       "combinedLabel": "合并全部 · 91 首"}
data_js = json.dumps(APP, ensure_ascii=False).replace("</", "<\\/")

# ---- 预计算摘要：保持报告在本地打开时不依赖额外脚本执行 ----
DIM_NOISE = "dimension-mrnmv2el-bcz56"
DIM_SWING = "dimension-mrnmv3aw-rxr7k"
DIM_BURDEN = "dimension-mrnmv3ns-cb63i"
TIME_ORDER = ["8-11", "11-14", "14-17", "17-20"]

def labels_of(track, dim_id):
    for s in track["sel"]:
        if s["dimensionId"] == dim_id:
            return s["labels"]
    return []

def value_of(track, dim_id):
    values = labels_of(track, dim_id)
    return int(values[0]) if values else None

def avg(values):
    return sum(values) / len(values) if values else None

def summary(tracks):
    conf = [t["confidence"] for t in tracks if t["confidence"] is not None]
    return {
        "n": len(tracks), "conf": avg(conf), "conf_n": len(conf), "notes": sum(bool(t["note"]) for t in tracks),
        "noise": avg([value_of(t, DIM_NOISE) for t in tracks]),
        "swing": avg([value_of(t, DIM_SWING) for t in tracks]),
        "burden": avg([value_of(t, DIM_BURDEN) for t in tracks]),
        "energy": {e: sum(labels_of(t, "energy-state")[:1] == [e] for t in tracks) for e in ["平静", "渐进", "有冲劲", "爆发"]},
        "times": {ts: sum(ts in labels_of(t, "time-scene") for t in tracks) for ts in TIME_ORDER},
        "time_per": avg([len(labels_of(t, "time-scene")) for t in tracks]),
    }

wave_summaries = [(d["label"], summary(d["tracks"])) for d in datasets]
base_summary = wave_summaries[0][1]
wave_rows = []
for i, (label, s) in enumerate(wave_summaries):
    def delta(key):
        if not i: return ""
        diff = s[key] - base_summary[key]
        return f'<span class="delta">较第一波 {diff:+.1f}</span>'
    energy_text = " · ".join(f'{e} {s["energy"][e] / s["n"]:.0%}' for e in ["平静", "渐进", "有冲劲", "爆发"])
    time_text = " / ".join(f'{s["times"][ts] / s["n"]:.0%}' for ts in TIME_ORDER)
    wave_rows.append(
        f'<tr><td>{label}</td><td>{s["n"]} 首<br>置信 {s["conf"]:.1f}/5'
        f'<span class="delta">已评 {s["conf_n"]}/{s["n"]} · 备注 {s["notes"]}</span></td>'
        f'<td>{s["noise"]:.2f}{delta("noise")}</td><td>{s["swing"]:.2f}{delta("swing")}</td>'
        f'<td>{s["burden"]:.2f}{delta("burden")}</td><td>{energy_text}</td>'
        f'<td>{time_text}<span class="delta">平均 {s["time_per"]:.2f} 个时段/首</span></td></tr>'
    )
WAVE_COMPARE_HTML = '<thead><tr><th>波次</th><th>样本 / 置信度</th><th>噪音</th><th>摇摆</th><th>负担</th><th>能量构成</th><th>时段覆盖率（8–11 / 11–14 / 14–17 / 17–20）</th></tr></thead><tbody>' + "".join(wave_rows) + "</tbody>"

all_tracks = [t for d in datasets for t in d["tracks"]]
low_tracks = [t for t in all_tracks if t["confidence"] is not None and t["confidence"] <= 2]
missing_tracks = [t for t in all_tracks if t["confidence"] is None]
note_tracks = [t for t in all_tracks if t["note"]]
QUALITY_HTML = "".join([
    f'<div class="quality-item"><div class="qv">{len(low_tracks)} <span style="font-size:12px;font-weight:500">首</span></div><div class="ql">低置信度（≤2）<br>建议复听或补充备注后再用于画像</div></div>',
    f'<div class="quality-item"><div class="qv">{len(missing_tracks)} <span style="font-size:12px;font-weight:500">首</span></div><div class="ql">未填置信度<br>已评 {len(all_tracks)-len(missing_tracks)}/{len(all_tracks)} 首；空值不按 0 分处理</div></div>',
    f'<div class="quality-item"><div class="qv">{len(note_tracks)} <span style="font-size:12px;font-weight:500">首</span></div><div class="ql">含主观备注<br>可作为复听与资源质量检查线索</div></div>',
])

core_tracks = [t for t in all_tracks if t["confidence"] is not None and t["confidence"] >= 4 and value_of(t, DIM_BURDEN) <= 2]
revisit_tracks = [t for t in all_tracks if t in low_tracks or t["note"]]
centroid = [avg([value_of(t, dim) for t in core_tracks]) for dim in [DIM_NOISE, DIM_SWING, DIM_BURDEN]]
explore_tracks = [t for t in all_tracks if t not in core_tracks and t["confidence"] is not None and t["confidence"] >= 3 and value_of(t, DIM_BURDEN) <= 2]
explore_tracks.sort(key=lambda t: sum((value_of(t, dim) - centroid[j]) ** 2 for j, dim in enumerate([DIM_NOISE, DIM_SWING, DIM_BURDEN])), reverse=True)

def short_name(track): return html.escape(track["name"].removesuffix(".mp3"))
def list_items(tracks, meta):
    if not tracks: return "<li>当前没有符合条件的曲目</li>"
    return "".join(f'<li>{short_name(t)}<span class="meta-line">{meta(t)}</span></li>' for t in tracks[:8])

def core_meta(t): return f"置信 {t['confidence']}/5 · 负担 {value_of(t, DIM_BURDEN)}"
def revisit_meta(t):
    conf = "未填" if t["confidence"] is None else f"{t['confidence']}/5"
    return f"置信 {conf}" + (" · 有备注" if t["note"] else "")
def explore_meta(t): return f"能量 {labels_of(t, 'energy-state')[0]} · 负担 {value_of(t, DIM_BURDEN)}"

ACTIONS_HTML = (
    f'<div class="action-card"><h3>优先保留 · {len(core_tracks)} 首</h3><p>置信度 ≥4 且负担 ≤2，可作为稳定偏好池。</p><ul>{list_items(core_tracks, core_meta)}</ul></div>'
    f'<div class="action-card"><h3>待复听 · {len(revisit_tracks)} 首</h3><p>低置信度或已有备注，暂不作为强结论依据。</p><ul>{list_items(revisit_tracks, revisit_meta)}</ul></div>'
    f'<div class="action-card"><h3>探索池 · {len(explore_tracks)} 首</h3><p>低负担、但偏离稳定偏好池，可用于扩大边界。</p><ul>{list_items(explore_tracks, explore_meta)}</ul></div>'
)

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Flowset 个人审美打标 · 可视化仪表盘（含试听）</title>
<style>
  :root{
    --bg:#f5f7fa; --panel:#ffffff; --ink:#1f2933; --sub:#6b7785; --line:#e4e9f0;
    --accent:#3b6ef5;
    --c-calm:#4c9aff; --c-prog:#36c5a8; --c-energy:#ff9f43; --c-burst:#ff5c5c; --c-unk:#9aa5b1;
  }
  *{box-sizing:border-box}
  body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
    background:var(--bg);color:var(--ink);line-height:1.5;-webkit-font-smoothing:antialiased;padding-bottom:84px}
  .wrap{max-width:1180px;margin:0 auto;padding:26px 22px 20px}
  header.top h1{font-size:23px;margin:0 0 6px}
  header.top .meta{color:var(--sub);font-size:13px}
  header.top .meta b{color:var(--ink);font-weight:600}
  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:18px 0 8px}
  .kpi{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:15px 18px;box-shadow:0 1px 2px rgba(20,40,80,.04)}
  .kpi .v{font-size:27px;font-weight:700}
  .kpi .l{color:var(--sub);font-size:12.5px;margin-top:2px}
  .kpi .v small{font-size:13px;color:var(--sub);font-weight:500}
  .toolbar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:14px 0 22px;
    background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:12px 16px}
  .toolbar .tl{font-size:13px;color:var(--sub);font-weight:600}
  .seg{display:inline-flex;background:#eef2f8;border-radius:10px;padding:3px;gap:3px}
  .seg button{border:0;background:transparent;color:#44505f;font-size:13px;font-weight:600;
    padding:7px 14px;border-radius:8px;cursor:pointer;transition:.15s}
  .seg button.active{background:#fff;color:var(--accent);box-shadow:0 1px 3px rgba(20,40,80,.12)}
  .warn{font-size:12.5px;color:#b54708;background:#fff4e5;border:1px solid #ffd8a8;
    border-radius:10px;padding:8px 12px;margin-left:auto}
  section{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px 22px;margin-bottom:20px;box-shadow:0 1px 3px rgba(20,40,80,.05)}
  section h2{font-size:16px;margin:0 0 4px;display:flex;align-items:center;gap:8px}
  section h2 .dot{width:9px;height:9px;border-radius:50%;background:var(--accent)}
  section .desc{color:var(--sub);font-size:12.5px;margin:0 0 16px}
  .grid2{display:grid;grid-template-columns:1.15fr .85fr;gap:26px;align-items:center}
  .grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}
  .chart-card h3{font-size:13.5px;margin:0 0 10px;font-weight:600}
  .legend{display:flex;flex-wrap:wrap;gap:10px 16px;margin-top:12px;font-size:12.5px;color:var(--sub)}
  .legend span{display:inline-flex;align-items:center;gap:6px}
  .legend i{width:11px;height:11px;border-radius:3px;display:inline-block}
  svg{display:block;width:100%;height:auto;overflow:visible}
  .tip{position:fixed;pointer-events:none;background:#1f2933;color:#fff;font-size:12px;
    padding:7px 10px;border-radius:8px;opacity:0;transition:opacity .12s;z-index:60;max-width:260px;
    box-shadow:0 6px 18px rgba(0,0,0,.2);line-height:1.45}
  table{width:100%;border-collapse:collapse;font-size:12.5px}
  th,td{padding:8px 9px;text-align:center;border-bottom:1px solid var(--line);white-space:nowrap}
  th{color:var(--sub);font-weight:600;font-size:12px;position:sticky;top:0;background:var(--panel);z-index:2}
  td.name{text-align:left;max-width:240px;overflow:hidden;text-overflow:ellipsis}
  .cell-num{display:inline-block;min-width:34px;padding:3px 7px;border-radius:7px;color:#fff;font-weight:600}
  .chip{display:inline-block;padding:2px 9px;border-radius:20px;color:#fff;font-size:11.5px;font-weight:600}
  .tag{display:inline-block;padding:1px 7px;border-radius:6px;background:#eef2f8;color:#44505f;font-size:11px;margin:1px 2px}
  .conf{color:var(--accent);letter-spacing:1px;font-weight:700}
  .conf .off{color:#d4dae3}
  .play-btn{border:0;cursor:pointer;width:30px;height:30px;border-radius:50%;font-size:13px;
    background:#eaf0ff;color:var(--accent);transition:.15s;display:inline-flex;align-items:center;justify-content:center}
  .play-btn:hover{background:var(--accent);color:#fff}
  .play-btn:disabled{background:#f1f3f6;color:#c4ccd6;cursor:not-allowed}
  tr.playing{background:#f3f8ff}
  .batch-badge{font-size:10.5px;padding:1px 7px;border-radius:6px;font-weight:700}
  .b-0716{background:#eef2f8;color:#5b8def}
  .b-0722{background:#e6f7f1;color:#0f9d76}
  .b-0728{background:#fdf2e9;color:#d68910}
  .tablewrap{max-height:560px;overflow:auto;border:1px solid var(--line);border-radius:10px}
  .sortable{cursor:pointer;user-select:none;transition:background .12s}
  .sortable:hover{background:#f0f6ff}
  .sort-arrow{font-size:9px;margin-left:2px;display:inline-block;width:14px;text-align:center;color:var(--accent)}
  .filter-bar{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:4px;margin-bottom:14px}
  .filter-chip{border:1px solid var(--line);background:transparent;border-radius:8px;padding:5px 12px;font-size:12px;cursor:pointer;transition:.12s;font-weight:500;color:#44505f}
  .filter-chip.active{border-color:var(--accent);background:#eaf0ff;color:var(--accent);font-weight:600}
  .filter-chip:hover:not(.active){border-color:#c4ccd6}
  .filter-divider{width:1px;height:20px;background:var(--line);margin:0 4px}
  .fcount{font-size:13px;color:var(--sub);margin-left:auto}
  .compare-table{width:100%;font-size:12px;border-collapse:separate;border-spacing:0}
  .compare-table th,.compare-table td{padding:9px 8px;border-bottom:1px solid var(--line);white-space:normal}
  .compare-table th{text-align:center;position:static;background:#f8fafc}
  .compare-table td:first-child{font-weight:700;text-align:left}
  .compare-table .delta{display:block;color:var(--sub);font-size:10.5px;margin-top:2px}
  .coverage-note{font-size:12px;color:var(--sub);margin-top:4px}
  .quality-grid,.action-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
  .quality-item,.action-card{border:1px solid var(--line);border-radius:12px;padding:13px 14px;background:#fbfcfe}
  .quality-item .qv{font-size:23px;font-weight:700}.quality-item .ql{font-size:12px;color:var(--sub)}
  .action-card h3{font-size:13.5px;margin:0 0 4px}.action-card p{font-size:11.5px;color:var(--sub);margin:0 0 8px}
  .action-card ul{list-style:none;padding:0;margin:0}.action-card li{padding:6px 0;border-top:1px solid var(--line);font-size:12px;line-height:1.35}
  .action-card .meta-line{color:var(--sub);font-size:10.5px;display:block;margin-top:2px}
  /* now playing bar */
  #np{position:fixed;left:0;right:0;bottom:0;height:72px;background:#ffffff;border-top:1px solid var(--line);
    box-shadow:0 -4px 18px rgba(20,40,80,.10);display:flex;align-items:center;gap:14px;padding:0 22px;z-index:80}
  #np .npbtn{border:0;cursor:pointer;width:42px;height:42px;border-radius:50%;background:var(--accent);color:#fff;font-size:16px;flex:0 0 auto}
  #np .npbtn:disabled{background:#cdd6e2;cursor:not-allowed}
  #np .npinfo{flex:0 0 280px;min-width:0}
  #np .npname{font-weight:600;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  #np .npstate{font-size:11.5px;color:var(--sub)}
  #np .npseek{flex:1;display:flex;align-items:center;gap:10px}
  #np input[type=range]{flex:1;accent-color:var(--accent);cursor:pointer}
  #np .nptime{font-size:11.5px;color:var(--sub);font-variant-numeric:tabular-nums;min-width:42px;text-align:center}
  .foot{color:var(--sub);font-size:12px;text-align:center;margin-top:24px}
  @media(max-width:820px){.kpis{grid-template-columns:repeat(2,1fr)}.grid2{grid-template-columns:1fr}.grid3,.quality-grid,.action-grid{grid-template-columns:1fr}
    #np .npinfo{flex-basis:160px}#np .nptime{display:none}}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <h1>🎧 Flowset 个人审美打标 · 可视化仪表盘</h1>
    <div class="meta" id="meta"></div>
  </header>

  <div class="toolbar">
    <span class="tl">查看批次：</span>
    <div class="seg" id="seg"></div>
    <div class="warn" id="warn" style="display:none"></div>
  </div>

  <div class="kpis" id="kpis"></div>

  <section>
    <h2><span class="dot"></span>三波对比总览</h2>
    <p class="desc">所有波次按相同口径并列。时段为“该波次中命中该时段的曲目占比”，不把多选次数当作独立曲目数。</p>
    <div class="tablewrap"><table class="compare-table" id="waveCompare">__WAVE_COMPARE__</table></div>
  </section>

  <section>
    <h2><span class="dot"></span>维度一 · 适合的时段 &amp; 能量状态</h2>
    <p class="desc">时段为「多选」标注（一首歌可适合多个时段）；能量为「单选」。</p>
    <div class="grid2">
      <div class="chart-card"><h3>各时段曲目覆盖率</h3><div id="chart-timeslot"></div><div class="coverage-note" id="timeslot-note"></div></div>
      <div class="chart-card"><h3>能量状态分布</h3><div id="chart-energy"></div><div class="legend" id="legend-energy"></div></div>
    </div>
  </section>

  <section>
    <h2><span class="dot"></span>维度二 · 三个数值维度的分布（1–10）</h2>
    <p class="desc">噪音程度 / 摇摆速率 / 负担程度均为 1–10 量表。竖线为均值。</p>
    <div class="grid3">
      <div class="chart-card"><h3>噪音程度</h3><div id="hist-noise"></div></div>
      <div class="chart-card"><h3>摇摆速率</h3><div id="hist-swing"></div></div>
      <div class="chart-card"><h3>负担程度</h3><div id="hist-burden"></div></div>
    </div>
  </section>

  <section>
    <h2><span class="dot"></span>维度三 · 相关性探索</h2>
    <p class="desc">散点：横轴噪音程度，纵轴摇摆速率，颜色代表能量状态。右侧为三个数值维度的皮尔逊相关系数。</p>
    <div class="grid2">
      <div class="chart-card"><h3>噪音程度 × 摇摆速率（按能量状态着色）</h3><div id="scatter"></div><div class="legend" id="legend-scatter"></div></div>
      <div class="chart-card"><h3>数值维度相关系数矩阵</h3><div id="corr"></div></div>
    </div>
  </section>

  <section>
    <h2><span class="dot"></span>维度四 · 完整画像（点击 ▶ 试听）</h2>
    <p class="desc">每行一首歌。数值格底色深浅对应数值；能量为彩色标签；置信度以圆点表示。灰显 🔇 表示该曲目暂无音频资源。</p>
    <div class="filter-bar" id="filterBar"></div>
    <div class="tablewrap"><table id="tracktable"></table></div>
  </section>

  <section>
    <h2><span class="dot"></span>数据质量与下一步行动</h2>
    <p class="desc">质量指标用于判断结论的可信度；曲目清单会随当前波次/合并视图同步变化。</p>
    <div class="quality-grid" id="qualityGrid">__QUALITY__</div>
    <div style="height:16px"></div>
    <div class="action-grid" id="actionLists">__ACTIONS__</div>
  </section>

  <div class="foot">由 WorkBuddy 基于 Flowset 导出 JSON 自动生成 · 纯前端离线可视化 · 含音频试听</div>
</div>

<div class="tip" id="tip"></div>
<audio id="player" preload="none"></audio>
<div id="np">
  <button class="npbtn" id="npToggle" disabled>▶</button>
  <div class="npinfo">
    <div class="npname" id="npName">未在播放</div>
    <div class="npstate" id="npState">选择曲目开始试听</div>
  </div>
  <div class="npseek">
    <input type="range" id="npSeek" min="0" max="1000" value="0" disabled>
    <span class="nptime" id="npCur">0:00</span>
    <span class="nptime" id="npDur">0:00</span>
  </div>
</div>

<script id="appdata" type="application/json">__DATA__</script>
<script>
const APP = JSON.parse(document.getElementById('appdata').textContent);
const $ = s => document.querySelector(s);
const tip=$('#tip');
const ENERGY_COLORS={'平静':'#4c9aff','渐进':'#36c5a8','有冲劲':'#ff9f43','爆发':'#ff5c5c','不确定':'#9aa5b1'};
const TS_ORDER=['8-11','11-14','14-17','17-20'];
const TS_COLORS={'8-11':'#f6c653','11-14':'#7cc6fe','14-17':'#5b8def','17-20':'#9b6dff'};
function showTip(h,e){tip.innerHTML=h;tip.style.opacity=1;moveTip(e);}
function moveTip(e){let x=e.clientX+14,y=e.clientY+14;if(x+260>innerWidth)x=e.clientX-274;if(y+120>innerHeight)y=e.clientY-120;tip.style.left=x+'px';tip.style.top=y+'px';}
function hideTip(){tip.style.opacity=0;}

// 批次选择：合并 + 各批次
const BATCHES=[{key:'all',label:APP.combinedLabel},...APP.datasets.map(d=>({key:d.key,label:d.label}))];
let currentKey='all';
let sortBy=null,sortDir=1,activeFilters={energy:new Set(),timeslot:new Set()};
function curTracks(){ if(currentKey==='all'){let a=[];APP.datasets.forEach(d=>d.tracks.forEach(t=>a.push(Object.assign({_batch:d.key},t))));return a;}
  return APP.datasets.find(d=>d.key===currentKey).tracks.map(t=>Object.assign({_batch:currentKey},t)); }

// 渲染批次按钮
$('#seg').innerHTML=BATCHES.map(b=>`<button data-k="${b.key}" class="${b.key==='all'?'active':''}">${b.label}</button>`).join('');
$('#seg').querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{
  currentKey=b.dataset.k;
  $('#seg').querySelectorAll('button').forEach(x=>x.classList.toggle('active',x===b));
  sortBy=null;sortDir=1;activeFilters={energy:new Set(),timeslot:new Set()};
  renderAll();
}));

function selOf(t,dimId){const s=t.sel.find(x=>x.dimensionId===dimId);return s;s?null:null;}
function labOf(t,dimId){const s=t.sel.find(x=>x.dimensionId===dimId);return s?s.labels:[];}

// ---- meta & kpis ----
function renderMeta(tracks){
  const ds=APP.datasets;
  const d0=ds[0],d1=ds[ds.length-1];
  $('#meta').innerHTML=`标注者 <b>${'郑卡罗'}</b> · 共 ${ds.length} 个批次（${d0.date} ~ ${d1.date}）· 合并 ${tracks.length} 首`;
  const conf=tracks.map(t=>t.confidence).filter(v=>v!=null);
  const avg=(conf.reduce((a,b)=>a+b,0)/conf.length).toFixed(1);
  const notes=tracks.filter(t=>t.note).length;
  const noAudio=tracks.filter(t=>!t.audio).length;
  $('#kpis').innerHTML=[
    ['曲目总数',tracks.length,'首'],
    ['含音频可试听',tracks.length-noAudio,`/ ${tracks.length} 首`],
    ['平均置信度',avg,`/5（${conf.length} 首已评）`],
    ['含备注曲目',notes,'首']
  ].map(([l,v,s])=>`<div class="kpi"><div class="v">${v}<small> ${s}</small></div><div class="l">${l}</div></div>`).join('');
  const w=$('#warn');
  if(noAudio>0){w.style.display='block';w.innerHTML=`⚠️ 当前视图有 <b>${noAudio}</b> 首缺少音频资源，无法试听`;}else{w.style.display='none';}
}

// ---- 1 timeslot ----
function chartTimeslot(tracks){
  const counts={};TS_ORDER.forEach(t=>counts[t]=0);
  tracks.forEach(t=>labOf(t,'time-scene').forEach(l=>counts[l]++));
  const rates={};TS_ORDER.forEach(t=>rates[t]=counts[t]/Math.max(tracks.length,1));
  const max=Math.max(...Object.values(rates),.01);
  const W=520,H=170,pad=10,rowH=(H-pad*2)/TS_ORDER.length;
  let svg=`<svg viewBox="0 0 ${W} ${H}">`;
  TS_ORDER.forEach((t,i)=>{const y=pad+i*rowH;const bw=(W-120)*rates[t]/max;
    svg+=`<rect x="110" y="${y+rowH*0.18}" width="${bw}" height="${rowH*0.64}" rx="5" fill="${TS_COLORS[t]}" opacity=".9"></rect>`;
    svg+=`<text x="102" y="${y+rowH*0.5+4}" text-anchor="end" font-size="12.5" fill="#44505f">${t}</text>`;
    svg+=`<text x="${110+bw+8}" y="${y+rowH*0.5+4}" font-size="12.5" fill="#1f2933" font-weight="600">${counts[t]} / ${tracks.length}（${Math.round(rates[t]*100)}%）</text>`;});
  svg+=`</svg>`;$('#chart-timeslot').innerHTML=svg;
  $('#timeslot-note').textContent=`平均每首命中 ${ (Object.values(counts).reduce((a,b)=>a+b,0)/Math.max(tracks.length,1)).toFixed(2) } 个时段；多选曲目会同时计入各时段覆盖率。`;
}

/* 暂由页面底部的静态摘要承载三波比较和行动清单，避免影响核心可视化初始化。
function mean(vals){return vals.length?vals.reduce((a,b)=>a+b,0)/vals.length:null;}
function getNumByDim(t,dimId){const s=t.sel.find(x=>x.dimensionId===dimId);return s?+s.labels[0]:null;}
function waveStats(ds){
  const tracks=ds.tracks, conf=tracks.map(t=>t.confidence).filter(v=>v!=null);
  const avg=dimId=>mean(tracks.map(t=>getNumByDim(t,dimId)).filter(v=>v!=null));
  const energy={};['平静','渐进','有冲劲','爆发','不确定'].forEach(e=>energy[e]=tracks.filter(t=>labOf(t,'energy-state')[0]===e).length);
  const times={};TS_ORDER.forEach(ts=>times[ts]=tracks.filter(t=>labOf(t,'time-scene').includes(ts)).length);
  return {n:tracks.length,conf:mean(conf),confN:conf.length,missing:tracks.length-conf.length,notes:tracks.filter(t=>t.note).length,noAudio:tracks.filter(t=>!t.audio).length,
    low:tracks.filter(t=>t.confidence!=null&&t.confidence<=2).length,noise:avg('dimension-mrnmv2el-bcz56'),swing:avg('dimension-mrnmv3aw-rxr7k'),burden:avg('dimension-mrnmv3ns-cb63i'),energy,times,timePer:mean(tracks.map(t=>labOf(t,'time-scene').length))};
}
function signed(v){return (v>0?'+':'')+v.toFixed(1);}
function renderWaveCompare(){
  const stats=APP.datasets.map(d=>({label:d.label,stats:waveStats(d)}));
  const base=stats[0].stats;
  let html='<thead><tr><th>波次</th><th>样本 / 置信度</th><th>噪音</th><th>摇摆</th><th>负担</th><th>能量构成</th><th>时段覆盖率（8–11 / 11–14 / 14–17 / 17–20）</th></tr></thead><tbody>';
  stats.forEach(({label,stats:s},i)=>{const delta=(v,k)=>i?`<span class="delta">较第一波 ${signed(v-base[k])}</span>`:'';
    const energy=['平静','渐进','有冲劲','爆发'].map(e=>`${e} ${Math.round(s.energy[e]/s.n*100)}%`).join(' · ');
    const times=TS_ORDER.map(ts=>Math.round(s.times[ts]/s.n*100)+'%').join(' / ');
    html+=`<tr><td>${label}</td><td>${s.n} 首<br>${s.conf==null?'未评':'置信 '+s.conf.toFixed(1)+'/5'}<span class="delta">已评 ${s.confN}/${s.n} · 备注 ${s.notes}</span></td><td>${s.noise.toFixed(2)}${delta(s.noise,'noise')}</td><td>${s.swing.toFixed(2)}${delta(s.swing,'swing')}</td><td>${s.burden.toFixed(2)}${delta(s.burden,'burden')}</td><td>${energy}</td><td>${times}<span class="delta">平均 ${s.timePer.toFixed(2)} 个时段/首</span></td></tr>`;
  });
  $('#waveCompare').innerHTML=html+'</tbody>';
}
function trackLabel(t){return t.name.replace(/\.mp3$/,'');}
function renderQualityAndActions(tracks){
  const conf=tracks.map(t=>t.confidence).filter(v=>v!=null), low=tracks.filter(t=>t.confidence!=null&&t.confidence<=2), missing=tracks.filter(t=>t.confidence==null), notes=tracks.filter(t=>t.note);
  $('#qualityGrid').innerHTML=[
    [low.length,'低置信度（≤2）','建议复听或补充备注后再用于画像'],
    [missing.length,'未填置信度',`已评 ${conf.length}/${tracks.length} 首；避免将空值当作 0 分`],
    [notes.length,'含主观备注',`音频缺失 ${tracks.filter(t=>!t.audio).length} 首；备注可作为质检线索`]
  ].map(x=>`<div class="quality-item"><div class="qv">${x[0]} <span style="font-size:12px;font-weight:500">首</span></div><div class="ql">${x[1]}<br>${x[2]}</div></div>`).join('');
  const core=tracks.filter(t=>t.confidence>=4&&getNumByDim(t,'dimension-mrnmv3ns-cb63i)<=2);
  const revisit=tracks.filter(t=>(t.confidence!=null&&t.confidence<=2)||t.note);
  const centroid=core.length?['dimension-mrnmv2el-bcz56','dimension-mrnmv3aw-rxr7k','dimension-mrnmv3ns-cb63i'].map(d=>mean(core.map(t=>getNumByDim(t,d)))):null;
  const explore=tracks.filter(t=>t.confidence>=3&&getNumByDim(t,'dimension-mrnmv3ns-cb63i)<=2&&!core.includes(t)).map(t=>({t,dist:centroid?Math.sqrt(['dimension-mrnmv2el-bcz56','dimension-mrnmv3aw-rxr7k','dimension-mrnmv3ns-cb63i'].reduce((sum,d,i)=>sum+(getNumByDim(t,d)-centroid[i])**2,0)):0})).sort((a,b)=>b.dist-a.dist).map(x=>x.t);
  const list=(arr,detail)=>arr.slice(0,8).map(t=>`<li>${trackLabel(t)}<span class="meta-line">${detail(t)}</span></li>`).join('')||'<li>当前没有符合条件的曲目</li>';
  $('#actionLists').innerHTML=`
    <div class="action-card"><h3>优先保留 · ${core.length} 首</h3><p>置信度 ≥4 且负担 ≤2，可作为当前稳定偏好池。</p><ul>${list(core,t=>`置信 ${t.confidence}/5 · 负担 ${getNumByDim(t,'dimension-mrnmv3ns-cb63i')}`)}</ul></div>
    <div class="action-card"><h3>待复听 · ${revisit.length} 首</h3><p>低置信度或已有备注，暂不作为强结论依据。</p><ul>${list(revisit,t=>`置信 ${t.confidence==null?'未填':t.confidence+'/5'}${t.note?' · 有备注':''}`)}</ul></div>
    <div class="action-card"><h3>探索池 · ${explore.length} 首</h3><p>低负担、但偏离稳定偏好池，可用于扩大边界。</p><ul>${list(explore,t=>`能量 ${labOf(t,'energy-state')[0]} · 负担 ${getNumByDim(t,'dimension-mrnmv3ns-cb63i')}`)}</ul></div>`;
}
*/
// ---- 2 energy donut ----
function chartEnergy(tracks){
  const counts={};['平静','渐进','有冲劲','爆发','不确定'].forEach(e=>counts[e]=0);
  tracks.forEach(t=>labOf(t,'energy-state').forEach(l=>counts[l]++));
  const total=tracks.length;let r=70,cx=110,cy=90,circ=2*Math.PI*r,off=0;
  let svg=`<svg viewBox="0 0 220 180"><circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#eef2f8" stroke-width="22"></circle>`;
  Object.entries(counts).forEach(([k,v])=>{if(!v)return;const frac=v/total,len=frac*circ;
    svg+=`<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${ENERGY_COLORS[k]}" stroke-width="22" stroke-dasharray="${len} ${circ-len}" stroke-dashoffset="${-off}" transform="rotate(-90 ${cx} ${cy})" style="cursor:pointer" data-k="${k}" data-v="${v}"></circle>`;off+=len;});
  svg+=`<text x="${cx}" y="${cy-4}" text-anchor="middle" font-size="26" font-weight="700" fill="#1f2933">${total}</text>`;
  svg+=`<text x="${cx}" y="${cy+16}" text-anchor="middle" font-size="11.5" fill="#6b7785">首曲目</text></svg>`;
  $('#chart-energy').innerHTML=svg;
  $('#legend-energy').innerHTML=Object.entries(counts).filter(([k,v])=>v).map(([k,v])=>`<span><i style="background:${ENERGY_COLORS[k]}"></i>${k} · ${v}</span>`).join('');
  $('#chart-energy').querySelectorAll('circle[data-k]').forEach(c=>{c.addEventListener('mousemove',e=>showTip(`<b>${c.dataset.k}</b><br>${c.dataset.v} 首 (${Math.round(c.dataset.v/total*100)}%)`,e));c.addEventListener('mouseleave',hideTip);});
}
// ---- 3 histograms ----
function hist(container,dimId,color){
  const vals=curTracks().map(t=>{const s=t.sel.find(x=>x.dimensionId===dimId);return s?+s.labels[0]:null;}).filter(v=>v!=null);
  const counts=Array(10).fill(0);let sum=0;vals.forEach(v=>{counts[v-1]++;sum+=v;});
  const avg=vals.length?(sum/vals.length).toFixed(1):'–';
  const max=Math.max(...counts,1);const W=300,H=170,padB=22,padT=8,padL=8,padR=8,bw=(W-padL-padR)/10;
  let svg=`<svg viewBox="0 0 ${W} ${H}">`;
  for(let i=0;i<10;i++){const h=(H-padB-padT)*counts[i]/max;const x=padL+i*bw,y=H-padB-h;
    svg+=`<rect x="${x+1}" y="${y}" width="${bw-2}" height="${h}" rx="3" fill="${color}" opacity="${0.35+0.6*counts[i]/max}"></rect>`;
    svg+=`<text x="${x+bw/2}" y="${H-padB+13}" text-anchor="middle" font-size="9.5" fill="#8a96a5">${i+1}</text>`;}
  if(vals.length){const ax=padL+(avg-1)*bw+bw/2;
    svg+=`<line x1="${ax}" y1="${padT}" x2="${ax}" y2="${H-padB}" stroke="#ff5c5c" stroke-width="1.6" stroke-dasharray="4 3"></line>`;
    svg+=`<text x="${ax}" y="${padT+9}" text-anchor="middle" font-size="10" fill="#ff5c5c" font-weight="700">μ${avg}</text>`;}
  svg+=`</svg>`;$(container).innerHTML=svg;
}
// ---- 4 scatter ----
function chartScatter(tracks){
  const pts=tracks.map(t=>({x:+t.sel.find(s=>s.dimensionId==='dimension-mrnmv2el-bcz56').labels[0],
    y:+t.sel.find(s=>s.dimensionId==='dimension-mrnmv3aw-rxr7k').labels[0],
    e:t.sel.find(s=>s.dimensionId==='energy-state').labels[0],name:t.name,note:t.note}));
  const W=520,H=360,padL=38,padB=40,padT=14,padR=14,x0=padL,x1=W-padR,y0=H-padB,y1=padT;
  const sx=v=>x0+(v-1)/9*(x1-x0),sy=v=>y0-(v-1)/9*(y0-y1);
  let svg=`<svg viewBox="0 0 ${W} ${H}">`;
  for(let i=1;i<=10;i++){svg+=`<line x1="${sx(i)}" y1="${y1}" x2="${sx(i)}" y2="${y0}" stroke="#eef2f8"></line>`;
    svg+=`<line x1="${x0}" y1="${sy(i)}" x2="${x1}" y2="${sy(i)}" stroke="#eef2f8"></line>`;
    svg+=`<text x="${sx(i)}" y="${y0+15}" text-anchor="middle" font-size="9.5" fill="#8a96a5">${i}</text>`;
    svg+=`<text x="${x0-8}" y="${sy(i)+3}" text-anchor="end" font-size="9.5" fill="#8a96a5">${i}</text>`;}
  svg+=`<text x="${(x0+x1)/2}" y="${H-6}" text-anchor="middle" font-size="11" fill="#6b7785">噪音程度 →</text>`;
  svg+=`<text x="14" y="${(y0+y1)/2}" text-anchor="middle" font-size="11" fill="#6b7785" transform="rotate(-90 14 ${(y0+y1)/2}")">摇摆速率 →</text>`;
  pts.forEach(p=>{svg+=`<circle class="pt" cx="${sx(p.x)}" cy="${sy(p.y)}" r="6.5" fill="${ENERGY_COLORS[p.e]}" opacity=".82" stroke="#fff" stroke-width="1.2" data-name="${p.name}" data-e="${p.e}" data-x="${p.x}" data-y="${p.y}" data-note="${p.note||''}"></circle>`;});
  svg+=`</svg>`;$('#scatter').innerHTML=svg;
  $('#legend-scatter').innerHTML=Object.entries(ENERGY_COLORS).map(([k,c])=>`<span><i style="background:${c}"></i>${k}</span>`).join('');
  $('#scatter').querySelectorAll('circle.pt').forEach(c=>{c.addEventListener('mousemove',e=>{const t=`<b>${c.dataset.name}</b><br>能量：${c.dataset.e}<br>噪音 ${c.dataset.x} · 摇摆 ${c.dataset.y}`+(c.dataset.note?`<br><span style="color:#ffd">📝 ${c.dataset.note}</span>`:'');showTip(t,e);});c.addEventListener('mouseleave',hideTip);});
}
// ---- 5 corr ----
function chartCorr(tracks){
  const dims=[['噪音程度','dimension-mrnmv2el-bcz56'],['摇摆速率','dimension-mrnmv3aw-rxr7k'],['负担程度','dimension-mrnmv3ns-cb63i']];
  const arr=dims.map(d=>tracks.map(t=>+t.sel.find(s=>s.dimensionId===d[1]).labels[0]));
  function pear(a,b){const n=a.length,ma=a.reduce((x,y)=>x+y,0)/n,mb=b.reduce((x,y)=>x+y,0)/n;let num=0,da=0,db=0;for(let i=0;i<n;i++){num+=(a[i]-ma)*(b[i]-mb);da+=(a[i]-ma)**2;db+=(b[i]-mb)**2;}return num/Math.sqrt(da*db);}
  const names=dims.map(d=>d[0]);const M=arr.map(a=>arr.map(b=>pear(a,b)));
  const W=300,H=300,pad=64,cw=(W-pad-10)/3,ch=(H-pad-10)/3;
  let svg=`<svg viewBox="0 0 ${W} ${H}">`;
  names.forEach((nm,j)=>{svg+=`<text x="${pad+j*cw+cw/2}" y="${pad-12}" text-anchor="middle" font-size="11" fill="#6b7785">${nm}</text>`;});
  for(let i=0;i<3;i++){svg+=`<text x="${pad-10}" y="${pad+i*ch+ch/2+4}" text-anchor="end" font-size="11" fill="#6b7785">${names[i]}</text>`;
    for(let j=0;j<3;j++){const v=M[i][j],x=pad+j*cw,y=pad+i*ch,a=Math.abs(v);
      const fill=v>=0?`rgba(91,141,239,${0.15+0.75*a})`:`rgba(255,159,67,${0.15+0.75*a})`;
      svg+=`<rect x="${x+2}" y="${y+2}" width="${cw-4}" height="${ch-4}" rx="6" fill="${fill}"></rect>`;
      svg+=`<text x="${x+cw/2}" y="${y+ch/2+4}" text-anchor="middle" font-size="13" font-weight="700" fill="${a>0.45?'#fff':'#22303f'}">${v.toFixed(2)}</text>`;}}
  svg+=`</svg>`;$('#corr').innerHTML=svg;
}
// ---- 排序 & 筛选 ----
function applyFilters(tracks){
  let r=tracks;
  if(activeFilters.energy.size>0)r=r.filter(t=>activeFilters.energy.has(labOf(t,'energy-state')[0]));
  if(activeFilters.timeslot.size>0)r=r.filter(t=>labOf(t,'time-scene').some(ts=>activeFilters.timeslot.has(ts)));
  return r;
}
function getNum(t,dimId){const s=t.sel.find(x=>x.dimensionId===dimId);return s?+s.labels[0]:0;}
function sortTracks(tracks){
  if(!sortBy)return tracks;
  const dir=sortDir;
  return [...tracks].sort((a,b)=>{let va,vb;
    switch(sortBy){
      case 'order':va=a.order;vb=b.order;break;
      case 'name':va=a.name.toLowerCase();vb=b.name.toLowerCase();break;
      case 'energy':va=labOf(a,'energy-state')[0]||'';vb=labOf(b,'energy-state')[0]||'';break;
      case 'noise':va=getNum(a,'dimension-mrnmv2el-bcz56');vb=getNum(b,'dimension-mrnmv2el-bcz56');break;
      case 'swing':va=getNum(a,'dimension-mrnmv3aw-rxr7k');vb=getNum(b,'dimension-mrnmv3aw-rxr7k');break;
      case 'burden':va=getNum(a,'dimension-mrnmv3ns-cb63i');vb=getNum(b,'dimension-mrnmv3ns-cb63i');break;
      case 'confidence':va=a.confidence||0;vb=b.confidence||0;break;
      default:return 0;}
    if(va<vb)return -1*dir;if(va>vb)return 1*dir;return 0;});
}
function sortArrow(col){if(sortBy!==col)return' \\u25B3';return sortDir===1?' \\u25B2':' \\u25BC';}
function renderFilterBar(){
  const tracks=curTracks();
  const ec=[];['平静','渐进','有冲劲','爆发','不确定'].forEach(e=>{const c=tracks.filter(t=>labOf(t,'energy-state')[0]===e).length;if(c>0)ec.push([e,c]);});
  const tc=[];TS_ORDER.forEach(ts=>{const c=tracks.filter(t=>labOf(t,'time-scene').includes(ts)).length;if(c>0)tc.push([ts,c]);});
  let html='<span style="font-size:12px;color:var(--sub);font-weight:600">筛选：</span>';
  html+=`<button class="filter-chip${(activeFilters.energy.size+activeFilters.timeslot.size===0)?' active':''}" data-ft="all">全部</button>`;
  html+=`<span class="filter-divider"></span>`;
  ec.forEach(([e,c])=>{html+=`<button class="filter-chip${activeFilters.energy.has(e)?' active':''}" data-ft="energy" data-fv="${e}">🔥 ${e} · ${c}</button>`;});
  html+=`<span class="filter-divider"></span>`;
  tc.forEach(([ts,c])=>{html+=`<button class="filter-chip${activeFilters.timeslot.has(ts)?' active':''}" data-ft="timeslot" data-fv="${ts}">⏰ ${ts} · ${c}</button>`;});
  html+=`<span class="fcount">点击表头 ▲▼ 排序</span>`;
  $('#filterBar').innerHTML=html;
  $('#filterBar').querySelectorAll('button.filter-chip').forEach(b=>b.addEventListener('click',()=>{
    const ft=b.dataset.ft,fv=b.dataset.fv;
    if(ft==='all'){activeFilters={energy:new Set(),timeslot:new Set()};}
    else{activeFilters.energy=new Set();activeFilters.timeslot=new Set();}
    if(ft==='energy'){if(activeFilters.energy.has(fv))activeFilters.energy.delete(fv);else activeFilters.energy.add(fv);}
    if(ft==='timeslot'){if(activeFilters.timeslot.has(fv))activeFilters.timeslot.delete(fv);else activeFilters.timeslot.add(fv);}
    renderFilterBar();renderTable(curTracks());
  }));
}

// ---- 6 table ----
function renderTable(tracks){
  let filtered=applyFilters(tracks);
  let sorted=sortTracks(filtered);
  const cols=[
    {h:'',w:42},{h:'#',w:32,sort:'order'},{h:'曲目',w:236,sort:'name'},{h:'批次',w:78},
    {h:'时段',w:140},{h:'能量',w:78,sort:'energy'},
    {h:'噪音',w:60,sort:'noise'},{h:'摇摆',w:60,sort:'swing'},{h:'负担',w:60,sort:'burden'},{h:'置信',w:70,sort:'confidence'}
  ];
  let html='<thead><tr>'+cols.map(c=>{
    const s=c.sort?` class="sortable" data-sort="${c.sort}"`:'';
    return `<th${s} style="width:${c.w}px">${c.h}<span class="sort-arrow">${c.sort?sortArrow(c.sort):''}</span></th>`;
  }).join('')+'</tr></thead><tbody>';
  function numColor(v){const a=(v-1)/9;return `rgb(${Math.round(91+(255-91)*a)},${Math.round(141+(159-141)*a)},${Math.round(239+(67-239)*a)})`;}
  sorted.forEach((t,si)=>{
    const oi=tracks.indexOf(t);
    const ts=labOf(t,'time-scene'),en=labOf(t,'energy-state')[0];
    const noise=getNum(t,'dimension-mrnmv2el-bcz56');
    const swing=getNum(t,'dimension-mrnmv3aw-rxr7k');
    const burden=getNum(t,'dimension-mrnmv3ns-cb63i');
    const conf=t.confidence;
    const tsTags=ts.map(x=>`<span class="tag" style="background:${TS_COLORS[x]}22;color:${TS_COLORS[x]}">${x}</span>`).join('');
    const confDots=[1,2,3,4,5].map(k=>`<span class="${conf&&k<=conf?'conf':'conf'}"><span class="${conf&&k<=conf?'':'off'}">●</span></span>`).join('');
    const playable=!!t.audio;
    const bkey=t._batch==='0716'?'b-0716':(t._batch==='0722'?'b-0722':(t._batch==='0728'?'b-0728':''));
    const btxt=t._batch==='0716'?'第一波':(t._batch==='0722'?'第二波':(t._batch==='0728'?'第三波':''));
    const noteAttr=t.note?` data-note="${t.note.replace(/"/g,'&quot;')}"`:'';
    html+=`<tr id="row-${oi}"${noteAttr}>`+
      `<td><button class="play-btn" data-idx="${oi}" ${playable?'':'disabled title="无音频资源"'}>${playable?'▶':'🔇'}</button></td>`+
      `<td>${t.order}</td>`+
      `<td class="name" title="${t.name}">${t.name.replace(/\.mp3$/,'')}</td>`+
      `<td><span class="batch-badge ${bkey}">${btxt}</span></td>`+
      `<td>${tsTags}</td>`+
      `<td><span class="chip" style="background:${ENERGY_COLORS[en]}">${en}</span></td>`+
      `<td><span class="cell-num" style="background:${numColor(noise)}">${noise}</span></td>`+
      `<td><span class="cell-num" style="background:${numColor(swing)}">${swing}</span></td>`+
      `<td><span class="cell-num" style="background:${numColor(burden)}">${burden}</span></td>`+
      `<td>${confDots}</td></tr>`;
  });
  html+='</tbody>';
  const tbl=$('#tracktable');tbl.innerHTML=html;
  tbl.querySelectorAll('tr[data-note]').forEach(tr=>{tr.style.cursor='help';tr.addEventListener('mousemove',e=>showTip(`<b>备注</b><br>${tr.dataset.note}`,e));tr.addEventListener('mouseleave',hideTip);});
  tbl.querySelectorAll('button.play-btn').forEach(b=>{if(!b.disabled)b.addEventListener('click',e=>{e.stopPropagation();playIdx(+b.dataset.idx);});});
  tbl.querySelectorAll('th.sortable').forEach(th=>{th.addEventListener('click',()=>{
    const col=th.dataset.sort;
    if(sortBy===col){sortDir*=-1;if(sortDir===1){sortBy=null;sortDir=1;}}
    else{sortBy=col;sortDir=1;}
    renderTable(tracks);
  });});
}

// ---- 播放器 ----
const player=$('#player'),npToggle=$('#npToggle'),npName=$('#npName'),npState=$('#npState'),npSeek=$('#npSeek'),npCur=$('#npCur'),npDur=$('#npDur');
let curIdx=-1;
function fmt(s){if(!isFinite(s))return'0:00';const m=Math.floor(s/60);const ss=Math.floor(s%60);return m+':'+(ss<10?'0':'')+ss;}
function playIdx(i){
  const t=curTracks()[i];if(!t||!t.audio)return;
  if(curIdx===i){togglePlay();return;}
  curIdx=i;
  player.src=encodeURI(t.audio);
  player.play().catch(()=>{});
  npName.textContent=t.name.replace(/\.mp3$/,'');
  document.querySelectorAll('#tracktable tr.playing').forEach(r=>r.classList.remove('playing'));
  const row=$('#row-'+i);if(row)row.classList.add('playing');
}
function togglePlay(){if(curIdx<0){const f=curTracks().findIndex(t=>t.audio);if(f>=0)playIdx(f);return;}if(player.paused)player.play().catch(()=>{});else player.pause();}
npToggle.addEventListener('click',togglePlay);
player.addEventListener('play',()=>{npToggle.textContent='⏸';npState.textContent='播放中';npSeek.disabled=false;});
player.addEventListener('pause',()=>{npToggle.textContent='▶';npState.textContent=player.ended?'播放结束':'已暂停';});
player.addEventListener('ended',()=>{npToggle.textContent='▶';npState.textContent='播放结束';document.querySelectorAll('#tracktable tr.playing').forEach(r=>r.classList.remove('playing'));curIdx=-1;});
player.addEventListener('loadedmetadata',()=>{npDur.textContent=fmt(player.duration);});
player.addEventListener('timeupdate',()=>{if(player.duration){npSeek.value=Math.floor(player.currentTime/player.duration*1000);npCur.textContent=fmt(player.currentTime);}});
npSeek.addEventListener('input',()=>{if(player.duration)player.currentTime=npSeek.value/1000*player.duration;});

// ---- 总渲染 ----
function renderAll(){
  const tracks=curTracks();
  renderMeta(tracks);
  chartTimeslot(tracks);chartEnergy(tracks);
  hist('#hist-noise','dimension-mrnmv2el-bcz56','#5b8def');
  hist('#hist-swing','dimension-mrnmv3aw-rxr7k','#36c5a8');
  hist('#hist-burden','dimension-mrnmv3ns-cb63i','#f6a04d');
  chartScatter(tracks);chartCorr(tracks);
  renderFilterBar();
  renderTable(tracks);
}
renderAll();
</script>
</body>
</html>"""

HTML = HTML.replace("__DATA__", data_js)
HTML = HTML.replace("__WAVE_COMPARE__", WAVE_COMPARE_HTML)
HTML = HTML.replace("__QUALITY__", QUALITY_HTML)
HTML = HTML.replace("__ACTIONS__", ACTIONS_HTML)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(HTML)
print("written:", OUT, "bytes:", len(HTML))
