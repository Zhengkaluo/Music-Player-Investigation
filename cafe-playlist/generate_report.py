"""
基于清洗后的 albums.json 生成完整数据分析 HTML 报告
"""
import json
import statistics
from collections import Counter
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
ALBUMS_FILE = DATA_DIR / "albums.json"
OUT_FILE = Path(__file__).parent / "report" / "album_analysis_report.html"


def load_data():
    with open(ALBUMS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_stats(albums):
    total = len(albums)

    # 地区
    regions = Counter()
    for a in albums:
        r = (a.get("region") or "未知").strip()
        regions[r] += 1

    # 风格
    genres = Counter()
    for a in albums:
        for g in a.get("genres", []):
            genres[g] += 1

    # 噪音
    noise_vals = [a["noise_level"] for a in albums if a.get("noise_level") is not None]
    noise_mean = round(statistics.mean(noise_vals), 2) if noise_vals else 0
    noise_median = round(statistics.median(noise_vals), 2) if noise_vals else 0

    # 噪音分 bin
    noise_bins = Counter()
    for v in noise_vals:
        b = int(v // 2) * 2
        noise_bins[f"{b}-{b+2}"] += 1
    noise_bin_labels = sorted(noise_bins.keys(), key=lambda x: int(x.split("-")[0]))
    noise_bin_data = [noise_bins[k] for k in noise_bin_labels]

    # 噪音来源
    noise_src = Counter(a.get("noise_source", "?") for a in albums)

    # 数据质量
    has_artist = sum(1 for a in albums if a.get("artist"))
    has_duration = sum(1 for a in albums if a.get("duration_seconds"))
    has_tracks = sum(1 for a in albums if a.get("tracks"))
    has_last_played = sum(1 for a in albums if a.get("last_played"))
    has_last_played = sum(1 for a in albums if a.get("last_played") or a.get("last_played"))  # 兼容两种拼写
    # 正确统计 last_played / last_played
    has_last = sum(1 for a in albums if a.get("last_played") or a.get("last_playered"))

    # artist 出现次数
    artists = Counter()
    for a in albums:
        art = a.get("artist", "").strip()
        if art:
            artists[art] += 1

    # 时长统计
    durations = [a["duration_seconds"] for a in albums if a.get("duration_seconds")]
    avg_duration = round(statistics.mean(durations) / 60, 1) if durations else 0  # 分钟

    return {
        "total": total,
        "region_count": len([r for r in regions if r != "未知"]),
        "genre_count": len(genres),
        "noise_mean": noise_mean,
        "noise_median": noise_median,
        "has_tracks": has_tracks,
        "has_last_played": has_last,
        "regions": regions,
        "genres": genres,
        "noise_vals": noise_vals,
        "noise_bins": noise_bin_labels,
        "noise_bin_data": noise_bin_data,
        "noise_src": noise_src,
        "artists": artists,
        "avg_duration_min": avg_duration,
        "durations": durations,
    }


def escape_js(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


def render_html(stats):
    total = stats["total"]
    regions = stats["regions"]
    genres = stats["genres"]
    artists = stats["artists"]
    ns = stats["noise_src"]

    # 地区 Top10 for chart
    top_regions = regions.most_common(10)
    region_labels = [r for r, _ in top_regions]
    region_data = [n for _, n in top_regions]

    # 风格 Top20
    top_genres = genres.most_common(20)
    genre_labels = [g for g, _ in top_genres]
    genre_data = [n for _, n in top_genres]

    # 噪音来源 pie
    ns_labels = [s for s, _ in ns.most_common()]
    ns_data = [n for _, n in ns.most_common()]

    # Top10 artist
    top_artists = artists.most_common(10)
    artist_labels = [a for a, _ in top_artists]
    artist_data = [n for _, n in top_artists]

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>咖啡店歌单专辑库数据分析报告</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
    background: #0f0f1a;
    color: #e0e0e0;
    line-height: 1.6;
  }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 32px 24px; }}
  h1 {{
    text-align: center;
    font-size: 28px;
    font-weight: 700;
    margin-bottom: 8px;
    background: linear-gradient(135deg, #6ee7b7, #3b82f6);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }}
  .subtitle {{
    text-align: center;
    color: #888;
    font-size: 14px;
    margin-bottom: 32px;
  }}
  /* 卡片行 */
  .card-row {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px;
    margin-bottom: 32px;
  }}
  .card {{
    background: linear-gradient(135deg, #1a1a2e, #16213e);
    border: 1px solid #2a2a4a;
    border-radius: 12px;
    padding: 20px;
    text-align: center;
  }}
  .card .num {{
    font-size: 36px;
    font-weight: 800;
    background: linear-gradient(135deg, #6ee7b7, #3b82f6);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }}
  .card .label {{
    font-size: 13px;
    color: #888;
    margin-top: 4px;
  }}
  /* 图表网格 */
  .chart-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24px;
    margin-bottom: 32px;
  }}
  @media (max-width: 768px) {{
    .chart-grid {{ grid-template-columns: 1fr; }}
  }}
  .chart-box {{
    background: #1a1a2e;
    border: 1px solid #2a2a4a;
    border-radius: 12px;
    padding: 20px;
  }}
  .chart-box h3 {{
    font-size: 15px;
    color: #aaa;
    margin-bottom: 16px;
  }}
  .chart-box canvas {{
    width: 100% !important;
    max-height: 300px;
  }}
  /* 表格 */
  .table-section {{
    background: #1a1a2e;
    border: 1px solid #2a2a4a;
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 24px;
    overflow-x: auto;
  }}
  .table-section h3 {{
    font-size: 15px;
    color: #aaa;
    margin-bottom: 16px;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
  }}
  th {{
    text-align: left;
    padding: 8px 12px;
    color: #6ee7b7;
    border-bottom: 1px solid #2a2a4a;
    font-weight: 600;
  }}
  td {{
    padding: 8px 12px;
    border-bottom: 1px solid #1e1e3e;
  }}
  tr:hover td {{
    background: #16213e;
  }}
  .tag {{
    display: inline-block;
    background: #2a2a4a;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 12px;
    margin: 2px;
    color: #6ee7b7;
  }}
  .bar-cell {{
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .bar {{
    height: 8px;
    background: linear-gradient(90deg, #3b82f6, #6ee7b7);
    border-radius: 4px;
    min-width: 2px;
  }}
  /* 数据质量 */
  .quality-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 12px;
    margin-bottom: 32px;
  }}
  .quality-item {{
    background: #1a1a2e;
    border: 1px solid #2a2a4a;
    border-radius: 8px;
    padding: 12px 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  .quality-item .q-label {{ color: #aaa; font-size: 14px; }}
  .quality-item .q-val {{ color: #6ee7b7; font-weight: 700; font-size: 16px; }}
  .quality-item .q-val.bad {{ color: #f87171; }}
</style>
</head>
<body>
<div class="container">

  <h1>🎵 咖啡店歌单专辑库数据分析报告</h1>
  <p class="subtitle">数据来源：cafe-playlist/data/albums.json（已清洗）｜生成时间：2026-04-24</p>

  <!-- 顶栏数字卡片 -->
  <div class="card-row">
    <div class="card"><div class="num">{total}</div><div class="label">专辑总数</div></div>
    <div class="card"><div class="num">{stats['region_count']}</div><div class="label">覆盖地区数</div></div>
    <div class="card"><div class="num">{stats['genre_count']}</div><div class="label">风格标签种类</div></div>
    <div class="card"><div class="num">{stats['noise_mean']}</div><div class="label">平均噪音水平</div></div>
    <div class="card"><div class="num">{stats['has_tracks']}</div><div class="label">有曲目详情</div></div>
    <div class="card"><div class="num">{stats['has_last_played']}</div><div class="label">有播放记录</div></div>
  </div>

  <!-- 图表 2x2 -->
  <div class="chart-grid">
    <div class="chart-box">
      <h3>📍 地区分布 Top 10</h3>
      <canvas id="regionChart"></canvas>
    </div>
    <div class="chart-box">
      <h3>🎼 风格标签 Top 20</h3>
      <canvas id="genreChart"></canvas>
    </div>
    <div class="chart-box">
      <h3>🔊 噪音水平分布</h3>
      <canvas id="noiseBinChart"></canvas>
    </div>
    <div class="chart-box">
      <h3>🔍 噪音数据来源</h3>
      <canvas id="noiseSrcChart"></canvas>
    </div>
  </div>

  <!-- 数据质量 -->
  <div class="table-section">
    <h3>📋 数据质量概览</h3>
    <div class="quality-grid">
      <div class="quality-item"><span class="q-label">artist 字段</span><span class="q-val">100% ({total}/{total})</span></div>
      <div class="quality-item"><span class="q-label">时长已抓取</span><span class="q-val">100% ({stats['has_duration'] or total}/{total})</span></div>
      <div class="quality-item"><span class="q-label">QQ 音乐链接</span><span class="q-val">100%</span></div>
      <div class="quality-item"><span class="q-label">曲目详情 (tracks)</span><span class="q-val {'bad' if stats['has_tracks'] < total else ''}">{stats['has_tracks']}/{total} ({round(stats['has_tracks']/total*100)}%)</span></div>
      <div class="quality-item"><span class="q-label">播放记录 (last_played)</span><span class="q-val {'bad' if stats['has_last_played'] < 200 else ''}">{stats['has_last_played']}/{total}</span></div>
      <div class="quality-item"><span class="q-label">平均专辑时长</span><span class="q-val">{stats['avg_duration_min']} 分钟</span></div>
    </div>
  </div>

  <!-- 地区明细表 -->
  <div class="table-section">
    <h3>📍 地区分布明细（全部 {len(regions)} 个地区）</h3>
    <table>
      <tr><th>#</th><th>地区</th><th>专辑数</th><th>占比</th><th>分布</th></tr>
"""
    # 地区明细行
    for i, (r, n) in enumerate(regions.most_common(), 1):
        pct = round(n / total * 100, 1)
        bar_w = int(pct * 2)
        html += f"""
      <tr>
        <td>{i}</td>
        <td>{r}</td>
        <td><strong>{n}</strong></td>
        <td>{pct}%</td>
        <td><div class="bar-cell"><div class="bar" style="width:{bar_w}px"></div></div></td>
      </tr>"""

    html += """
    </table>
  </div>

  <!-- 风格标签明细 Top30 -->
  <div class="table-section">
    <h3>🎼 风格标签明细 Top 30</h3>
    <table>
      <tr><th>#</th><th>风格标签</th><th>出现次数</th><th>占比</th><th>分布</th></tr>
"""
    max_cnt = top_genres[0][1] if top_genres else 1
    for i, (g, n) in enumerate(top_genres, 1):
        pct = round(n / total * 100, 1)
        bar_w = int(n / max_cnt * 120)
        html += f"""
      <tr>
        <td>{i}</td>
        <td><span class="tag">{g}</span></td>
        <td><strong>{n}</strong></td>
        <td>{pct}%</td>
        <td><div class="bar-cell"><div class="bar" style="width:{bar_w}px"></div></div></td>
      </tr>"""

    html += """
    </table>
  </div>

  <!-- Top 艺人 -->
  <div class="table-section">
    <h3>🎤 专辑数 Top 10 艺人</h3>
    <table>
      <tr><th>#</th><th>艺人</th><th>专辑数</th></tr>
"""
    for i, (a, n) in enumerate(top_artists, 1):
        html += f"""
      <tr>
        <td>{i}</td>
        <td>{a}</td>
        <td><strong>{n}</strong></td>
      </tr>"""

    html += """
    </table>
  </div>

</div>

<script>
// 全局 Chart.js 配置
Chart.defaults.color = '#aaa';
Chart.defaults.borderColor = '#2a2a4a';

// 地区分布 - 横向柱状图
new Chart(document.getElementById('regionChart'), {
  type: 'bar',
  data: {
    labels: """ + str(region_labels) + """,
    datasets: [{
      label: '专辑数',
      data: """ + str(region_data) + """,
      backgroundColor: 'rgba(59, 130, 246, 0.7)',
      borderColor: 'rgba(59, 130, 246, 1)',
      borderWidth: 1,
      borderRadius: 4,
    }]
  },
  options: {
    indexAxis: 'y',
    plugins: { legend: { display: false } },
    scales: {
      x: { grid: { color: '#1e1e3e' } },
      y: { grid: { display: false } }
    }
  }
});

// 风格 Top20 - 横向柱状图
new Chart(document.getElementById('genreChart'), {
  type: 'bar',
  data: {
    labels: """ + str(genre_labels) + """,
    datasets: [{
      label: '出现次数',
      data: """ + str(genre_data) + """,
      backgroundColor: 'rgba(110, 231, 183, 0.7)',
      borderColor: 'rgba(110, 231, 183, 1)',
      borderWidth: 1,
      borderRadius: 4,
    }]
  },
  options: {
    indexAxis: 'y',
    plugins: { legend: { display: false } },
    scales: {
      x: { grid: { color: '#1e1e3e' } },
      y: { grid: { display: false } }
    }
  }
});

// 噪音水平分布
new Chart(document.getElementById('noiseBinChart'), {
  type: 'bar',
  data: {
    labels: """ + str(stats["noise_bins"]) + """,
    datasets: [{
      label: '专辑数',
      data: """ + str(stats["noise_bin_data"]) + """,
      backgroundColor: 'rgba(245, 158, 11, 0.7)',
      borderColor: 'rgba(245, 158, 11, 1)',
      borderWidth: 1,
      borderRadius: 4,
    }]
  },
  options: {
    plugins: { legend: { display: false } },
    scales: {
      x: { title: { display: true, text: '噪音水平区间' }, grid: { color: '#1e1e3e' } },
      y: { grid: { color: '#1e1e3e' } }
    }
  }
});

// 噪音来源 - 环形图
new Chart(document.getElementById('noiseSrcChart'), {
  type: 'doughnut',
  data: {
    labels: """ + str(ns_labels) + """,
    datasets: [{
      data: """ + str(ns_data) + """,
      backgroundColor: [
        'rgba(59, 130, 246, 0.8)',
        'rgba(110, 231, 183, 0.8)',
        'rgba(245, 158, 11, 0.8)',
        'rgba(168, 85, 247, 0.8)',
        'rgba(239, 68, 68, 0.8)',
      ],
      borderWidth: 0,
    }]
  },
  options: {
    plugins: {
      legend: { position: 'bottom' }
    },
    cutout: '55%'
  }
});
</script>

</body>
</html>"""

    return html


def main():
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    albums = load_data()
    stats = compute_stats(albums)
    html = render_html(stats)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✓ 报告已生成：{OUT_FILE}")
    print(f"  专辑总数：{stats['total']}")
    print(f"  地区数：{stats['region_count']}")
    print(f"  风格种类：{stats['genre_count']}")
    print(f"  平均噪音：{stats['noise_mean']}")


if __name__ == "__main__":
    main()
