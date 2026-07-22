# 负担程度 / 摇摆速率 打标标准

> 本文档用于给 cafe-playlist 专辑库的 `burden_level`(负担程度) 和 `swing_rate`(摇摆速率) 两个维度打标。
> 目的：先由你（人工）标注一批锚点样本，再用「音频分析 + 曲风兜底」自动推广到全库。
> 生成依据：从 Notion 原始表反推出的 11 个已标注样本 + 你确认的定义。

---

## 0. 量表约定（已确认）

- **两个维度都是 1–10 制**（不是 1–7）。数值可带小数（如 6.55）。
- 与 `noise_level`（噪音程度，1–7 制）是**相互独立**的维度，不要混用。

---

## 1. 负担程度 burden_level

### 定义（已确认）
**听觉信息密度 + 情绪重量** —— 越需要集中精力去听/消化、信息量越大、情绪越沉重，负担越高。
**关键：与「吵/音量大」无关。** 一张安静的古典交响可以负担很高，一张吵闹的流行摇滚可以负担不高。

### 锚点样本（来自你的真实标注）

| 数值 | 专辑 | 类型 | 说明 |
|------|------|------|------|
| 2.0 | The Beast in Its Tracks | indie-folk | 轻盈，好入耳，几乎无负担 |
| 2.5 | Esja | 纯钢琴/ambient jazz/古典 | 安静舒缓，听感轻 |
| 3.0 | Dark Times | hip-hop/jazz hip-hop/neo-soul | 有内容但流畅、"挺高级"不费劲 |
| 3.5 | Dreamer On The Run | post-rock | 有张力但不烧脑 |
| 3.5 | Blue Building Blocks | math-rock | 技术性但仍轻快 |
| 4.0 | eye | electronic/indie-rock/math-rock | 失真氛围，中等密度 |
| 4.0 | Prayer | ambient jazz/jazz hip-hop | 中等 |
| 5.0 | Expanding To One | ambient jazz/jazz | 偏密集的爵士 |
| 5.0 | 十万个为什么 | ambient-rock/post-rock | 层层薄雾、概念性强(概念传达8.5) |
| 7.5 | Inner Symphonies | 古典/当代古典 | 信息量极大，需认真听 |
| 8.0 | Memory Streams | ambient jazz/fusion jazz/math-rock | 复杂融合，信息量爆炸 |

### 分档参考

| 区间 | 档位 | 典型 | 打标提示 |
|------|------|------|---------|
| 1–3 | 低 | indie-folk、纯钢琴、acoustic、lofi、轻爵士 | 能当背景、不占用注意力 |
| 3.5–5 | 中 | post-rock、math-rock、indie-rock、多数爵士/嘻哈 | 有内容，认真听有收获，但不累 |
| 6–8 | 高 | 古典交响、当代古典、复杂融合爵士、experimental | 信息密集/情绪沉重，需专注 |
| 8.5–10 | 极高 | 先锋/噪音/极复杂编曲/沉重概念 | 极度烧脑，咖啡店慎用 |

### 打标时可参考的 Notion 辅助字段
你的 Notion 表里这些字段和负担高度相关，标注时可交叉参考：
`概念传达`（越高越可能高负担）、`技法`、`细节处理`、`专辑观感`、`感情分`（情绪重量）。

---

## 2. 摇摆速率 swing_rate

### 定义（已确认）
**律动 / 节奏摆动感 / groove** —— 身体想跟着摆动的程度。爵士、funk、嘻哈的 swing 高；ambient、古典、drone 的 swing 低。

### 锚点样本（⚠️ 仅 4 张，且全为高值，低值区严重缺样本）

| 数值 | 专辑 | 类型 |
|------|------|------|
| 5.0 | Dreamer On The Run | post-rock |
| 6.5 | Dark Times | jazz hip-hop |
| 6.5 | 十万个为什么 | ambient-rock/post-rock |
| 6.55 | Blue Building Blocks | math-rock |

### 分档参考（低值区为推测，**急需你补标**）

| 区间 | 档位 | 典型（推测） | 状态 |
|------|------|-------------|------|
| 1–2.5 | 极低/低 | ambient、古典、drone、纯钢琴 | ⚠️ 无样本，请优先补 |
| 3–4.5 | 中 | folk、indie-pop、pop、dream pop、shoegaze | ⚠️ 无样本，请优先补 |
| 5–6.5 | 高 | jazz、funk、hip-hop、math-rock、soul | ✅ 有样本 |
| 7–10 | 极高 | swing爵士、强groove funk/放克 | 待确认上限 |

---

## 3. 你需要补标什么（关键行动）

当前锚点严重不均衡，为了让自动推广准确，**建议你补标 15–20 张**，优先覆盖空白区：

1. **【最急】低摇摆样本**：找 3–5 张 ambient / 古典 / 纯钢琴 / drone 专辑，标 swing（预计 1–2.5）。
2. **【急】中摇摆样本**：找 3–5 张 folk / pop / dream pop，标 swing（预计 3–4.5）。
3. **低负担 + 各风格交叉**：确认 indie-pop、shoegaze、electronic 这些中间地带的 burden。
4. 每个维度尽量覆盖 1–10 的各个刻度，让锚点分布均匀。

补标方式：直接在 Notion 原表填 `负担程度` / `摇摆速率` 两列，重新导出 CSV，跑 `import` 合并即可（保留已有 URL/时长）。

---

## 4. 打标完成后如何生效

1. 已标注的专辑：直接进 `albums.json`，评分引擎自动使用（六维已接入，见 scheduler_engine.py）。
2. 未标注的专辑：
   - 优先走**音频分析**（librosa 提取特征 → 映射 1–10，详见后续脚本）。
   - 拿不到音频的，用 `scheduler_config.json` 里的 `genre_burden_map` / `genre_swing_map` 兜底（已按本标准的定义配好）。
3. 评分引擎的 `compute_score` 已实现动态权重重归一化：某专辑缺该值时该维度自动不参与，不会因为空值拉偏结果。

---

## 5. 数值校准建议

补标后，用 `data/albums.json` 里所有已标注专辑做一次校准：
- 检查同一曲风的人工标注值 vs 曲风映射表的估算值，偏差大的调整映射表。
- 检查音频分析输出的分布是否和人工锚点对齐（比如把 11 个锚点的音频特征跑一遍，看落点是否合理），必要时调整「特征→1-10」的映射系数。
