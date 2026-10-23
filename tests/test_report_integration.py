"""NB PPT report integration: real routing/auth/storage; model calls are stubbed."""
import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from PIL import Image

from gateway import main, reports
from gateway.billing_tcc import BillingManager
from tools.report_studio.models import ExportInput
from tools.report_studio.overview import attach
from worker import worker_api, report_generation

KEY_A = 'report-test-a-' + 'a' * 40
KEY_B = 'report-test-b-' + 'b' * 40
HEADERS = {'Authorization': 'Bearer ' + KEY_A}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.delenv('NBPPT_ADMIN_API_KEY', raising=False)
    monkeypatch.delenv('NBPPT_REQUIRE_ISOLATION', raising=False)
    manager = BillingManager(str(tmp_path / 'platform.db'), tmp_path / 'media')
    run(manager.initialize())
    with sqlite3.connect(manager.db_path) as db:
        for user, key in [('alice', KEY_A), ('bob', KEY_B)]:
            db.execute('INSERT INTO users(id,phone_or_email,tier,credits_available,created_at) VALUES (?,?,?,?,?)', (user, user, 'studio', 2000, 'now'))
            db.execute('INSERT INTO mcp_api_keys(api_key,user_id,created_at) VALUES (?,?,?)', (key, user, 'now'))
    ws = reports.ReportWorkspace(tmp_path / 'reports')
    monkeypatch.setattr(main, 'billing', manager)
    monkeypatch.setattr(reports, 'workspace', ws)
    monkeypatch.setattr(main, 'report_workspace', ws)
    return ws


@pytest.fixture
def sample():
    return json.loads((reports.STATIC.parent / 'sample.json').read_text())


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='https://testserver', headers=HEADERS)


async def import_report(c, data):
    response = await c.post('/api/reports/preview', json=data)
    assert response.status_code == 200, response.text
    url = response.json()['url']
    return url, url.rsplit('/', 1)[-1]


def test_main_entry_and_login_boundary(setup):
    async def check():
        async with client() as c:
            assert 'id="mode-report"' in (await c.get('/')).text
            assert '先讲清内容' in (await c.get('/')).text
            unauth = {'Authorization': ''}
            for url in ['/reports/static/studio.js', '/api/reports/health', '/api/reports/sample', '/api/reports/jobs']:
                assert (await c.get(url, headers=unauth)).status_code == 401
            redirect = await c.get('/reports', headers=unauth)
            assert redirect.status_code == 303
            assert redirect.headers['location'] == '/?next=reports'
            page = await c.get('/reports')
            assert page.status_code == 200
            assert 'NB PPT · 研究报告' in page.text
            assert 'apiBase:"/api/reports"' in page.text
            assert '/reports/static/studio.js' in page.text
            assert '我的报告' in page.text
            assert (await c.get('/reports/static/studio.js')).status_code == 200
    run(check())


def test_local_generation_persistence_and_ownership(setup):
    async def check():
        async with client() as c:
            started = await c.post('/api/reports/generate', json={'content': '# 门店核查\n## 依据\n保留原文。', 'title': '本地报告', 'mode': 'local'})
            assert started.status_code == 202
            key = started.json()['id']
            await asyncio.gather(*list(setup.tasks.values()))
            state = (await c.get(started.json()['status_url'])).json()
            assert state['state'] == 'completed'
            assert 'owner' not in state and 'sha256' not in state
            result = await c.get('/api/reports/jobs/' + key + '/result')
            assert result.json()['report']['title'] == '本地报告'
            assert not result.json()['report']['metrics']
            assert (await c.get(state['preview_url'])).status_code == 200
            assert len((await c.get('/api/reports/jobs')).json()['items']) == 1
            for url in [started.json()['status_url'], '/api/reports/jobs/' + key + '/result', state['preview_url'], state['preview_url'] + '/overview.png']:
                assert (await c.get(url, headers={'Authorization': 'Bearer ' + KEY_B})).status_code == 404
            assert (await c.get('/api/reports/jobs', headers={'Authorization': 'Bearer ' + KEY_B})).json()['items'] == []
            # A new process can read completed results without an in-memory preview cache.
            restored = reports.ReportWorkspace(setup.root)
            assert restored.result(key, 'alice').report.title == '本地报告'
    run(check())


