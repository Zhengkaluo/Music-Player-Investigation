# 咖啡店情景采集、策展与歌单生成

本目录负责生成前的情景事实和策展建议；FlowSystem 负责实际排程和试听结果页。其他 Agent 无需本次对话历史，先读本 README，再按下方入口执行。

当前标题规则版本：`2026-10-19.1`。歌曲关联仍待逐首复核；程序化采集不等于批准歌曲、自动锁曲或确认 CD。

## Agent 先读

| 入口 | 用途 |
|---|---|
| [cafe-context-brief/SKILL.md](skills/cafe-context-brief/SKILL.md) | 每次情景任务的简明执行约定 |
| [BRIEF-WORKFLOW.md](BRIEF-WORKFLOW.md) | 输入核对、候选策展、分段配置、脚本生成与完整归档流程 |
| [brief_template.md](brief_template.md) | 面向用户的报告模板 |
| [briefs/README.md](briefs/README.md) | 已有报告、版本和替代关系索引 |
| [context_settings.json](context_settings.json) | 固定采集器的门店默认值和启用范围 |

实际生成前还需读取 FlowSystem 仓库的 `AGENTS.md`、`.agents/skills/flowset-weekly/SKILL.md` 与 `docs/WEEKLY-WORKFLOW.md`。两个仓库、私人曲库和 CD 历史分别定位，不把仓库名当作数据文件路径，不假定其他设备与本机相同。

当前 Windows 参考位置：情景仓库为 `F:/SystemPlayerInvestigation`，FlowSystem 为 `F:/SystemPlayerFlowSystem`。换设备先核实实际 checkout；旧报告中的 macOS 路径只是历史证据。

## 谁负责什么

| 环节 | 固定入口 / 责任 | 当前能力 |
|---|---|---|
| 目标日情景采集 | [collect_context.py](collect_context.py) | 固定 HTTPS 来源采集日期、农历、节气、天气；本地计算近似日出日落；记录来源和缺失 |
| 标题情境候选 | [scan_title_contexts.py](scan_title_contexts.py) 与有效 `scans/` 快照 | 扫描歌曲标题，保留原始证据和待复核关联；不查询目标日天气 |
| 策展与沟通 | Agent + 用户 | 核对曲目版本和实际特征，讨论采用哪些情景、歌曲、窗口及分段配置 |
| 实际排程 | FlowSystem 的 `tools/weekly_playlist.mjs generate` | 使用现有 catalog、衔接矩阵和 CD 历史生成草稿，不另写调度算法 |
| 试听交付 | 同一 CLI 的 `report` 子命令 | 将成功草稿转为自包含 HTML，选择本地音频试听并查看逐首诊断 |
| 正式采用 | 用户明确授权后的 `export` | 确认计划并生成含 CD 历史的新文件；与试生成、试听分开 |

情景快照不能直接作为生成器的 request。Agent 需要把用户选定的歌曲和开始窗口转换为 `flowset.weekly-request/v1` 的段落与 `requirements`。情景曲作为搜索中的必选条件参与排程，不是生成后额外插入；风格和能量是软偏好，不能保证每首都命中。

## 标准顺序与授权

1. 核实目标日期、时区、地点、播放区间、实际 catalog 和最新确认版 CD 历史。相对日期用用户当前日期解释，已确认项沿用，只讨论变化；历史缺失不得默默从空账本开始。
2. 选取未使用的版本目录，运行固定采集器。先查看实际 `context.json` 的状态、来源、覆盖和缺失，再从有效标题扫描与当前 catalog 的交集提出少量候选。
3. 与用户确认分段起止、主副风格偏好、能量、噪音/摇摆/负担三节点曲线与宽容度，以及采用的情景曲、准确 `songId` 和开始窗口。用户明确“其他按建议”可沿用已展示方案；未回复不是确认。
4. 用户要求脚本生成并确认配置后，保存本版 `request.json`、验证 catalog，再调用现有 `generate`。失败不静默删必选、不放宽 CD 或衔接风险，也不把搜索失败说成全局无解。
5. 对成功草稿调用 `report`，核查全天连续覆盖、唯一曲目、必选次数与实际开始位置、末曲截短、偏好偏离及原 CD 不变，再交付报告、证据、草稿和试听页。
6. 只有用户之后明确决定正式采用才执行 `export`。配置确认只授权试生成，不自动采用计划，不清空 CD，不自动导入 QQ，也不永久批准某条歌曲关联。

