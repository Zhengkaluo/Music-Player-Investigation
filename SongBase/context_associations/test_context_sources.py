import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import context_sources as S

UTC = timezone.utc
NOW = datetime(2026, 10, 20, 8, tzinfo=UTC)
URL = 'https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=22.5600&lon=114.0400'


class Response(io.BytesIO):
    def __init__(self, text='{"fixture":true}', headers=None, code=200):
        super().__init__(text.encode('utf-8'))
        self.headers = headers or {'Expires': 'Tue, 20 Oct 2026 09:00:00 GMT',
                                   'Last-Modified': 'Tue, 20 Oct 2026 07:45:00 GMT'}
        self.code = code


class SourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.now = NOW
        self.client = S.SourceClient(self.root, 'Fixture/1.0 (https://example.org)', now=lambda: self.now)

    def test_fresh_cache_avoids_duplicate_network_requests(self):
        with patch.object(S, 'urlopen', return_value=Response()) as read:
            text, first = self.client.fetch(URL)
            second_text, second = self.client.fetch(URL)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(second_text, text)
        self.assertEqual(second['mode'], 'cache')
        self.assertEqual(second['retrievedAt'], first['retrievedAt'])
        self.assertFalse(second['cacheExpired'])
        self.assertEqual(first['updatedAt'], '2026-10-20T07:45:00+00:00')

    def test_expired_cache_is_revalidated_and_304_keeps_original_retrieval(self):
        with patch.object(S, 'urlopen', return_value=Response()):
            _, original = self.client.fetch(URL)
        self.now += timedelta(hours=2)
        response = HTTPError(URL, 304, 'Not modified', {'Expires': 'Tue, 20 Oct 2026 11:00:00 GMT'}, None)
        with patch.object(S, 'urlopen', side_effect=response) as read:
            text, meta = self.client.fetch(URL)
        request = read.call_args.args[0]
        self.assertEqual(request.get_header('If-modified-since'), 'Tue, 20 Oct 2026 07:45:00 GMT')
        self.assertEqual(meta['mode'], 'cache-revalidated')
        self.assertEqual(meta['retrievedAt'], original['retrievedAt'])
        self.assertEqual(json.loads(text), {'fixture': True})
        self.assertEqual(meta['checkedAt'], self.now.isoformat())

    def test_offline_expired_data_is_explicit_and_missing_cache_fails(self):
        with patch.object(S, 'urlopen', return_value=Response()):
            self.client.fetch(URL)
        self.now += timedelta(hours=2)
        self.client.offline = True
        with patch.object(S, 'urlopen', side_effect=AssertionError('offline cannot fetch')):
            _, meta = self.client.fetch(URL)
            self.assertTrue(meta['cacheExpired'])
            self.assertEqual(meta['mode'], 'offline-expired-cache')
            with self.assertRaises(OSError):
                self.client.fetch('https://example.org/missing')

    def test_modified_cache_is_rejected_instead_of_trusted(self):
        with patch.object(S, 'urlopen', return_value=Response()):
            self.client.fetch(URL)
        path = next(self.root.glob('*.json'))
        data = json.loads(path.read_text(encoding='utf-8'))
        data['text'] = '{"tampered":true}'
        path.write_text(json.dumps(data), encoding='utf-8')
        self.client.offline = True
        with self.assertRaises(OSError):
            self.client.fetch(URL)

    def test_http_and_generic_empty_identity_are_rejected(self):
        with self.assertRaises(ValueError):
            self.client.fetch('http://example.org/data')
        with self.assertRaises(ValueError):
            S.SourceClient(self.root, '')
        with self.assertRaises(ValueError):
            S.SourceClient(self.root, 'app\r\nmalicious-header')


if __name__ == '__main__':
    unittest.main(verbosity=2)
