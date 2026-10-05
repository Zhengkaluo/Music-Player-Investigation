# System Audio Auto Volume

> 状态：M0–M2 已完成；M3 macOS 与 M4 Windows 只读原型已实现  
> 建立日期：2026-10-03  
> 开发路径：`/Users/kaluozheng/Music-Player-Investigation/System-Audio-Auto-Volume`

## 当前实现状态

M0–M2 已建立可运行的模拟版本：版本化 JSON 契约、六类音频场景、共享控制状态机、本机 API、设置持久化和监控界面。

M3 已接入 macOS 14.4+ Core Audio process tap：实时显示默认输出设备、RMS、Peak、采样率、丢帧、回调指标和只读系统音量。它不保存 PCM、不写录音文件，也没有任何系统音量写入调用。M3 的 60 分钟连续运行与多设备门禁仍待正式验收。

M4 已接入 Windows WASAPI loopback 与 EndpointVolume 只读接口：沿用严格的默认渲染端点匹配，监听默认设备、端点状态和音量/静音变化。当前代码不包含任何 EndpointVolume 写入调用；由于本轮开发主机是 macOS，Windows 实机验收尚未进行。

两个系统使用隔离入口，共用同一份 `AudioSource` 接口、控制器、HTTP 服务、状态契约和界面：

| 范围 | 入口与实现 |
|---|---|
| 模拟开发 | `src/service.py` → `Simulator` |
| macOS | `src/run_macos.py` → `src/macos_monitor.py` → Core Audio helper |
| Windows | `src/run_windows.py` → `src/windows_monitor.py` → WASAPI / EndpointVolume |
| 跨平台共享 | `src/source_contract.py`、`src/controller.py`、`src/service.py`、`ui/index.html` |

平台入口只在确认当前操作系统后延迟加载本平台适配器；macOS 不导入 Windows 依赖，Windows 也不导入 macOS helper。

运行：

```bash
cd /Users/kaluozheng/Music-Player-Investigation/System-Audio-Auto-Volume
python3 src/service.py
```

浏览器打开 `http://127.0.0.1:8765`。运行测试：

```bash
python3 -m unittest discover -s tests -v
```

离线回放单个合成场景，不启动服务、不接触系统设备：

```bash
python3 src/replay.py --mode shadow --scenario loud
```

macOS 真实只读监控：

```bash
python3 src/run_macos.py
```

首次运行可能出现“系统音频录制”权限提示；允许后只会取得实时电平摘要，不会保存声音内容。真实模式的控制模式被服务端固定为 `monitor`。

Windows 10/11 首次安装依赖并运行：

```powershell
py -3.12 -m venv runtime\.venv-windows
runtime\.venv-windows\Scripts\python.exe -m pip install -r requirements-windows.txt
runtime\.venv-windows\Scripts\python.exe src\run_windows.py
```

Windows 模式同样固定为 `monitor`。WASAPI exclusive-mode、设备拔出与同名输出的行为必须在 Windows 主机上完成门禁验收。

## 1. 项目目标

开发一套同时支持 macOS 和 Windows 的系统级自动音量工具。它不依赖 QQ 音乐或任何特定播放器，而是监听当前输出设备正在播放的系统混音，实时估计响度，并在必要时平滑调整该设备的系统主音量。

目标是减少歌曲、视频、网页和其他播放来源切换时的明显音量落差，同时尽量保留内容自身的动态变化。

基础闭环：

```text
当前输出设备的系统混音
        ↓
实时响度与峰值监测
        ↓
静音门限、时间平滑、手动干预判断
        ↓
生成有限幅度的音量调整建议
        ↓
调整当前输出设备的系统主音量
        ↓
继续监测并验证结果
```

## 2. 统一后的需求边界

### 2.1 必须做到

