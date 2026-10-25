"""Offline P5 single-shot revision through the real gateway/worker/wallet.

The current customer's authorizations remain missing. This produces a marked
review draft and proves actual refusal/refund, not completed client delivery.
"""
import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gateway.exec_pitch_contract import canonical, digest


def prepare(root, registration, parent_job, runtime, probes):
    os.environ.update(json.loads(runtime.read_text()))
    prior=json.loads(registration.read_text());spec=prior['spec'];owner=spec['video_input_owner']
    package=Path(prior['registry'])/owner/prior['input_id'];value=json.loads((package/'input.json').read_text())
    os.environ.update(NBPPT_EXEC_PITCH_ROOT=prior['registry'],NBPPT_EXEC_REVIEW_ROOT=str(root/'reviews'),
                      NBPPT_EXEC_REVISION_ROOT=str(root/'cache'),NBPPT_MICROSOFT_EDGE_ENABLED='false')
    for d in ('reviews','cache'): (root/d).mkdir()
    (root/'reviews/authority.json').write_text('{}')  # No fictitious human reviewer grants.
    from gateway.exec_pitch_revision import export_parent
    plan=json.loads((parent_job/'validated_video_plan.json').read_text())
    parent_key=export_parent(parent_job,plan,root/'cache')
    old_key=value['quality']['alignment_sha256'];a=json.loads((package/'evidence'/f'{old_key}.json').read_text())
    if digest(canonical(a))!=old_key:raise ValueError('原始对齐改变')
    rechecks=json.loads(probes.read_text());evidence=canonical(rechecks);probe_key=digest(evidence)
    refined=deepcopy(a);refined['version']=2
    refined['recheck']={'parent_alignment_sha256':old_key,'evidence_sha256':probe_key}
    for s in refined['shots']:
        candidates=[t for t in rechecks['trials'] if t['shot_num']==s['shot_num']]
        s['inference_prefix_samples']=1920 if candidates else 0
        if candidates:s['units']=candidates[0]['units']
    new_alignment=digest(canonical(refined));value['quality']['alignment_sha256']=new_alignment
    from tools.exec_pitch_review import import_record
    now=datetime.now(timezone.utc)
    profile={'version':1,'previous_sha256':None,'owner':owner,'source_sha256':value['source_sha256'],
             'client_id':'unassigned-local-review','record_type':'candidate','created_at':now.isoformat(),
             'expires_at':(now+timedelta(days=30)).isoformat(),'reviewer':'待真实客户审核，来源为本轮任务约束',
             'evidence_sha256':None,'brand':'待客户确认','forbidden_terms':['车间2.0'],'required_terms':[],
             'disclosure':'external','redact_ip':True,'require_product_assets':True,'number_policy':'literal_source_only'}
    key=import_record(root/'reviews','profiles',profile);value['governance']={'profile_sha256':key}
    value['shots'][0]['motion']={'layout':'comparison','headline':'记录与现场不一致','labels':['预期库位','现场核对'],'focus':1}
    value['revision']={'parent_input_id':prior['input_id'],'parent_job_id':parent_job.name,'manifest_sha256':parent_key,
                       'operation':'replace_opening','shot_num':1}
    identity=digest(canonical(value));registry=root/'registered';destination=registry/owner/identity
    shutil.copytree(package,destination);(destination/'input.json').write_bytes(canonical(value))
    (destination/'evidence'/f'{probe_key}.json').write_bytes(evidence)
    (destination/'evidence'/f'{new_alignment}.json').write_bytes(canonical(refined))
    for t in rechecks['trials']:
        path=probes.parent/f"alignment-shot-{t['shot_num']}-pad-{t['prefix_silence_samples']}.wav"
        if digest(path.read_bytes())!=t['probe_audio_sha256']:raise ValueError('分析音频改变')
        shutil.copyfile(path,destination/'evidence'/f"{t['probe_audio_sha256']}.wav")
    os.environ['NBPPT_EXEC_PITCH_ROOT']=str(registry)
    spec={**spec,'video_input_id':identity}
    from gateway.exec_pitch_inputs import load_input
    load_input(owner,identity,spec)
    record={'registry':str(registry),'input_id':identity,'spec':spec,'parent_manifest_sha256':parent_key,
            'source':prior['source'],'alignment_sha256':new_alignment,'profile_sha256':key,'provider_calls':0}
    (root/'registration.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
    return record


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--registration',required=True)
    p.add_argument('--parent-job',required=True);p.add_argument('--runtime',required=True);p.add_argument('--probes',required=True)
    p.add_argument('--version',default='video_v11_review_only')
    args=p.parse_args();root=Path(args.root).resolve();root.mkdir(parents=True,exist_ok=False)
    record=prepare(root,Path(args.registration),Path(args.parent_job),Path(args.runtime),Path(args.probes))
    formal=root/'formal';formal.mkdir()
    os.environ.update(NBPPT_REQUIRE_ISOLATION='true',DATABASE_PATH=str(formal/'sandbox.db'),
                      NBPPT_EXEC_PITCH_ROOT=str(formal/'registry'),NBPPT_JOBS_ROOT=str(formal/'jobs'))
    def builder(registry,user):
        owner=digest(user.encode());source=Path(record['registry'])/owner/record['input_id']
        shutil.copytree(source,registry/owner/record['input_id'])
        return record['source'],record['input_id'],json.loads((source/'input.json').read_text())
    from tools.exec_pitch_acceptance import acceptance
    asyncio.run(acceptance(formal,builder=builder,milestone='P5_SINGLE_SHOT_REVISION',
                          version=args.version,expected_blocked_p4=True))


if __name__=='__main__':main()
