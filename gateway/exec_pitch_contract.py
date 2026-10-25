"""Bounded, data-only long films. Frames are the only editing clock (24 Hz).

Each shot is one approved narration beat with a measured 48 kHz PCM take.
This is beat alignment, not word alignment or human content approval.
"""
import hashlib
import json
import re

from gateway.video_contract import _plain_text, NUMBER_PATTERN, source_boundaries

CONTRACT = 'exec-pitch-v1'
FPS = 24
SAMPLE_RATE = 48000
SAMPLES_PER_FRAME = SAMPLE_RATE // FPS
MAX_SECONDS = 600
MAX_SHOTS = 240
MAX_SECTIONS = 30


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def hash_id(value):
    return isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) is not None


def validate_input(value, spec):
    fields = {'title', 'audience', 'purpose', 'thesis', 'causal_chain', 'evidence_boundary',
              'source_sha256', 'media_kind', 'sections', 'shots'}
    if not isinstance(value, dict) or set(value)-{'product_visuals','voice_mix','bilingual','quality','governance','revision','story'} != fields:
        raise ValueError('长片输入字段不符合严格契约')
    if 'product_visuals' in value:
        from gateway.product_visuals import validate_scope
        validate_scope(value['product_visuals'])
    if value['source_sha256'] != digest(spec['original_prompt_cn'].encode()):
        raise ValueError('长片原文与登记稿不一致')
    if value['media_kind'] not in ('approved_local', 'synthetic_fixture'):
        raise ValueError('必须标明本地审批素材或合成测试素材')
    for key, maximum in [('title',80),('audience',100),('purpose',150),('thesis',240),('evidence_boundary',400)]:
        if _plain_text(value[key], key, maximum) != value[key]:
            raise ValueError('长片文字必须预先规范化')
    chain = value['causal_chain']
    if not isinstance(chain, list) or not 2 <= len(chain) <= 10:
        raise ValueError('长片必须先建立因果链')
    for link in chain:
        _plain_text(link, 'causal_chain', 180)
    sections, shots = value['sections'], value['shots']
    if not isinstance(sections, list) or not 2 <= len(sections) <= MAX_SECTIONS:
        raise ValueError('长片口播段落必须为2至30段，与镜头数分开')
    minimum = 40 if spec['video_duration_sec'] >= 480 else 2
    if not isinstance(shots, list) or not minimum <= len(shots) <= MAX_SHOTS:
        raise ValueError('长片镜头数量不合法；八分钟至少40镜，最多240镜')
    numbers = set(NUMBER_PATTERN.findall(spec['original_prompt_cn']))
    def text(text_value, name, maximum):
        clean = _plain_text(text_value, name, maximum)
        if clean != text_value or any(n not in numbers for n in NUMBER_PATTERN.findall(clean)):
            raise ValueError('长片包含未规范化文字或原文没有的数字')
        return clean
    for key in ('title','audience','purpose','thesis','evidence_boundary'):
        text(value[key], key, 400)
    for link in chain:
        text(link,'causal_chain',180)
    def quotes(items):
        if (not isinstance(items,list) or not 1 <= len(items) <= 8 or
                any(not isinstance(q,str) or not q.strip() or len(q)>160 or q not in spec['original_prompt_cn'] for q in items)):
            raise ValueError('长片缺少逐镜原文证据')
    for i, section in enumerate(sections,1):
        if (not isinstance(section,dict) or set(section) != {'section_num','argument','narration','source_quotes'}
                or type(section['section_num']) is not int or section['section_num'] != i):
            raise ValueError('口播段落编号或字段无效')
        text(section['argument'],'argument',350)
        text(section['narration'],'narration',500)
        quotes(section['source_quotes'])
    timeline=[]; cursor=0; previous=1
    for i, shot in enumerate(shots,1):
        if not isinstance(shot,dict) or set(shot)-{'motion','product_asset_id'} != {'shot_num','section_num','narration','source_quotes','reason',
                'audio_sha256','visual_sha256','audio_samples','lead_frames','tail_frames'}:
            raise ValueError('长片镜头字段无效；不得提供路径、秒数或可执行代码')
        if 'motion' in shot:
            from gateway.motion_contract import validate_motion
            validate_motion(shot['motion'],spec['original_prompt_cn'])
        if 'product_asset_id' in shot:
            from gateway.product_visuals import identifier
            if (not identifier(shot['product_asset_id']) or 'product_visuals' not in value
                    or shot.get('motion',{}).get('layout') not in ('crm_frame','broll_plate','closing')):
                raise ValueError('产品素材编号需要已登记客户范围及对应镜头版式')
        elif (shot.get('motion',{}).get('layout')=='crm_frame'
                or 'product_visuals' in value and shot.get('motion',{}).get('layout','broll_plate')=='broll_plate'):
            raise ValueError('产品画面或受品牌限制的实景缺少已审素材；不生成假界面或占位交付')
        section=shot['section_num']
        if (type(shot['shot_num']) is not int or shot['shot_num']!=i or type(section) is not int
                or not previous <= section <= previous+1 or not 1 <= section <= len(sections)):
            raise ValueError('镜头与口播段落必须连续且单调')
        previous=section
        text(shot['narration'],'shot narration',80)
        text(shot['reason'],'reason',180)
        quotes(shot['source_quotes'])
        if shot['source_quotes'] != sections[section-1]['source_quotes']:
            raise ValueError('镜头证据与所属口播段落不一致')
        if not hash_id(shot['audio_sha256']) or not hash_id(shot['visual_sha256']):
            raise ValueError('音频和画面必须是已登记的摘要编号')
        samples=shot['audio_samples']
        if type(samples) is not int or not 1 <= samples <= 20*SAMPLE_RATE:
            raise ValueError('实测音频样本数无效')
        lead,tail=shot['lead_frames'],shot['tail_frames']
        if any(type(n) is not int or not 6 <= n <= 12 for n in (lead,tail)):
            raise ValueError('声音前后留量必须为6至12帧')
        frames=(samples+SAMPLES_PER_FRAME-1)//SAMPLES_PER_FRAME+lead+tail
        if not 2*FPS <= frames <= 20*FPS:
            raise ValueError('单镜必须为2至20秒；自然口播不加速或截断')
        # Character density estimates a script before synthesis; it cannot
        # validate an already measured take (voice, punctuation and rate vary).
        # Admission uses this sample clock; load_input remeasures the PCM and
        # delivery independently checks the encoded beat placement and mix.
        timeline.append({'shot_num':i,'section_num':section,'start_frame':cursor,'end_frame':cursor+frames,
                         'speech_start_sample':(cursor+lead)*SAMPLES_PER_FRAME,'audio_samples':samples,
                         'audio_sha256':shot['audio_sha256'],'visual_sha256':shot['visual_sha256']})
        cursor+=frames
    if cursor != spec['video_duration_sec']*FPS:
        raise ValueError('实测口播与声音留量不符合请求总时长；未填充、拉伸、加速或截断')
    for i, section in enumerate(sections,1):
        if ''.join(s['narration'] for s in shots if s['section_num']==i) != section['narration']:
            raise ValueError('口播与镜头不一致或段落丢失')
    if len({s['narration'] for s in shots}) != len(shots):
        raise ValueError('长片包含重复口播')
    spoken=''.join(s['narration'] for s in shots)
    if any(b not in spoken for b in source_boundaries(spec['original_prompt_cn'])):
        raise ValueError('口播遗漏原文限制或承诺边界')
    result={'time_base':'1/24','fps':FPS,'sample_rate':SAMPLE_RATE,'total_frames':cursor,
            'alignment':'measured_narration_beats_not_words','shots':timeline}
    from gateway.exec_pitch_voice import validate_bilingual
    validate_bilingual(value,spec,result)
    from gateway.word_alignment import validate_quality
    validate_quality(value,spec)
    from gateway.exec_pitch_review import validate_governance
    validate_governance(value,spec)
    from gateway.exec_pitch_revision import validate_revision
    validate_revision(value)
    from gateway.exec_pitch_story import validate_story
    validate_story(value,spec)
    return result
