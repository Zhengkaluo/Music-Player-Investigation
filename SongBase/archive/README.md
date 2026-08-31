# SongBase Archive

这里保存已经退出当前主线、但暂时不删除的历史工具。归档文件用于追溯旧流程，不应直接作为日常入口运行。

## `removed_tracks/`：归档舍弃

这是 SongBase 唯一的“归档舍弃”路径。`discarded_tracks.json` 保存完整清单，
`discarded_tracks_browser.html` 用于离线查看；仍有本地音频的曲目也保存在该目录。

归档舍弃的含义是：曲目只保留在归档中，不得继续出现在
`song_base_by_artist.json`、`song_tags.json`、`song_tag_candidates.json`、
`song_base_browser.html` 或 `song_tags_browser.html`。

今后不要直接手改三个主 JSON 来舍弃曲目，应使用项目主线脚本：

```bash
python3 SongBase/archive_discarded_tracks.py \
  --track-id qq:MID --artist "艺人" --title "曲名" --reason "人工复核舍弃"
```

脚本会先按“艺人 + 曲名 + MID”核对，保存三个主 JSON 的操作前快照，
再更新归档清单、移动已有音频并重建三个浏览页。

## `legacy-link-search/`

旧版 `find_official_links.py` 操作 `SongBase/qqmusic_playlists.json`，功能已由当前的 `SongBase/manage_albums.py links` 接替。

旧脚本保留原始路径配置，因此从归档目录直接执行仍会修改旧的 QQ 歌单数据。

## `legacy-monitors/`

包含两套依赖静态 HTML 和进度 JSON 的旧监控：

- `_search_monitor.py` + `search_monitor.html`
- `_dl_monitor.py` + `dl_monitor.html`

当前链接搜索监控使用：

```bash
python3 SongBase/manage_albums.py monitor
```

## `broken-download-pipeline/`

包含旧版 `batch_download_youtube.py` 以及它的监控、看门狗和启动脚本。

这套流程被归档的原因：

- 输入仍是旧的 `qqmusic_playlists.json`；
- 输出路径写成项目根部的 `SongResources/`；
- 当前实际音频目录是 `SongBase/SongResources/`；
- 看门狗还通过绝对路径重新启动旧下载脚本。

当前自动同步入口是 `SongBase/sync_missing_audio.py`；旧的
`SongBase/batch_down_pending.py` 暂时保留用于固定清单批次。

## 恢复原则

如果以后需要恢复某个工具，应先：

1. 改成基于脚本位置计算路径；
2. 确认使用当前主数据 `song_base_by_artist.json`；
3. 确认输出统一写入 `SongBase/SongResources/`；
4. 增加一次小规模验证后再移出 archive。
