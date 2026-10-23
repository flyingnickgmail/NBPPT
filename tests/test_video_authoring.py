import asyncio
import copy
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from gateway import main
from gateway.mcp_server import PresentationJobs
from gateway.auth import authenticate_key
from gateway.video_manuscript import validate_manuscript, validate_handoff, read_json_text
from worker.video_authoring import author_video, text_command
from worker.video_generation import generate_video_stream
from test_security_delivery import manager, KEY_A, KEY_B, balance

SOURCE='工单信息分散。系统汇总工单。由顾问确认交车。不能自动承诺交车时间。'


def spec():
    return {'generation_contract':'story-video-v2','planner_provider':'claude_cli',
            'original_prompt_cn':SOURCE,'video_duration_sec':24,'video_aspect_ratio':'9:16',
            'video_narration':False,'video_subtitles':False,'account_owner_user_id':'runtime-owner'}


def manuscript():
    return {'title':'交车之前','audience':'售后负责人','purpose':'决定试点','thesis':'先统一信息再确认承诺',
            'causal_chain':['信息分散导致确认困难','汇总后由顾问确认'],
            'evidence_boundary':'原文说明流程，未提供收益数据。',
            'sections':[{'scene_num':1,'duration_sec':8,'argument':'信息分散，难以统一判断。',
                'narration':'工单信息分散，顾问难以确认。','subtitle':'工单信息分散，顾问难以确认。','source_quotes':['工单信息分散。']},
                {'scene_num':2,'duration_sec':8,'argument':'统一工单，让顾问判断。',
                 'narration':'系统汇总工单，顾问确认交车。','subtitle':'系统汇总工单，顾问确认交车。','source_quotes':['系统汇总工单。','由顾问确认交车。']},
                {'scene_num':3,'duration_sec':8,'argument':'人仍对客户承诺负责。',
                 'narration':'不能自动承诺交车时间。','subtitle':'不能自动承诺交车时间。','source_quotes':['不能自动承诺交车时间。']}]}


def storyboard():
    m=manuscript()
    return {'task_summary_cn':'交车之前','story':{'subject':'工单','goal':'确认交车','question':'谁来确认承诺','visual':'document'},
            'scenes':[{**{k:s[k] for k in ['scene_num','duration_sec','narration','source_quotes']},
                       'title':['信息分散','汇总判断','由人承诺'][i], 'body':s['argument'],
                       'items':[['预约','维修'],['工单','状态'],['系统','顾问']][i],
                       'role':['hook','mechanism','resolution'][i], 'layout':['scatter','gather','resolve'][i],
                       'state_before':['信息分散','等待判断','尚未确认'][i],
                       'state_after':['发现问题','统一状态','顾问确认'][i]} for i,s in enumerate(m['sections'])]}


@pytest.mark.parametrize('defect',['number','quote','boundary','duration','script','subtitle','repeat','extra'])
def test_bad_manuscripts_fail(defect):
    m=manuscript()
    if defect=='number': m['sections'][0]['argument']='收益增长90%'
    if defect=='quote': m['sections'][0]['source_quotes']=['原文没有']
    if defect=='boundary': m['sections'][-1]['narration']=m['sections'][-1]['subtitle']='系统会确认交车。'
    if defect=='duration': m['sections'][0]['duration_sec']=9
    if defect=='script': m['sections'][0]['narration']='<script>'
    if defect=='subtitle': m['sections'][0]['subtitle']='另一份事实'
    if defect=='repeat': m['sections'][1]['narration']=m['sections'][1]['subtitle']=m['sections'][0]['narration']
    if defect=='extra': m['run_command']='bad'
    with pytest.raises(ValueError): validate_manuscript(m,spec())


@pytest.mark.parametrize('field',['narration','source_quotes','duration_sec'])
def test_storyboard_cannot_rewrite_approved_content(field):
    plan=storyboard()
    if field=='narration': plan['scenes'][0][field]='这是另一段口播。'
    if field=='source_quotes': plan['scenes'][0][field]=['系统汇总工单。']
    if field=='duration_sec': plan['scenes'][0][field]=7;plan['scenes'][1][field]=9
    with pytest.raises(ValueError): validate_handoff(manuscript(),plan,spec())


