"""Independently compare encoded chunk boundaries with trusted browser captures."""
import hashlib
import json
import re
import subprocess
import tempfile

import numpy as np
from PIL import Image


def selection_expression(frames):
    if not frames or len(frames)>800 or any(type(n) is not int or n<0 for n in frames):
        raise ValueError('切点帧列表无效或超限')
    def combine(values):
        if len(values)==1:return f'eq(n\\,{values[0]})'
        middle=len(values)//2
        return '('+combine(values[:middle])+'+'+combine(values[middle:])+')'
    # FFmpeg's expression parser has a recursion ceiling. A left-deep sum of
    # hundreds of eq() terms can fail even for a perfectly valid long film.
    return combine(frames)


def verify_motion_chunks(spec,root):
    from gateway.delivery import contained_file
    from gateway.exec_pitch_contract import hash_id
    path=contained_file(root,'render_chunks.json')
    if path.stat().st_size>1024*1024:raise ValueError('HTML分块记录超限')
    ledger=json.loads(path.read_text());total=spec['video_duration_sec']*24;cursor=0;samples=[]
    if (ledger.get('engine')!='html-chromium-lottie-v1' or ledger.get('time_base')!='1/24'
            or ledger.get('total_frames')!=total or ledger.get('chunk_frames')!=96
            or ledger.get('network_requests')!=[] or ledger.get('errors')!=[]
            or ledger.get('playwright')!='1.62.1' or ledger.get('lottie')!='5.13.0'
            or ledger.get('font_loaded') is not True
            or not isinstance(ledger.get('chunks'),list) or not 1<=len(ledger['chunks'])<=400):
        raise ValueError('HTML渲染缺少可信、有界、离线的分块事实')
    work=root.parent/'html-render'
    if work.is_symlink():raise ValueError('HTML工作目录不安全')
    browser=json.loads(contained_file(work,'browser.json').read_text())
    if (not hash_id(ledger.get('html_sha256'))
            or hashlib.sha256(contained_file(work,'scene.html').read_bytes()).hexdigest()!=ledger['html_sha256']):
        raise ValueError('HTML渲染页面快照改变')
    seeks=ledger.get('seek_determinism')
    if not isinstance(seeks,list) or len(seeks)!=len(spec['exec_pitch_timeline']['shots']):
        raise ValueError('HTML镜头缺少重复定位证据')
    for i,record in enumerate(seeks,1):
        if (record.get('shot_num')!=i or record.get('frame')!=0 or not hash_id(record.get('first_sha256'))
                or record.get('first_sha256')!=record.get('reseek_sha256')):
            raise ValueError('HTML镜头重复定位不确定')
    arguments=browser.get('arguments',[])
    if (any(a in ('--no-sandbox','--disable-setuid-sandbox') for a in arguments)
            or browser.get('profile')!=str(work/'profile') or not any(a=='--user-data-dir='+str(work/'profile') for a in arguments)
            or ledger.get('chromium_sha256')!=browser.get('sha256')
            or ledger.get('chromium_version')!=browser.get('version')):
        raise ValueError('HTML浏览器沙箱或独立配置目录证据无效')
    for i,chunk in enumerate(ledger['chunks']):
        if (chunk.get('path')!=f'chunk-{i:04}.mp4' or type(chunk.get('frame_count')) is not int
                or not 1<=chunk['frame_count']<=96 or chunk.get('start_frame')!=cursor
                or chunk.get('end_frame')!=cursor+chunk['frame_count']):
            raise ValueError('HTML分块时间轴有缺帧、重复或重叠')
        shot=next((s for s in spec['exec_pitch_timeline']['shots'] if s['shot_num']==chunk.get('shot_num')),None)
        if not shot or not shot['start_frame']<=cursor<chunk['end_frame']<=shot['end_frame']:
            raise ValueError('HTML分块超出口播镜头边界')
        file=contained_file(work,chunk['path'])
        if hashlib.sha256(file.read_bytes()).hexdigest()!=chunk.get('sha256'):raise ValueError('HTML分块文件改变')
        evidence=chunk.get('samples',[])
        if len(evidence)!=2:raise ValueError('HTML分块缺少首尾帧')
        for label,frame,record in zip(('first','last'),(cursor,chunk['end_frame']-1),evidence):
            image=contained_file(work,chunk['path']+f'.{label}.png')
            if (record.get('global_frame')!=frame or record.get('local_frame')!=frame-shot['start_frame']
                    or hashlib.sha256(image.read_bytes()).hexdigest()!=record.get('sha256')):
                raise ValueError('HTML原始首尾帧证据不一致')
            samples.append((frame,image))
        if cursor==shot['start_frame'] and evidence[0]['sha256']!=seeks[shot['shot_num']-1]['first_sha256']:
            raise ValueError('HTML实际首帧与定位检查不一致')
        cursor=chunk['end_frame']
    if cursor!=total:raise ValueError('HTML分块未覆盖完整时间轴')
    video=contained_file(root,f"{root.parent.name}_video.mp4")
    # Decode all selected boundary frames in one process, retaining only a bounded
    # crop above captions. The final AAC/VTT and full decode gates run separately.
    samples=sorted(dict(samples).items());selection=selection_expression([frame for frame,_ in samples])
    errors=[]
    with tempfile.TemporaryDirectory(prefix='.boundary-qa-',dir=work) as temp:
        from pathlib import Path
        temp=Path(temp)
        subprocess.run(['ffmpeg','-v','error','-nostdin','-threads','2','-filter_threads','1','-i',str(video),
                        '-vf',f'select={selection}','-fps_mode','vfr','-threads','2',str(temp/'%06d.png')],
                       check=True,capture_output=True,timeout=max(120,spec['video_duration_sec']*2))
        if len(list(temp.glob('*.png')))!=len(samples):raise ValueError('最终成片切点帧数量不一致')
        for i,(_,original) in enumerate(samples,1):
            with Image.open(original) as expected,Image.open(temp/f'{i:06d}.png') as actual:
                if expected.size!=actual.size:raise ValueError('HTML拼接尺寸改变')
                w,h=expected.size;crop=(0,0,w,round(h*.80))
                a=np.asarray(expected.convert('RGB').crop(crop),dtype=np.float32)
                b=np.asarray(actual.convert('RGB').crop(crop),dtype=np.float32)
                error=float(np.abs(a-b).mean());errors.append(error)
                if error>8:raise ValueError('最终成片与HTML分块首尾帧错位或画面改变')
    return path,{'boundary_frames':len(samples),'max_mean_pixel_error':max(errors),
                 'threshold':8,'chunks':len(ledger['chunks']),'total_frames':total,'time_base':'1/24'}
