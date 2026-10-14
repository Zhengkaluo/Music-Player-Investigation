# SongBase 曲库维护说明

## 当前主线

`song_base_by_artist.json` 是当前歌曲级曲库的唯一主数据。推荐的数据流是：

```text
new_albums_config.json
        │
        ▼
manage_albums.py add
        │
        ▼
song_base_by_artist.json
        │
        ├── manage_albums.py links ── 补 YouTube / Bilibili 链接
        ├── build_song_base_browser.py ── 生成 song_base_browser.html
        ├── song_tags.json ── 按 QQ Music MID 维护歌曲标签
        ├── build_song_tags_browser.py ── 生成 song_tags_browser.html
        └── manage_albums.py ── 重建 song_base_by_artist.md
```

`SongResources/` 是本地下载音频目录，不是曲库主数据。

### 归档舍弃

“舍弃”统一表示“归档舍弃”：完整记录写入
`archive/removed_tracks/discarded_tracks.json`，已有本地音频移入同一目录；
曲目同时从 `song_base_by_artist.json`、`song_tags.json` 和
`song_tag_candidates.json` 移除，因此不会再出现在两个主浏览页中。

单首操作必须同时提供 QQ MID、艺人和曲名：

```bash
python3 SongBase/archive_discarded_tracks.py \
  --track-id qq:MID --artist "艺人" --title "曲名" --reason "人工复核舍弃"
```

脚本会自动备份主数据并重建 `song_base_browser.html`、
`song_tags_browser.html` 和归档查看页
`archive/removed_tracks/discarded_tracks_browser.html`。主浏览器构建程序也会检查
归档 MID；若归档曲目重新混入任一主 JSON，构建将直接失败。

## 文件分组

### 主数据与配置

| 文件 | 角色 |
|---|---|
| `song_base_by_artist.json` | 当前主数据，按艺人组织歌曲 |
| `song_tags.json` | 稀疏的歌曲标签数据；没有记录表示尚未标注 |
| `song_tag_mapping.json` | 平台原始标签 → SongTag 风格候选的长期映射规则 |
| `new_albums_config.json` | 待追加或待补链接的专辑清单 |
| `SongResources/` | 本地音频文件 |

### 当前可用入口

| 文件 | 职责 | 建议 |
|---|---|---|
| `manage_albums.py` | 添加专辑、补官方链接、查看进度 | 作为曲库维护主入口 |
| `build_song_base_browser.py` | 从主数据生成离线浏览页 | 保留，由主入口调用 |
| `build_song_tags_browser.py` | 合并曲库与标签，校验并生成标签浏览页 | 修改标签后运行 |
| `build_manual_tagging_browser.py` | 生成无候选曲目的逐首手动标注子页面 | 候选无法定类时使用 |
| `generate_song_tag_candidates.py` | 从公开平台生成只读标签候选与复核报告 | 批量标注前运行 |
| `song_tag_mapping_editor.html` | 可双击打开的离线映射规则编辑器 | 调整标签映射时使用 |
| `sync_missing_audio.py` | 自动比较曲库与本地音频、下载缺失项并显示监控页面 | 作为当前音频同步入口 |
| `archive_discarded_tracks.py` | 将曲目统一归档舍弃并从全部主数据移除 | 舍弃曲目的唯一入口 |
| `batch_down_pending.py` | 下载旧 `_pending_downloads.txt` 固定批次 | 仅保留为手动批次工具 |

### 维护歌曲标签

标签单独保存在 `song_tags.json`，使用 QQ 音乐歌曲 MID 作为键。文件采用稀疏结构：

- `tracks` 中存在记录，表示这首歌已经完成标签判断；
- `tracks` 中没有记录，表示尚未标注；
- `genre` 是唯一主风格，`secondary_genres` 是 0–2 个副风格；
- 副风格不可重复、不可与主风格相同，也不能超过两个；
- `language: null` 表示中文或英文歌曲不显示语言标签；
- `instrumental: false` 表示已判断为非器乐，不能用缺少记录代替。

单条标签示例：

```json
"qq:003jSlE31PQbqZ": {
  "genre": "Rock / Alternative",
  "secondary_genres": ["Electronic"],
  "language": null,
  "instrumental": false,
  "source": "manual",
  "updated_at": "2026-08-07",
  "note": ""
}
```

完成修改后运行；该命令也会同步刷新无候选手动标注子页面：

```bash
python3 SongBase/build_song_tags_browser.py
```

构建程序会先检查主风格、副风格、语言、器乐字段以及歌曲 ID；发现无效值时停止生成并指出具体记录。成功后打开 `SongBase/song_tags_browser.html`，可以查看标注完成率、主副风格合计分布，并按进度、风格、主风格范围、语言和器乐性筛选曲目。

标签浏览与候选纠错页都带有播放按钮。优先播放 `SongResources/` 中已同步的本地音频；若该曲尚未同步，按钮会打开它的 YouTube、Bilibili 或 QQ 音乐页面作为兜底。页面底部会显示当前曲目、播放/暂停与进度。

