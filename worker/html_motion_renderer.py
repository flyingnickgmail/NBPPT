"""Bounded HTML chunks inside the existing renderer lease and process group."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from gateway.motion_contract import shot_motion
from worker.scene_assets import probe
from worker.live_action_renderer import run

ROOT=Path(__file__).resolve().parent/'html_motion'
ENV_KEYS=('NBPPT_HTML_NODE','NBPPT_PLAYWRIGHT_MODULE','NBPPT_CHROMIUM_BIN','NBPPT_CHROMIUM_VERSION',
          'NBPPT_CHROMIUM_SHA256','NBPPT_HTML_FONT','NBPPT_HTML_FONT_SHA256','NBPPT_HTML_SOCKET_ROOT')


def preflight():
    node=os.getenv('NBPPT_HTML_NODE') or shutil.which('node')
    if not node or not Path(node).is_absolute() or not Path(node).is_file():
        raise ValueError('HTML长片需要受信Node运行时')
    for key in ('NBPPT_CHROMIUM_BIN','NBPPT_HTML_FONT'):
        path=Path(os.getenv(key,''))
        if not path.is_absolute() or not path.is_file(): raise ValueError('HTML长片缺少已固定的浏览器或字体配置')
    if not all(os.getenv(key) for key in ('NBPPT_CHROMIUM_VERSION','NBPPT_CHROMIUM_SHA256','NBPPT_HTML_FONT_SHA256')):
        raise ValueError('HTML长片需要浏览器版本、二进制及字体摘要锁定')
    return node


def render_chunks(job,plan,value,timeline,registry,encoder):
    from gateway.product_visuals import resolve_visuals
    products=resolve_visuals(value,plan)
    node=preflight();work=job/'html-render';work.mkdir(exist_ok=False)
    from gateway.exec_pitch_revision import prepare_reuse
    reused,revision=prepare_reuse(value,plan,timeline,work)
    shots=[];media_bytes=0
    for shot,cut in zip(value['shots'],timeline['shots']):
        motion=shot_motion(shot);frames=cut['end_frame']-cut['start_frame']
        item={'shot_num':shot['shot_num'],'motion':motion,'frames':frames,'brand':value['title'],
              'portrait':plan['video_height']>plan['video_width']}
        if 'story' in value:
            b=value['story'];beat=b['beats'][shot['shot_num']-1];act=next(a for a in b['acts'] if a['id']==beat['act'])
            item['story']={**beat,'question':b['question'],'entity':b['entity'],'act_title':act['title']}
        if shot['shot_num'] in reused:
            item['reuse']=reused[shot['shot_num']]
            shots.append(item)
            continue
        product=None
        if shot.get('product_asset_id'):
            product=products['assets'][shot['product_asset_id']]
            copied=work/f"product-{product['sha256']}.{product['extension']}"
            if not copied.exists():shutil.copyfile(product['path'],copied)
            if hashlib.sha256(copied.read_bytes()).hexdigest()!=product['sha256']:
                raise ValueError('复制已审产品素材时摘要改变')
            item.update(product_asset_id=product['id'],product_asset_sha256=product['sha256'],
                        product_kind=product['kind'],approved_asset=True)
            if product['kind']!='brand_broll':item['image_path']=str(copied)
        if motion['layout']=='broll_plate':
            if product and product['kind']!='brand_broll':
                shots.append(item);continue
            visual=copied if product else registry/'assets'/f"{shot['visual_sha256']}.mp4"
            info=probe(visual);stream=next(s for s in info['streams'] if s['codec_type']=='video')
            if ((stream['width'],stream['height'])!=(plan['video_width'],plan['video_height'])
                    or float(info['format']['duration'])+.001<frames/24):
                raise ValueError('B-roll镜头长度或已审画幅不满足口播，未循环或冻结')
            media=work/f"media-{shot['shot_num']:03}";media.mkdir()
            seek=['-ss',str(product['approval']['frame_window'][0]/24)] if product else []
            run([encoder,'-v','error','-nostdin','-threads','2','-protocol_whitelist','file,pipe',*seek,'-i',str(visual),'-an','-vf','fps=24',
                 '-frames:v',str(frames),'-q:v','3',str(media/'%06d.jpg')])
            media_bytes+=sum(p.stat().st_size for p in media.glob('*.jpg'))
            if media_bytes>512*1024*1024:raise ValueError('B-roll工作帧超过512MiB上限')
            item['media_dir']=str(media)
        shots.append(item)
    font=Path(os.environ['NBPPT_HTML_FONT'])
    if font.is_symlink() or font.stat().st_size>64*1024*1024:
        raise ValueError('HTML字体路径不安全或超过64MiB')
    config={'width':plan['video_width'],'height':plan['video_height'],'total_frames':timeline['total_frames'],
            'chunk_frames':96,'shots':shots,'ffmpeg':encoder,'font':str(font),
            'font_sha256':os.environ['NBPPT_HTML_FONT_SHA256']}
    if 'story' in value:config['story_profile']='parcel-story-v1'
    (work/'config.json').write_text(json.dumps(config,ensure_ascii=False))
    environment={key:os.environ[key] for key in ENV_KEYS if key in os.environ}
    environment.update(PATH=os.environ.get('PATH','/usr/bin:/bin'),TMPDIR=str(work/'tmp'))
    (work/'tmp').mkdir()
    with (work/'chromium.log').open('wb') as log:
        subprocess.run([node,str(ROOT/'render.mjs'),str(work)],env=environment,stdout=None,stderr=log,
                       check=True,timeout=max(180,plan['video_duration_sec']*12))
    ledger=json.loads((work/'chunks.json').read_text());cursor=0;paths=[]
    for chunk in ledger['chunks']:
        path=work/chunk['path'];info=probe(path);stream=next(s for s in info['streams'] if s['codec_type']=='video')
        if (chunk['start_frame']!=cursor or chunk['end_frame']-cursor!=chunk['frame_count']
                or int(stream['nb_frames'])!=chunk['frame_count']
                or abs(float(stream['duration'])-chunk['frame_count']/24)>1/24+.001
                or hashlib.sha256(path.read_bytes()).hexdigest()!=chunk['sha256']):
            raise ValueError('HTML分块出现重复、缺帧或时长不闭合')
        paths.append(path);cursor=chunk['end_frame']
    if cursor!=timeline['total_frames']:raise ValueError('HTML分块未覆盖完整口播时间轴')
    (work/'concat.txt').write_text(''.join(f"file '{p.name}'\n" for p in paths))
    picture=work/'picture.mp4'
    run([encoder,'-v','error','-nostdin','-f','concat','-safe','1','-i','concat.txt','-c','copy',str(picture)],cwd=work)
    if int(probe(picture)['streams'][0]['nb_frames'])!=cursor:raise ValueError('HTML拼接后帧数不一致')
    # The immutable output carries the bounded frame ledger, not browser profiles.
    (job/'staging/render_chunks.json').write_text(json.dumps(ledger,ensure_ascii=False,indent=2))
    if revision is not None:
        revision['reused_chunks']=sum(1 for c in ledger['chunks'] if c.get('reused') is True)
        revision['rendered_chunks']=len(ledger['chunks'])-revision['reused_chunks']
        (job/'staging/revision.json').write_text(json.dumps(revision,ensure_ascii=False,indent=2))
    return picture
