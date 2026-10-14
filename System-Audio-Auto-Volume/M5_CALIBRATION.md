# M5 响度指标校准报告

> 日期：2026-10-05
> 状态：离线算法与平台接入完成；真实设备交叉验收待进行

## 实现

- 实时链路使用 ITU-R BS.1770 K-weighting。
- Momentary 使用 400 ms 窗口，Short-term 使用 3 s 窗口，每 100 ms 更新一个能量块。
- Windows WASAPI 直接调用共享 Python meter。
- macOS Core Audio helper 使用相同系数生成公式，不传输或保存 PCM。
- FFmpeg `ebur128` 只用于离线校准，不进入实时服务。

## 合成信号结果

测试信号为双声道、幅度 0.125、持续 4 秒的正弦波。以下误差为本项目实时结果减 FFmpeg `ebur128` 结果：

| 采样率 | 频率 | Momentary 误差 | Short-term 误差 |
|---:|---:|---:|---:|
| 44.1 kHz | 100 Hz | 0.000 LU | 0.000 LU |
| 44.1 kHz | 1 kHz | 0.000 LU | 0.000 LU |
| 44.1 kHz | 10 kHz | 0.000 LU | 0.000 LU |
| 48 kHz | 100 Hz | 0.000 LU | 0.000 LU |
| 48 kHz | 1 kHz | 0.000 LU | 0.000 LU |
| 48 kHz | 10 kHz | 0.000 LU | 0.000 LU |

本机 Python 实现处理速度为实时的 19.1–20.9 倍。macOS Swift 48 kHz / 1 kHz 自检得到 −18.055 LUFS，FFmpeg 参考值为 −18.056 LUFS。

复现命令：

```bash
python3 src/calibrate_loudness.py \
  --ffmpeg /Users/kaluozheng/MusicPlayer-FlowSystem/node_modules/ffmpeg-static/ffmpeg

xcrun swiftc -swift-version 5 \
  -module-cache-path /private/tmp/system-audio-auto-volume-swift-cache \
  src/macos_monitor.swift -o /private/tmp/SystemAudioMonitor-m5-check
/private/tmp/SystemAudioMonitor-m5-check --self-test
```

## 尚未通过的门禁

- 真实音乐、对白、静音与切歌场景仍需与 FFmpeg 时间序列抽样对照。
- Windows 真实设备的 CPU、回调耗时和 44.1/48 kHz 切换仍需实机验证。
- 多声道的实际 WASAPI 声道顺序尚未验证；当前正式验收范围为 mono/stereo。
- 当前 Peak 仍是 sample peak，不宣称 True Peak。

本阶段没有系统音量写入能力，也没有启动自动控制。

## M5.5 Peak Guard 影子检测

当前实现采用固定 10 ms 能量块，同时观察 Sample Peak、快速 RMS 和约 1 秒 EWMA 基线。启动后的前 1 秒只建立基线、不触发；之后默认条件为 Sample Peak 不低于 −1 dBFS、相对基线突增至少 10 dB，并持续至少 20 ms。触发后依次进入 `ATTACK → HOLD → RELEASE → ARMED`，建议衰减最多 −12 dB。

- Windows 在 WASAPI PCM 回调内调用共享 Python `PeakGuard`；macOS helper 内使用同参数 Swift 实现。
- 平台回调只累计数字和状态，共享服务仅接收摘要，不传输、不保存 PCM。
- 事件契约为 `system-audio.peak-guard-event/v1`，`mode` 固定为 `shadow`，`execute` 固定为 `false`。
- 合成测试确认 30 ms 满幅突增会生成一次建议；10 ms 单峰会被最短持续时间过滤；Hold/Release 后回到待命。
- macOS 合成自检记录 Sample Peak 0 dBFS、相对基线突增约 28.01 dB，并建议 −12 dB，未执行。

当前只实现 Sample Peak；`truePeakDbtp` 为 `null`，不能把这部分称为 True-Peak limiter。真实通知音、强鼓点、切歌阶跃、对白爆破音和 Windows 实机 CPU/误触发率仍是下一轮验收项。
