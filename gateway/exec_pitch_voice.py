"""P3 opt-in mix and administrator-registered bilingual caption evidence.

No translation, signature fabrication or provider call is performed here.
The registry is writable only by the trusted registering operator, like P0/P2.
"""
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from gateway.exec_pitch_contract import canonical, digest, hash_id
from gateway.video_manuscript import read_json_text


def mix_profile(value):
    mix=value.get('voice_mix')
    if mix is None:return 'legacy'
    if (not isinstance(mix,dict) or set(mix)!={'profile','music','input_audio'}
            or mix['profile']!='exec_pitch_p3' or mix['music'] not in ('none','original_ducked')
            or mix['input_audio']!='dry_dialogue'):
        raise ValueError('P3混音须明确原始干声及有界背景音乐方式；不叠加已混合音轨')
    return 'exec_pitch_p3'


def caption_vtt(value,timeline,alignment=None):
    import html
    from worker.video_speech import _stamp
    if 'quality' in value:
        if alignment is None:raise ValueError('P4字幕缺少已登记实测逐字对齐')
        from gateway.word_alignment import aligned_vtt
        return aligned_vtt(value,timeline,alignment)
    bilingual=value.get('bilingual');lines=['WEBVTT','']
    if bilingual:
        for cue in bilingual['cues']:
            lines.extend([f"{_stamp(cue['start_frame']/24)} --> {_stamp(cue['end_frame']/24)}",
                          html.escape(cue['zh']),html.escape(cue['ko']),''])
    else:
        for shot,cut in zip(value['shots'],timeline['shots']):
            lines.extend([f"{_stamp(cut['start_frame']/24)} --> {_stamp(cut['end_frame']/24)}",
                          html.escape(shot['narration']),''])
    return '\n'.join(lines)


def narration_text(value):
    mapping=value.get('bilingual')
    if mapping and mapping['narration_language']=='ko-KR':
        groups={s['section_num']:[] for s in value['sections']}
        section_for_shot={s['shot_num']:s['section_num'] for s in value['shots']}
        for cue in mapping['cues']:groups[section_for_shot[cue['shot_num']]].append(cue['ko'])
        return '\n\n'.join(''.join(groups[s['section_num']]) for s in value['sections'])
    return '\n\n'.join(section['narration'] for section in value['sections'])


def validate_bilingual(value,spec,timeline):
    mix_profile(value)
    mapping=value.get('bilingual')
    if mapping is None:return
    fields={'enabled','narration_language','arrangement','voice','rate','record_type','approval_sha256','cues'}
    if (not isinstance(mapping,dict) or set(mapping)!=fields or mapping['enabled'] is not True
            or mapping['narration_language'] not in ('zh-CN','ko-KR')
            or mapping['arrangement']!='single_language_track' or spec.get('video_subtitles') is not True
            or mix_profile(value)!='exec_pitch_p3' or not hash_id(mapping['approval_sha256'])):
        raise ValueError('双语须使用P3、单一语言旁白及已审中韩字幕映射，必须烧录字幕')
    expected={'zh-CN':{'microsoft_yunxi','microsoft_xiaoxiao','microsoft_yunjian'},'ko-KR':{'microsoft_injoon'}}
    if mapping['voice'] not in expected[mapping['narration_language']] or mapping['rate'] not in ('-6%','+0%','+10%'):
        raise ValueError('双语旁白语言、登记音色或合成语速不一致')
    kind='test_fixture' if value['media_kind']=='synthetic_fixture' else 'human_record'
    if mapping['record_type']!=kind:
        raise ValueError('合成字幕测试不能作为人工译审或真实配音审批')
    cues=mapping['cues'];limit=18 if spec['video_aspect_ratio']=='9:16' else 30
    if not isinstance(cues,list) or not len(value['shots'])<=len(cues)<=1200:
        raise ValueError('中韩字幕需要完整且有界的人工对齐分句')
    previous=0;groups={s['shot_num']:[] for s in value['shots']}
    for cue in cues:
        if not isinstance(cue,dict) or set(cue)!={'shot_num','start_frame','end_frame','zh','ko'}:
            raise ValueError('中韩字幕分句字段不合法')
        number=cue['shot_num'];start=cue['start_frame'];end=cue['end_frame']
        if (type(number) is not int or number not in groups or type(start) is not int or type(end) is not int
                or not previous<=start<end<=timeline['total_frames'] or end-start<12):
            raise ValueError('中韩字幕时间须单调无重叠，至少显示半秒；不得编造按字数均分的对齐')
        cut=timeline['shots'][number-1]
        if not cut['start_frame']<=start<end<=cut['end_frame']:
            raise ValueError('中韩字幕跨越所属口播节拍')
        for language in ('zh','ko'):
            text=cue[language]
            if (not isinstance(text,str) or not text.strip() or len(text)>limit or text!=text.strip()
                    or any(c in text for c in '\n\r\x00{}\\<>') or any(ord(c)<32 for c in text)):
                raise ValueError('中韩字幕每种语言仅一行，横屏最多30字、竖屏18字；必须提供已审分句')
        if not re.search('[가-힣]',cue['ko']):raise ValueError('韩语字幕缺少韩文，不能用占位文本冒充译文')
        previous=end;groups[number].append(cue)
    for shot in value['shots']:
        group=groups[shot['shot_num']]
        if ''.join(c['zh'] for c in group)!=shot['narration']:
            raise ValueError('中韩字幕中文与原文口播不一致或存在遗漏')
        cut=timeline['shots'][shot['shot_num']-1]
        # Explicit caption coverage, rather than made-up word timestamps.
        speech_start=cut['speech_start_sample']//2000
        speech_end=(cut['speech_start_sample']+shot['audio_samples']+1999)//2000
        if not group or group[0]['start_frame']>speech_start or group[-1]['end_frame']<speech_end:
            raise ValueError('中韩字幕未覆盖登记口播范围')
        if any(a['end_frame']!=b['start_frame'] for a,b in zip(group,group[1:])):
            raise ValueError('同一口播节拍的中韩字幕存在未说明间隙')


