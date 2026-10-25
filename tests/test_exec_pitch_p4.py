"""P4 acoustic timing, frame evidence and fail-closed publication/refund."""
import asyncio
import copy
import json
import shutil
import subprocess
import wave

import httpx
import numpy as np
import pytest

from gateway import main,mcp_server
from gateway.auth import authenticate_key
from gateway.exec_pitch_contract import canonical,digest,validate_input
from gateway.exec_pitch_inputs import load_input
from gateway.word_alignment import load_alignment,spoken,aligned_cues,verify_words
from gateway.frame_qa import client_rules,verify_p4_report,inspect_frames
from gateway.mcp_server import PresentationJobs
from test_exec_pitch import spec
from test_security_delivery import manager,KEY_A,balance
from tools.exec_pitch_fixture import build_fixture
from worker import worker_api


def fixture(registry,user):
    source,old,value=build_fixture(registry,user,6);owner=digest(user.encode());oldroot=registry/owner/old
    records=[]
    for s in value['shots']:
        # Deterministic, nonperiodic, band-limited synthetic audio makes delay
        # measurement unambiguous; this is explicitly NOT real spoken evidence.
        rng=np.random.default_rng(s['shot_num']);x=rng.normal(0,.05,s['audio_samples'])
        x=np.convolve(x,np.ones(7)/7,'same');data=(x*32767).astype('<i2').tobytes()
        path=oldroot/'assets'/'new.wav'
        with wave.open(str(path),'wb') as w:
            w.setnchannels(1);w.setsampwidth(2);w.setframerate(48000);w.writeframes(data)
        h=digest(path.read_bytes());path.rename(oldroot/'assets'/f'{h}.wav');s['audio_sha256']=h
        records.append({'shot_num':s['shot_num'],'audio_sha256':h,'narration_sha256':digest(s['narration'].encode()),
            'units':[{'text':c,'start_sample':(2+2*i)*3840,'end_sample':(4+2*i)*3840} for i,c in enumerate(spoken(s['narration']))]})
    a={'version':1,'owner':owner,'source_sha256':value['source_sha256'],
       'engine':{'name':'qwen3-forced-aligner-mlx','version':'0.5.9','model_manifest_sha256':'a'*64,
                 'quantum_ms':80,'timestamp_repair':'disabled_no_interpolation','record_type':'test_fixture'},'shots':records}
    key=digest(canonical(a));value['voice_mix']={'profile':'exec_pitch_p3','music':'none','input_audio':'dry_dialogue'}
    value['quality']={'profile':'exec_pitch_p4','alignment_sha256':key,'client_rules_sha256':None}
    identity=digest(canonical(value));root=registry/owner/identity;shutil.copytree(oldroot,root)
    (root/'input.json').write_bytes(canonical(value));(root/'evidence').mkdir();(root/'evidence'/f'{key}.json').write_bytes(canonical(a))
    return source,identity,value,a,root


@pytest.fixture
def p4(tmp_path,monkeypatch):
    registry=tmp_path/'registry';source,identity,value,a,root=fixture(registry,'a')
    monkeypatch.setenv('NBPPT_EXEC_PITCH_ROOT',str(registry));s=spec(source,6,identity,digest(b'a'))
    timeline=validate_input(value,s)
    return value,a,root,s,timeline


def test_alignment_is_audio_owner_text_bound_and_not_proportional(p4):
    v,a,root,s,t=p4
    assert load_alignment(v,s,t,root)==a
    c=aligned_cues(v,t,a)[0]
    expected=t['shots'][0]['speech_start_sample']+a['shots'][0]['units'][0]['start_sample']
    assert 0<=expected-c['start_frame']*2000<2000
    assert c['text']==v['shots'][0]['narration']
    for mutate in (lambda x:x.update(owner='a'*64),lambda x:x['shots'][0].update(audio_sha256='b'*64),
                   lambda x:x.update(version=True),lambda x:x['shots'][0].update(shot_num=True),
                   lambda x:x['shots'][0]['units'][0].update(start_sample=-3840),
                   lambda x:x['shots'][0]['units'].pop(),lambda x:x['engine'].update(timestamp_repair='interpolate'),
                   lambda x:x['engine'].update(record_type='model_output')):
        bad=copy.deepcopy(a);mutate(bad);key=digest(canonical(bad));q=copy.deepcopy(v);q['quality']['alignment_sha256']=key
        (root/'evidence'/f'{key}.json').write_bytes(canonical(bad))
        with pytest.raises(ValueError):load_alignment(q,s,t,root)


def test_missing_or_uncertain_client_evidence_never_passes(p4):
    v,a,root,s,t=p4
    assert client_rules(v,s,root)['status']=='UNAVAILABLE'
    rule={'record_type':'test_fixture','owner':s['video_input_owner'],'source_sha256':v['source_sha256'],
          'reviewer':'unit test fixture only','approved_at':'2020-01-01T00:00:00+00:00','expires_at':'2099-01-01T00:00:00+00:00',
          'brand':'测试','forbidden_terms':['车间2.0'],'required_terms':[]}
    def register():
        key=digest(canonical(rule));(root/'evidence'/f'{key}.json').write_bytes(canonical(rule));v['quality']['client_rules_sha256']=key
    register();assert client_rules(v,s,root)['status']=='NEEDS_REVIEW'
    v['title']='车间2.0';assert client_rules(v,s,root)['status']=='FAILED'
    rule['record_type']='human_record';register()
    with pytest.raises(ValueError):client_rules(v,s,root)


