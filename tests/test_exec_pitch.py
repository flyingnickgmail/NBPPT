"""P0 contracts, admission boundaries, retry and real trusted media integration."""
import asyncio
import copy
import json
import sqlite3
import subprocess
from types import SimpleNamespace

import httpx
import pytest

from gateway import main, mcp_server
from gateway.auth import authenticate_key
from gateway.exec_pitch_contract import canonical, digest, validate_input
from gateway.exec_pitch_inputs import load_input
from gateway.video_contract import validate_video_spec
from gateway.mcp_server import PresentationJobs
from test_security_delivery import manager, KEY_A, KEY_B, balance
from tools.exec_pitch_fixture import SENTENCES, build_fixture
from worker import video_subtitles, worker_api


def spec(source,seconds=480,input_id='a'*64,owner='b'*64):
    return {'generation_contract':'exec-pitch-v1','planner_provider':'approved_data','video_preset':'exec_pitch',
            'video_input_id':input_id,'video_input_owner':owner,'original_prompt_cn':source,
            'video_duration_sec':seconds,'video_aspect_ratio':'16:9','video_voice':'approved_local',
            'video_narration':True,'video_subtitles':True,'video_visual_mode':'registered_local'}


def long_data():
    source='\n'.join(SENTENCES)
    shots=[];sections=[]
    for i,(sentence,d) in enumerate(zip(SENTENCES,[8,11,13,16]*10),1):
        section=(i+1)//2
        shots.append({'shot_num':i,'section_num':section,'narration':sentence,'source_quotes':[],
                      'reason':'合成测试镜头说明对应制作环节。','audio_sha256':'a'*64,'visual_sha256':'b'*64,
                      'audio_samples':int((d-.75)*48000),'lead_frames':6,'tail_frames':12})
    for i in range(1,21):
        group=shots[(i-1)*2:i*2];quotes=[s['narration'] for s in group]
        for shot in group: shot['source_quotes']=quotes
        sections.append({'section_num':i,'argument':'先确定来源，再核对具体输入与交付。',
                         'narration':''.join(quotes),'source_quotes':quotes})
    return source,{'title':'制作链路','audience':'制作人员','purpose':'检验长片输入与交付','thesis':'来源连接可验证交付。',
                   'causal_chain':['原文固定口播。','实测音频决定镜头。'],'evidence_boundary':'合成测试素材，仍须人工审阅。',
                   'source_sha256':digest(source.encode()),'media_kind':'synthetic_fixture','sections':sections,'shots':shots}


def test_long_timeline_uses_measured_beats_and_separate_sections():
    source,value=long_data();timeline=validate_input(value,spec(source))
    assert len(value['sections'])==20 and len(timeline['shots'])==40
    assert timeline['total_frames']==11520 and timeline['time_base']=='1/24'
    assert [s['end_frame']-s['start_frame'] for s in timeline['shots'][:4]]==[192,264,312,384]
    assert all(a['end_frame']==b['start_frame'] for a,b in zip(timeline['shots'],timeline['shots'][1:]))
    assert timeline['shots'][0]['speech_start_sample']==6*2000


@pytest.mark.parametrize('mutation',[
    lambda v:v.update(causal_chain=[]),
    lambda v:v['sections'].extend(v['sections']),
    lambda v:v['shots'].extend(v['shots']*6),
    lambda v:v['shots'].pop(),
    lambda v:v['shots'][0].update(start_frame=1),
    lambda v:v['shots'][0].update(audio_samples=True),
    lambda v:v['shots'][0].update(audio_samples=9999999999),
    lambda v:v['shots'][0].update(lead_frames=-1),
    lambda v:v['shots'][0].update(tail_frames=0),
    lambda v:v['shots'][0].update(section_num=3),
    lambda v:v['shots'][0].update(shot_num=True),
    lambda v:v['shots'][0].update(narration='没有依据的收益增长99%'),
    lambda v:v['shots'][0].update(source_quotes=['原文没有的证据']),
    lambda v:v['shots'][0].update(audio_sha256='../../secret'),
    lambda v:v['sections'][0].update(narration='擅自改稿'),
    lambda v:v.update(source_sha256='0'*64),
])
def test_malformed_long_inputs_fail(mutation):
    source,value=long_data();mutation(value)
    with pytest.raises(ValueError):validate_input(value,spec(source))