def test_worker_model_generation_composes_short_inputs(setup, sample, monkeypatch):
    calls = []
    async def generated(content, title):
        calls.append('generate')
        return ExportInput.model_validate(sample).report
    async def reading(report, content):
        calls.append('reading'); return report
    async def editorial(report, content):
        calls.append('editorial'); return report
    async def progress(*args): pass
    monkeypatch.setattr(report_generation, 'ai_report', generated)
    monkeypatch.setattr(report_generation, 'design_reading', reading)
    monkeypatch.setattr(report_generation, 'design_editorial', editorial)
    async def check():
        result = await report_generation.generate_report(reports.GenerateInput(content=sample['content'],mode='ai'),
                                                        'generate',setup.root,progress)
        assert result.report == ExportInput.model_validate(sample).report
        assert calls == ['generate', 'reading', 'editorial']
    run(check())


def test_import_export_and_tamper_guard(setup, sample):
    async def check():
        async with client() as c:
            url, key = await import_report(c, sample)
            repeated, repeated_key = await import_report(c, sample)
            assert repeated == url and repeated_key == key
            assert len((await c.get('/api/reports/jobs')).json()['items']) == 1
            preview = await c.get(url)
            assert 'window.ReportStudioConfig={apiBase:"/api/reports",platform:true}' in preview.text
            assert "frame-ancestors 'self'" in preview.headers['content-security-policy']
            download = await c.post('/api/reports/export', json=sample)
            assert download.status_code == 200
            assert 'window.ReportStudioConfig={apiBase:' not in download.text
            assert '<script src=' not in download.text
            path = setup.folder(key) / 'report.json'
            path.write_text(path.read_text() + ' ')
            assert (await c.get(url)).status_code == 409
            assert (await c.get('/api/reports/jobs/' + key + '/result')).status_code == 409
    run(check())


def test_image_download_bytes_and_owner(setup, sample, tmp_path):
    image = tmp_path / 'share.png'
    Image.new('RGB', (640, 800), '#F5F1E9').save(image)
    attached = attach(ExportInput.model_validate(sample), image, '用于验证下载绑定与字节一致性的测试分享图，不是业务结果。')
    async def check():
        async with client() as c:
            url, _ = await import_report(c, attached.model_dump())
            response = await c.get(url + '/overview.png')
            assert response.status_code == 200
            assert response.content == image.read_bytes()
            assert response.headers['content-type'] == 'image/png'
            assert (await c.get(url + '/overview.png', headers={'Authorization': 'Bearer ' + KEY_B})).status_code == 404
    run(check())


def test_rejected_overview_keeps_original_report(setup, sample, monkeypatch):
    async def failed(*args):
        raise ValueError('bad visual')
    configure_worker(setup, sample, monkeypatch, model=failed)
    async def check():
        async with client() as c:
            original, key = await import_report(c, sample)
            original_bytes = (setup.folder(key) / 'report.json').read_bytes()
            response = await c.post('/api/reports/overview', json=sample)
            await asyncio.gather(*list(setup.tasks.values()))
            state = (await c.get(response.json()['status_url'])).json()
            assert state['state'] == 'failed'
            assert (await c.get(original)).status_code == 200
            assert (setup.folder(key) / 'report.json').read_bytes() == original_bytes
            assert (await c.get('/api/reports/overview/' + response.json()['id'] + '/result')).status_code == 409
            assert not setup.lock.locked()
            recovered = await c.get('/api/reports/jobs/' + response.json()['id'] + '/input')
            assert recovered.status_code == 200
            assert recovered.json()['content'] == sample['content']
            assert (await c.get('/api/reports/jobs/' + response.json()['id'] + '/input', headers={'Authorization': 'Bearer ' + KEY_B})).status_code == 404
    run(check())


def test_busy_rejects_duplicate_and_shutdown_marks_failure(setup, sample, monkeypatch):
    async def waiting(*args):
        await asyncio.Event().wait()
    configure_worker(setup, sample, monkeypatch, model=waiting)
    async def check():
        async with client() as c:
            first = await c.post('/api/reports/overview', json=sample)
            second = await c.post('/api/reports/overview', json=sample)
            assert second.status_code == 202
            third = await c.post('/api/reports/overview', json=sample)
            assert third.status_code == 422  # Existing platform limit: two running jobs per account.
            await setup.shutdown()
            state = (await c.get(first.json()['status_url'])).json()
            assert state['state'] == 'failed'
            assert not setup.lock.locked()
    run(check())


