"""Local end-to-end acceptance against the authorized server's canonical Claude.

No deployment: only text inference runs remotely. API, disposable billing DB and
all rendering run locally. The operator must supply an already-authorized SSH
control path. No password, token, personal login or credential copy is stored.
"""
import argparse
import asyncio
import inspect
import json
import os
from pathlib import Path
import shlex
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def bridge_code():
    from worker.video_authoring import canonical_turn,text_command,SYSTEM
    from gateway.video_manuscript import read_json_text
    return '''import asyncio,json,os,sys,tempfile
from pathlib import Path
sys.path.insert(0,'/opt/NBPPT')
from worker.claude_account import ClaudeProfile,AccountGate,verify_login,ensure_fresh_login
from worker.claude_generation import result_cost,stop_cli
os.environ['NBPPT_CLAUDE_HOME']='/var/lib/nbppt-worker'
os.environ['NBPPT_ACCOUNT_STATE_DIR']='/var/lib/nbppt-worker/account-state'
'''+'\nSYSTEM='+repr(SYSTEM)+'\n'+inspect.getsource(text_command)+'\n'+inspect.getsource(read_json_text)+'\n'+inspect.getsource(canonical_turn)+'''
async def main():
 request=json.load(sys.stdin)
 profile=ClaudeProfile.configured();gate=AccountGate.configured(profile)
 gate.check();await verify_login('/usr/bin/claude',profile)
 async with gate.lease(timeout=60):
  cost=await ensure_fresh_login('/usr/bin/claude',profile,gate)
  with tempfile.TemporaryDirectory(prefix='nbppt-video-author-') as tmp:
   answer,used=await canonical_turn('/usr/bin/claude',profile,gate,request['prompt'],request['budget']-cost,Path(tmp),request['turn'])
   print(json.dumps({'answer':answer,'cost':used+cost},ensure_ascii=False))
asyncio.run(main())
'''


