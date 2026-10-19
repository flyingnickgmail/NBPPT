"""Use real OS processes/locks, but never real accounts or credentials."""
import asyncio
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import time

import pytest

from worker.claude_account import AccountGate, ClaudeProfile, ProviderUnavailable
from tools.claude_account import duplicate_profiles, retire_duplicates


def child_lease(root, queue, hold=0.15, crash=False):
    async def run():
        gate=AccountGate('claude-sameaccount',root)
        async with gate.lease(timeout=3):
            queue.put(('enter',os.getpid(),time.monotonic()))
            if crash:
                queue.close();queue.join_thread();os._exit(0)
            await asyncio.sleep(hold)
            queue.put(('exit',os.getpid(),time.monotonic()))
    asyncio.run(run())


def test_multiprocess_mutual_exclusion_and_crash_release(tmp_path):
    root=tmp_path/'state';AccountGate('claude-sameaccount',root)
    ctx=multiprocessing.get_context('spawn');queue=ctx.Queue()
    processes=[ctx.Process(target=child_lease,args=(root,queue)) for _ in range(3)]
    for p in processes:p.start()
    events=[queue.get(timeout=8) for _ in range(6)]
    for p in processes:p.join(8);assert p.exitcode==0
    assert [x[0] for x in events]==['enter','exit']*3
    crash=ctx.Process(target=child_lease,args=(root,queue,.15,True));crash.start()
    assert queue.get(timeout=8)[0]=='enter'
    crash.join(8);assert crash.exitcode==0
    async def acquire():
        async with AccountGate('claude-sameaccount',root).lease(timeout=.5): pass
    asyncio.run(acquire())


def test_waiting_lease_rechecks_circuit_and_cancellation_releases(tmp_path):
    gate=AccountGate('claude-sameaccount',tmp_path/'state')
    async def run():
        async with gate.lease():
            async def wait():
                async with AccountGate('claude-sameaccount',gate.root).lease():pytest.fail('circuit bypass')
            pending=asyncio.create_task(wait());await asyncio.sleep(.02)
            with pytest.raises(ProviderUnavailable):gate.record_event({'type':'system','subtype':'api_retry','error_status':401})
        with pytest.raises(ProviderUnavailable):await pending
        await gate.reset()
        entered=asyncio.Event()
        async def hold():
            async with gate.lease():entered.set();await asyncio.Event().wait()
        task=asyncio.create_task(hold());await entered.wait();task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        async with gate.lease(timeout=.1):pass
    asyncio.run(run())


@pytest.mark.parametrize('event,state', [
    ({'type':'system','subtype':'api_retry','error_status':429,'retry_delay_ms':120000},'cooldown'),
    ({'type':'system','subtype':'api_retry','error_status':403,'error':'account_on_hold'},'blocked'),
    ({'type':'system','subtype':'api_retry','error':'billing_error'},'blocked'),
    ({'type':'rate_limit_event','rate_limit_info':{'status':'rejected','resetsAt':None}},'blocked'),
    ({'type':'rate_limit_event','rate_limit_info':{'status':'rejected','resetsAt':time.time()+3600}},'cooldown'),
    ({'type':'result','subtype':'error_during_execution','is_error':True,'result':'You have hit your limit. private-fake-token'},'blocked'),
])
def test_rejection_persists_across_restart_without_secrets(tmp_path,event,state):
    gate=AccountGate('claude-test',tmp_path/'state')
    with pytest.raises(ProviderUnavailable):gate.record_event(event)
    restarted=AccountGate('claude-test',gate.root)
    assert restarted.status()['state']==state
    assert 'private-fake-token' not in gate.state_path.read_text()
    with pytest.raises(ProviderUnavailable):restarted.check()
    asyncio.run(restarted.reset());assert gate.status()['state']=='ready'


def test_overload_warning_does_not_block_and_expired_cooldown_is_ready(tmp_path):
    gate=AccountGate('claude-test',tmp_path/'state')
    gate.record_event({'type':'system','subtype':'api_retry','error_status':529,'error':'overloaded_error'})
    gate.record_event({'type':'rate_limit_event','rate_limit_info':{'status':'allowed_warning'}})
    assert gate.status()['state']=='ready'
    gate._write({'state':'cooldown','until':time.time()-1,'strikes':1})
    assert gate.status()['state']=='ready'


@pytest.mark.parametrize('defect',['json','link','hardlink','permissions','strikes','nonfinite'])
def test_corrupt_or_exposed_state_fails_closed(tmp_path,defect):
    gate=AccountGate('claude-test',tmp_path/'state')
    gate._write({'state':'ready','until':0})
    if defect=='json':gate.state_path.write_text('{')
    if defect=='link':
        gate.state_path.unlink();gate.state_path.symlink_to(tmp_path/'absent')
    if defect=='hardlink':os.link(gate.state_path,tmp_path/'linked')
    if defect=='permissions':gate.state_path.chmod(0o644)
    if defect=='strikes':gate._write({'state':'ready','strikes':'bad'})
    if defect=='nonfinite':gate._write({'state':'cooldown','until':float('nan')})
    with pytest.raises(ValueError):gate.check()


