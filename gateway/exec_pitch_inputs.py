"""Administrator-registered immutable inputs; never resolve a client filesystem path."""
import os
from pathlib import Path
import wave

from gateway.exec_pitch_contract import canonical, digest, hash_id, validate_input, SAMPLE_RATE
from gateway.video_manuscript import read_json_text


def enabled():
    value=os.getenv('NBPPT_EXEC_PITCH_ROOT','')
    return bool(value and Path(value).is_absolute() and Path(value).is_dir() and not Path(value).is_symlink())


def safe_file(root, relative, maximum):
    path=root/relative
    if (any(p.is_symlink() for p in [root,*path.parents,path]) or not path.is_file()
            or not path.resolve().is_relative_to(root.resolve()) or not 0 < path.stat().st_size <= maximum):
        raise ValueError('长片登记文件缺失、不安全或超限')
    return path


def load_input(owner, input_id, spec):
    if not enabled() or not hash_id(owner) or not hash_id(input_id):
        raise ValueError('长片未配置，或内容包编号无效')
    root=Path(os.environ['NBPPT_EXEC_PITCH_ROOT'])/owner/input_id
    path=safe_file(root,'input.json',128*1024)
    value=read_json_text(path.read_text())
    if digest(canonical(value))!=input_id:
        raise ValueError('已登记内容包发生变化')
    timeline=validate_input(value,spec)
    from gateway.exec_pitch_story import validate_parent
    validate_parent(value,spec)
    from gateway.exec_pitch_voice import load_bilingual
    load_bilingual(value,spec,timeline,root)
    from gateway.word_alignment import load_alignment
    load_alignment(value,spec,timeline,root)
    if 'governance' in value:
        from gateway.exec_pitch_review import load_profile
        load_profile(value,spec)
    if 'revision' in value:
        from gateway.exec_pitch_revision import load_parent
        load_parent(value,spec)
    from gateway.product_visuals import resolve_visuals
    resolve_visuals(value,spec)
    checked=set();total_bytes=0
    for shot in value['shots']:
        for kind,extension,maximum in [('audio','wav',2_000_000),('visual','mp4',32_000_000)]:
            key=shot[kind+'_sha256'];relative=f'assets/{key}.{extension}'
            asset=safe_file(root,relative,maximum)
            if relative not in checked:
                total_bytes+=asset.stat().st_size
                if total_bytes>256_000_000 or digest(asset.read_bytes())!=key:
                    raise ValueError('长片素材摘要不一致或素材总量超限')
                checked.add(relative)
            if kind=='audio':
                with wave.open(str(asset),'rb') as audio:
                    if (audio.getnchannels()!=1 or audio.getsampwidth()!=2 or audio.getframerate()!=SAMPLE_RATE
                            or audio.getcomptype()!='NONE' or audio.getnframes()!=shot['audio_samples']
                            or len(audio.readframes(audio.getnframes())) != shot['audio_samples']*2):
                        raise ValueError('实测音频与已登记口播镜头不一致')
    return value,timeline,root