async def run(args):
    os.environ.update(NBPPT_CLAUDE_ENABLED='true',NBPPT_CLAUDE_OWNER_USER_ID='acceptance-runtime',NBPPT_MICROSOFT_EDGE_ENABLED='true')
    from gateway import main,mcp_server
    from gateway.billing_tcc import BillingManager
    from gateway.auth import authenticate_key
    from worker import worker_api,video_generation
    import httpx
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    manager=BillingManager(str(out/'test.db'),out/'jobs')
    await manager.initialize()
    # Keys exist only in this disposable local DB. Never touch a production wallet.
    key='acceptance-local-'+os.urandom(24).hex()
    other='acceptance-other-'+os.urandom(24).hex()
    with sqlite3.connect(manager.db_path) as db:
        existing=db.execute("SELECT user_id,api_key FROM mcp_api_keys").fetchall()
        if existing:
            key=dict(existing)['author'];other=dict(existing)['other']
        for uid,k in [('author',key),('other',other)]:
            db.execute("INSERT OR IGNORE INTO users(id,phone_or_email,tier,credits_available,created_at) VALUES (?,?,?,2000,'now')",(uid,uid,'studio'))
            db.execute("INSERT OR IGNORE INTO mcp_api_keys(api_key,user_id,created_at,scope,allow_claude) VALUES (?,?,'now','generate',1)",(k,uid))
    main.billing=manager;main.JOBS_ROOT=manager.jobs_root
    jobs=mcp_server.PresentationJobs(manager);main.mcp_jobs=jobs
    secret='acceptance-worker-'+os.urandom(24).hex()
    worker_api.WORKER_SECRET=secret;worker_api.WORKSPACE_JOBS_DIR=manager.jobs_root
    original_client=httpx.AsyncClient
    import socket,uvicorn
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(64)
    port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(worker_api.app,log_level='error',lifespan='off'))
    server_task=asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started: await asyncio.sleep(.05)
    mcp_server.get_runtime_settings=lambda:{'overseas_worker_url':f'http://127.0.0.1:{port}','overseas_worker_secret':secret}
    async def ready(*_):
        # Remote canonical_turn checks the live gate and official login under a lease.
        return None
    jobs.require_claude_ready=ready
    async def turn(prompt,budget,job,name):
        remote=['runuser','-u','nbppt-worker','--','/opt/NBPPT/.venv/bin/python','-c',bridge_code()]
        cmd=['ssh','-S',args.control_path,'-o','BatchMode=yes','-p','56475','root@38.97.249.8',shlex.join(remote)]
        proc=await asyncio.create_subprocess_exec(*cmd,stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        stdout,stderr=await asyncio.wait_for(proc.communicate(json.dumps({'prompt':prompt,'budget':budget,'turn':name}).encode()),300)
        (job/f'{name}_remote_stderr.log').write_bytes(stderr)
        if proc.returncode:
            raise RuntimeError('Server Claude turn failed; see private acceptance log. No automatic retry.')
        result=json.loads(stdout)
        (job/f'{name}_response.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        return result['answer'],result['cost']
    original_generate=video_generation.generate_video_stream
    def generate(*a,**kw): return original_generate(*a,**kw,author_turn=turn)
    video_generation.generate_video_stream=generate
    headers={'Authorization':'Bearer '+key}
    sources=[('auto', (out/'source-auto.txt').read_text() if (out/'source-auto.txt').exists() else '', '16:9'),
             ('solar','给光伏电站运维负责人介绍巡检助手。巡检照片和设备记录分散，异常要反复核对。系统把同一设备的照片和历史告警放在一起，帮助工程师区分新故障和旧问题。不能自动下发维修指令。工程师核查后再安排现场处理，处置结果回到设备档案。先选一个站点试点，依据漏报与误报记录决定是否推广。','9:16')]
    if args.source_file:
        sources=[('film',Path(args.source_file).read_text(),args.ratio)]
    receipts=[]
    async with original_client(transport=httpx.ASGITransport(app=main.app),base_url='http://local') as client:
        for label,source,ratio in sources:
            payload={'source':source,'task_type':'video','execution_mode':'claude_cli','video_duration_sec':args.duration, 'video_visual_mode':args.visual_mode,
                     'video_aspect_ratio':ratio,'video_voice':'microsoft_yunxi','video_narration':True,
                     'video_subtitles':True,'request_id':'acceptance-author-'+label}
            r=await client.post('/api/jobs',headers=headers,json=payload);r.raise_for_status();job=r.json()['job_id']
            previous=await jobs.status(await authenticate_key(manager,key),job)
            if previous['status']=='FAILED' and args.retry_failed:
                retry=await client.post('/api/jobs/'+job+'/retry',headers=headers,json={'request_id':'acceptance-author-'+label+'-'+args.retry_suffix})
                retry.raise_for_status();job=retry.json()['job_id']
            seen=[]
            while jobs.tasks:
                state=await jobs.status(await authenticate_key(manager,key),job)
                if not seen or seen[-1]!=state:
                    seen.append(state);print(label,state.get('stage'),state.get('percent'),flush=True)
                await asyncio.sleep(1)
            state=(await client.get('/api/jobs/'+job,headers=headers)).json()
            (out/f'{label}-progress.json').write_text(json.dumps(seen,ensure_ascii=False,indent=2))
            (out/f'{label}-state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2))
            if state['status']!='COMPLETED':
                with sqlite3.connect(manager.db_path) as db:
                    error=db.execute('SELECT error_msg FROM media_jobs WHERE job_id=?',(job,)).fetchone()[0]
                print(label,'FAILED',error,flush=True)
                receipts.append({'label':label,'job':job,'status':state,'error':error});continue
            artifact=(await client.get('/api/jobs/'+job+'/artifacts',headers=headers)).json()
            for path in artifact['artifacts'].values():
                if isinstance(path,str) and path.startswith('/artifacts/'):
                    download=await client.get(path,headers=headers);download.raise_for_status()
            isolated=(await client.get('/api/jobs/'+job,headers={'Authorization':'Bearer '+other})).status_code==404
            receipts.append({'label':label,'job':job,'status':state,'artifacts':artifact,'other_account_denied':isolated})
            print(label,'COMPLETED',job,flush=True)
    (out/'receipts.json').write_text(json.dumps(receipts,ensure_ascii=False,indent=2))
    await jobs.close()
    server.should_exit=True
    await server_task


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--control-path',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--retry-failed',action='store_true')
    parser.add_argument('--retry-suffix',default='retry1')
    parser.add_argument('--source-file')
    parser.add_argument('--duration',type=int,default=36)
    parser.add_argument('--ratio',default='16:9')
    parser.add_argument('--visual-mode',default='motion')
    asyncio.run(run(parser.parse_args()))