| ID | 需求 | 验收方式 |
|---|---|---|
| REQ-01 | 支持 macOS 和 Windows | 两个平台都能完成“监听、显示、自动调节、暂停”完整流程 |
| REQ-02 | 与播放器无关 | QQ 音乐、浏览器、本地播放器等共享同一控制链路 |
| REQ-03 | 监听当前输出设备的系统混音 | 不使用麦克风；监测内容与当前扬声器或耳机输出对应 |
| REQ-04 | 稳定歌曲和来源之间的听感音量 | 使用持续响度而非单个采样峰值决定常规调节 |
| REQ-05 | 保留内容内部动态 | 安静段落、停顿和渐弱不能触发连续升音量 |
| REQ-06 | 防止突然过响 | 持续过响时较快下降；极端峰值触发保护策略 |
| REQ-07 | 平滑调节 | 音量不能频繁跳动；每次调整量和单位时间调整速度都有限制 |
| REQ-08 | 尊重手动操作 | 检测到用户手动调音量后，自动控制暂时让路 |
| REQ-09 | 适应设备变化 | 切换扬声器、耳机或蓝牙设备后暂停闭环并重新校准 |
| REQ-10 | 可解释与可回退 | 显示监测值、调整原因和当前状态；可以一键暂停并恢复原音量 |
| REQ-11 | 不保存原始音频 | 默认只在内存中计算指标；日志不写入 PCM 或可还原的音频内容 |
| REQ-12 | 失败时安全降级 | 无权限、设备不可控或捕获异常时进入“只监测”或“暂停”，不能继续盲调 |
| REQ-13 | 提供实时监控界面 | 同时显示当前响度、系统实际音量、用户基准音量和自动修正量 |
| REQ-14 | 可调整控制参数 | 可设置触发响度、目标响度区间、系统音量上下限、压低与恢复速度 |
| REQ-15 | 显示动态调整过程 | 提供最近 60 秒趋势和动作原因，区分用户操作与自动操作 |
| REQ-16 | 区分音量调节与信号压制 | 界面和日志必须明确当前采用系统主音量控制，还是音频 DSP 压缩/限幅 |

### 2.2 当前不做

- 不按应用分别调节音量；第一版只控制当前输出设备的系统主音量。
- 不对音频流施加压缩器、限制器或重新编码；第一版调整的是系统音量，不修改音频内容。
- 不识别歌曲、艺人、风格或 ZMPD 标签。
- 不使用麦克风估计房间内的真实声压级，因此不能承诺耳边的绝对 dBA 或医疗级听力保护。
- 不把监测到的系统声音录制、归档或加入 SongBase/Flowset 训练数据。
- 不为未知来源预先做整曲分析，也不要求播放器提供曲目信息。

## 3. “音量稳定”的准确含义

系统稳定的是数字输出的相对听感响度，不是房间中的绝对声压。耳机灵敏度、外置功放旋钮、扬声器距离和环境噪声都不在无麦克风方案的观测范围内。

第一版同时观察四类指标：

| 指标 | 用途 | 是否直接驱动常规调节 |
|---|---|---|
| 短窗口峰值 / dBFS | 识别削波风险和突然巨响 | 只用于快速下降或保护，不用于升音量 |
| RMS | 低成本、低延迟的能量监测和降级指标 | 是，作为实时基础指标 |
| Momentary loudness（约 400 ms） | 观察短时听感变化 | 是，但必须经过平滑 |
| Short-term loudness（约 3 s） | 判断持续偏大或偏小 | 是，作为常规控制主指标 |

Integrated LUFS 适合整曲或较长节目总结，不适合独自驱动低延迟闭环。True Peak、完整 EBU R128 一致性和实际 CPU 开销在原型阶段测量后再决定是否进入实时主循环。

## 4. 控制行为

控制器采用状态机，而不是每收到一帧就改一次音量：

```text
MONITORING ──稳定且已校准──→ AUTO_HOLDING
    ↑                            │
    │                            ├──用户手动调节──→ USER_OVERRIDE
    │                            ├──设备切换──────→ RECALIBRATING
    │                            └──捕获/控制失败─→ SUSPENDED
    └──────────恢复条件满足───────┴───────────────────────
```

建议的首轮控制规则如下，数值是待实测的初始值，不是已确认产品参数：

