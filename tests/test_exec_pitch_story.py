"""P6 causal coverage and evidence/voice integrity, without semantic approval."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from gateway.exec_pitch_contract import canonical,digest,validate_input
from gateway.exec_pitch_story import validate_story,validate_parent,voice_identity,story_manifest
from test_exec_pitch import long_data,spec


def fixture():
    source,v=long_data();v['shots']=v['shots'][:5];v['sections']=v['sections'][:3]
    v['sections'][-1]['narration']=v['shots'][-1]['narration']
    v['sections'][-1]['source_quotes']=[v['shots'][-1]['narration']]
    v['shots'][-1]['source_quotes']=v['sections'][-1]['source_quotes']
    source='\n'.join(s['narration'] for s in v['shots']);v['source_sha256']=digest(source.encode())
    v['voice_mix']={'profile':'exec_pitch_p3','music':'none','input_audio':'dry_dialogue'}
    v['quality']={'profile':'exec_pitch_p4','alignment_sha256':'a'*64,'client_rules_sha256':None}
    parent=deepcopy(v);key=digest(canonical(parent));s=spec(source,56)
    acts=[{'id':k,'title':title,'argument':'只验证合成测试简报与声音身份，不是实际故事验收。',
           'first_shot':a,'last_shot':b,'source_quotes':[v['shots'][a-1]['source_quotes'][0]]}
          for k,title,a,b in [('problem','问题',1,1),('mechanism','机制',2,3),('proof','证据边界',4,4),('close','收束',5,5)]]
    kinds=['conditional_scenario','conditional_scenario','conditional_scenario','limitation','proposed_validation']
    actions=['locate_gap','escalate_unknown','confirm_location','separate_proof','return_question']
    v['story']={'version':1,'source_sha256':v['source_sha256'],'parent_input_id':key,
        'voice_identity_sha256':voice_identity(v),'question':'输入怎样形成可追溯交付？','entity':'合成测试对象','acts':acts,
        'turn':{'shot_num':2,'condition':v['shots'][1]['source_quotes'][0],'source_quotes':v['shots'][1]['source_quotes']},
        'proof':{'kind':'source_grounded_demonstration','observed_outcomes':[],
                 'limitation':source.splitlines()[-1],'source_quotes':[source.splitlines()[-1]]},
        'ending':{'echo_question':'输入怎样形成可追溯交付？','next_step':source.splitlines()[0],
                  'source_quotes':[source.splitlines()[0]],'status':'proposed_not_deployed'},
        'beats':[{'shot_num':i,'act':act,'action':action,'evidence_kind':kind,'source_quotes':v['shots'][i-1]['source_quotes']}
                 for i,act,action,kind in zip(range(1,6),['problem','mechanism','mechanism','proof','close'],actions,kinds)]}
    for shot in v['shots']:shot['motion']={'layout':'parcel_story','headline':'合成测试动作','labels':['来源','交付'],'focus':0}
    return source,v,s,parent,key


def test_story_covers_clock_preserves_original_voice_and_distinguishes_proof():
    source,v,s,parent,key=fixture();t=validate_input(v,s);m=story_manifest(v,t)
    assert m['acts'][0]['start_frame']==0 and m['acts'][-1]['end_frame']==56*24
    assert voice_identity(v)==voice_identity(parent) and m['observed_outcomes']==[]
    assert m['human_story_approval']=='NOT_REVIEWED'
    assert m['beats'][3]['evidence_kind']=='limitation'


@pytest.mark.parametrize('mutate',[
    lambda v:v['story'].update(version=True),
    lambda v:v['story']['proof'].update(observed_outcomes=['已提升效率']),
    lambda v:v['story']['proof'].update(kind='observed_business_result'),
    lambda v:v['story']['proof'].update(limitation='来源没有的承诺'),
    lambda v:v['story']['acts'][1].update(first_shot=3),
    lambda v:v['story']['beats'][3].update(evidence_kind='source_statement'),
    lambda v:v['story']['beats'][1].update(action='confirm_location'),
    lambda v:v['story']['ending'].update(status='deployed'),
    lambda v:v['story']['ending'].update(echo_question='另一个问题'),
    lambda v:v['story'].update(question='<script>alert(1)</script>'),
    lambda v:v['story']['beats'][0].update(source_quotes=['不存在的来源']),
    lambda v:v['shots'][0].update(narration='擅自改配音稿。'),
    lambda v:v['shots'][0].update(audio_sha256='b'*64),
    lambda v:v.update(revision={'operation':'polish_shot'}),
    lambda v:v.pop('story'),
])
def test_story_refuses_invented_proof_gaps_unbound_actions_or_voice_edits(mutate):
    source,v,s,parent,key=fixture();mutate(v)
    with pytest.raises(ValueError):validate_story(v,s)


def test_story_rejects_portrait_without_regressing_legacy_profile():
    source,v,s,parent,key=fixture()
    with pytest.raises(ValueError):validate_story(v,{**s,'video_aspect_ratio':'9:16'})
    validate_story(parent,{**s,'video_aspect_ratio':'9:16'})


def test_parent_identity_is_account_bound_and_not_just_a_recomputed_self_hash(tmp_path,monkeypatch):
    source,v,s,parent,key=fixture();s['video_input_owner']='b'*64
    root=tmp_path/'registry';p=root/s['video_input_owner']/key;p.mkdir(parents=True);(p/'input.json').write_bytes(canonical(parent))
    monkeypatch.setenv('NBPPT_EXEC_PITCH_ROOT',str(root));validate_parent(v,s)
    bad=deepcopy(v);bad['shots'][0]['audio_sha256']='c'*64;bad['story']['voice_identity_sha256']=voice_identity(bad)
    with pytest.raises(ValueError,match='父版本不同'):validate_parent(bad,s)
    with pytest.raises(ValueError):validate_parent(v,{**s,'video_input_owner':'a'*64})
    (p/'input.json').write_text('{}')
    with pytest.raises(ValueError):validate_parent(v,s)
