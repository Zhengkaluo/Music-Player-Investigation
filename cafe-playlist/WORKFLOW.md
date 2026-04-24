# ☕ 咖啡店歌单自动编排系统 — 完整工作流

> 本文档供 AI Agent 读取，详细描述了系统的架构、数据流、所有 CLI 命令、核心算法和日常操作流程。

---

## 1. 系统概述

为咖啡店自动编排每日播放歌单（09:00-18:00），基于专辑库中的音乐风格、噪音程度、播放历史等维度，使用四维评分 + 贪心填充算法，按时段安排合适的专辑。

**核心能力**：
- 从 Notion 多维表格导入专辑元数据
- 自动从 QQ 音乐搜索补全专辑 URL 和时长
- 按时段 + 四维评分生成每日/每周歌单
- 播放历史轮播避免重复

---

## 2. 项目结构

```
cafe-playlist/
├── cafe_playlist.py          # CLI 主入口（所有命令的入口）
├── album_db.py               # 专辑数据库管理（导入/查询/更新/统计）
├── scheduler_engine.py       # 歌单编排核心引擎（评分/填充/生成）
├── duration_fetcher.py       # QQ 音乐时长抓取（搜索/API/批量）
├── scheduler_config.json     # 编排配置（时段/权重/风格噪音映射）
├── data/
│   ├── albums.json           # 📦 专辑数据库（唯一数据源）
│   ├── play_history.json     # 📅 播放历史记录
│   └── *.csv                 # Notion 导出的 CSV 文件
└── playlists/
    └── YYYY-MM-DD.json       # 已生成的每日歌单
```

---

## 3. 数据模型

### 3.1 专辑记录 (`albums.json` 中的单条)

```json
{
  "name": "downt",                    // 专辑名（主键，用于去重）
  "artist": "downt",                  // 艺人/乐队
  "genres": ["ambient", "electronic"],// 风格标签列表
  "region": "日本",                   // 地区
  "noise_level": 3.0,                // 噪音程度（1-7，越大越吵）
  "noise_source": "manual",          // 噪音来源：manual/estimated/default
  "swing_rate": null,                 // 摇摆速率（可选）
  "burden_level": null,               // 负担程度（可选）
  "last_played": "2026-04-22",       // 上次播放日期
  "qq_music_url": "https://y.qq.com/n/ryqq/albumDetail/0035hRPf3HUqu6",
  "qq_music_album_mid": "0035hRPf3HUqu6",
  "duration_seconds": 1337,           // 专辑总时长（秒）
  "tracks": [                         // 每首歌的名称+时长
    {"name": "no title", "duration": 84},
    {"name": "track 2", "duration": 120}
  ]
}
```

**关键字段说明**：

| 字段 | 来源 | 说明 |
|------|------|------|
| `name` | Notion CSV | **主键**，合并导入时按此去重 |
| `artist` | Notion CSV | 用于 QQ 音乐搜索匹配 |
| `genres` | Notion CSV | 逗号分隔字符串，自动拆为列表 |
| `noise_level` | Notion CSV 或自动估算 | 若 CSV 未填，先从 `genre_noise_map` 估算，否则默认 4.0 |
| `noise_source` | 自动判定 | `manual`=用户填写, `estimated`=风格估算, `default`=兜底 |
| `qq_music_url` | `auto-url` 命令抓取 | QQ 音乐专辑页 URL |
| `qq_music_album_mid` | 从 URL 解析 | QQ 音乐内部专辑 ID |
| `duration_seconds` | `auto-url`/`fetch-duration` 抓取 | 专辑总时长（秒） |
| `tracks` | `auto-url`/`fetch-duration` 抓取 | 曲目列表 `[{name, duration}]` |

### 3.2 播放历史 (`play_history.json`)

```json
{
  "2026-04-22": {
    "albums": [
      {"name": "downt", "slot": "早上", "duration_seconds": 1337},
      ...
    ],
    "generated_at": "2026-04-22T16:40:46.123456"
  }
}
```

### 3.3 歌单输出 (`playlists/YYYY-MM-DD.json`)