只要求情景建议时停在第 3 步并交付建议报告。收到“把已有草稿做成试听页”时只执行报告转换，不重新排歌。普通任务不操作浏览器、不创建定时任务、不上传音频。

## 运行环境与输入

采集器只用 Python 标准库，建议 Python 3.12+；Windows 使用本机实际可用的 `python`，macOS/Linux 通常使用 `python3`。生成和报告需要 Node.js 22.13+。纯试听 HTML 的使用者不需要 Python、Node、构建或后台服务，但试听需要自己可访问的音频。

| 输入 | 必须核实 |
|---|---|
| 目标日与播放区间 | 完整年月日、时区和本次实际起止时间；结束早于开始表示次日结束，相同起止无效 |
| 曲库 | UI 可导入的 `flowset.browser-playlist-catalog/v1`，包括人工主副风格、ZMPD 来源和完整衔接矩阵；不能用标签表、扫描结果或训练特征代替 |
| CD 历史 | 用户最新采用的确认 bundle 或独立账本；catalog 变更不清空历史 |
| 标题候选 | 规则版本、源曲库与扫描快照有效性，按稳定歌曲 ID 核对当前 catalog 中可用版本 |
| 人工 ZMPD | 只有与当前音频 SHA256 完全匹配的标注可称为绑定人工值；旧录音参考单列，缺失不补造 |

私人 catalog、音频和 CD 不会随 FlowSystem 代码仓库自动下载。缺输入时明确列出需要用户提供的文件。

## 固定采集

在情景仓库根目录执行以下示例。日期和 `r001` 只是示例，先查看归档索引并选择下一个未使用版本；不要覆盖同日旧版本。

```powershell
python -B SongBase/context_associations/collect_context.py --date 2026-10-23 --start 09:30 --end 18:30 --timezone Asia/Shanghai --output-dir SongBase/context_associations/briefs/2026-10-23/r001/context-snapshot
```

必需参数只有 `--date`、`--output-dir`。可选参数：`--start`、`--end`、`--timezone`、`--latitude`、`--longitude`、`--settings`、`--cache-dir`、`--user-agent`、`--offline`。路径含空格时加引号；日历支持 1901–2100 年，不代表天气覆盖相同范围。

配置优先级：程序默认 [context_settings.json](context_settings.json) → `--settings` 指定的局部配置 → 命令行覆盖。局部配置只允许现有字段，不修改用户未确认的长期默认值。

| 配置 | 默认与边界 |
|---|---|
| 地点 / 时区 / 播放时间 | 深圳景田，22.56°N / 114.04°E，`Asia/Shanghai`，09:30–18:30；本次新要求优先 |
| `weatherMaxAgeHours` | 12 小时，依据来源预报更新时间，不是本次点击采集的时间 |
| `enabledHolidays` | 空数组；节日事实仍保留在日历中，但须经用户选择后显式启用，不能默认节日预热 |
| `coldAtOrBelowC` / `hotAtOrAboveC` | `null`，不自动触发冷热；已确认数值阈值才可设置 |
| `seasonBasis` / `eveningBeforeMinutes` / `eveningAfterMinutes` | 尚未实现自动季节判定或傍晚窗口计算的预留项；填值不能当作已生效。四季与情景曲窗口仍需策展确认 |
| `userAgent` | 固定天气服务要求可识别应用身份；沿用项目配置或维护者提供的真实身份，不伪造联系人 |

输出为 `context.json`（`context-playlist-snapshot/v1`）、`context.md`、`sources.json` 及可获得的 `raw/` 原始响应。程序只创建新的快照目录；报告、证据和归档索引由 Agent 按标准流程另行维护，不是采集器自动生成。

默认缓存为本目录 `.context-cache/`，已忽略 Git。采集器尊重 HTTP 有效期并使用条件请求；有效缓存复用不等于重新发布预报。保留 `retrievedAt`、`checkedAt`、来源 `updatedAt` 和缓存状态。`--offline` 只使用缓存，无缓存会报告缺失，过期缓存不可冒充新天气。

### 状态与降级

采集命令退出 0 表示写出了快照，可能仍为 `status=partial`；不能仅凭退出码说“情景已完整收集”。退出 1 表示参数或输出等错误，先查 stderr，不重试覆盖旧目录。

