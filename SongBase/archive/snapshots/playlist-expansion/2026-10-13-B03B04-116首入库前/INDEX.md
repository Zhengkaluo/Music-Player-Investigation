# SongBase 文件索引

本索引只说明文件职责；曲库主数据与音源不因整理而改变。

## 当前主线（根目录）

| 分类 | 文件 | 用途 |
|---|---|---|
| 曲库主数据 | `song_base_by_artist.json` | 当前歌曲级曲库唯一主数据。 |
| 正式标签 | `song_tags.json` | 以 `qq:<MID>` 为键的人工确认标签。 |
| 候选与规则 | `song_tag_candidates.json`、`song_tag_mapping.json` | 复核证据与长期映射规则。 |
| 本地音源 | `SongResources/` | 当前唯一音源目录；Flowset 通过软链接引用。 |
| 当前工具 | `manage_albums.py`、`sync_missing_audio.py`、`serve_songbase.py`、`archive_discarded_tracks.py`、`import_recording_delivery.py`、`import_combined_annotations.py`、`update_report_snapshots.py`、`build_annotation_gap_report.py` | 维护曲库、同步/导入音源、启动试听、归档舍弃、导入联合 Tag + ZMPD 标注，以及刷新统计与联合缺口报告。 |
| 生成页面 | `song_base_browser.html`、`song_tags_browser.html`、`song_manual_tagging.html`、`song_combined_annotation.html` | 由对应 `build_*` 脚本生成。 |

## 补录与运行状态

- `imports/`：曲目元数据导入、补录与重录的 JSON/Markdown 清单，以及保留的已验收音源。清单至少记录 QQ MID、来源和处理状态；涉及音频文件时再记录目标文件和 SHA-256。
- `待录制清单.json`、`待录制清单.md`：当前主库缺本地音源的逐曲核对结果；严格分开可进入 QQ 录制的曲目与已确认下架曲目，并保留建议批次。
- `待重录清单.json`：用户明确指定的待重录曲目；保留 QQ MID、来源链接、目标文件与任务状态，不等同于归档舍弃或错误音源记录。
- `待舍弃归档清单.json`：用户明确指定、尚未实际归档的舍弃任务；仅作待办记录，不等同于 `archive/removed_tracks/` 中已执行的归档。
- `runtime/history/`：已结束任务的运行状态快照；新的同步运行会在根目录生成新的运行状态文件。

### 当前录制入库状态（2026-10-12）

本轮116首元数据和音源已写入主库与`SongResources/`；113首自动验收、3首人工认可例外、4首裁去最后1秒。逐曲QQ MID、来源、完整署名、目标路径与SHA-256见`imports/2026-10-12-歌单补充116首元数据导入.json/.md`和`imports/2026-10-12-歌单补充116首正式入档.json/.md`。当前本地可播1,434首，待录制0首、待入库0首；主库3首已下架缺源保持不变。候选2首下架未入库，另350首候选未录制，见`reviews/468首候选曲目录制与入库进度-2026-10-12.json/.md`。

### 当前标注状态（2026-10-12）

主库1,437首、535位主艺人分组；正式Tag1,215首，当前候选0首，无正式Tag或候选222首。SongBase可匹配历史人工ZMPD434首，训练manifest仍为477条记录、467首合格真值。联合待标队列1006首：219首两者都缺、3首只缺Tag、784首只缺ZMPD。新增曲目不伪造标签或真值；当前1204首特征库未扩充。

## 归档

- `archive/removed_tracks/`：唯一的“归档舍弃”路径，包含被舍弃曲目记录与其音源。
- `archive/incorrect_audio/`：保留曲目的错误本地音频，与舍弃曲目严格分开。
- `archive/replaced_audio/`：重录替换前的旧音源备份；按批次保存，并由 `imports/` 中的替换清单记录新旧 SHA-256。
- `archive/snapshots/`：归档操作前的主曲库、正式标签和候选标签快照。
- `archive/manual-pending-download/`：已退役的固定清单下载流程。
- `archive/legacy-link-search/`、`archive/legacy-monitors/`、`archive/broken-download-pipeline/`：只供追溯的旧工具。

## 历史参考资料（仍在根目录）

- `qqmusic_playlists.json`、`qqmusic_playlists.md`：10份QQ歌单来源档案、2695条歌单成员记录（未跨单去重）；保留曲序、QQ MID与分享链接。2026-10-12新增咖啡厅和可以放完整快照，不代表全部已入主库。
- `song_tag_candidate_report.md`：候选生成器的报告输出；内容日期由候选生成任务决定。
- `曲库风格与语种报告.md`：基于当前主库与正式标签的统计快照，不是主数据；语种部分会随正式标签覆盖度更新。
- `咖啡店曲库_50张专辑扩充建议.md`：历史扩充建议，不是当前主数据。

## 日常入口

1. 曲库条目与外链：`manage_albums.py`
2. 本地音源缺失扫描/下载：`sync_missing_audio.py`
3. 已核验补录：`import_supplemental_audio.py`
4. 标签浏览页重建：`build_song_tags_browser.py`
5. 联合 Tag + ZMPD 导入：`import_combined_annotations.py`
6. 页面试听：`serve_songbase.py`
7. 曲目归档舍弃：`archive_discarded_tracks.py`
