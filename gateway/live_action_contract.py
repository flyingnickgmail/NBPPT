"""A data-only edit decision list, shared with independent delivery validation."""
import re
import math


def validate_live_plan(plan, spec):
    from gateway.video_contract import validate_video_plan, _plain_text
    if not isinstance(plan,dict) or not isinstance(plan.get('scenes'),list):
        raise ValueError('实景流程缺少分镜')
    if any(not isinstance(s,dict) or 'shots' not in s for s in plan['scenes']):
        raise ValueError('实景场景缺少剪辑镜头')
    base=validate_video_plan({**plan,'scenes':[{k:v for k,v in s.items() if k!='shots'} for s in plan['scenes']]},
                             {**spec,'video_visual_mode':'motion'})
    used=set();footage_seconds=0;animations=0;shot_count=0
    for scene,raw in zip(base,plan['scenes']):
        shots=raw['shots']
        if not isinstance(shots,list) or not 1<=len(shots)<=8:
            raise ValueError('每个口播段需要1至8个镜头')
        if scene['duration_sec']>18:
            raise ValueError('口播段过长，请拆成有独立行动的短段')
        total=0;clean=[]
        for shot in shots:
            if not isinstance(shot,dict) or set(shot)!={'clip_id','duration_sec','reason'}:
                raise ValueError('剪辑只接受素材编号、秒数和原因，不接受路径或代码')
            d=shot['duration_sec'];cid=shot['clip_id']
            if type(d) is not int or not 2<=d<=6:
                raise ValueError('每镜必须2至6秒，禁止长时间停留')
            if not isinstance(cid,str) or not re.fullmatch(r'[a-z0-9_-]{1,64}',cid):
                raise ValueError('素材编号无效')
            _plain_text(shot['reason'],'选镜原因',180)
            if cid=='animation':
                animations+=1
                if animations>2:
                    raise ValueError('不能连续用解释动画替代实景')
            else:
                animations=0;footage_seconds+=d
                if cid in used:
                    raise ValueError('同一实景时间窗不能重复使用')
                used.add(cid)
            clean.append(dict(shot));total+=d;shot_count+=1
        if total!=scene['duration_sec']:
            raise ValueError('剪辑镜头总时长与口播段不一致')
        scene['shots']=clean
    if footage_seconds<spec['video_duration_sec']*.6:
        raise ValueError('实景至少占总时长60%，素材不足不能回退动态PPT')
    if spec['video_duration_sec']>=60 and (len(used)<8 or shot_count<spec['video_duration_sec']//5):
        raise ValueError('长片缺少足够素材和镜头变化')
    return base


def validate_sources(data, spec):
    """Validate public provenance and its exact correspondence to the edit list."""
    from gateway.footage_contract import validate_source
    from gateway.video_contract import validate_footage_review
    if not isinstance(data,dict) or data.get('usage')!='illustration_only' or set(data)!={'usage','clips'}:
        raise ValueError('缺少实景来源记录')
    expected=[(s,shot) for s in spec['video_scenes'] for shot in s['shots'] if shot['clip_id']!='animation']
    clips=data['clips']
    if not isinstance(clips,list) or len(clips)!=len(expected):
        raise ValueError('素材来源未覆盖实际剪辑')
    intervals={};sizes=set();previous=[]
    for c,(s,shot) in zip(clips,expected):
        validate_source(c)
        if c.get('id')!=shot['clip_id'] or c.get('duration_sec')!=shot['duration_sec'] or c.get('reason')!=shot['reason']:
            raise ValueError('素材来源与已核验分镜不一致')
        if (type(c.get('start')) not in (int,float) or not math.isfinite(c['start']) or c['start']<0
                or not re.fullmatch(r'[a-f0-9]{64}',c.get('sha256',''))
                or c.get('source_quote') not in s['source_quotes']):
            raise ValueError('素材时间窗、摘要或引用无效')
        start=c['start'];end=start+c['duration_sec']
        if any(max(start,a)<min(end,b) for a,b in intervals.get(c['sha256'],[])):
            raise ValueError('重复使用同一实拍画面')
        intervals.setdefault(c['sha256'],[]).append((start,end))
        if c.get('review'):
            validate_footage_review(c,spec)
        elif c.get('reviewed') is not True:
            raise ValueError('素材没有通过审核')
        if c.get('shot_size') not in {'wide','person','interaction','detail','medium','close'}:
            raise ValueError('缺少受支持的景别')
        sizes.add(c.get('shot_size'))
        previous.append(c['sha256'])
    if len(clips)>=4 and len(sizes)<2:
        raise ValueError('实景缺少景别变化')
    if any(a==b==c for a,b,c in zip(previous,previous[1:],previous[2:])):
        raise ValueError('连续同机位过多')
    return clips
