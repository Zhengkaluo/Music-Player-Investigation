# ☕ cafe-playlist — 咖啡店歌单自动编排系统

从 Notion 专辑库到每日歌单，一条命令搞定。

## 快速开始

```bash
cd cafe-playlist
pip install requests

# 1. 导入 Notion 导出的 CSV
python cafe_playlist.py import --csv "data\你的csv.csv"

# 2. 自动搜索 QQ 音乐 URL + 抓取时长
python cafe_playlist.py auto-url

# 3. 生成今天的歌单
python cafe_playlist.py generate
```

## 命令一览

| 命令 | 说明 | 示例 |
|------|------|------|
| `import --csv` | 导入 Notion CSV（默认合并，保留URL/时长） | `import --csv "data\x.csv"` |
| `import --replace` | 全量覆盖导入（⚠️ 会丢失已有数据） | `import --csv "data\x.csv" --replace` |
| `auto-url` | 自动搜索补全 QQ 音乐 URL + 时长 | `auto-url` / `auto-url --force` |
| `fetch-duration` | 单独抓取专辑时长 | `fetch-duration` / `--name "xxx"` |
| `generate` | 生成歌单 | `generate --date 2026-04-23 --prefer "jazz"` |
| `show` | 显示已生成歌单 | `show --date 2026-04-23` |
| `week` | 生成一周歌单（周一~周五） | `week --start 2026-04-20` |
| `stats` | 专辑库统计 | `stats` |
| `config` | 查看编排配置 | `config` |

## 日常更新

Notion 加了新专辑？两步搞定：

```bash
python cafe_playlist.py import --csv "data\新导出.csv"  # 合并导入
python cafe_playlist.py auto-url                         # 补全新增的URL
```

## 编排算法

四维评分（噪音匹配 35% + 风格偏好 25% + 轮播新鲜度 25% + 风格一致性 15%）+ 贪心填充，按 3 个时段（早上/中午/下午）排列，目标覆盖 09:00-18:00。

## 详细文档

→ 完整工作流、数据模型、API 参考见 [WORKFLOW.md](WORKFLOW.md)
