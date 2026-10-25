"""Trusted local shot editing for registered narration beats; no provider calls."""
import json
import math
from pathlib import Path
import wave

import numpy as np
from PIL import Image, ImageDraw

from gateway.exec_pitch_contract import FPS, SAMPLE_RATE, SAMPLES_PER_FRAME, canonical
from gateway.exec_pitch_inputs import load_input
from worker.live_action_renderer import run
from worker.scene_assets import probe
from worker.video_renderer import _font
from worker.video_subtitles import _find_ffmpeg
from worker.video_speech import _write_pcm_wav, _mux_audio, _stamp


def render_exec(job, job_id, plan):
    value,timeline,root=load_input(plan['video_input_owner'],plan['video_input_id'],plan)
    if value!=plan['exec_pitch_input'] or timeline!=plan['exec_pitch_timeline']:
        raise ValueError('长片输入在入场后改变')
    work=job/'exec-render';work.mkdir(exist_ok=False)
    staging=job/'staging';encoder=str(_find_ffmpeg())
    width,height=plan['video_width'],plan['video_height']
    paths=[];audio_parts=[];vtt=['WEBVTT',''];checked={}
    html_mode=plan.get('video_render_engine','html_chromium')=='html_chromium'
    if html_mode:
        from worker.html_motion_renderer import render_chunks
        picture=render_chunks(job,plan,value,timeline,root,encoder)
    for shot,cut in zip(value['shots'],timeline['shots']):
        number=shot['shot_num'];frames=cut['end_frame']-cut['start_frame'];duration=frames/FPS
        visual=root/'assets'/f"{shot['visual_sha256']}.mp4"
        if not html_mode and visual not in checked:
            info=probe(visual);streams=[s for s in info['streams'] if s['codec_type']=='video']
            if len(streams)!=1 or (streams[0]['width'],streams[0]['height'])!=(width,height):
                raise ValueError('登记镜头必须事先审核实际交付画幅')
            checked[visual]=float(streams[0].get('duration',info['format']['duration']))
        if not html_mode and checked[visual]+.001<duration:
            raise ValueError('实景镜头短于自然口播，未循环、冻结或补帧')
        destination=work/f'shot-{number:03}.mp4'
        if not html_mode:
            run([encoder,'-v','error','-nostdin','-threads','2','-i',str(visual),'-an','-frames:v',str(frames),
                 '-vf','fps=24,format=yuv420p','-c:v','libx264','-preset','fast','-crf','20','-threads','2',str(destination)])
            if int(probe(destination)['streams'][0].get('nb_frames',0))!=frames:
                raise ValueError('镜头编码帧数与时间轴不一致')
            paths.append(destination)
        with wave.open(str(root/'assets'/f"{shot['audio_sha256']}.wav"),'rb') as wav:
            samples=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').astype(np.float32)/32768
        lead=shot['lead_frames']*SAMPLES_PER_FRAME
        tail=frames*SAMPLES_PER_FRAME-lead-len(samples)
        if tail<shot['tail_frames']*SAMPLES_PER_FRAME:
            raise ValueError('口播声音留量不足')
        audio_parts.extend([np.zeros(lead,dtype=np.float32),samples,np.zeros(tail,dtype=np.float32)])
        import html
        vtt.extend([f"{_stamp(cut['start_frame']/FPS)} --> {_stamp(cut['end_frame']/FPS)}",html.escape(shot['narration']),''])
        print(json.dumps({'type':'progress','pct':number*90/len(value['shots']),'frame':cut['end_frame'],
                          'total_frames':timeline['total_frames']}),flush=True)
    if not html_mode:
        (work/'concat.txt').write_text(''.join(f"file '{p.name}'\n" for p in paths))
        run([encoder,'-v','error','-nostdin','-f','concat','-safe','1','-i','concat.txt','-c','copy','picture.mp4'],cwd=work)
        picture=work/'picture.mp4'
    audio=work/'narration.wav'
    from gateway.exec_pitch_voice import mix_profile, caption_vtt
    from gateway.word_alignment import load_alignment
    alignment=load_alignment(value,plan,timeline,root)
    if alignment is not None:
        # P4 drafts remain visibly non-deliverable while client frame evidence
        # is unavailable. The mark is below the P1 comparison crop, above VO.
        from os import environ
        mark=work/'review-label.txt';mark.write_text('仅本地审阅 · 同步与客户审核状态见质检报告')
        marked=work/'picture-review.mp4'
        run([encoder,'-v','error','-nostdin','-threads','2','-i',str(picture),
             '-vf',f"drawtext=fontfile='{environ['NBPPT_HTML_FONT']}':textfile='{mark}':fontsize=18:fontcolor=0xE5AB68:box=1:boxcolor=black@0.65:x=w-tw-24:y=h*0.82",
             '-an','-c:v','libx264','-preset','fast','-crf','18','-threads','2',str(marked)])
        picture=marked
    combined=np.concatenate(audio_parts)
    if value.get('voice_mix',{}).get('music')=='original_ducked':
        from worker.video_music import mix_original_bed
        combined=mix_original_bed(combined,SAMPLE_RATE)
    _write_pcm_wav(audio,combined,SAMPLE_RATE)
    video=staging/f'{job_id}_video.mp4'
    _mux_audio(picture,audio,video,plan['video_duration_sec'],normalise=True,sample_rate=SAMPLE_RATE,audio_profile=mix_profile(value))
    (staging/'subtitles.vtt').write_text(caption_vtt(value,timeline,alignment))
    if alignment is not None:
        (staging/'word_alignment.json').write_bytes(canonical(alignment))
    # Contact sheet samples actual encoded shots; human/frame QA remains pending.
    thumbs=[]
    for cut in timeline['shots']:
        frame=work/f"frame-{cut['shot_num']:03}.png"
        run([encoder,'-v','error','-nostdin','-ss',str((cut['start_frame']+cut['end_frame'])/(2*FPS)),
             '-i',str(video),'-frames:v','1',str(frame)])
        with Image.open(frame) as im:
            if cut['shot_num']==1: im.save(staging/'assets/video_poster.png')
            tile=Image.new('RGB',(320,210),'#102D35');im.thumbnail((320,180));tile.paste(im,(0,0))
            ImageDraw.Draw(tile).text((8,184),f"{cut['shot_num']:02} | frame {cut['start_frame']}",font=_font(14),fill='white')
            thumbs.append(tile)
    sheet=Image.new('RGB',(320*4,210*math.ceil(len(thumbs)/4)),'#102D35')
    for i,tile in enumerate(thumbs): sheet.paste(tile,((i%4)*320,(i//4)*210))
    sheet.save(staging/'assets/storyboard.png')
    return {'video':video,'poster':staging/'assets/video_poster.png','subtitles':staging/'subtitles.vtt'}
