# M8a-2～M8a-5 验收报告

> 日期：2026-10-13  
> 模式：真实采集 + 影子决策；自动系统音量写入关闭

## 1. 结论

M8a-2、M8a-3、M8a-4 的实现和自动测试已经完成。M8a-5 的代码门禁与本机 macOS 内建扬声器门禁已通过；Windows 实机以及两平台外接设备矩阵尚未执行，因此当前不开放 M8b `lower-only`。

## 2. 已完成能力

| 阶段 | 结果 | 说明 |
|---|---|---|
| M8a-2 捕获分类 | 通过 | 三档稳定样本分类为 `pre-volume` / `post-volume` / `unreliable`；画像按平台和设备 ID 保存 |
| M8a-3 有效响度 | 通过 | `pre-volume` 加入设备相对最大值的 dB 衰减；`post-volume` 使用捕获值；不可靠时停止建议 |
| M8a-4 dB 建议 | 通过 | 比例下降、每秒最大 dB 变化、最小 dB 步长和设备范围限制均在共享控制器完成 |
| M8a-5 代码门禁 | 通过 | 相同契约供 macOS、Windows 与模拟回放使用；UI 显示档案、置信度、有效响度和 dB 建议 |
| M8a-5 物理设备门禁 | 部分通过 | macOS 内建扬声器通过；其余设备与 Windows 待测 |

## 3. macOS 本机结果

设备：`BuiltInSpeakerDevice`（MacBook Pro 扬声器，`built-in`）

- 捕获分类：`pre-volume`
- 置信度：`high`
- 证据：同一首曲目前约 20 秒，在 31%、50%、69% 系统音量下的 Short-term 曲线基本重合
- dB 来源：`coreaudio-volume-decibels`
- 设备范围：−63.5 dB 至 0 dB
- 实测状态：68.75% = −10.85 dB
- 只读换算：目标 −11.85 dB = 约 66.16%
- 换算前后系统音量保持 68.75%，证明换算命令没有执行写入
- 真实影子服务成功加载画像，得到 `effectiveLufs = sourceShortTermLufs + outputAttenuationDb`
- 动作保持 `execute=false`，没有自动系统音量写入

## 4. 自动化门禁

覆盖内容：

- 三类捕获响应分类；
- 稳定窗口中位数与音量移动拒绝；
- 系统环境、dB 来源和 dB 范围变化后的画像失效；
- 未校准或映射不可靠时停止 dB 建议；
- 建议 dB 的比例、最小步长、速率限制和设备范围；
- macOS dB/scalar 双向能力入口；
- Windows EndpointVolume dB 范围及硬件支持读取；
- 影子动作不执行写入。

## 5. 待完成的物理门禁

| 平台 | 场景 | 必查结果 |
|---|---|---|
| macOS | 蓝牙、USB、HDMI/AirPlay | 捕获位置、dB 映射、可写能力、设备切换后的画像失效 |
| Windows | 内建/主板扬声器、耳机、USB、蓝牙 | 每个 Endpoint ID 的三档分类、dB 范围、步长和回读 |
| Windows | shared / exclusive | loopback 是否可用；exclusive 或中断时是否安全退回只监测 |
| 两平台 | 暂停、静音、淡出、切歌、通知、对白 | 无错误降低、无自动升高、事件合并与建议幅度自然 |

## 6. 进入 M8b 的条件

只有在目标物理设备完成上述门禁，并且档案有效、dB 映射可靠、用户接管和设备切换保护通过后，才允许开发和启用只自动压低。M8a 期间 Peak Guard 和响度控制均无自动系统音量写权限。
