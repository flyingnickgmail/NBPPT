"""Admin account UI endpoints, auditable credit adjustment and isolation."""
import asyncio
import hashlib
import json
import sqlite3

import httpx
import pytest

from gateway import auth, main
from test_security_delivery import ADMIN,KEY_A,KEY_B,manager

ADMIN_HEADERS={'Authorization':'Bearer '+ADMIN}


def test_admin_create_manage_audit_and_idempotency(manager,monkeypatch):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='https://test',headers=ADMIN_HEADERS) as client:
            payload={'name':'产品测试','initial_credits':180,'daily_credit_limit':180,'scope':'generate','request_id':'admin-create-0001'}
            first=await client.post('/api/admin/keys',json=payload)
            assert first.status_code==200
            key=first.json()['new_key']; key_id=key['key_id']
            assert key['credits_available']==180 and not key['allow_claude'] and key['user_id']!='admin'
            assert (await client.post('/api/admin/keys',json=payload)).json()==first.json()
            assert (await client.post('/api/admin/keys',json={**payload,'initial_credits':999})).status_code==422
            patch={'name':'产品只读','daily_credit_limit':120,'scope':'read','request_id':'admin-update-0001'}
            assert (await client.patch('/api/admin/keys/'+key_id,json=patch)).status_code==200
            assert (await client.patch('/api/admin/keys/'+key_id,json=patch)).status_code==200
            add={'delta':60,'note':'测试分配','request_id':'admin-credit-0001'}
            result=await client.post('/api/admin/keys/'+key_id+'/credits',json=add)
            assert result.status_code==200 and result.json()['credits_available']==240
            assert (await client.post('/api/admin/keys/'+key_id+'/credits',json=add)).json()==result.json()
            assert (await client.post('/api/admin/keys/'+key_id+'/credits',json={**add,'delta':600})).status_code==422
            listing=await client.get('/api/admin/keys')
            row=next(k for k in listing.json()['keys'] if k['key_id']==key_id)
            assert row['credits_available']==240 and row['scope']=='read' and row['effective_daily_limit']==120
            assert key['api_key'] not in listing.text and ADMIN not in listing.text
            audit=await client.get('/api/admin/actions')
            assert len(audit.json()['actions'])==3 and key['api_key'] not in audit.text and ADMIN not in audit.text
            with sqlite3.connect(manager.db_path) as db:
                assert db.execute('SELECT count(*) FROM users').fetchone()[0]==4
                ledger=db.execute("SELECT amount,balance_after FROM credit_ledger WHERE user_id=? ORDER BY id",(key['user_id'],)).fetchall()
                assert ledger==[(180,180),(60,240)]
                assert db.execute('SELECT credits_available FROM users WHERE id="admin"').fetchone()[0]==2000
            token=await auth.create_session(manager,key['api_key']);assert token
            revoke={'request_id':'admin-revoke-0001'}
            assert (await client.post('/api/admin/keys/'+key_id+'/revoke',json=revoke)).status_code==200
            assert (await client.post('/api/admin/keys/'+key_id+'/revoke',json=revoke)).status_code==200
            assert (await client.post('/api/admin/keys',json=payload)).status_code==422
            assert (await client.get('/api/session',headers={'Authorization':'Bearer '+key['api_key']})).status_code==401
            with sqlite3.connect(manager.db_path) as db:
                assert db.execute('SELECT count(*) FROM web_sessions').fetchone()[0]==0
                assert db.execute('SELECT count(*) FROM users').fetchone()[0]==4
    asyncio.run(run())


def test_credit_adjustment_concurrency_never_spends_frozen_points(manager):
    async def run():
        await manager.try_freeze_credits(KEY_A,'ppt_1111111111','ppt','test',60)
        key_id=hashlib.sha256(KEY_A.encode()).hexdigest()
        results=await asyncio.gather(*(manager.adjust_managed_credits(ADMIN,key_id,60,'同一笔网络重试','concurrent-credit-01') for _ in range(3)))
        assert all(r['credits_available']==2000 and r['credits_frozen']==60 for r in results)
        with pytest.raises(ValueError,match='减额超过'):
            await manager.adjust_managed_credits(ADMIN,key_id,-2001,'错误减额','invalid-credit-001')
        await manager.adjust_managed_credits(ADMIN,key_id,-2000,'归还可用余额','subtract-credit-01')
        with sqlite3.connect(manager.db_path) as db:
            assert db.execute('SELECT credits_available,credits_frozen FROM users WHERE id="a"').fetchone()==(0,60)
            assert db.execute("SELECT count(*) FROM credit_ledger WHERE action='ADMIN_ADJUST'").fetchone()[0]==2
        await manager.cancel_refund('ppt_1111111111','controlled failure')
        with sqlite3.connect(manager.db_path) as db:
            assert db.execute('SELECT credits_available,credits_frozen FROM users WHERE id="a"').fetchone()==(60,0)
    asyncio.run(run())


