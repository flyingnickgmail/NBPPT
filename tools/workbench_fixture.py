"""Private loopback acceptance server: real app/worker/media, fixed planner only.

Never run against a configured service or existing database. Secrets are generated
for this disposable process and emitted only through its private ready pipe.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = '客户需要把事实讲清楚。先解释现状，再对比方案，最后给出实施流程。项目分为3步，但收益仍需验证。'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output/'tmp').mkdir()
    database = output/'fixture.db'
    if database.exists():
        raise ValueError('Use a new acceptance directory; never reopen an existing wallet')
    sys.path.insert(0, str(ROOT))
    worker_secret = secrets.token_urlsafe(40)
    os.environ.update(DATABASE_PATH=str(database), NBPPT_JOBS_ROOT=str(output/'jobs'),
                      TMPDIR=str(output/'tmp'), TMP=str(output/'tmp'), TEMP=str(output/'tmp'),
                      NBPPT_COOKIE_SECURE='false', NBPPT_CLAUDE_ENABLED='false',
                      NBPPT_MICROSOFT_EDGE_ENABLED='true', NBPPT_KOKORO_ENABLED='false',
                      NBPPT_REQUIRE_ISOLATION='false', NBPPT_REPORT_MODEL_ENABLED='false')
    from gateway import main as gateway, mcp_server
    from worker import worker_api, video_generation
    from starlette.routing import Mount
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    import uvicorn

    asyncio.run(gateway.billing.initialize())
    keys = {name: secrets.token_urlsafe(40) for name in ('a', 'b')}
    with sqlite3.connect(database) as db:
        for name, key in keys.items():
            db.execute('INSERT INTO users(id,phone_or_email,tier,credits_available,created_at) VALUES (?,?,?,?,?)',
                       (name, name, 'studio', 2000, 'acceptance-only'))
            db.execute('INSERT INTO mcp_api_keys(api_key,user_id,created_at,scope,allow_claude) VALUES (?,?,?,?,?)',
                       (key, name, 'acceptance-only', 'generate', 0))
    server_socket = socket.socket()
    server_socket.bind(('127.0.0.1', 0))
    origin = f'http://127.0.0.1:{server_socket.getsockname()[1]}'
    worker_api.WORKSPACE_JOBS_DIR = gateway.JOBS_ROOT
    worker_api.WORKER_SECRET = worker_secret
    mcp_server.get_runtime_settings = lambda: dict(
        overseas_worker_url=origin+'/_acceptance_worker', overseas_worker_secret=worker_secret)
    plan = {'task_summary_cn': '把事实讲清楚', 'scenes': [
        dict(scene_num=1, duration_sec=3, title='先解释现状', body='客户需要把事实讲清楚。',
             narration='讲清客户事实', source_quotes=['客户需要把事实讲清楚。'],
             layout='title', items=['事实', '边界']),
        dict(scene_num=2, duration_sec=3, title='再给出实施流程', body='收益仍需验证。',
             narration='收益仍需验证', source_quotes=['最后给出实施流程。', '收益仍需验证。'],
             layout='process', items=['现状', '方案', '流程'])]}
    planner = output/'fixed_planner.py'
    planner.write_text('import pathlib,time\ntime.sleep(6)\npathlib.Path("video_plan.json").write_text('
                       + repr(json.dumps(plan, ensure_ascii=False))+',encoding="utf-8")\n')
    calls = 0
    def fixed_planner(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        # First request really fails in the worker; retry uses the real renderer.
        if calls == 1:
            return [sys.executable, '-c', 'import time;time.sleep(1);raise SystemExit(17)']
        return [sys.executable, str(planner)]
    video_generation._planner_command = fixed_planner

    async def state(_request):
        with sqlite3.connect(database) as db:
            jobs = db.execute('SELECT job_id,user_id,status,credits_charged FROM media_jobs ORDER BY rowid').fetchall()
            wallets = db.execute('SELECT id,credits_available,credits_frozen FROM users ORDER BY id').fetchall()
            errors = db.execute('SELECT job_id,error_msg FROM media_jobs WHERE error_msg IS NOT NULL').fetchall()
        return JSONResponse({'jobs': jobs, 'wallets': wallets, 'errors':errors})

    # These two routes exist ONLY in this private fixture process, before the MCP mount.
    gateway.app.router.routes.insert(0, Mount('/_acceptance_worker', app=worker_api.app))
    gateway.app.router.routes.insert(0, Route('/_acceptance_state', state))
    config = uvicorn.Config(gateway.app, log_level='warning', access_log=False)
    print(json.dumps({'origin': origin, 'key_a': keys['a'], 'key_b': keys['b'], 'source': SOURCE}), flush=True)
    uvicorn.Server(config).run(sockets=[server_socket])


if __name__ == '__main__':
    main()
