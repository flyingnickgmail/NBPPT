"""Single-shot edits and operator-owned, tenant-isolated raw chunk reuse.

Only pictures are cached. Final captions, mix and every delivery gate run anew.
The cache is a trusted local configuration, never a path from a request.
"""
import json
import os
from pathlib import Path
import shutil

from gateway.exec_pitch_contract import canonical, digest, hash_id
from gateway.exec_pitch_inputs import safe_file


def validate_revision(value):
    r = value.get('revision')
    if r is None:
        return
    if (not isinstance(r, dict) or set(r) != {'parent_input_id', 'parent_job_id', 'manifest_sha256', 'operation', 'shot_num'}
            or not hash_id(r['parent_input_id']) or not hash_id(r['manifest_sha256'])
            or r['operation'] not in ('polish_shot', 'replace_opening', 'swap_vo')
            or type(r['shot_num']) is not int or not 1 <= r['shot_num'] <= len(value['shots'])
            or r['operation'] == 'replace_opening' and r['shot_num'] != 1):
        raise ValueError('局部修订必须是有限操作、单个镜头和固定父版本')
    from gateway.delivery import safe_job_id
    safe_job_id(r['parent_job_id'])


def cache_root():
    raw = os.getenv('NBPPT_EXEC_REVISION_ROOT', '')
    root = Path(raw)
    if not raw or not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError('局部修订未配置管理员缓存目录')
    return root


def fingerprint():
    root = Path(__file__).resolve().parents[1]
    from worker.html_motion_renderer import ENV_KEYS
    from worker.video_subtitles import _find_ffmpeg
    import subprocess
    return digest(canonical({'code': {p: digest((root / p).read_bytes()) for p in
        ('worker/html_motion/render.mjs', 'worker/html_motion/scene.js', 'worker/html_motion/story_scene.js', 'worker/html_motion/vendor/lottie_light.min.js',
         'worker/html_motion_renderer.py', 'gateway/exec_pitch_revision.py')},
        'runtime': {k: os.getenv(k, '') for k in ENV_KEYS if k not in ('NBPPT_HTML_NODE', 'NBPPT_PLAYWRIGHT_MODULE', 'NBPPT_CHROMIUM_BIN', 'NBPPT_HTML_FONT')},
        'ffmpeg': subprocess.check_output([str(_find_ffmpeg()), '-version'], text=True).splitlines()[0]}))


def shot_key(value, shot, cut, spec, engine):
    return digest(canonical({'owner': spec['video_input_owner'], 'source': value['source_sha256'],
        'title': value['title'], 'shot': shot, 'cut': cut, 'size': [spec['video_width'], spec['video_height']],
        'voice': {'provider': 'registered_pcm', 'voice': spec['video_voice'], 'rate': 'baked_into_audio_sha256',
                  'language': 'zh-CN', 'mix': value.get('voice_mix'), 'bilingual': value.get('bilingual')},
        'products': value.get('product_visuals'), 'engine': engine}))


def load_parent(value, spec):
    r = value['revision']; root = cache_root(); owner = spec['video_input_owner']
    folder = root / owner / r['parent_job_id']
    path = safe_file(folder, 'manifest.json', 1024 * 1024)
    m = json.loads(path.read_text())
    if (digest(canonical(m)) != r['manifest_sha256'] or m['owner'] != owner
            or m['input_id'] != r['parent_input_id'] or digest(canonical(m['value'])) != r['parent_input_id']
            or m['job_id'] != r['parent_job_id'] or m['engine'] != fingerprint()
            or m['file_ok'] != 'PASSED' or m['frame_qa'] != 'PASSED'):
        raise ValueError('父版本、账户、渲染依赖或已验证画面缓存不一致')
    parent = m['value']; old = {k: v for k, v in parent.items() if k not in ('revision', 'governance', 'quality', 'shots')}
    new = {k: v for k, v in value.items() if k not in ('revision', 'governance', 'quality', 'shots')}
    changed = [i for i, (a, b) in enumerate(zip(parent['shots'], value['shots']), 1) if a != b]
    if old != new or len(parent['shots']) != len(value['shots']) or changed != [r['shot_num']]:
        raise ValueError('局部修订只能改变指定单镜，不能暗改原稿、其他镜头或声音配置')
    a = parent['shots'][r['shot_num'] - 1]; b = value['shots'][r['shot_num'] - 1]
    allowed = {'audio_sha256', 'audio_samples', 'lead_frames', 'tail_frames'} if r['operation'] == 'swap_vo' else {'motion', 'visual_sha256', 'product_asset_id'}
    if any(a.get(k) != b.get(k) for k in set(a) | set(b) if k not in allowed):
        raise ValueError('该修订操作不能改变口播或越出单镜画面/声音范围')
    return m, folder


