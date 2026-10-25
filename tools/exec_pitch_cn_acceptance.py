"""Run the ordinary application pipeline using the selected, cached Chinese B takes.

No synthesis or planning path exists here. Earlier blocked review outputs stay intact.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gateway.exec_pitch_contract import canonical, digest, validate_input


def cached_input(registry, user, cache):
    selection = json.loads((cache/'human-selection.json').read_text())
    if (selection.get('source') != 'current_human_user_message' or selection.get('decision') != 'B'
            or selection.get('voice') != 'microsoft_yunjian' or selection.get('rate') != '+10%'
            or selection.get('full_synthesis_authorized') is not True
            or selection.get('paid_calls_authorized') is not False):
        raise ValueError('Missing human selection of B; cached audio cannot establish approval')
    previous = json.loads((cache/'admission.json').read_text())
    input_id = previous['input_id']
    owner = digest(user.encode())
    if previous['spec']['video_input_owner'] != owner:
        raise ValueError('Cached input belongs to a different sandbox account')
    package = Path(previous['registry'])/owner/input_id
    value = json.loads((package/'input.json').read_text())
    if digest(canonical(value)) != input_id:
        raise ValueError('Cached input identity changed')
    records = json.loads((cache/'takes.json').read_text())
    if len(records) != len(value['shots']):
        raise ValueError('Incomplete cached narration')
    for shot, record in zip(value['shots'], records):
        identity = {'voice':'zh-CN-YunjianNeural', 'rate':'+10%',
                    'text':shot['narration'], 'edge_tts':'7.3.1'}
        key = digest(canonical(identity))
        raw = cache/'takes'/f"{shot['shot_num']:02}-{key}.wav"
        if (record['key'] != key or record['shot_num'] != shot['shot_num']
                or any(record[k] != identity[k] for k in ('voice','rate','text'))
                or record['sha256'] != digest(raw.read_bytes())):
            raise ValueError('Selected cached take changed; no new synthesis will be requested')
        pcm = cache/'candidate-assets'/f"beat-{shot['shot_num']:02}.wav"
        registered = package/'assets'/f"{shot['audio_sha256']}.wav"
        if not digest(pcm.read_bytes()) == digest(registered.read_bytes()) == shot['audio_sha256']:
            raise ValueError('Registered PCM differs from the cached selected take')
    validate_input(value, previous['spec'])
    destination = registry/owner/input_id
    shutil.copytree(package, destination)
    # The normal gateway and worker remeasure every copied asset before use.
    return previous['spec']['original_prompt_cn'], input_id, value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--cache', required=True)
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--version', default='video_v8')
    args = parser.parse_args()
    if not re.fullmatch(r'video_v[1-9][0-9]*', args.version):
        parser.error('version must be a video_vN directory name')
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=False)
    cache = Path(args.cache).resolve()
    os.environ.update(json.loads(Path(args.runtime).read_text()))
    os.environ.update(NBPPT_REQUIRE_ISOLATION='true', DATABASE_PATH=str(root/'sandbox.db'),
                     NBPPT_EXEC_PITCH_ROOT=str(root/'registry'), NBPPT_JOBS_ROOT=str(root/'jobs'),
                     NBPPT_MICROSOFT_EDGE_ENABLED='false')
    from tools.exec_pitch_acceptance import acceptance
    asyncio.run(acceptance(root, builder=lambda registry,user:cached_input(registry,user,cache),
                          milestone='P3_CHINESE_B_CACHED', version=args.version))


if __name__ == '__main__':
    main()
