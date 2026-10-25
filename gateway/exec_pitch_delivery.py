"""Independent long-film file gate, called again by settlement and download."""
import html
import json
import subprocess
import wave
from fractions import Fraction

from PIL import Image
from gateway.exec_pitch_contract import canonical, digest, validate_input, FPS


def verify_beat_audio(video,spec,timeline):
    """Check copied PCM beat identity/position after AAC, without word timestamps.

    Loudness normalization changes gain; normalized correlation checks the take
    at the expected sample offset. This cannot judge text pronunciation/meaning.
    """
    import numpy as np
    from gateway.exec_pitch_inputs import load_input
    value,_,registry=load_input(spec['video_input_owner'],spec['video_input_id'],spec)
    result=subprocess.run(['ffmpeg','-v','error','-nostdin','-threads','2','-i',str(video),
        '-vn','-ac','1','-ar','48000','-f','s16le','-'],check=True,capture_output=True,
        timeout=max(120,spec['video_duration_sec']*2))
    decoded=np.frombuffer(result.stdout,dtype='<i2')
    if abs(len(decoded)-spec['video_duration_sec']*48000)>1024:
        raise ValueError('编码配音样本总量与镜头时间轴不一致')
    correlations=[]
    for shot,cut in zip(value['shots'],timeline['shots']):
        with wave.open(str(registry/'assets'/f"{shot['audio_sha256']}.wav"),'rb') as wav:
            original=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2')
        window=min(24000,len(original))
        # Select the most energetic window to avoid mistaking an approved pause
        # for evidence. No model-produced word timestamps are used.
        candidates=[round((len(original)-window)*i/4) for i in range(5)]
        start=max(candidates,key=lambda at:float(np.dot(original[at:at+window].astype('float64'),original[at:at+window])))
        expected=original[start:start+window].astype('float64');expected-=expected.mean()
        offset=cut['speech_start_sample']+start
        actual=decoded[offset:offset+window].astype('float64');actual-=actual.mean()
        norm=float(np.linalg.norm(expected)*np.linalg.norm(actual))
        correlation=float(np.dot(expected,actual)/norm) if norm>0 and len(actual)==window else 0
        if correlation<.90:
            raise ValueError(f"第{shot['shot_num']}镜编码音频与登记节拍不一致；未通过口播位置校验")
        correlations.append(correlation)
    return {'method':'registered_pcm_beat_correlation_not_words','min_correlation':min(correlations),
            'checked_beats':len(correlations),'threshold':.90}


def content_markdown(value):
    lines=[f"# {value['title']}",'',f"受众：{value['audience']}",f"目的：{value['purpose']}",
           f"论点：{value['thesis']}",'','## 因果链',*['- '+x for x in value['causal_chain']],
           '','## 证据边界',value['evidence_boundary'],'']
    for section in value['sections']:
        lines += [f"## 口播段落 {section['section_num']}",section['argument'],section['narration'],
                  *['原文依据：'+q for q in section['source_quotes']],'']
    return '\n'.join(lines)


def source_manifest(spec):
    value=spec['exec_pitch_input']
    result={'input_id':spec['video_input_id'],'source_sha256':value['source_sha256'],
            'media_kind':value['media_kind'],'approval_scope':'registered_input_only_not_content_acceptance',
            'shots':[{k:s[k] for k in ('shot_num','audio_sha256','visual_sha256','source_quotes','reason')} for s in value['shots']]}
    if 'voice_mix' in value:result['voice_mix']=value['voice_mix']
    if 'story' in value:
        result['story']={'brief_sha256':digest(canonical(value['story'])),
                         'parent_input_id':value['story']['parent_input_id'],
                         'evidence_scope':value['story']['proof']['kind'],'human_approval':'NOT_REVIEWED'}
    if 'bilingual' in value:
        from gateway.exec_pitch_voice import load_bilingual
        from gateway.exec_pitch_inputs import load_input
        _,timeline,root=load_input(spec['video_input_owner'],spec['video_input_id'],spec)
        result['bilingual']={k:v for k,v in load_bilingual(value,spec,timeline,root).items() if k!='font_path'}
    return result