def test_strict_json_and_tool_free_cli():
    with pytest.raises(ValueError): read_json_text('{"scenes":[],"scenes":[]}')
    with pytest.raises(ValueError): read_json_text('{"x":NaN}')
    cmd=text_command('/usr/bin/claude',.3)
    assert cmd[cmd.index('--tools')+1]==''
    assert '--no-session-persistence' in cmd and '--setting-sources' in cmd


def test_two_stage_real_contract_and_no_fallback(tmp_path,monkeypatch):
    monkeypatch.setenv('NBPPT_CLAUDE_ENABLED','true');monkeypatch.setenv('NBPPT_CLAUDE_OWNER_USER_ID','runtime-owner')
    called=[]
    async def turn(prompt,budget,job,name):
        called.append(name)
        assert 'untrusted' in prompt or 'untrusted' in prompt.lower()
        return (manuscript() if name=='content' else storyboard()),.01
    async def go():
        req=SimpleNamespace(english_spec=spec(),max_budget_usd=.5)
        updates=[json.loads(x[6:]) async for x in author_video(req,tmp_path,'unused',asyncio.Semaphore(1),turn_runner=turn)]
        assert called==['content','storyboard']
        assert updates[-1]['type']=='authored'
        assert json.loads((tmp_path/'manuscript.json').read_text())==manuscript()
    asyncio.run(go())


def test_invalid_content_never_calls_storyboard(tmp_path,monkeypatch):
    monkeypatch.setenv('NBPPT_CLAUDE_ENABLED','true');monkeypatch.setenv('NBPPT_CLAUDE_OWNER_USER_ID','runtime-owner')
    calls=[]
    async def turn(*args):
        calls.append(args[-1]);m=manuscript();m['sections'][0]['source_quotes']=['伪造'];return m,.01
    async def go():
        req=SimpleNamespace(english_spec=spec(),max_budget_usd=.5)
        with pytest.raises(ValueError):
            async for _ in author_video(req,tmp_path,'unused',asyncio.Semaphore(1),turn_runner=turn): pass
        assert calls==['content','content_repair'] and not (tmp_path/'video_plan.json').exists()
    asyncio.run(go())


def test_claude_video_authorization_refund_and_retry(manager,monkeypatch):
    monkeypatch.setenv('NBPPT_CLAUDE_ENABLED','true');monkeypatch.setenv('NBPPT_CLAUDE_OWNER_USER_ID','runtime-owner')
    async def go():
        jobs=PresentationJobs(manager)
        a=await authenticate_key(manager,KEY_A);b=await authenticate_key(manager,KEY_B)
        with pytest.raises(PermissionError):
            await jobs.create(b,SOURCE,'auto',0,'video-denied-001','video',24,'9:16',video_narration=False,execution_mode='claude_cli')
        assert balance(manager)==(2000,0)
        async def ready(*args): pass
        monkeypatch.setattr(jobs,'require_claude_ready',ready)
        async def fail(job,args):
            await manager.save_compiled_spec(job,{'_request':{k:v for k,v in args.items() if k!='account_owner_user_id'}})
            await manager.cancel_refund(job,'controlled failure')
        monkeypatch.setattr(jobs,'execute',fail)
        first=await jobs.create(a,SOURCE,'auto',0,'video-author-001','video',24,'9:16',video_narration=False,execution_mode='claude_cli')
        while jobs.tasks: await asyncio.gather(*list(jobs.tasks))
        assert (await jobs.status(a,first['job_id']))['status']=='FAILED'
        assert balance(manager)==(2000,0)
        new=await jobs.retry(a,first['job_id'],'video-retry-002')
        while jobs.tasks: await asyncio.gather(*list(jobs.tasks))
        args=json.loads((await manager.get_job(new['job_id'],'a'))['en_compiled_spec'])['_request']
        assert args['execution_mode']=='claude_cli' and args['video_aspect_ratio']=='9:16'
        with pytest.raises(ValueError): await jobs.status(b,new['job_id'])
        assert balance(manager)==(2000,0)
    asyncio.run(go())