@pytest.mark.parametrize('headers',[{}, {'Authorization':'Bearer '+KEY_A},{'Authorization':'Bearer '+KEY_B}])
def test_admin_pages_and_every_management_operation_require_admin(manager,headers):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='https://test') as client:
            key_id=hashlib.sha256(KEY_A.encode()).hexdigest()
            for path in ('/admin','/static/admin.html'):
                r=await client.get(path,headers=headers)
                assert r.status_code==(303 if not headers else 403)
                assert 'Cache-Control' in r.headers
            for method,path,body in [
                ('GET','/api/admin/keys',None),('GET','/api/admin/actions',None),
                ('POST','/api/admin/keys',{'name':'bad','request_id':'unauthorized-create'}),
                ('PATCH','/api/admin/keys/'+key_id,{'scope':'read','request_id':'unauthorized-change'}),
                ('POST','/api/admin/keys/'+key_id+'/credits',{'delta':100,'note':'bad','request_id':'unauthorized-credit'}),
                ('POST','/api/admin/keys/'+key_id+'/revoke',{'request_id':'unauthorized-revoke'})]:
                assert (await client.request(method,path,headers=headers,json=body)).status_code==(401 if not headers else 403)
            with sqlite3.connect(manager.db_path) as db:
                assert db.execute('SELECT count(*) FROM admin_actions').fetchone()[0]==0
    asyncio.run(run())


def test_admin_cookie_csrf_and_current_admin_protection(manager,monkeypatch):
    monkeypatch.setenv('NBPPT_PUBLIC_ORIGIN','https://test')
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='https://test') as client:
            assert (await client.post('/api/session',json={'api_key':ADMIN})).status_code==200
            page=await client.get('/admin');assert page.status_code==200
            assert "script-src 'self'" in page.headers['content-security-policy']
            assert '账户与访问管理' in page.text and 'https://cdn.' not in page.text
            key_id=hashlib.sha256(ADMIN.encode()).hexdigest()
            for headers in ({},{'Origin':'https://evil.test'}):
                assert (await client.post('/api/admin/keys',headers=headers,json={'request_id':'csrf-create-0001'})).status_code==403
                assert (await client.patch('/api/admin/keys/'+key_id,headers=headers,json={'request_id':'csrf-update-0001','scope':'read'})).status_code==403
            good={'Origin':'https://test'}
            assert (await client.patch('/api/admin/keys/'+key_id,headers=good,json={'request_id':'protect-admin-001','scope':'read'})).status_code==403
            assert (await client.post('/api/admin/keys/'+key_id+'/revoke',headers=good,json={'request_id':'protect-admin-002'})).status_code==422
            assert (await client.get('/api/session')).json()['admin'] is True
    asyncio.run(run())


@pytest.mark.parametrize('body',[
    {'delta':True,'note':'bad'}, {'delta':0,'note':'bad'}, {'delta':1.5,'note':'bad'},
    {'delta':1000001,'note':'bad'}, {'delta':10,'note':' '}, {'delta':10,'note':'ok','unexpected':True},
])
def test_invalid_adjustments_are_atomic_and_strict(manager,body):
    async def run():
        key_id=hashlib.sha256(KEY_A.encode()).hexdigest()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='https://test',headers=ADMIN_HEADERS) as client:
            assert (await client.post('/api/admin/keys/'+key_id+'/credits',json={'request_id':'invalid-adjust-0001',**body})).status_code==422
        with sqlite3.connect(manager.db_path) as db:
            assert db.execute('SELECT credits_available FROM users WHERE id="a"').fetchone()[0]==2000
            assert db.execute('SELECT count(*) FROM credit_ledger').fetchone()[0]==0
    asyncio.run(run())


def test_admin_cannot_grant_claude_to_unbound_accounts_or_reset_daily_usage(manager,monkeypatch):
    monkeypatch.setenv('NBPPT_CLAUDE_ENABLED','true');monkeypatch.setenv('NBPPT_CLAUDE_OWNER_USER_ID','a')
    async def run():
        key_a=hashlib.sha256(KEY_A.encode()).hexdigest();key_b=hashlib.sha256(KEY_B.encode()).hexdigest()
        await manager.try_freeze_credits(KEY_A,'ppt_1111111111','ppt','test',60)
        await manager.cancel_refund('ppt_1111111111','test')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='https://test',headers=ADMIN_HEADERS) as client:
            assert (await client.patch('/api/admin/keys/'+key_b,json={'request_id':'claude-grant-0001','allow_claude':True})).status_code==403
            assert (await client.patch('/api/admin/keys/'+key_a,json={'request_id':'claude-revoke-001','allow_claude':False,'daily_credit_limit':40})).status_code==200
            row=next(k for k in (await client.get('/api/admin/keys')).json()['keys'] if k['key_id']==key_a)
            assert row['daily_spent']==60 and row['effective_daily_limit']==40 and not row['allow_claude']
            assert row['claude_eligible']
        with pytest.raises(ValueError,match='额度'):
            await manager.try_freeze_credits(KEY_A,'ppt_2222222222','ppt','test',60)
        from gateway.mcp_server import PresentationJobs
        with pytest.raises(PermissionError):
            await PresentationJobs(manager).create({'api_key':KEY_A,'user_id':'a'},'test','auto',2,'disabled-claude-key',execution_mode='claude_cli')
    asyncio.run(run())
