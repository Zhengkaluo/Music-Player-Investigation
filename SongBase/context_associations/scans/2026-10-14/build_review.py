"""Build this dated review from the unmodified rule scan. All proposals remain pending."""
import copy
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
sys.path.insert(0, str(BASE))
import scan_title_contexts as scanner

scan = scanner.load_json(HERE / 'title_context_candidates.json')
old = scanner.load_json(BASE / 'scans/2026-10-12/title_context_candidates.json')
tracks = scan['tracks']
features_path = BASE.parent / '歌曲特征.json'
features = {t['songBaseId']: t for t in scanner.load_json(features_path)['tracks']}
sources = {
    'avril': 'https://dictionary.cambridge.org/dictionary/french-english/avril',
    'aphex': 'https://aphextwin.warp.net/release/86961-aphex-twin-drukqs?lang=en_US',
    'rain_idiom': 'https://dictionary.cambridge.org/dictionary/english/be-as-right-as-rain?topic=fit-and-healthy',
    'egg_idiom': 'https://dictionary.cambridge.org/us/dictionary/english/sunny-side-up',
    'twilight_idiom': 'https://dictionary.cambridge.org/dictionary/english/twilight-zone',
    'hoppipolla': 'https://sigurros.com/news/2005/hopppolla-video/',
    'plantasia': 'https://mort-garson.com/products/sbr3030-mort-garson-mother-earths-plantasia',
    'cicada': 'https://flau.jp/releases/hiking-in-the-mist/',
}

def track(title, artist):
    found = [t for t in tracks.values() if t['title'] == title and t['artist'] == artist]
    assert len(found) == 1, (title, artist, len(found))
    return found[0]

def record(title, artist, tag, label, judgment, text, reason, source_keys=()):
    t = track(title, artist)
    start = title.index(text)
    return {
        'track_id': t['track_id'], 'title': title, 'artist': artist, 'album': t['album'],
        'tag': tag, 'label': label, 'title_judgment': judgment,
        'review_status': 'pending', 'auto_lock_allowed': False,
        'evidence': [{'type': 'title', 'source_title': title, 'matched_text': text,
                      'span': [start, start + len(text)]}],
        'reason': reason, 'sources': [sources[k] for k in source_keys],
        'generator_catalogue_present': t['track_id'] in features,
        'trigger_hint': {'enabled': False},
    }

additions = [
    record('Avril 14th', 'Aphex Twin', 'calendar.month04', '四月', 'explicit', 'Avril',
           '法语 Avril 表示四月；现词表缺少此别名。月份和日期来自同一依据，不重复加分。', ('avril', 'aphex')),
    record('Avril 14th', 'Aphex Twin', 'calendar.date.04-14', '4 月 14 日', 'explicit', 'Avril 14th',
           '法语月份与英语序数构成标题日期；原解析器仅覆盖英语月份。不是发行日期；年度复现仍未配置。', ('avril', 'aphex')),
    record('4seasons', 'sow', 'season.all', '四季整体／季节流转', 'explicit', '4seasons',
           '数字与英文连写表达四季；现规则仅有 four seasons / all seasons / 四季，不补成四个独立季节。'),
    record('月の光 Arranged by kazumasa hashimoto', 'Kazumasa Hashimoto', 'light.moonlight', '月光意象', 'explicit', '月の光',
           '日语短语字面为月光，属于已保留的月光关联；不恢复已排除的月亮标签，也不推断夜晚。'),
    record('我独自过冬', '碎叠', 'season.winter', '冬季意象', 'explicit', '过冬',
           '过冬是明确冬季语义；现词表仅识别冬天、冬季、冬日、冬の等，不包含此短语。'),
    record('如果太阳落下', '许钧', 'light.sunset', '日落／夕阳', 'explicit', '太阳落下',
           '现扫描仅识别太阳，遗漏落下的完整日落表达；标题带条件句，不代表当地日落事实。'),
    record('晚霞的声音', '重组乐队', 'time.dusk', '黄昏／暮色', 'explicit', '晚霞',
           '晚霞是傍晚天光线索；现词表缺少此表达。不作为天空泛意象回流，也不固定为日落的某一分钟。'),
    record('80°F', 'SoulFa 灵魂沙发', 'weather.temperature_reference', '温度数值意象：80°F（约 26.7°C）', 'explicit', '80°F',
           '明确温度数值，现规则未解析华氏。数值换算不证明描述天气；不自动归为炎热或设置阈值。此通用温度标签是建议补充，未加入规则。'),
    record('Hoppípolla', 'Sigur Rós', 'weather.rain', '雨／雨后积水的间接线索', 'indirect', 'Hoppípolla',
           '乐队官方解释标题为跳进水洼；水洼仅提供雨或雨后联想，不证明正在降雨。此项使用官方标题释义，须与纯本地字面扫描区分。', ('hoppipolla',)),
    record('Umbrella', "I Don't Like Mondays.", 'weather.rain', '雨伞相关的雨天补查线索', 'ambiguous', 'Umbrella',
           '伞也可用于遮阳或比喻，不能直接断定雨天；仅列为补查，不读取艺人名中的 Mondays 建立星期一关联。'),
]