| 天气状态 | Agent 的处理 |
|---|---|
| `available` | 已覆盖本次区间，仍是预报而非门店实况，保留粒度和更新时间 |
| `partial-coverage` | 只对已覆盖区间讨论天气，缺失部分明确标待补，不外推全天 |
| `outside-forecast-range` | 不借用邻日或历史天气，等待有效预报或由用户决定跳过天气情景 |
| `stale` / `unknown-update-time` / `invalid-future-update` / `expired-cache` / `unavailable` | 不用于天气选曲依据，说明原因；本地日历与天文仍可继续 |

最终以 `weather.usableForSuggestions` 为准，同时查看 `problems`。逐小时、六小时或十二小时区间保持源粒度，不插值；源区间起点温度不冒充全区间恒温，降水量不按营业时间交集等比例分配。

农历和节气优先香港天文台固定历表；官方节气表无法获取或核验时，明确降级为本地太阳黄经近似计算。`approximate=true` 不等于官方日期，接近午夜的结果须权威复核。日出日落也是近似计算，不证明会出现晚霞或真实可见日出。网络/TLS 出错保留原因，不关闭证书验证、不让大模型编造事实填空。

## 脚本生成与试听页

以下 PowerShell 示例可从任意工作目录调用。先替换本机两仓库路径、目标日期、未使用版本号，以及用户实际提供的 catalog 和 CD 文件。示例不是预约，也不是执行授权。

```powershell
$InvestigationRoot = 'F:/SystemPlayerInvestigation'
$FlowRoot = 'F:/SystemPlayerFlowSystem'
$RunDir = Join-Path $InvestigationRoot 'SongBase/context_associations/briefs/2026-10-23/r001'
$Catalog = Join-Path $InvestigationRoot 'SongBase/周歌单专用特征-1103首-raw416.json'
$Ledger = '<用户最新确认版歌单/CD JSON 的绝对路径>'
$Cli = Join-Path $FlowRoot 'tools/weekly_playlist.mjs'
node $Cli validate --catalog $Catalog
node $Cli generate --catalog $Catalog --request "$RunDir/request.json" --ledger $Ledger --output "$RunDir/draft.json"
```

`request.json` 由 Agent 在配置确认后写入，schema 为 `flowset.weekly-request/v1`。它保存唯一 `playlistId`、带偏移的 `startAt`、总分钟数、连续段落、三节点曲线、宽容度和必选项。完整契约及例子在 FlowSystem 的 `docs/WEEKLY-WORKFLOW.md`。

单曲必选格式是 `{"type":"song","songId":"已核实ID","count":1,"segmentId":"目标段ID"}`。每首 `songId` 整份歌单只出现一次；歌手必选可以由多首不同歌曲满足。开始窗口用独立小段承载，曲线按原趋势重采样并保持共享边界连续，默认窗口不超过 30 分钟。按歌曲开始所在段计次，不保证该段首曲或某个精确分钟；不能直接把天文时刻当作歌单位置。

真正首次使用且没有历史，或用户明确允许从空账本开始时，才省略 `--ledger`。`generate` 退出 0 对应成功；退出 2 对应 `incomplete`，保留草稿和原因；退出 1 查参数、输入或运行错误。三者都不自动确认 CD。

成功后执行：

```powershell
node $Cli report --draft "$RunDir/draft.json" --request "$RunDir/request.json" --context "$RunDir/context-snapshot/context.json" --timezone Asia/Shanghai --output "$RunDir/完整歌单.html"
```

`report` 的必需参数是 `--draft` 与 `--output`；完整交付应传本版 `--request` 和匹配的 `--context`。情景 schema、目标日、播放起止和时区必须与草稿一致；时区使用相同名称，不能只把 `+08:00` 当作 `Asia/Shanghai` 传给报告页。如果用户修改起止时间、地点或日期，先生成本次新快照，不附上旧天气。程序不代替 Agent 检查预报时效与地域。

转换没有情景快照的历史草稿时可省略 `--context`，明确这是纯歌单诊断页。不要为通过校验而借用另一日情景或修改原草稿。输出文件已存在时换新版本；`report` 不覆盖、不排歌、不写 CD，拒绝不完整或诊断数据缺失的旧格式，不伪造缺失数据。

### 试听页显示什么

| 内容 | 口径 |
|---|---|
| 日期与时间 | 目标日期、时区和逐首预计开始/结束；跨日清楚显示，不是实际播放回执 |
| 实际 Tag | 最终选中曲目的人工主副风格，不把本段请求的偏好冒充曲目标签 |
| ZMPD / 能量 | 排程使用的整首预测、模型版本，以及可得的同录音人工值；缺失不补造，不冒充逐秒实测 |
| 衔接 | `objectiveCost` 综合成本、`acousticCost` 声学成本和 `risk`；首曲无前曲，不填假零；缺失或风险 ≥0.5 不冒充合格衔接 |
| 诊断 | 本段必选、跨段连续播放、风格/能量偏离、曲线成本和末曲截短 |
| 情景与配置 | 本版数据来源、缺失、近似性及附带的已确认分段配置 |

