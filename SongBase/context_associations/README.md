# SongBase 标题情境关联扫描

本目录只建立歌曲标题的情境候选。不会修改曲库、曲风标签、播放历史或歌单，不调用天气、歌词或外部作品资料。

## 当前结果

首轮扫描日期：2026-10-12。输入实际 1,162 条歌曲记录，按 QQ MID 合并成 1,161 首唯一歌曲；重复记录原文保留，不修改主数据。当前规则版本：2026-10-12.3。

候选 100 首、115 条关联，其中 78 首至少有一条明确标题关联，22 首只有间接或歧义线索。没有命中的 1,061 首仍保留在扫描 JSON 中。

| 类别 | 候选歌曲 | 关联条数 |
|---|---:|---:|
| 四季 | 26 | 26 |
| 天气与体感 | 22 | 25 |
| 节日与纪念情境 | 2 | 2 |
| 月份与日期 | 18 | 24 |
| 二十四节气 | 1 | 1 |
| 时段与天光 | 36 | 37 |

不同类别可以命中同一首歌，表中歌曲数不能相加作为总候选数。节日类目前仅有泛假日、祝贺；本次标题检查未发现明确圣诞等具体节日候选。

2026-10-12 用户先排除冰意象、露水意象、毕业纪念，共移除 5 条关联，候选由 155 首、176 条变为 151 首、171 条。

随后排除云意象、雪意象、风意象、夜晚、天空意象（无天气判定）、月亮意象、黎明之前、黎明、无 AM／PM 的钟点候选、极光／曙光候选、泛光意象（无具体时段）。本次移除 56 条关联，更新为 100 首、115 条。

累计 14 类已加入 `policy.excluded_tags`；对应规则、同标签别名及语义初审已移除，扫描收口过滤确保以后重扫不会回流，包括解析器及语义附加项产生的候选。所有歌曲仍在曲库与全库扫描审计中，其他关联逐条比对未变。例如《Summer Nights》保留夏季，《Night Squall》保留风暴，《Morning Dew》保留早晨。

这次严格按列出的类别排除：月光、傍晚风歇、霜、日出、日落、早晨、明确 AM／PM 的钟点及白露／小雪等节气仍保留，不因名称接近而扩大删除范围。

## 文件

| 文件 | 作用 |
|---|---|
| [情境关联功能需求与歌单生成影响.md](F:/SystemPlayerInvestigation/SongBase/context_associations/情境关联功能需求与歌单生成影响.md) | 功能需求、计划流程、对歌单生成的理论影响及接入边界 |
| `scan_title_contexts.py` | 标准库全库扫描入口 |
| `title_context_rules.json` | 六类多语言词表与规则版本 |
| `title_context_semantic_reviews.json` | 本次 Agent 的标题语义初审与防误命中记录 |
| `title_context_report_template.html` | 无需服务或构建的静态报告模板 |
| `test_title_contexts.py` | 回归测试 |
| `scans/2026-10-12/title_context_report.html` | 可筛选、搜索的离线候选报告 |
| `scans/2026-10-12/title_context_report.md` | 全部候选与排除理由文字报告 |
| `scans/2026-10-12/title_context_candidates.json` | 全库审计、原始重复记录、标题证据与候选 |
| `scans/2026-10-12/title_context_candidates.csv` | 每行一条候选关联，UTF-8 BOM |

## 运行

仅用 Python 标准库，无新增依赖。Windows PowerShell 在工作区根目录执行：

```powershell
python -B -X utf8 "F:/SystemPlayerInvestigation/SongBase/context_associations/scan_title_contexts.py" --output-dir "F:/SystemPlayerInvestigation/SongBase/context_associations/scans/2026-10-12"
```

同一输出目录会覆盖生成文件；需要保留旧快照时指定新的 `--output-dir`。

```powershell
python -B -X utf8 "F:/SystemPlayerInvestigation/SongBase/context_associations/scan_title_contexts.py" --dry-run
python -B -X utf8 "F:/SystemPlayerInvestigation/SongBase/context_associations/test_title_contexts.py"
```

`--dry-run` 真正不写任何候选或报告，与其他项目同名选项的行为无关。

## 口径与边界

- `explicit`：词语或完整短语的标题关联明确，不证明歌词主题或播放适配。
- `indirect`：例如 Sakura 到春季、蝉到夏季，只作为补查线索。
- `ambiguous`：Fall、Indian Summer、Golden Hour 等存在其他词义，待用户复核。
- 所有关联 `review_status=pending`、`auto_lock_allowed=false`；所有触发建议 `enabled=false`。
- 标题、艺人仅用于定位已审阅记录，标签提取只看标题；艺人、专辑、音频不参与匹配。
- 所有证据保留原始标题、命中文字和原文字符位置。规范化用于检索，不改原标题。
- 使用 NFKC、大小写归一化与涉及规则的有限繁体字映射，不声称完整所有语言覆盖。
- 合作艺人段以及明确技术版本括号段被屏蔽；非技术版本的内容括号保留。
- 标题日期保留年份，日期不是发行日期，年度复现尚未配置。
- 不从月份推四季、从雨推悲伤，也不从标题意象直接推断实际天气。
- 同一词组产生的多个关联用于复核视图，不应在后续排序时机械累加，例如阵雨间歇转晴与雨、晴，或完整日期与月份。
- 太阳等意象不自动等同真实当地天气。无标题命中不代表歌词或创作背景没有关联。

## 后续复核

先浏览“明确标题关联”，再看“间接线索”和“语义待确认”。人工确认结果应独立保存，使用歌曲 ID 与情境标签定位；不要直接改扫描 JSON 或 CSV，也不要把候选直接写入正式曲风 Tag。

此轮未开发正式关联库写回、人工确认导入或浏览器锁曲能力。未来可在已确认关联上增加歌词、官方介绍和人工听感证据，再与运行时情境快照匹配。
