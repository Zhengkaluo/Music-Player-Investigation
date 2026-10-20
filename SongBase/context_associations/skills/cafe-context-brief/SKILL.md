---
name: cafe-context-brief
description: 为深圳景田咖啡店收集目标日期的歌单情景，结合当前曲库和人工标注提出候选、分段与前端手动配置，并返回报告及版本归档。用于生成歌单前的情景策展建议。
---

# 咖啡店每日情景建议

执行 [标准流程](../../BRIEF-WORKFLOW.md)，以 [报告模板](../../brief_template.md) 为输出骨架。门店标签与边界见 [关联库说明](../../README.md)，归档入口见 [报告索引](../../briefs/README.md)。

用户给日期即可开始；缺少非关键偏好时使用流程默认值并说明。相对日期以 Asia/Shanghai 的用户日期解释；出现明确日期冲突时先核实，其他资料核对可继续。

先调用本目录固定采集器 `python -B SongBase/context_associations/collect_context.py --date YYYY-MM-DD --output-dir NEW_VERSION/context-snapshot`。不要为常规采集临时让大模型上网找天气和历法；优先引用 `context.json`、`context.md`、`sources.json` 及 `raw/`。数据源失败、节气本地近似或天气覆盖不足时明确告知，缺失不可补猜。接着从有效标题扫描和当前曲库交集提出少量情景候选，不把 `pending` 关联视为自动获批。

先向用户确认日期、实际播放区间、曲库和最新 CD 来源，音乐段的 Tag、能量、曲线及宽容度，以及情景必选曲和开始窗口。用户明确确认配置或说“其他按建议”后才执行标准流程的脚本草稿分支：读取 FlowSystem 的 `.agents/skills/flowset-weekly/SKILL.md`，复用 `tools/weekly_playlist.mjs generate`，随后用 `report --draft draft.json --request request.json --context context-snapshot/context.json --output 完整歌单.html` 固定生成可试听页。`--context` 必须匹配本次日期、时间和时区；不匹配先重新采集。报告页可选择本地音频目录，不把播放成功或 CD 确认写成已完成。

每次完成给用户看的 Markdown 报告和可追溯的 evidence.json，并更新归档索引。对话中同时返回当日情景、候选特征、前端配置及文件链接，不能只贴归档路径。生成后交付草稿和试听页，页面逐首显示计划日期时间、主副 Tag、预测/绑定人工 ZMPD、综合/声学衔接成本与风险。

这是按请求执行的策展流程，不是定时任务。普通情景建议不默认运行排程；试生成不确认或清空 CD、不写回歌曲关联，不替用户导入 QQ。