@pytest.mark.parametrize('changes',[
    {'video_preset':'unknown'},{'video_duration_sec':True},{'video_duration_sec':601},
    {'video_duration_sec':999999},{'video_narration':False},{'video_voice':'melo'},
    {'planner_provider':'codex_cli'},{'video_preset':'legacy'},{'video_visual_mode':'live_action'},
])
def test_invalid_exec_specs_rejected(changes):
    with pytest.raises(ValueError):validate_video_spec({**spec('来源'),**changes})


def test_old_duration_boundaries_and_explicit_short_are_preserved():
    legacy={'generation_contract':'skill-video-v1','original_prompt_cn':'原文','video_duration_sec':60,
            'video_aspect_ratio':'16:9','planner_provider':'codex_cli'}
    assert validate_video_spec(legacy)==legacy
    with pytest.raises(ValueError):validate_video_spec({**legacy,'video_duration_sec':61})
    claude={**legacy,'generation_contract':'story-video-v2','planner_provider':'claude_cli','video_duration_sec':180}
    assert validate_video_spec(claude)==claude
    with pytest.raises(ValueError):validate_video_spec({**claude,'video_preset':'short'})
    with pytest.raises(ValueError):validate_video_spec({**claude,'video_duration_sec':480})
    assert validate_video_spec(spec('来源'))['video_duration_sec']==480
    assert validate_video_spec(spec('来源',600))['video_duration_sec']==600


def test_frame_rounding_cannot_hide_audio_overrun():
    source,value=long_data();value['shots'][0]['audio_samples']+=1
    with pytest.raises(ValueError,match='总时长'):validate_input(value,spec(source))
    # Sub-frame samples are rounded upward; a matching second beat absorbs only
    # its existing quantization fraction, never a truncated waveform.
    value['shots'][0]['audio_samples']-=2
    timeline=validate_input(value,spec(source))
    assert timeline['total_frames']==11520


def test_measured_beats_do_not_use_pre_synthesis_character_budget():
    source,value=long_data()
    # All narration and evidence stay intact. The measured takes occupy two
    # seconds each, exceeding four characters/sec without exceeding the clock.
    for shot in value['shots']:
        shot['audio_samples']=2*48000
    current=spec(source,110)
    timeline=validate_input(value,current)
    assert timeline['total_frames']==110*24
    assert all(len(s['narration']) > 2*4 for s in value['shots'])
    # Accepting density must not conceal an actual extra audio frame.
    value['shots'][0]['audio_samples']+=2000
    with pytest.raises(ValueError,match='总时长'):
        validate_input(value,current)


def test_registry_remeasures_audio_and_rejects_cross_account_and_symlink(tmp_path,monkeypatch):
    registry=tmp_path/'registry';source,input_id,value=build_fixture(registry,'a',6)
    monkeypatch.setenv('NBPPT_EXEC_PITCH_ROOT',str(registry));owner=digest(b'a')
    current=spec(source,6,input_id,owner)
    assert load_input(owner,input_id,current)[0]==value
    with pytest.raises(ValueError):load_input(digest(b'b'),input_id,current)
    bad=copy.deepcopy(value);bad['shots'][0]['audio_samples']+=2000;bad['shots'][1]['audio_samples']-=2000
    new_id=digest(canonical(bad));folder=registry/owner/new_id
    import shutil
    shutil.copytree(registry/owner/input_id,folder);(folder/'input.json').write_bytes(canonical(bad))
    with pytest.raises(ValueError,match='实测音频'):load_input(owner,new_id,{**current,'video_input_id':new_id})
    asset=registry/owner/input_id/'assets'/f"{value['shots'][0]['audio_sha256']}.wav"
    actual=asset.with_suffix('.backup');asset.rename(actual);asset.symlink_to(actual)
    with pytest.raises(ValueError,match='不安全'):load_input(owner,input_id,current)


