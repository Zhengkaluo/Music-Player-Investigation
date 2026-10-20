#!/usr/bin/env python3
"""Collect dated cafe context from fixed sources, never search or schedule songs."""
import argparse
import csv
import io
import json
import math
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from context_astronomy import TERMS, solar_terms, sun_times
from context_sources import SourceClient

BASE = Path(__file__).resolve().parent
UTC = timezone.utc
LUNAR_URL = 'https://data.weather.gov.hk/weatherAPI/hko_data/calendar/nongli_calendar_{year}.csv'
TERMS_URL = 'https://www.hko.gov.hk/tc/gts/time/calendar/text/files/T{year}c.txt'
WEATHER_URL = 'https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat:.4f}&lon={lon:.4f}'
MONTHS = {m: i for i, m in enumerate('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(), 1)}
NUMBERS = {'正': 1, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6,
           '七': 7, '八': 8, '九': 9, '十': 10, '十一': 11, '十二': 12, '腊': 12, '臘': 12}
DAYS = ['初一', '初二', '初三', '初四', '初五', '初六', '初七', '初八', '初九', '初十',
        '十一', '十二', '十三', '十四', '十五', '十六', '十七', '十八', '十九', '二十',
        '廿一', '廿二', '廿三', '廿四', '廿五', '廿六', '廿七', '廿八', '廿九', '三十']
WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
FIXED_HOLIDAYS = {(1, 1): ('holiday.new_year', '元旦／公历新年'), (2, 14): ('holiday.valentine', '情人节'),
                  (10, 31): ('holiday.halloween', '万圣节'), (12, 25): ('holiday.christmas', '圣诞节')}
LUNAR_HOLIDAYS = {(1, 1): ('holiday.lunar_new_year', '春节'), (1, 15): ('holiday.lantern_festival', '元宵'),
                  (5, 5): ('holiday.dragon_boat', '端午'), (7, 7): ('holiday.qixi', '七夕'),
                  (8, 15): ('holiday.mid_autumn', '中秋'), (9, 9): ('holiday.double_ninth', '重阳')}


def load_settings(path=None):
    settings = json.loads((BASE / 'context_settings.json').read_text(encoding='utf-8'))
    if path:
        custom = json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(custom, dict) or any(k not in settings for k in custom):
            raise ValueError('采集配置存在未知字段。')
        settings.update(custom)
    return settings


def get_timezone(name):
    if name in ('UTC', 'Z'):
        return UTC
    match = re.fullmatch(r'([+-])(\d{2}):(\d{2})', name)
    if match:
        hours, minutes = int(match[2]), int(match[3])
        if hours > 14 or minutes > 59 or (hours == 14 and minutes):
            raise ValueError('无效时区偏移。')
        return timezone(timedelta(minutes=(hours * 60 + minutes) * (-1 if match[1] == '-' else 1)))
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name == 'Asia/Shanghai':
            return timezone(timedelta(hours=8), name='Asia/Shanghai')
        raise ValueError('没有此 IANA 时区的数据；Windows 可使用明确的 +08:00 偏移。') from None


def parse_lunar_csv(text, year):
    reader = csv.DictReader(io.StringIO(text.replace('\r\r\n', '\n'), newline=None))
    if not {'Gregorian Date', 'Lunar month', 'Lunar Date'}.issubset(reader.fieldnames or []):
        raise ValueError('天文台农历 CSV 表头不符合固定接口契约。')
    result = {}
    for row in reader:
        if not any(row.values()):
            continue
        match = re.fullmatch(r'(\d{1,2})-([A-Za-z]{3})-(\d{2}|\d{4})', row['Gregorian Date'].strip())
        if not match or match[2] not in MONTHS or int(match[3]) not in (year, year % 100):
            raise ValueError('历表日期或年份不匹配。')
        day = date(year, MONTHS[match[2]], int(match[1])).isoformat()
        raw_month, raw_day = row['Lunar month'].strip(), row['Lunar Date'].strip()
        month_text = raw_month.replace('閏', '').replace('闰', '').removesuffix('月')
        if month_text not in NUMBERS or raw_day not in DAYS or day in result:
            raise ValueError('历表农历字段无效或日期重复。')
        result[day] = {'month': NUMBERS[month_text], 'day': DAYS.index(raw_day) + 1,
                       'leapMonth': '閏' in raw_month or '闰' in raw_month,
                       'label': raw_month + raw_day, 'ganZhiYear': row.get('Chinese year (Gan-Zhi)'),
                       'basisTimezone': 'Asia/Shanghai', 'source': 'hko-lunar'}
    if not result:
        raise ValueError('历表没有日期记录。')
    return result


def parse_official_terms(text, year):
    names = {name: ('solar_term.' + key) for name, key, *_ in TERMS}
    traditional = str.maketrans({'驚': '惊', '蟄': '蛰', '穀': '谷', '滿': '满', '處': '处'})
    found = {}
    for line in text.splitlines():
        match = re.match(r'\s*(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日\s+(.+)', line)
        if not match or int(match[1]) != year:
            continue
        suffix = match[4].translate(traditional)
        for name, tag in names.items():
            if re.search(r'(?<!\S)' + name + r'(?!\S)', suffix):
                if tag in found:
                    raise ValueError('官方节气表重复。')
                found[tag] = {'name': name, 'tag': tag, 'date': date(year, int(match[2]), int(match[3])).isoformat(),
                              'at': None, 'timezone': 'Asia/Shanghai', 'approximate': False,
                              'dateStatus': 'official-calendar-date', 'source': TERMS_URL.format(year=year)}
    if len(found) != 24:
        raise ValueError('未能从目标年份官方历表核对完整的二十四节气。')
    return sorted(found.values(), key=lambda x: x['date'])


def parse_weather(payload, start, end, now, max_age_hours):
    properties = payload['properties']
    series = properties['timeseries']
    if not isinstance(series, list) or not series:
        raise ValueError('天气响应缺少时间序列。')
    updated_text = properties.get('meta', {}).get('updated_at')
    updated = datetime.fromisoformat(updated_text) if updated_text else None
    if updated and updated.tzinfo is None:
        raise ValueError('预报更新时间必须带时区。')
    age = (now - updated).total_seconds() / 3600 if updated else None
    intervals, seen, previous_end = [], set(), None
    for row in sorted(series, key=lambda x: x['time']):
        at = datetime.fromisoformat(row['time'])
        if at.tzinfo is None or at in seen:
            raise ValueError('预报时刻缺少时区或有重复。')
        seen.add(at)
        block_hours = next((hours for hours in (1, 6, 12) if f'next_{hours}_hours' in row['data']), None)
        if block_hours is None:
            continue
        until = at + timedelta(hours=block_hours)
        if until <= start or at >= end:
            continue
        left, right = max(at, start), min(until, end)
        if previous_end and left < previous_end:
            raise ValueError('预报区间重叠，不能重复计算覆盖。')
        previous_end = right
        details = row['data'].get('instant', {}).get('details', {})
        block = row['data'][f'next_{block_hours}_hours']
        symbol = block.get('summary', {}).get('symbol_code')
        base_symbol = (symbol or '').split('_')[0]
        tags = []
        if 'rain' in base_symbol:
            tags = ['weather.rain']
        elif base_symbol in ('clearsky', 'fair'):
            tags = ['weather.clear']
        elif base_symbol == 'cloudy':
            tags = ['weather.overcast']
        def numeric(value):
            return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None
        intervals.append({'forecastStartAt': at.astimezone(start.tzinfo).isoformat(),
                          'forecastEndAt': until.astimezone(start.tzinfo).isoformat(),
                          'windowStartAt': left.astimezone(start.tzinfo).isoformat(),
                          'windowEndAt': right.astimezone(start.tzinfo).isoformat(),
                          'resolutionHours': block_hours, 'temperatureC': numeric(details.get('air_temperature')),
                          'cloudCoverPercent': numeric(details.get('cloud_area_fraction')), 'symbol': symbol,
                          'precipitationMmForSourceInterval': numeric(block.get('details', {}).get('precipitation_amount')),
                          'tags': tags})
    covered = sum((datetime.fromisoformat(x['windowEndAt']) - datetime.fromisoformat(x['windowStartAt'])).total_seconds() for x in intervals)
    status = 'available' if covered == (end - start).total_seconds() else 'partial-coverage'
    if not intervals:
        status = 'outside-forecast-range'
    elif updated is None:
        status = 'unknown-update-time'
    elif age < -0.1:
        status = 'invalid-future-update'
    elif age > max_age_hours:
        status = 'stale'
    temps = [x['temperatureC'] for x in intervals if x['temperatureC'] is not None]
    return {'status': status, 'usableForSuggestions': status in ('available', 'partial-coverage'),
            'updatedAt': updated_text, 'ageHours': age, 'coverageSeconds': covered,
            'requestedSeconds': (end - start).total_seconds(), 'resolutionHours': sorted({x['resolutionHours'] for x in intervals}),
            'temperatureRangeC': [min(temps), max(temps)] if temps else None, 'intervals': intervals,
            'attribution': 'Data from MET Norway; CC BY 4.0. 数据已按播放区间裁取和归并。',
            'license': 'https://creativecommons.org/licenses/by/4.0/',
            'limitations': '这是数值预报，不是门店实况。温度是源区间起点值；降水量属于完整源区间，不按半小时比例推断。'}


def collect(target, settings, fetcher, *, now=None):
    now = now or datetime.now(UTC)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', target):
        raise ValueError('日期必须写成 YYYY-MM-DD。')
    day = date.fromisoformat(target)
    if not 1901 <= day.year <= 2100:
        raise ValueError('本版日历范围为 1901–2100 年。')
    for key, limit in [('latitude', 90), ('longitude', 180)]:
        value = settings[key]
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or abs(value) > limit:
            raise ValueError('门店坐标无效。')
    for key in ['weatherMaxAgeHours', 'coldAtOrBelowC', 'hotAtOrAboveC', 'eveningBeforeMinutes', 'eveningAfterMinutes']:
        value = settings.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise ValueError('采集阈值须为有限数值或 null。')
    if not 0 < settings['weatherMaxAgeHours'] <= 48:
        raise ValueError('天气时效上限须为 0–48 小时。')
    if not isinstance(settings['enabledHolidays'], list) or any(x not in {v[0] for v in [*FIXED_HOLIDAYS.values(), *LUNAR_HOLIDAYS.values()]} for x in settings['enabledHolidays']):
        raise ValueError('存在未支持的节日启用项。')
    tz = get_timezone(settings['timezone'])
    clocks = []
    for key in ('start', 'end'):
        if not re.fullmatch(r'\d{2}:\d{2}', settings[key]):
            raise ValueError('起止时间须为 HH:MM。')
        clocks.append(time.fromisoformat(settings[key]))
    start, end = [datetime.combine(day, clock, tz) for clock in clocks]
    if end == start:
        raise ValueError('开始与结束时间不能相同。')
    if end < start:
        end += timedelta(days=1)
    # The fixed +08 fallback is correct for modern China, not its historical DST.
    if settings['timezone'] == 'Asia/Shanghai' and not isinstance(tz, ZoneInfo) and day.year < 1992:
        raise ValueError('历史日期需要安装 IANA 时区数据，不能套用现代固定 +08 偏移。')
    dates = [day]
    if (end - timedelta(microseconds=1)).date() != day:
        dates.append(end.date())
    years = sorted({d.year for d in dates})
    tasks = [(f'lunar-{year}', LUNAR_URL.format(year=year), 30 * 86400) for year in years]
    tasks += [(f'solar-{year}', TERMS_URL.format(year=year), 30 * 86400) for year in years]
    tasks.append(('weather', WEATHER_URL.format(lat=settings['latitude'], lon=settings['longitude']), 1800))
    sources, raw, bodies, problems = [], {}, {}, []
    def read_source(task):
        key, url, ttl = task
        try:
            text, meta = fetcher(url, max_age_seconds=ttl)
            return key, text, {'id': key, **meta}, None
        except (OSError, ValueError, KeyError, TypeError) as error:
            return key, None, {'id': key, 'url': url, 'status': 'unavailable', 'checkedAt': now.isoformat()}, str(error)
    with ThreadPoolExecutor(max_workers=3) as pool:
        for key, text, meta, error in pool.map(read_source, tasks):
            sources.append(meta)
            if error:
                problems.append({'source': key, 'reason': error})
            if text is not None:
                bodies[key] = text
                raw[key + ('.json' if key == 'weather' else '.txt')] = text
    lunar, terms_by_year = {}, {}
    for year in years:
        try:
            lunar.update(parse_lunar_csv(bodies[f'lunar-{year}'], year))
        except (KeyError, ValueError) as error:
            problems.append({'source': f'lunar-{year}', 'reason': str(error)})
        try:
            terms_by_year[year] = parse_official_terms(bodies[f'solar-{year}'], year)
        except (KeyError, ValueError) as error:
            terms_by_year[year] = solar_terms(year)
            existing = next((item for item in problems if item['source'] == f'solar-{year}'), None)
            note = '官方表未核对，改列本地天文近似；不冒充官方日期。'
            if existing:
                existing['reason'] = note + existing['reason']
            else:
                problems.append({'source': f'solar-{year}', 'reason': note + str(error)})
    weather_meta = next(x for x in sources if x['id'] == 'weather')
    try:
        weather = parse_weather(json.loads(bodies['weather']), start, end, now, settings['weatherMaxAgeHours'])
        if weather_meta.get('cacheExpired'):
            weather.update(status='expired-cache', usableForSuggestions=False)
    except (KeyError, ValueError, TypeError) as error:
        weather = {'status': 'unavailable', 'usableForSuggestions': False, 'intervals': [], 'reason': str(error)}
    weather['source'] = weather_meta
    calendar, astronomy, contexts = [], [], []
    def add(tag, left, right, basis, source, *, certainty='fact'):
        contexts.append({'tag': tag, 'startAt': left.isoformat() if left else None,
                         'endAt': right.isoformat() if right else None, 'basis': basis, 'source': source,
                         'certainty': certainty, 'status': 'for-discussion', 'autoLockAllowed': False})
    for current_day in dates:
        left = max(start, datetime.combine(current_day, time(), tz))
        right = min(end, datetime.combine(current_day + timedelta(days=1), time(), tz))
        value = lunar.get(current_day.isoformat())
        holidays = [FIXED_HOLIDAYS[(current_day.month, current_day.day)]] if (current_day.month, current_day.day) in FIXED_HOLIDAYS else []
        if value and not value['leapMonth'] and (value['month'], value['day']) in LUNAR_HOLIDAYS:
            holidays.append(LUNAR_HOLIDAYS[(value['month'], value['day'])])
        term = next((x for x in terms_by_year[current_day.year] if x['date'] == current_day.isoformat()), None)
        calendar.append({'date': current_day.isoformat(), 'month': current_day.month,
                         'weekday': WEEKDAYS[current_day.weekday()], 'weekdayLabel': '星期' + '一二三四五六日'[current_day.weekday()],
                         'lunar': value, 'solarTerm': term,
                         'holidays': [{'tag': tag, 'name': name, 'enabled': tag in settings['enabledHolidays']} for tag, name in holidays]})
        astronomy.append(sun_times(current_day, settings['latitude'], settings['longitude'], tz))
        add(f'calendar.month{current_day.month:02d}', left, right, '目标播放日期月份', 'local-calendar')
        add('calendar.' + WEEKDAYS[current_day.weekday()], left, right, '目标播放日期星期', 'local-calendar')
        if current_day.weekday() >= 5:
            add('calendar.weekend', left, right, '星期周末，不代表法定休息或调休', 'local-calendar')
        add('calendar.date.' + current_day.isoformat(), left, right, '精确年月日，不默认年度复现', 'local-calendar')
        for tag, name in holidays:
            if tag in settings['enabledHolidays']:
                add(tag, left, right, name + '；按门店显式启用', 'hko-lunar' if tag in {x[0] for x in LUNAR_HOLIDAYS.values()} else 'fixed-gregorian-rule')
        if term and term['dateStatus'] != 'near-midnight-needs-authoritative-check':
            add(term['tag'], left, right, term['name'] + ('；本地近似，需确认' if term['approximate'] else '；官方历表'), term['source'], certainty='approximate' if term['approximate'] else 'fact')
        for tag, a, b in [('time.morning', time(8), time(11)), ('time.midday', time(11), time(14)), ('time.afternoon', time(14), time(18, 30))]:
            a, b = max(left, datetime.combine(current_day, a, tz)), min(right, datetime.combine(current_day, b, tz))
            if a < b:
                add(tag, a, b, '实际播放区间与门店时段的交集', 'venue-settings')
        sun = astronomy[-1]
        if current_day == day and start.hour < 11:
            add('light.sunrise', start, min(end, datetime.combine(day, time(11), tz)), '日出开店意象，不要求真实日出重叠', 'local-astronomy', certainty='curation-option')
        if sun['sunsetAt']:
            add('light.evening', None, None, '日落约 ' + sun['sunsetAt'] + '；开始窗口由用户确认，不证明晚霞', 'local-astronomy', certainty='curation-option')
    if weather['usableForSuggestions']:
        for interval in weather['intervals']:
            tags = list(interval['tags'])
            temperature = interval['temperatureC']
            for threshold, tag, condition in [('coldAtOrBelowC', 'weather.temperature_cold', lambda t, v: t <= v), ('hotAtOrAboveC', 'weather.temperature_hot', lambda t, v: t >= v)]:
                if temperature is not None and settings.get(threshold) is not None and condition(temperature, settings[threshold]):
                    tags.append(tag)
            for tag in tags:
                add(tag, datetime.fromisoformat(interval['windowStartAt']), datetime.fromisoformat(interval['windowEndAt']),
                    f'气象预报 {interval["symbol"]}；源粒度 {interval["resolutionHours"]} 小时', 'weather', certainty='forecast')
    excluded = set(json.loads((BASE / 'title_context_rules.json').read_text(encoding='utf-8'))['policy']['excluded_tags'])
    contexts = [x for x in contexts if x['tag'] not in excluded]
    snapshot = {'schemaVersion': 'context-playlist-snapshot/v1', 'targetDate': target, 'timezone': settings['timezone'],
                'collectedAt': now.astimezone(tz).isoformat(), 'status': 'partial' if problems or weather['status'] != 'available' else 'complete',
                'venue': {'name': settings['venueName'], 'latitude': settings['latitude'], 'longitude': settings['longitude']},
                'playback': {'startAt': start.isoformat(), 'endAt': end.isoformat(), 'durationMinutes': (end - start).total_seconds() / 60},
                'calendar': calendar, 'astronomy': astronomy, 'weather': weather, 'contexts': contexts, 'sources': sources,
                'problems': problems, 'policy': {'collection': 'fixed-sources-no-llm-search-v1', 'autoLockAllowed': False,
                                               'seasonBasis': settings['seasonBasis'], 'temperatureThresholds': {k: settings[k] for k in ['coldAtOrBelowC', 'hotAtOrAboveC']},
                                               'solarTermsFallback': 'local-approximation-explicitly-labelled', 'requiresConfigurationConfirmation': True}}
    return snapshot, raw


def markdown(snapshot):
    rows = ['# 生成前情景采集', '', f'目标日期：{snapshot["targetDate"]}；时区：{snapshot["timezone"]}；状态：{snapshot["status"]}。',
            f'播放区间：{snapshot["playback"]["startAt"]} 至 {snapshot["playback"]["endAt"]}。', '',
            '这是程序化事实采集和待讨论选项，不是歌单、自动锁曲或播放回执。', '', '## 日历与天文', '']
    for item, sun in zip(snapshot['calendar'], snapshot['astronomy']):
        lunar = item['lunar']['label'] if item['lunar'] else '农历未获取'
        term = item['solarTerm']
        rows.append(f'- {item["date"]} {item["weekdayLabel"]}，{lunar}；节气：{term["name"] if term else "无当日节气"}{"（近似，需确认）" if term and term["approximate"] else ""}；日出 {sun["sunriseAt"] or sun["status"]}，日落 {sun["sunsetAt"] or sun["status"]}（近似）。')
        for holiday in item['holidays']:
            rows.append(f'- 节日事实：{holiday["name"]}；门店{ "已启用" if holiday["enabled"] else "未启用，仅供确认"}。')
    weather = snapshot['weather']
    rows += ['', '## 天气预报', '', f'状态：{weather["status"]}；更新时间：{weather.get("updatedAt") or "未知"}。',
             '温度为源时刻值；降水量属于完整源区间。六小时预报不拆成逐小时事实。', '',
             '| 播放交集 | 源粒度 | 预报 | 温度 ℃ |', '|---|---:|---|---:|']
    for item in weather['intervals']:
        rows.append(f'| {item["windowStartAt"]} 至 {item["windowEndAt"]} | {item["resolutionHours"]} 小时 | {item["symbol"] or "未知"} | {item["temperatureC"] if item["temperatureC"] is not None else "缺失"} |')
    rows += ['', 'Data from MET Norway；[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)，已按播放区间裁取和转换。', '', '## 缺失与边界', '']
    rows += ['- ' + item['source'] + '：' + item['reason'].replace('\n', ' ') for item in snapshot['problems']]
    rows += ['- 季节口径和温度阈值未确认时不自动推定；节日须显式启用。', '- 日出日落不保证实际可见天光；情景曲及开始窗口仍由用户确认。', '', '## 数据来源', '']
    rows += [f'- [{s["id"]}]({s["url"]})；采集 {s.get("retrievedAt") or "未成功"}；核查 {s["checkedAt"]}。' for s in snapshot['sources']]
    return '\n'.join(rows) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='固定接口采集歌单情景；不联网搜索、不生成歌单、不修改 CD')
    parser.add_argument('--date', required=True)
    parser.add_argument('--output-dir', required=True, type=Path, help='新的版本目录，拒绝覆盖')
    parser.add_argument('--settings', type=Path)
    parser.add_argument('--cache-dir', type=Path, default=BASE / '.context-cache')
    parser.add_argument('--offline', action='store_true')
    for key in ['start', 'end', 'timezone', 'user-agent']:
        parser.add_argument('--' + key)
    for key in ['latitude', 'longitude']:
        parser.add_argument('--' + key, type=float)
    args = parser.parse_args(argv)
    try:
        if args.output_dir.exists() or args.output_dir.is_symlink():
            raise ValueError('输出版本目录已存在；请换新版本，禁止覆盖旧证据。')
        settings = load_settings(args.settings)
        overrides = {'userAgent' if k == 'user_agent' else k: getattr(args, k) for k in ['start', 'end', 'timezone', 'user_agent', 'latitude', 'longitude'] if getattr(args, k) is not None}
        settings.update(overrides)
        client = SourceClient(args.cache_dir, settings['userAgent'], offline=args.offline)
        snapshot, raw = collect(args.date, settings, client.fetch)
        args.output_dir.mkdir(parents=True, exist_ok=False)
        (args.output_dir / 'raw').mkdir()
        for name, text in raw.items():
            with (args.output_dir / 'raw' / name).open('x', encoding='utf-8', newline='\n') as output:
                output.write(text)
        for name, value in [('context.json', snapshot), ('sources.json', snapshot['sources'])]:
            with (args.output_dir / name).open('x', encoding='utf-8', newline='\n') as output:
                json.dump(value, output, ensure_ascii=False, indent=2)
                output.write('\n')
        with (args.output_dir / 'context.md').open('x', encoding='utf-8', newline='\n') as output:
            output.write(markdown(snapshot))
        print(json.dumps({'status': snapshot['status'], 'output': str(args.output_dir.resolve()), 'weather': snapshot['weather']['status'], 'problemCount': len(snapshot['problems'])}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
