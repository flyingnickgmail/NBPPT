"""Video admission, ownership, retry and billing must remain independent from PPT."""
import asyncio
import json
import sqlite3

import httpx
import pytest

from gateway import main
from gateway.mcp_server import PresentationJobs
from gateway.delivery import delivery_urls
from test_security_delivery import manager, KEY_A, KEY_B, make_delivery, balance


def test_independent_failure_refund_retry_and_ppt_delivery(manager, monkeypatch):
    async def scenario():
        jobs = PresentationJobs(manager)
        release = asyncio.Event()

        async def execute(job, args):
            await release.wait()
            if args.get('task_type') == 'video':
                await manager.cancel_refund(job, 'controlled video failure')
            else:
                spec, manifest = make_delivery(manager.jobs_root / job / 'output', job=job)
                spec['_request'] = args
                await manager.save_compiled_spec(job, spec)
                await manager.confirm_settle(job, .1, delivery_urls(job, manifest))

        monkeypatch.setattr(jobs, 'execute', execute)
        monkeypatch.setattr(main, 'mcp_jobs', jobs)
        headers = {'Authorization': 'Bearer ' + KEY_A}
        payload = {'source': '原文内容', 'request_id': 'paired-delivery-001', 'slide_count': 2}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='https://test') as client:
            ppt = (await client.post('/api/jobs', headers=headers, json=payload)).json()['job_id']
            video_args = {**payload, 'task_type': 'video', 'video_duration_sec': 12, 'video_aspect_ratio': '9:16'}
            first = await client.post('/api/jobs', headers=headers, json=video_args)
            assert first.status_code == 200
            video = first.json()['job_id']
            assert video.startswith('video_') and ppt.startswith('ppt_')
            assert balance(manager) == (1860, 140)
            assert (await client.post('/api/jobs', headers=headers, json=video_args)).json()['job_id'] == video
            assert (await client.post('/api/jobs', headers=headers, json={**video_args, 'video_duration_sec': 18})).status_code == 409
            assert (await client.get('/api/jobs/' + video, headers={'Authorization': 'Bearer ' + KEY_B})).status_code == 404
            release.set()
            while jobs.tasks:
                await asyncio.gather(*list(jobs.tasks))
            assert (await client.get('/api/jobs/' + ppt, headers=headers)).json()['status'] == 'COMPLETED'
            assert (await client.get('/api/jobs/' + video, headers=headers)).json()['status'] == 'FAILED'
            assert balance(manager) == (1958, 0)
            ready = (await client.get('/api/jobs/' + ppt + '/artifacts', headers=headers)).json()
            assert ready['artifacts']['pptx_url']
            assert (await client.get('/api/jobs/' + video + '/artifacts', headers=headers)).status_code == 409
            retried = await client.post('/api/jobs/' + video + '/retry', headers=headers, json={'request_id': 'retry-video-001'})
            assert retried.status_code == 200
            new_id = retried.json()['job_id']
            assert new_id.startswith('video_') and new_id != video
            while jobs.tasks:
                await asyncio.gather(*list(jobs.tasks))
            args = json.loads((await manager.get_job(new_id, 'a'))['en_compiled_spec'])['_request']
            assert args['video_duration_sec'] == 12 and args['video_aspect_ratio'] == '9:16'
            assert (await client.post('/api/jobs/' + video + '/retry', headers=headers,
                                      json={'request_id': 'retry-video-001'})).json()['job_id'] == new_id
            assert balance(manager) == (1958, 0)
            assert (await client.get('/api/jobs/' + ppt + '/artifacts', headers=headers)).json() == ready
        with sqlite3.connect(manager.db_path) as db:
            assert db.execute("SELECT count(*) FROM credit_ledger WHERE action='FREEZE'").fetchone()[0] == 3
            assert db.execute("SELECT count(*) FROM credit_ledger WHERE action='SETTLE'").fetchone()[0] == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('changes', [{'video_duration_sec': 0}, {'video_duration_sec': 61},
    {'video_duration_sec': True}, {'video_duration_sec': 6.5}, {'video_aspect_ratio': '1:1'}, {'task_type': 'composite'}])
def test_invalid_video_options_never_freeze(manager, changes):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='https://test') as client:
            r = await client.post('/api/jobs', headers={'Authorization': 'Bearer ' + KEY_A},
                json={'source': '原文', 'task_type': 'video', 'request_id': 'invalid-video-001', **changes})
            assert r.status_code == 422
            assert balance(manager) == (2000, 0)
    asyncio.run(scenario())


@pytest.mark.parametrize('defect', ['quote', 'number', 'template', 'duplicate', 'source', 'duration'])
def test_gateway_rejects_worker_completion_not_grounded_in_admitted_request(manager, monkeypatch, defect):
    from gateway import mcp_server
    async def scenario():
        jobs = PresentationJobs(manager)
        job = 'video_9999999999'
        source = '先讲现状，再讲流程。收益需要验证。'
        await manager.try_freeze_credits(KEY_A, job, 'video', source, 80)
        called = []
        async def settle(*args):
            called.append(args)
        monkeypatch.setattr(manager, 'confirm_settle', settle)
        class Stream:
            def __init__(self, spec): self.spec = spec
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def raise_for_status(self): pass
            async def aiter_lines(self):
                spec = {**self.spec, 'task_summary_cn': '内容汇报', 'video_scenes': [
                    {'scene_num': 1, 'duration_sec': 3, 'title': '现状', 'body': '先讲现状', 'narration': '说明现状',
                     'source_quotes': ['先讲现状'], 'layout': 'title', 'items': []},
                    {'scene_num': 2, 'duration_sec': 3, 'title': '流程', 'body': '收益需要验证', 'narration': '谨慎验证',
                     'source_quotes': ['收益需要验证'], 'layout': 'process', 'items': ['现状', '流程']} ]}
                if defect == 'quote': spec['video_scenes'][0]['source_quotes'] = ['不存在的原文']
                elif defect == 'number': spec['video_scenes'][0]['body'] = '收益增长90%'
                elif defect == 'template': spec['matched_template'] = {'template': {'id': 'wrong'}}
                elif defect == 'duplicate': spec['video_scenes'][1]['title'] = '现状'
                elif defect == 'source': spec['original_prompt_cn'] = '偷换原文'
                elif defect == 'duration': spec['video_scenes'][0]['duration_sec'] = 4
                yield 'data: ' + json.dumps({'type': 'completed', 'compiled_spec': spec,
                                            'total_cost_usd': .01, 'cdn_urls': {}})
        class Client:
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def stream(self, *args, **kwargs): return Stream(kwargs['json']['english_spec'])
        monkeypatch.setattr(mcp_server.httpx, 'AsyncClient', Client)
        await jobs.execute(job, {'source': source, 'template_id': 'auto', 'slide_count': 0,
                                'task_type': 'video', 'video_duration_sec': 6, 'video_aspect_ratio': '16:9'})
        assert not called
        assert (await manager.get_job(job, 'a'))['status'] == 'FAILED'
        assert balance(manager) == (2000, 0)
    asyncio.run(scenario())
