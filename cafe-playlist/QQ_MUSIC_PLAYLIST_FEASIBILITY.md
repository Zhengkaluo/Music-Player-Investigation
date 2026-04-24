# QQ 音乐歌单自动同步 — 可行性分析

## 结论先行

**✅ 完全可行。** 有一条成熟路径可以实现自动化：

> 用 Python 库 `qqmusic-api-python` 扫码登录 → 创建歌单 → 按编排结果添加歌曲 → 每天自动更新

---

## 方案对比

| 方案 | 可行性 | 难度 | 稳定性 | 推荐 |
|------|--------|------|--------|------|
| **A. qqmusic-api-python 库** | ✅ 完全可行 | ⭐⭐ 低 | ⭐⭐⭐⭐ 较高 | **🏆 推荐** |
| B. Selenium 网页版自动化 | ✅ 可行 | ⭐⭐⭐⭐ 高 | ⭐⭐ 低（页面常变） | ❌ |
| C. QQ 音乐官方 OpenAPI | ⚠️ 需审批 | ⭐⭐⭐ 中 | ⭐⭐⭐⭐⭐ 最高 | ❌ 个人用太重 |
| D. URL Scheme 调起客户端 | ⚠️ 只能打开歌单 | ⭐ 最低 | ⭐⭐⭐ | 可做辅助 |

---

## 推荐方案详解：qqmusic-api-python

### 基本信息

| 项 | 详情 |
|----|------|
| 库名 | `qqmusic-api-python` |
| PyPI | https://pypi.org/project/qqmusic-api-python/ |
| GitHub | https://github.com/L-1124/QQMusicApi (337⭐, 87 fork) |
| 最新版 | v0.5.2 (2026-04-18) |
| Python | ≥3.10 |
| 协议 | GPLv3+ |
| 特点 | 全异步、Pydantic v2、完整类型标注 |

### 可用 API（已确认源码）

| 操作 | 方法 | 需登录 | 说明 |
|------|------|--------|------|
| 创建歌单 | `SonglistApi.create(dirname)` | ✅ | 重名会自动加时间戳 |
| 删除歌单 | `SonglistApi.delete(dirid)` | ✅ | — |
| 添加歌曲 | `SonglistApi.add_songs(dirid, song_info)` | ✅ | `song_info=[(song_id, song_type)]`，已有不报错 |
| 删除歌曲 | `SonglistApi.del_songs(dirid, song_info)` | ✅ | 不存在不报错 |
| 获取歌单详情 | `SonglistApi.get_detail(songlist_id)` | ❌ | 支持分页 |
| 搜索歌曲 | `SearchApi` | ❌ | 可搜到 song_id |
| 登录 | `LoginApi` (扫码/Cookie) | — | QQ 扫码 → 拿 Credential |

### 实现思路

```
每日定时任务:
1. 加载 Credential（首次扫码，后续刷新 Cookie）
2. 读取当天歌单 JSON (playlists/2026-04-23.json)
3. 创建 QQ 音乐歌单（名称: "咖啡店 04-23 周三"）
4. 遍历歌单中的每张专辑:
   a. 用专辑的 qq_music_album_mid 拿到曲目列表
   b. 收集所有 (song_id, song_type) 
   c. 调用 add_songs 批量添加
5. 输出歌单链接，可选用 URL Scheme 直接调起播放
```

### 关键问题与解决

| 问题 | 解决方案 |
|------|---------|
| **登录态过期** | 首次扫码登录拿 Cookie → 存本地 → 定时用 `refreshLogin` 刷新 |
| **怎么拿 song_id** | 我们已有 `qq_music_album_mid` → 调专辑详情 API 拿所有曲目的 `song_id` |
| **song_type 是什么** | 普通歌曲固定传 `0` |
| **调用频率限制** | 每次添加歌曲间隔 1-2 秒，一天 14 张专辑约 150 首歌 < 5 分钟 |
| **歌单重复** | 可以先查现有歌单 → 有同名则清空重建 → 或直接覆盖 |

---

## 辅助方案 D: URL Scheme 一键播放

创建完歌单后，可生成 URL Scheme 直接调起 QQ 音乐客户端播放：

```
qqmusic://qq.com/ui/openDetail?p={"type":1,"id":歌单ID}
```

或通过网页链接：

```
https://y.qq.com/n/ryqq/playlist/歌单ID
```

在 Windows 上可以用 `os.startfile()` 或 `webbrowser.open()` 直接打开。

---

## 不推荐的方案

### B. Selenium 网页版自动化
- 2019 年有人做过（Selenium 同步网易云→QQ 音乐）
- 但 QQ 音乐网页版 2019→2026 改版多次，元素定位全部失效
- 登录框套 iframe，JS 动态渲染，维护成本极高
- 每次页面改版都要重写选择器

### C. QQ 音乐官方 OpenAPI
- 需要注册开发者账号 + 提交应用审核
- 面向企业级合作伙伴（智能音箱、车机等）
- 个人咖啡店歌单这种用途几乎不可能通过审核

---

## 实施计划

### 第一步：安装与登录验证（30分钟）
```bash
pip install qqmusic-api-python
```
写一个最小脚本：扫码登录 → 创建一个测试歌单 → 添加一首歌 → 验证成功

### 第二步：歌曲 ID 映射（1小时）
- 用已有的 `qq_music_album_mid` 批量获取每张专辑的曲目 `song_id` 列表
- 缓存到 `albums.json` 的 `tracks` 字段（部分已有）

### 第三步：sync-playlist 子命令（2小时）
新增 CLI 命令：
```bash
python cafe_playlist.py sync-playlist --date 2026-04-23
```
自动执行：读歌单 → 创建 QQ 音乐歌单 → 添加全部歌曲

### 第四步：每日自动化（可选）
- Windows 定时任务 / cron
- 每天早上 8:30 自动生成歌单 + 同步到 QQ 音乐

---

## 风险提示

1. **仅供个人学习使用** — 该库基于逆向工程，不是官方 SDK
2. **Cookie 可能过期** — 需要定期刷新，长期不刷新会失效
3. **频繁调用可能被风控** — 控制请求频率，别一口气添加上千首
4. **法律合规** — 不做商业用途，不涉及音乐文件下载/播放

---

*分析日期: 2026-04-22*
*数据来源: GitHub 源码、PyPI、官方开发者平台、社区文章*
