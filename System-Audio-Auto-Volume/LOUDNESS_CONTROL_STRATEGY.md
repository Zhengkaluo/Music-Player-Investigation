# M8 响度控制策略与跨平台边界

> 更新日期：2026-10-13
>
> 基线：M5 实时 LUFS、M5.5 Peak Guard、M6 人工音量校准、M7 真实影子模式
>
> 性质：下一阶段开发依据；不再把早期 M0–M4 行为当作当前目标策略

## 0. 结论

整体链路是：

```text
读取系统输出音频 + 读取当前系统音量（分系统）
                    ↓
          统一为跨平台观测数据
                    ↓
        动态调整判断（共享控制器）
                    ↓
          生成调整决定，不直接写系统
                    ↓
          执行实际调整（分系统）
                    ↓
       重新读取音量并验证结果（分系统）
                    ↓
          反馈给共享状态机与日志
```

因此，“读取音量 → 共用判断 → 分系统调整”的理解是正确的，但第一步实际包含两类输入：

1. 系统输出音频的实时电平和响度；
2. 当前系统音量位置、设备身份和控制能力。

实际写入后还必须增加一次平台侧回读验证，形成闭环。任何一步不可靠，都只能停留在 `monitor` 或 `shadow`，不能继续自动写音量。

## 1. 分层边界

### 1.1 平台采集层

负责采集，不负责判断“该不该降音量”。

macOS：

- Core Audio process/global tap 读取系统输出 PCM；
- 读取默认输出设备 ID、名称、当前系统音量和静音状态；
- 识别设备切换与用户手动调节；
- 输出实时 RMS、Sample Peak、Momentary LUFS、Short-term LUFS；
- 提供设备音量的安全写入和回读能力。

Windows：

- WASAPI loopback 读取默认输出 PCM；
- IAudioEndpointVolume 读取端点音量 scalar、dB、静音状态和设备 ID；
- 用事件上下文区分程序写入与用户手动调节；
- 输出与 macOS 相同的实时测量字段；
- 提供端点音量的安全写入和回读能力。

两个平台最终都转换成同一个观测对象，至少包含：

```text
timestampMs
platform
deviceId
systemVolumePercent
systemVolumeDb       # 能可靠取得时提供
momentaryLufs
shortTermLufs
rmsDbfs
samplePeakDbfs
isSilent
captureAvailable
volumeControllable
manualVolumeChanged
```

### 1.2 共享测量与决策层

这一层不导入 Core Audio、WASAPI 或平台音量 API，只处理统一观测数据。

负责：

- 静音门、暂停、设备切换、用户接管等安全拦截；
- 计算设备路径下的有效输出响度；
- 判断持续偏响、保持、建议下降或暂停；
- 应用目标区间、回差、下降速度和最低音量限制；
- 生成平台无关的 `VolumeDecision`；
- 在 `shadow` 模式写摘要日志，但绝不执行调整。

共享决定至少包含：

```text
kind                  # none / blocked / would-lower / lower
reason
deviceId
beforeVolumePercent
recommendedVolumePercent
requestedDeltaDb
execute
evidence
```

### 1.3 平台执行层

共享控制器只提出决定，平台适配器负责实际执行。

执行前必须再次确认：

- 默认输出设备没有变化；
- 当前音量仍与决策时一致，允许少量平台量化误差；
- 没有新的用户手动操作；
- 建议值未突破设备的安全上下限；
- 当前模式明确允许写入。

执行后必须：

1. 回读系统音量；
2. 核对是否到达允许误差内的目标值；
3. 记录实际值，而不是只记录请求值；
4. 写入失败、结果不一致或设备变化时立即暂停自动控制。

## 2. M5–M7 已有能力

下一阶段以这些能力为基线，不重复开发：