def test_restart_marks_only_interrupted_task_failed(setup):
    status = setup.create('alice', '中断报告', 'generate')
    (setup.folder(status['id']) / 'input.json').write_text('{}')
    state = setup.owned(status['id'], 'alice')
    assert state['state'] == 'failed'
    assert (setup.folder(status['id']) / 'input.json').exists()


def test_shutdown_before_task_first_runs_releases_lock(setup):
    async def check():
        await setup.start('alice', '排版任务', 'generate', reports.GenerateInput(content='原文', mode='local'))
        await setup.shutdown()
        assert not setup.lock.locked()
        assert not setup.tasks
        status_file = next(setup.root.glob('*/status.json'))
        assert json.loads(status_file.read_text())['state'] == 'failed'
    run(check())


def test_invalid_evidence_is_not_persisted(setup, sample):
    sample['report']['sections'][0]['chart']['points'][0]['value'] = 999999
    async def check():
        async with client() as c:
            response = await c.post('/api/reports/preview', json=sample)
            assert response.status_code == 422
            assert list(setup.root.glob('*/report.json')) == []
    run(check())


def test_cookie_auth_origin_and_revocation(setup, monkeypatch):
    monkeypatch.delenv('NBPPT_PUBLIC_ORIGIN', raising=False)
    async def check():
        async with client() as c:
            assert (await c.post('/api/session', json={'api_key': KEY_A})).status_code == 200
            c.headers.pop('Authorization')
            assert (await c.get('/reports')).status_code == 200
            payload = {'content': '报告原文', 'mode': 'local'}
            assert (await c.post('/api/reports/generate', json=payload)).status_code == 403
            assert (await c.post('/api/reports/generate', json=payload, headers={'Origin': 'https://evil.example'})).status_code == 403
            response = await c.post('/api/reports/generate', json=payload, headers={'Origin': 'https://testserver'})
            assert response.status_code == 202
            await asyncio.gather(*list(setup.tasks.values()))
            with sqlite3.connect(main.billing.db_path) as db:
                db.execute('UPDATE mcp_api_keys SET is_active=0 WHERE api_key=?', (KEY_A,))
            assert (await c.get('/reports')).status_code == 303
            assert (await c.get(response.json()['status_url'])).status_code == 401
    run(check())


def test_chunked_size_bound_and_missing_runtime(setup, monkeypatch):
    monkeypatch.setattr(reports, 'get_runtime_settings', lambda: {})
    async def chunks():
        for _ in range(6):
            yield b'a' * 2_000_000
    async def check():
        async with client() as c:
            assert (await c.post('/api/reports/preview', content=chunks())).status_code == 413
            response = await c.post('/api/reports/generate', json={'content': '真实材料', 'mode': 'ai'})
            assert response.status_code == 503
            assert not setup.tasks
    run(check())


def test_unsafe_job_symlink_cannot_read(setup, sample, tmp_path):
    async def check():
        async with client() as c:
            url, key = await import_report(c, sample)
            path = setup.folder(key) / 'report.json'
            copy = tmp_path / 'outside.json'
            path.rename(copy)
            path.symlink_to(copy)
            assert (await c.get(url)).status_code == 409
            assert (await c.get('/api/reports/jobs/not-a-valid-id')).status_code == 404
    run(check())


def test_mcp_report_tools_use_current_registration_and_scopes(setup):
    class Registry:
        tools = {}
        def tool(self):
            def register(fn):
                self.tools[fn.__name__] = fn
                return fn
            return register
    registry = Registry()
    reports.register_report_tools(registry, lambda context: context)
    assert {'generate_research_report', 'get_research_report', 'generate_report_share_image', 'continue_research_report'} <= registry.tools.keys()
    async def check():
        principal = {'user_id':'alice','scope':'generate'}
        task = await registry.tools['generate_research_report'](principal, '# MCP材料\n保留原文', mode='local')
        await asyncio.gather(*list(setup.tasks.values()))
        state = await registry.tools['get_research_report'](principal, task['id'])
        assert state['state']=='completed'
        with pytest.raises(reports.HTTPException):
            await registry.tools['get_research_report']({'user_id':'bob','scope':'generate'}, task['id'])
        with pytest.raises(reports.HTTPException):
            await registry.tools['generate_research_report']({'user_id':'alice','scope':'read'}, '只读不能生成', mode='local')
    run(check())