```json
{
  "date": "2026-04-22",
  "generated_at": "...",
  "config_snapshot": { "business_hours": {...}, "weights": {...}, "style_preferences": [] },
  "summary": {
    "total_albums": 15,
    "target_duration_seconds": 32400,
    "actual_duration_seconds": 31200,
    "target_duration_display": "9h00m",
    "actual_duration_display": "8h40m",
    "fill_percentage": 96.3
  },
  "slots": [
    {
      "slot_name": "早上",
      "start": "09:00",
      "end": "11:00",
      "target_noise": [2, 4],
      "target_duration_seconds": 7200,
      "actual_duration_seconds": 7100,
      "albums": [
        {
          "name": "downt",
          "genres": ["ambient"],
          "noise_level": 3.0,
          "duration_seconds": 1337,
          "duration_display": "22:17",
          "score": 0.8234,
          "qq_music_url": "https://..."
        }
      ]
    }
  ]
}
```

---

## 4. 编排配置 (`scheduler_config.json`)

```json
{
  "business_hours": {"start": "09:00", "end": "18:00"},
  "time_slots": [
    {"name": "morning",   "label": "早上", "start": "09:00", "end": "11:00", "target_noise": [2, 4]},
    {"name": "midday",    "label": "中午", "start": "11:00", "end": "14:00", "target_noise": [4, 6]},
    {"name": "afternoon", "label": "下午", "start": "14:00", "end": "18:00", "target_noise": [3, 5]}
  ],
  "weights": {
    "noise": 0.35,       // 噪音匹配权重
    "style": 0.25,       // 风格偏好权重
    "freshness": 0.25,   // 轮播新鲜度权重
    "cohesion": 0.15     // 风格一致性权重
  },
  "style_preferences": [],    // 全局风格偏好（可被 CLI --prefer 覆盖）
  "default_duration": 2400,   // 缺失时长时的默认值（秒，40分钟）
  "exclude_albums": [],       // 排除的专辑名列表
  "seed": null,               // 随机种子（null=每次不同）
  "genre_noise_map": {        // 风格→噪音程度映射（1-7）
    "ambient": 1.5,
    "jazz": 3.0,
    "post-rock": 4.5,
    "math-rock": 5.5
    // ... 完整列表见文件
  }
}
```

**`genre_noise_map` 用途**：当 Notion CSV 中专辑未填写噪音程度时，系统自动从该映射表估算。多个风格取平均值。

---

## 5. 核心算法

### 5.1 四维评分

对每个候选专辑计算综合评分：

```
score = w_noise × noise_match + w_style × style_pref + w_fresh × freshness + w_cohesion × cohesion
```

| 维度 | 默认权重 | 算法 | 说明 |
|------|---------|------|------|
| **噪音匹配** | 0.35 | 高斯距离 | 专辑噪音越接近时段 `target_noise` 中心，得分越高 |
| **风格偏好** | 0.25 | 标签命中率 | 专辑风格标签命中偏好数量越多，得分越高；无偏好时中性分 0.5 |
| **轮播新鲜度** | 0.25 | 线性衰减 | 距上次播放天数越多分越高；从未播放满分 1.0；最近播放过 0.0 |
| **风格一致性** | 0.15 | Jaccard 相似度 | 与当天已选专辑风格标签的交集/并集比值 |

### 5.2 贪心填充

每个时段独立执行：
1. 过滤掉已选专辑和排除列表
2. 为所有候选专辑计算评分（+ 0~0.05 随机扰动）
3. 按评分降序排序
4. 依次选取，直到时段时长填满
5. 全天去重：同一张专辑不会出现在多个时段

### 5.3 噪音程度来源优先级

```
1. 用户在 Notion 中手动填写 → noise_source = "manual"
2. 从 genre_noise_map 估算 → noise_source = "estimated"（多风格取平均）
3. 默认值 4.0 → noise_source = "default"
```

---

## 6. CLI 命令参考

所有命令通过 `python cafe_playlist.py <command>` 调用。

### 6.1 `import` — 导入专辑数据

```bash
# 合并导入（默认）：保留已有 URL/时长/tracks
python cafe_playlist.py import --csv "data\xxx.csv"

# 替换导入：清空重写（⚠️ 会丢失已有URL/时长）
python cafe_playlist.py import --csv "data\xxx.csv" --replace

# 从 JSON 导入
python cafe_playlist.py import --json "data\xxx.json"
```

