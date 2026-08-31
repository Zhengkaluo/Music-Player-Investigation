# Music Player Investigation

这个目录目前包含四个相对独立的项目。它们都与音乐有关，但数据目标和运行环境不同，不应当作为一条连续流水线理解。

## 从这里开始

| 目录 | 用途 | 当前入口 | 状态 |
|---|---|---|---|
| `SongBase/` | 建设可搜索、可离线下载的歌曲曲库 | `manage_albums.py` | 活跃 |
| `cafe-playlist/` | 从专辑库自动编排咖啡店每日歌单 | `cafe_playlist.py` | 独立、活跃 |
| `Flowset-个人审美打标-Demo/` | 在浏览器中试听并进行个人审美标注 | `开始打标.html` | 独立 Demo |
| `webui/` | Windows“正在播放”悬浮界面的新版前端 | `webui_app.py` / `启动Web版.bat` | 独立、活跃 |

根目录的 `music_display_gui.py` 与 `get_music_powershell.py` 是旧版 Windows 桌面界面；`webui/` 是它的新实现。两者共享 `music_display_config.json`，但日常优先使用 Web 版。

## 已识别的旧版或重复入口

| 文件 | 与当前功能的关系 | 当前处理 |
|---|---|---|
| `music_display_gui.py` | 与 `webui/` 都显示 Windows 当前播放信息 | 保留旧版兼容，优先使用 `webui/` |
| `batch_download.py` | 为 Flowset 第二波测试下载样本，不属于 SongBase 下载流程 | 保留为历史批次工具 |
| `cafe-playlist/generate_diversity_reoport.py` | 文件名拼写错误，与 `generate_diversity_report.py` 功能重合 | 暂不运行，后续归档 |
| `SongBase/archive/legacy-link-search/find_official_links.py` | 与 `manage_albums.py links` 重合，但操作旧数据 | 已归档，详见 `SongBase/README.md` |

## 数据边界

- `SongBase/song_base_by_artist.json`：歌曲级曲库的当前主数据。
- `cafe-playlist/data/albums.json`：咖啡店编排使用的专辑级主数据。
- `Flowset-个人审美打标-Demo/Flowset-个人审美样本-*.json`：审美标注结果。
- `music_display_config.json`：正在播放悬浮界面的本地配置。

这四类数据用途不同，不建议合并成一个 JSON。

## 当前目录约定

- 下载得到的音乐放在 `SongBase/SongResources/`，不把新下载的 MP3 加入 Git。
- 自动生成的 HTML、Markdown 和进度文件是产物，不作为新的数据源继续编辑。
- `Notion Export/` 只保存原始导出；实际导入后由 `cafe-playlist/data/albums.json` 接管。
- 项目内仍有少量写死的本机绝对路径。移动脚本前应先改成相对路径。

## 建议的日常入口

### 更新歌曲曲库

```bash
python3 SongBase/manage_albums.py add
python3 SongBase/manage_albums.py links
python3 SongBase/sync_missing_audio.py
```

详细的数据关系和旧脚本说明见 `SongBase/README.md`。

### 生成咖啡店歌单

```bash
cd cafe-playlist
python3 cafe_playlist.py generate
```

完整说明见 `cafe-playlist/README.md`。

### 启动正在播放界面

在 Windows 上运行 `启动Web版.bat`。旧的 `启动.bat` 仍保留用于 tkinter 版本。

## 暂不自动处理的内容

- 不删除或移动已有音频。
- 不删除旧脚本，因为部分脚本之间仍存在硬编码调用。
- 不自动去重两个音频目录；当前已确认有 55 组完全相同的 MP3，重复副本约占 329 MB，清理前需要先决定哪个目录保留为唯一音频库。