def inspect_exec(job_id,spec,root,*,_p4_preflight=False):
    from gateway.delivery import contained_file
    from gateway.video_contract import validate_video_spec
    from gateway.audio_contract import verify_loudness
    from worker.video_speech import _stamp
    from gateway.exec_pitch_voice import narration_text
    validate_video_spec(spec)
    value=spec['exec_pitch_input'];timeline=validate_input(value,spec)
    from gateway.exec_pitch_inputs import load_input
    from gateway.word_alignment import load_alignment
    alignment=None
    if 'quality' in value:
        _,_,registry=load_input(spec['video_input_owner'],spec['video_input_id'],spec)
        alignment=load_alignment(value,spec,timeline,registry)
    if (digest(canonical(value))!=spec['video_input_id'] or timeline!=spec['exec_pitch_timeline']
            or spec.get('video_scenes')!=value['shots'] or spec.get('video_sections')!=value['sections']):
        raise ValueError('长片交付时间轴或输入摘要不一致')
    expected={'manuscript.json':value,'storyboard.json':value['shots'],'timeline.json':timeline,
              'source_manifest.json':source_manifest(spec)}
    files=[]
    for name,content in expected.items():
        path=contained_file(root,name)
        if path.stat().st_size>256*1024 or json.loads(path.read_text())!=content:
            raise ValueError('长片下载稿件或时间轴改变')
        files.append(path)
    if 'story' in value:
        from gateway.exec_pitch_story import story_manifest,brief_markdown
        path=contained_file(root,'story_evidence.json')
        if path.stat().st_size>256*1024 or json.loads(path.read_text())!=story_manifest(value,timeline):
            raise ValueError('叙事来源/声音/时钟/证据分类改变')
        brief=contained_file(root,'story_brief.md')
        if brief.read_text()!=brief_markdown(value):raise ValueError('先行叙事简报发生变化')
        files.extend([path,brief])
    for name,text in [('content_manuscript.md',content_markdown(value)),
                      ('narration.txt',narration_text(value))]:
        path=contained_file(root,name)
        if path.read_text()!=text: raise ValueError('长片文字与已登记口播不一致')
        files.append(path)
    from gateway.exec_pitch_voice import caption_vtt, mix_profile
    captions=contained_file(root,'subtitles.vtt')
    if captions.read_text()!=caption_vtt(value,timeline,alignment): raise ValueError('长片字幕与实测口播时间轴不一致')
    files.append(captions)
    video=contained_file(root,f'{job_id}_video.mp4')
    info=json.loads(subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(video)],
                                  check=True,capture_output=True,timeout=30).stdout)
    videos=[s for s in info['streams'] if s['codec_type']=='video'];audios=[s for s in info['streams'] if s['codec_type']=='audio']
    size=(1280,720) if spec['video_aspect_ratio']=='16:9' else (720,1280)
    if len(videos)!=1 or len(audios)!=1: raise ValueError('长片必须有一条视频和一条配音')
    v,a=videos[0],audios[0];seconds=spec['video_duration_sec']
    if ((v['width'],v['height'])!=size or v['codec_name']!='h264' or v['pix_fmt']!='yuv420p'
            or Fraction(v['avg_frame_rate'])!=FPS or int(v.get('nb_frames',0))!=timeline['total_frames']
            or a['codec_name']!='aac' or int(a['sample_rate'])!=48000 or abs(float(a['duration'])-seconds)>.05
            or abs(float(v['duration'])-seconds)>1/FPS+.001
            or abs(float(info['format']['duration'])-seconds)>1/FPS+.001
            or (spec.get('video_width'),spec.get('video_height'))!=size or spec.get('fps')!=FPS
            or spec.get('video_audio') is not True or spec.get('narration',{}).get('provider')!='approved_local'
            or spec.get('narration',{}).get('status')!='generated'
            or spec.get('narration',{}).get('voice')!='approved_local'
            or spec.get('narration',{}).get('media_kind')!=value['media_kind']
            or spec.get('video_subtitles') and spec.get('subtitles_burned') is not True):
        raise ValueError('长片编码、声音或时长不符合交付契约')
    subprocess.run(['ffmpeg','-v','error','-xerror','-nostdin','-threads','2','-i',str(video),'-f','null','-'],
                   check=True,capture_output=True,timeout=max(120,seconds*2))
    verify_beat_audio(video,spec,timeline)
    if spec.get('video_render_engine')=='html_chromium':
        from gateway.motion_delivery import verify_motion_chunks
        chunk_path,_=verify_motion_chunks(spec,root)
        files.append(chunk_path)
    from gateway.product_visuals import verify_product_visuals
    files.extend(verify_product_visuals(spec,root))
    options={'profile':mix_profile(value)} if 'voice_mix' in value else {}
    verify_loudness(video,timeout_sec=max(120,seconds*2),**options)
    for name in ('assets/video_poster.png','assets/storyboard.png'):
        path=contained_file(root,name)
        with Image.open(path) as image:
            image.load()
            if image.format!='PNG' or name.endswith('video_poster.png') and image.size!=size:
                raise ValueError('长片预览图无效')
        files.append(path)
    files.append(video)
    # The review request is produced after preflight, alongside P4 QA.
    if 'revision' in value and not _p4_preflight:
        from gateway.exec_pitch_revision import verify_revision
        files.extend(verify_revision(value,spec,root))
    if 'quality' in value and not _p4_preflight:
        from gateway.frame_qa import verify_p4_report
        files.extend(verify_p4_report(job_id,spec,root))
    return files
