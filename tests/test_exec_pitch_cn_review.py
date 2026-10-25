"""The local comparison cannot silently select a voice or reuse changed takes."""
import json

import pytest

from gateway.exec_pitch_contract import canonical,digest
from tools.exec_pitch_cn_review import prepare
from tools.exec_pitch_cn_review import review_clock
from tools.exec_pitch_cn_acceptance import cached_input


def test_full_voice_preparation_requires_exact_human_b_choice(tmp_path):
    (tmp_path/'human-selection.json').write_text(json.dumps({'source':'model_generated','decision':'B',
        'voice':'microsoft_yunjian','rate':'+10%','full_synthesis_authorized':True,'paid_calls_authorized':False}))
    # No reference files or provider are consulted until selection is checked.
    with pytest.raises(ValueError,match='human B choice'):prepare(tmp_path,tmp_path/'absent-reference',synthesize=True)
    assert not (tmp_path/'takes').exists()


def test_voice_cache_hash_change_never_triggers_implicit_new_synthesis(tmp_path):
    root=tmp_path/'review';reference=tmp_path/'reference';root.mkdir();reference.mkdir()
    (root/'human-selection.json').write_text(json.dumps({'source':'current_human_user_message','decision':'B',
        'voice':'microsoft_yunjian','rate':'+10%','full_synthesis_authorized':True,'paid_calls_authorized':False}))
    text='保留原文。'
    value={'title':'说明','audience':'审阅者','purpose':'检查身份','thesis':'保留来源。','causal_chain':['原文固定。','再核对。'],
           'evidence_boundary':'测试。','sections':[],'shots':[{'shot_num':1,'narration':text}]}
    (reference/'validated_video_plan.json').write_text(json.dumps({'exec_pitch_input':value,'exec_pitch_timeline':{},'original_prompt_cn':text}))
    takes=root/'takes';takes.mkdir()
    key=digest(canonical({'voice':'zh-CN-YunjianNeural','rate':'+10%','text':text,'edge_tts':'7.3.1'}))
    wav=takes/f'01-{key}.wav';wav.write_bytes(b'changed cached bytes')
    wav.with_suffix('.json').write_text(json.dumps({'key':key,'sha256':digest(b'original bytes')}))
    with pytest.raises(ValueError,match='Cached take identity changed'):prepare(root,reference,synthesize=True)
    assert wav.read_bytes()==b'changed cached bytes'


def test_private_review_clock_uses_raw_samples_and_only_permitted_handles():
    shots=[{'shot_num':i,'section_num':i,'audio_samples':108000,'lead_frames':6,'tail_frames':12,
            'audio_sha256':'a'*64,'visual_sha256':'b'*64} for i in (1,2)]
    clock=review_clock({'shots':shots})
    assert clock['total_frames']==144
    assert clock['shots'][0]['speech_start_sample']==12000
    assert clock['shots'][1]['start_frame']==72
    assert clock['shots'][1]['speech_start_sample']==156000
    shots[0]['tail_frames']=13
    with pytest.raises(ValueError,match='handles'):review_clock({'shots':shots})


def test_formal_cached_input_rejects_changed_takes_and_cross_account(tmp_path):
    # Test tones exercise provenance only, never voice/translation approval.
    from tools.exec_pitch_fixture import build_fixture
    from test_exec_pitch import spec
    cache=tmp_path/'cache';cache.mkdir()
    registry=cache/'registered'
    source,input_id,value=build_fixture(registry,'sandbox-nick',6)
    owner=digest(b'sandbox-nick');package=registry/owner/input_id
    (cache/'human-selection.json').write_text(json.dumps({'source':'current_human_user_message','decision':'B',
        'voice':'microsoft_yunjian','rate':'+10%','full_synthesis_authorized':True,'paid_calls_authorized':False}))
    (cache/'admission.json').write_text(json.dumps({'input_id':input_id,'registry':str(registry),
        'spec':spec(source,6,input_id,owner)}))
    (cache/'takes').mkdir();(cache/'candidate-assets').mkdir();records=[]
    for shot in value['shots']:
        identity={'voice':'zh-CN-YunjianNeural','rate':'+10%','text':shot['narration'],'edge_tts':'7.3.1'}
        key=digest(canonical(identity));audio=(package/'assets'/f"{shot['audio_sha256']}.wav").read_bytes()
        (cache/'takes'/f"{shot['shot_num']:02}-{key}.wav").write_bytes(audio)
        (cache/'candidate-assets'/f"beat-{shot['shot_num']:02}.wav").write_bytes(audio)
        records.append({**identity,'shot_num':shot['shot_num'],'key':key,'sha256':digest(audio)})
    (cache/'takes.json').write_text(json.dumps(records))
    destination=tmp_path/'accepted'
    assert cached_input(destination,'sandbox-nick',cache)==(source,input_id,value)
    assert (destination/owner/input_id/'input.json').read_bytes()==(package/'input.json').read_bytes()
    with pytest.raises(ValueError,match='different sandbox account'):
        cached_input(tmp_path/'foreign','another-user',cache)
    first=next((cache/'takes').glob('01-*.wav'));first.write_bytes(b'changed')
    with pytest.raises(ValueError,match='no new synthesis'):
        cached_input(tmp_path/'tampered','sandbox-nick',cache)
    assert not (tmp_path/'tampered').exists()
    first.write_bytes((package/'assets'/f"{value['shots'][0]['audio_sha256']}.wav").read_bytes())
    (cache/'candidate-assets'/'beat-01.wav').write_bytes(b'changed PCM')
    with pytest.raises(ValueError,match='Registered PCM differs'):
        cached_input(tmp_path/'bad-pcm','sandbox-nick',cache)
    assert not (tmp_path/'bad-pcm').exists()
