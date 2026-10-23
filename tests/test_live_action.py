import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from gateway.video_contract import validate_video_plan,validate_video_spec
from gateway.live_action_contract import validate_sources
from worker.scene_assets import select_shots
from test_video_authoring import spec,storyboard
from test_security_delivery import manager


def live_plan():
    sp={**spec(),'video_visual_mode':'live_action'}
    p=storyboard()
    for i,s in enumerate(p['scenes']):
        s['shots']=[{'clip_id':f'clip-{i}-a','duration_sec':4,'reason':'按记录核对实物'},
                    {'clip_id':f'clip-{i}-b','duration_sec':4,'reason':'确认后的现场动作'}]
    return sp,p


@pytest.mark.parametrize('defect',['repeat','path','duration','sum','mostly_animation','extra','long_hold'])
def test_edit_failures_rejected(defect):
    sp,p=live_plan()
    if defect=='repeat':p['scenes'][1]['shots'][0]['clip_id']='clip-0-a'
    if defect=='path':p['scenes'][0]['shots'][0]['clip_id']='../../secret'
    if defect=='duration':p['scenes'][0]['shots'][0]['duration_sec']=True
    if defect=='sum':p['scenes'][0]['shots'][0]['duration_sec']=3
    if defect=='mostly_animation':
        for s in p['scenes']:s['shots'][0]['clip_id']='animation'
    if defect=='extra':p['scenes'][0]['shots'][0]['filter']='unsafe code'
    if defect=='long_hold':p['scenes'][0]['shots']=[{'clip_id':'clip0','duration_sec':8,'reason':'not a shot'}]
    with pytest.raises(ValueError):validate_video_plan(p,sp)


def test_valid_live_plan_keeps_approved_edits():
    sp,p=live_plan();assert validate_video_plan(p,sp)==p['scenes']
    p['scenes'][0]['shots'][0]['clip_id']='animation'
    assert validate_video_plan(p,sp)==p['scenes']


def test_long_form_only_with_authorized_claude_contract():
    sp={**spec(),'video_duration_sec':180}
    assert validate_video_spec(sp)==sp
    for bad in [181,True,0]:
        with pytest.raises(ValueError):validate_video_spec({**sp,'video_duration_sec':bad})
    with pytest.raises(ValueError):validate_video_spec({**sp,'planner_provider':'codex_cli'})


def test_catalog_rejects_overlap_missing_file_and_too_short():
    sp,p=live_plan()
    clips=[]
    for i,s in enumerate(p['scenes']):
        for j,x in enumerate(s['shots']):
            clips.append({'id':x['clip_id'],'file':f'{i}.mp4','start':j*4,'end':j*4+4,
                          'sha256':str(i)*64,'shot_size':'detail' if j else 'wide'})
    c={'clips':clips}
    assert len(select_shots(p['scenes'],c))==6
    c['clips'][1]['start']=0
    with pytest.raises(ValueError):select_shots(p['scenes'],c)


def test_independent_source_validation_binds_every_edit():
    sp,p=live_plan();sp['video_scenes']=p['scenes']
    rows=[]
    for i,s in enumerate(p['scenes']):
        for j,x in enumerate(s['shots']):
            rows.append({'id':x['clip_id'],'start':j*4,'duration_sec':4,'sha256':str(i)*64,
                'reason':x['reason'],'source_quote':s['source_quotes'][0],'reviewed':True,
                'shot_size':'wide' if j else 'detail','provider':'pexels','author':'作者',
                'source_url':f'https://www.pexels.com/video/reviewed-{i}/','license_url':'https://www.pexels.com/license/'})
    data={'usage':'illustration_only','clips':rows}
    assert validate_sources(data,sp)==rows
    for field,value in [('duration_sec',3),('reason','另一原因'),('source_quote','编造的引用'),('reviewed',False),('source_url','http://127.0.0.1/')]:
        bad=deepcopy(data);bad['clips'][0][field]=value
        with pytest.raises(ValueError):validate_sources(bad,sp)
    bad=deepcopy(data);bad['clips'].pop()
    with pytest.raises(ValueError):validate_sources(bad,sp)


def test_live_mode_cannot_silently_complete_without_catalog(tmp_path,monkeypatch):
    from worker.video_generation import generate_video_stream
    monkeypatch.setenv('NBPPT_SCENE_SOURCE','catalog');monkeypatch.setenv('NBPPT_SCENE_CATALOG','/nonexistent/catalog.json')
    req=SimpleNamespace(job_id='video_1234567890',english_spec={**spec(),'video_visual_mode':'live_action','video_narration':False,'video_subtitles':False})
    async def go():return [json.loads(v[6:]) async for v in generate_video_stream(req,tmp_path,'unused',asyncio.Semaphore(1))]
    updates=asyncio.run(go())
    assert updates[-1]['type']=='error' and not any(x['type']=='completed' for x in updates)
    assert not (tmp_path/req.job_id/'output').exists()


def test_renderer_frames_have_different_evidence_and_both_ratios():
    from worker.live_action_renderer import explanation_frame
    sp,p=live_plan()
    for w,h in [(1280,720),(720,1280)]:
        plan={'video_width':w,'video_height':h}
        a=explanation_frame(p['scenes'][0],plan,.15,0);b=explanation_frame(p['scenes'][0],plan,.9,0)
        assert a.size==(w,h) and a.tobytes()!=b.tobytes()


