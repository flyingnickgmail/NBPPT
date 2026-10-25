"""P3 profiles, approval binding and actual AAC/subtitle acceptance boundaries."""
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from gateway import audio_contract
from gateway.exec_pitch_contract import canonical,digest,validate_input
from gateway.exec_pitch_inputs import load_input
from gateway.exec_pitch_voice import mix_profile,load_bilingual,bilingual_font,narration_text
from gateway.video_contract import validate_voice_rate
from tools.exec_pitch_voice_fixture import build_voice_fixture
from test_exec_pitch import spec
from test_security_delivery import manager,KEY_A,balance


@pytest.fixture
def voice_input(tmp_path,monkeypatch):
    registry=tmp_path/'registry';monkeypatch.setenv('NBPPT_EXEC_PITCH_ROOT',str(registry))
    source,input_id,value=build_voice_fixture(registry,'voice-test')
    data=spec(source,6,input_id,digest(b'voice-test'))
    root=registry/data['video_input_owner']/input_id
    return value,data,root


@pytest.mark.parametrize('peak,legacy,p3', [(-3.8,True,True),(-3.79,True,False),(-1.6,True,False),(-1.49,False,False)])
def test_final_peak_profile_does_not_retroactively_reject_legacy(monkeypatch,peak,legacy,p3):
    monkeypatch.setattr(audio_contract,'measure_loudness',lambda *a,**kw:{'input_i':-16,'input_tp':peak})
    for profile,allowed in [('legacy',legacy),('exec_pitch_p3',p3)]:
        if allowed:assert audio_contract.verify_loudness('encoded.mp4',profile=profile)['true_peak_dbfs']==peak
        else:
            with pytest.raises(ValueError):audio_contract.verify_loudness('encoded.mp4',profile=profile)


@pytest.mark.parametrize('level',[-17.01,-14.99,float('nan')])
def test_p3_loudness_cannot_be_loosened_for_a_low_peak(monkeypatch,level):
    monkeypatch.setattr(audio_contract,'measure_loudness',lambda *a,**kw:{'input_i':level,'input_tp':-6})
    with pytest.raises(ValueError):audio_contract.verify_loudness('encoded.mp4',profile='exec_pitch_p3')


@pytest.mark.parametrize('mutate',[
    lambda v:v.update(voice_mix={'profile':'exec_pitch_p3','music':'download_url','input_audio':'dry_dialogue'}),
    lambda v:v['voice_mix'].update(input_audio='already_mixed'),
    lambda v:v['bilingual'].update(enabled=False),
    lambda v:v['bilingual'].update(arrangement='overlap_two_voices'),
    lambda v:v['bilingual'].update(voice='microsoft_yunxi'),
    lambda v:v['bilingual'].update(record_type='human_record'),
    lambda v:v['bilingual']['cues'][1].update(start_frame=1),
    lambda v:v['bilingual']['cues'][0].update(start_frame=24),
    lambda v:v['bilingual']['cues'][0].update(end_frame=100),
    lambda v:v['bilingual']['cues'][0].update(zh='偷偷更改原文'),
    lambda v:v['bilingual']['cues'][0].update(ko='unapproved placeholder'),
    lambda v:v['bilingual']['cues'][0].update(ko='가'*31),
    lambda v:v['bilingual']['cues'][0].update(ko='{가}'),
    lambda v:v['bilingual']['cues'][0].update(start_frame=True),
])
def test_bilingual_bad_or_unapproved_alignment_fails(voice_input,mutate):
    value,data,_=voice_input;mutate(value)
    with pytest.raises(ValueError):validate_input(value,data)


def test_bilingual_requires_burn_and_tighter_mix(voice_input):
    value,data,_=voice_input
    with pytest.raises(ValueError):validate_input(value,{**data,'video_subtitles':False})
    value.pop('voice_mix')
    with pytest.raises(ValueError):validate_input(value,data)


def test_selected_language_transcript_matches_the_registered_captions(voice_input):
    value,_,_=voice_input
    assert narration_text(value)=='원문 보존.\n\n사람 검토 아님.'
    value['bilingual']['narration_language']='zh-CN'
    assert narration_text(value)=='先保留原文。\n\n不代表人工审核。'


