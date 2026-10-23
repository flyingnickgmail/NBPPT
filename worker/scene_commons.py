"""Keyless official Wikimedia API: bounded video search and explicit licenses."""
from __future__ import annotations
from html.parser import HTMLParser
import json
import math
import re
import unicodedata
from urllib.parse import urlsplit

import httpx

API = 'https://commons.wikimedia.org/w/api.php'
USER_AGENT = 'NBPPT/0.1 (https://github.com/flyingnickgmail/NBPPT; source-grounded video editor)'


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
    def handle_data(self, data):
        self.parts.append(data)


def plain(value: str, limit: int) -> str:
    parser = PlainText()
    parser.feed(value)
    value = re.sub(r'\s+', ' ', ' '.join(parser.parts))
    return ''.join(c for c in value if not unicodedata.category(c).startswith('C')).strip()[:limit]


def candidate(page: dict, query: dict) -> dict | None:
    try:
        ident = page['pageid']
        if type(ident) is not int or ident <= 0 or page.get('ns') != 6:
            return None
        info = page['videoinfo'][0]
        meta = info['extmetadata']
        if info.get('badfile') or any(flag in info for flag in ('filehidden', 'suppressed')):
            return None
        categories = meta.get('Categories', {}).get('value', '')
        if re.search(r'copyright violations|deletion requests|disputed|missing permission|no permission|no license|no source', categories, re.I):
            return None
        if meta.get('Restrictions', {}).get('value', '').strip():
            return None
        license_name = plain(meta['LicenseShortName']['value'], 100)
        license_url = meta.get('LicenseUrl', {}).get('value', '').replace('http://', 'https://').rstrip('/') + '/'
        if license_name == 'Public domain' and license_url == '/':
            license_url = 'https://creativecommons.org/publicdomain/mark/1.0/'
        if license_name == 'CC0' and license_url == '/':
            license_url = 'https://creativecommons.org/publicdomain/zero/1.0/'
        title = plain(page['title'].removeprefix('File:'), 400)
        description = plain(meta.get('ImageDescription', {}).get('value', ''), 1800)
        author = plain(meta.get('Artist', {}).get('value', ''), 160)
        if not description or not author:
            return None
        duration = info['duration']
        if type(duration) not in (int, float) or not math.isfinite(duration) or not 5 <= duration <= 600:
            return None
        # Explicit reusable-license gate, including URL/name agreement.
        row = {'id': str(ident), 'provider': 'commons', 'source_url': f'https://commons.wikimedia.org/w/index.php?curid={ident}',
               'source_title': title, 'source_description': description, 'author': author,
               'license_name': license_name, 'license_url': license_url,
               'query': query['query'], 'source_quote': query['source_quote'], 'action': query['action']}
        from gateway.footage_contract import validate_source
        validate_source({**row, 'id': f'commons-{ident}-0'})
        variants = []
        for variant in info.get('derivatives', []):
            url = variant.get('src', '')
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or parsed.hostname != 'upload.wikimedia.org' or not parsed.path.startswith('/wikipedia/commons/'):
                continue
            width, height = variant.get('width', 0), variant.get('height', 0)
            if min(width, height) < 720 or max(width, height) > 3840:
                continue
            if not variant.get('type', '').startswith(('video/webm', 'video/ogg', 'video/mp4')):
                continue
            estimated = variant.get('bandwidth', 0) * duration / 8
            if estimated > 150 * 1024 * 1024:
                continue
            variants.append((abs(max(width, height)-1920), estimated, variant))
        if not variants:
            return None
        chosen = min(variants, key=lambda item: item[:2])[2]
        suffix = '.webm' if chosen['type'].startswith('video/webm') else ('.ogv' if chosen['type'].startswith('video/ogg') else '.mp4')
        row.update(download_url=chosen['src'], suffix=suffix, duration_sec=duration,
                   provider_description=title+'. '+description)
        return row
    except (KeyError, IndexError, TypeError, ValueError):
        return None


async def search(queries: list[dict], client: httpx.AsyncClient) -> list[dict]:
    found, seen = [], set()
    for query in queries:
        # Literal terms only; the model cannot inject search operators/URLs.
        params = {'action':'query', 'format':'json', 'generator':'search', 'gsrnamespace':6,
                  'gsrsearch':'filetype:video '+query['query'], 'gsrlimit':20, 'gsrsort':'relevance',
                  'prop':'videoinfo', 'viprop':'url|size|mime|extmetadata|derivatives|badfile',
                  'viextmetadatafilter':'Artist|ImageDescription|LicenseShortName|LicenseUrl|Restrictions|Categories',
                  'maxlag':5}
        try:
            async with client.stream('GET', API, params=params, headers={'User-Agent': USER_AGENT}) as response:
                if response.status_code != 200:
                    raise RuntimeError(f'公开素材搜索返回 HTTP {response.status_code}，未自动重试')
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 3 * 1024 * 1024:
                        raise ValueError('公开素材搜索响应过大')
            data = json.loads(raw)
            if 'error' in data:
                raise RuntimeError('公开素材搜索服务暂不可用，未自动重试')
            pages = data.get('query', {}).get('pages', {})
            if not isinstance(pages, dict) or len(pages) > 20:
                raise ValueError('公开素材响应格式无效')
            for page in sorted(pages.values(), key=lambda p:p.get('index', 0)):
                row = candidate(page, query)
                if row and row['id'] not in seen:
                    seen.add(row['id'])
                    found.append(row)
        except httpx.HTTPError:
            raise RuntimeError('公开素材搜索网络失败，未自动重试') from None
    return found[:32]