corrections = [
    dict(record("Let's Fall in Love for the Night", 'FINNEAS', 'season.autumn', '秋季意象', 'ambiguous', 'Fall',
                'Fall in love 为恋爱短语，不支持秋季关联；night 在排除清单，不能补回。'), action='exclude'),
    dict(record('Right As Rain', 'Adele', 'weather.rain', '雨意象', 'explicit', 'Rain',
                '完整短语的惯用义为恢复健康／状态良好，标题不足以支持雨关联；不是断言歌词完全没有雨。', ('rain_idiom',)), action='exclude'),
    dict(record('Sunny Side Up', 'Surfaces', 'weather.clear', '晴／晴空意象', 'explicit', 'Sunny',
                '完整短语有单面煎蛋的固定用法，不能只凭 Sunny 标为明确晴天；暂移出天气候选，歌词或官方资料可另建证据。', ('egg_idiom',)), action='exclude'),
    dict(record('Tone Twilight Zone', 'CORNELIUS', 'time.dusk', '黄昏／暮色待确认', 'ambiguous', 'Twilight',
                'Twilight zone 也指过渡／模糊状态，不能仅提取 Twilight 视作明确黄昏；降为歧义，未确认作者意图。', ('twilight_idiom',)), action='reclassify'),
    dict(record('Siesta Freestyle', 'Lewis OfMan, Alicia te quiero', 'time.afternoon', '午休／午后活动线索', 'indirect', 'Siesta',
                'Siesta 是午休活动线索，类似 Breakfast，不是明确播放钟点；建议从明确关联改为间接线索。'), action='reclassify'),
]

