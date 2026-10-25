"""Offline operator registration from existing takes and a pinned local MLX model.

Run with an already installed mlx-audio==0.5.9 interpreter. No downloads/TTS.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def digest(data):return hashlib.sha256(data).hexdigest()


def file_hash(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(1024*1024):h.update(block)
    return h.hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cache',required=True)
    parser.add_argument('--model',required=True);parser.add_argument('--root',required=True)
    args=parser.parse_args();out=Path(args.root).resolve();out.mkdir(parents=True,exist_ok=False)
    cache=Path(args.cache).resolve();model=Path(args.model).resolve(strict=True)
    if not model.is_dir() or not (model/'model.safetensors').is_file():raise ValueError('Local model missing; no downloads')
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',TOKENIZERS_PARALLELISM='false')
    from importlib.metadata import version
    if version('mlx-audio')!='0.5.9':raise ValueError('Expected pinned mlx-audio 0.5.9')
    # Human voice choice is already authorized; never infer it from model data.
    selection=json.loads((cache/'human-selection.json').read_text())
    if (selection.get('source')!='current_human_user_message' or selection.get('decision')!='B'
            or selection.get('voice')!='microsoft_yunjian' or selection.get('rate')!='+10%'):
        raise ValueError('Missing original human B choice')
    prior=json.loads((cache/'admission.json').read_text());owner=prior['spec']['video_input_owner']
    package=Path(prior['registry'])/owner/prior['input_id'];value=json.loads((package/'input.json').read_text())
    if digest(canonical(value))!=prior['input_id']:raise ValueError('Original input changed')
    files={p.name:file_hash(p) for p in sorted(model.iterdir()) if p.is_file()}
    manifest={'files':files,'mlx':version('mlx'),'mlx-audio':version('mlx-audio'),'transformers':version('transformers')}
    (out/'model-manifest.json').write_bytes(canonical(manifest))
    from mlx_audio.stt import load
    aligner=load(str(model))
    # Upstream may interpolate nonmonotonic predictions. Preserve raw acoustic
    # predictions instead and let the contract/QA expose every uncertainty.
    aligner.aligner_processor.fix_timestamp=lambda data:data.tolist()
    alignment={'version':1,'owner':owner,'source_sha256':value['source_sha256'],
        'engine':{'name':'qwen3-forced-aligner-mlx','version':'0.5.9','record_type':'model_output',
                  'model_manifest_sha256':digest(canonical(manifest)),'quantum_ms':80,
                  'timestamp_repair':'disabled_no_interpolation'},'shots':[]}
    for s in value['shots']:
        audio=package/'assets'/f"{s['audio_sha256']}.wav"
        if file_hash(audio)!=s['audio_sha256']:raise ValueError('Registered take changed')
        result=aligner.generate(audio=str(audio),text=s['narration'],language='Chinese')
        units=[{'text':u.text,'start_sample':round(u.start_time*48000),'end_sample':round(u.end_time*48000)} for u in result]
        alignment['shots'].append({'shot_num':s['shot_num'],'audio_sha256':s['audio_sha256'],
                                  'narration_sha256':digest(s['narration'].encode()),'units':units})
        print(json.dumps({'stage':'offline_alignment','shot':s['shot_num'],'units':len(units)}),flush=True)
    key=digest(canonical(alignment))
    value['quality']={'profile':'exec_pitch_p4','alignment_sha256':key,'client_rules_sha256':None}
    identity=digest(canonical(value));registry=out/'registry';destination=registry/owner/identity
    shutil.copytree(package,destination);(destination/'input.json').write_bytes(canonical(value))
    (destination/'evidence').mkdir(exist_ok=True);(destination/'evidence'/f'{key}.json').write_bytes(canonical(alignment))
    spec={**prior['spec'],'video_input_id':identity}
    (out/'registration.json').write_text(json.dumps({'source':spec['original_prompt_cn'],'input_id':identity,
        'registry':str(registry),'spec':spec,'alignment_sha256':key,'provider_calls':0},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
