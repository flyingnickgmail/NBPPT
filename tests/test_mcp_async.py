import asyncio
from contextlib import asynccontextmanager
import json
import socket
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from clients.nbppt_mcp import remote_client, validate_config
from gateway.auth import authenticate_request
from gateway.delivery import delivery_urls
from gateway.mcp_server import PresentationJobs, build_mcp
from test_security_delivery import manager, KEY_A, KEY_B, balance, make_delivery

A = {'user_id': 'a', 'api_key': KEY_A}
B = {'user_id': 'b', 'api_key': KEY_B}


def test_async_retries_disconnect_and_ownership(manager, monkeypatch):
    async def scenario():
        jobs = PresentationJobs(manager)
        started, release = asyncio.Event(), asyncio.Event()
        async def execute(job, arguments):
            started.set()
            await release.wait()
            await manager.cancel_refund(job, 'test failure')
        monkeypatch.setattr(jobs, 'execute', execute)
        responses = await asyncio.gather(*(jobs.create(A, '客户内容', 'auto', 5, 'retry-0001') for _ in range(5)))
        job_id = responses[0]['job_id']
        assert {r['job_id'] for r in responses} == {job_id}
        assert balance(manager) == (1940, 60)
        await started.wait()
        running = await jobs.status(A, job_id)
        assert running['status'] == 'RUNNING'
        assert (running['credits_held'], running['credits_refunded']) == (60, 0)
        for method in (jobs.status, jobs.artifacts):
            with pytest.raises(ValueError, match='无权'): await method(B, job_id)
        with pytest.raises(ValueError, match='不同内容'):
            await jobs.create(A, 'changed', 'auto', 5, 'retry-0001')
        with pytest.raises(ValueError, match='尚未'):
            await jobs.artifacts(A, job_id)
        release.set()
        await asyncio.gather(*list(jobs.tasks))
        failed = await jobs.status(A, job_id)
        assert failed['status'] == 'FAILED'
        assert (failed['credits_frozen'], failed['credits_held'], failed['credits_refunded']) == (60, 0, 60)
        retry = await jobs.create(A, '客户内容', 'auto', 5, 'retry-0001')
        assert retry['status'] == 'FAILED'
        assert balance(manager) == (2000, 0)
        with sqlite3.connect(manager.db_path) as db:
            assert db.execute("SELECT count(*) FROM credit_ledger WHERE action='FREEZE'").fetchone()[0] == 1
    asyncio.run(scenario())


def test_disconnect_during_admission_does_not_lose_job(manager, monkeypatch):
    async def scenario():
        jobs = PresentationJobs(manager)
        entered, release, executed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original = manager.try_freeze_credits
        async def delayed(*args, **kwargs):
            await original(*args, **kwargs)
            entered.set()
            await release.wait()
        async def execute(job, args):
            executed.set()
            await manager.cancel_refund(job, 'test')
        monkeypatch.setattr(manager, 'try_freeze_credits', delayed)
        monkeypatch.setattr(jobs, 'execute', execute)
        request = asyncio.create_task(jobs.create(A, 'test', 'auto', 2, 'disconnect-01'))
        await entered.wait()
        request.cancel()
        with pytest.raises(asyncio.CancelledError): await request
        release.set()
        await asyncio.wait_for(executed.wait(), 2)
        await asyncio.gather(*list(jobs.tasks))
        assert balance(manager) == (2000, 0)
    asyncio.run(scenario())


def test_completed_artifacts_rechecked_and_owned(manager):
    async def scenario():
        jobs = PresentationJobs(manager)
        job = 'ppt_1234567890'
        await manager.try_freeze_credits(KEY_A, job, 'ppt', 'test', 60)
        spec, manifest = make_delivery(manager.jobs_root / job / 'output', job=job)
        await manager.save_compiled_spec(job, spec)
        await manager.confirm_settle(job, .1, delivery_urls(job, manifest))
        completed = await jobs.status(A, job)
        assert (completed['credits_charged'], completed['credits_held'], completed['credits_refunded']) == (42, 0, 18)
        assert (await jobs.artifacts(A, job))['slide_count'] == 2
        (manager.jobs_root / job / 'output/assets/slide_preview_1.png').write_bytes(b'corrupt')
        with pytest.raises(ValueError): await jobs.artifacts(A, job)
    asyncio.run(scenario())