def test_original_music_ducks_without_moving_or_mutating_voice():
    import numpy as np
    from worker.video_music import mix_original_bed
    rate=2000;silence=np.zeros(rate*10,dtype=np.float32)
    voice=np.full(rate*10,.1,dtype=np.float32);original=voice.copy()
    quiet=mix_original_bed(silence,rate);mixed=mix_original_bed(voice,rate)
    assert np.array_equal(voice,original) and len(mixed)==len(voice)
    assert np.max(np.abs(quiet))>0
    middle=slice(rate*3,rate*7)
    assert np.sqrt(np.mean((mixed[middle]-voice[middle])**2))<np.sqrt(np.mean(quiet[middle]**2))*.3


def test_long_script_error_is_actionable():
    from gateway.video_manuscript import validate_manuscript
    from test_video_authoring import manuscript
    m=manuscript();m['sections'][0]['narration']=m['sections'][0]['subtitle']='文'*33
    with pytest.raises(ValueError,match=r'section\[1\].*max 24.*got 33'):
        validate_manuscript(m,spec())


def test_long_live_request_keeps_permissions_fingerprint_and_retry(manager,monkeypatch):
    import sqlite3
    from gateway.auth import authenticate_key
    from gateway.mcp_server import PresentationJobs
    from test_security_delivery import KEY_A,KEY_B,balance
    monkeypatch.setenv('NBPPT_CLAUDE_ENABLED','true');monkeypatch.setenv('NBPPT_CLAUDE_OWNER_USER_ID','runtime-owner')
    async def go():
        jobs=PresentationJobs(manager);seen=[]
        async def ready(*_):pass
        async def failed(job,args):
            seen.append(args);await manager.save_compiled_spec(job,{'_request':args})
            await manager.cancel_refund(job,'controlled source coverage failure')
        monkeypatch.setattr(jobs,'require_claude_ready',ready);monkeypatch.setattr(jobs,'execute',failed)
        a=await authenticate_key(manager,KEY_A);b=await authenticate_key(manager,KEY_B)
        kw={'task_type':'video','video_duration_sec':180,'video_visual_mode':'live_action','execution_mode':'claude_cli'}
        with pytest.raises(PermissionError):await jobs.create(b,'仓库协作','auto',0,'long-denied-001',**kw)
        assert balance(manager)==(2000,0)
        result=await jobs.create(a,'仓库协作','auto',0,'long-author-001',**kw)
        while jobs.tasks:await asyncio.gather(*list(jobs.tasks))
        assert balance(manager)==(2000,0)
        with pytest.raises(ValueError,match='request_id'):
            await jobs.create(a,'仓库协作','auto',0,'long-author-001',**{**kw,'video_visual_mode':'motion'})
        retried=await jobs.retry(a,result['job_id'],'long-retry-001')
        while jobs.tasks:await asyncio.gather(*list(jobs.tasks))
        assert retried['job_id']!=result['job_id']
        assert seen[-1]['video_visual_mode']=='live_action' and seen[-1]['video_duration_sec']==180
        assert balance(manager)==(2000,0)
    asyncio.run(go())


def test_cached_voice_cli_runs_outside_repo_with_clean_environment(tmp_path):
    """Real child process catches imports that in-process unit tests cannot cover."""
    import os,shutil,subprocess,sys
    import numpy as np
    from worker.video_speech import _write_pcm_wav
    if not shutil.which('ffmpeg'):pytest.skip('ffmpeg unavailable')
    job=tmp_path/'video_1234567890';(job/'staging').mkdir(parents=True);(job/'prepared-speech').mkdir()
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=black:s=1280x720:r=24:d=6',
                    '-c:v','libx264','-threads','2','-pix_fmt','yuv420p',str(job/'staging'/f'{job.name}_video.mp4')],check=True)
    records=[];scenes=[];rate=24000
    for i,text in enumerate(['先查记录。','再核实物。'],1):
        samples=(np.sin(np.arange(rate)/rate*2*np.pi*220)*.1).astype(np.float32)
        _write_pcm_wav(job/'prepared-speech'/f'{i:02}.wav',samples,rate)
        records.append({'scene_num':i,'narration':text,'sample_rate':rate,'speech_duration_sec':1})
        scenes.append({'scene_num':i,'duration_sec':3,'narration':text})
    (job/'speech_cache.json').write_text(json.dumps({'voice':'microsoft_yunxi','scenes':records}))
    (job/'validated_video_plan.json').write_text(json.dumps({'video_scenes':scenes,'video_voice':'microsoft_yunxi',
       'generation_contract':'story-video-v2','video_visual_mode':'live_action'}))
    entry=Path(__file__).resolve().parents[1]/'worker/video_speech.py'
    result=subprocess.run([sys.executable,str(entry),'--job-dir',str(job),'--job-id',job.name],
       cwd=tmp_path,env={'PATH':os.environ['PATH'],'LANG':'C.UTF-8'},capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stdout+result.stderr
    assert json.loads((job/'speech_result.json').read_text())['provider']=='microsoft_edge'


def test_footage_credits_are_not_reported_as_a_ppt_html_deck():
    from gateway.delivery import delivery_urls
    links=delivery_urls('video_1234567890',{'planned_slides':0,'files':[{'path':'footage_credits.html'},{'path':'footage_sources.json'}]})
    assert links['html_deck_url'] is None and links['footage_credits_url'].endswith('/footage_credits.html')