**合并模式行为**：

| 场景 | 行为 |
|------|------|
| CSV 有新专辑 | ➕ 新增（需跑 `auto-url` 补 URL） |
| CSV 有已存在专辑 | 🔄 更新 Notion 字段（genres/noise 等），**保留** URL/时长/tracks/album_mid |
| 旧数据中有但 CSV 没有 | 📊 统计告知数量，实际从库中移除 |

**CSV 格式要求**：Notion 导出的 CSV（UTF-8 with BOM），支持的列名映射：

| Notion 列名 | 标准字段 |
|-------------|---------|
| 专辑名 / Name / name | `name` |
| 歌手/乐队 / 歌手 / 艺人 / Artist | `artist` |
| 音乐类型+特点 / 音乐类型 / genres | `genres`（逗号分隔） |
| 地区 / region | `region` |
| 噪音程度 / noise_level | `noise_level`（1-7 数值） |
| 摇摆速率 / swing_rate | `swing_rate` |
| 负担程度 / burden_level | `burden_level` |
| 上一轮店里放 / last_played | `last_played`（日期） |
| URL / url / qq_music_url | `qq_music_url` |

### 6.2 `auto-url` — 自动搜索补全 QQ 音乐 URL + 时长

```bash
# 只补缺失的
python cafe_playlist.py auto-url

# 强制重新搜索所有（包括已有URL的）
python cafe_playlist.py auto-url --force
```

**搜索策略（按优先级）**：
1. `"专辑名 艺人名"` → 新版搜索 API（search_type=8 专辑搜索）
2. `"艺人名 专辑名"` → 新版搜索 API（换顺序）
3. `"专辑名"` → 新版搜索 API（仅专辑名）
4. 旧版 `client_search_cp` 接口（兜底）
5. 歌曲搜索反查专辑（最后手段）

**匹配规则**：不盲取第一个结果。使用 `_pick_best_album()` 做智能匹配：
- 优先：专辑名 + 艺人名 都匹配
- 次之：艺人名匹配
- 兜底：专辑名匹配
- 匹配时忽略大小写和标点（`_normalize_for_compare`）

**限速**：每次请求间随机延迟 1.5~3.0 秒，防封。

### 6.3 `fetch-duration` — 单独抓取时长

```bash
# 批量：只抓缺失的
python cafe_playlist.py fetch-duration

# 批量：强制重新抓取
python cafe_playlist.py fetch-duration --force

# 单张专辑
python cafe_playlist.py fetch-duration --name "downt"
```

**API 双通道**：
1. `musicu.fcg` 新版接口（POST JSON）→ 获取 songList + interval
2. `fcg_v8_album_detail_cp` 旧版接口（GET 参数）→ 获取 list + interval

### 6.4 `generate` — 生成歌单

```bash
# 生成今天的
python cafe_playlist.py generate

# 指定日期
python cafe_playlist.py generate --date 2026-04-23

# 带风格偏好
python cafe_playlist.py generate --prefer "R&B,jazz"

# 指定随机种子（可复现）
python cafe_playlist.py generate --seed 42

# dry-run（不更新播放历史）
python cafe_playlist.py generate --dry-run
```

**输出**：
- 保存歌单到 `playlists/YYYY-MM-DD.json`
- 更新 `play_history.json`
- 更新专辑的 `last_played` 字段
- 终端打印格式化歌单

### 6.5 `show` — 显示已生成的歌单

```bash
python cafe_playlist.py show                    # 今天
python cafe_playlist.py show --date 2026-04-23  # 指定日期
```

### 6.6 `week` — 生成一周歌单

```bash
python cafe_playlist.py week                    # 本周一~周五
python cafe_playlist.py week --start 2026-04-20 # 指定起始日期
python cafe_playlist.py week --prefer "jazz"    # 带风格偏好
python cafe_playlist.py week --dry-run          # 不更新历史
```

### 6.7 `stats` — 专辑库统计

```bash
python cafe_playlist.py stats
```

