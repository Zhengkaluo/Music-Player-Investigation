# 咖啡店曲库标签说明

## 标签系统原则

这套标签用于咖啡店曲库整理，目标是在不过度复杂的前提下，描述歌曲的风格、语言和器乐性。

使用原则如下：

- 每首歌必须有 1 个主风格，可选 0–2 个副风格
- 主风格描述最核心、最稳定的音乐身份；副风格只记录同样清晰但次要的骨架或审美方向
- 需要时补充 1 个语言标签
- 少数歌曲补充 `Instrumental` 作为附加标签
- 中文、英文歌曲默认不标语言
- 主风格不可在副风格中重复，副风格之间也不可重复
- 没有足够明确的第二种风格时，`secondary_genres` 保持空列表，不为凑数量而补标签
- 如果出现犹豫，优先标记这首歌最稳定、最核心的风格特征
- 驱动力（平静 / 渐进 / 有冲劲 / 爆发）不属于本标签体系，统一由 Flowset 的能量状态维护

---

## 标签总表

### 主风格与副风格

- `genre`：唯一主风格，回答“如果只能选一个，这首歌最应该归到哪里”。
- `secondary_genres`：0–2 个副风格，记录对听感与编曲同样有持续影响、但不是第一身份的风格。
- 编制、速度、情绪或单一音色不单独构成副风格；必须能听到对应风格的结构、律动、和声或制作逻辑。
- 边界犹豫不等于双标签。只有两种风格都成立时才使用副风格；如果只是无法决定，应继续判断主风格。

正式记录示例：

```json
{
  "genre": "Electronic",
  "secondary_genres": ["Ambient / Neo-Classical"],
  "language": null,
  "instrumental": null
}
```

`instrumental` 使用三态：`true` 表示 Instrumental，`false` 表示已确认非器乐，`null` 表示尚未判断。未知状态不得自动当作非器乐。

### 一、风格 Genre

#### Ambient / Neo-Classical

用于氛围、钢琴、现代古典、极简器乐、配乐感较强的作品。

适用于：

- 钢琴为主的器乐作品
- 情绪留白较多、动态较小的作品
- 有明显现代古典、氛围、室内乐气质的音乐

不适用于：

- 只是节奏偏慢，但本质仍是民谣、摇滚或流行的作品
- 有明显摇滚推进结构的作品

#### Post-Rock / Cinematic

用于后摇、电影感、情绪递进、大场景铺陈明显的作品。

适用于：

- 从安静逐渐推进到高潮的器乐或乐队作品
- 画面感强、层层堆叠的编曲
- 具有明显后摇、史诗感、配乐化推进的音乐

不适用于：

- 单纯安静但没有明显推进结构的作品
- 以电子氛围为主、缺乏后摇骨架的作品

#### Electronic

用于电子乐主导的作品，重点在于节拍、合成器、音色设计和制作感。

适用于：

- Downtempo、IDM、House、Synth、电子氛围类作品
- 节拍和电子音色是主要识别特征的音乐

不适用于：

- 只是加入少量电子元素，但整体骨架仍属于摇滚、民谣或 R&B 的作品

#### Jazz / Soul

用于爵士、灵魂、Neo-Soul，以及 groove 和和声质感较突出的作品。

适用于：

- 爵士器乐
- 带明显 swing、groove、soul 气质的作品
- 和声细腻、律动感稳定的音乐

不适用于：

- 只是“听起来柔和”但没有明显爵士或灵魂乐特征的作品

#### Folk / Singer-Songwriter

用于民谣、唱作、叙述性强、原声感明显的作品。

适用于：

- 以创作歌手为核心的作品
- 木吉他、原声编制明显
- 人声表达和歌词叙述是作品核心的歌曲

不适用于：

- 虽由唱作人演唱，但整体编曲和乐队感已经明显偏向摇滚或流行制作的作品

#### Rock / Alternative

用于摇滚、独立摇滚、另类、Dream Pop、Britpop 等吉他或乐队骨架明显的作品。

适用于：

- 吉他、贝斯、鼓构成核心框架
- 独立摇滚、另类摇滚、Dream Pop 等作品
- 乐队整体声响是主要识别点的歌曲

不适用于：

- 明显属于后摇体系的作品
- 核心特征更偏电子制作或说唱节奏的作品