def test_missing_bilingual_evidence_rejected_by_real_http_before_freeze(manager,tmp_path,monkeypatch):
    from gateway import main
    from gateway.auth import authenticate_key
    import httpx
    async def run():
        principal=await authenticate_key(manager,KEY_A)
        registry=tmp_path/'registry';monkeypatch.setenv('NBPPT_EXEC_PITCH_ROOT',str(registry))
        source,input_id,value=build_voice_fixture(registry,principal['user_id'])
        root=registry/digest(principal['user_id'].encode())/input_id
        (root/'evidence'/f"{value['bilingual']['approval_sha256']}.json").unlink()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://sandbox') as client:
            response=await client.post('/api/jobs',headers={'Authorization':'Bearer '+KEY_A},json={
                'source':source,'request_id':'voice-no-proof-p3','task_type':'video','video_duration_sec':6,
                'video_preset':'exec_pitch','video_input_id':input_id,'video_voice':'approved_local',
                'video_visual_mode':'registered_local'})
        assert response.status_code==422 and balance(manager)==(2000,0)
    asyncio.run(run())


def test_approval_record_binds_full_mapping_audio_source_and_owner(voice_input,monkeypatch):
    value,data,root=voice_input;timeline=validate_input(value,data)
    monkeypatch.setattr('gateway.exec_pitch_voice.bilingual_font',lambda text:(Path('/operator/font.ttf'),'Test Font','f'*64))
    assert load_bilingual(value,data,timeline,root)['record_type']=='test_fixture'
    with pytest.raises(ValueError):load_bilingual(value,{**data,'video_input_owner':'a'*64},timeline,root)
    changed=copy.deepcopy(value);changed['bilingual']['cues'][0]['ko']='원문 보존합니다.'
    with pytest.raises(ValueError,match='译审证据'):load_bilingual(changed,data,timeline,root)
    proof=root/'evidence'/f"{value['bilingual']['approval_sha256']}.json"
    proof.write_text(proof.read_text()+' ')
    with pytest.raises(ValueError,match='摘要'):load_bilingual(value,data,timeline,root)


def test_missing_font_runtime_fails_before_admission(voice_input,monkeypatch):
    _,data,_=voice_input;monkeypatch.delenv('NBPPT_BILINGUAL_FONT',raising=False)
    with pytest.raises(ValueError,match='字体'):load_input(data['video_input_owner'],data['video_input_id'],data)


def test_real_glyph_check_rejects_missing_korean(tmp_path,monkeypatch):
    # A deliberately tiny local test font proves glyph checks, without relying
    # on the operator's installed fonts or licensing a font fixture.
    pytest.importorskip('fontTools',reason='optional bilingual glyph runtime not configured')
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    builder=FontBuilder(1000,isTTF=True);builder.setupGlyphOrder(['.notdef','A'])
    pen=TTGlyphPen(None);glyph=pen.glyph()
    builder.setupCharacterMap({65:'A'});builder.setupGlyf({'.notdef':glyph,'A':glyph})
    builder.setupHorizontalMetrics({'.notdef':(500,0),'A':(500,0)});builder.setupHorizontalHeader(ascent=800,descent=-200)
    builder.setupNameTable({'familyName':'Test Font','styleName':'Regular'});builder.setupOS2();builder.setupPost()
    font=tmp_path/'test.ttf';builder.save(font)
    monkeypatch.setenv('NBPPT_BILINGUAL_FONT',str(font));monkeypatch.setenv('NBPPT_BILINGUAL_FONT_SHA256',digest(font.read_bytes()))
    assert bilingual_font('A')[1]=='Test Font'
    with pytest.raises(ValueError,match='字形'):bilingual_font('한')
    font.write_bytes(font.read_bytes()+b'changed')
    with pytest.raises(ValueError,match='摘要'):bilingual_font('A')


def test_rate_is_synthesis_parameter_no_post_stretch(monkeypatch):
    from worker import video_microsoft_voice as voice
    import sys
    monkeypatch.setattr(voice,'preflight_microsoft',lambda:None)
    captured=[]
    class Communicate:
        def __init__(self,text,name,**kwargs):captured.append((text,name,kwargs))
        async def stream(self):yield {'type':'audio','data':b'encoded'}
    monkeypatch.setitem(sys.modules,'edge_tts',SimpleNamespace(Communicate=Communicate))
    engine=voice.MicrosoftEngine('microsoft_yunjian',rate='+10%')
    assert asyncio.run(engine._request('相同口播'))==b'encoded'
    assert captured[0][1]=='zh-CN-YunjianNeural' and captured[0][2]['rate']=='+10%'
    assert voice.MicrosoftEngine('microsoft_injoon').voice=='ko-KR-InJoonNeural'
    with pytest.raises(ValueError):engine.generate('相同口播',speed=1.1)
    with pytest.raises(ValueError):voice.MicrosoftEngine('microsoft_yunjian',rate='+100%')
    with pytest.raises(ValueError):validate_voice_rate('approved_local','+10%')