# These are proposed new themes, not missing matches under the six existing categories.
theme_rows = [
    ('activity.tea_coffee', '咖啡／茶', 'アイスカフェラテ', 'Forest306', 'カフェラテ', 'explicit', '冰拿铁标题；冷饮不恢复冰意象，不推出季节。'),
    ('activity.tea_coffee', '咖啡／茶', 'Sleepy Tea', 'Chon', 'Tea', 'explicit', '茶的标题意象；不因此推下午适配。'),
    ('activity.tea_coffee', '咖啡／茶', '二人でお茶を', '北村英治', 'お茶', 'explicit', '两人喝茶的标题线索；适合茶主题策展，不默认下午时段。'),
    ('activity.food_drink', '餐饮／酒饮', 'I Drink Wine', 'Adele', 'Wine', 'explicit', '酒饮主题标题。'),
    ('activity.food_drink', '餐饮／酒饮', 'Sémillon', '尚先生', 'Sémillon', 'ambiguous', '葡萄品种名的词义尚需独立来源核对；不要仅从专辑小酒馆推断歌曲内容。'),
    ('activity.food_drink', '餐饮／酒饮', 'Pink Lemonade', 'Johnny Stimson', 'Lemonade', 'explicit', '柠檬饮品标题；不自动推出夏季。'),
    ('activity.picnic', '野餐', 'picnic-perfect', 'A Picture Of Her', 'picnic', 'explicit', '野餐活动标题；只在相应门店活动或主题中考虑。'),
    ('activity.work', '工作／通勤', 'GO TO WORK', 'KOHEI JAPAN', 'WORK', 'explicit', '去工作的标题线索；时段听感独立检查。'),
    ('activity.cycling', '骑行', 'Biking', 'Frank Ocean, JAŸ-Z, Tyler, The Creator', 'Biking', 'explicit', '骑行标题；不推固定速度或能量。'),
    ('activity.dance', '舞动', 'God Gave Me Feet For Dancing (feat. Yazmin Lacey)', 'Ezra Collective, Yazmin Lacey', 'Dancing', 'explicit', '跳舞标题；节奏适配需听感依据。'),
    ('place.window', '窗边／阳台', '窓辺', 'haruka nakamura', '窓辺', 'explicit', '日语窗边标题；不从 Twilight 专辑继承黄昏。'),
    ('place.veranda', '窗边／阳台', 'ベランダにて', 'haruka nakamura', 'ベランダ', 'explicit', '阳台／露台标题；不从专辑标题继承时段。'),
    ('place.mountain_forest', '山林／步行', '山屋里的小脚印', 'Cicada', '山屋', 'explicit', '山屋地点标题；没有天气关联也可有自然场所主题。'),
    ('place.mountain_forest', '山林／步行', '越过海岸山脉 (Over Coastal Range)', 'Cicada', '山脉', 'explicit', '山脉标题；背景和实际地域应另证。'),
    ('nature.plants', '植物／园艺', 'Wild Orchid', 'Devon Rea, Etymology Records', 'Orchid', 'explicit', '兰花标题；不能统一当成春季物候。'),
    ('nature.plants', '植物／园艺', 'Peonies for Breakfast', 'LAUSSE THE CAT', 'Peonies', 'explicit', '牡丹／芍药类标题线索；花期和种类需进一步核对，不自动绑定月份。'),
    ('nature.plants', '植物／园艺', 'Lotus Blossom (Explicit)', 'LAUSSE THE CAT', 'Lotus', 'explicit', '莲花标题；仅植物主题，不自动推出夏季。'),
    ('nature.plants', '植物／园艺', '花', '藤井风', '花', 'explicit', '泛花意象，主题较宽；不自动转为春季。'),
    ('event.gifting', '送礼／店庆', '礼物', '浅堤, HUSH', '礼物', 'explicit', '送礼主题标题；不证明具体生日、店庆日期。'),
    ('event.gifting', '送礼／店庆', 'Gifts', 'Goldmund', 'Gifts', 'ambiguous', '既可礼物也可天赋，需补查；不匹配具体节日。'),
]
extensions = [record(title, artist, tag, label, judgment, term, reason)
              for tag, label, title, artist, term, judgment, reason in theme_rows]

def background(title, artist, tag, label, keys, reason, evidence_scope):
    t = track(title, artist)
    return {'track_id': t['track_id'], 'title': title, 'artist': artist, 'album': t['album'],
            'tag': tag, 'label': label, 'evidence_type': 'official_background',
            'evidence_scope': evidence_scope, 'sources': [sources[k] for k in keys], 'reason': reason,
            'review_status': 'pending', 'auto_lock_allowed': False,
            'generator_catalogue_present': t['track_id'] in features}

