"""P5 trust boundaries, version invalidation and actual single-shot reuse."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest

from gateway import mcp_server
from gateway.auth import authenticate_key
from gateway.exec_pitch_contract import canonical, digest, validate_input
from gateway.exec_pitch_review import verdict, load_profile
from gateway.exec_pitch_revision import export_parent, load_parent, validate_revision
from gateway.mcp_server import PresentationJobs
from test_exec_pitch_p4 import fixture, p4
from test_security_delivery import manager, KEY_A, balance
from tools.exec_pitch_review import import_record
from worker import worker_api


def test_refined_alignment_requires_actual_prefix_pcm_and_stable_raw_probes(p4):
    import wave
    from gateway.word_alignment import load_alignment
    v,a,r,s,t=p4;old=v['quality']['alignment_sha256'];trials=[]
    refined=deepcopy(a);refined['version']=2
    for shot in refined['shots']:
        shot['inference_prefix_samples']=1920 if shot['shot_num']==1 else 0
        if shot['shot_num']!=1:continue
        with wave.open(str(r/'assets'/f"{shot['audio_sha256']}.wav"),'rb') as w:pcm=w.readframes(w.getnframes())
        for pad,shift in [(1920,-1920),(3840,0),(5760,1920)]:
            p=r/'probe.wav'
            with wave.open(str(p),'wb') as w:
                w.setnchannels(1);w.setsampwidth(2);w.setframerate(48000);w.writeframes(b'\0'*(pad*2)+pcm)
            key=digest(p.read_bytes());p.rename(r/'evidence'/f'{key}.wav')
            units=[{**u,'start_sample':u['start_sample']+shift,'end_sample':u['end_sample']+shift} for u in shot['units']]
            trials.append({'shot_num':1,'prefix_silence_samples':pad,'original_audio_sha256':shot['audio_sha256'],
                           'probe_audio_sha256':key,'units':units,'timestamp_repair':'disabled_no_interpolation'})
        shot['units']=trials[0]['units']
    evidence={'status':'MACHINE_RECHECK_NOT_HUMAN_APPROVAL','original_alignment_sha256':old,'trials':trials}
    h=digest(canonical(evidence));(r/'evidence'/f'{h}.json').write_bytes(canonical(evidence))
    refined['recheck']={'parent_alignment_sha256':old,'evidence_sha256':h}
    def register(a):
        key=digest(canonical(a));(r/'evidence'/f'{key}.json').write_bytes(canonical(a));v['quality']['alignment_sha256']=key
    register(refined);assert load_alignment(v,s,t,r)==refined
    bad=deepcopy(refined);bad['shots'][0]['units'][0]['start_sample']+=1920;register(bad)
    with pytest.raises(ValueError):load_alignment(v,s,t,r)
    register(refined)
    probe=r/'evidence'/f"{trials[0]['probe_audio_sha256']}.wav";probe.write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='摘要'):load_alignment(v,s,t,r)


def profile(v,s):
    return {'version':1,'previous_sha256':None,'owner':s['video_input_owner'],'source_sha256':v['source_sha256'],
        'client_id':'TEST-ONLY-NOT-A-CLIENT','record_type':'candidate','created_at':'2020-01-01T00:00:00+00:00',
        'expires_at':'2099-01-01T00:00:00+00:00','reviewer':'fixture-only','evidence_sha256':None,
        'brand':'测试卡','forbidden_terms':['车间2.0'],'required_terms':[],'disclosure':'external',
        'redact_ip':True,'require_product_assets':False,'number_policy':'literal_source_only'}


def review_store(tmp_path,monkeypatch,s):
    root=tmp_path/'reviews';root.mkdir()
    (root/'authority.json').write_text(json.dumps({s['video_input_owner']:{'rule_reviewers':['fixture-only'],
                                                     'final_visual_reviewers':['fixture-only']}}))
    monkeypatch.setenv('NBPPT_EXEC_REVIEW_ROOT',str(root))
    proof=tmp_path/'proof.txt';proof.write_text('Synthetic test fixture; NOT actual customer or human approval.')
    return root,proof


def test_rule_candidates_version_chain_and_text_scope(p4,tmp_path,monkeypatch):
    v,a,r,s,t=p4;root,proof=review_store(tmp_path,monkeypatch,s);p=profile(v,s)
    key=import_record(root,'profiles',p);v['governance']={'profile_sha256':key}
    # The forbidden string in metadata must not create a false film violation.
    assert verdict(v,s)['status']=='UNAVAILABLE'
    p2={**p,'version':2,'previous_sha256':key,'required_terms':[v['title']]}
    k2=import_record(root,'profiles',p2);v['governance']['profile_sha256']=k2
    assert load_profile(v,s)['version']==2
    v['shots'][0]['motion']={'layout':'title','headline':'车间2.0','labels':['测试','标签'],'focus':0}
    assert verdict(v,s)['status']=='FAILED'
    bad={**p2,'version':3,'previous_sha256':key}
    with pytest.raises(ValueError,match='父版本'):import_record(root,'profiles',bad)
    v['governance']['profile_sha256']=key
    with pytest.raises(ValueError):load_profile(v,{**s,'video_input_owner':'f'*64})
    p['version']=True
    with pytest.raises(ValueError):import_record(root,'profiles',p)


def test_final_review_bound_to_exact_film_rules_frames_and_authority(p4,tmp_path,monkeypatch):
    v,a,r,s,t=p4;root,proof=review_store(tmp_path,monkeypatch,s);p=profile(v,s)
    p.update(record_type='test_fixture',evidence_sha256=digest(proof.read_bytes()))
    key=import_record(root,'profiles',p,proof);v['governance']={'profile_sha256':key}
    video=tmp_path/'video.mp4';video.write_bytes(b'fixture bytes, not a media acceptance')
    frames={'samples':[{'frame':0,'sha256':'a'*64}]}
    assert verdict(v,s,video,frames)['status']=='NEEDS_REVIEW'
    receipt={'owner':s['video_input_owner'],'input_id':s['video_input_id'],'source_sha256':v['source_sha256'],
        'profile_sha256':key,'video_sha256':digest(video.read_bytes()),'samples_sha256':digest(canonical(frames['samples'])),
        'record_type':'test_fixture','reviewer':'fixture-only','evidence_sha256':digest(proof.read_bytes()),
        'created_at':p['created_at'],'expires_at':p['expires_at'],
        'scopes':{k:'PASSED' for k in ('brand','watermark','forbidden_terms','disclosure','redaction')}}
    import_record(root,'receipts',receipt,proof)
    assert verdict(v,s,video,frames)['status']=='PASSED'
    with pytest.raises(ValueError):verdict(v,{**s,'video_input_id':'b'*64},video,frames)
    with pytest.raises(ValueError):verdict(v,s,video,{'samples':[]})
    (root/'authority.json').write_text('{}')
    with pytest.raises(ValueError,match='权限'):verdict(v,s,video,frames)
    video.write_bytes(b'changed')
    assert verdict(v,s,video,frames)['status']=='NEEDS_REVIEW'
    with pytest.raises(ValueError):import_record(root,'receipts',receipt,proof)


def test_no_fixture_or_candidate_can_claim_actual_customer_review(p4,tmp_path,monkeypatch):
    v,a,r,s,t=p4;root,proof=review_store(tmp_path,monkeypatch,s);p=profile(v,s)
    p.update(record_type='test_fixture',evidence_sha256=digest(proof.read_bytes()))
    key=import_record(root,'profiles',p,proof);v['governance']={'profile_sha256':key}
    v['media_kind']='approved_local'
    with pytest.raises(ValueError,match='测试规则'):load_profile(v,s)
    p['record_type']='human_record';p['reviewer']='not-authorized'
    with pytest.raises(ValueError,match='权限'):import_record(root,'profiles',p,proof)
    p['reviewer']='fixture-only';p['evidence_sha256']='f'*64
    with pytest.raises(ValueError,match='摘要'):import_record(root,'profiles',p,proof)


def test_real_single_shot_revision_refuses_stale_qa_and_missing_customer_rules(manager,monkeypatch,tmp_path):
    registry=tmp_path/'registry';source,identity,v,a,r=fixture(registry,'a')
    monkeypatch.setenv('NBPPT_EXEC_PITCH_ROOT',str(registry));monkeypatch.setattr(worker_api,'WORKSPACE_JOBS_DIR',manager.jobs_root)
    secret='p5-fixture-'+'s'*40;monkeypatch.setattr(worker_api,'WORKER_SECRET',secret)
    monkeypatch.setattr(mcp_server,'get_runtime_settings',lambda:{'overseas_worker_url':'http://worker','overseas_worker_secret':secret})
    original=httpx.AsyncClient
    monkeypatch.setattr(mcp_server.httpx,'AsyncClient',lambda **kw:original(transport=httpx.ASGITransport(app=worker_api.app),**kw))
    cache=tmp_path/'cache';cache.mkdir();monkeypatch.setenv('NBPPT_EXEC_REVISION_ROOT',str(cache))
    from test_exec_pitch import spec
    s=spec(source,6,identity,digest(b'a'));reviews,proof=review_store(tmp_path,monkeypatch,s)
    async def run():
        jobs=PresentationJobs(manager);principal=await authenticate_key(manager,KEY_A)
        async def create(key,request,expected='FAILED'):
            created=await jobs.create(principal,source,'auto',0,request,task_type='video',video_duration_sec=6,
                video_voice='approved_local',video_visual_mode='registered_local',video_preset='exec_pitch',video_input_id=key)
            while jobs.tasks:await asyncio.gather(*list(jobs.tasks))
            state=await jobs.status(principal,created['job_id']);assert state['status']==expected
            if expected=='FAILED':assert balance(manager)==(2000,0)
            folder=manager.jobs_root/created['job_id'];return created,folder
        first,parent=await create(identity,'p5-parent')
        plan=json.loads((parent/'validated_video_plan.json').read_text());before=digest((parent/'staging'/f'{parent.name}_video.mp4').read_bytes())
        key=export_parent(parent,plan,cache)
        new=deepcopy(v);new['shots'][0]['motion']={'layout':'comparison','headline':'输入核对','labels':['来源','交付'],'focus':1}
        new['revision']={'parent_input_id':identity,'parent_job_id':parent.name,'manifest_sha256':key,'operation':'replace_opening','shot_num':1}
        new['governance']={'profile_sha256':import_record(reviews,'profiles',profile(new,s))}
        import shutil
        new_id=digest(canonical(new));dest=registry/s['video_input_owner']/new_id;shutil.copytree(r,dest);(dest/'input.json').write_bytes(canonical(new))
        bad=deepcopy(new);bad['shots'][1]['reason']='暗改其他镜头'
        with pytest.raises(ValueError,match='单镜'):load_parent(bad,plan)
        with pytest.raises(ValueError):load_parent(new,{**plan,'video_input_owner':'f'*64})
        malformed=deepcopy(new);malformed['revision']['shot_num']=True
        with pytest.raises(ValueError):validate_revision(malformed)
        second,folder=await create(new_id,'p5-revised')
        qa=json.loads((folder/'staging/p4_qa.json').read_text());receipt=json.loads((folder/'staging/revision.json').read_text())
        assert qa['FILE_OK']['status']=='PASSED' and qa['FRAME_QA_PASSED']['status']=='PASSED'
        assert qa['WORD_SYNC']['status']=='PASSED' and qa['CLIENT_RULES_PASSED']['status']=='UNAVAILABLE'
        assert qa['REVISION_INTEGRITY']['status']=='PASSED'
        assert receipt['reused_shots']==[2] and receipt['rendered_shots']==[1] and receipt['qa_reused'] is False
        assert receipt['audio_reused_by_hash']==[1,2]
        assert not (folder/'output').exists() and digest((parent/'staging'/f'{parent.name}_video.mp4').read_bytes())==before
        # Exercise the positive policy ONLY with visibly synthetic media and
        # fixture approvals; this grants nothing to the actual Chinese film.
        candidate=profile(new,s);candidate_key=new['governance']['profile_sha256']
        approved={**candidate,'version':2,'previous_sha256':candidate_key,'record_type':'test_fixture',
                  'evidence_sha256':digest(proof.read_bytes())}
        approved_key=import_record(reviews,'profiles',approved,proof)
        reviewed=deepcopy(new);reviewed['governance']['profile_sha256']=approved_key
        reviewed_id=digest(canonical(reviewed));target=registry/s['video_input_owner']/reviewed_id
        shutil.copytree(dest,target);(target/'input.json').write_bytes(canonical(reviewed))
        third,pending=await create(reviewed_id,'p5-fixture-pending')
        q=json.loads((pending/'staging/p4_qa.json').read_text())
        assert q['CLIENT_RULES_PASSED']['status']=='NEEDS_REVIEW'
        actual_receipt={'owner':s['video_input_owner'],'input_id':reviewed_id,'source_sha256':new['source_sha256'],
            'profile_sha256':approved_key,'video_sha256':q['video_sha256'],
            'samples_sha256':digest(canonical(q['FRAME_QA_PASSED']['samples'])),'record_type':'test_fixture',
            'reviewer':'fixture-only','evidence_sha256':digest(proof.read_bytes()),
            'created_at':approved['created_at'],'expires_at':approved['expires_at'],
            'scopes':{k:'PASSED' for k in ('brand','watermark','forbidden_terms','disclosure','redaction')}}
        import_record(reviews,'receipts',actual_receipt,proof)
        fourth,complete=await create(reviewed_id,'p5-fixture-with-exact-review','COMPLETED')
        assert (complete/'output').is_dir()
        artifacts=await jobs.artifacts(principal,fourth['job_id'])
        assert artifacts['content_status']=='NOT_REVIEWED'
        assert balance(manager)[1]==0
        cached=cache/s['video_input_owner']/parent.name/'chunk-0001.mp4'
        cached.write_bytes(b'corrupted')
        from gateway.exec_pitch_revision import prepare_reuse
        work=tmp_path/'reuse-work';work.mkdir()
        newplan=json.loads((folder/'validated_video_plan.json').read_text())
        with pytest.raises(ValueError,match='摘要'):prepare_reuse(new,newplan,newplan['exec_pitch_timeline'],work)
        await jobs.close()
    asyncio.run(run())
