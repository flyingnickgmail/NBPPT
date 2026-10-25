"""Actual P6 story/voice reuse through ordinary creation, rendering and refusal.

No planner/provider/TTS/download path. Customer approvals remain unavailable.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gateway.exec_pitch_contract import canonical,digest


def prepare(root,registration,runtime):
    os.environ.update(json.loads(runtime.read_text()))
    prior=json.loads(registration.read_text());spec=prior['spec'];owner=spec['video_input_owner']
    parent=Path(prior['registry'])/owner/prior['input_id']
    from gateway.exec_pitch_inputs import safe_file
    old=json.loads(safe_file(parent,'input.json',128*1024).read_text())
    if digest(canonical(old))!=prior['input_id']:raise ValueError('父版本登记稿发生变化')
    from tools.exec_pitch_story import refine_parcel_story
    value=refine_parcel_story(old,prior['input_id'],spec)
    registry=root/'registered';parent_copy=registry/owner/prior['input_id'];shutil.copytree(parent,parent_copy)
    identity=digest(canonical(value));target=registry/owner/identity;shutil.copytree(parent,target)
    (target/'input.json').write_bytes(canonical(value))
    reviews=registration.parent/'reviews'
    if not reviews.is_dir() or reviews.is_symlink():raise ValueError('父版本审核配置缺失或不安全')
    shutil.copytree(reviews,root/'reviews',symlinks=True)
    os.environ.update(NBPPT_EXEC_PITCH_ROOT=str(registry),NBPPT_EXEC_REVIEW_ROOT=str(root/'reviews'),
                      NBPPT_MICROSOFT_EDGE_ENABLED='false')
    spec={**spec,'video_input_id':identity}
    from gateway.exec_pitch_inputs import load_input
    load_input(owner,identity,spec)
    from gateway.exec_pitch_story import brief_markdown,story_manifest
    from gateway.exec_pitch_contract import validate_input
    (root/'story_brief.md').write_text(brief_markdown(value))
    (root/'story_evidence.json').write_text(json.dumps(story_manifest(value,validate_input(value,spec)),ensure_ascii=False,indent=2))
    record={'registry':str(registry),'spec':spec,'input_id':identity,'source':prior['source'],
            'parent_input_id':prior['input_id'],'voice_identity_sha256':value['story']['voice_identity_sha256'],
            'story_sha256':digest(canonical(value['story'])),'provider_calls':0}
    (root/'registration.json').write_text(json.dumps(record,ensure_ascii=False,indent=2))
    return record


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--registration',required=True)
    p.add_argument('--runtime',required=True);p.add_argument('--version',default='video_v13_review_only');args=p.parse_args()
    import re
    if not re.fullmatch(r'video_v[1-9][0-9]*_review_only',args.version):raise ValueError('必须使用明确的新待审版本目录')
    root=Path(args.root).resolve();root.mkdir(parents=True,exist_ok=False)
    record=prepare(root,Path(args.registration).resolve(),Path(args.runtime).resolve())
    formal=root/'formal';formal.mkdir()
    os.environ.update(NBPPT_REQUIRE_ISOLATION='true',DATABASE_PATH=str(formal/'sandbox.db'),
                      NBPPT_EXEC_PITCH_ROOT=str(formal/'registry'),NBPPT_JOBS_ROOT=str(formal/'jobs'))
    def builder(registry,user):
        owner=digest(user.encode())
        if owner!=record['spec']['video_input_owner']:raise ValueError('叙事素材不得跨账户复用')
        shutil.copytree(Path(record['registry'])/owner,registry/owner)
        value=json.loads((registry/owner/record['input_id']/'input.json').read_text())
        return record['source'],record['input_id'],value
    from tools.exec_pitch_acceptance import acceptance
    asyncio.run(acceptance(formal,builder=builder,milestone='P6_SOURCE_GROUNDED_STORY',version=args.version,expected_blocked_p4=True))


if __name__=='__main__':main()