def test_home_draft_transfers_source_without_browser_storage(setup):
    async def check():
        async with client() as c:
            text = '主页输入的原文，不应在进入研究报告时丢失。'
            response = await c.post('/api/reports/draft', json={'content':text,'mode':'ai'})
            assert response.status_code==201
            key=response.json()['id']
            assert response.json()['url']=='/reports?draft='+key
            assert text not in response.json()['url']
            assert (await c.get('/api/reports/jobs/'+key)).json()['state']=='draft'
            assert (await c.get('/api/reports/jobs/'+key+'/input')).json()['content']==text
            assert (await c.get('/api/reports/jobs/'+key+'/input',headers={'Authorization':'Bearer '+KEY_B})).status_code==404
    run(check())


def test_read_only_key_cannot_write_or_call_models(setup,sample):
    read_key='report-read-'+'c'*40
    with sqlite3.connect(main.billing.db_path) as db:
        db.execute('INSERT INTO mcp_api_keys(api_key,user_id,created_at,scope) VALUES (?,?,?,?)',(read_key,'alice','now','read'))
    async def check():
        async with client() as c:
            url,key=await import_report(c,sample)
            headers={'Authorization':'Bearer '+read_key}
            assert (await c.get(url,headers=headers)).status_code==200
            assert (await c.get('/api/reports/health',headers=headers)).json()['can_generate'] is False
            for path,data in [('/api/reports/draft',{'content':'只读原文'}),('/api/reports/generate',{'content':'只读原文','mode':'local'}),('/api/reports/preview',sample),('/api/reports/overview',sample),('/api/reports/continue',sample)]:
                assert (await c.post(path,json=data,headers=headers)).status_code==403
    run(check())


def test_isolated_deployment_does_not_bypass_worker_policy(setup,sample,monkeypatch):
    from tools.report_studio import runtime
    monkeypatch.setenv('NBPPT_REQUIRE_ISOLATION','true')
    with pytest.raises(RuntimeError, match='isolated worker'):
        runtime.command(['/usr/bin/codex'], setup.root)
    assert not setup.tasks


def configure_worker(ws, sample, monkeypatch, model=None):
    """Actual worker route, SSE, file publication and billing; only model output is stubbed."""
    real_client = httpx.AsyncClient
    secret = 'worker-test-' + 'd' * 40
    monkeypatch.setattr(worker_api, 'WORKER_SECRET', secret)
    monkeypatch.setattr(worker_api, 'WORKSPACE_JOBS_DIR', main.billing.jobs_root)
    monkeypatch.setattr(worker_api, 'ACCOUNT_SAFE_SEMAPHORE', asyncio.Semaphore(1))
    monkeypatch.setattr(main, 'JOBS_ROOT', main.billing.jobs_root)
    monkeypatch.setattr(reports, 'get_runtime_settings', lambda: {'overseas_worker_url':'http://worker.test','overseas_worker_secret':secret})
    def clients(**kw):
        if 'transport' not in kw:
            kw['transport'] = httpx.ASGITransport(app=worker_api.app)
        return real_client(**kw)
    monkeypatch.setattr(httpx, 'AsyncClient', clients)
    async def generated(data, kind, folder, progress):
        await progress('generating', 'test progress')
        if kind != 'generate':
            result = data.model_copy(deep=True)
        else:
            result = ExportInput.model_validate(sample)
            result.content = data.content; result.theme = data.theme
            if data.title: result.report.title = data.title
        result.mode = 'ai'
        if kind == 'overview':
            image = folder / 'test-image.png'
            Image.new('RGB', (640,800), '#F5F1E9').save(image)
            result = attach(result, image, '测试图像，用于验证实际下载字节与报告版本绑定，不代表内容审核。')
        return result
    monkeypatch.setattr(report_generation, 'generate_report', model or generated)