- 实时 K-weighting、Momentary LUFS 和 Short-term LUFS；
- RMS 与 Sample Peak；
- Peak Guard 的影子检测和建议衰减；
- macOS/Windows 独立采集适配器；
- 人工降低一个百分点与条件式安全恢复；
- 用户手动操作与程序测试写入的基本区分；
- 真实 `monitor` / `shadow` 模式；
- 实际音量、建议音量、原因和 60 秒趋势界面；
- 平台独立的 shadow JSONL 摘要日志；
- `shadow` 动作始终满足 `execute=false`、`appliedVolume=null`。

M8a 已完成窗口占比、目标上沿回差、30 秒影子事件聚合、设备 dB 能力、反馈档案、有效输出响度和 dB 建议。当前剩余限制是物理设备覆盖尚未完整：Windows 实机及两平台外接设备仍需补齐校准与失败路径门禁；未通过门禁前不进入真实 `lower-only`。

## 3. M8 采用的策略改进

### 3.1 先验证设备反馈路径

自动控制前必须判定捕获信号位于系统主音量之前还是之后。

校准流程：

1. 用户明确触发一次小幅、可恢复的音量测试；
2. 保持同一段相对稳定的音频；
3. 比较调整前后的系统音量、RMS 和 Short-term LUFS；
4. 记录该设备的响应类型和置信度；
5. 安全恢复到测试前音量。

#### 3.1.1 已确认的 macOS 结果

2026-10-13 在 `MacBook Pro扬声器` 上，用同一首曲目前约 20 秒分别以 31%、50%、69% 系统音量播放。三次 Short-term 曲线的峰谷位置与绝对高度基本重合，主要峰值均约为 −24 至 −25 LUFS；系统音量变化没有使整条捕获曲线同步平移。

因此该设备当前可记录为：

```text
captureResponse = pre-volume
confidence      = high
measurementBasis = source-lufs
```

这只证明当前设备、当前路由和当前系统环境下的 Core Audio tap 位于主音量之前，不能外推为“所有 macOS 设备都相同”。切换到蓝牙、AirPlay、HDMI、USB、聚合设备或其他系统版本后必须重新校准。

#### 3.1.2 macOS 开发策略

macOS 继续使用 Core Audio tap 计算源响度，同时由 Swift 平台适配器补齐设备音量的 dB 信息：

1. 读取 `kAudioDevicePropertyVolumeScalar`、静音状态和设备 UID；
2. 优先读取 `kAudioDevicePropertyVolumeDecibels` 与 `kAudioDevicePropertyVolumeRangeDecibels`；
3. 若设备只提供 scalar 转换能力，使用 `kAudioDevicePropertyVolumeScalarToDecibels` / `kAudioDevicePropertyVolumeDecibelsToScalar`；
4. 绝不使用 `20 * log10(volumeScalar)` 猜测系统音量衰减；
5. 用设备最大 dB 值归一化当前衰减：

```text
outputAttenuationDb = currentVolumeDb - maximumVolumeDb
effectiveLufs       = sourceShortTermLufs + outputAttenuationDb
```

6. 若属性缺失、转换不单调、回读不一致或设备音量不可写，只提供源响度并保持 `monitor/shadow`；
7. M8b 执行下降时，先把共享控制器要求的目标 dB 转换成设备 scalar，写入后同时回读 scalar 与 dB 验证。

Apple Core Audio 已定义上述 scalar、dB、dB 范围及双向转换属性：