@pytest.mark.parametrize(('color','message'),[('black','黑帧'),('green','冻结')])
def test_final_frame_gate_rejects_actual_black_or_frozen_encoding(p4,tmp_path,color,message):
    v,a,root,s,t=p4;video=tmp_path/'bad.mp4'
    subprocess.run(['ffmpeg','-v','error','-nostdin','-f','lavfi','-i',
        f'color=c={color}:s=1280x720:r=24:d=6','-an','-c:v','libx264','-threads','2',str(video)],check=True,timeout=30)
    with pytest.raises(ValueError,match=message):inspect_frames(video,{**s,'exec_pitch_timeline':t},tmp_path)


def test_frame_work_directory_cannot_escape_through_symlink(p4,tmp_path):
    v,a,root,s,t=p4;job=tmp_path/'job';job.mkdir();staging=job/'staging';staging.mkdir()
    elsewhere=tmp_path/'elsewhere';elsewhere.mkdir();(job/'frame-qa').symlink_to(elsewhere,target_is_directory=True)
    with pytest.raises(ValueError,match='不安全'):inspect_frames(tmp_path/'absent.mp4',{**s,'exec_pitch_timeline':t},staging)
    assert list(elsewhere.iterdir())==[]
    (job/'frame-qa').unlink();(job/'frame-qa').mkdir()
    (job/'frame-qa/contact-sheet.png').symlink_to(elsewhere/'should-not-be-written.png')
    with pytest.raises(ValueError,match='不安全'):inspect_frames(tmp_path/'absent.mp4',{**s,'exec_pitch_timeline':t},staging)
    assert list(elsewhere.iterdir())==[]


def test_real_p4_worker_blocks_missing_rules_refunds_and_rejects_shift(manager,monkeypatch,tmp_path):
    registry=tmp_path/'registered';source,identity,v,a,root=fixture(registry,'a')
    monkeypatch.setenv('NBPPT_EXEC_PITCH_ROOT',str(registry));monkeypatch.setattr(worker_api,'WORKSPACE_JOBS_DIR',manager.jobs_root)
    secret='p4-fixture-'+'s'*40;monkeypatch.setattr(worker_api,'WORKER_SECRET',secret)
    monkeypatch.setattr(mcp_server,'get_runtime_settings',lambda:{'overseas_worker_url':'http://worker','overseas_worker_secret':secret})
    original=httpx.AsyncClient
    monkeypatch.setattr(mcp_server.httpx,'AsyncClient',lambda **kw:original(transport=httpx.ASGITransport(app=worker_api.app),**kw))
    async def run():
        jobs=PresentationJobs(manager);principal=await authenticate_key(manager,KEY_A)
        created=await jobs.create(principal,source,'auto',0,'p4-real-refusal',task_type='video',video_duration_sec=6,
            video_voice='approved_local',video_visual_mode='registered_local',video_preset='exec_pitch',video_input_id=identity)
        while jobs.tasks:await asyncio.gather(*list(jobs.tasks))
        state=await jobs.status(principal,created['job_id']);assert state['status']=='FAILED'
        assert balance(manager)==(2000,0)
        folder=manager.jobs_root/created['job_id'];staging=folder/'staging'
        qa=json.loads((staging/'p4_qa.json').read_text())
        assert qa['FILE_OK']['status']=='PASSED' and qa['WORD_SYNC']['status']=='PASSED'
        assert qa['FRAME_QA_PASSED']['status']=='PASSED' and qa['CLIENT_RULES_PASSED']['status']=='UNAVAILABLE'
        assert qa['delivery_status']=='BLOCKED' and not (folder/'output').exists()
        with pytest.raises(ValueError):await jobs.artifacts(principal,created['job_id'])
        plan=json.loads((folder/'validated_video_plan.json').read_text())
        video=staging/f"{created['job_id']}_video.mp4";shift=folder/'shift.mp4'
        subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(video),'-filter_complex',
            '[0:a]adelay=125:all=1,atrim=duration=6[a]','-map','0:v','-map','[a]','-c:v','copy','-c:a','aac',str(shift)],check=True,timeout=30)
        with pytest.raises(ValueError,match='音轨错位'):
            verify_words(shift,v,plan['exec_pitch_timeline'],a,root)
        # A green claim cannot bypass an unavailable client verdict.
        qa['delivery_status']='PASSED'
        for k in ('WORD_SYNC','FRAME_QA_PASSED','CLIENT_RULES_PASSED'):qa[k]['status']='PASSED'
        (staging/'p4_qa.json').write_text(json.dumps(qa))
        with pytest.raises(ValueError):verify_p4_report(created['job_id'],plan,staging)
        await jobs.close()
    asyncio.run(run())