def test_speech_cache_cannot_reuse_another_rate(tmp_path):
    from worker.video_speech import synthesize_narration,SpeechError
    root=tmp_path/'video_1234567890';(root/'staging').mkdir(parents=True)
    (root/'staging/video_1234567890_video.mp4').write_bytes(b'not read before cache validation')
    (root/'speech_cache.json').write_text(json.dumps({'voice':'microsoft_yunjian','rate':'+0%','scenes':[{}]}))
    with pytest.raises(SpeechError,match='缓存'):
        synthesize_narration(root,root.name,{'video_voice':'microsoft_yunjian','video_voice_rate':'+10%','video_scenes':[{}]})


def test_ducking_is_derived_from_voice_without_wraparound():
    from worker.video_music import mix_original_bed
    rate=8000;silent=np.zeros(8*rate,dtype=np.float32);voice=silent.copy()
    voice[3*rate:5*rate]=.05*np.sin(2*np.pi*440*np.arange(2*rate)/rate)
    baseline=mix_original_bed(silent,rate);bed=mix_original_bed(voice,rate)-voice
    assert np.sqrt(np.mean(bed[3*rate:5*rate]**2))<.35*np.sqrt(np.mean(baseline[3*rate:5*rate]**2))
    end=voice*0;end[-rate:]=.05
    assert np.allclose(mix_original_bed(end,rate)[:rate],baseline[:rate])
    assert len(mix_original_bed(np.zeros(8,dtype=np.float32),rate))==8


def test_rate_idempotency_retry_and_wrong_voice_pre_freeze(manager,monkeypatch):
    from gateway.mcp_server import PresentationJobs
    from gateway.auth import authenticate_key
    monkeypatch.setenv('NBPPT_MICROSOFT_EDGE_ENABLED','true')
    async def run():
        jobs=PresentationJobs(manager);principal=await authenticate_key(manager,KEY_A);captured=[]
        async def fail(job,args):captured.append(args);await manager.cancel_refund(job,'fixture failure')
        monkeypatch.setattr(jobs,'execute',fail)
        first=await jobs.create(principal,'完整原文','auto',0,'voice-p3-001','video',6,'16:9','microsoft_yunjian',video_voice_rate='+10%')
        await asyncio.gather(*list(jobs.tasks))
        with pytest.raises(ValueError,match='request_id'):
            await jobs.create(principal,'完整原文','auto',0,'voice-p3-001','video',6,'16:9','microsoft_yunjian',video_voice_rate='+0%')
        await jobs.retry(principal,first['job_id'],'voice-p3-002');await asyncio.gather(*list(jobs.tasks))
        assert captured[0]==captured[1] and captured[1]['video_voice_rate']=='+10%'
        with pytest.raises(ValueError):await jobs.create(principal,'原文','auto',0,'voice-p3-003','video',6,'16:9','melo',video_voice_rate='+10%')
        assert balance(manager)==(2000,0)
        await jobs.close()
    asyncio.run(run())


def test_encoded_dynamic_mix_keeps_peak_loudness_and_sample_clock(tmp_path):
    """Transient-rich dialogue and music gaps, unlike the short steady tone."""
    import subprocess
    from worker.video_music import mix_original_bed
    from worker.video_speech import _write_pcm_wav,_mux_audio
    rate=48000;seconds=24;t=np.arange(rate*seconds)/rate
    voice=np.zeros(len(t),dtype=np.float32)
    for start,end in [(1,5),(8,12),(16,20)]:
        local=t[start*rate:end*rate]-start
        envelope=.25+.75*np.sin(2*np.pi*2*local)**2
        voice[start*rate:end*rate]=.09*(np.sin(2*np.pi*147*local)+.23*np.sin(2*np.pi*294*local))*envelope
        for at in np.arange(start+.2,end,.65):
            first=round(at*rate);count=240
            voice[first:first+count]+=.55*np.exp(-np.arange(count)/35)
    video=tmp_path/'picture.mp4';wav=tmp_path/'mix.wav';out=tmp_path/'encoded.mp4'
    subprocess.run(['ffmpeg','-v','error','-nostdin','-f','lavfi','-i',f'color=size=128x72:rate=24:duration={seconds}',
                    '-an','-c:v','libx264','-threads','2',str(video)],check=True,capture_output=True)
    _write_pcm_wav(wav,mix_original_bed(voice,rate),rate)
    _mux_audio(video,wav,out,seconds,normalise=True,sample_rate=rate,audio_profile='exec_pitch_p3')
    assert audio_contract.verify_loudness(out,profile='exec_pitch_p3')['true_peak_dbfs']<=-3.8
    decoded=np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-nostdin','-i',str(out),'-vn','-ac','1',
        '-ar',str(rate),'-f','s16le','-']),dtype='<i2').astype(float)
    assert abs(len(decoded)-rate*seconds)<=1024
    start=2*rate;window=rate//2
    assert np.corrcoef(voice[start:start+window],decoded[start:start+window])[0,1]>.9