#### Hip-Hop / R&B

用于说唱、R&B、Lo-fi hip-hop，以及以 beat 和 vocal phrasing 为核心的作品。

适用于：

- Rap、R&B、Lo-fi hip-hop
- 节奏型明显，beat 和人声律动是作品核心
- 具有稳定 groove 和 urban 气质的歌曲

不适用于：

- 虽有电子节拍，但核心并非说唱或 R&B 结构的作品

---

### 二、语言 Language

#### Minnan

用于主体演唱语言为闽南语或台语的作品。

适用于：

- 主要歌词内容为闽南语 / 台语

不适用于：

- 只出现少量闽南语词句，但主体语言并非闽南语的歌曲

#### Japanese

用于主体演唱语言为日语的作品。

适用于：

- 主要歌词内容为日语

不适用于：

- 仅有少量日语采样或短句点缀的歌曲

#### Other Languages

用于除中文、英文、闽南语、日语之外的其他语言作品。

适用于：

- 韩语
- 法语
- 德语
- 西班牙语
- 葡萄牙语
- 意大利语
- 俄语
- 其他非中英、非闽南语、非日语歌曲

不适用于：

- 中文歌曲
- 英文歌曲
- 已适用 `Minnan` 或 `Japanese` 的歌曲

---

### 三、器乐性 Vocal Form

#### Instrumental

用于纯器乐，或人声不是主要信息载体的作品。

适用于：

- 无主唱
- 人声仅作为氛围元素存在
- 器乐、配乐型作品

不适用于：

- 歌词和主唱表达仍是主要识别重点的歌曲

说明：

`Instrumental` 是附加标签，不替代风格标签。  
例如一首钢琴曲不应只标 `Instrumental`，而应标记为：

`Ambient / Neo-Classical + Instrumental`

---

## 边界判断

### Ambient / Neo-Classical 与 Post-Rock / Cinematic

两者都可能带有器乐、画面感和情绪性，但重点不同。

- `Ambient / Neo-Classical` 更偏留白、悬浮、细腻、极简
- `Post-Rock / Cinematic` 更偏推进、堆叠、起伏、场景展开

如果一首歌最重要的特征是“安静流动”，更适合前者。  
如果最重要的特征是“情绪逐步被推起来”，更适合后者。

### Rock / Alternative 与 Folk / Singer-Songwriter

- `Folk / Singer-Songwriter` 更重视叙述感、人声表达和唱作核心
- `Rock / Alternative` 更重视乐队结构和整体声响

如果一首歌的核心是“这位歌手在唱什么”，更偏 Folk。  
如果核心是“这首歌整体的乐队声响和编曲结构”，更偏 Rock。

### Electronic 与 Hip-Hop / R&B

- `Electronic` 更重制作、音色、电子编排
- `Hip-Hop / R&B` 更重 beat、groove 和人声节奏表达

如果核心在音景和电子制作，优先 `Electronic`。  
如果核心在 beat 和 vocal phrasing，优先 `Hip-Hop / R&B`。

---

## 标注建议

推荐按以下顺序判断标签：

1. 先确定主风格
2. 判断是否存在清晰且持续的第二种风格；有则补 1–2 个副风格
3. 如有需要，再补一个语言标签
4. 如果是纯器乐或近似纯器乐，再补 `Instrumental`

驱动力请在 Flowset 的能量状态中标注：`平静`、`渐进`、`有冲劲`、`爆发`。

常见组合示例：

- 主 `Ambient / Neo-Classical` + `Instrumental`
- 主 `Post-Rock / Cinematic` + 副 `Ambient / Neo-Classical` + `Instrumental`
- 主 `Electronic` + 副 `Jazz / Soul`
- 主 `Jazz / Soul`
- 主 `Rock / Alternative` + 副 `Electronic`
- `Folk / Singer-Songwriter + Minnan`
- `Hip-Hop / R&B + Other Languages`

---

## 标签清单

最终使用的标签如下：

- Ambient / Neo-Classical
- Post-Rock / Cinematic
- Electronic
- Jazz / Soul
- Folk / Singer-Songwriter
- Rock / Alternative
- Hip-Hop / R&B
- Minnan
- Japanese
- Other Languages
- Instrumental