backgrounds = [
    background('Plantasia', 'Mort Garson', 'nature.plants', '植物／园艺', ['plantasia'],
               '官方介绍确认此专辑为植物及喜爱植物的人创作。建议在植物主题活动中优先复核本库的同名曲；不宣称促进植物生长。', 'album'),
    background('山屋里的小脚印', 'Cicada', 'place.mountain_forest', '山林／步行', ['cicada'],
               'FLAU 专辑介绍明确山行记录和山屋野生动物相遇。作为专辑级背景证据，不继承整张专辑所有天气标签。', 'album'),
    background('降落在金黄色草坡', 'Cicada', 'place.mountain_forest', '山林／步行', ['cicada'],
               'FLAU 专辑介绍明确台湾山行背景。英文曲目 Sunlit Grassland 可能提供阳光依据，但尚未核实与本地中文曲名的唯一版本对应，本次不补阳光标签。', 'album'),
]

reviewed = copy.deepcopy(scan)
for r in corrections:
    t = reviewed['tracks'][r['track_id']]
    matches = [a for a in t['associations'] if a['tag'] == r['tag']]
    assert len(matches) == 1
    if r['action'] == 'exclude':
        t['associations'].remove(matches[0])
    else:
        matches[0]['title_judgment'] = r['title_judgment']
for r in additions:
    t = reviewed['tracks'][r['track_id']]
    assert not any(a['tag'] == r['tag'] for a in t['associations'])
    t['associations'].append(r)
items = [a for t in reviewed['tracks'].values() for a in t['associations']]
counts = Counter(a['title_judgment'] for a in items)
reviewed_summary = {'tracks_with_candidates': sum(bool(t['associations']) for t in reviewed['tracks'].values()),
                    'total_associations': len(items), 'associations_by_judgment': dict(counts),
                    'generator_catalogue_candidate_tracks': sum(bool(t['associations']) and tid in features for tid,t in reviewed['tracks'].items())}

def pairs(data):
    return {(tid, a['tag']) for tid, t in data['tracks'].items() for a in t['associations']}

new_pairs, old_pairs = pairs(scan), pairs(old)
diff = {'added_track_ids': sorted(tracks.keys() - old['tracks'].keys()),
        'removed_track_ids': sorted(old['tracks'].keys() - tracks.keys()),
        'added_associations': sorted(new_pairs - old_pairs),
        'removed_associations': sorted(old_pairs - new_pairs)}
excluded = set(scan['policy']['excluded_tags'])
for r in additions + extensions:
    assert r['tag'] not in excluded
    for e in r['evidence']:
        assert r['title'][slice(*e['span'])] == e['matched_text']
assert all(a['review_status'] == 'pending' and not a['auto_lock_allowed'] for a in items)
assert reviewed_summary['tracks_with_candidates'] == 130 and len(items) == 147
assert sum(a['title_judgment'] == 'explicit' for a in additions) == 8
hashes = scanner.load_json(HERE / 'review_source_hashes.json')
assert scanner.digest(scan['source']['path']) == scan['source']['sha256']
assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == sha for p, sha in hashes.items())
result = {'schema_version': 'songbase.context-supplement-review/v1', 'review_date': '2026-10-14',
          'source': scan['source'], 'generator_catalogue_sha256': scanner.digest(features_path),
          'scope': 'full_current_library_rule_scan_plus_agent_title_review_and_limited_primary_source_checks',
          'approval_status': 'all_proposals_pending_user_review',
          'baseline_summary': scan['summary'], 'library_diff': diff,
          'title_additions': additions, 'title_corrections': corrections,
          'proposed_new_theme_candidates': extensions, 'official_background_candidates': backgrounds,
          'hypothetical_summary_if_proposals_adopted': reviewed_summary,
          'policy': scan['policy'], 'source_integrity': {'protected_files_unchanged': True, 'count': len(hashes)}}
(HERE / 'supplemental_review.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')