输出：总数、风格类型数、地区、时长覆盖率、URL覆盖率、噪音来源分布、所有风格标签。

### 6.8 `config` — 查看当前配置

```bash
python cafe_playlist.py config
```

---

## 7. 日常操作工作流

### 7.1 首次初始化

```bash
cd cafe-playlist

# Step 1: 从 Notion 导出 CSV，放入 data/ 目录

# Step 2: 导入专辑数据
python cafe_playlist.py import --csv "data\你的csv.csv"

# Step 3: 自动搜索 QQ 音乐 URL + 抓取时长（耗时较长，1-3秒/专辑）
python cafe_playlist.py auto-url

# Step 4: 检查统计，确认 URL 和时长覆盖率
python cafe_playlist.py stats

# Step 5: 生成歌单
python cafe_playlist.py generate
# 或生成一周
python cafe_playlist.py week
```

### 7.2 Notion 新增专辑后更新

```bash
# Step 1: 从 Notion 导出新的 CSV

# Step 2: 合并导入（自动保留已有 URL/时长）
python cafe_playlist.py import --csv "data\新导出.csv"

# Step 3: 如有新增专辑，补全 URL
python cafe_playlist.py auto-url

# Step 4: 重新生成歌单
python cafe_playlist.py generate
```

### 7.3 每日/每周歌单生成

```bash
# 每日
python cafe_playlist.py generate

# 每周（周一到周五）
python cafe_playlist.py week

# 想要某种风格多一些
python cafe_playlist.py generate --prefer "ambient,jazz"
```

### 7.4 排除某张专辑

编辑 `scheduler_config.json`，在 `exclude_albums` 中添加专辑名：

```json
{
  "exclude_albums": ["不想放的专辑名"]
}
```

### 7.5 调整评分权重

编辑 `scheduler_config.json` 的 `weights` 部分：

```json
{
  "weights": {
    "noise": 0.35,      // 增大→更严格按噪音匹配时段
    "style": 0.25,      // 增大→更偏向 style_preferences 中的风格
    "freshness": 0.25,  // 增大→更倾向选最近没放过的专辑
    "cohesion": 0.15    // 增大→当天风格更统一
  }
}
```

### 7.6 添加新风格的噪音映射

编辑 `scheduler_config.json` 的 `genre_noise_map`：

```json
{
  "genre_noise_map": {
    "新风格名": 3.5
  }
}
```

---

## 8. 模块 API 参考

### 8.1 `album_db` 模块

```python
# 数据读写
album_db.load_albums() -> list[dict]         # 读取全部专辑
album_db.save_albums(albums: list[dict])      # 写入全部专辑
album_db.load_play_history() -> dict          # 读取播放历史
album_db.save_play_history(history: dict)     # 写入播放历史

# 导入
album_db.import_from_csv(csv_path, merge=True) -> (new, updated, removed)
album_db.import_from_json(json_path, merge=True) -> (new, updated, removed)

# 查询
album_db.find_album(name: str) -> dict | None
album_db.find_albums_by_genre(genre: str) -> list[dict]
album_db.get_albums_without_duration() -> list[dict]
album_db.get_album_stats() -> dict

# 更新
album_db.update_album(name, updates: dict) -> bool
album_db.update_album_duration(name, duration_seconds, tracks=None) -> bool
album_db.update_last_played(album_names: list, date_str: str)

# 工具函数
album_db.extract_album_mid(url: str) -> str | None
album_db.estimate_noise_from_genres(genres: list, genre_noise_map=None) -> float | None
```

### 8.2 `scheduler_engine` 模块

```python
# 核心
scheduler_engine.generate_playlist(
    date_str=None,              # YYYY-MM-DD，默认今天
    style_overrides=None,       # 临时风格偏好列表
    seed=None,                  # 随机种子
    verbose=True,               # 打印详情
) -> dict                       # 返回歌单字典

# 辅助
scheduler_engine.save_playlist(playlist) -> filepath
scheduler_engine.load_playlist(date_str) -> dict | None
scheduler_engine.update_play_history(playlist)
scheduler_engine.format_playlist(playlist) -> str

# 评分（内部调用）
scheduler_engine.compute_score(album, slot, config, today, selected_genres, play_history) -> float
scheduler_engine.load_config() -> dict
```

