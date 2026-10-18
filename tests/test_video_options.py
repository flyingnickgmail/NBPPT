import asyncio
import json
import os
import subprocess
from pathlib import Path

import httpx
import pytest

from gateway import main
from gateway.mcp_server import PresentationJobs
from gateway.video_contract import validate_video_spec
from test_security_delivery import manager, KEY_A, balance
from test_video_generation import spec
from test_video_speech import plan
from worker.video_renderer import render_video
from worker.video_speech import SpeechError, trusted_model_dir


def test_disabled_voice_rejected_before_reservation(manager, monkeypatch):
    monkeypatch.delenv('NBPPT_KOKORO_ENABLED', raising=False)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='https://test') as c:
            r = await c.post('/api/jobs', headers={'Authorization': 'Bearer ' + KEY_A}, json={
                'source': '完整原文', 'task_type': 'video', 'request_id': 'voice-not-enabled', 'video_voice': 'kokoro_female'})
            assert r.status_code == 422
            assert balance(manager) == (2000, 0)
    asyncio.run(run())


def test_voice_options_bound_to_idempotency_and_preserved_on_retry(manager, monkeypatch):
    monkeypatch.setenv('NBPPT_KOKORO_ENABLED', 'true')
    async def run():
        jobs = PresentationJobs(manager)
        captured = []
        async def fail(job, args):
            captured.append(args)
            await manager.cancel_refund(job, 'test failure')
        monkeypatch.setattr(jobs, 'execute', fail)
        from gateway.auth import authenticate_key
        principal = await authenticate_key(manager, KEY_A)
        first = await jobs.create(principal, '完整原文', 'auto', 0, 'voice-option-001',
                                  'video', 15, '9:16', 'kokoro_male', True, False)
        await asyncio.gather(*list(jobs.tasks))
        with pytest.raises(ValueError, match='request_id'):
            await jobs.create(principal, '完整原文', 'auto', 0, 'voice-option-001',
                              'video', 15, '9:16', 'kokoro_female', True, False)
        retried = await jobs.retry(principal, first['job_id'], 'voice-option-002')
        await asyncio.gather(*list(jobs.tasks))
        assert retried['job_id'] != first['job_id']
        assert captured[0] == captured[1]
        assert captured[1]['video_voice'] == 'kokoro_male'
        assert captured[1]['video_subtitles'] is False
        assert balance(manager) == (2000, 0)
    asyncio.run(run())


@pytest.mark.parametrize('change', [{'video_voice':'/tmp/model'}, {'video_subtitles':'true'}, {'video_narration':1}])
def test_video_spec_rejects_invalid_options(change):
    with pytest.raises(ValueError):
        validate_video_spec({**spec(), **change})


def test_kokoro_missing_or_symlink_model_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv('NBPPT_KOKORO_MODEL_DIR', str(tmp_path / 'missing'))
    with pytest.raises(SpeechError):
        trusted_model_dir('kokoro_female')
    (tmp_path / 'alias').symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.setenv('NBPPT_KOKORO_MODEL_DIR', str(tmp_path / 'alias'))
    with pytest.raises(SpeechError):
        trusted_model_dir('kokoro_male')


@pytest.mark.skipif(not os.environ.get('NBPPT_KOKORO_MODEL_DIR'), reason='optional Kokoro model not configured')
@pytest.mark.parametrize('voice', ['kokoro_female', 'kokoro_male'])
def test_real_optional_voice_produces_requested_metadata(tmp_path, voice):
    job = 'video_1234567890'
    root = tmp_path / job
    (root / 'staging/assets').mkdir(parents=True)
    data = plan()
    data['video_voice'] = voice
    for s in data['video_scenes']:
        s['narration'] = '谨慎验证'
    render_video(root, job, data)
    (root / 'validated_video_plan.json').write_text(json.dumps(data, ensure_ascii=False))
    result = subprocess.run([os.environ['NBPPT_TTS_PYTHON'], 'worker/video_speech.py',
                             '--job-dir', str(root), '--job-id', job],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads((root / 'speech_result.json').read_text())
    assert receipt['voice'] == voice and receipt['provider'] == 'kokoro'