- [Volume scalar](https://developer.apple.com/documentation/coreaudio/kaudiodevicepropertyvolumescalar)
- [Volume decibels](https://developer.apple.com/documentation/coreaudio/kaudiodevicepropertyvolumedecibels)
- [Volume dB range](https://developer.apple.com/documentation/coreaudio/kaudiodevicepropertyvolumerangedecibels)
- [Scalar to dB](https://developer.apple.com/documentation/coreaudio/kaudiodevicepropertyvolumescalartodecibels)
- [dB to scalar](https://developer.apple.com/documentation/coreaudio/kaudiodevicepropertyvolumedecibelstoscalar)

#### 3.1.3 Windows 开发策略

Windows 保持 WASAPI loopback 与 EndpointVolume 两条信息路径分离：

1. WASAPI loopback 继续计算 Momentary/Short-term LUFS；
2. IAudioEndpointVolume 同时读取 `GetMasterVolumeLevelScalar()`、`GetMasterVolumeLevel()` 与 `GetVolumeRange()`；
3. 使用端点 dB 范围归一化当前衰减：

```text
outputAttenuationDb = currentMasterDb - maximumMasterDb
```

4. 不能假设所有 WASAPI loopback 都位于主音量之前或之后。WASAPI 的 loopback 数据来源可能由音频引擎复制，也可能由硬件 loopback pin 提供，因此每个 Endpoint ID 都必须执行同一套三档音量校准；
5. 若判定为 `pre-volume`，使用 `sourceLufs + outputAttenuationDb`；若为 `post-volume`，直接使用捕获 LUFS；若不稳定则标记 `unreliable`；
6. M8b 优先用 `SetMasterVolumeLevel()` 按 dB 请求下降，再通过 `GetMasterVolumeLevel()` 回读，而不是把 scalar 当成线性响度；
7. 保留程序事件上下文与 EndpointVolume callback，用于区分程序写入、用户接管和系统策略变化；
8. exclusive-mode、端点失效、硬件音量不可回读或 loopback 中断时立即退出闭环。

Windows 的 dB 回读证明的是 EndpointVolume API 状态，不等于扬声器位置的真实声压，也不保证硬件恰好采用了请求的连续 dB 值；验证时必须结合 `GetVolumeRange()` 的步进容差和 callback，不能把 API 回读写成声学测量。

Microsoft 文档确认 WASAPI loopback 捕获渲染端点的系统混音，但具体实现可来自硬件 loopback pin 或音频引擎复制；IAudioEndpointVolume 提供端点 scalar、dB、dB 范围和变更通知：

- [WASAPI Loopback Recording](https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording)
- [IAudioEndpointVolume](https://learn.microsoft.com/en-us/windows/win32/api/endpointvolume/nn-endpointvolume-iaudioendpointvolume)
- [GetVolumeRange](https://learn.microsoft.com/en-us/windows/win32/api/endpointvolume/nf-endpointvolume-iaudioendpointvolume-getvolumerange)
- [EndpointVolume API](https://learn.microsoft.com/en-us/windows/win32/coreaudio/endpointvolume-api)

#### 3.1.4 设备反馈档案

两平台使用同一份最小档案结构，但由各自适配器产生和验证：

```text
platform
deviceId
captureResponse       # pre-volume / post-volume / unreliable
confidence            # low / medium / high
volumeDbSource        # coreaudio-property / endpoint-volume / unavailable
volumeDbMin
volumeDbMax
volumeDbStep
mappingReliable
calibratedAt
evidenceSummary
```

档案按设备 ID 保存为普通 JSON；设备 ID、dB 范围、驱动或系统版本发生变化时立即失效并回到 shadow。档案只保存测量摘要，不保存 PCM。

处理方式：

- 音量后捕获：测量值可直接作为有效输出响度；
- 音量前捕获：使用系统音量衰减修正测量值；
- 结果不稳定或设备不支持可靠映射：只允许 `monitor` / `shadow`。

音量前捕获的逻辑模型：

```text
effectiveLufs = measuredLufs + outputAttenuationDb
```

这里的 `effectiveLufs` 是设备数字路径上的相对有效响度，不等于扬声器位置的真实声压级。程序不宣称测量了房间里的 dB SPL。

平台差异：

- Windows 优先读取 IAudioEndpointVolume 提供的端点 dB 值与范围；
- macOS 优先使用设备提供的 dB 属性或 scalar/dB 转换，不能假定 scalar 与 dB 线性；
- 蓝牙、AirPlay、HDMI、聚合设备等若无法可靠读取或写入，保持只监控。

### 3.2 用 dB 决策，平台负责换算

共享控制器不再把“降低几个系统音量百分点”当成主要控制量，而是计算需要降低多少 dB：

```text
errorDb   = effectiveLufs - targetLufs.high
desiredDb = -errorDb * lowerGain
stepDb    = clamp(desiredDb, -maxLowerDbPerSecond * dt, 0)
```

原则：

- 偏差大时允许更快下降；
- 接近目标时自然减慢；
- 每秒最大变化量是硬限制；
- `minSystemVolume` 仍是最终硬下限；
- 平台适配器把 dB 决定转换成该设备可执行的音量值。

不可靠的设备不使用猜测曲线，也不退回另一套自动算法，而是保持 shadow。

### 3.3 建立真正的触发与回差

- 启动降低：有效 Short-term LUFS 高于 `triggerLufs`；
- 持续降低：已经进入降低状态，且仍高于 `targetLufs.high`；
- 停止降低：回到 `targetLufs.high` 或更低；
- 重新触发：之后再次超过 `triggerLufs`。

这样 `triggerLufs` 与 `targetLufs.high` 之间才是明确的回差区，不会长期停在触发阈值附近。

### 3.4 持续证据改为窗口占比

不再要求每一个 tick 都超过阈值。建议初始规则：

```text
最近 3 秒内，至少 80% 的有效观测高于判断阈值
```

当前实现沿用兼容字段 `lowerSustainSeconds` 作为证据窗口长度，并新增 `sustainRatio`（默认 `0.8`）。这样旧设置无需迁移；后续若重命名字段，只做一次明确的 schema 升级。

相同的 `would-lower` 建议在共用服务层按固定 30 秒窗口聚合。macOS 与 Windows 都只显示一个持续偏响事件，并附起止时间、持续秒数与判断次数；这不会改变控制器的逐次判断，也不会执行音量写入。

下列观测不计入有效样本，并直接阻止动作：

- 静音、暂停或淡出；
- LUFS 尚未预热完成；
- 捕获中断；
- 设备切换；
- 用户接管；
- 系统音量不可读或不可控。

### 3.5 M8 只开放有界下降

M8 分两步：

1. `M8a`：新策略继续跑真实 shadow，验证建议是否自然；
2. `M8b`：复核通过后开放 `lower-only`，只允许有界下降。

M8 不自动升高系统音量。音量恢复继续通过人工“安全恢复”，或等下一阶段获得足够真实数据后再设计。这样可以避免暂停、淡出、歌曲间隙和安静录音引发自动放大。

## 4. 突发声音与 Peak Guard

保留现有 Peak Guard，但下一阶段不把它直接接到系统音量写入。

原因：

- loopback / tap 看到第一个峰值时，该峰值通常已经进入播放链路；
- 系统音量写入只能压住随后持续的爆发，不能拦截第一个瞬间；
- Sample Peak 很高不一定代表主观响度危险；
- 未经真实内容验证就立即降低较大幅度，可能对鼓点、电影瞬态或切歌产生误触发。

M8a 中 Peak Guard 继续记录：

- Sample Peak；
- 相对背景的突增；
- 建议衰减；
- hold、release 和 cooldown 状态；
- 是否同时出现 Momentary / Short-term 响度异常。

只有在 shadow 数据证明误触发可控后，才考虑增加“快速下降层”；即使增加，也只能处理持续爆发，不能称为提前限幅。

真正拦截第一个爆音需要独立 DSP 音频路径和 look-ahead limiter。macOS 的重路由实验、Windows APO 或虚拟声卡均不属于 M8 范围，但属于最终产品必须完成的能力。

### 4.1 最终产品验收定义

“真正拦截第一个爆音”必须同时满足：

- 原始声音不会绕过处理链直接到达真实设备；
- DSP 在输出前保留小型 look-ahead 缓冲；
- 使用 Peak Guard 建立快速增益包络，并以 True-Peak limiter 约束最终输出；
- 记录检测到的峰值、实际 gain reduction、输出 True Peak 和端到端延迟；
- macOS 与 Windows 分别完成路由、设备切换、崩溃恢复和卸载验证；
- 系统音量事后降低只能标记为“快速补救”，不能计入该目标完成度。

## 5. 配置调整

M8 新增或明确使用：

| 字段 | 初始建议 | 用途 |
|---|---:|---|
| `triggerLufs` | 保留现有配置 | 开始降低的触发值 |
| `targetLufs.high` | 保留现有配置 | 停止降低的目标上沿 |
| `minSystemVolume` | 保留现有配置 | 自动降低硬下限 |
| `maxLowerDbPerSecond` | 2.0 dB/s | 最大下降速度 |
| `lowerGain` | 0.5 | 每次修正响度偏差的比例 |
| `lowerSustainSeconds` | 3 s | 持续证据窗口；沿用旧字段名兼容现有设置 |
| `sustainRatio` | 0.8 | 窗口内超阈值比例 |
| `manualOverrideSeconds` | 保留现有配置 | 用户调节后的让路时间 |

`lowerStepPercent` 在旧配置中暂时保留用于兼容和日志解释，但新 dB 策略不再把它作为主要决策参数。配置迁移完成后再删除，避免一次修改同时破坏旧设置、UI 和回放数据。

暂不加入：

- 自动恢复速度和自动升高参数；
- Peak 触发的实际紧急写入参数；
- True Peak limiter 参数；
- DSP 压缩器、look-ahead 或虚拟声卡设置。

## 6. M8 开发顺序

1. **已完成**：窗口占比、目标上沿回差、30 秒影子事件聚合；
2. **已完成**：冻结共享观测中的 dB 能力字段；
3. **已完成代码与 macOS 只读验证**：macOS 读取设备 dB、范围与 scalar/dB 转换；Windows 读取 EndpointVolume dB 与范围，仍待 Windows 实机复核；
4. **已完成代码与 macOS 内建设备档案**：按设备 ID 持久化反馈档案，并在环境或 dB 能力变化时失效；
5. **已完成**：引导式校准对同一稳定片段取三档 Short-term 中位数，并拒绝音量移动中的样本；
6. **已完成**：共享服务同时显示源 Short-term、有效输出响度、捕获位置、映射来源与置信度；
7. **已完成**：自动测试覆盖 `pre-volume`、`post-volume`、`unreliable` 与档案失效；
8. **已完成**：建议改为 dB 比例与每秒限速，平台只负责 dB ↔ scalar/percent 换算；
9. **进行中**：M8a shadow 的 macOS 内建扬声器已验证；真实音乐、对白、通知、切歌、暂停、淡出及外接设备矩阵继续积累；
10. **未开放**：完成 Windows 与两平台外接设备门禁后，才进入 M8b `lower-only`。

## 7. M8 验收条件

共享逻辑：

- 同一组标准化观测在 macOS/Windows 上产生相同决定；
- `triggerLufs`、`targetLufs.high` 和回差行为符合预期；
- 短暂间隙不会反复清空全部证据；
- 建议变化不超过每秒 dB 限制；
- 静音、暂停、淡出和测量缺失时绝不降低或升高。

平台逻辑：

- 每个设备都有明确的 `captureResponse`、置信度和 dB 来源；
- macOS 的 dB/scalar 转换与 Windows 的 EndpointVolume 范围分别通过单调性和回读测试；
- 写入前后设备 ID 一致；
- 写入后回读值与目标值在允许误差内；
- 用户中途调节时立即停止程序控制；
- 设备切换、权限丢失或写入失败时回退到只监控；
- Windows 与 macOS 各自完成真实设备校准，分别留下结果。

安全门禁：

- M8a shadow 中始终不写系统音量；
- M8b 只允许下降，不允许自动升高、静音或修改 PCM；
- 自动降低不得突破用户设置的最低系统音量；
- 未校准或映射不可靠的设备不得进入 M8b；
- Peak Guard 在本阶段仍无系统音量写权限。
