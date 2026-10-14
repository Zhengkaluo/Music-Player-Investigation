# 第一二批13首试听

2026-10-12。只做试听，不改变录制状态、交付状态或主库。

- 前10首使用对应accepted记录中的MP3；原哈希核对通过。
- 后3首使用最新完整失败take的WAV，播放结束证据与目标时长核对通过；保留原有削波，不重新编码、不改变增益。
- lowkey的短测试片段未选入；使用171.7116秒完整录音。
- audio目录为指向明确源文件的本地符号链接，不移动、删除或修改原文件。
- 试听清单.json记录QQ MID、完整歌手、原路径、原SHA-256、实测时长与复核原因。
- 本地HTTP必须支持Range；复用SongBase/serve_songbase.py。
- 校验命令：python3 verify_audition.py http://127.0.0.1:8770/reviews/%E8%AF%95%E5%90%AC-13%E9%A6%96-2026-10-12/

原始批次：/Users/kaluozheng/MusicPlayer-FlowSystem/workspace/recordings/歌单补充-B01-B02-118首-2026-10-11


## 2026-10-12 人工试听决定

后山舞曲、Pandemonium、All Around、Fucking Young / Perfect各裁最后1秒；另9首保留完整录音。4份衍生WAV均验证恰少44100帧，剩余PCM样本逐块与原始WAV一致，没有淡出或额外增益处理。3份MP3沿用原录制的编码参数，未对原MP3叠加衰减。

原自动状态未改写：3首削波失败另记manual-approved-exception；10条疑似尾部检测保留为历史证据，人工复核已完成。当前未执行正式入库，也未启动那2首播放器超时曲目的重录。

完整决定与3首人工例外分别见录制batch的dashboard-review-decisions.json与manual-delivery-exceptions.json。试听页已切换为衍生音频的新URL，避免缓存旧版本。


## 正式入库（2026-10-12）

本页13首已随116首正式入库，包括4首裁尾版本与3首人工认可例外。原始录音、自动失败和人工授权均保留。当前事实见试听清单.json的formal_import及imports/2026-10-12-歌单补充116首正式入档.json；前文“未入库”是历史试听准备状态。