@pytest.fixture
def live_mcp(manager):
    jobs = PresentationJobs(manager)
    transport = build_mcp(jobs)
    @asynccontextmanager
    async def lifespan(app):
        async with transport.router.lifespan_context(transport):
            yield
            await jobs.close()
    app = FastAPI(lifespan=lifespan)
    @app.middleware('http')
    async def auth(request: Request, next):
        try:
            request.state.principal = await authenticate_request(manager, request)
        except Exception:
            return JSONResponse({'detail': 'Unauthorized'}, status_code=401)
        return await next(request)
    app.mount('/', transport)
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline: time.sleep(.01)
    assert server.started
    yield {'url': f'http://127.0.0.1:{port}/mcp', 'api_key': KEY_A}, jobs
    server.should_exit = True
    thread.join(5)
    sock.close()
    assert not thread.is_alive()


def test_real_sdk_handshake_tools_and_validation(live_mcp):
    config, jobs = live_mcp
    async def scenario():
        async with remote_client(config) as client:
            tools = await client.list_tools()
            assert {t.name for t in tools.tools} == {'list_templates', 'create_presentation', 'create_video', 'retry_job', 'get_job_status', 'get_job_artifacts'}
            templates = await client.call_tool('list_templates', {})
            assert not templates.is_error
            result = await client.call_tool('create_presentation', {'source':'test', 'request_id':'bad', 'slide_count':2})
            assert result.is_error
            missing = await client.call_tool('get_job_status', {'job_id':'ppt_0000000000'})
            assert missing.is_error
        assert not jobs.tasks
    asyncio.run(scenario())


def test_adapter_refuses_cleartext_remote():
    with pytest.raises(ValueError, match='HTTPS'):
        validate_config({'url':'http://38.97.249.8:8000/mcp', 'api_key':KEY_A})


def test_real_client_submit_disconnect_retry(live_mcp, monkeypatch, manager):
    config, jobs = live_mcp
    release = threading.Event()
    async def execute(job, args):
        while not release.is_set():
            await asyncio.sleep(.01)
        await manager.cancel_refund(job, 'controlled worker failure')
    monkeypatch.setattr(jobs, 'execute', execute)
    async def scenario():
        args = {'source': 'independent background task', 'request_id': 'sdk-retry-01', 'slide_count': 2}
        started = time.monotonic()
        async with remote_client(config) as client:
            first = await client.call_tool('create_presentation', args)
            assert not first.is_error
            job = json.loads(first.content[0].text)['job_id']
        assert time.monotonic() - started < 3
        async with remote_client(config) as client:
            second = await client.call_tool('create_presentation', args)
            assert json.loads(second.content[0].text)['job_id'] == job
            status = await client.call_tool('get_job_status', {'job_id': job})
            assert json.loads(status.content[0].text)['status'] == 'RUNNING'
        assert balance(manager) == (1940, 60)
        release.set()
        deadline = time.monotonic() + 2
        while balance(manager) != (2000, 0) and time.monotonic() < deadline: await asyncio.sleep(.01)
        assert balance(manager) == (2000, 0)
    try:
        asyncio.run(scenario())
    finally:
        release.set()


@pytest.mark.parametrize("kind,suffix", [("ppt", "_deck.pptx"), ("ppt", "/content_outline.md"), ("ppt", "/content_plan.json"), ("video", "_video.mp4"), ("video", "/assets/video_poster.png"), ("video", "/subtitles.vtt")])
def test_download_integrity_and_path_boundary(tmp_path, monkeypatch, kind, suffix):
    import hashlib
    import httpx
    from clients import nbppt_mcp as adapter
    job = kind + '_1234567890'
    config = {'url': 'http://127.0.0.1:1234/mcp', 'api_key': KEY_A, 'download_dir': str(tmp_path)}
    result = {'job_id': job, 'slide_count': 2,
              'files': [{'path': suffix[1:] if suffix.startswith('/') else job+suffix, 'size': 4, 'sha256': hashlib.sha256(b'data').hexdigest()}]}
    real = httpx.AsyncClient
    def handler(request):
        assert request.headers['Authorization'] == 'Bearer '+KEY_A
        assert KEY_A not in str(request.url)
        return httpx.Response(200, content=b'data')
    monkeypatch.setattr(adapter.httpx, 'AsyncClient', lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))
    async def scenario():
        response = await adapter.download_artifacts(config, result)
        assert Path(response['local_files'][0]).read_bytes() == b'data'
        result['files'][0]['sha256'] = 'wrong'
        with pytest.raises(ValueError, match='integrity'): await adapter.download_artifacts(config, result)
        result['files'][0]['path'] = '../../escape'
        with pytest.raises(ValueError, match='path'): await adapter.download_artifacts(config, result)
    from pathlib import Path
    asyncio.run(scenario())
