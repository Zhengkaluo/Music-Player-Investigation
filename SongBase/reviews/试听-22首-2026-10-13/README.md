# 第三四批22首试听

2026-10-13初建时只做试听，未裁切、未修改自动验收状态、未入库。其后已按人工决定裁尾并正式入库，最新状态见下方。

- 前13首：疑似循环尾部，使用accepted记录中明确关联的完整MP3。
- 后9首：自动削波失败，使用最新失败take中完整WAV，不重新编码、不改变增益；播放已到原曲末尾，时长有效。
- 按QQ MID、标题与完整歌手核对来源；试听清单.json记录原路径、SHA-256、时长、检测原因与待复核状态。
- audio目录使用指向明确原文件的符号链接；不移动或修改源音频。
- it is over、Bossa No Sé因播放器超时没有录音，不加入本页。
- 复用上一轮试听页、原生audio controls和SongBase/serve_songbase.py；提供“试听最后20秒”和HTTP Range拖动。

复验命令：

```sh
python3 verify_audition.py http://127.0.0.1:8770/reviews/%E8%AF%95%E5%90%AC-22%E9%A6%96-2026-10-13/
```

## 2026-10-13 人工试听结果

6首各裁去最后1秒：Paradise、Cry Cry Cry、me me she、疯狂的朋友、じゃむ(feat. iri)、Fair-Weather Friend。

其他16首人工认可，保留全长，其中9首削波录音单独记录为 manual-approved-exception，原失败状态不变。当时尚未正式入库，2首播放器超时曲目另行处理。

原始WAV与MP3保留，SHA-256未变。6首裁切WAV精确减少44100帧，剩余PCM与原录音前缀逐字节一致；无淡出或归一化。MP3从裁切WAV按原管线（320k、固定-1dB编码余量）导出，未对原MP3重复衰减；解码、峰值和时长核验通过。

试听清单保留原路径与哈希，新版本音频路径带 trimmed-tail-1s；人工试听决定、批次 dashboard-review-decisions.json 和 manual-delivery-exceptions.json 保存授权与裁切证据。

## 正式入库

本页22首已纳入第三、四批共116首正式入库。元数据、实际音源路径与SHA-256见 `SongBase/imports/2026-10-13-歌单补充B03B04-116首元数据导入.json/.md` 与 `2026-10-13-歌单补充B03B04-116首正式入档.json/.md`。9首人工例外导出的MP3保留对应WAV和自动失败证据；本试听页仍提供原WAV，不替换历史试听来源。

it is over和Bossa No Sé已用新的“2首无回音重录”批次补齐，未使用旧回音录音。Bossa原单曲链接已下架，用户明确改用Para Mi专辑版；主库使用实际MID与专辑。

