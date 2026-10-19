"""Per-key Claude grants never merge the tenant with the provider login."""
import asyncio
import hashlib
import json
import sqlite3

import httpx
import pytest

from gateway import auth,main
from gateway.delivery import delivery_urls
from gateway.mcp_server import PresentationJobs
from test_security_delivery import ADMIN,KEY_A,KEY_B,manager,make_delivery
from test_claude_generation import enabled


@pytest.mark.parametrize('mode',['claude_cli','claude_codex'])
def test_authorized_independent_tenant_uses_runtime_login_but_owns_its_bill_and_files(manager,enabled,monkeypatch,mode):
    async def run():
        a=await manager.create_new_api_key(ADMIN,'Claude 独立账户',allow_claude=True,initial_credits=120,daily_credit_limit=120)
        b=await manager.create_new_api_key(ADMIN,'无 Claude 账户',initial_credits=90)
        pa=await auth.authenticate_key(manager,a['api_key']);pb=await auth.authenticate_key(manager,b['api_key'])
        assert pa['user_id']!='a' and pb['user_id'] not in ('a',pa['user_id'])
        jobs=PresentationJobs(manager);calls=[]
        async def ready(_):pass
        async def execute(job,args):
            calls.append(args)
            spec,manifest=make_delivery(manager.jobs_root/job/'output',job)
            spec['_request']={k:v for k,v in args.items() if k!='account_owner_user_id'}
            await manager.save_compiled_spec(job,spec)
            await manager.confirm_settle(job,.85,delivery_urls(job,manifest))
        monkeypatch.setattr(jobs,'require_claude_ready',ready);monkeypatch.setattr(jobs,'execute',execute)
        monkeypatch.setattr(main,'mcp_jobs',jobs)
        with pytest.raises(PermissionError):await jobs.create(pb,'B不允许Claude','auto',2,'tenant-denied-001',execution_mode=mode)
        result=await jobs.create(pa,'A自己的产品介绍','auto',2,'tenant-allowed-001',execution_mode=mode)
        await asyncio.gather(*list(jobs.tasks))
        assert calls[0]['account_owner_user_id']=='a' and calls[0]['execution_mode']==mode
        assert calls[0]['account_owner_user_id']!=pa['user_id']
        assert (await jobs.status(pa,result['job_id']))['status']=='COMPLETED'
        assert len((await jobs.artifacts(pa,result['job_id']))['files'])==4
        with sqlite3.connect(manager.db_path) as db:
            assert db.execute('SELECT user_id,credits_charged FROM media_jobs WHERE job_id=?',(result['job_id'],)).fetchone()==(pa['user_id'],60)
            assert db.execute('SELECT credits_available,credits_frozen FROM users WHERE id=?',(pa['user_id'],)).fetchone()==(60,0)
            assert db.execute('SELECT credits_available,credits_frozen FROM users WHERE id=?',(pb['user_id'],)).fetchone()==(90,0)
            assert db.execute('SELECT credits_available FROM users WHERE id="a"').fetchone()[0]==2000
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='https://test') as client:
            for key,expected in ((a['api_key'],200),(b['api_key'],404),(KEY_A,404),(ADMIN,404)):
                headers={'Authorization':'Bearer '+key};job=result['job_id']
                assert (await client.get('/api/jobs/'+job,headers=headers)).status_code==expected
                assert (await client.get(f'/artifacts/{job}/{job}_deck.pptx',headers=headers)).status_code==expected
            assert (await client.get('/api/jobs',headers={'Authorization':'Bearer '+b['api_key']})).json()['jobs']==[]
    asyncio.run(run())


def test_permission_is_per_key_even_when_siblings_share_the_same_account(manager,enabled):
    async def run():
        sibling='test-sibling-'+'s'*40
        with sqlite3.connect(manager.db_path) as db:
            db.execute('INSERT INTO mcp_api_keys(api_key,user_id,created_at,scope,allow_claude) VALUES (?,"a","now","generate",0)',(sibling,))
        jobs=PresentationJobs(manager)
        await jobs.require_claude_access(await auth.authenticate_key(manager,KEY_A))
        with pytest.raises(PermissionError):await jobs.require_claude_access(await auth.authenticate_key(manager,sibling))
        await manager.set_key_claude_permission(ADMIN,hashlib.sha256(sibling.encode()).hexdigest(),True)
        await manager.set_key_claude_permission(ADMIN,hashlib.sha256(KEY_A.encode()).hexdigest(),False)
        await jobs.require_claude_access(await auth.authenticate_key(manager,sibling))
        with pytest.raises(PermissionError):await jobs.require_claude_access(await auth.authenticate_key(manager,KEY_A))
    asyncio.run(run())


