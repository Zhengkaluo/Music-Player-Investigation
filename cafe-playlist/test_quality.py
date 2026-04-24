"""歌单质量分析脚本"""
import json, os
from collections import Counter

playlist_dir = os.path.join(os.path.dirname(__file__), "playlists")
db_path = os.path.join(os.path.dirname(__file__), "data", "albums.json")

# Load all playlists
all_albums_per_day = {}
all_albums_flat = []
fill_stats = []

for f in sorted(os.listdir(playlist_dir)):
    if not f.endswith(".json"):
        continue
    data = json.load(open(os.path.join(playlist_dir, f), "r", encoding="utf-8"))
    date = data["date"]
    day_albums = []
    for slot in data["slots"]:
        for a in slot["albums"]:
            day_albums.append(a["name"])
            all_albums_flat.append(a["name"])
    all_albums_per_day[date] = day_albums
    s = data["summary"]
    fill_stats.append((date, s["total_albums"], s["actual_duration_display"],
                       s["target_duration_display"], s["fill_percentage"]))

# 1. Fill rate per day
print("=" * 60)
print("1. 每日填充率")
print("=" * 60)
for date, count, actual, target, pct in fill_stats:
    status = "OK" if 100 <= pct <= 115 else ("偏多" if pct > 115 else "不足")
    print(f"  {date}: {count}张, {actual}/{target} ({pct}%) [{status}]")

# 2. Album repetition across days
print()
print("=" * 60)
print("2. 跨天轮播分析（5天内重复情况）")
print("=" * 60)
album_counter = Counter(all_albums_flat)
repeated = {k: v for k, v in album_counter.items() if v > 1}
print(f"  总选取次数: {len(all_albums_flat)}")
print(f"  不同专辑数: {len(album_counter)}")
print(f"  出现 >1 次: {len(repeated)} 张")
print()
print("  Top 10 最常出现:")
for name, count in sorted(repeated.items(), key=lambda x: -x[1])[:10]:
    days = [d for d, albums in all_albums_per_day.items() if name in albums]
    print(f"    {name}: {count}次 -> {', '.join(days)}")

# 3. Coverage
all_db = json.load(open(db_path, "r", encoding="utf-8"))
all_names = {a["name"] for a in all_db}
selected_names = set(album_counter.keys())
never = sorted(all_names - selected_names)
print()
print(f"  库中共 {len(all_names)} 张, 被选 {len(selected_names)} 张, 从未出现 {len(never)} 张")
if never:
    print(f"  未被选专辑: {', '.join(never[:15])}{'...' if len(never) > 15 else ''}")

# 4. Per-day noise analysis
print()
print("=" * 60)
print("3. 噪音匹配分析（每个时段实际 vs 目标）")
print("=" * 60)
for f in sorted(os.listdir(playlist_dir)):
    if not f.endswith(".json"):
        continue
    data = json.load(open(os.path.join(playlist_dir, f), "r", encoding="utf-8"))
    print(f"  {data['date']}:")
    for slot in data["slots"]:
        noises = [a["noise_level"] for a in slot["albums"]]
        avg_noise = sum(noises) / len(noises) if noises else 0
        target = slot["target_noise"]
        in_range = sum(1 for n in noises if target[0] <= n <= target[1])
        print(f"    {slot['slot_name']}: 目标{target}, "
              f"均值{avg_noise:.1f}, "
              f"命中{in_range}/{len(noises)}")

# 5. Genre diversity
print()
print("=" * 60)
print("4. 每日风格多样性")
print("=" * 60)
for f in sorted(os.listdir(playlist_dir)):
    if not f.endswith(".json"):
        continue
    data = json.load(open(os.path.join(playlist_dir, f), "r", encoding="utf-8"))
    genres = set()
    for slot in data["slots"]:
        for a in slot["albums"]:
            genres.update(a.get("genres", []))
    print(f"  {data['date']}: {len(genres)} 种风格")

# 6. Consecutive day overlap
print()
print("=" * 60)
print("5. 相邻天重叠率")
print("=" * 60)
dates = sorted(all_albums_per_day.keys())
for i in range(1, len(dates)):
    prev = set(all_albums_per_day[dates[i-1]])
    curr = set(all_albums_per_day[dates[i]])
    overlap = prev & curr
    print(f"  {dates[i-1]} -> {dates[i]}: "
          f"重叠 {len(overlap)}/{len(curr)} 张 "
          f"({len(overlap)/len(curr)*100:.0f}%)"
          f"{' -> ' + ', '.join(sorted(overlap)) if overlap else ''}")