@pytest.mark.parametrize('render_engine',['html_chromium','registered_video'])
def test_real_exec_failure_refund_retry_gateway_worker_and_delivery(manager,monkeypatch,tmp_path,render_engine):
    registry=tmp_path/'registry';source,input_id,_=build_fixture(registry,'a',6)
    monkeypatch.setenv('NBPPT_EXEC_PITCH_ROOT',str(registry))
    monkeypatch.setattr(worker_api,'WORKSPACE_JOBS_DIR',manager.jobs_root)
    secret='sandbox-'+'s'*40;monkeypatch.setattr(worker_api,'WORKER_SECRET',secret)
    monkeypatch.setattr(mcp_server,'get_runtime_settings',lambda:{'overseas_worker_url':'http://worker','overseas_worker_secret':secret})
    original=httpx.AsyncClient
    monkeypatch.setattr(mcp_server.httpx,'AsyncClient',lambda **kw:original(transport=httpx.ASGITransport(app=worker_api.app),**kw))
    preflight=video_subtitles.preflight_subtitles
    def broken():raise ValueError('test missing subtitle filter')
    monkeypatch.setattr(video_subtitles,'preflight_subtitles',broken)
    async def run():
        jobs=PresentationJobs(manager);monkeypatch.setattr(main,'mcp_jobs',jobs)
        principal=await authenticate_key(manager,KEY_A)
        kwargs={'task_type':'video','video_duration_sec':6,'video_voice':'approved_local',
                'video_visual_mode':'registered_local','video_preset':'exec_pitch','video_input_id':input_id,
                'video_render_engine':render_engine}
        with pytest.raises(PermissionError):await jobs.create({**principal,'scope':'read'},source,'auto',0,'read-denied',**kwargs)
        other=await authenticate_key(manager,KEY_B)
        with pytest.raises(ValueError):await jobs.create(other,source,'auto',0,'foreign-input',**kwargs)
        assert balance(manager)==(2000,0)
        first=await jobs.create(principal,source,'auto',0,'exec-failed-1',**kwargs)
        while jobs.tasks:await asyncio.gather(*list(jobs.tasks))
        assert (await jobs.status(principal,first['job_id']))['status']=='FAILED'
        assert balance(manager)==(2000,0)
        monkeypatch.setattr(video_subtitles,'preflight_subtitles',preflight)
        second=await jobs.retry(principal,first['job_id'],'exec-retry-2')
        assert (await jobs.create(principal,source,'auto',0,'exec-retry-2',**kwargs))['job_id']==second['job_id']
        while jobs.tasks:await asyncio.gather(*list(jobs.tasks))
        state=await jobs.status(principal,second['job_id'])
        assert state['status']=='COMPLETED',await manager.get_job(second['job_id'],'a')
        assert state['request']['video_preset']=='exec_pitch' and state['request']['video_input_id']==input_id
        assert state['request']['video_render_engine']==render_engine
        assert balance(manager)==(1944,0)
        with pytest.raises(ValueError,match='request_id已用于'):
            await jobs.create(principal,source,'auto',0,'exec-retry-2',**{**kwargs,'video_subtitles':False})
        artifacts=await jobs.artifacts(principal,second['job_id'])
        assert artifacts['content_status']=='NOT_REVIEWED' and artifacts['artifacts']['timeline_url']
        assert any(f['path']=='render_chunks.json' for f in artifacts['files'])==(render_engine=='html_chromium')
        qa=json.loads((manager.jobs_root/second['job_id']/'output/qa_report.json').read_text())
        assert qa['delivered_sections']==2 and qa['delivered_shots']==2
        assert any('非人声' in check for check in qa['checks_cn'])
        with pytest.raises(ValueError):await jobs.create(principal,source+'新要求','auto',0,'exec-retry-2',**kwargs)
        async with original(transport=httpx.ASGITransport(app=main.app),base_url='http://test') as c:
            path=artifacts['artifacts']['mp4_url']
            assert (await c.get(path)).status_code==401
            assert (await c.get(path,headers={'Authorization':'Bearer '+KEY_B})).status_code==404
            assert (await c.get(path,headers={'Authorization':'Bearer '+KEY_A,'Range':'bytes=0-99'})).status_code==206
        output=manager.jobs_root/second['job_id']/'output'
        video=output/f"{second['job_id']}_video.mp4";saved=video.read_bytes()
        shifted=tmp_path/'shifted.mp4'
        subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(video),'-filter_complex',
                        '[0:a]adelay=500:all=1,atrim=duration=6[a]','-map','0:v','-map','[a]',
                        '-c:v','copy','-c:a','aac','-ar','48000',str(shifted)],check=True,timeout=30)
        video.write_bytes(shifted.read_bytes())
        with pytest.raises(ValueError,match='音频与登记节拍不一致'):
            await jobs.artifacts(principal,second['job_id'])
        video.write_bytes(saved)
        timeline=manager.jobs_root/second['job_id']/'output/timeline.json';timeline.write_text('{}')
        with pytest.raises(ValueError):await jobs.artifacts(principal,second['job_id'])
    asyncio.run(run())


