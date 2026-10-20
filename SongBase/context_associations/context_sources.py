"""Small HTTPS client with provenance and conditional caching; standard library only."""
import gzip
import hashlib
import json
import os
import tempfile
import zlib
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

UTC = timezone.utc
MAX_BYTES = 4 * 1024 * 1024


def http_time(value):
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(UTC).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


class SourceClient:
    def __init__(self, cache_dir, user_agent, *, offline=False, timeout=20, now=None):
        if not isinstance(user_agent, str) or not user_agent.strip() or '\r' in user_agent or '\n' in user_agent:
            raise ValueError('数据服务需要非空、可识别的 User-Agent。')
        self.cache_dir = Path(cache_dir)
        self.user_agent = user_agent
        self.offline = offline
        self.timeout = timeout
        self.now = now or (lambda: datetime.now(UTC))

    def fetch(self, url, *, max_age_seconds=1800):
        if urlsplit(url).scheme != 'https':
            raise ValueError('数据源必须使用 HTTPS。')
        now = self.now()
        key = hashlib.sha256(url.encode('utf-8')).hexdigest()
        path = self.cache_dir / (key + '.json')
        cached = None
        if path.is_file() and not path.is_symlink():
            try:
                candidate = json.loads(path.read_text(encoding='utf-8'))
                if candidate['url'] == url and hashlib.sha256(candidate['text'].encode('utf-8')).hexdigest() == candidate['sha256']:
                    cached = candidate
            except (OSError, ValueError, KeyError, TypeError):
                pass
        if cached:
            try:
                valid = datetime.fromisoformat(cached['expiresAt']) > now
            except (KeyError, ValueError, TypeError):
                valid = False
            if valid or self.offline:
                metadata = {k: v for k, v in cached.items() if k != 'text'}
                metadata.update(mode='cache' if valid else 'offline-expired-cache', checkedAt=now.isoformat(), cacheExpired=not valid)
                return cached['text'], metadata
        if self.offline:
            raise OSError('离线模式没有这个固定数据源的缓存。')
        headers = {'User-Agent': self.user_agent, 'Accept-Encoding': 'gzip, deflate'}
        if cached:
            if cached.get('lastModified'):
                headers['If-Modified-Since'] = cached['lastModified']
            if cached.get('etag'):
                headers['If-None-Match'] = cached['etag']
        try:
            response = urlopen(Request(url, headers=headers), timeout=self.timeout)
        except HTTPError as error:
            if error.code != 304 or not cached:
                raise
            response = error
        with response:
            response_headers = response.headers
            expiry = http_time(response_headers.get('Expires')) or (now + timedelta(seconds=max_age_seconds)).isoformat()
            if response.code == 304:
                text = cached['text']
                retrieved = cached['retrievedAt']
                mode = 'cache-revalidated'
            else:
                raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise ValueError('数据源响应超过 4 MB 上限。')
                compression = response_headers.get('Content-Encoding', '').lower()
                if compression == 'gzip':
                    raw = gzip.decompress(raw)
                elif compression == 'deflate':
                    raw = zlib.decompress(raw)
                elif compression not in ('', 'identity'):
                    raise ValueError('不支持数据源的压缩格式。')
                if len(raw) > MAX_BYTES:
                    raise ValueError('解压后的数据源超过 4 MB 上限。')
                text = raw.decode('utf-8-sig')
                retrieved = now.isoformat()
                mode = 'network'
            last_modified = response_headers.get('Last-Modified') or (cached or {}).get('lastModified')
            metadata = {'url': url, 'retrievedAt': retrieved, 'checkedAt': now.isoformat(),
                        'updatedAt': http_time(last_modified), 'expiresAt': expiry,
                        'lastModified': last_modified, 'etag': response_headers.get('ETag') or (cached or {}).get('etag'),
                        'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(), 'mode': mode,
                        'cacheExpired': datetime.fromisoformat(expiry) <= now}
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if self.cache_dir.is_symlink() or path.is_symlink():
            raise ValueError('拒绝写入符号链接缓存。')
        descriptor, temporary = tempfile.mkstemp(prefix='.context-', dir=self.cache_dir)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as output:
                json.dump({**metadata, 'text': text}, output, ensure_ascii=False)
                output.write('\n')
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return text, metadata
