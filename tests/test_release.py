import asyncio
import sqlite3
from pathlib import Path

import pytest
from test_security_delivery import manager, KEY_A, balance
from worker import isolation


def test_queue_and_daily_limits_atomic(manager, monkeypatch):
    monkeypatch.setenv('NBPPT_MAX_USER_RUNNING', '1')
    async def scenario():
        await manager.try_freeze_credits(KEY_A, 'ppt_1111111111', 'ppt', 'test', 60)
        with pytest.raises(ValueError, match='队列'):
            await manager.try_freeze_credits(KEY_A, 'ppt_2222222222', 'ppt', 'test', 60)
        assert balance(manager) == (1940,60)
        await manager.cancel_refund('ppt_1111111111','test')
        monkeypatch.setenv('NBPPT_DAILY_CREDITS', '60')
        with pytest.raises(ValueError, match='额度'):
            await manager.try_freeze_credits(KEY_A, 'ppt_2222222222', 'ppt', 'test', 60)
        assert balance(manager) == (2000,0)
    asyncio.run(scenario())


def test_isolation_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv('NBPPT_REQUIRE_ISOLATION','true')
    monkeypatch.setattr(isolation.os,'geteuid',lambda:0)
    with pytest.raises(RuntimeError,match='non-root'):
        isolation.isolated_command(['/usr/bin/codex'], tmp_path, [])


def test_isolation_mounts_only_current_job_and_allowed_runtime(monkeypatch,tmp_path):
    monkeypatch.setenv('NBPPT_REQUIRE_ISOLATION','true')
    monkeypatch.setattr(isolation.sys,'platform','linux')
    monkeypatch.setattr(isolation.os,'geteuid',lambda:1001)
    monkeypatch.setattr(isolation.shutil,'which',lambda _: '/usr/bin/bwrap')
    home=tmp_path/'worker'
    (home/'.codex').mkdir(parents=True)
    (home/'.codex/auth.json').write_text('{}')
    monkeypatch.setattr(isolation.Path,'home',classmethod(lambda _:home))
    job=tmp_path/'jobs/ppt_1111111111'
    job.mkdir(parents=True)
    cmd,_=isolation.isolated_command(['/usr/bin/codex','exec','prompt'],job,[])
    assert '--clearenv' in cmd and '--unshare-pid' in cmd and '--die-with-parent' in cmd
    assert str(job.resolve()) in cmd
    assert str(job.parent) not in cmd and '/root' not in cmd and '/etc/nbppt' not in cmd
    assert cmd.count('--bind')==2


def test_client_scope_and_revocation(manager):
    import hashlib
    import httpx
    from gateway import main, auth
    from test_security_delivery import ADMIN
    async def scenario():
        child = (await manager.create_new_api_key(ADMIN, 'desktop'))['api_key']
        principal = await auth.authenticate_key(manager, child)
        assert principal['tier'] == 'studio' and principal['scope'] == 'generate'
        token = await auth.create_session(manager, child)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='https://test') as client:
            for path, body in [('/api/wallet/topup', {'amount': 1}), ('/api/wallet/keys', {'name':'x'}), ('/api/settings/models', {})]:
                response=await client.post(path,headers={'Authorization':'Bearer '+child},json=body)
                assert response.status_code == 403
        admin=await auth.authenticate_key(manager, ADMIN)
        await manager.revoke_api_key(admin, hashlib.sha256(child.encode()).hexdigest())
        from fastapi import HTTPException
        with pytest.raises(HTTPException): await auth.authenticate_key(manager, child)
        with sqlite3.connect(manager.db_path) as db:
            assert db.execute('SELECT count(*) FROM web_sessions').fetchone()[0] == 0
    asyncio.run(scenario())


def test_download_replaces_hardlink_privately(tmp_path, monkeypatch):
    import hashlib
    import os
    import httpx
    from clients import nbppt_mcp as adapter
    job='ppt_1234567890'; name=job+'_deck.pptx'; data=b'verified-pptx'
    directory=tmp_path/job; directory.mkdir()
    unrelated=tmp_path/'unrelated'; unrelated.write_bytes(b'original')
    os.link(unrelated, directory/name)
    real=httpx.AsyncClient
    monkeypatch.setattr(adapter.httpx, 'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=data)),**kw))
    result={'job_id':job,'slide_count':1,'files':[{'path':name,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}]}
    asyncio.run(adapter.download_artifacts({'download_dir':str(tmp_path),'url':'https://example.test/mcp','api_key':'x'*40}, result))
    assert unrelated.read_bytes() == b'original'
    assert (directory/name).read_bytes() == data
    assert (directory/name).stat().st_mode & 0o077 == 0