def test_disabling_independent_key_blocks_stale_principal_and_failed_retry_before_new_freeze(manager,enabled):
    async def run():
        key=await manager.create_new_api_key(ADMIN,'独立重试账户',allow_claude=True,initial_credits=120)
        p=await auth.authenticate_key(manager,key['api_key']);job='ppt_1234567890'
        await manager.try_freeze_credits(key['api_key'],job,'ppt','原文',60,require_claude=True)
        await manager.save_compiled_spec(job,{'_request':{'source':'原文','template_id':'auto','slide_count':2,'execution_mode':'claude_codex'}})
        await manager.cancel_refund(job,'test failure')
        await manager.set_key_claude_permission(ADMIN,key['key_id'],False)
        jobs=PresentationJobs(manager)
        with pytest.raises(PermissionError):await jobs.retry(p,job,'disabled-tenant-retry')
        with pytest.raises(PermissionError):await manager.try_freeze_credits(key['api_key'],'ppt_1111111111','ppt','test',60,require_claude=True)
        with sqlite3.connect(manager.db_path) as db:
            assert db.execute('SELECT count(*) FROM media_jobs WHERE user_id=?',(p['user_id'],)).fetchone()[0]==1
            assert db.execute('SELECT credits_available,credits_frozen FROM users WHERE id=?',(p['user_id'],)).fetchone()==(120,0)
    asyncio.run(run())


def test_admin_can_preconfigure_claude_and_read_only_still_cannot_generate(manager,monkeypatch):
    monkeypatch.setenv('NBPPT_CLAUDE_ENABLED','false')
    async def run():
        k=await manager.create_new_api_key(ADMIN,'只读预授权',allow_claude=True,scope='read',initial_credits=60)
        p=await auth.authenticate_key(manager,k['api_key']);assert p['allow_claude']
        with pytest.raises(PermissionError):await PresentationJobs(manager).create(p,'test','auto',2,'readonly-claude-01',execution_mode='claude_cli')
        with pytest.raises(PermissionError):await manager.try_freeze_credits(k['api_key'],'ppt_1111111111','ppt','test',60,require_claude=True)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='https://test') as client:
            modes=(await client.get('/api/capabilities',headers={'Authorization':'Bearer '+k['api_key']})).json()['delivery_modes']['ppt']['execution_modes']
            assert modes==['codex_cli']
        with sqlite3.connect(manager.db_path) as db:assert db.execute('SELECT count(*) FROM media_jobs').fetchone()[0]==0
    asyncio.run(run())


def test_client_cannot_forge_permission_tenant_or_provider_binding(manager,enabled,monkeypatch):
    async def run():
        jobs=PresentationJobs(manager);monkeypatch.setattr(main,'mcp_jobs',jobs)
        with pytest.raises(PermissionError):await jobs.require_claude_access({'api_key':KEY_A,'user_id':'b','allow_claude':True})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='https://test') as client:
            body={'source':'test','request_id':'forged-claude-001','execution_mode':'claude_codex','allow_claude':True,'user_id':'a','account_owner_user_id':'a'}
            assert (await client.post('/api/jobs',headers={'Authorization':'Bearer '+KEY_B},json=body)).status_code==403
        with sqlite3.connect(manager.db_path) as db:assert db.execute('SELECT count(*) FROM credit_ledger').fetchone()[0]==0
    asyncio.run(run())


def test_process_exit_race_does_not_mask_claude_auth_or_rate_limit_failure(monkeypatch):
    from types import SimpleNamespace
    from worker import direct_generation
    waited=[]
    proc=SimpleNamespace(pid=12345,returncode=None)
    async def wait():waited.append(True);proc.returncode=0
    proc.wait=wait
    def missing(*_):raise ProcessLookupError('already exited')
    monkeypatch.setattr(direct_generation.os,'killpg',missing)
    asyncio.run(direct_generation.stop_process(proc))
    assert waited==[True]
