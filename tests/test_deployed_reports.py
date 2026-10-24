"""Production nginx config + real HTTP services, with synthetic paid-model output.

Explicit --deployment opt-in fails if dependencies are absent. No credentials,
live database or model accounts are required, including on pull requests.
"""
import asyncio
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from gateway.billing_tcc import BillingManager
from gateway.delivery import delivery_urls, inspect_delivery
from tools.deployment_acceptance import AcceptanceError, check_deployment
from worker.video_renderer import render_video
from test_security_delivery import make_delivery
from test_video_generation import actual_plan

ROOT = Path(__file__).resolve().parents[1]
KEY_A = 'deployment-fixture-a-' + 'a' * 40
KEY_B = 'deployment-fixture-b-' + 'b' * 40
PPT = 'ppt_0101010101'
VIDEO = 'video_0202020202'


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_until(check, processes=(), timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        assert all(p.poll() is None for p in processes), 'A test service exited; inspect task-local service logs'
        try:
            result = check()
            if result:
                return result
        except httpx.TransportError:
            pass
        time.sleep(.1)
    raise AssertionError('Timed out waiting for the deployment fixture')


@pytest.fixture(scope='module')
def deployed(tmp_path_factory):
    for name in ('nginx', 'openssl', 'ffmpeg', 'ffprobe'):
        assert shutil.which(name), f'--deployment requires {name}; install it rather than skipping this gate'
    root = tmp_path_factory.mktemp('deployment')
    jobs = root / 'jobs'
    jobs.mkdir()
    database = root / 'platform.db'
    manager = BillingManager(str(database), jobs)
    asyncio.run(manager.initialize())
    with sqlite3.connect(database) as db:
        for user, key in [('deploy-a', KEY_A), ('deploy-b', KEY_B)]:
            db.execute('INSERT INTO users(id,phone_or_email,tier,credits_available,created_at) VALUES (?,?,?,?,?)', (user, user, 'studio', 2000, 'now'))
            db.execute('INSERT INTO mcp_api_keys(api_key,user_id,created_at) VALUES (?,?,?)', (key, user, 'now'))
        ppt_spec, ppt_manifest = make_delivery(jobs / PPT / 'output', PPT)
        video_dir = jobs / VIDEO
        (video_dir / 'staging/assets').mkdir(parents=True)
        video_spec = actual_plan()
        render_video(video_dir, VIDEO, video_spec)
        video_manifest = inspect_delivery(VIDEO, 'video', video_spec, video_dir / 'staging')
        (video_dir / 'staging/delivery.json').write_text(json.dumps(video_manifest))
        (video_dir / 'staging').rename(video_dir / 'output')
        for job, kind, spec, manifest in [(PPT, 'ppt', ppt_spec, ppt_manifest), (VIDEO, 'video', video_spec, video_manifest)]:
            db.execute("INSERT INTO media_jobs(job_id,user_id,task_type,status,cn_user_prompt,en_compiled_spec,credits_frozen,credits_charged,result_cdn_urls,created_at) VALUES (?,?,?,'COMPLETED',?,?,0,0,?,'now')", (job, 'deploy-a', kind, 'Synthetic pre-existing media', json.dumps(spec), json.dumps(delivery_urls(job, manifest))))
    cert, key = root / 'cert.pem', root / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-keyout', str(key), '-out', str(cert), '-subj', '/CN=localhost',
                    '-addext', 'subjectAltName=IP:127.0.0.1,DNS:localhost'], check=True, capture_output=True)
    gateway_port, worker_port, tls_port, http_port = [free_port() for _ in range(4)]
    env = {**os.environ, 'NBPPT_DEPLOYMENT_TEST_ROOT': str(root), 'DATABASE_PATH': str(database),
           'NBPPT_JOBS_ROOT': str(jobs), 'NBPPT_REPORTS_ROOT': str(root / 'reports'),
           'NBPPT_ADMIN_API_KEY': '', 'NBPPT_REQUIRE_ISOLATION': 'true',
           'OVERSEAS_WORKER_URL': f'http://127.0.0.1:{worker_port}',
           'OVERSEAS_WORKER_SECRET': 'deployment-worker-' + 'c' * 40,
           'NBPPT_COOKIE_SECURE': 'true', 'NBPPT_PUBLIC_ORIGIN': f'https://127.0.0.1:{tls_port}',
           'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1'}
    processes, logs = [], []
    config = (ROOT / 'deploy/production/nginx.conf').read_text()
    # Substitute only runtime addresses/certificates; keep the shipped locations,
    # limits, headers, rate limiting and proxy directives under test.
    config = config.replace('listen 80;', f'listen 127.0.0.1:{http_port};')
    config = config.replace('listen 443 ssl;', f'listen 127.0.0.1:{tls_port} ssl;')
    config = config.replace('38.97.249.8', f'127.0.0.1:{tls_port}')
    config = config.replace(f'/etc/letsencrypt/live/127.0.0.1:{tls_port}/fullchain.pem', str(cert))
    config = config.replace(f'/etc/letsencrypt/live/127.0.0.1:{tls_port}/privkey.pem', str(key))
    config = config.replace('127.0.0.1:8000', f'127.0.0.1:{gateway_port}')
    (root / 'site.conf').write_text(config)
    (root / 'nginx.conf').write_text(f'pid {root}/nginx.pid;\nerror_log {root}/nginx-error.log;\nevents {{}}\nhttp {{\naccess_log off;\nclient_body_temp_path {root}/body;\nproxy_temp_path {root}/proxy;\ninclude {root}/site.conf;\n}}\n')
    nginx_command = ['nginx', '-p', str(root) + '/', '-c', str(root / 'nginx.conf')]
    proxy = None
    try:
        for role, port in [('worker', worker_port), ('gateway', gateway_port)]:
            log = (root / (role + '.log')).open('w')
            logs.append(log)
            processes.append(subprocess.Popen([sys.executable, '-m', 'uvicorn', 'deployment_apps:' + role,
                '--app-dir', str(ROOT / 'tests'), '--host', '127.0.0.1', '--port', str(port),
                '--no-access-log'], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT))
            with httpx.Client(trust_env=False) as ready:
                wait_until(lambda: ready.get(f'http://127.0.0.1:{port}/health').status_code == 200, processes)
        subprocess.run(nginx_command + ['-t'], check=True, capture_output=True)
        proxy = subprocess.Popen(nginx_command + ['-g', 'daemon off;'], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        context = ssl.create_default_context(cafile=str(cert))
        base = f'https://127.0.0.1:{tls_port}'
        with httpx.Client(base_url=base, verify=context, trust_env=False) as ready:
            wait_until(lambda: ready.get('/').status_code == 200, processes + [proxy])
        yield {'root': root, 'database': database, 'jobs': jobs, 'base': base, 'verify': context,
               'nginx_command': nginx_command, 'original_site': config, 'http_port': http_port}
    finally:
        for process in [proxy, *reversed(processes)]:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        for log in logs:
            log.close()


@pytest.mark.deployment
def test_report_share_downloads_and_media_through_production_proxy(deployed):
    stack = deployed
    headers = {'Authorization': 'Bearer ' + KEY_A}
    db = sqlite3.connect(stack['database'])
    wallet = lambda: db.execute("SELECT credits_available,credits_frozen FROM users WHERE id='deploy-a'").fetchone()
    original_media = {p: hashlib.sha256(p.read_bytes()).hexdigest() for job in (PPT, VIDEO) for p in (stack['jobs'] / job / 'output').rglob('*') if p.is_file()}
    with httpx.Client(base_url=stack['base'], headers=headers, verify=stack['verify'], trust_env=False,
                      timeout=60, event_hooks={'request': [lambda request: time.sleep(.22)]}) as client:
        def post(path, data, request_id):
            response = client.post(path, json=data, headers={'X-Request-ID': request_id})
            assert response.status_code in (201, 202), (path, response.status_code)
            return response.json()

        def finished(started):
            return wait_until(lambda: (v if (v := client.get(started['status_url']).json())['state'] in ('completed', 'failed') else None))

        home = client.get('/')
        assert 'id="mode-report"' in home.text and 'id="mode-ppt"' in home.text and 'id="mode-video"' in home.text
        source = '\n  ' + json.loads((ROOT / 'tools/report_studio/sample.json').read_text())['content'] + '\n\n'
        draft = post('/api/reports/draft', {'content': source, 'title': '部署验收合成材料', 'mode': 'ai'}, 'draft')
        draft_id = draft['id']
        assert client.get('/api/reports/jobs/' + draft_id + '/input').json()['content'] == source
        payload = {'content': source, 'title': '部署验收合成材料', 'mode': 'ai'}
        admitted = post('/api/reports/generate', payload, 'deployment-report')
        state = finished(admitted)
        assert state['state'] == 'completed' and state['credits_charged'] == 60 and wallet() == (1940, 0)
        assert post('/api/reports/generate', payload, 'deployment-report') == admitted
        report = client.get(admitted['status_url'] + '/result').json()
        share = post('/api/reports/overview', report, 'deployment-share')
        state = finished(share)
        assert state['state'] == 'completed' and state['credits_charged'] == 40 and wallet() == (1900, 0)
        assert post('/api/reports/overview', report, 'deployment-share') == share
        result = client.get(share['status_url'] + '/result').json()
        assert result['content'] == source and result['report'] == report['report']
        assert len(json.dumps(result).encode()) > 1_000_000
        receipt = check_deployment(stack['base'], KEY_A, share['id'], [PPT, VIDEO], verify=stack['verify'])
        assert receipt['status'] == 'passed' and receipt['wallet_unchanged'] and len(receipt['checks']) == 3
        media_only = check_deployment(stack['base'], KEY_A, media_jobs=[PPT, VIDEO], verify=stack['verify'])
        assert [check['kind'] for check in media_only['checks']] == ['ppt', 'video']
        (stack['root'] / 'receipt.json').write_text(json.dumps(receipt, indent=2))
        for path in [state['preview_url'], state['preview_url'] + '/overview.png', '/api/jobs/' + PPT + '/artifacts', '/artifacts/' + VIDEO + '/' + VIDEO + '_video.mp4']:
            assert client.get(path, headers={'Authorization': 'Bearer ' + KEY_B}).status_code == 404
        failures = post('/api/reports/generate', {'content': 'DEPLOYMENT_FIXTURE_FAILURE', 'mode': 'ai'}, 'deployment-failure')
        failed = finished(failures)
        assert failed['state'] == 'failed' and failed['credits_held'] == 0 and wallet() == (1900, 0)
        assert db.execute('SELECT action FROM credit_ledger WHERE job_id=? ORDER BY id', (failed['billing_job_id'],)).fetchall() == [('FREEZE',), ('REFUND',)]
        history = client.get('/api/jobs').json()['jobs']
        assert {j['job_id'] for j in history} == {PPT, VIDEO}
        assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in original_media.items())
        # Negative control: reproduce the exact previous defect with the old
        # limit. Prove this acceptance fails on a bad deployment, then restore it.
        site = stack['root'] / 'site.conf'
        try:
            site.write_text(stack['original_site'].replace('client_max_body_size 10m;', 'client_max_body_size 1m;'))
            subprocess.run(stack['nginx_command'] + ['-s', 'reload'], check=True, capture_output=True)
            wait_until(lambda: client.post('/api/reports/export', json=result).status_code == 413)
            with pytest.raises(AcceptanceError, match='expected HTTP 200, received 413'):
                check_deployment(stack['base'], KEY_A, share['id'], verify=stack['verify'])
        finally:
            site.write_text(stack['original_site'])
            subprocess.run(stack['nginx_command'] + ['-s', 'reload'], check=True, capture_output=True)
        wait_until(lambda: client.post('/api/reports/export', json=result).status_code == 200)
        assert wallet() == (1900, 0)
    db.close()


def test_live_acceptance_rejects_credentials_in_url_before_network():
    with pytest.raises(AcceptanceError, match='HTTPS origin'):
        check_deployment('https://key:secret@example.test', 'test', 'a' * 32)
