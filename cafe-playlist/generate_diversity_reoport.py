#!/usr/bin/env python3
"""
generate_diversity_report.py v2
生成专辑库多样性 HTML 报告（更新版，包含 Last.fm 标注数据）
"""
import json
from collections import Counter

# ============ 读取数据 ============
with open(r"f:\SystemPlayerInvestigation\cafe-playlist\data\albums.json", encoding="utf-8") as f:
    albums = json.load(f)

# ============ 统计数据 ============
total = len(albums)
has_genres = len([a for a in albums if a.get("genres")])
has_region = len([a for a in albums if a.get("region")])
has_duration = len([a for a in albums if a.get("duration")])

all_genres = []
for a in albums:
    all_genres.extend(a.get("genres", []))

genre_count = Counter(all_genres)
region_count = Counter(a.get("region", "未知") for a in albums)
source_count = Counter(a.get("noise_source", "unknown") for a in albums)

# 多样性指标
unique_genres = len(genre_count)
unique_regions = len(region_count)
gini_simpson = 1 - sum((count/total) ** 2 for count in genre_count.values())

# Top 数据
top_genres = dict(genre_count.most_common(15))
top_regions = dict(region_count.most_common(12))
source_data = dict(source_count)

# ============ 生成 HTML ============
html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>专辑库多样性报告 - 更新版</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f7fa; color: #333; padding: 20px; }
  .container { max-width: 1200px; margin: 0 auto; }
  h1 { text-align: center; color: #2c3e50; margin-bottom: 10px; }
  .subtitle { text-align: center; color: #7f8c8d; margin-bottom: 30px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 20px; }
  .card { background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
  .card h2 { font-size: 18px; color: #2c3e50; margin-bottom: 15px; border-bottom: 2px solid #3498db; padding-bottom: 8px; }
  .stat { display: flex; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #ecf0f1; }
  .stat:last-child { border-bottom: none; }
  .stat-name { color: #7f8c8d; }
  .stat-value { font-weight: bold; color: #2c3e50; }
  .big-number { font-size: 48px; font-weight: bold; color: #3498db; text-align: center; margin: 20px 0; }
  .diversity { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 12px; text-align: center; margin-bottom: 20px; }
  .diversity h2 { font-size: 24px; margin-bottom: 10px; }
  .diversity .score { font-size: 64px; font-weight: bold; }
  table { width: 100%; border-collapse: collapse; }
  th, td { padding: 10px; text-align: left; border-bottom: 1px solid #ecf0f1; }
  th { background: #f8f9fa; font-weight: 600; }
</style>
</head>
<body>
<div class="container">
  <h1>🎵 专辑库多样性报告（更新版）</h1>
  <p class="subtitle">生成时间：2026-04-24 | 数据来源：albums.json（Last.fm 标注后）| 总专辑数：528 张</p>
  
  <div class="grid">
    <div class="card">
      <h2>📊 基本统计</h2>
      <div class="big-number">""" + str(total) + """</div>
      <p style="text-align:center;color:#7f8c8d;">总专辑数</p>
      <div class="stat">
        <span class="stat-name">有 genres</span>
        <span class="stat-value">""" + str(has_genres) + """ (100%)</span>
      </div>
      <div class="stat">
        <span class="stat-name">有 region</span>
        <span class="stat-value">""" + str(has_region) + """ (""" + str(round(has_region/total*100, 1)) + """%)</span>
      </div>
      <div class="stat">
        <span class="stat-name">有 duration</span>
        <span class="stat-value">""" + str(has_duration) + """ (""" + str(round(has_duration/total*100, 1)) + """%)</span>
      </div>
    </div>
    
    <div class="diversity">
      <h2>多样性指数</h2>
      <div class="score">""" + str(round(gini_simpson, 3)) + """</div>
      <p>Gini-Simpson 指数（0=无多样性，1=完全多样性）</p>
      <div style="margin-top:20px;">
        <div style="display:flex; justify-content:space-between; margin:10px 0;">
          <span>唯一 genres</span>
          <span style="font-weight:bold;">""" + str(unique_genres) + """</span>
        </div>
        <div style="display:flex; justify-content:space-between; margin:10px 0;">
          <span>唯一 regions</span>
          <span style="font-weight:bold;">""" + str(unique_regions) + """</span>
        </div>
      </div>
    </div>
  </div>
  
  <div class="grid">
    <div class="card">
      <h2>🎵 Genre 分布（Top 15）</h2>
      <div style="height:300px;">
        <canvas id="genreChart"></canvas>
      </div>
    </div>
    
    <div class="card">
      <h2>🌍 Region 分布（Top 12）</h2>
      <div style="height:300px;">
        <canvas id="regionChart"></canvas>
      </div>
    </div>
  </div>
  
  <div class="grid">
    <div class="card">
      <h2>📂 数据来源分布</h2>
      <div style="height:300px;">
        <canvas id="sourceChart"></canvas>
      </div>
    </div>
    
    <div class="card">
      <h2>📋 Genre 详细列表（Top 20）</h2>
      <table>
        <tr><th>Genre</th><th>数量</th><th>占比</th></tr>"""

# 添加 genre 表格行
for g, c in genre_count.most_common(20):
    pct = round(c/total*100, 1)
    html += f"<tr><td>{g}</td><td>{c}</td><td>{pct}%</td></tr>"

html += """      </table>
    </div>
  </div>
</div>

<script>
// Genre 数据
const genreLabels = """ + str(list(top_genres.keys())) + """;
const genreData = """ + str(list(top_genres.values())) + """;

// Region 数据
const regionLabels = """ + str(list(top_regions.keys())) + """;
const regionData = """ + str(list(top_regions.values())) + """;

// Source 数据
const sourceLabels = """ + str(list(source_data.keys())) + """;
const sourceData = """ + str(list(source_data.values())) + """;

// Genre 分布图
new Chart(document.getElementById('genreChart'), {
  type: 'bar',
  data: {
    labels: genreLabels,
    datasets: [{
      label: '专辑数',
      data: genreData,
      backgroundColor: 'rgba(52, 152, 219, 0.8)'
    }]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } }
  }
});

// Region 分布图
new Chart(document.getElementById('regionChart'), {
  type: 'doughnut',
  data: {
    labels: regionLabels,
    datasets: [{
      data: regionData,
      backgroundColor: ['#3498db','#e74c3c','#2ecc71','#f39c12','#9b59b6','#1abc9c','#34495e','#95a5a6','#e67e22','#16a085','#8e44ad','#2c3e50']
    }]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { position: 'right' } }
  }
});

// 数据来源图
new Chart(document.getElementById('sourceChart'), {
  type: 'pie',
  data: {
    labels: sourceLabels,
    datasets: [{
      data: sourceData,
      backgroundColor: ['#3498db','#e74c3c','#2ecc71','#f39c12']
    }]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false
  }
});
</script>
</body>
</html>"""

# ============ 保存文件 ============
output_file = r"f:\SystemPlayerInvestigation\cafe-playlist\report\diversity_report_updated.html"
with open(output_file, "w", encoding="utf-8") as f:
    f.write(html)

print(f"✅ 报告已生成：{output_file}")
print(f"   总专辑数：{total}")
print(f"   多样性指数：{gini_simpson:.3f}")
print(f"   唯一 genres：{unique_genres}")
print(f"\n用浏览器打开查看完整报告！")