def wallet_state():
    with sqlite3.connect(main.billing.db_path) as db:
        return db.execute("SELECT credits_available,credits_frozen FROM users WHERE id='alice'").fetchone()


def ledger_actions(job_id):
    with sqlite3.connect(main.billing.db_path) as db:
        return db.execute('SELECT action FROM credit_ledger WHERE job_id=? ORDER BY id',(job_id,)).fetchall()


def test_remote_report_share_settlement_and_download(setup, sample, monkeypatch):
    configure_worker(setup,sample,monkeypatch)
    async def check():
        async with client() as c:
            payload={'content':sample['content'],'title':'测试远程报告','mode':'ai'}
            started=await c.post('/api/reports/generate',json=payload,headers={'X-Request-ID':'remote-complete-01'})
            assert started.status_code==202, started.text
            key=started.json()['id']
            await asyncio.gather(*list(setup.tasks.values()))
            state=(await c.get(started.json()['status_url'])).json()
            assert state['state']=='completed',state
            assert state['credits_charged']==60 and state['credits_held']==0
            assert wallet_state()==(1940,0)
            job=await main.billing.get_job(state['billing_job_id'],'alice')
            assert job['overseas_cost_usd'] is None
            assert ledger_actions(job['job_id'])==[('FREEZE',),('SETTLE',)]
            # Replaying a completed request never reserves/charges a second time.
            duplicate=await c.post('/api/reports/generate',json=payload,headers={'X-Request-ID':'remote-complete-01'})
            assert duplicate.json()==started.json()
            assert wallet_state()==(1940,0)
            changed=await c.post('/api/reports/generate',json={**payload,'title':'另一标题'},headers={'X-Request-ID':'remote-complete-01'})
            assert changed.status_code==409
            result=(await c.get('/api/reports/jobs/'+key+'/result')).json()
            assert result['report']['title']=='测试远程报告'
            downloaded=await c.get('/api/reports/jobs/'+key+'/download')
            assert downloaded.content==(setup.folder(key)/'report.html').read_bytes()
            share=await c.post('/api/reports/overview',json=result,headers={'X-Request-ID':'remote-share-01'})
            assert share.status_code==202,share.text
            await asyncio.gather(*list(setup.tasks.values()))
            shared=(await c.get(share.json()['status_url'])).json()
            assert shared['state']=='completed',shared
            assert shared['credits_charged']==40 and wallet_state()==(1900,0)
            new=(await c.get('/api/reports/jobs/'+shared['id']+'/result')).json()
            assert new['report']==result['report']
            image=await c.get(shared['preview_url']+'/overview.png')
            import base64
            assert image.content==base64.b64decode(new['overview']['data_url'].split(',',1)[1])
            assert (await c.get(shared['preview_url']+'/overview.png',headers={'Authorization':'Bearer '+KEY_B})).status_code==404
            root=main.billing.jobs_root/shared['billing_job_id']/'output'
            assert (root/'report.json').stat().st_mode&0o777==0o640
            assert (root/'overview.png').read_bytes()==image.content
            # Report rows must never appear as fake PPTs in the original creation history.
            assert (await c.get('/api/jobs')).json()['jobs']==[]
            assert (await c.get('/api/reports/health')).json()['credits_available']==1900
    run(check())


def test_remote_failure_and_cancellation_refund_exactly_once(setup,sample,monkeypatch):
    async def failed(*args): raise ValueError('model error')
    configure_worker(setup,sample,monkeypatch,model=failed)
    async def check():
        async with client() as c:
            r=await c.post('/api/reports/generate',json={'content':sample['content'],'mode':'ai'})
            await asyncio.gather(*list(setup.tasks.values()))
            state=(await c.get(r.json()['status_url'])).json()
            assert state['state']=='failed' and state['credits_held']==0
            assert wallet_state()==(2000,0)
            job=state['billing_job_id']
            assert ledger_actions(job)==[('FREEZE',),('REFUND',)]
            await main.billing.cancel_refund(job,'repeat')
            assert ledger_actions(job)==[('FREEZE',),('REFUND',)]
            async def waiting(*args): await asyncio.Event().wait()
            monkeypatch.setattr(report_generation,'generate_report',waiting)
            r=await c.post('/api/reports/generate',json={'content':sample['content'],'mode':'ai'})
            assert wallet_state()==(1940,60)
            await setup.shutdown()
            state=(await c.get(r.json()['status_url'])).json()
            assert state['state']=='failed' and wallet_state()==(2000,0)
            assert ledger_actions(state['billing_job_id'])==[('FREEZE',),('REFUND',)]
    run(check())


