"""P6 source-bound causal brief and deterministic schematic story beats.

This optional profile preserves the registered script/audio. Its evidence
classification is explicit: a mechanism demonstration is not an observed result.
"""
from gateway.exec_pitch_contract import canonical, digest, hash_id
from gateway.video_contract import _plain_text, NUMBER_PATTERN

ACTS = ('problem', 'mechanism', 'proof', 'close')
ACTIONS = {'locate_gap', 'withhold_judgment', 'form_question', 'join_records', 'trace_origin',
           'route_not_proof', 'visit_handover', 'scan_identity', 'escalate_unknown', 'block_guess',
           'human_decision', 'confirm_location', 'append_basis', 'notify_then_verify',
           'review_trace', 'separate_proof', 'withhold_roi', 'pilot_roles', 'decide_scale', 'return_question'}
KINDS = ('source_statement', 'conditional_scenario', 'proposed_validation', 'limitation')


def voice_identity(value):
    return digest(canonical([{'shot_num':s['shot_num'],'narration':s['narration'],
                             'audio_sha256':s['audio_sha256'],'audio_samples':s['audio_samples'],
                             'lead_frames':s['lead_frames'],'tail_frames':s['tail_frames']} for s in value['shots']]))


def validate_parent(value,spec):
    if 'story' not in value:return
    import os,json
    from pathlib import Path
    from gateway.exec_pitch_inputs import safe_file
    key=value['story']['parent_input_id']
    root=Path(os.environ['NBPPT_EXEC_PITCH_ROOT'])/spec['video_input_owner']/key
    parent=json.loads(safe_file(root,'input.json',128*1024).read_text())
    if (digest(canonical(parent))!=key or parent['source_sha256']!=value['source_sha256']
            or voice_identity(parent)!=voice_identity(value)):
        raise ValueError('P6原文、镜头顺序、配音或留量与同账户父版本不同')