生成的 HTML 内嵌 CSS/JS/数据，可直接打开。必须交付这个页面文件本身；预览链接不代表打包了音频。用户点击“选择本地音乐目录”后按 `filename` 精确匹配，重名或 SHA256 不符拒绝试听；没有哈希时明确版本未核验。缺音频仍可阅读；异地/IM 用户需在自己的设备提供音频。只按计划顺序连续试听，无混音或交叉淡化，不修剪原文件。

FlowSystem 的 `apps/playlist-generator/playlist-report.html` 是可手动导入草稿的通用入口，依赖同目录资源，不可只复制这个模板 HTML。`report` 生成的自包含页面则可单独分发。两者都不是已退役的旧试听包。

## 每次交付与留档

完整生成分支的推荐布局：

```text
briefs/YYYY-MM-DD/rNNN/
  context-snapshot/
    context.json
    context.md
    sources.json
    raw/
  request.json
  draft.json
  完整歌单.html
  情景与手动配置建议.md
  evidence.json
```

只建议时不伪造 `draft.json` 或试听页。所有版本先检查冲突，旧版保留；更新 [归档索引](briefs/README.md) 的版本、状态、采集时间与替代关系。报告版本不等于 CD 确认版。

对话至少返回当日情景、缺失项、候选特征与配置；生成后增加曲目数量、覆盖时长、指定情景曲实际位置、诊断、试听页和草稿下载入口。不能只说“已存档”，不能把普通算法选入的其他情景标题冒充本次指定曲。详细证据字段按 [标准流程](BRIEF-WORKFLOW.md) 和 [报告模板](brief_template.md)。

## 已确认的标题扫描规则

以下为现行标题规则/快照的原过滤口径，不是最新采集默认营业时间：深圳景田，东经 114.04°、北纬 22.56°，`Asia/Shanghai`，08:00–18:00（不含闭店端点）。新采集默认 09:30–18:30；采集器下午区间到 18:30，但扫描快照仍到 18:00，涉及 18 点后明确钟点标题须重扫或人工核对，不能假定已覆盖。

| 分组 | 保留内容 |
|---|---|
| 日历：季节 | 春、夏、秋、冬；低优先级，不由月份或天气反推 |
| 日历：月份 | 一月至十二月 |
| 日历：星期 | 星期一至星期日、周末；不把周末等同调休后的休息日 |
| 日历：日期 | 明确月日；保留原年份，不默认每年复现 |
| 日历：节日 | 元旦／新年、春节、元宵、端午、七夕、中秋、重阳、情人节、万圣节、圣诞节；历法需核实，按门店采用范围启用 |
| 日历：节气 | 二十四节气，完整保留；不表示当地实际天气 |
| 天气与体感 | 下雨、晴天／阳光、阴天、偏冷／凉爽、偏热 |
| 营业时段 | 上午 08:00–11:00、午间 11:00–14:00、下午 14:00–18:00 |
| 日出 | 保留为早晨开店意象，不要求实际日出与营业时间重叠 |
| 傍晚天光 | 傍晚、黄昏、暮色、日落、夕阳、晚霞统一归类；原标题词义仍保留，适用窗口须与营业时间重叠 |

咖啡／茶只保留为 `manual_themes` 手动主题，不参与自动标题扫描或日常加分。

四季整体、历法未确认月份、泛假日、泛祝贺、生日、雾、霜、风暴、雷电、温暖、傍晚风歇、泛太阳、月光、午夜、黄金时刻、山行、自然、植物、空间和活动扩展等退出日常关联；原有冰、露水、云、雪、风、夜晚、黎明等排除继续生效。退出的是关联，不是歌曲。

单纯的温度数值不直接产生偏冷／偏热标题标签，原文仍保存在标题审计中。早餐、午休为间接线索。明确钟点只有在扫描营业区间内才保留，并归入对应时段。

### 合并与证据

