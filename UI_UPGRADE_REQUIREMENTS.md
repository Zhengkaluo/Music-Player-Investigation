# 界面升级需求表（交接给独立 Agent 执行）

> **本文档自包含**：接手的 Agent 无需了解本次对话历史，仅凭本文即可开工。
> **任务范围**：仅做「界面/视觉升级」，不改音乐数据抓取逻辑、不动 cafe-playlist 编排算法。
> **工作目录**：`f:\SystemPlayerInvestigation\`（Windows 主力开发环境，桌面 GUI 依赖 Windows SMTC + PowerShell）。
> **重要**：桌面 GUI 数据源为 Windows 专属（SMTC）；非 Windows 平台取不到真实播放数据属正常，可用 `manual_data` / 前端 mock 预览。

---

## 实施进度总览（2026-07-14 更新）

> 对象 A 已进入编码阶段。已产出目录：`webui/`（后端 `backend/` + 前端 `frontend/`）。

| 模块 | 状态 | 说明 |
|------|------|------|
| 技术路线选型（A2 Web 套壳 pywebview） | ✅ 已定 | 见下方【路线已定】 |
| 三层解耦架构 + 数据契约 `state` | ✅ 已落地 | `webui/backend/` 三件套；契约见下 |
| 后端 ConfigStore（读写/迁移/兼容） | ✅ 完成并测试 | 旧字段迁移、`custom_content↔panels` 双向映射均已验证 |
| 后端 ColorExtractor（Pillow 封面提色） | ✅ 完成并测试 | 主色/调色板/明暗判断，含兜底 |
| 后端 Bridge（js_api + 轮询推送） | ✅ 完成 | pywebview 冒烟测试通过 |
| 前端渲染核心 + 深色沉浸主题 | ✅ 完成 | 浏览器 mock 预览正常 |
| A+3 面板化网格布局引擎 | ✅ 第一版完成 | 拖动/缩放/吸附/禁重叠/比例自适应/增删板块；手感已确认 |
| A+2 自定义内容区（video/image/text） | ◑ 基本达成 | 已并入 panels 结构；**编辑入口待补**（在设置面板选类型/填内容源） |
| A+1 响应式三档重排 | ◑ 降级保留 | 作为 `layout.mode="responsive"` 可选项，代码保留，待完善 |
| ≥3 套主题细节打磨 | ☐ 待办 | 三套已可切换，细节需精修 |
| 设置面板增强（内容编辑/删板块/样式微调） | ☐ 待办 | 当前仅有主题、布局模式两个下拉 |
| Windows 真机实测（真实 SMTC + 无边框拖动） | ☐ 待办 | 仅冒烟测过数据流，未长驻实跑 |
| 依赖 requirements + README（Windows 安装说明） | ☐ 待办 | 依赖：pywebview 6.2.1、Pillow 12.3 |
| 对象 B（HTML 报告模板化） | ☐ 未开始 | 待对象 A 收尾后进行 |

**已产出文件清单（对象 A）：**
- `webui/webui_app.py` — pywebview 入口（无边框/可拖动/置顶/尺寸持久化）
- `webui/backend/config_store.py`、`color_extractor.py`、`bridge.py`
- `webui/frontend/index.html`
- `webui/frontend/css/base.css`、`grid.css`、`themes/{immersive,minimal,adaptive}.css`
- `webui/frontend/js/mock.js`、`grid_layout.js`、`render.js`、`app.js`

---

## 背景与两个升级对象

本项目有两类界面，技术栈不同，**分别独立升级**：

### 对象 A：桌面「正在播放」悬浮显示器
- **文件**：`music_display_gui.py`（约 1300 行）、`get_music_powershell.py`（数据源）、`music_display_config.json`（配置）、`启动.bat`（Windows 启动）
- **技术栈现状**：Python **tkinter** + `ttk` + Pillow(PIL) 显示封面；置顶半透明悬浮窗
- **数据来源**：`get_playing_music_with_thumbnail()` 调用 PowerShell 读取 Windows 媒体传输控件(SMTC / `GlobalSystemMediaTransportControls`)，拿到当前播放的 标题/艺人/专辑/封面(base64) —— **这套数据逻辑不要动**，只换 UI 层。
- **现有功能（升级后必须全部保留）**：
  - 自动轮询更新（默认 5 秒，`auto_update.interval` 可配）
  - 手动/自动模式切换（手动可编辑标题/艺人/专辑/状态）
  - 封面缩略图显示（可开关、可调尺寸）
  - 样式设置：背景色/文字色/强调色/字体/字号
  - 窗口设置：尺寸/位置/置顶/透明度(alpha)
  - 文字对齐设置（左/中/右）
  - 配置自动保存到 `music_display_config.json`
  - 右键菜单、窗口可拖动
- **痛点（核心诉求）**：**设计感太弱**。tkinter 原生控件观感陈旧（方块按钮、系统默认样式、无圆角、无精致排版）。

### 对象 B：数据分析 HTML 报告
- **文件**：`cafe-playlist/report/album_analysis.html`、`album_library_report.html`、`diversity_report_updated.html`；生成脚本 `cafe-playlist/generate_report.py`、`generate_diversity_report.py`
- **技术栈现状**：Python 生成**手写 HTML 字符串** + 内联 CSS + **Chart.js 4.4.1**(CDN)
- **现状评价**：已有不错的极简排版（米白底 #f5f4f0、细边框、PingFang/YaHei 字体），但**缺乏组件化和多主题**，图表样式偏默认。
- **痛点**：想要更强的设计感 / 可切换的多套主题模板。

---

## 升级需求

### A. 桌面显示器 —— 目标：现代化视觉，保留全部功能

**推荐技术路线（二选一，接手 Agent 可自行判断后与用户确认）：**

| 路线 | 做法 | 优点 | 缺点 |
|------|------|------|------|
| **A1. CustomTkinter** | 用 `customtkinter` 替换 tkinter 控件 | 改动最小、纯 Python、现代圆角/深色主题、保留现有逻辑结构 | 定制上限不如 Web |
| **A2. Web 套壳**（✅ 已选定） | HTML/CSS/JS 做界面 + `pywebview` 套壳，Python 后端喂数据 | 设计自由度最高、易做多套精致模板、响应式/内嵌视频最自然 | 重写量大、多一层依赖 |

> **【路线已定 · 2026-07-14】** 经与用户确认，**对象 A 采用 A2 Web 套壳（pywebview）**。理由：新增的响应式布局（A+1）和自定义内容区含视频/GIF（A+2），用 Web（CSS 容器查询 + 原生 `<video>`）实现最自然；主题可切换、后期可持续演进也更容易。视觉基调做成**可切换主题**，且架构要求**数据与视觉彻底解耦**，方便后期继续调整布局/换视觉方案。

#### 技术底座（架构 & 数据契约 —— 施工前必须遵守）

**三层解耦架构：**
1. **数据源层（冻结，禁改）**：`get_music_powershell.py` 原样保留，仅被上层调用。
2. **Python 后端桥接层（新建，逻辑核心）**：通过 `pywebview` 的 `js_api` 暴露给前端。职责：
   - `Bridge/API`：5 秒轮询调用 `get_playing_music_with_thumbnail()`，向前端推送 `state`；接收前端的配置写入、窗口尺寸变更等回调。
   - `ColorExtractor`：用 **Pillow** 对封面 `cover_base64` 提取主色/调色板，算出 `theme`（primary/accent/bg/fg/muted/palette/is_dark）。
   - `ConfigStore`：读写 `music_display_config.json`，**向后兼容旧字段 + 缺字段自动补默认值（迁移）**。
   - 说明：**未来更换任何前端视觉，这一层不改动。**
3. **Web 前端表现层（可持续替换，所有视觉在此）**：
   - `渲染核心（稳定）`：把 `state` 绑定到 DOM；按**容器宽度**切响应式断点（迷你/标准/放大，对应 A+1）。
   - `主题系统（可切换/可扩展）`：CSS 变量 + 独立主题包 `theme-*.css`；封面提色注入 `--accent` 等变量，实现"封面取色自适应"。新增主题 = 加一个 css/配置，不动核心。
   - `组件（插拔式）`：封面 / 播放信息 / 进度 / **自定义内容区**（A+2）等独立组件。
   - `设置面板`：切主题、配置自定义内容、样式微调（字体/字号/颜色/对齐/透明度/置顶）。

**统一数据契约 `state`（前后端唯一约定，必须钉死；只允许新增字段，不破坏语义）：**

```jsonc
{
  "track": {                    // 当前播放，来自 SMTC，只读
    "title": "", "artist": "", "album": "", "status": "正在播放",
    "cover_base64": null,       // 封面图（可空）
    "position": null, "duration": null,  // 进度秒数，有则显示进度条
    "app_name": "", "is_playing": true
  },
  "theme": {                    // 后端用 Pillow 从封面算出
    "primary": "#...", "accent": "#...",
    "bg": "#...", "fg": "#...", "muted": "#...",
    "palette": ["#...", "#..."], // 调色板
    "is_dark": true             // 明暗判断，供前端选文字色
  },
  "config": {                   // 用户设置，可读写，落盘到 music_display_config.json
    "theme_id": "immersive",    // 当前主题包 id
    "window": { "width": 0, "height": 0, "x": 0, "y": 0, "alpha": 0.95, "topmost": true },
    "style": { "font_family": "Microsoft YaHei UI", "title_size": 25, "artist_size": 19,
               "album_size": 14, "bg_color": "#...", "text_color": "#...", "accent_color": "#...",
               "alignment": { "title": "left", "artist": "left", "album": "left", "status": "left" } },
    "thumbnail": { "show": true, "size": 400 },
    "auto_update": { "enabled": true, "interval": 5 },
    "manual_data": { "title": "", "artist": "", "album": "", "status": "" },
    "layout": {                 // A+3 面板化布局
      "mode": "grid",           // "grid"(默认,自由面板) | "responsive"(A+1 三档自动重排)
      "grid": { "cols": 12, "rows": 8 },  // 虚拟网格，坐标按此换算
      "edit": false,            // 是否处于编辑态
      "snap": true,             // 自动吸附对齐
      "overlap": false          // 禁止重叠
    },
    "panels": [                 // 各板块，坐标用网格单位，随窗口按比例缩放
      { "id": "nowplaying", "type": "nowplaying", "visible": true,
        "grid": { "col": 0, "row": 0, "w": 7, "h": 4 }, "locked": false },
      { "id": "custom-1", "type": "custom", "visible": true,
        "grid": { "col": 7, "row": 0, "w": 5, "h": 4 }, "locked": false,
        "content": {            // 等价于旧 custom_content，挂到板块上（支持多个）
          "kind": "text",       // "video" | "image" | "text"
          "source": "",
          "follow_theme": true,
          "fit": "cover"
        } }
    ],
    "custom_content": {         // 兼容保留：单自定义区旧字段，迁移时映射到 panels[custom-1]
      "enabled": false,
      "type": "text",           // "video" | "image" | "text"
      "source": "",             // 本地路径 / URL / 文本内容
      "follow_theme": true,     // 配色是否跟随封面主题色
      "fit": "cover",           // 填充方式：cover/contain/fill
      "position": "right",      // 区域位置（预留）
      "size": { "w": 0, "h": 0 }
    }
  }
}
```

> **兼容性说明**：`config` 直接沿用现有 `music_display_config.json` 的 `window / style / alignment / thumbnail / auto_update / manual_data` 字段语义（`alignment` 收纳进 `style` 下，读取时兼容旧的顶层 `alignment`）。新增字段为 `theme_id`、`layout`、`panels`、`custom_content`。`custom_content`（单区旧结构）在加载时映射为 `panels` 中的一个 `type:"custom"` 板块，两者保持同步以向后兼容；旧配置文件加载后由 `ConfigStore` 自动补齐缺省值。

**功能要求：**
1. 保留上文列出的全部现有功能，配置文件 `music_display_config.json` 结构尽量向后兼容（新增字段可以，不要破坏旧字段语义）。
2. **提供 ≥3 套内置界面模板/主题**（例如：极简浅色、深色沉浸、专辑封面取色自适应），可在设置里一键切换。
3. **封面为主视觉**：大封面 + 模糊封面做背景、文字叠加，是这类"正在播放"卡片的经典高级做法，建议实现。
4. 保持悬浮窗特性：置顶、可调透明度、可拖动、无边框或精致标题栏。
5. 字体/字号/颜色/对齐仍可自定义（在模板基础上微调）。

**验收标准：**
- Windows 上 `启动.bat` 或 `python music_display_gui.py` 能正常拉起，正确显示当前播放信息与封面。
- 至少 3 套模板可切换且视觉明显区别、都精致。
- 现有配置项全部可用，配置能正确保存/加载。
- 自动更新、手动编辑、封面开关等原功能无回归。

#### A+. 补充需求（需求评审后追加，优先级高）

> 以下两项是用户在需求评审后追加的核心诉求，接手 Agent 必须一并实现。

**A+1. 界面尺寸灵活可调（响应式布局）** — 状态：◑ 降级为可选布局模式 `layout.mode="responsive"`（默认走 A+3 自由面板），代码保留待完善。
- 背景：用户尚未确定最终在多大尺寸的屏幕上展示，因此界面必须能**自由拖拽缩放**，且布局随尺寸智能重排，而不是简单等比拉伸导致留白或裁切。
- 要求：
  1. 窗口大小可由用户自由拖拽调整（保留悬浮/置顶特性），当前尺寸写入配置并在下次启动时恢复。
  2. **按断点自动重排布局**，建议至少 3 档形态：
     - **迷你态**（小窗）：仅封面缩略图 + 标题/艺人，隐藏进度条与次要信息。
     - **标准态**（中窗）：封面 + 完整信息（标题/艺人/专辑）+ 进度条 + 基础控件。
     - **放大态**（大窗）：在标准态基础上展开「自定义内容区」（见 A+2）及更多留白。
  3. 字号/封面尺寸随窗口尺寸自适应缩放（在模板与用户微调设置基础上按比例联动），中文 `wraplength` 自适应逻辑必须保留。
  4. 高 DPI 下各档形态均需清晰不糊。
- 备注：此需求会明显影响技术路线取舍——**Web 套壳（A2）天然用 CSS 媒体查询/容器查询做响应式更省力**；若选 CustomTkinter（A1），需手动监听窗口 resize 事件并切换布局，实现成本更高。接手 Agent 应把这一点纳入路线确认时的说明。

**A+2. 可自定义内容区（视频/图片/文字）** — 状态：◑ 数据结构与渲染已并入 panels 完成；**设置里的内容编辑入口待补**。
- 背景：用户希望界面上有一块**可自由配置内容的区域**，用来放置个性化内容。
- 要求：
  1. 提供一块独立的「自定义内容区」，内容类型支持 **三选一**：本地/网络**视频**、**图片**（含 GIF）、**富文本/纯文字**。
  2. 内容源、类型、区域开关、尺寸/位置等通过配置项管理（写入 `music_display_config.json`，保持向后兼容）。
  3. **主题色联动（尽力实现，不强求）**：自定义内容区的背景/边框/文字配色应尽量与「封面取色」得到的主题色协调统一；封面变化导致主题色变化时，该区域配色随之更新。取色可用 Pillow 对封面做主色/调色板提取。
  4. 该区域仅在窗口达到「标准态/放大态」时展示（与 A+1 响应式断点联动），迷你态可自动隐藏。
  5. 视频/GIF 播放不得阻塞主 UI 与 5 秒轮询逻辑（用独立线程或播放组件），Windows 上需实测可播。
- 验收：能在设置中切换内容类型并填入内容源，界面正确渲染；换封面时主题色联动生效（若实现）；关闭该区域不影响其余功能。

**A+3. 面板化自由布局（网格布局引擎）——【2026-07-14 追加，替代 A+1 的自动重排作为默认布局】** — 状态：✅ 引擎第一版完成（拖动/缩放/吸附/禁重叠/比例自适应/增删板块），手感已确认。
- 背景：用户希望「正在播放」与「自定义内容」各自成为**独立板块**，可在界面内**自由拖动 + 缩放**，用 HTML 方式操作。
- 用户已确认的三项设计取向：
  1. **自由摆放 + 比例自适应**：板块位置/尺寸由用户手动摆放；坐标以**百分比/网格单位**存储，窗口缩放时按比例重算像素，板块随之等比缩放（跨屏幕尺寸不用重摆）。
  2. **禁止重叠 + 自动吸附**：板块互斥，拖动时做碰撞检测，自动避让或吸附对齐到网格。
  3. **可增删多板块**：未来支持添加多个自定义内容板块（多图/多段文字/多视频），每块独立。
- 技术形态：**自研轻量「网格布局引擎」**（不引第三方库，桌面离线可用）。虚拟网格（如 12 列 × N 行）负责对齐、吸附、碰撞检测；板块存 `{col,row,w,h}` 网格坐标；渲染时按容器尺寸换算像素。已用纯 HTML/CSS/JS 的 POC 验证核心拖拽/缩放/边界约束逻辑可行（约 40 行 JS）。
- 每个板块结构：标题栏（拖动手柄）+ 内容区 + 右下角缩放把手；支持锁定、显隐、层级（若允许重叠则用 z-index，本项目选禁止重叠故用吸附）。
- **与 A+1 的关系（重要）**：本项目**默认采用面板自由布局（A+3）**；原 A+1 的「迷你/标准/放大」三档自动重排**降级为可选布局模式**，通过 `config.layout.mode = "grid" | "responsive"` 切换，默认 `grid`。已写好的响应式断点代码保留复用。
- 编辑态 vs 展示态：提供「编辑布局」开关——进入后显示拖拽手柄/缩放把手/网格线，退出后回到干净展示。布局变更实时写入 `config.layout` 并落盘，下次启动恢复。
- 验收：进入编辑态可拖动/缩放两个板块并自动吸附不重叠；退出编辑态布局保持；重启后布局恢复；窗口缩放时板块按比例自适应；可添加/删除自定义板块（至少预留数据结构与接口）。

### B. HTML 报告 —— 目标：更强设计感 + 多主题模板

1. 抽出**可复用的 HTML 报告模板/组件**（页头、KPI 卡片、图表容器、数据表、页脚），让三个报告共用同一套设计语言。
2. **提供 ≥2 套可切换主题**（如：浅色极简 / 深色）。
3. 图表（Chart.js）统一配色、字体、圆角、留白，与整体设计语言一致。**遵循中国股市/常识无关**——这是音乐数据报告，配色以美观协调为主。
4. 保持纯静态、离线可打开（CDN 允许 Chart.js）；不引入需要构建的重型框架，除非与用户确认。
5. 生成脚本 `generate_report.py` / `generate_diversity_report.py` 改为套用新模板输出。

**验收标准：**
- 三个报告 HTML 用统一设计语言重新生成，浏览器直接打开正常。
- 主题可切换（顶部开关或独立文件均可）。
- 图表美观、数据正确未丢失。

---

## 约束与注意事项

1. **不要触碰**：`cafe-playlist/` 下的编排算法（`scheduler_engine.py`、`scheduler_config.json`、`cafe_playlist.py`）、数据抓取（`get_music_powershell.py` 的 PowerShell/SMTC 逻辑）、`data/*.json` 数据文件。本任务纯 UI。
2. **依赖安装**：Web 套壳需 `pywebview`（Windows 上通常走 EdgeWebView2/MSHTML）、`Pillow`（封面提色）。写进 README 或 requirements，并说明 Windows 安装方式。
3. **跨平台**：桌面 GUI 数据源是 Windows 专属（SMTC），macOS 上无法取到真实播放数据属正常；UI 改造可用 `manual_data` 模式在任意平台预览。
4. **中文字体**：Windows 用 Microsoft YaHei UI，保证中文不乱码/不裁切（现有代码有 wraplength 自适应逻辑，注意保留）。
5. **高 DPI**：现有代码开头有 Windows 高 DPI 适配（`SetProcessDpiAwareness`），改造后需保持清晰不糊。

---

## 交接文件清单

**对象 A 相关：**
- `music_display_gui.py` — 主 GUI（要改）
- `get_music_powershell.py` — 数据源（勿改逻辑）
- `music_display_config.json` — 配置（保持兼容）
- `启动.bat` — 启动脚本
- `test_*.py`（根目录）— 封面/缩略图测试，可参考

**对象 B 相关：**
- `cafe-playlist/report/*.html` — 三个现有报告（改）
- `cafe-playlist/generate_report.py`、`generate_diversity_report.py` — 生成脚本（改）

---

## 建议执行顺序

1. ~~先跟用户确认路线~~ ✅ **已定：A2 Web 套壳（pywebview）**。
2. **搭技术底座**：先建 Python 后端桥接层（Bridge/ColorExtractor/ConfigStore）+ 前端渲染核心，跑通「数据契约 `state` → 前端渲染」的最小闭环（先用一套主题、`manual_data` 可在任意平台预览）。
3. **补齐能力**：响应式断点（A+1 迷你/标准/放大）→ 自定义内容区（A+2）→ 封面提色主题联动 →  ≥3 套可切换主题。
4. 再做对象 B 报告模板化。
5. 每个阶段用 `present_files` 展示效果给用户确认。
