"""Reproducible P0 sandbox: real HTTP gateway, loopback worker and actual media.

No production DB, account credentials, CLI planning, network media or TTS calls.
Run from the repository: python tools/exec_pitch_acceptance.py --root workspace/exec-pitch-p0
The destination must be new. Earlier video_vN outputs are never overwritten.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


async def acceptance(root, *, builder=None, milestone='P0', version='video_v1', aspect_ratio='16:9', expected_blocked_p4=False):
    from tools.exec_pitch_fixture import build_fixture
    from gateway.exec_pitch_contract import digest
    source,input_id,value=(builder or build_fixture)(root/'registry','sandbox-nick')
    total_frames=sum((s['audio_samples']+1999)//2000+s['lead_frames']+s['tail_frames'] for s in value['shots'])
    assert total_frames%24==0
    seconds=total_frames//24
    from gateway.billing_tcc import BillingManager
    from gateway import main, mcp_server
    from gateway.mcp_server import PresentationJobs
    import httpx
    manager=BillingManager(str(root/'sandbox.db'),root/'jobs');await manager.initialize()
    key=secrets.token_urlsafe(40);other=secrets.token_urlsafe(40)
    with sqlite3.connect(manager.db_path) as db:
        for user,token in [('sandbox-nick',key),('sandbox-other',other)]:
            db.execute("INSERT INTO users(id,phone_or_email,tier,credits_available,created_at) VALUES (?,?,'studio',2000,'sandbox')",(user,user))
            db.execute("INSERT INTO mcp_api_keys(api_key,user_id,created_at,scope) VALUES (?,?,'sandbox','generate')",(token,user))
    jobs=PresentationJobs(manager);main.billing=manager;main.mcp_jobs=jobs;main.JOBS_ROOT=manager.jobs_root
    secret=secrets.token_urlsafe(40)
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();port=listener.getsockname()[1]
    env={**os.environ,'OVERSEAS_WORKER_SECRET':secret,'NBPPT_JOBS_ROOT':str(manager.jobs_root),
         'NBPPT_REQUIRE_ISOLATION':'true','NBPPT_EXEC_PITCH_ROOT':str(root/'registry')}
    mcp_server.get_runtime_settings=lambda:{'overseas_worker_url':f'http://127.0.0.1:{port}','overseas_worker_secret':secret}
    worker_log=(root/'worker.log').open('wb')
    process=subprocess.Popen([sys.executable,'-m','uvicorn','worker.worker_api:app','--fd',str(listener.fileno()),
                              '--no-access-log'],pass_fds=(listener.fileno(),),env=env,stdout=worker_log,stderr=worker_log)
    try:
        async with httpx.AsyncClient(trust_env=False) as network:
            for _ in range(100):
                if process.poll() is not None: raise RuntimeError('Sandbox worker startup failed; inspect worker.log')
                try:
                    response=await network.get(f'http://127.0.0.1:{port}/openapi.json',timeout=.2)
                    if response.status_code==404: break
                except httpx.HTTPError: pass
                await asyncio.sleep(.1)
            else: raise TimeoutError('Sandbox worker did not start')
        listener.close()
        headers={'Authorization':'Bearer '+key}
        payload={'source':source,'request_id':f'exec-pitch-{milestone.lower()}-{version}','task_type':'video','execution_mode':'auto',
                 'video_duration_sec':seconds,'video_aspect_ratio':aspect_ratio,'video_preset':'exec_pitch','video_input_id':input_id,
                 'video_voice':'approved_local','video_narration':True,'video_visual_mode':'registered_local','video_subtitles':True}
        (root/'request.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2))
        (root/'source.md').write_text(source)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://sandbox') as client:
            response=await client.post('/api/jobs',headers=headers,json=payload);response.raise_for_status();created=response.json()
            repeated=await client.post('/api/jobs',headers=headers,json=payload)
            assert repeated.json()['job_id']==created['job_id']
            previous=None;started=time.monotonic();progress=[]
            while jobs.tasks:
                state=(await client.get('/api/jobs/'+created['job_id'],headers=headers)).json()
                snapshot={k:state.get(k) for k in ('status','stage','percent','message')}
                if snapshot!=previous:
                    progress.append(snapshot);print(json.dumps(snapshot,ensure_ascii=False),flush=True);previous=snapshot
                await asyncio.sleep(2)
                if time.monotonic()-started>21600: raise TimeoutError('Sandbox deadline exceeded')
            state=(await client.get('/api/jobs/'+created['job_id'],headers=headers)).json()
            (root/'state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2))
            if state['status']!='COMPLETED':
                if expected_blocked_p4:
                    import shutil
                    assert state['status']=='FAILED'
                    job=manager.jobs_root/created['job_id'];staging=job/'staging'
                    qa=json.loads((staging/'p4_qa.json').read_text())
                    assert qa['FILE_OK']['status']=='PASSED' and qa['delivery_status']=='BLOCKED'
                    assert not (job/'output').exists()
                    with sqlite3.connect(manager.db_path) as db:
                        wallet=db.execute("SELECT credits_available,credits_frozen FROM users WHERE id='sandbox-nick'").fetchone()
                    assert wallet==(2000,0) and state.get('credits_charged',0)==0
                    rejected=await client.get('/api/jobs/'+created['job_id']+'/artifacts',headers=headers)
                    assert rejected.status_code>=400
                    draft=root/version;shutil.copytree(staging,draft)
                    facts={'milestone':milestone,'job_id':created['job_id'],'status':'BLOCKED_REVIEW_ONLY',
                           'job_status':state['status'],'gateway_artifact_status':rejected.status_code,
                           'published':False,'credits_charged':0,'wallet':{'available':2000,'frozen':0},
                           'external_provider_calls':0,'content_status':'NOT_REVIEWED',
                           'video_sha256':digest((draft/f"{created['job_id']}_video.mp4").read_bytes())}
                    (draft/'facts.json').write_text(json.dumps(facts,ensure_ascii=False,indent=2))
                    (root/'progress.json').write_text(json.dumps(progress,ensure_ascii=False,indent=2))
                    print(json.dumps(facts,ensure_ascii=False),flush=True)
                    return facts
                raise RuntimeError('Sandbox draft failed; inspect state.json, jobs/* logs and database error_log')
            artifacts=await client.get('/api/jobs/'+created['job_id']+'/artifacts',headers=headers)
            artifacts.raise_for_status();artifacts=artifacts.json()
            path=artifacts['artifacts']['mp4_url']
            assert (await client.get(path)).status_code==401
            assert (await client.get(path,headers={'Authorization':'Bearer '+other})).status_code==404
            partial=await client.get(path,headers={**headers,'Range':'bytes=0-1023'})
            assert partial.status_code==206 and len(partial.content)==1024
            downloaded=await client.get(path,headers=headers);downloaded.raise_for_status()
            receipt=next(f for f in artifacts['files'] if f['path'].endswith('.mp4'))
            assert digest(downloaded.content)==receipt['sha256']
        output=manager.jobs_root/created['job_id']/'output'
        draft=root/version;draft.mkdir(exist_ok=False)
        # Keep the published job intact; link its independently verified immutable outputs.
        for f in artifacts['files']:
            destination=draft/f['path'];destination.parent.mkdir(parents=True,exist_ok=True)
            os.link(output/f['path'],destination)
        facts={'milestone':milestone,'job_id':created['job_id'],'duration_seconds':seconds,'sections':len(value['sections']),
               'shots':len(value['shots']),'media_kind':value['media_kind'],'external_provider_calls':0,
               'external_provider_cost_usd':0,'local_compute_cost':'unpriced','content_status':'NOT_REVIEWED',
               'download_sha256':receipt['sha256'],'checks':{'idempotency':True,'anonymous_401':True,'other_account_404':True,
               'range_206':True,'download_hash':True,'encoded_audio_beats':True},'elapsed_seconds':round(time.monotonic()-started,2)}
        (draft/'facts.json').write_text(json.dumps(facts,ensure_ascii=False,indent=2))
        (draft/'artifacts.json').write_text(json.dumps(artifacts,ensure_ascii=False,indent=2))
        (root/'progress.json').write_text(json.dumps(progress,ensure_ascii=False,indent=2))
        (draft/'REPORT.md').write_text(f'''# {milestone} 工程草稿

真实应用链路：HTTP 创建与重复提交 → 现有任务管理与钱包冻结 → 环回 HTTP Worker → 已登记因果稿、口播节拍与本地音频 → 串行可信剪辑 → 字幕烧录 → 独立完整解码与响度校验 → 原子发布 → 独立复检后结算 → 鉴权与 Range 下载。

时长：{seconds}秒；口播段落：{len(value['sections'])}；镜头：{len(value['shots'])}。单一时钟为24帧每秒，音频为48000采样每秒。各镜头由实际音频样本数、向上取整不足一帧的余量及明确声音前后留量构成；镜头长短随节拍变化，并非平均分配。timeline.json 为机器可读时间轴，source_manifest.json 为来源事实。

输入类型：{value['media_kind']}。证据边界：{value['evidence_boundary']}。没有请求模型、在线声音或素材服务。服务商调用及费用为零，本地计算成本未计价。沙盒钱包沿用现有80点冻结与最低70%结算规则；不声称生产价格覆盖长片成本。

文件校验通过，内容状态仍为 NOT_REVIEWED（待人工审阅）。未证明客户素材、品牌规则、逐字同步、影视叙事或长城/现代参考片质量。{'P3混音配置已执行，最终编码须通过−17至−15 LUFS、真峰值≤−3.8 dBTP检查。' if value.get('voice_mix',{}).get('profile')=='exec_pitch_p3' else '本输入未启用P3更严混音配置。'}P4/P5的独立画面/客户规则门槛未由本报告代验。

执行入口：python tools/exec_pitch_acceptance.py --root <全新沙盒目录>。当前输入 request.json、状态 state.json、进度 progress.json 与 jobs 日志保存在上级目录。该目录含沙盒随机凭证数据库，请勿对外分享；{version} 可独立审阅。

未推送、未部署、未访问生产、未重启既有服务、未改账号额度。当前里程碑完成后停止，等待下一条指令。
''')
        print(json.dumps(facts,ensure_ascii=False),flush=True)
    finally:
        await jobs.close();process.terminate()
        try: process.wait(timeout=10)
        except subprocess.TimeoutExpired: process.kill();process.wait(timeout=5)
        listener.close();worker_log.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True)
    args=parser.parse_args();root=Path(args.root).resolve();root.mkdir(parents=True,exist_ok=False)
    os.environ.update(NBPPT_REQUIRE_ISOLATION='true',DATABASE_PATH=str(root/'sandbox.db'),
                      NBPPT_EXEC_PITCH_ROOT=str(root/'registry'),NBPPT_JOBS_ROOT=str(root/'jobs'))
    asyncio.run(acceptance(root))


if __name__=='__main__': main()
