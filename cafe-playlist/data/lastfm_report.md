# Last.fm 批量标注结果报告
生成时间：2026-04-24 12:23

## 处理统计
- 总计处理：476 张
- ✅ 成功标注：351 张 (73.7%)
- ❌ 失败：62 张 (13.0%)
- ⏭️  跳过（大陆）：63 张 (13.2%)

## 失败原因分布
- no valid tags: 53 张
- Album not found: 9 张

## 标注的 genres 分布（Top 10）
1. pop: 74 张
2. Indie: 70 张
3. rock: 42 张
4. singer-songwriter: 37 张
5. folk: 35 张
6. indie-pop: 34 张
7. jazz: 30 张
8. electronic: 28 张
9. soul: 27 张
10. Alternative: 27 张

## 文件更新
- ✅ albums.json 已更新（noise_source 从 'estimated' 改为 'lastfm'）
- ✅ lastfm_log.json 已生成（完整处理日志）

## 后续建议
1. 手动处理 62 张失败的专辑（主要是 Last.fm 无数据）
2. 为跳过的 63 张大陆专辑寻找其他数据源（如网易云、QQ 音乐）
3. 运行 `python show.py --refresh` 刷新歌单生成缓存