def bilingual_font(text):
    from gateway.exec_pitch_inputs import safe_file
    configured=os.getenv('NBPPT_BILINGUAL_FONT','');expected=os.getenv('NBPPT_BILINGUAL_FONT_SHA256','')
    if not configured or not Path(configured).is_absolute() or not hash_id(expected):
        raise ValueError('缺少经摘要固定的中韩字幕字体配置')
    path=Path(configured)
    safe_file(path.parent,path.name,50_000_000)
    if path.suffix.lower() not in ('.ttf','.otf') or digest(path.read_bytes())!=expected:
        raise ValueError('中韩字幕字体摘要不一致或不是单字体文件')
    try:
        from fontTools.ttLib import TTFont
    except ImportError as exc:
        raise ValueError('中韩字幕缺少fonttools字形检查运行时') from exc
    with TTFont(path) as font:
        cmap=font.getBestCmap() or {};family=font['name'].getDebugName(1)
        if any(ord(c) not in cmap for c in text if not c.isspace()):
            raise ValueError('中韩字幕字体缺少实际字幕字形，拒绝方框或静默回退')
        if not family or not re.fullmatch('[A-Za-z0-9 -]{1,80}',family):
            raise ValueError('中韩字幕字体族名不受支持')
    return path,family,expected


def load_bilingual(value,spec,timeline,root):
    from gateway.exec_pitch_inputs import safe_file
    validate_bilingual(value,spec,timeline)
    mapping=value.get('bilingual')
    if mapping is None:return None
    approval=safe_file(root,f"evidence/{mapping['approval_sha256']}.json",128*1024)
    raw=approval.read_bytes()
    if digest(raw)!=mapping['approval_sha256']:raise ValueError('中韩译审证据摘要改变')
    record=read_json_text(raw.decode())
    payload={k:v for k,v in mapping.items() if k!='approval_sha256'}
    fields={'record_type','reviewer','owner','source_sha256','mapping_sha256','audio_sha256','scope','approved_at','expires_at'}
    if (not isinstance(record,dict) or set(record)!=fields or record['record_type']!=mapping['record_type']
            or record['owner']!=spec['video_input_owner'] or record['source_sha256']!=value['source_sha256']
            or record['mapping_sha256']!=digest(canonical(payload))
            or record['audio_sha256']!=[s['audio_sha256'] for s in value['shots']]
            or record['scope']!='translation_captions_and_single_language_audio'
            or not isinstance(record['reviewer'],str) or not 1<=len(record['reviewer'])<=100):
        raise ValueError('中韩译审证据不匹配账户、原文、音轨或完整映射')
    try:
        start=datetime.fromisoformat(record['approved_at']);end=datetime.fromisoformat(record['expires_at'])
        if start.tzinfo is None or end.tzinfo is None or not start<=datetime.now(timezone.utc)<end:raise ValueError()
    except (TypeError,ValueError) as exc:raise ValueError('中韩译审证据未生效或已过期') from exc
    font,family,font_hash=bilingual_font(''.join(c['zh']+c['ko'] for c in mapping['cues']))
    return {'record_type':mapping['record_type'],'mapping_sha256':record['mapping_sha256'],
            'approval_sha256':mapping['approval_sha256'],'narration_language':mapping['narration_language'],
            'arrangement':mapping['arrangement'],'font_sha256':font_hash,'font_family':family,
            'alignment':'registered_caption_segments_not_word_alignment','font_path':font}