- 每 50–100 ms 接收一次电平摘要，不在 UI 线程或系统音频回调中执行重计算。
- 对持续响度使用约 3 秒窗口，并设置目标区间而不是单一目标点。
- 只有连续越过目标区间一段时间才调节，避免边界抖动。
- 降音量比升音量快；升音量前要求更长的稳定证据。
- 静音、停顿、歌曲淡出、暂停播放时禁止升音量。
- 单次只改变一个小步长，并限制每秒最大变化量。
- 设置用户可见的最低和最高系统音量，任何自动动作不得越界。
- 用户手动调节后进入暂时让路状态；倒计时结束且信号稳定后才恢复自动控制。
- 切换输出设备后先停止写音量，重新确认捕获源、音量控制能力和反馈方向。

必须先验证一个关键事实：各设备的回录信号是在系统主音量之前还是之后。如果捕获信号不会随主音量变化，控制器不能直接把它当作闭环反馈；此时需要把设备音量的增益映射加入估算，或对该设备降级为只监测。每个设备首次使用都要做一次小幅、可撤销的响应校准。

## 5. 本地音源分析能力审计

### 5.1 可以复用的内容

现有 Flowset 已经具备相关基础：

- `audio_backend/audio_io.py` 使用 FFmpeg `ebur128` 提取 Momentary 和 Short-term LUFS。
- `audio_backend/frame_features.py` 已实现 RMS、峰值、crest factor、响度斜率、滚动波动和局部动态范围等计算。
- `tools/record_system_audio.py` 已验证 Windows WASAPI loopback、设备选择、实时峰值回调、静音/削波/丢帧检查。
- `tools/macos_audio_capture.swift` 已实现 macOS Core Audio 全局输出 tap、设备变化检测和无麦克风捕获。
- 相关测试已经覆盖部分电平、静音、削波、设备匹配和录音异常场景，可作为新项目测试设计的依据。

本项目复用的是指标定义、边界处理经验、测试样本和平台捕获方式。开发时只提取最小必要逻辑，不直接把整套 Flowset 分析器挂进实时进程。

### 5.2 不进入第一版实时主链路的内容

| 本地能力 | 结论 | 原因 |
|---|---|---|
| FFmpeg 整文件 `ebur128` 子进程 | 不直接复用 | 当前实现面向完整文件，子进程和文件输入不适合作为低延迟控制回路 |
| 频谱亮度、chroma、音高、节奏、onset | 暂不使用 | 对系统主音量控制不是必要条件，增加 CPU 和误判面 |
| Flowset 结构切分和转场分析 | 暂不使用 | 依赖较长上下文，无法覆盖未知系统来源 |
| ZMPD/ASP 审美预测模型 | 不使用 | 预测时段、能量、噪音、摇摆、负担，与主音量闭环目标不同 |
| MERT/CLAP 或新神经网络 | 不使用 | 第一版没有必须由模型解决的问题 |
| SongBase 曲目前置分析 | 不作为主链路 | 只能覆盖已知本地歌曲，无法处理浏览器、会议、视频和流媒体 |

### 5.3 决策

第一版采用实时监控，不依赖整曲预分析，也不训练模型。

离线音源分析只承担三项辅助工作：

1. 用已知测试音频生成可重复的响度和动态测试场景。
2. 对比实时估计与 Flowset/FFmpeg 离线结果，校准误差和窗口行为。
3. 将来如果能够可靠获得本地文件身份，可选用整曲响度缓存改善切歌后的前几秒；它只能是前馈优化，不能取代实时监控。

## 6. 最小技术架构

第一阶段就提供监控界面，但不先做复杂桌面壳。最小实现采用本机后台服务加本地网页界面，复用现有录音 dashboard 的组织方式；控制体验验证后再决定是否封装托盘应用和安装包。

```text
shared/
  meter             PCM → RMS / peak / momentary / short-term 摘要
  controller        状态机、目标区间、升降速率、静音门、边界
  event-log         不含原始音频的结构化事件
  local-api         仅监听本机，向监控界面提供状态和设置

ui/
  monitor           当前响度、系统音量、自动修正、历史和设置

macos/
  capture-adapter   Core Audio global tap
  volume-adapter    当前输出设备音量读写、变更监听、能力检测

windows/
  capture-adapter   WASAPI loopback
  volume-adapter    EndpointVolume 读写、回调、设备变更监听
```

