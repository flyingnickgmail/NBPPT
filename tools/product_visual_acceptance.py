"""P2 synthetic-only application acceptance. Never author human approval records."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--runtime',required=True)
    args=parser.parse_args();root=Path(args.root).resolve();root.mkdir(parents=True,exist_ok=False)
    os.environ.update(json.loads(Path(args.runtime).read_text()))
    os.environ.update(NBPPT_REQUIRE_ISOLATION='true',DATABASE_PATH=str(root/'sandbox.db'),
        NBPPT_EXEC_PITCH_ROOT=str(root/'registry'),NBPPT_PRODUCT_VISUAL_ROOT=str(root/'product-visuals'),NBPPT_JOBS_ROOT=str(root/'jobs'))
    from tools.exec_pitch_acceptance import acceptance
    from tools.product_visual_fixture import build_product_fixture
    asyncio.run(acceptance(root,builder=lambda registry,user:build_product_fixture(registry,user,root/'product-visuals'),
                           milestone='P2',version='video_v3'))


if __name__=='__main__':main()