def test_remote_admission_scope_balance_and_request_id(setup,sample,monkeypatch):
    configure_worker(setup,sample,monkeypatch)
    with sqlite3.connect(main.billing.db_path) as db:
        db.execute("UPDATE users SET credits_available=1 WHERE id='alice'")
    async def check():
        async with client() as c:
            payload={'content':sample['content'],'mode':'ai'}
            assert (await c.post('/api/reports/generate',json=payload)).status_code==422
            assert (await c.post('/api/reports/generate',json=payload,headers={'X-Request-ID':'bad'})).status_code==422
            assert not setup.tasks and wallet_state()==(1,0)
            with sqlite3.connect(main.billing.db_path) as db:
                assert db.execute('SELECT count(*) FROM media_jobs').fetchone()[0]==0
    run(check())


@pytest.mark.parametrize('mutation',['content','theme','html','missing-image'])
def test_delivery_binding_rejects_tampering(setup,sample,monkeypatch,mutation):
    configure_worker(setup,sample,monkeypatch)
    original=reports.verify_published
    def tampered(job_id,task_type,spec,root):
        p=root/'report.json'; d=json.loads(p.read_text())
        if mutation=='content': d['content']+='改动原文'
        elif mutation=='theme': d['theme']='dark'
        elif mutation=='html': (root/'report.html').write_text('<html>fake</html>')
        else: (root/'overview.png').unlink()
        if mutation in ('content','theme'): p.write_text(json.dumps(d))
        return original(job_id,task_type,spec,root)
    monkeypatch.setattr(reports,'verify_published',tampered)
    async def check():
        async with client() as c:
            if mutation=='missing-image':
                response=await c.post('/api/reports/overview',json=sample)
            else:
                response=await c.post('/api/reports/generate',json={'content':sample['content'],'mode':'ai'})
            await asyncio.gather(*list(setup.tasks.values()))
            state=(await c.get(response.json()['status_url'])).json()
            assert state['state']=='failed' and wallet_state()==(2000,0)
    run(check())


def test_worker_requires_secret_and_isolated_context(setup,sample,monkeypatch):
    configure_worker(setup,sample,monkeypatch)
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=worker_api.app),base_url='http://worker.test') as c:
            request={'job_id':'report_0123456789','spec':{}}
            assert (await c.post('/internal/reports/execute-stream',json=request)).status_code==403
            assert (await c.post('/internal/reports/execute-stream',json=request,headers={'X-Worker-Secret':worker_api.WORKER_SECRET})).status_code==422
    run(check())


@pytest.mark.parametrize('name',['report.html','report.json','overview.png'])
def test_desktop_adapter_downloads_report_bytes(tmp_path,monkeypatch,name):
    from clients import nbppt_mcp as adapter
    raw=b'verified-test-artifact'
    real=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=raw)),**kw))
    result={'job_id':'reportshare_0123456789','task_type':'report_share','slide_count':0,
            'files':[{'path':name,'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}]}
    output=run(adapter.download_artifacts({'download_dir':str(tmp_path),'url':'https://example.test/mcp','api_key':'test'},result))
    assert Path(output['local_files'][0]).read_bytes()==raw
    assert Path(output['local_files'][0]).stat().st_mode&0o077==0


def test_desktop_adapter_rejects_private_report_files(tmp_path,monkeypatch):
    from clients import nbppt_mcp as adapter
    result={'job_id':'report_0123456789','task_type':'report','slide_count':0,
            'files':[{'path':'request.json','size':10,'sha256':'0'*64}]}
    with pytest.raises(ValueError,match='Unexpected artifact path'):
        run(adapter.download_artifacts({'download_dir':str(tmp_path),'url':'https://example.test/mcp','api_key':'test'},result))
