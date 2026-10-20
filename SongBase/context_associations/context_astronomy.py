"""NOAA/Meeus low-order solar calculation, deliberately marked approximate."""
import math
from datetime import date, datetime, time, timedelta, timezone

UTC = timezone.utc
SOURCE = 'https://gml.noaa.gov/grad/solcalc/calcdetails.html'
TERMS = [
    ('小寒', 'xiaohan', 285, 1, 5), ('大寒', 'dahan', 300, 1, 20),
    ('立春', 'lichun', 315, 2, 4), ('雨水', 'yushui', 330, 2, 19),
    ('惊蛰', 'jingzhe', 345, 3, 5), ('春分', 'chunfen', 0, 3, 20),
    ('清明', 'qingming', 15, 4, 5), ('谷雨', 'guyu', 30, 4, 20),
    ('立夏', 'lixia', 45, 5, 5), ('小满', 'xiaoman', 60, 5, 21),
    ('芒种', 'mangzhong', 75, 6, 5), ('夏至', 'xiazhi', 90, 6, 21),
    ('小暑', 'xiaoshu', 105, 7, 7), ('大暑', 'dashu', 120, 7, 23),
    ('立秋', 'liqiu', 135, 8, 7), ('处暑', 'chushu', 150, 8, 23),
    ('白露', 'bailu', 165, 9, 7), ('秋分', 'qiufen', 180, 9, 23),
    ('寒露', 'hanlu', 195, 10, 8), ('霜降', 'shuangjiang', 210, 10, 23),
    ('立冬', 'lidong', 225, 11, 7), ('小雪', 'xiaoxue', 240, 11, 22),
    ('大雪', 'daxue', 255, 12, 7), ('冬至', 'dongzhi', 270, 12, 22),
]


def geometry(at):
    t = (at.timestamp() / 86400 + 2440587.5 - 2451545) / 36525
    radians = math.radians
    longitude = (280.46646 + t * (36000.76983 + 0.0003032 * t)) % 360
    anomaly = radians(357.52911 + t * (35999.05029 - 0.0001537 * t))
    center = (math.sin(anomaly) * (1.914602 - t * (0.004817 + 0.000014 * t))
              + math.sin(2 * anomaly) * (0.019993 - 0.000101 * t) + math.sin(3 * anomaly) * 0.000289)
    omega = radians(125.04 - 1934.136 * t)
    apparent = (longitude + center - 0.00569 - 0.00478 * math.sin(omega)) % 360
    obliquity = radians(23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - 0.001813 * t))) / 60) / 60 + 0.00256 * math.cos(omega))
    declination = math.asin(math.sin(obliquity) * math.sin(radians(apparent)))
    y = math.tan(obliquity / 2) ** 2
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    l = radians(longitude)
    eqtime = 4 * math.degrees(y * math.sin(2 * l) - 2 * e * math.sin(anomaly)
                            + 4 * e * y * math.sin(anomaly) * math.cos(2 * l)
                            - 0.5 * y * y * math.sin(4 * l) - 1.25 * e * e * math.sin(2 * anomaly))
    return apparent, declination, eqtime


def solar_terms(year):
    if not 1901 <= year <= 2100:
        raise ValueError('本地天文计算支持 1901–2100 年。')
    china = timezone(timedelta(hours=8))
    result = []
    for name, key, target, month, day in TERMS:
        center = datetime(year, month, day, 12, tzinfo=UTC)
        left, right = center - timedelta(days=7), center + timedelta(days=7)
        while (right - left).total_seconds() > 1:
            middle = left + (right - left) / 2
            distance = (geometry(middle)[0] - target + 180) % 360 - 180
            if distance < 0:
                left = middle
            else:
                right = middle
        instant = (left + (right - left) / 2).astimezone(china)
        margin = min(instant.hour * 60 + instant.minute, 1440 - instant.hour * 60 - instant.minute)
        result.append({'name': name, 'tag': 'solar_term.' + key, 'date': instant.date().isoformat(),
                       'at': instant.isoformat(timespec='minutes'), 'timezone': 'Asia/Shanghai',
                       'method': 'apparent-solar-longitude-bisection-v1', 'source': SOURCE,
                       'approximate': True, 'uncertaintyMinutes': 20,
                       'dateStatus': 'near-midnight-needs-authoritative-check' if margin <= 20 else 'approximate-date'})
    return result


def sun_times(day, latitude, longitude, tz):
    result = {'date': day.isoformat(), 'status': 'available', 'sunriseAt': None, 'sunsetAt': None,
              'approximate': True, 'method': 'noaa-solar-position-iterated-v1', 'source': SOURCE,
              'limitations': '平地视界、大气折射标准近似；不保证可见日出、晚霞，不包含地形遮挡。'}
    lat = math.radians(latitude)
    for kind, direction in [('sunriseAt', -1), ('sunsetAt', 1)]:
        for shift in (-1, 0, 1):
            midnight = datetime.combine(day + timedelta(days=shift), time(), UTC)
            at = midnight + timedelta(minutes=720 - 4 * longitude)
            polar = None
            for _ in range(4):
                _, declination, equation = geometry(at)
                divisor = math.cos(lat) * math.cos(declination)
                cos_h = (math.cos(math.radians(90.833)) - math.sin(lat) * math.sin(declination)) / max(divisor, 1e-15)
                if not -1 <= cos_h <= 1:
                    polar = 'polar-night' if cos_h > 1 else 'polar-day'
                    break
                angle = math.degrees(math.acos(cos_h))
                at = midnight + timedelta(minutes=720 - 4 * longitude - equation + direction * 4 * angle)
            if polar:
                result['status'] = polar
                break
            local = at.astimezone(tz)
            if local.date() == day:
                result[kind] = local.isoformat(timespec='minutes')
                break
    if result['status'] == 'available' and (result['sunriseAt'] is None or result['sunsetAt'] is None):
        result['status'] = 'date-or-timezone-outside-model'
    return result