### 8.3 `duration_fetcher` 模块

```python
# 搜索
duration_fetcher.search_album(album_name, artist="") -> str | None  # 返回 album_mid

# 抓取详情
duration_fetcher.fetch_album_detail_by_mid(album_mid) -> dict | None
# 返回: {"album_name", "singer", "total_tracks", "duration_seconds", "tracks"}

# 批量操作
duration_fetcher.fetch_all_durations(force=False, verbose=True) -> (success, fail, skip)
duration_fetcher.fetch_single_duration(album_name, verbose=True) -> bool
duration_fetcher.auto_fill_urls(verbose=True, force=False) -> (found, not_found, skipped)

# URL 解析
duration_fetcher.extract_album_mid_from_url(url) -> str | None
```

---

## 9. 数据流图

```
┌─────────────┐     import --csv      ┌──────────────┐     auto-url      ┌──────────────┐
│ Notion CSV  │ ──────────────────── → │  album_db.py │ ────────────── → │  QQ 音乐 API │
│ (手动导出)   │     (合并/替换)        │              │   search_album   │  musicu.fcg   │
└─────────────┘                        │  albums.json │ ← ────────────── │  album_detail │
                                       │              │   URL + 时长      └──────────────┘
                                       └──────┬───────┘
                                              │
                                    generate  │  读取专辑库 + 播放历史
                                              ▼
                                       ┌──────────────────┐
                                       │ scheduler_engine  │
                                       │                  │
                                       │ 1. 加载配置       │
                                       │ 2. 按时段遍历     │
                                       │ 3. 四维评分排序    │
                                       │ 4. 贪心填充       │
                                       │ 5. 输出歌单       │
                                       └────────┬─────────┘
                                                │
                                    ┌───────────┼───────────┐
                                    ▼           ▼           ▼
                              playlists/    play_history   albums.json
                              YYYY-MM-DD      .json       (更新 last_played)
                                .json
```

---

## 10. 环境依赖

- **Python**: 3.10+（已验证 3.13.5）
- **pip 包**: `requests`（QQ 音乐 API 调用）
- **终端 emoji**: Windows 下需 `$env:PYTHONIOENCODING="utf-8"`
- **网络**: 需要访问 `y.qq.com` / `c.y.qq.com` / `u.y.qq.com`

```bash
pip install requests
```

---

## 11. 常见问题

### Q: 导入后 URL/时长丢失了？
A: 你可能用了 `--replace`。默认合并模式（不加 `--replace`）会保留已有的 URL/时长。

### Q: `auto-url` 有些专辑找不到？
A: QQ 音乐可能未收录该专辑。终端会列出未找到的列表，需要手动在 QQ 音乐搜索并补上 URL，或接受该专辑使用默认时长（40分钟）。

### Q: 生成的歌单时长不够？
A: 检查 `stats` 看有多少专辑有时长数据。没有时长的专辑会使用 `default_duration`（默认2400秒=40分钟）。也可以在 `scheduler_config.json` 中调整此值。

### Q: 每次生成歌单都一样？
A: 检查是否设置了固定 `seed`。设为 `null` 每次结果都不同（有随机扰动）。

### Q: 想让某个风格出现更多？
A: 用 `--prefer` 参数：`generate --prefer "jazz,ambient"`，或编辑 `scheduler_config.json` 的 `style_preferences`。

---

## 12. QQ 音乐 API 备忘

| 接口 | URL | 用途 |
|------|-----|------|
| musicu.fcg (新版) | `https://u.y.qq.com/cgi-bin/musicu.fcg` | 专辑详情、搜索（POST JSON） |
| album_detail_cp (旧版) | `https://c.y.qq.com/v8/fcg-bin/fcg_v8_album_detail_cp.fcg` | 专辑详情（GET 参数） |
| client_search_cp (旧版) | `https://c.y.qq.com/soso/fcgi-bin/client_search_cp` | 搜索（GET 参数） |

**请求头必须带**：
```
Referer: https://y.qq.com/
User-Agent: Chrome/120.0.0.0
```

**限速**：每次请求间 1.5~3.0 秒随机延迟。