esc = lambda s: str(s).replace('|', '\\|')
lines = ['# 标题补查与扩展候选明细', '', '2026-10-14；所有条目均待用户复核。规则文件、正式曲库、标签、歌单和历史未改变。', '',
         '原规则重扫：1,554 条记录、1,553 首唯一歌曲；125 首候选、140 条关联。',
         '人工补查：7 首明确标题候选、8 条关联；另 2 首间接或歧义候选、2 条关联。',
         '同时建议排除 3 条误命中、降低 2 条判断强度。以下是独立复核建议，未回写扫描规则。', '',
         '若采纳上述建议，候选将为 130 首、147 条关联；该数包括间接与歧义，不包括新主题扩展和专辑背景候选。', '',
         '## 标题遗漏与间接线索', '', '| 歌曲与艺人 | 建议关联 | 判断 | 原文证据 | 已在生成器目录 | 理由 |', '|---|---|---|---|---|---|']
for r in additions:
    lines.append('| ' + ' | '.join(map(esc, [r['title']+' · '+r['artist'], r['label'], r['title_judgment'],r['evidence'][0]['matched_text'], '是' if r['generator_catalogue_present'] else '否',r['reason']])) + ' |')
lines += ['', '## 误命中与强度纠正建议', '', '| 歌曲与艺人 | 动作 | 关联 | 原因 |', '|---|---|---|---|']
for r in corrections:
    lines.append('| ' + ' | '.join(map(esc,[r['title']+' · '+r['artist'],r['action']+(' → '+r['title_judgment'] if r['action']=='reclassify' else ''),r['label'],r['reason']]))+' |')
lines += ['', '## 新主题试点候选', '', '以下不是现六类词表的遗漏；属于扩展提案。明细仅是一组可审阅例子，不声称全库已覆盖这些新主题。', '', '| 歌曲与艺人 | 新主题 | 判断 | 已在生成器目录 | 原因 |', '|---|---|---|---|---|']
for r in extensions:
    lines.append('| '+' | '.join(map(esc,[r['title']+' · '+r['artist'],r['label'],r['title_judgment'],'是' if r['generator_catalogue_present'] else '否',r['reason']]))+' |')
lines += ['', '## 标题之外的官方背景候选', '']
for r in backgrounds:
    lines.append('- '+r['title']+' · '+r['artist']+'：'+r['reason']+' [官方来源]('+r['sources'][0]+')')
lines += ['', '## 来源与边界', '',
          '- 现有扫描以 QQ MID 为身份；同名歌曲分别审查。新增证据保留命中文字和原标题位置。',
          '- 所有人工补查是 Agent 建议，不是用户已确认关联；新主题和官方背景单独存储。',
          '- 对 1,553 首进行了规则扫描和标题复看；不保证所有多语言词义、作者暗喻已被识别。未试听音频、未全库检索歌词。',
          '- 月光仍保留；月亮、夜晚、云、雪、风、冰等原 14 类排除不会回流。',
          '- 《季风 (Monsoon)》未补雨标签：季风本身含风的含义，不能借改名绕过排除；需独立雨内容证据。',
          '- 《Scarlet Holliday》未当成 holiday：拼写和词义需查证；《恒春花絮》不拆地名恒春认春季；《AWARDS SEASON》不认自然四季。',
          '- 《Mars 2027》《秋水》《Indian Summer》等保留原有歧义边界，没有凭想象确认。',
          '- 官方英文别名可补证据，但需核对艺人、专辑、版本及曲目对应；本次未将 Sunlit Grassland 直接映射为新阳光标签。', '']
for key,url in sources.items():
    lines.append('- ['+key+']('+url+')')
(HERE / '标题补查与扩展候选明细.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'baseline': scan['summary'], 'proposal_summary': reviewed_summary,
                  'strong_title_tracks': len({r['track_id'] for r in additions if r['title_judgment']=='explicit'}),
                  'title_additions':len(additions), 'new_theme_examples':len(extensions), 'diff_counts':{k:len(v) for k,v in diff.items()},
                  'source_integrity':result['source_integrity']},ensure_ascii=False,indent=2))
