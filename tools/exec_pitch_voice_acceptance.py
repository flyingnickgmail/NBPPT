"""P3 actual application acceptance with explicitly synthetic bilingual input."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--runtime',required=True)
    parser.add_argument('--portrait',action='store_true')
    args=parser.parse_args();root=Path(args.root).resolve();root.mkdir(parents=True,exist_ok=False)
    os.environ.update(json.loads(Path(args.runtime).read_text()))
    os.environ.update(NBPPT_REQUIRE_ISOLATION='true',DATABASE_PATH=str(root/'sandbox.db'),
        NBPPT_EXEC_PITCH_ROOT=str(root/'registry'),NBPPT_JOBS_ROOT=str(root/'jobs'))
    from tools.exec_pitch_acceptance import acceptance
    from tools.exec_pitch_voice_fixture import build_voice_fixture
    asyncio.run(acceptance(root,builder=lambda registry,user:build_voice_fixture(registry,user,portrait=args.portrait),
        milestone='P3_SYNTHETIC_BILINGUAL_MIX',version='video_v4',aspect_ratio='9:16' if args.portrait else '16:9'))


if __name__=='__main__':main()