共享控制算法必须能够读取保存的电平时间序列进行离线回放测试。平台适配器只负责：

- 输出 PCM 或最小电平摘要；
- 读取当前设备及系统音量；
- 写入有边界的音量变化；
- 报告用户手动变更、静音、设备切换和能力错误。

不为了“跨平台”提前建立复杂插件系统；两个明确的平台适配器已经足够。

监控界面和声音压制的详细方案见 [`MONITORING_AND_SUPPRESSION.md`](MONITORING_AND_SUPPRESSION.md)。
可直接执行的里程碑、任务门禁和验收顺序见 [`DEVELOPMENT_PLAN.md`](DEVELOPMENT_PLAN.md)。

## 7. 平台方案

### 7.1 Windows

- 捕获：复用现有 WASAPI loopback 经验。微软文档确认 loopback 能捕获渲染端点正在播放的系统混音；它只适用于 shared-mode，独占播放需要明确降级处理。
- 控制：使用 Windows EndpointVolume API 的 `IAudioEndpointVolume` 读取和设置当前渲染端点主音量。
- 手动干预：注册 `IAudioEndpointVolumeCallback`，使用事件上下文区分“本程序写入”和“用户/其他程序写入”。
- 当前本地原型使用 PyAudioWPatch。是否继续使用 Python 绑定，等 Windows 监测原型的稳定性和打包成本验证后决定。

### 7.2 macOS

- 捕获：复用现有 Swift Core Audio tap。当前本地实现基线为 macOS 14.4+，使用全局 stereo tap，不采集麦克风。
- 权限：需要系统音频录制授权；拒绝授权时只能暂停，不能伪装成有效监测。
- 控制：探测当前输出设备是否公开可写的主音量属性，并监听系统音量和默认设备变化。
- 能力降级：HDMI、数字输出、部分蓝牙/外置设备可能不提供可写主音量；这类设备进入只监测模式，不能用模拟按键等不可靠方式盲调。

## 8. 开发流程

### 阶段 0：冻结可测需求

产物：本文档 v1.0、默认参数表、验收音频集合。

完成条件：确认目标区间的解释、音量上下限、手动让路时长、是否需要开机启动，以及第一批测试设备。

### 阶段 1：只监测与监控界面原型

先不改系统音量，在本地监控界面显示并记录：设备、系统音量、RMS、峰值、Momentary、Short-term、静音状态和采样延迟。界面允许调整参数，但此阶段只生成调整建议，不真正写系统音量。

完成条件：两个平台连续运行 60 分钟无丢帧失控；暂停、静音、切歌和设备切换能正确进入相应状态；日志不含原始音频。

### 阶段 2：音量适配器与校准

独立测试系统音量读写，不连接自动算法。验证写入边界、用户手动变更识别、恢复原值和设备切换。

完成条件：每种测试设备都能明确标记为“可控制”或“只监测”；失败不会影响其他设备；能判断捕获电平是否响应主音量变化。

### 阶段 3：离线控制器回放

用保存的“电平摘要时间序列”模拟安静段、淡出、切歌、突然巨响、通知音和长时间持续偏响。控制器只输出建议音量，不触碰真实系统。

完成条件：所有安全约束可自动测试；安静段不爬升、过响能下降、边界不抖动、用户操作会让路。

### 阶段 4：系统音量受限闭环试用

默认最高音量设为保守值，先只允许自动降低，再启用受限的自动升高。每次动作都显示原因并可立即暂停。

完成条件：在指定测试歌单、浏览器视频和混合来源中，没有意外持续升音量；设备切换和权限变化会立即停止写入。

### 阶段 5：音频信号压制技术验证

在独立实验链路中验证“捕获并静音原声 → 慢速增益骑乘 → 压缩器 → 峰值限制器 → 输出设备”。不接入日常模式，不与阶段 4 同时启用。