- `tag_aliases` 统一旧标签；`association_groups` 定义合并后的名称与触发条件。82 条词表规则输出 68 种固定日常标签，另有按标题产生的具体日期。
- `source_associations` 保存合并前的标签、判断、理由、触发提示和原始证据；`evidence` 保留原文字符位置，不把晚霞改写成精确日落。
- `weather_changes` 保存雨后放晴、雨晴交替和阴转晴的组合信息；输出其天气分量，不再产生第三个独立变化标签。
- `scoring_groups` 标识共享依据：天气过程分量、具体日期与月份、星期与周末不得机械重复加分。这里只记录约束，没有排名加分引擎。
- `policy.excluded_tags` 在词表、解析器、语义附加项之后统一过滤，避免旧标签重扫回流。营业时间外钟点和其他被过滤项保存在 `title_audit.store_filtered`。

### 当前扫描快照

2026-10-19 使用新规则扫描：1,554 条记录 → 1,553 首唯一歌曲，103 首候选、115 条关联。其中 84 首至少有一条明确标题关联，19 首只有间接或歧义线索；1,450 首没有标题命中。同一 QQ MID 合并扫描，原始重复记录保留。这是历史快照数据，重新扫库后以新有效快照为准。

| 类别 | 候选歌曲 | 关联条数 |
|---|---:|---:|
| 日历 | 53 | 60 |
| 天气与体感 | 24 | 26 |
| 营业时段与天光 | 28 | 29 |

类别可能重叠，关联条数不等于独立加分次数。

- [可筛选候选报告](scans/2026-10-19/title_context_report.html)
- [文字报告](scans/2026-10-19/title_context_report.md)
- [完整扫描与审计 JSON](scans/2026-10-19/title_context_candidates.json)
- [逐关联 CSV](scans/2026-10-19/title_context_candidates.csv)

`scans/2026-10-12/` 与 `scans/2026-10-14/` 是未覆盖的历史快照，旧标签和扩展提案不代表现行规则。

## 验证与故障排查

只检查采集入口，不联网、不写报告：

```powershell
python -B SongBase/context_associations/collect_context.py --help
```

在情景仓库根目录运行情景/扫描测试：

```powershell
python -B -m unittest discover -s SongBase/context_associations -p 'test_*.py' -v
python -B SongBase/context_associations/scan_title_contexts.py --dry-run
```

扫描器 `--dry-run` 不写文件。正式重扫需指定新的 `--output-dir`；扫描器与采集器不同，同名扫描输出可能覆盖报告，不重复写旧目录。

在 FlowSystem 仓库根目录运行相关验证：

```powershell
node --test tests/playlist-report.test.mjs tests/weekly-cli.test.mjs tests/weekly-generator.test.mjs tests/weekly-ui-flow.test.mjs
python -B -m unittest discover -s tests -p 'test_playlist_generator_package.py' -v
npm run lint
```

测试/代码检查环境按该仓库 `docs/COMMANDS.md` 准备；只阅读试听页不需要安装依赖。本文不承诺跨机全套测试均通过，例如录音用例依赖平台环境，不能用录音环境缺项掩盖采集或排程失败。

| 问题 | 先做什么 |
|---|---|
| 输出版本已存在 | 检查归档索引，换未使用的版本或新文件，不删除旧证据绕过保护 |
| 天气/官方历表请求失败 | 看 `problems`、来源及原始响应；明确缺失/近似，不关闭 TLS 验证 |
| `generate` 未完成 | 保留结果，报告未满足必选、CD、曲库、覆盖或衔接情况；修改约束先与用户确认 |
| `report` 拒绝情景 | 检查目标日、起止、时区名称、实际地点及时效；不改写旧证据欺骗校验 |
| 有草稿但无试听音频 | 仍交付阅读页，提醒在用户设备选择准确目录；文件名歧义、哈希不符不能自动替代 |
| 只有模型预测 | 显示预测及模型版本，人工列写缺失，不根据歌名或相似版本补出“实际 ZMPD” |

## 实现边界

已实现固定来源采集、标题候选审计、配置确认后的现有脚本生成与试听页交付；未实现自动天气到歌曲排名、正式关联库写回、自动永久批准或浏览器锁曲。`timeScores` 不自动限制排程时段；不修改生成器来追随标题线索。

所有扫描候选仍为 `review_status=pending`、`auto_lock_allowed=false`、触发提示 `enabled=false`。用户本次选择一首歌只影响本次 request，不代表永久批准。人工确认结果独立保存，不直接编辑扫描产物。

历史讨论见 [情境关联功能需求与歌单生成影响](情境关联功能需求与歌单生成影响.md)，其中旧范围以现行规则和本次用户要求为准。维护脚本后同时核对本 README、技能入口和标准流程，避免命令、能力与授权边界漂移。
