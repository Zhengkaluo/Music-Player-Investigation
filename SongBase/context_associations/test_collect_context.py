import contextlib
import io
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import collect_context as C
from context_sources import SourceClient

UTC = timezone.utc
NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)
LUNAR = ('Gregorian Date,Chinese year (Gan-Zhi),Chinese year (Zodiac),Lunar month,Lunar Date\n'
         '16-Feb-26,乙巳年,蛇,十二月,廿九\n17-Feb-26,丙午年,馬,正月,初一\n'
         '20-Oct-26,丙午年,馬,九月,初十\n21-Oct-26,丙午年,馬,九月,十一\n'
         '23-Oct-26,丙午年,馬,九月,十三\n')


def forecast(start='2026-10-20T01:00:00Z', hours=10, resolution=1, updated=None):
    first = datetime.fromisoformat(start)
    series = []
    for index in range(hours):
        at = first + timedelta(hours=index * resolution)
        series.append({'time': at.isoformat(), 'data': {
            'instant': {'details': {'air_temperature': 28, 'cloud_area_fraction': 10}},
            f'next_{resolution}_hours': {'summary': {'symbol_code': 'fair_day'},
                                        'details': {'precipitation_amount': 0.0}}}})
    return {'geometry': {'coordinates': [114.04, 22.56, 17]}, 'properties': {
        'meta': {'updated_at': updated or NOW.isoformat()}, 'timeseries': series}}


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.settings = C.load_settings()

    def fake_fetch(self, url, **_):
        text = LUNAR if 'calendar' in url else json.dumps(forecast())
        return text, {'url': url, 'retrievedAt': NOW.isoformat(), 'checkedAt': NOW.isoformat(),
                      'updatedAt': None, 'expiresAt': (NOW + timedelta(hours=1)).isoformat(),
                      'mode': 'network', 'sha256': 'a' * 64}

    def test_lunar_csv_is_locale_independent_and_leap_months_are_distinct(self):
        rows = C.parse_lunar_csv(LUNAR, 2026)
        self.assertEqual(rows['2026-02-17']['month'], 1)
        self.assertEqual(rows['2026-02-17']['day'], 1)
        leap = C.parse_lunar_csv(LUNAR.replace('正月', '閏正月'), 2026)
        self.assertTrue(leap['2026-02-17']['leapMonth'])
        self.assertEqual(C.parse_lunar_csv(LUNAR.replace('-26', '-01'), 2001)['2001-02-17']['month'], 1)
        with self.assertRaises(ValueError):
            C.parse_lunar_csv(LUNAR + '17-Feb-26,丙午年,馬,正月,初一\n', 2026)
        with self.assertRaises(ValueError):
            C.parse_lunar_csv('<html>blocked</html>', 2026)

    def test_local_solar_terms_match_verified_2026_calendar_dates(self):
        expected = ['01-05', '01-20', '02-04', '02-18', '03-05', '03-20', '04-05', '04-20',
                    '05-05', '05-21', '06-05', '06-21', '07-07', '07-23', '08-07', '08-23',
                    '09-07', '09-23', '10-08', '10-23', '11-07', '11-22', '12-07', '12-22']
        terms = C.solar_terms(2026)
        self.assertEqual([t['date'][5:] for t in terms], expected)
        self.assertTrue(all(t['approximate'] for t in terms))
        self.assertEqual(terms[19]['tag'], 'solar_term.shuangjiang')

    def test_sunrise_and_sunset_are_local_and_polar_status_is_explicit(self):
        sun = C.sun_times(date(2026, 10, 20), 22.56, 114.04, C.get_timezone('Asia/Shanghai'))
        self.assertEqual(sun['sunriseAt'][11:13], '06')
        self.assertTrue('17:5' in sun['sunsetAt'])
        self.assertTrue(sun['approximate'])
        polar = C.sun_times(date(2026, 6, 21), 89, 0, UTC)
        self.assertEqual(polar['status'], 'polar-day')
        self.assertIsNone(polar['sunsetAt'])

    def test_weather_keeps_source_interval_and_never_interpolates_six_hour_data(self):
        start = datetime.fromisoformat('2026-10-20T09:30:00+08:00')
        end = start + timedelta(hours=9)
        weather = C.parse_weather(forecast(), start, end, NOW, 12)
        self.assertEqual(weather['status'], 'available')
        self.assertEqual(weather['coverageSeconds'], 32400)
        self.assertEqual(weather['intervals'][0]['forecastStartAt'][11:16], '09:00')
        self.assertEqual(weather['intervals'][0]['windowStartAt'][11:16], '09:30')
        self.assertEqual(weather['intervals'][0]['tags'], ['weather.clear'])
        coarse = C.parse_weather(forecast(start='2026-10-20T00:00:00Z', hours=3, resolution=6), start, end, NOW, 12)
        self.assertEqual(coarse['resolutionHours'], [6])
        self.assertEqual(len(coarse['intervals']), 2)

    def test_weather_age_missing_update_and_out_of_range_are_not_usable(self):
        start = datetime.fromisoformat('2026-10-20T09:30:00+08:00')
        end = start + timedelta(hours=9)
        stale = C.parse_weather(forecast(updated='2026-10-17T01:00:00Z'), start, end, NOW, 12)
        self.assertEqual(stale['status'], 'stale')
        self.assertFalse(stale['usableForSuggestions'])
        payload = forecast()
        del payload['properties']['meta']['updated_at']
        unknown = C.parse_weather(payload, start, end, NOW, 12)
        self.assertEqual(unknown['status'], 'unknown-update-time')
        far = C.parse_weather(forecast(), start + timedelta(days=30), end + timedelta(days=30), NOW, 12)
        self.assertEqual(far['status'], 'outside-forecast-range')
        self.assertEqual(far['intervals'], [])

    def test_collector_proposes_facts_without_locking_or_enabling_seasons(self):
        snapshot, raw = C.collect('2026-10-20', self.settings, self.fake_fetch, now=NOW)
        self.assertEqual(snapshot['schemaVersion'], 'context-playlist-snapshot/v1')
        self.assertEqual(snapshot['playback']['durationMinutes'], 540)
        tags = {item['tag'] for item in snapshot['contexts']}
        self.assertIn('weather.clear', tags)
        self.assertIn('calendar.tuesday', tags)
        self.assertFalse(any(t.startswith('season.') for t in tags))
        self.assertNotIn('weather.temperature_hot', tags)
        self.assertTrue(all(not item['autoLockAllowed'] for item in snapshot['contexts']))
        self.assertTrue(raw)

    def test_failures_degrade_locally_without_inventing_weather(self):
        def fail(url, **_):
            raise OSError('network unavailable')
        snapshot, _ = C.collect('2026-10-20', self.settings, fail, now=NOW)
        self.assertEqual(snapshot['status'], 'partial')
        self.assertEqual(snapshot['weather']['status'], 'unavailable')
        self.assertTrue(snapshot['astronomy'])
        self.assertFalse(any(x['tag'].startswith('weather.') for x in snapshot['contexts']))
        self.assertIsNone(snapshot['calendar'][0]['lunar'])

    def test_overnight_date_and_offset_are_explicit_and_invalid_settings_fail(self):
        settings = {**self.settings, 'start': '23:30', 'end': '00:30'}
        snapshot, _ = C.collect('2026-10-20', settings, self.fake_fetch, now=NOW)
        self.assertEqual([x['date'] for x in snapshot['calendar']], ['2026-10-20', '2026-10-21'])
        self.assertEqual(snapshot['playback']['durationMinutes'], 60)
        for change in [{'latitude': float('nan')}, {'end': '09:30'}, {'timezone': 'unknown-zone'}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                C.collect('2026-10-20', {**self.settings, **change}, self.fake_fetch, now=NOW)

    def test_holidays_are_facts_but_require_store_opt_in(self):
        snapshot, _ = C.collect('2026-02-17', self.settings, self.fake_fetch, now=NOW)
        found = snapshot['calendar'][0]['holidays']
        self.assertTrue(any(x['tag'] == 'holiday.lunar_new_year' and not x['enabled'] for x in found))
        self.assertFalse(any(x['tag'].startswith('holiday.') for x in snapshot['contexts']))

    def test_output_is_create_only_and_refuses_overwrite_before_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'new'
            with patch.object(SourceClient, 'fetch', side_effect=self.fake_fetch), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(C.main(['--date', '2026-10-20', '--output-dir', str(output)]), 0)
            before = (output / 'context.json').read_bytes()
            with patch.object(SourceClient, 'fetch', side_effect=AssertionError('must not fetch')), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(C.main(['--date', '2026-10-20', '--output-dir', str(output)]), 1)
            self.assertEqual((output / 'context.json').read_bytes(), before)
            self.assertTrue((output / 'context.md').is_file())
            self.assertTrue((output / 'sources.json').is_file())


if __name__ == '__main__':
    unittest.main(verbosity=2)