浏览器中的“候选纠错”页读取 `song_tag_candidates.json`，默认展示置信度 ≥65% 的风格候选。可逐首确认或改正主风格、选择最多两个副风格、补充语言和器乐性，并标明映射规则是正确、太宽泛、目标错误、缺少组合规则，还是来源不可靠。反馈先保存在浏览器本机，不会改写 `song_tags.json`、`song_tag_mapping.json` 或候选文件。

点击“导出纠错 JSON”会生成 `song_tag_corrections_YYYY-MM-DD.json`。其中保留曲目、原候选、命中的映射规则、原始平台证据及人工反馈；把这份文件交给 agent，即可据此总结哪些词应保留、降权、改目标或增补组合规则。

标签浏览器顶部的“无候选手动标注”进入独立子页面 `song_manual_tagging.html`。它只列出尚未正式标注、且没有形成主风格候选的曲目。主 Tag、副 Tag、语言、器乐状态和备注会自动作为草稿保存在当前浏览器本机；只有点击“完成本首并下一首”后，该曲才会计入完成进度与导出范围。完成一批后点击“导出已完成 JSON”，生成 `song_manual_tags_YYYY-MM-DD.json`，再交给 agent 写回正式库。该页面本身不会修改任何 JSON。

### 生成批量标签候选

先不要让外部平台的标签直接写入 `song_tags.json`。使用候选流程把原始依据、映射结果和置信度保存到独立文件，人工确认后再迁移到正式标签库：

```bash
# 固定随机种子抽样 50 首，访问 Last.fm 的曲目、专辑与艺人标签
python3 SongBase/generate_song_tag_candidates.py --sample-size 50 --seed 20260807

# 仅预览本次会抽到哪些歌曲，不访问网络
python3 SongBase/generate_song_tag_candidates.py --sample-size 50 --seed 20260807 --dry-run

# 映射规则调整后，用已保存的原始依据重算置信度和报告
python3 SongBase/generate_song_tag_candidates.py --refresh-existing
```

输出文件：

| 文件 | 作用 |
|---|---|
| `song_tag_candidates.json` | 每首抽样歌曲的候选标签、原始平台标签、置信度与错误信息 |
| `song_tag_candidate_report.md` | 便于人工浏览的候选报告 |

候选系统生成一个 `genre_candidate` 主风格和 0–2 个 `secondary_genre_candidates` 副风格。副风格必须至少得到 2 分、达到主风格得分的 45%，且有曲目、专辑或艺人平台标签的实际命中，不能仅由艺人先验产生。曲目级 Last.fm 标签优先，缺失时回退到专辑级、再回退到艺人级；艺人级候选的置信度会封顶为 65%，仅供复核，不应直接写入正式标签。系统也包含已知艺人中文名/外文名别名，用于改进跨语言曲库的查询命中率。

`song_tag_mapping.json` 是候选系统的映射事实来源，分为三类规则：

- `direct_rules`：例如 `shoegaze → Rock / Alternative`、`neo-soul → Jazz / Soul`；
- `combination_rules`：例如 `piano + ambient → Ambient / Neo-Classical`，避免把单一编制词误判为风格；
- `weak_terms`：例如 `piano`、`indie`、`pop`、`experimental`，记录为什么它们不能单独定类。
- `artist_review_policies`：艺人级的复核政策；可声明多个风格属于边界可接受，或让特定错误候选自动暂缓、禁止直接入库。

每条规则有 `proposed`、`verified` 或 `deprecated` 状态。人工复核候选后，应优先更新这里的规则和说明，再用 `--refresh-existing` 重算已有候选；不要为了单首歌曲直接改写正式标签。

### 在浏览器里维护映射规则

直接双击打开 `song_tag_mapping_editor.html`，再点击“选择 song_tag_mapping.json”。它可以增删和编辑直接映射、组合映射、弱信号词、忽略词与维护原则，无需启动服务或联网。

在支持 File System Access 的浏览器中（如 Chrome / Edge），选择文件时会授予本次会话的写入权限，点击“保存回本地文件”便会原位更新该 JSON。在其他浏览器中，点击保存会下载更新后的 `song_tag_mapping.json`；用它替换原文件即可。编辑器会在保存前校验必填字段、规则 ID、风格名、状态和分数范围。

完成一批规则调整后，运行：

```bash
python3 SongBase/generate_song_tag_candidates.py --refresh-existing
```

这只会重算候选与报告，仍不会自动写入正式标签库 `song_tags.json`。

### 同步缺失音频

直接运行：

```bash
python3 SongBase/sync_missing_audio.py
```

脚本会自动打开 `http://127.0.0.1:8766/`，页面显示：

- 曲库歌曲、有链接歌曲和本地音频数量；
- 待下载、正在下载、成功、失败和跳过数量；
- 当前歌曲、来源、专辑、进度、耗时、预计剩余时间和下载大小；
- 完整任务队列、筛选搜索和最近运行记录；
- “完成当前曲目后停止”按钮。

