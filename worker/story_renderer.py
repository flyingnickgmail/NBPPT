"""Source-driven animated objects, rendered without model-generated executable code."""
import json
import math
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageDraw
from worker.video_renderer import _font, _draw_fitted, _trusted_palette, _write_subtitles


def _ease(t):
    return 1-(1-max(0,min(1,t)))**3


def _object(label, width, height, color, *, subject=False, visual="document"):
    im=Image.new('RGBA',(width,height))
    d=ImageDraw.Draw(im)
    d.rounded_rectangle((2,2,width-3,height-3),radius=22,
                        fill='#17343D' if subject else '#17262F',outline=color,width=2)
    if subject:
        # A document/object that changes state; this is intentionally not a stock actor.
        if visual=='person':
            d.ellipse((width*.43,12,width*.57,40),fill=color)
            d.rounded_rectangle((width*.33,45,width*.67,78),radius=15,fill=color)
        elif visual=='device':
            d.rounded_rectangle((width*.32,14,width*.68,74),radius=6,outline=color,width=5)
            d.line((width*.43,82,width*.57,82),fill=color,width=4)
            d.line((width*.5,74,width*.5,82),fill=color,width=4)
        elif visual=='parcel':
            d.polygon([(width*.32,28),(width*.5,14),(width*.68,28),(width*.68,65),(width*.5,80),(width*.32,65)],outline=color,width=4)
            d.line((width*.5,44,width*.5,78),fill=color,width=3)
            d.line((width*.33,28,width*.5,44,width*.67,28),fill=color,width=3)
        elif visual=='book':
            d.rounded_rectangle((width*.3,15,width*.7,75),radius=6,outline=color,width=4)
            d.line((width*.5,18,width*.5,72),fill=color,width=3)
        else:
            d.rounded_rectangle((width*.32,15,width*.68,75),radius=8,fill=color)
            for i in range(3):
                y=28+i*12
                d.line((width*.38,y,width*.61,y),fill='#12212A',width=3)
        y=int(height*.59)
    else:
        d.ellipse((18,18,25,25),fill=color)
        y=36
    _draw_fitted(d,(18,y),label,'#F0F3EE',width-36,height-y-12,26,16,bold=True,max_lines=2)
    return im


def scene_frame(scene, plan, progress, *, cache=None):
    w,h=plan['video_width'],plan['video_height']
    portrait=h>w
    if cache is None:
        palette=_trusted_palette(plan)
        # Customer colors influence the accent while retaining readable contrast.
        accent=palette['primary'] if palette['primary']!='#08717A' else '#5CD8BB'
        # Dark customer colors are lightened for a dark stage.
        rgb=tuple(int(accent[i:i+2],16) for i in (1,3,5))
        accent=tuple(max(130,c) for c in rgb)
        base=Image.new('RGB',(w,h),'#0D171F')
        d=ImageDraw.Draw(base)
        for y in range(h):
            k=1-abs(y-h*.5)/(h*.7)
            d.line((0,y,w,y),fill=(int(12+5*k),int(22+12*k),int(30+12*k)))
        for x in range(0,w,60):
            d.line((x,0,x,h),fill='#1A2B34')
        d.text((int(w*.07),int(h*.055)),f"{scene['scene_num']:02}  /  {len(plan['video_scenes']):02}",font=_font(20),fill=accent)
        top=int(h*.105)
        _draw_fitted(d,(int(w*.07),top),scene['title'],'#F1F3EE',int(w*.86),int(h*.15),
                     48 if not portrait else 46,28,bold=True,max_lines=2)
        _draw_fitted(d,(int(w*.07),int(h*.275 if portrait else h*.245)),scene['body'],'#ADC0C4',
                     int(w*.86),int(h*.12),27 if portrait else 25,18,max_lines=3 if portrait else 2)
        # Subtitle area is deliberately empty and owned by the subtitle compositor.
        d.line((int(w*.07),int(h*.83),int(w*.93),int(h*.83)),fill='#324851',width=1)
        labels=scene['items']
        sprites=[_object(x,190 if not portrait else 230,100,accent) for x in labels]
        subject_before=_object(scene['state_before'],240,150,accent,subject=True,visual=plan['story']['visual'])
        subject_after=_object(scene['state_after'],240,150,accent,subject=True,visual=plan['story']['visual'])
        cache=(base,sprites,subject_before,subject_after,accent)
    base,sprites,before,after,accent=cache
    im=base.copy().convert('RGBA');d=ImageDraw.Draw(im)
    t=_ease(progress/.8)
    cx=w*.5;cy=h*(.61 if portrait else .57)
    layout=scene['layout']; n=len(sprites)
    # Items enter in a staggered rhythm, follow the narrated mechanism, and remain legible.
    points=[]
    for i in range(n):
        u=_ease((progress-i*.075)/.65)
        if layout=='journey':
            x=w*.7 if portrait else w*.17+i*(w*.66/max(1,n-1))
            y=h*.44+i*(h*.32/max(1,n-1)) if portrait else h*.70
        elif portrait:
            if n==2:
                x=cx;y=h*(.46 if i==0 else .76)
            else:
                x=w*(.25 if i%2==0 else .75)
                y=h*(.46 if i<2 else .76)
        else:
            x=w*(.21 if i%2==0 else .79)
            y=cy if n==2 else h*(.47 if i<2 else .70)
        if layout=='scatter':
            x+=(1-u)*(-60 if x<cx else 60)
        elif layout=='gather':
            x+=(1-u)*(-100 if x<cx else 100)
        elif layout in {'focus','inspect'}:
            y+=(1-u)*30
        points.append((x,y,u))
    for x,y,u in points:
        d.line((cx,cy,x,y),fill='#36545A',width=3)
    for sprite,(x,y,u) in zip(sprites,points):
        layer=sprite.copy()
        layer.putalpha(layer.getchannel('A').point(lambda a:round(a*u)))
        im.alpha_composite(layer,(int(x-sprite.width/2),int(y-sprite.height/2)))
    mix=_ease((progress-.42)/.32)
    subject=Image.blend(before,after,mix)
    subject_y=cy+20*math.sin(progress*math.pi)
    if layout=='journey':
        subject_y=h*.43+t*h*.28 if portrait else cy-100
        cx=w*.17+t*w*.66 if not portrait else w*.26
    if layout=='decision':
        subject_y=cy
    im.alpha_composite(subject,(int(cx-subject.width/2),int(subject_y-subject.height/2)))
    d=ImageDraw.Draw(im)
    if layout in {'inspect','feedback'}:
        radius=95+25*math.sin(progress*math.pi)
        d.arc((cx-radius,subject_y-radius,cx+radius,subject_y+radius),
              start=progress*360,end=progress*360+250,fill=accent,width=4)
    d.line((int(w*.07),int(h*.805),int(w*(.07+.86*progress)),int(h*.805)),fill=accent,width=3)
    return im.convert('RGB'),cache