def test_same_account_profiles_share_identity_and_retirement_never_copies(tmp_path,monkeypatch):
    homes=[]
    for i,account in enumerate(('same','same','different')):
        home=tmp_path/str(i);(home/'.claude').mkdir(parents=True,mode=0o700)
        (home/'.claude.json').write_text(json.dumps({'oauthAccount':{'accountUuid':account}}))
        p=home/'.claude/.credentials.json';p.write_text(json.dumps({'fake-token':str(i)}));p.chmod(0o600)
        homes.append(home)
    monkeypatch.setenv('NBPPT_CLAUDE_HOME',str(homes[0]));a=ClaudeProfile.configured()
    monkeypatch.setenv('NBPPT_CLAUDE_HOME',str(homes[1]));b=ClaudeProfile.configured()
    assert a.account_id==b.account_id
    digest=hashlib.sha256(a.credentials.read_bytes()).hexdigest()
    assert duplicate_profiles(a,homes)==[b.credentials]  # rotated same-account copy still found
    gate=AccountGate(a.account_id,tmp_path/'state')
    async def held():
        async with gate.lease():
            with pytest.raises(ValueError):retire_duplicates(a,homes,gate)
    asyncio.run(held())
    retired=retire_duplicates(a,homes,gate)
    assert len(retired)==1 and not b.credentials.exists()
    assert Path(retired[0]).exists() and Path(retired[0]).stat().st_mode&0o777==0o600
    assert hashlib.sha256(a.credentials.read_bytes()).hexdigest()==digest
    assert (homes[2]/'.claude/.credentials.json').exists()

@pytest.mark.parametrize('method,provider,logged', [('none','firstParty',False),('api_key','firstParty',True),('oauth_token','thirdParty',True),('claude.ai','firstParty',True)])
def test_auth_preflight_ignores_user_configuration(tmp_path,method,provider,logged):
    from worker.claude_account import verify_login
    import sys
    script=tmp_path/'claude'
    script.write_text('#!'+sys.executable+'\nimport sys,json\nassert "--restricted" in sys.argv and "--safe-mode" in sys.argv\nassert sys.argv[sys.argv.index("--setting-sources")+1]==""\nprint('+repr(json.dumps({'loggedIn':logged,'apiProvider':provider,'authMethod':method}))+')\n')
    script.chmod(0o700)
    profile=ClaudeProfile(tmp_path,'claude-test')
    if method=='claude.ai':asyncio.run(verify_login(str(script),profile))
    else:
        with pytest.raises(ProviderUnavailable):asyncio.run(verify_login(str(script),profile))


def test_http_auth_failure_never_persists_an_arbitrary_provider_error(tmp_path):
    gate=AccountGate('claude-test',tmp_path/'state')
    with pytest.raises(ProviderUnavailable):gate.record_event({'type':'system','subtype':'api_retry','error_status':403,'error':'fake-secret-provider-payload'})
    assert json.loads(gate.state_path.read_text())['reason']=='authentication_failed'
    assert 'fake-secret' not in gate.state_path.read_text()


def test_managed_callers_require_explicit_shared_configuration(tmp_path,monkeypatch):
    monkeypatch.delenv('NBPPT_CLAUDE_HOME',raising=False)
    with pytest.raises(ValueError,match='NBPPT_CLAUDE_HOME'):ClaudeProfile.configured()
    monkeypatch.delenv('NBPPT_ACCOUNT_STATE_DIR',raising=False)
    profile=ClaudeProfile(tmp_path,'claude-test')
    with pytest.raises(ValueError,match='NBPPT_ACCOUNT_STATE_DIR'):AccountGate.configured(profile)
    monkeypatch.setenv('NBPPT_ACCOUNT_STATE_DIR',str(tmp_path/'shared'))
    gate=AccountGate.configured(profile)
    assert gate.root==tmp_path/'shared'


def test_root_maintenance_preserves_state_owner(tmp_path,monkeypatch):
    gate=AccountGate('claude-test',tmp_path/'state');owner=gate.root.stat();calls=[]
    monkeypatch.setattr(os,'geteuid',lambda:0)
    monkeypatch.setattr(os,'fchown',lambda fd,uid,gid:calls.append((uid,gid)))
    fd=gate._open_lock();os.close(fd);gate._write({'state':'ready','until':0})
    assert calls==[(owner.st_uid,owner.st_gid)]*2
