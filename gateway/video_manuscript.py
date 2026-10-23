"""Content is a first-class deliverable, not an incidental rendering prompt."""
import json
import re
from gateway.video_contract import _plain_text, NUMBER_PATTERN, source_boundaries, validate_video_plan, narration_density

FIELDS = {'title', 'audience', 'purpose', 'thesis', 'causal_chain', 'evidence_boundary', 'sections'}
SECTION_FIELDS = {'scene_num', 'duration_sec', 'argument', 'narration', 'subtitle', 'source_quotes'}


def source_catalog(source):
    """Stable literal excerpts; the model selects IDs instead of retyping punctuation."""
    parts = re.findall(r'[^。！？\n]+[。！？]?', source)
    return [part[i:i+150] for part in parts for i in range(0,len(part),150) if part[i:i+150].strip()]


def bind_manuscript_evidence(value, source):
    if not isinstance(value,dict) or not isinstance(value.get('sections'),list):
        raise ValueError('缺少内容章节')
    catalog=source_catalog(source)
    out={**value,'sections':[]}
    for raw in value['sections']:
        if not isinstance(raw,dict):
            raise ValueError('内容章节格式无效')
        current=dict(raw)
        if 'source_quote_ids' in current:
            ids=current.pop('source_quote_ids')
            if ('source_quotes' in current or not isinstance(ids,list) or not 1<=len(ids)<=8
                    or any(type(i) is not int or not 1<=i<=len(catalog) for i in ids)):
                raise ValueError('内容稿证据编号无效')
            current['source_quotes']=[catalog[i-1] for i in ids]
        out['sections'].append(current)
    return out


def bind_storyboard_evidence(plan, manuscript):
    if not isinstance(plan,dict) or not isinstance(plan.get('scenes'),list):
        raise ValueError('缺少故事分镜')
    out={**plan,'scenes':[]}
    for raw in plan['scenes']:
        if not isinstance(raw,dict):
            raise ValueError('分镜格式无效')
        current=dict(raw)
        if 'source_section' in current:
            index=current.pop('source_section')
            if ('source_quotes' in current or type(index) is not int or index!=current.get('scene_num')
                    or not 1<=index<=len(manuscript['sections'])):
                raise ValueError('分镜证据章节不一致')
            current['source_quotes']=list(manuscript['sections'][index-1]['source_quotes'])
        out['scenes'].append(current)
    return out


def read_json_text(text):
    if not isinstance(text, str) or len(text.encode()) > 128 * 1024:
        raise ValueError('Claude 文字稿超过大小限制')
    # A provider may wrap JSON, but never extract a convenient object from prose.
    if text.strip().startswith('```json') and text.strip().endswith('```'):
        text = text.strip()[7:-3].strip()
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('JSON 包含重复字段')
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('非法数字')))


def validate_manuscript(value, spec):
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError('内容稿顶层字段不符合契约')
    out = {k: _plain_text(value.get(k), k, n) for k, n in
           [('title', 80), ('audience', 100), ('purpose', 150), ('thesis', 240), ('evidence_boundary', 400)]}
    chain = value['causal_chain']
    if not isinstance(chain, list) or not 2 <= len(chain) <= 10:
        raise ValueError('内容稿必须先建立因果链')
    if any(n not in set(NUMBER_PATTERN.findall(spec['original_prompt_cn'])) for n in NUMBER_PATTERN.findall(' '.join(out.values())+' '.join(chain))):
        raise ValueError('内容逻辑包含原文没有的数字')
    out['causal_chain'] = [_plain_text(s, 'causal_chain', 180) for s in chain]
    sections = value['sections']
    if not isinstance(sections, list) or not 2 <= len(sections) <= min(30 if spec['video_duration_sec']>60 else 10, spec['video_duration_sec']//3):
        raise ValueError('内容稿章节数量不合法')
    source = spec['original_prompt_cn']
    numbers = set(NUMBER_PATTERN.findall(source))
    out['sections'] = []
    for i, s in enumerate(sections, 1):
        if not isinstance(s, dict) or set(s) != SECTION_FIELDS or type(s['scene_num']) is not int or s['scene_num'] != i:
            raise ValueError('内容稿章节字段或编号不合法')
        d = s['duration_sec']
        if type(d) is not int or d < 3:
            raise ValueError('内容稿章节时长不合法')
        current = {'scene_num': i, 'duration_sec': d,
                   'argument': _plain_text(s['argument'], 'argument', 350),
                   'narration': _plain_text(s['narration'], f'section[{i}].narration (max {d*narration_density(spec)[1]} characters; got {len(str(s["narration"]))})', d*narration_density(spec)[1]),
                   'subtitle': _plain_text(s['subtitle'], 'subtitle', d*4)}
        quotes = s['source_quotes']
        if (not isinstance(quotes, list) or not quotes or len(quotes) > 8
                or any(not isinstance(q, str) or not q.strip() or len(q)>160 or q not in source for q in quotes)):
            raise ValueError('内容稿缺少真实的原文引用')
        current['source_quotes'] = quotes
        if any(n not in numbers for n in NUMBER_PATTERN.findall(' '.join(current[k] for k in ['argument','narration','subtitle']))):
            raise ValueError('内容稿包含原文没有的数字')
        # Different display orthography is useful, but it cannot silently change the spoken claim.
        if current['subtitle'] != current['narration']:
            raise ValueError('本版字幕必须与口播逐字一致；两份稿件分别保存')
        out['sections'].append(current)
    if sum(s['duration_sec'] for s in out['sections']) != spec['video_duration_sec']:
        raise ValueError('内容稿总时长不闭合')
    if len({s['narration'] for s in out['sections']}) != len(sections):
        raise ValueError('内容稿重复口播')
    if spec['video_duration_sec']>60 and sum(len(s['narration']) for s in out['sections'])>int(spec['video_duration_sec']*3.5):
        raise ValueError(f'Long film spoken script exceeds natural pacing budget: maximum {int(spec["video_duration_sec"]*3.5)} total characters including punctuation; shorten the script without removing factual limits')
    presented = ' '.join(s['narration'] for s in out['sections'])
    if any(b not in presented for b in source_boundaries(source)):
        raise ValueError('口播遗漏原文的限制或承诺边界')
    return out


def validate_handoff(manuscript, plan, spec):
    content = validate_manuscript(manuscript, spec)
    scenes = validate_video_plan(plan, spec)
    if len(scenes) != len(content['sections']):
        raise ValueError('分镜丢失了已审核的内容章节')
    for section, scene in zip(content['sections'], scenes):
        for key in ['scene_num','duration_sec','narration','source_quotes']:
            if section[key] != scene[key]:
                raise ValueError('分镜擅自更改已审核的口播或证据')
    return scenes


def manuscript_markdown(m):
    lines = [f"# {m['title']}", '', f"受众：{m['audience']}", f"目的：{m['purpose']}", '',
             f"核心论点：{m['thesis']}", '', '## 内容逻辑', *[f'- {x}' for x in m['causal_chain']], '',
             '## 事实与推论边界', m['evidence_boundary'], '']
    for s in m['sections']:
        lines += [f"## 第{s['scene_num']}段 · {s['duration_sec']}秒", s['argument'], '',
                  '口播：'+s['narration'], '', *['原文依据：'+q for q in s['source_quotes']], '']
    return '\n'.join(lines)