def test_evidence_ids_keep_original_chinese_punctuation_and_reject_invalid_ids():
    from gateway.video_manuscript import bind_manuscript_evidence, bind_storyboard_evidence, source_catalog
    source='照片分散，反复核对。系统汇总。'
    raw={'sections':[{'source_quote_ids':[1]}]}
    assert bind_manuscript_evidence(raw,source)['sections'][0]['source_quotes']==['照片分散，反复核对。']
    for ids in [[True],[0],[3],[],['1']]:
        with pytest.raises(ValueError): bind_manuscript_evidence({'sections':[{'source_quote_ids':ids}]},source)
    m=manuscript();plan=storyboard()
    for scene in plan['scenes']:
        scene.pop('source_quotes');scene['source_section']=scene['scene_num']
    assert bind_storyboard_evidence(plan,m)==storyboard()
    plan['scenes'][0]['source_section']=2
    with pytest.raises(ValueError): bind_storyboard_evidence(plan,m)


def test_one_content_repair_preserves_budget_and_approved_handoff(tmp_path,monkeypatch):
    monkeypatch.setenv('NBPPT_CLAUDE_ENABLED','true');monkeypatch.setenv('NBPPT_CLAUDE_OWNER_USER_ID','runtime-owner')
    calls=[]
    async def turn(prompt,budget,job,name):
        calls.append((name,budget))
        if name=='content':
            m=manuscript();m['sections'][0]['argument']='收益提高90%';return m,.02
        if name=='content_repair': return manuscript(),.02
        return storyboard(),.02
    async def go():
        req=SimpleNamespace(english_spec=spec(),max_budget_usd=.5)
        updates=[json.loads(x[6:]) async for x in author_video(req,tmp_path,'unused',asyncio.Semaphore(1),turn_runner=turn)]
        assert [x[0] for x in calls]==['content','content_repair','storyboard']
        assert calls[-1][1]==pytest.approx(.46)
        assert updates[-1]['cost_usd']==pytest.approx(.06)
    asyncio.run(go())


def test_provider_rejection_is_not_retried_as_a_draft_repair(tmp_path,monkeypatch):
    from gateway.ppt_contract import ProviderUnavailable
    monkeypatch.setenv('NBPPT_CLAUDE_ENABLED','true');monkeypatch.setenv('NBPPT_CLAUDE_OWNER_USER_ID','runtime-owner')
    calls=[];slot=asyncio.Semaphore(1)
    async def turn(*args):
        calls.append(args[-1]);raise ProviderUnavailable('blocked','auth failed')
    async def go():
        req=SimpleNamespace(english_spec=spec(),max_budget_usd=.5)
        with pytest.raises(ProviderUnavailable):
            async for _ in author_video(req,tmp_path,'unused',slot,turn_runner=turn):pass
        assert calls==['content'] and slot._value==1
    asyncio.run(go())


def test_measured_speech_redistributes_time_without_speeding_or_changing_text(tmp_path):
    from worker.video_speech import prepare_manuscript_audio
    from types import SimpleNamespace
    import numpy as np
    m=manuscript();s={**spec(),'video_voice':'microsoft_yunxi','video_narration':True}
    class Voice:
        def __init__(self):self.calls=0
        def generate(self,text,sid=0,speed=1):
            assert speed==1
            self.calls+=1
            seconds=8.1 if self.calls==1 else 2
            return SimpleNamespace(samples=np.full(round(seconds*24000),.1,dtype=np.float32),sample_rate=24000)
    engine=Voice();timed=prepare_manuscript_audio(tmp_path,s,m,engine)
    assert sum(x['duration_sec'] for x in timed['sections'])==24
    assert timed['sections'][0]['duration_sec']==9
    assert [x['narration'] for x in timed['sections']]==[x['narration'] for x in m['sections']]
    assert engine.calls==3
    assert len(list((tmp_path/'prepared-speech').glob('*.wav')))==3


def test_audio_longer_than_selected_film_is_rejected_without_truncation():
    from worker.video_speech import allocate_scene_seconds,SpeechError
    with pytest.raises(SpeechError,match='未加速或截断'):
        allocate_scene_seconds([3,3],[4,4],6,[3,3])
