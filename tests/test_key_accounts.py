"""Independent tenants and live per-credential Claude authorization; no model calls."""
import asyncio
import hashlib
import json
import sqlite3

import httpx
import pytest

from gateway import auth, main
from gateway.billing_tcc import BillingManager
from gateway.delivery import delivery_urls
from gateway.mcp_server import PresentationJobs
from test_security_delivery import ADMIN, KEY_A, KEY_B, JOB, manager, prepare


def test_independent_keys_cannot_read_each_others_history_files_or_wallet(manager, monkeypatch):
    async def run():
        first = await manager.create_new_api_key(ADMIN, '客户甲')
        second = await manager.create_new_api_key(ADMIN, '客户乙')
        assert len({first['user_id'], second['user_id'], 'admin', 'a'}) == 4
        assert first['credits_available'] == 0 and not first['allow_claude']
        assert len(first['api_key']) > 40
        manifest = await prepare(manager)
        await manager.confirm_settle(JOB, .1, delivery_urls(JOB, manifest))
        # Give one independent account only test credit and its own failed job.
        with sqlite3.connect(manager.db_path) as db:
            db.execute('UPDATE users SET credits_available=60 WHERE id=?', (first['user_id'],))
        own_job = 'ppt_abcdef0123'
        await manager.try_freeze_credits(first['api_key'], own_job, 'ppt', 'private', 60)
        await manager.save_compiled_spec(own_job, {'_request': {'source':'private','template_id':'auto','slide_count':2}})
        await manager.cancel_refund(own_job, 'controlled failure')
        jobs = PresentationJobs(manager)
        monkeypatch.setattr(main, 'mcp_jobs', jobs)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='https://test') as client:
            for key, expected in ((first['api_key'], [own_job]), (second['api_key'], [])):
                headers = {'Authorization':'Bearer '+key}
                history = (await client.get('/api/jobs', headers=headers)).json()['jobs']
                assert [row['job_id'] for row in history] == expected
                wallet = (await client.get('/api/wallet', headers=headers)).json()
                assert len(wallet['api_keys']) == 1
                assert wallet['user']['user_id'] in (first['user_id'], second['user_id'])
                for target in (JOB, own_job) if key == second['api_key'] else (JOB,):
                    assert (await client.get('/api/jobs/'+target, headers=headers)).status_code == 404
                    assert (await client.get('/api/jobs/'+target+'/artifacts', headers=headers)).status_code == 404
                    assert (await client.post('/api/jobs/'+target+'/retry', json={'request_id':'cross-owner-retry'}, headers=headers)).status_code == 404
                    assert (await client.get(f'/artifacts/{target}/{target}_deck.pptx', headers=headers)).status_code == 404
                for method, path, body in (('GET','/api/wallet/keys',None),('POST','/api/wallet/keys',{'name':'escalate'}),
                                          ('PATCH','/api/wallet/keys/'+first['key_id'],{'allow_claude':True})):
                    assert (await client.request(method,path,json=body,headers=headers)).status_code == 403
            # Even the operator's account does not acquire a customer's history via ordinary job routes.
            for old_key in (KEY_A, ADMIN):
                assert (await client.get('/api/jobs/'+own_job,headers={'Authorization':'Bearer '+old_key})).status_code == 404
            principal = await auth.authenticate_key(manager, second['api_key'])
            with pytest.raises(ValueError, match='无权访问'):
                await jobs.status(principal, own_job)
            with pytest.raises(ValueError, match='无权访问'):
                await jobs.artifacts(principal, own_job)
            with pytest.raises(ValueError, match='无权访问'):
                await jobs.retry(principal, own_job, 'mcp-cross-retry')
        with sqlite3.connect(manager.db_path) as db:
            assert db.execute('SELECT credits_available,credits_frozen FROM users WHERE id=?',(second['user_id'],)).fetchone() == (0,0)
            assert db.execute('SELECT count(*) FROM credit_ledger WHERE user_id=?',(second['user_id'],)).fetchone()[0] == 0
    asyncio.run(run())