def prepare_reuse(value, spec, timeline, work):
    if 'revision' not in value:
        return {}, None
    m, folder = load_parent(value, spec); reuse = {}; reused = []; rendered = []
    if len(m['shot_keys']) != len(value['shots']):
        raise ValueError('父版本镜头缓存不完整')
    for s, cut in zip(value['shots'], timeline['shots']):
        n = s['shot_num']
        if shot_key(value, s, cut, spec, m['engine']) != m['shot_keys'][n - 1]:
            rendered.append(n); continue
        chunks = [c for c in m['ledger']['chunks'] if c['shot_num'] == n]
        if not chunks:
            raise ValueError('父版本缺少未变镜头的分块')
        for c in chunks:
            records = [(c['path'], c['sha256'])] + [(c['path'] + f'.{label}.png', record['sha256'])
                       for label, record in zip(('first', 'last'), c['samples'])]
            for relative, key in records:
                source = safe_file(folder, relative, 64 * 1024 * 1024)
                if digest(source.read_bytes()) != key:
                    raise ValueError('局部修订缓存文件摘要改变')
                target = work / relative
                if target.exists() or target.is_symlink() or '/' in relative or '\\' in relative:
                    raise ValueError('局部修订缓存路径不安全')
                shutil.copyfile(source, target)
        reuse[n] = {'chunks': chunks, 'seek': m['ledger']['seek_determinism'][n - 1]}
        reused.append(n)
    receipt = {'version': 1, 'parent_job_id': m['job_id'], 'parent_input_id': m['input_id'],
        'parent_manifest_sha256': value['revision']['manifest_sha256'], 'input_id': spec['video_input_id'],
        'owner': spec['video_input_owner'], 'operation': value['revision']['operation'],
        'reused_shots': reused, 'rendered_shots': rendered, 'engine_sha256': m['engine'],
        'audio_reused_by_hash': [s['shot_num'] for s, old in zip(value['shots'], m['value']['shots']) if s['audio_sha256'] == old['audio_sha256']],
        'qa_reused': False, 'final_mix_and_captions': 'regenerated_and_independently_rechecked'}
    return reuse, receipt


def export_parent(job, spec, destination):
    """Operator snapshot after independent checks of this exact final parent."""
    from gateway.exec_pitch_delivery import inspect_exec
    from gateway.frame_qa import inspect_frames
    from gateway.delivery import contained_file
    value = spec['exec_pitch_input']; staging = job / 'staging'
    inspect_exec(job.name, spec, staging, _p4_preflight=True)
    frames = inspect_frames(staging / f'{job.name}_video.mp4', spec, staging)
    ledger = json.loads(contained_file(staging, 'render_chunks.json').read_text())
    engine = fingerprint(); folder = destination / spec['video_input_owner'] / job.name
    if any(p.is_symlink() for p in (destination, folder.parent, folder)):
        raise ValueError('父版本缓存目录不安全')
    folder.mkdir(parents=True, exist_ok=False)
    copied = 0
    for c in ledger['chunks']:
        for relative in (c['path'], c['path'] + '.first.png', c['path'] + '.last.png'):
            source = contained_file(job / 'html-render', relative); copied += source.stat().st_size
            if copied > 1024 * 1024 * 1024:
                raise ValueError('父版本画面缓存超过1GiB')
            shutil.copyfile(source, folder / relative)
    m = {'owner': spec['video_input_owner'], 'job_id': job.name, 'input_id': spec['video_input_id'],
         'value': value, 'engine': engine, 'file_ok': 'PASSED', 'frame_qa': frames['status'],
         'parent_video_sha256': digest((staging / f'{job.name}_video.mp4').read_bytes()),
         'ledger': ledger, 'shot_keys': [shot_key(value, s, c, spec, engine) for s, c in zip(value['shots'], spec['exec_pitch_timeline']['shots'])]}
    (folder / 'manifest.json').write_bytes(canonical(m))
    return digest(canonical(m))


def verify_revision(value, spec, root):
    from gateway.delivery import contained_file
    if 'revision' not in value:
        return []
    m, folder = load_parent(value, spec)
    path = contained_file(root, 'revision.json')
    report = json.loads(path.read_text())
    ledger = json.loads(contained_file(root,'render_chunks.json').read_text())
    expected = [s['shot_num'] for s,c in zip(value['shots'],spec['exec_pitch_timeline']['shots'])
                if shot_key(value,s,c,spec,m['engine']) == m['shot_keys'][s['shot_num']-1]]
    audio = [s['shot_num'] for s,o in zip(value['shots'],m['value']['shots']) if s['audio_sha256']==o['audio_sha256']]
    if (report.get('parent_manifest_sha256')!=value['revision']['manifest_sha256'] or report.get('owner')!=spec['video_input_owner']
            or report.get('input_id')!=spec['video_input_id'] or report.get('reused_shots')!=expected
            or report.get('audio_reused_by_hash')!=audio or report.get('qa_reused') is not False):
        raise ValueError('局部修订报告与实际依赖不一致')
    for c in ledger['chunks']:
        if (c.get('reused') is True)!=(c['shot_num'] in expected):raise ValueError('局部复用分块身份不一致')
        if c['shot_num'] in expected:
            previous=next((p for p in m['ledger']['chunks'] if p['path']==c['path']),None)
            if previous is None or {k:v for k,v in c.items() if k!='reused'}!={k:v for k,v in previous.items() if k!='reused'}:
                raise ValueError('局部复用不是同一父版本的验证分块')
            original=safe_file(folder,c['path'],64*1024*1024)
            if digest(original.read_bytes())!=c['sha256']:raise ValueError('父版本缓存发生变化')
    return [path,contained_file(root,'final_review_request.json')]