完成条件：能够量化端到端延迟、漏音/双声、时钟漂移、削波、设备切换和崩溃恢复；Windows 和 macOS 都有可安装、可撤销的路由方案后，才讨论成为正式模式。

### 阶段 6：跨平台日常试用

加入设备档案、开关、目标区间和最小/最大音量配置。收集的只是指标与动作日志，不收集音频内容。

完成条件：macOS、Windows 各完成不少于一周的日常使用记录；用户确认调节节奏自然，再决定是否制作托盘 UI、安装包和开机启动。

## 9. 验收场景

| 场景 | 预期结果 |
|---|---|
| 播放器 A 切到明显更响的播放器 B | 在允许延迟内平滑降低，不突然跳到很低 |
| 曲内短暂高潮 | 保留音乐动态，不因单个峰值反复调节 |
| 长时间持续偏响 | 较快、分步下降到目标区间 |
| 长时间持续偏轻 | 在确认不是停顿/淡出后缓慢升高，且不超过上限 |
| 暂停、静音、歌曲尾部淡出 | 禁止自动升高 |
| 系统通知音突然出现 | 可触发峰值保护，但不会令之后长期音量过低 |
| 用户按音量键 | 立即进入手动让路状态 |
| 切换蓝牙耳机或扬声器 | 停止写入，重新识别设备与校准 |
| 捕获权限被撤销或音频回调停止 | 自动暂停并明确报错 |
| 设备没有可写主音量 | 保持只监测，不尝试替代性盲控 |

## 10. 日志与隐私

默认日志只保留：

- 时间、平台、匿名化设备 ID；
- RMS、峰值、短时响度等数值摘要；
- 系统音量、控制器状态、动作方向和原因；
- 设备切换、权限、丢帧和错误事件。

不保留 PCM、WAV、频谱、歌曲名、应用内容或能还原音频的信息。调试录音必须是单独、显式开启的开发行为，不能沿用日常监控日志。

## 11. 需要用户确认的产品参数

开发第一阶段前只需确认以下选择：

1. 默认允许自动升高音量，还是第一版先只自动降低。
2. 系统音量允许的默认最低值和最高值。
3. 用户手动调节后暂停自动控制多久。
4. 第一批实际测试设备：Mac/Windows 各自的内置扬声器、耳机和蓝牙设备。
5. 是否需要开机自动运行；建议等闭环稳定后再加。
6. 是否接受真正 DSP 压制需要额外音频路由、权限和延迟；建议第一版不默认启用。

## 12. 参考依据

- 本地 Flowset：`/Users/kaluozheng/MusicPlayer-FlowSystem/audio_backend/audio_io.py`
- 本地 Flowset：`/Users/kaluozheng/MusicPlayer-FlowSystem/audio_backend/frame_features.py`
- 本地 Windows 回录：`/Users/kaluozheng/MusicPlayer-FlowSystem/tools/record_system_audio.py`
- 本地 macOS 回录：`/Users/kaluozheng/MusicPlayer-FlowSystem/tools/macos_audio_capture.swift`
- 本项目研究：`MONITORING_AND_SUPPRESSION.md`
- [Apple：Capturing system audio with Core Audio taps](https://developer.apple.com/documentation/CoreAudio/capturing-system-audio-with-core-audio-taps)
- [Apple：CATapMuteBehavior](https://developer.apple.com/documentation/coreaudio/catapmutebehavior)
- [Apple：System-Supplied Audio Units](https://developer.apple.com/library/archive/documentation/MusicAudio/Conceptual/CoreAudioOverview/SystemAudioUnits/SystemAudioUnits.html)
- [Microsoft：Loopback Recording](https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording)
- [Microsoft：EndpointVolume API](https://learn.microsoft.com/en-us/windows/win32/coreaudio/endpointvolume-api)
- [Microsoft：SetMasterVolumeLevelScalar](https://learn.microsoft.com/en-us/windows/win32/api/endpointvolume/nf-endpointvolume-iaudioendpointvolume-setmastervolumelevelscalar)
- [Microsoft：Audio Processing Object Architecture](https://learn.microsoft.com/en-us/windows-hardware/drivers/audio/audio-processing-object-architecture)
