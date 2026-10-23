"""Action-driven moving footage with brief editorial mechanism inserts.

The model supplies data-only edits. It never supplies code, filters or paths.
"""
import json
import math
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw
from worker.scene_assets import safe_file, sha256, probe
from worker.scene_framing import frame_filter
from worker.video_subtitles import _find_ffmpeg
from worker.video_renderer import _font,_draw_fitted,_write_subtitles
from gateway.live_action_contract import validate_sources
from gateway.footage_contract import credits_html


def run(command,**kw):
    p=subprocess.run(command,capture_output=True,timeout=600,**kw)
    if p.returncode:
        raise RuntimeError('实景剪辑编码失败：'+p.stderr.decode(errors='replace')[-700:])


def explanation_frame(scene,plan,t,variant):
    """A source-specific evidence board, not a full-screen talking-point card."""
    w,h=plan['video_width'],plan['video_height'];p=h>w
    im=Image.new('RGB',(w,h),'#EEEAE1' if variant%2 else '#102D35');d=ImageDraw.Draw(im)
    dark=variant%2==0;ink='#EEEAE1' if dark else '#173943';accent='#E2A86F' if dark else '#BA572D'
    t=max(0,min(1,t));ease=1-(1-t)**3
    margin=int(w*.075)
    d.text((margin,int(h*.07)),f"{scene['scene_num']:02d}   /   机制示意",font=_font(18),fill=accent)
    _draw_fitted(d,(margin,int(h*.16)),scene['title'],ink,int(w*.85),int(h*.2),52 if not p else 46,28,bold=True,max_lines=2)
    # A progressing evidence thread; labels are from the approved manuscript.
    labels=scene['items'];n=len(labels)
    if scene['role']=='choice':
        center=(int(w*.5),int(h*.57));d.ellipse((center[0]-10,center[1]-10,center[0]+10,center[1]+10),fill=accent)
        for i,label in enumerate(labels[:2]):
            x=int(w*(.25+.5*i));y=int(h*(.7 if p else .61))
            d.line((center[0],int(h*.46),x,y),fill=accent,width=4)
            _draw_fitted(d,(x-int(w*.18),y+24),label,ink,int(w*.36),int(h*.12),38,22,bold=True,max_lines=2)
        d.line((int(w*.2),int(h*.47),int(w*(.2+.6*ease)),int(h*.47)),fill=accent,width=5)
    else:
        y=int(h*.54);left=margin;right=w-margin
        if p:
            x=int(w*.18)
            d.line((x,int(h*.45),x,int(h*(.45+.27*ease))),fill=accent,width=4)
            for i,label in enumerate(labels):
                yy=int(h*(.45+i*.27/max(1,n-1)))
                if t<(i*.13):continue
                d.ellipse((x-7,yy-7,x+7,yy+7),fill=accent)
                _draw_fitted(d,(x+28,yy-22),label,ink,int(w*.65),70,38,22,bold=True,max_lines=2)
        else:
            d.line((left,y,right,y),fill='#586E6D' if dark else '#B6BFBA',width=2)
            d.line((left,y,int(left+(right-left)*ease),y),fill=accent,width=5)
            for i,label in enumerate(labels):
                x=int(left+(right-left)*i/max(1,n-1))
                if t<i*.13:continue
                d.ellipse((x-8,y-8,x+8,y+8),fill=accent)
                boxw=int(w*.24);xx=max(margin,min(w-margin-boxw,x-boxw//2))
                _draw_fitted(d,(xx,y+40),label,ink,boxw,90,36,22,bold=True,max_lines=2)
        # The subject visibly travels from unresolved to confirmed; never a fabricated screenshot.
        sx=int(w*(.12+.68*ease));sy=int(h*(.77 if not p else .34))
        d.polygon([(sx,sy),(sx+38,sy-16),(sx+76,sy),(sx+76,sy+42),(sx+38,sy+60),(sx,sy+42)],fill=accent)
        d.line((sx,sy,sx+38,sy+18,sx+76,sy),fill=ink,width=2)
    return im


def _animation(encoder,target,scene,plan,seconds,variant):
    w,h=plan['video_width'],plan['video_height']
    command=[encoder,'-v','error','-nostdin','-f','rawvideo','-pix_fmt','rgb24','-s',f'{w}x{h}',
             '-r','24','-i','pipe:0','-an','-c:v','libx264','-preset','fast','-crf','18','-threads','2','-pix_fmt','yuv420p',str(target)]
    with target.with_suffix('.log').open('wb') as log:
        proc=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=log)
        try:
            for frame in range(seconds*24):
                proc.stdin.write(explanation_frame(scene,plan,frame/max(1,seconds*24-1),variant).tobytes())
            proc.stdin.close()
            if proc.wait(timeout=90):raise RuntimeError('解释动画编码失败')
        finally:
            if proc.poll() is None:
                proc.kill();proc.wait()


def render_film(job,job_id,plan):
    job=Path(job);staging=job/'staging';work=job/'film-render';work.mkdir(exist_ok=False)
    snapshot=job/'selected_footage.json'
    if snapshot.is_symlink() or snapshot.stat().st_size>1024*1024:raise ValueError('素材快照不安全')
    selected=json.loads(snapshot.read_text())['clips'];by_id={c['id']:c for c in selected}
    ledger={'usage':'illustration_only','clips':[]}
    for scene in plan['video_scenes']:
        for shot in scene['shots']:
            if shot['clip_id']=='animation':continue
            c=by_id[shot['clip_id']]
            ledger['clips'].append({k:v for k,v in c.items() if k not in {'file','topics','crops','end','continuity','scene_num'}}
                                  |{'frame_layout':c['crops'][plan['video_aspect_ratio']].get('mode','crop')})
    validate_sources(ledger,plan)
    encoder=str(_find_ffmpeg());w,h=plan['video_width'],plan['video_height'];paths=[];timeline=[];cursor=0;checked=set()
    shots=[(s,x) for s in plan['video_scenes'] for x in s['shots']]
    for i,(scene,shot) in enumerate(shots):
        destination=work/f'shot-{i:03}.mp4';d=shot['duration_sec'];cid=shot['clip_id']
        if cid=='animation':
            _animation(encoder,destination,scene,plan,d,i)
        else:
            c=by_id[cid];path=safe_file(job/'footage',c['file'])
            if path.name not in checked:
                if sha256(path)!=c['sha256']:raise ValueError('素材文件已变化')
                checked.add(path.name)
            info=probe(path);v=next(s for s in info['streams'] if s['codec_type']=='video')
            if c['start']+d>min(c['end'],float(info['format']['duration'])-.02):raise ValueError('镜头超出实际素材')
            filters=frame_filter(v['width'],v['height'],w,h,c['crops'][plan['video_aspect_ratio']],d)
            filters+=',fps=24,eq=contrast=1.025:saturation=0.9,format=yuv420p'
            run([encoder,'-v','error','-nostdin','-filter_complex_threads','1','-filter_threads','1',
                 '-ss',str(c['start']),'-i',str(path),'-t',str(d),'-an','-vf',filters,'-c:v','libx264',
                 '-preset','fast','-crf','18','-threads','2','-pix_fmt','yuv420p',str(destination)])
        if abs(float(probe(destination)['format']['duration'])-d)>1/24+.001:raise ValueError('镜头时间轴不闭合')
        paths.append(destination);timeline.append({'start':cursor,'end':cursor+d,'scene':scene['scene_num'],'clip_id':cid})
        cursor+=d
        print(json.dumps({'type':'progress','pct':(i+1)*85/len(shots),'frame':i+1,'total_frames':len(shots)}),flush=True)
    (work/'concat.txt').write_text(''.join(f"file '{p.name}'\n" for p in paths))
    run([encoder,'-v','error','-f','concat','-safe','1','-i','concat.txt','-c','copy','picture.mp4'],cwd=work)
    def _stamp(seconds):
        n=round(seconds*100)
        return f'{n//360000}:{n//6000%60:02}:{n//100%60:02}.{n%100:02}'
    def _text(value,width):
        value=value.replace('\\','＼').replace('{','（').replace('}','）')
        return r'\N'.join(value[i:i+width] for i in range(0,len(value),width))
    # A brief chapter label, not a repeated full-page title/body template.
    styles=f'''[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Chapter,Noto Sans CJK SC,{'34' if h>w else '32'},&H00FFFFFF,&H00FFFFFF,&H00202020,&H80000000,-1,0,0,0,100,100,0,0,1,2,1,7,48,48,75,1
Style: Boundary,Noto Sans CJK SC,16,&H00FFFFFF,&H00FFFFFF,&H00202020,&H80000000,0,0,0,0,100,100,0,0,1,1,1,9,30,30,22,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events=[f'Dialogue: 0,0:00:00.00,{_stamp(cursor)},Boundary,,0,0,0,,情境演绎 · 非真实客户记录\n'];at=0
    for scene in plan['video_scenes']:
        if scene['shots'][0]['clip_id']!='animation':
            events.append(f"Dialogue: 1,{_stamp(at+.25)},{_stamp(at+min(2.7,scene['duration_sec']))},Chapter,,0,0,0,,{{\\fad(180,180)}}{_text(scene['title'],17)}\n")
        at+=scene['duration_sec']
    (work/'labels.ass').write_text(styles+''.join(events))
    video=staging/f'{job_id}_video.mp4'
    run([encoder,'-v','error','-i','picture.mp4','-vf','ass=labels.ass','-an','-c:v','libx264','-preset','fast',
         '-crf','18','-threads','2','-pix_fmt','yuv420p','-movflags','+faststart',str(video)],cwd=work)
    run([encoder,'-v','error','-ss','1','-i',str(video),'-frames:v','1',str(staging/'assets/video_poster.png')])
    # Per-shot three-phase contact sheet, covering every actual edit.
    thumbs=[]
    for i,item in enumerate(timeline):
        for fraction in (.3,.6,.92):
            p=work/f'check-{i:03}-{fraction}.jpg'
            run([encoder,'-v','error','-ss',str(item['start']+(item['end']-item['start'])*fraction),'-i',str(video),'-vf','scale=320:-2','-frames:v','1',str(p)])
            with Image.open(p) as image:
                tile=Image.new('RGB',(320,205),'#102D35');tile.paste(image,(0,0));ImageDraw.Draw(tile).text((8,183),f'{i+1:02} | {item["start"]}s | {fraction}',font=_font(14),fill='white');thumbs.append(tile)
    sheet=Image.new('RGB',(320*3,205*len(timeline)),'#102D35')
    for i,tile in enumerate(thumbs):sheet.paste(tile,((i%3)*320,(i//3)*205))
    sheet.save(staging/'assets/storyboard.png')
    (staging/'footage_sources.json').write_text(json.dumps(ledger,ensure_ascii=False,indent=2))
    (staging/'footage_credits.html').write_text(credits_html(ledger['clips']))
    (job/'edit_timeline.json').write_text(json.dumps(timeline,indent=2))
    _write_subtitles(staging/'subtitles.vtt',plan['video_scenes'],True)
    return {'video':video,'poster':staging/'assets/video_poster.png','subtitles':staging/'subtitles.vtt'}
