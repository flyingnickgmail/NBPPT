"""Provider provenance rules shared by catalog loading and independent delivery QA."""
from __future__ import annotations
import re
import html


def validate_source(clip: dict) -> None:
    url, license_url = clip.get('source_url', ''), clip.get('license_url', '')
    provider = clip.get('provider', 'pexels')
    if provider == 'pexels':
        if not re.fullmatch(r'https://www\.pexels\.com/video/[a-zA-Z0-9-]+/', url) or license_url != 'https://www.pexels.com/license/':
            raise ValueError('Pexels 素材来源或许可无效')
    elif provider == 'commons':
        match = re.fullmatch(r'https://commons\.wikimedia\.org/w/index\.php\?curid=([0-9]+)', url)
        if not match or not clip.get('id', '').startswith('commons-' + match[1] + '-'):
            raise ValueError('Commons 素材编号与来源不一致')
        if not re.fullmatch(r'https://creativecommons\.org/(?:licenses/by/(?:2\.0|2\.5|3\.0|4\.0)|publicdomain/(?:zero/1\.0|mark/1\.0))/', license_url):
            raise ValueError('素材许可不在已支持范围：仅 CC BY、CC0 或公有领域')
        for field, limit in [('source_title', 400), ('source_description', 1800), ('license_name', 100)]:
            value = clip.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise ValueError('Commons 素材缺少许可或原始描述')
        expected = ('CC BY ' + license_url.rstrip('/').split('/')[-1] if '/licenses/by/' in license_url
                    else ('CC0' if '/zero/' in license_url else 'Public domain'))
        if clip['license_name'] != expected:
            raise ValueError('素材许可名称与地址不一致')
    elif provider == 'mixkit':
        match = re.fullmatch(r'https://mixkit\.co/free-stock-video/[a-z0-9-]+-([0-9]+)/', url)
        if (not match or not clip.get('id','').startswith('mixkit-'+match[1]+'-')
                or license_url != 'https://mixkit.co/license/#videoFree'
                or clip.get('license_name') != 'Mixkit Stock Video Free License'
                or not isinstance(clip.get('source_title'),str) or not 1 <= len(clip['source_title']) <= 400
                or not isinstance(clip.get('source_description'),str) or not 1 <= len(clip['source_description']) <= 1800):
            raise ValueError('Mixkit 素材来源或商业许可无效')
    else:
        raise ValueError('未知实景素材来源')


def description(clip: dict) -> str:
    if clip.get('provider', 'pexels') in {'commons','mixkit'}:
        return clip['source_title'] + '. ' + clip['source_description']
    return clip['source_url'].rstrip('/').split('/')[-1].replace('-', ' ')


def casting_pattern(preference: str) -> str:
    china = r'\b(chinese|china)\b|中国|中國'
    asia = r'\b(asian|chinese|china|japanese|japan|korean|korea|taiwan|singapore|india|indian|vietnam|thailand)\b|亚洲|亞洲|中国|中國|日本|韩国|韓國|台湾|臺灣|台灣|新加坡|印度|越南|泰国'
    return china if preference == 'china' else asia


def casting_required(source: str) -> bool:
    # "优先" is a preference, not permission to claim uncertain ethnicity as fact.
    return not bool(re.search(r'(?:优先|偏好)[^。\n]{0,25}(?:中国|亚洲|Chinese|Asian)', source, re.I))


def credits_html(clips: list[dict]) -> str:
    unique = {c['source_url']:c for c in clips}
    rows = []
    for c in unique.values():
        validate_source(c)
        title = c.get('source_title', '实景素材')
        rows.append('<li><a href="'+html.escape(c['source_url'],quote=True)+'">'+html.escape(title)+'</a><br>作者：'
                    +html.escape(c['author'])+' · <a href="'+html.escape(c['license_url'],quote=True)+'">'
                    +html.escape(c.get('license_name','Pexels License'))+'</a></li>')
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            '<title>视频素材署名与许可</title><style>body{max-width:800px;margin:40px auto;padding:20px;font:17px system-ui;line-height:1.8}li{margin:24px 0}</style>'
            '<h1>视频素材署名与许可</h1><p>以下片段用于情境演绎。已进行截取、裁切、调色、重新剪辑、静音及添加字幕和配音；'
            '原作者、人物和机构不代表本产品用户、背书或业务结果。许可适用于各自原始素材。</p><ul>'
            +''.join(rows)+'</ul></html>')