def render_story(job_dir,job_id,plan):
    from gateway.video_contract import validate_video_plan
    validate_video_plan({'task_summary_cn':plan['task_summary_cn'],'story':plan['story'],
                         'scenes':plan['video_scenes']},plan)
    if plan.get('fps') != 24 or plan.get('video_audio') is not False:
        raise ValueError('故事渲染要求24fps无音轨输入')
    staging=Path(job_dir)/'staging'
    (staging/'assets').mkdir(exist_ok=True)
    video=staging/f'{job_id}_video.mp4'
    w,h=plan['video_width'],plan['video_height']
    cmd=[shutil.which('ffmpeg'),'-v','error','-nostdin','-y','-f','rawvideo','-pix_fmt','rgb24',
         '-s',f'{w}x{h}','-r','24','-i','pipe:0','-an','-c:v','libx264','-preset','fast',
         '-crf','19','-pix_fmt','yuv420p','-threads','2','-movflags','+faststart',str(video)]
    contacts=[];total=plan['video_duration_sec']*24;count=0
    with (Path(job_dir)/'story_encoder.log').open('wb') as log:
        proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=log)
        try:
            # A pipe timeout is bounded by the worker's process-group deadline.
            for scene in plan['video_scenes']:
                cache=None;frames=scene['duration_sec']*24
                for frame in range(frames):
                    im,cache=scene_frame(scene,plan,frame/max(1,frames-1),cache=cache)
                    proc.stdin.write(im.tobytes());count+=1
                    if frame==round(frames*.6):
                        contacts.append(im.copy())
                        if len(contacts)==1:
                            im.save(staging/'assets/video_poster.png')
                    if count%24==0:
                        print(json.dumps({'type':'progress','frame':count,'total_frames':total,'pct':count*100/total}),flush=True)
            proc.stdin.close()
            if proc.wait(timeout=60):
                raise RuntimeError('故事视频编码失败')
        finally:
            if proc.poll() is None:
                proc.kill();proc.wait(timeout=5)
    tw=320;th=round(h*tw/w)
    sheet=Image.new('RGB',(tw*min(3,len(contacts)),th*math.ceil(len(contacts)/3)),'#0D171F')
    for i,im in enumerate(contacts):
        sheet.paste(im.resize((tw,th)),((i%3)*tw,(i//3)*th))
    sheet.save(staging/'assets/storyboard.png')
    _write_subtitles(staging/'subtitles.vtt',plan['video_scenes'],True)