@pytest.mark.parametrize('mode', ['claude_cli', 'claude_codex'])
def test_permission_toggle_denies_rest_mcp_retry_and_legacy_before_freeze(manager, monkeypatch, mode):
    monkeypatch.setenv('NBPPT_CLAUDE_ENABLED','true')
    monkeypatch.setenv('NBPPT_CLAUDE_OWNER_USER_ID','a')
    async def run():
        jobs = PresentationJobs(manager)
        monkeypatch.setattr(main,'mcp_jobs',jobs)
        key_id = hashlib.sha256(KEY_A.encode()).hexdigest()
        principal = await auth.authenticate_key(manager, KEY_A)
        await jobs.require_claude_access(principal)
        failed = 'ppt_abcdef0123'
        await manager.try_freeze_credits(KEY_A,failed,'ppt','test',60, require_claude=True)
        await manager.save_compiled_spec(failed, {'_request': {'source':'test','template_id':'auto','slide_count':2,'execution_mode':mode}})
        await manager.cancel_refund(failed,'test failure')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='https://test') as client:
            admin = {'Authorization':'Bearer '+ADMIN}
            result = await client.patch('/api/wallet/keys/'+key_id, headers=admin, json={'allow_claude':False})
            assert result.status_code == 200 and not result.json()['allow_claude']
            # Reuse a stale authenticated principal; the DB permission must win.
            with pytest.raises(PermissionError):
                await jobs.create(principal,'test','auto',2,'disabled-direct-01',execution_mode=mode)
            with pytest.raises(PermissionError):
                await jobs.retry(principal,failed,'disabled-retry-01')
            with pytest.raises(PermissionError):
                await manager.try_freeze_credits(KEY_A,'ppt_1111111111','ppt','test',60, require_claude=True)
            headers={'Authorization':'Bearer '+KEY_A}
            cap = (await client.get('/api/capabilities',headers=headers)).json()
            assert cap['delivery_modes']['ppt']['execution_modes'] == ['codex_cli'] and 'providers' not in cap
            assert (await client.get('/api/providers/claude/status',headers=headers)).status_code == 403
            assert (await client.post('/api/jobs',headers=headers,json={'source':'test','execution_mode':mode,'request_id':'disabled-rest-01'})).status_code == 403
            assert (await client.post('/api/jobs/stream',headers=headers,json={'prompt_cn':'test','execution_mode':mode})).status_code == 403
            # Admin can restore an eligible holder's permission, but cannot grant another tenant.
            assert (await client.patch('/api/wallet/keys/'+key_id, headers=admin,json={'allow_claude':True})).status_code == 200
            await jobs.require_claude_access(principal)
            other_id = hashlib.sha256(KEY_B.encode()).hexdigest()
            assert (await client.patch('/api/wallet/keys/'+other_id,headers=admin,json={'allow_claude':True})).status_code == 200
            assert (await client.patch('/api/wallet/keys/'+key_id,headers=admin,json={'allow_claude':'false'})).status_code == 422
            registry = (await client.get('/api/wallet/keys',headers=admin)).json()
            assert KEY_A not in json.dumps(registry) and ADMIN not in json.dumps(registry)
        assert not jobs.tasks
        with sqlite3.connect(manager.db_path) as db:
            assert db.execute('SELECT credits_available,credits_frozen FROM users WHERE id="a"').fetchone() == (2000,0)
            assert db.execute('SELECT count(*) FROM media_jobs').fetchone()[0] == 1
    asyncio.run(run())


def test_create_endpoint_strict_defaults_rollback_and_revocation(manager, monkeypatch):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='https://test',headers={'Authorization':'Bearer '+ADMIN}) as client:
            for body in ({'allow_claude':'true'}, {'daily_credit_limit':True}, {'daily_credit_limit':0}, {'name':' '}):
                assert (await client.post('/api/wallet/keys',json=body)).status_code in (400,422)
            with sqlite3.connect(manager.db_path) as db:
                assert db.execute('SELECT count(*) FROM users').fetchone()[0] == 3
            response=await client.post('/api/wallet/keys',json={'name':'隔离客户'})
            assert response.status_code==200
            new=response.json()['new_key']
            assert new['user_id'] != 'admin' and new['daily_credit_limit']==240
            token=await auth.create_session(manager,new['api_key'])
            assert token
            assert (await client.post('/api/wallet/keys/revoke',json={'key_id':new['key_id']})).status_code == 200
            from fastapi import HTTPException
            with pytest.raises(HTTPException): await auth.authenticate_key(manager,new['api_key'])
            with sqlite3.connect(manager.db_path) as db:
                assert db.execute('SELECT count(*) FROM web_sessions').fetchone()[0] == 0
    asyncio.run(run())


def test_permission_migration_preserves_holder_once_and_never_reenables_disabled(manager, monkeypatch):
    monkeypatch.setenv('NBPPT_CLAUDE_OWNER_USER_ID','a')
    with sqlite3.connect(manager.db_path) as db:
        db.execute('ALTER TABLE mcp_api_keys DROP COLUMN allow_claude')
    async def run():
        migrated=BillingManager(manager.db_path,manager.jobs_root)
        await migrated.initialize()
        assert (await auth.authenticate_key(migrated,KEY_A))['allow_claude']
        assert not (await auth.authenticate_key(migrated,KEY_B))['allow_claude']
        await migrated.set_key_claude_permission(ADMIN,hashlib.sha256(KEY_A.encode()).hexdigest(),False)
        restarted=BillingManager(manager.db_path,manager.jobs_root)
        await restarted.initialize()
        assert not (await auth.authenticate_key(restarted,KEY_A))['allow_claude']
    asyncio.run(run())
