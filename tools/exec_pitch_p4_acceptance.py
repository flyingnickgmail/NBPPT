"""Real application refusal/refund for a P4 draft with preserved client gaps."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--registration',required=True)
    p.add_argument('--runtime',required=True);args=p.parse_args()
    root=Path(args.root).resolve();root.mkdir(parents=True,exist_ok=False)
    record=json.loads(Path(args.registration).read_text())
    os.environ.update(json.loads(Path(args.runtime).read_text()))
    os.environ.update(NBPPT_REQUIRE_ISOLATION='true',DATABASE_PATH=str(root/'sandbox.db'),
        NBPPT_EXEC_PITCH_ROOT=str(root/'registry'),NBPPT_JOBS_ROOT=str(root/'jobs'),NBPPT_MICROSOFT_EDGE_ENABLED='false')
    from gateway.exec_pitch_contract import digest
    from tools.exec_pitch_acceptance import acceptance
    def builder(registry,user):
        owner=digest(user.encode());source=Path(record['registry'])/owner/record['input_id']
        destination=registry/owner/record['input_id'];shutil.copytree(source,destination)
        return record['source'],record['input_id'],json.loads((destination/'input.json').read_text())
    asyncio.run(acceptance(root,builder=builder,milestone='P4_CN_LOCAL_ALIGNMENT',
                          version='video_v10_review_only',expected_blocked_p4=True))


if __name__=='__main__':main()
