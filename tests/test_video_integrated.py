"""Exercise actual worker media processes, gateway settlement and authenticated downloads.

Only the planner is replayed: generation, captioning, QA, billing and downloads are real.
"""
import asyncio
import hashlib
import json
import os
import sys

import httpx
import pytest

from gateway import main, mcp_server
from gateway.auth import authenticate_key
from gateway.mcp_server import PresentationJobs
from worker import worker_api, video_generation, video_subtitles
from test_security_delivery import manager, KEY_A, KEY_B, balance
from test_video_generation import SOURCE, plan


@pytest.mark.parametrize('with_voice', [
    pytest.param(True, marks=pytest.mark.skipif(not os.environ.get('NBPPT_KOKORO_MODEL_DIR'),
                                             reason='optional voice integration runtime required')),
    False,
])
def test_real_media_failure_refund_retry_download_and_voice(manager, monkeypatch, tmp_path, with_voice):
    monkeypatch.setenv('NBPPT_KOKORO_ENABLED', 'true')
    monkeypatch.setattr(worker_api, 'WORKSPACE_JOBS_DIR', manager.jobs_root)
    secret = 'local-worker-test-' + 'x' * 40
    monkeypatch.setattr(worker_api, 'WORKER_SECRET', secret)
    story = plan()
    for scene in story['scenes']:
        scene['narration'] = '讲清事实' if scene['scene_num'] == 1 else '收益仍需验证'
    planner = tmp_path / 'planner.py'
    planner.write_text('from pathlib import Path\nPath("video_plan.json").write_text(' + repr(json.dumps(story, ensure_ascii=False)) + ')\n')
    monkeypatch.setattr(video_generation, '_planner_command', lambda *args: [sys.executable, str(planner)])
    monkeypatch.setattr(mcp_server, 'get_runtime_settings', lambda: {'overseas_worker_url':'http://worker','overseas_worker_secret':secret})
    original_client = httpx.AsyncClient
    def worker_client(**kwargs):
        return original_client(transport=httpx.ASGITransport(app=worker_api.app), **kwargs)
    monkeypatch.setattr(mcp_server.httpx, 'AsyncClient', worker_client)
    preflight = video_subtitles.preflight_subtitles
    def broken():
        raise video_subtitles.SubtitleBurnError('test missing subtitle filter')
    monkeypatch.setattr(video_subtitles, 'preflight_subtitles', broken)

    async def run():
        jobs = PresentationJobs(manager)
        principal = await authenticate_key(manager, KEY_A)
        first = await jobs.create(principal, SOURCE, 'auto', 0, 'integrated-failure-1',
                                  'video', 6, '9:16', 'kokoro_female', with_voice, True)
        while jobs.tasks:
            await asyncio.gather(*list(jobs.tasks))
        assert (await jobs.status(principal, first['job_id']))['status'] == 'FAILED'
        assert balance(manager) == (2000, 0)
        assert not (manager.jobs_root / first['job_id'] / 'output').exists()
        monkeypatch.setattr(video_subtitles, 'preflight_subtitles', preflight)
        second = await jobs.retry(principal, first['job_id'], 'integrated-retry-2')
        while jobs.tasks:
            await asyncio.gather(*list(jobs.tasks))
        state = await jobs.status(principal, second['job_id'])
        assert state['status'] == 'COMPLETED', state
        assert balance(manager)[1] == 0 and balance(manager)[0] < 2000
        artifact = await jobs.artifacts(principal, second['job_id'])
        if with_voice:
            assert artifact['video']['narration']['voice'] == 'kokoro_female'
        else:
            assert artifact['video']['audio'] is False
            assert artifact['video']['narration']['status'] == 'disabled'
        assert artifact['video']['subtitles_burned'] is True
        path = artifact['artifacts']['mp4_url']
        async with original_client(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as c:
            assert (await c.get(path)).status_code == 401
            assert (await c.get(path, headers={'Authorization':'Bearer '+KEY_B})).status_code == 404
            response = await c.get(path, headers={'Authorization':'Bearer '+KEY_A})
            assert response.status_code == 200
            receipt = next(f for f in artifact['files'] if f['path'].endswith('.mp4'))
            assert hashlib.sha256(response.content).hexdigest() == receipt['sha256']
            partial = await c.get(path, headers={'Authorization':'Bearer '+KEY_A,'Range':'bytes=0-1023'})
            assert partial.status_code == 206 and len(partial.content) == 1024
    asyncio.run(run())