def validate_story(value, spec):
    story = value.get('story')
    layouts = [s.get('motion', {}).get('layout') for s in value['shots']]
    if story is None:
        if 'parcel_story' in layouts:
            raise ValueError('叙事镜头缺少先行因果简报')
        return
    fields = {'version','source_sha256','parent_input_id','voice_identity_sha256','question','entity',
              'acts','turn','proof','ending','beats'}
    if (not isinstance(story,dict) or set(story)!=fields or type(story['version']) is not int or story['version']!=1
            or story['source_sha256']!=value['source_sha256'] or not hash_id(story['parent_input_id'])
            or story['voice_identity_sha256']!=voice_identity(value)
            or spec['video_aspect_ratio']!='16:9' or value.get('quality',{}).get('profile')!='exec_pitch_p4'
            or 'revision' in value or any(x!='parcel_story' for x in layouts)):
        raise ValueError('P6简报必须绑定原文/声音、横屏P4实测管线和完整叙事；不能冒充单镜修订')
    source = spec['original_prompt_cn']; numbers = set(NUMBER_PATTERN.findall(source))
    def plain(text, name, maximum):
        if _plain_text(text,name,maximum)!=text or any(n not in numbers for n in NUMBER_PATTERN.findall(text)):
            raise ValueError('叙事文字未规范化或包含原文没有的数字')
    def quotes(items):
        if not isinstance(items,list) or not 1<=len(items)<=8 or any(not isinstance(q,str) or not q.strip() or len(q)>400 or q not in source for q in items):
            raise ValueError('叙事论证缺少逐条原文支持')
    plain(story['question'],'question',80);plain(story['entity'],'entity',20)
    acts=story['acts']
    if not isinstance(acts,list) or len(acts)!=4:raise ValueError('叙事须依次覆盖问题、机制、来源支持的证据与收束')
    cursor=1;mapping={}
    for act,kind in zip(acts,ACTS):
        if (not isinstance(act,dict) or set(act)!={'id','title','argument','first_shot','last_shot','source_quotes'}
                or act['id']!=kind or any(type(act[k]) is not int for k in ('first_shot','last_shot'))
                or act['first_shot']!=cursor or not cursor<=act['last_shot']<=len(value['shots'])):
            raise ValueError('叙事阶段必须连续完整，不得调换已有口播顺序')
        plain(act['title'],'act title',12);plain(act['argument'],'argument',240);quotes(act['source_quotes'])
        for n in range(cursor,act['last_shot']+1):mapping[n]=kind
        cursor=act['last_shot']+1
    if cursor!=len(value['shots'])+1:raise ValueError('叙事阶段未覆盖完整口播')
    proof=story['proof']
    if (not isinstance(proof,dict) or set(proof)!={'kind','observed_outcomes','limitation','source_quotes'}
            or proof['kind']!='source_grounded_demonstration' or proof['observed_outcomes']!=[]):
        raise ValueError('本P6演绎配置没有实测成效，不能把建议或演示登记为观察证据')
    plain(proof['limitation'],'proof limitation',160);quotes(proof['source_quotes'])
    if proof['limitation'] not in source:raise ValueError('证据边界必须保留原文限制')
    turn=story['turn']
    if (not isinstance(turn,dict) or set(turn)!={'shot_num','condition','source_quotes'}
            or type(turn['shot_num']) is not int or mapping.get(turn['shot_num'])!='mechanism'):
        raise ValueError('故事缺少查证后的条件判断')
    plain(turn['condition'],'turn condition',100);quotes(turn['source_quotes'])
    if turn['condition'] not in source:raise ValueError('转折条件没有原文依据')
    ending=story['ending']
    if (not isinstance(ending,dict) or set(ending)!={'echo_question','next_step','source_quotes','status'}
            or ending['echo_question']!=story['question'] or ending['status']!='proposed_not_deployed'):
        raise ValueError('收束必须回应同一问题，不能把试点建议写成已经部署')
    plain(ending['next_step'],'next_step',160);quotes(ending['source_quotes'])
    if ending['next_step'] not in source:raise ValueError('收束建议没有原文依据')
    beats=story['beats']
    if not isinstance(beats,list) or len(beats)!=len(value['shots']):raise ValueError('叙事动作未覆盖全部镜头')
    seen=[]
    for shot,beat in zip(value['shots'],beats):
        if (not isinstance(beat,dict) or set(beat)!={'shot_num','act','action','evidence_kind','source_quotes'}
                or type(beat['shot_num']) is not int or beat['shot_num']!=shot['shot_num']
                or beat['act']!=mapping[shot['shot_num']] or not isinstance(beat['action'],str) or beat['action'] not in ACTIONS
                or beat['evidence_kind'] not in KINDS or beat['source_quotes']!=shot['source_quotes']):
            raise ValueError('叙事镜头动作、证据分类或来源与原口播不一致')
        quotes(beat['source_quotes']);seen.append(beat['action'])
        if beat['act']=='proof' and beat['evidence_kind'] not in ('proposed_validation','limitation'):
            raise ValueError('来源演绎不等于已观察到的业务成效')
    required=['locate_gap','escalate_unknown','confirm_location','return_question']
    if any(seen.count(k)!=1 for k in required) or seen[0]!='locate_gap' or seen[-1]!='return_question':
        raise ValueError('叙事缺少同一事件的开场、条件交接、确认分支或问题回扣')
    if not seen.index('escalate_unknown')<seen.index('confirm_location') or beats[turn['shot_num']-1]['action']!='escalate_unknown':
        raise ValueError('未经查证不能直接跳到确认或更正')


def story_manifest(value,timeline):
    story=value['story']
    return {'version':1,'brief_sha256':digest(canonical(story)),'source_sha256':value['source_sha256'],
            'parent_input_id':story['parent_input_id'],'voice_identity_sha256':voice_identity(value),
            'evidence_scope':'source_grounded_mechanism_and_proposed_validation_not_observed_outcomes',
            'human_story_approval':'NOT_REVIEWED','observed_outcomes':[],
            'acts':[{**a,'start_frame':timeline['shots'][a['first_shot']-1]['start_frame'],
                     'end_frame':timeline['shots'][a['last_shot']-1]['end_frame']} for a in story['acts']],
            'beats':[{**b,'start_frame':cut['start_frame'],'end_frame':cut['end_frame'],
                      'audio_sha256':s['audio_sha256']} for b,cut,s in zip(story['beats'],timeline['shots'],value['shots'])]}


def brief_markdown(value):
    b=value['story'];lines=['# P6 叙事简报','',b['question'],f"贯穿对象：{b['entity']}",'']
    for act in b['acts']:
        lines.extend([f"## {act['title']}",act['argument'],*['原文依据：'+q for q in act['source_quotes']],''])
    lines.extend(['## 判断与边界',b['turn']['condition'],b['proof']['limitation'],
                  '已观察到的业务成效：无；演绎与建议均不作为实测证据。',
                  '内容、客户最终画面、品牌与韩语译审未由叙事简报批准。',''])
    return '\n'.join(lines)
