"""Bounded public Mixkit discovery, with per-item commercial license verification.

No private search tokens, account cookies, bulk library crawling or preview bypass.
Only public search pages and up to eight selected item detail pages are read.
"""
from __future__ import annotations
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit, quote

import httpx
from worker.scene_commons import USER_AGENT, plain

LICENSE = 'https://mixkit.co/license/#videoFree'
ITEM = r'https://mixkit\.co/free-stock-video/([a-z0-9-]+)-(\d+)/'


class Page(HTMLParser):
    def __init__(self):
        super().__init__(); self.active = False; self.scripts = []; self.buffer = []
        self.in_copy = False; self.copy = []; self.free_license = False
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('type') == 'application/ld+json':
            self.active = True; self.buffer = []
        if tag == 'p' and 'download-video-options__download-copy' in attrs.get('class', '').split():
            self.in_copy = True
        if self.in_copy and tag == 'a' and attrs.get('data-license') == 'videoFree' and attrs.get('href') == '/license/#videoFree':
            self.free_license = True
    def handle_endtag(self, tag):
        if tag == 'script' and self.active:
            self.scripts.append(''.join(self.buffer)); self.active = False
        if tag == 'p': self.in_copy = False
    def handle_data(self, value):
        if self.active: self.buffer.append(value)
        if self.in_copy: self.copy.append(value)
    def videos(self):
        result = []
        for text in self.scripts:
            try:
                data = json.loads(text)
                nodes = data.get('@graph', [data]) if isinstance(data, dict) else []
                result.extend(n for n in nodes if isinstance(n, dict) and n.get('@type') == 'VideoObject')
            except (ValueError, TypeError):
                continue
        return result
    def commercial(self):
        return self.free_license and 'for commercial or personal use' in re.sub(r'\s+', ' ', ' '.join(self.copy))
    def item_topics(self, video):
        refs = {v.get('@id') for v in video.get('about', []) + video.get('mentions', []) if isinstance(v, dict)}
        names = []
        for text in self.scripts:
            try:
                data = json.loads(text)
                for node in data.get('@graph', []) if isinstance(data, dict) else []:
                    if isinstance(node, dict) and node.get('@id') in refs and node.get('@type') == 'Thing' and isinstance(node.get('name'), str):
                        names.append(plain(node['name'], 100))
            except (ValueError, TypeError):
                continue
        return list(dict.fromkeys(names))[:12]


def public_url(url):
    p = urlsplit(url)
    if (p.scheme != 'https' or p.netloc != 'mixkit.co' or p.query or p.fragment
            or not p.path.startswith('/free-stock-video/') or '..' in p.path):
        raise ValueError('Mixkit 公开页面地址无效')
    return url


async def read_page(client, url):
    for _ in range(4):
        public_url(url)
        async with client.stream('GET', url, headers={'User-Agent': USER_AGENT}) as response:
            if response.status_code in {301,302,303,307,308}:
                url = urljoin(url, response.headers.get('location','')); continue
            if response.status_code == 404: return None
            if response.status_code != 200:
                raise RuntimeError(f'Mixkit 公开页面返回 HTTP {response.status_code}，未自动重试')
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > 3*1024*1024: raise ValueError('Mixkit 页面超过大小预算')
            page = Page();page.feed(raw.decode('utf-8'));return page
    raise ValueError('Mixkit 页面重定向过多')


def candidate(item, detail, query):
    try:
        source = item['@id'].removesuffix('#video')
        match = re.fullmatch(ITEM, source)
        if not match or not detail.commercial(): return None
        exact = [v for v in detail.videos() if v.get('@id') == item['@id']]
        if len(exact) != 1: return None
        verified = exact[0]
        if any(v.get('copyrightNotice') != 'Free' or v.get('license') != LICENSE
               or v.get('encodingFormat') != 'video/mp4' for v in [item, verified]): return None
        duration = re.fullmatch(r'PT(?:(\d+)M)?(?:(\d+)S)?', verified.get('duration',''))
        if not duration: return None
        seconds = int(duration[1] or 0)*60+int(duration[2] or 0)
        if not 5 <= seconds <= 90: return None
        # The listing can advertise a large 4K original. The item page declares its
        # free HD content rendition separately from embedUrl (the preview).
        # Prefer that rendition; actual dimensions/codec are checked after download.
        for media_url in [item['contentUrl'], verified['contentUrl']]:
            parsed = urlsplit(media_url)
            if parsed.scheme != 'https' or parsed.netloc != 'assets.mixkit.co' or parsed.query or parsed.fragment: return None
        media = verified['contentUrl']
        name = plain(verified['name'],400); description = plain(verified.get('description',name),1800)
        topics = detail.item_topics(verified)
        if topics: description = (description + ' Source tags: ' + ', '.join(topics))[:1800]
        return {'id': match[2], 'provider':'mixkit', 'source_url':source,
            'source_title':name,'source_description':description,
            'author':'Mixkit（来源站未列出单独作者）','license_name':'Mixkit Stock Video Free License',
            'license_url':LICENSE,'provider_description':name+'. '+description,
            'query':query['query'],'source_quote':query['source_quote'],'action':query['action'],
            'download_url':media,'suffix':'.mp4','duration_sec':seconds}
    except (KeyError,TypeError,ValueError): return None


async def search(queries, client):
    batches = []
    for query in queries:
        if not re.fullmatch(r"[A-Za-z0-9 ,'-]+",query['query']): continue
        slug = '-'.join(re.findall(r'[a-z0-9]+',query['query'].lower()))
        page = await read_page(client,'https://mixkit.co/free-stock-video/discover/'+quote(slug,safe='')+'/')
        batches.append([(v,query) for v in page.videos()
                        if v.get('copyrightNotice') == 'Free' and re.fullmatch(ITEM,v.get('@id','').removesuffix('#video'))] if page else [])
    # Metadata recall precedes semantic ranking. Do not spend the eight detail
    # checks on the first items (especially unrelated geography-tag results).
    rows, seen = [], set()
    for position in range(max(map(len,batches),default=0)):
        for batch in batches:
            if position >= len(batch): continue
            item, query = batch[position];url = item['@id'].removesuffix('#video')
            if url in seen: continue
            seen.add(url)
            match=re.fullmatch(ITEM,url)
            rows.append({'id':match[2],'provider':'mixkit','source_url':url,
                'source_title':plain(item.get('name',''),400),
                'source_description':plain(item.get('description',item.get('name','')),1800),
                'query':query['query'],'source_quote':query['source_quote'],'action':query['action'],
                'license_pending':True,'listing':item})
            if len(rows)>=32:return rows
    return rows


async def verify_selected(rows, client):
    if not 1<=len(rows)<=8:raise ValueError('Mixkit 详情审核数量超出范围')
    verified=[]
    for row in rows:
        page=await read_page(client,row['source_url'])
        result=candidate(row['listing'],page,row) if page else None
        if result:verified.append(result)
    return verified