def test_mcp_schema_and_real_admission_preserve_exec_input(manager,monkeypatch,tmp_path):
    registry=tmp_path/'registry';source,input_id,_=build_fixture(registry,'a',6)
    monkeypatch.setenv('NBPPT_EXEC_PITCH_ROOT',str(registry))
    original=mcp_server.MCPServer;captured=[]
    def capture(*args,**kwargs):
        server=original(*args,**kwargs);captured.append(server);return server
    monkeypatch.setattr(mcp_server,'MCPServer',capture)
    jobs=PresentationJobs(manager);calls=[]
    async def no_worker(job,args):calls.append(args)
    monkeypatch.setattr(jobs,'execute',no_worker)
    mcp_server.build_mcp(jobs);server=captured[0]
    async def run():
        principal=await authenticate_key(manager,KEY_A)
        context=SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(state=SimpleNamespace(principal=principal))))
        tool=next(t for t in await server.list_tools() if t.name=='create_video')
        properties=tool.input_schema['properties']
        assert properties['duration_seconds']['maximum']==600
        assert properties['preset']['enum']==['legacy','short','exec_pitch']
        args={'source':source,'request_id':'mcp-exec-001','duration_seconds':6,'preset':'exec_pitch',
              'input_id':input_id,'voice':'approved_local','visual_mode':'registered_local'}
        result=await server.call_tool('create_video',args,context=context)
        assert result.is_error is not True
        created=json.loads(result.content[0].text)
        assert created['status']=='RUNNING'
        while jobs.tasks:await asyncio.gather(*list(jobs.tasks))
        assert calls[0]['video_preset']=='exec_pitch' and calls[0]['video_input_id']==input_id
        assert calls[0]['video_input_owner']==digest(b'a')
        for invalid in ({'duration_seconds':True},{'preset':'bad'},{'duration_seconds':601}):
            with pytest.raises(Exception):await server.call_tool('create_video',{**args,**invalid},context=context)
        await manager.cancel_refund(created['job_id'],'No-worker schema/admission fixture complete')
        assert balance(manager)==(2000,0)
    asyncio.run(run())


def test_default_engine_is_persisted_and_pre_p1_retry_keeps_registered_video(manager,monkeypatch,tmp_path):
    registry=tmp_path/'registry';source,input_id,_=build_fixture(registry,'a',6)
    monkeypatch.setenv('NBPPT_EXEC_PITCH_ROOT',str(registry))
    calls=[];jobs=PresentationJobs(manager)
    async def fail(job,args):
        calls.append(args)
        await manager.cancel_refund(job,'Controlled failure without executing a browser')
    monkeypatch.setattr(jobs,'execute',fail)
    async def run():
        principal=await authenticate_key(manager,KEY_A)
        kwargs={'task_type':'video','video_duration_sec':6,'video_voice':'approved_local',
                'video_visual_mode':'registered_local','video_preset':'exec_pitch','video_input_id':input_id}
        first=await jobs.create(principal,source,'auto',0,'default-engine-001',**kwargs)
        while jobs.tasks:await asyncio.gather(*list(jobs.tasks))
        assert calls[-1]['video_render_engine']=='html_chromium'
        repeated=await jobs.create(principal,source,'auto',0,'default-engine-001',**kwargs)
        assert repeated['job_id']==first['job_id']
        retried=await jobs.retry(principal,first['job_id'],'default-retry-002')
        while jobs.tasks:await asyncio.gather(*list(jobs.tasks))
        assert calls[-1]['video_render_engine']=='html_chromium'
        # Reproduce the original P0 persisted shape: no engine key anywhere.
        original=json.loads((await manager.get_job(first['job_id'],'a'))['en_compiled_spec'])
        original['_request'].pop('video_render_engine',None)
        await manager.save_compiled_spec(first['job_id'],original)
        await jobs.retry(principal,first['job_id'],'historical-retry-003')
        while jobs.tasks:await asyncio.gather(*list(jobs.tasks))
        assert calls[-1]['video_render_engine']=='registered_video' and balance(manager)==(2000,0)
    asyncio.run(run())
