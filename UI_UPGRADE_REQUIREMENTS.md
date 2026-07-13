# 界面升级需求表（交接给独立 Agent 执行）

> **本文档自包含**：接手的 Agent 无需了解本次对话历史，仅凭本文即可开工。
> **任务范围**：仅做「界面/视觉升级」，不改音乐数据抓取逻辑、不动 cafe-playlist 编排算法。
> **工作目录**：`/Users/kaluozheng/Music-Player-Investigation/`
> **重要**：原作者主力开发环境是 **Windows**（桌面 GUI 依赖 Windows SMTC + PowerShell），但当前审阅环境是 macOS。改造需保证 Windows 上可运行。

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
| **A1. CustomTkinter**（首选） | 用 `customtkinter` 替换 tkinter 控件 | 改动最小、纯 Python、现代圆角/深色主题、保留现有逻辑结构 | 定制上限不如 Web |
| **A2. Web 套壳** | HTML/CSS/JS 做界面 + `pywebview` 套壳，Python 后端喂数据 | 设计自由度最高、易做多套精致模板 | 重写量大、多一层依赖 |

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
2. **依赖安装**：如需 `customtkinter` / `pywebview`，写进 README 或 requirements，并说明 Windows 安装方式。
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

1. 先跟用户确认路线（A 选 CustomTkinter 还是 Web 套壳）。
2. 先做对象 A（用户日常高频使用），出 1 套模板 → 验收 → 再补齐 3 套。
3. 再做对象 B 报告模板化。
4. 每个阶段用 `present_files` 展示效果给用户确认。