下载规则：

1. 只处理具有 `youtube` 或 `bilibili` 链接的曲目；
2. 根据“歌曲名 + 艺人名”比较 `SongResources/`，已有非空音频不会重复下载；
3. 优先使用 YouTube，失败后自动尝试 Bilibili；
4. 每首歌使用独立临时目录，完成后统一写入 `SongResources/`；
5. 下次运行会重新扫描，因此中断后可直接再次运行。

常用检查：

```bash
# 只查看缺失规模，不启动页面或下载
python3 SongBase/sync_missing_audio.py --scan-only

# 打开监控页面并模拟整个流程，不写入音频
python3 SongBase/sync_missing_audio.py --dry-run

# 只处理前 5 首，用于小批量验证
python3 SongBase/sync_missing_audio.py --limit 5
```

默认会自动寻找系统中的 `yt-dlp`、FFmpeg 和 Node.js；找不到时才使用当前电脑已有的兼容路径。可通过 `--yt-dlp`、`--ffmpeg` 和 `--node` 显式指定。

### 自动生成文件

| 文件 | 来源 |
|---|---|
| `song_base_by_artist.md` | `manage_albums.py` |
| `song_base_browser.html` | `build_song_base_browser.py` |
| `song_tags_browser.html` | `build_song_tags_browser.py` |
| `song_manual_tagging.html` | `build_manual_tagging_browser.py` |
| `song_tag_mapping.json` | `generate_song_tag_candidates.py` |
| `song_tag_candidates.json`、`song_tag_candidate_report.md` | `generate_song_tag_candidates.py` |
| `_search_progress.json`、`_search_live.txt` | 搜索/下载监控 |
| `SongResources/_download_log.txt` | 下载过程 |

不要手动编辑这些文件；应修改 JSON 主数据或配置后重新生成。

## 重合与历史脚本

### `archive/legacy-link-search/find_official_links.py`

它和 `manage_albums.py links` 都会：

- 搜索 YouTube 与 Bilibili；
- 判断频道是否属于艺人；
- 排除 Live、Cover、Remix 等版本；
- 把结果写回 JSON 并重建 Markdown。

区别是它操作旧数据 `qqmusic_playlists.json`，而 `manage_albums.py` 操作当前主数据 `song_base_by_artist.json`。它已经移入 archive，不再是当前主线的一部分。7 个 QQ 歌单数据暂留原位，供来源与历史报告追溯；其中“早上嗨着听”于 2026-09-15 补录。

### `archive/legacy-monitors/` 与 `manage_albums.py monitor`

两者都是链接搜索监控：

- 归档的 `_search_monitor.py` 生成进度 JSON，供旧的 `search_monitor.html` 使用；
- `manage_albums.py monitor` 自带 HTTP 页面和 `/data` 接口。

日常只使用后一套作为主入口。旧的搜索监控和下载监控均已归档。

### 下载脚本

旧的 `batch_download_youtube.py` 与配套 `downloadscripts/` 仍指向项目根部的 `SongResources/`，但实际目录已经是 `SongBase/SongResources/`。这组脚本已移入 `archive/broken-download-pipeline/`，不再作为主入口。

`batch_down_pending.py` 指向正确目录，可以继续使用。后续应把下载逻辑统一成一个带子命令的入口，再归档旧脚本。

当前已经新增 `sync_missing_audio.py` 作为自动同步入口。原有的
`gen_pending_downloads.py`、`batch_down_pending.py` 和 `download_monitor.py`
仍保持不变，组成旧的“生成固定清单 → 下载 → 单独监控”流程；不要与新入口同时启动，
尤其是两个监控默认都可能尝试使用端口 8766。新入口检测到端口占用时会自动改用空闲端口。

### `archive/legacy-monitors/_dl_monitor.py`

它把下载进度写入名为 `_search_progress.json` 的文件，会与搜索进度互相覆盖。它属于临时监控脚本，目前不建议与搜索任务同时运行。

## 与其他项目的关系

- `cafe-playlist/` 是专辑级排播系统，主数据是 `cafe-playlist/data/albums.json`；它不会读取本目录的歌曲级主数据。
- `Flowset-个人审美打标-Demo/` 是审美标注工具，只使用用户选择的本地音频。
- `webui/` 是正在播放界面，不参与曲库建设。

## 下一阶段整理建议

在不改变功能的前提下，建议按以下顺序继续：

1. 修正 `manage_albums.py` 的艺人别名匹配和中文标题过滤问题。
2. 将官方链接搜索规则抽成一个共享模块，停止复制两套实现。
3. 将所有绝对路径改成基于脚本目录的相对路径。
4. 确认旧 `qqmusic_playlists.*` 不再使用后，再决定是否归档旧数据。
5. 新同步入口稳定运行后，归档旧的固定清单下载与独立监控脚本。

旧搜索、旧监控和错误路径下载流程已整体归档；归档内的 `_watchdog.py` 等脚本仍保留原始硬编码，仅用于追溯。
