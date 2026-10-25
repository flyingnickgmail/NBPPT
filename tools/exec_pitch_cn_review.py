"""Local B-voice comparison of an existing complete P1 film.

This is deliberately NOT an application completion or publish command. The
unchanged exec_pitch admission is exercised separately against the new raw
takes. If it refuses them, this private watermarked review remains BLOCKED.
No gate is disabled, no wallet is settled and no translation is synthesized.
"""
import argparse
import asyncio
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import wave

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from gateway.exec_pitch_contract import canonical,digest,validate_input
from worker.video_speech import _write_pcm_wav,_mux_audio


def write_json(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2))


def prepare(root,reference,*,synthesize=False):
    """One chosen take per unchanged section; no automatic retry or fallback."""
    selection=json.loads((root/'human-selection.json').read_text())
    if (selection.get('source')!='current_human_user_message' or selection.get('decision')!='B'
            or selection.get('voice')!='microsoft_yunjian' or selection.get('rate')!='+10%'
            or selection.get('full_synthesis_authorized') is not True or selection.get('paid_calls_authorized') is not False):
        raise ValueError('Missing exact human B choice for this local run')
    original=json.loads((reference/'validated_video_plan.json').read_text())
    value=original['exec_pitch_input'];timeline=original['exec_pitch_timeline']
    manuscript={k:value[k] for k in ('title','audience','purpose','thesis','causal_chain','evidence_boundary','sections')}
    write_json(root/'manuscript.json',manuscript)
    (root/'source.md').write_text(original['original_prompt_cn'])
    takes=root/'takes';takes.mkdir(exist_ok=True)
    records=[];engine=None
    for shot in value['shots']:
        number=shot['shot_num'];text=shot['narration']
        key=digest(canonical({'voice':'zh-CN-YunjianNeural','rate':'+10%','text':text,'edge_tts':'7.3.1'}))
        wav=takes/f'{number:02}-{key}.wav';receipt=wav.with_suffix('.json')
        if receipt.exists():
            record=json.loads(receipt.read_text())
            if (record.get('sha256')!=digest(wav.read_bytes()) or record.get('key')!=key
                    or record.get('text')!=text or record.get('voice')!='zh-CN-YunjianNeural' or record.get('rate')!='+10%'):
                raise ValueError('Cached take identity changed; refusing reuse')
        else:
            if not synthesize:raise ValueError('Missing take; synthesis requires explicit --synthesize')
            if number==1 and (root/'first-beat.wav').is_file():
                first=json.loads((root/'first-beat.json').read_text())
                if first['text']!=text or first['voice']!='zh-CN-YunjianNeural' or first['rate']!='+10%':
                    raise ValueError('First measured beat differs from selected source')
                shutil.copyfile(root/'first-beat.wav',wav);elapsed=first['elapsed_seconds']
            else:
                from worker.video_microsoft_voice import MicrosoftEngine
                if engine is None:engine=MicrosoftEngine('microsoft_yunjian',rate='+10%')
                write_json(root/'request-in-progress.json',{'shot_num':number,'key':key,'status':'STARTED_NO_AUTOMATIC_RETRY'})
                started=time.monotonic();generated=engine.generate(text)
                _write_pcm_wav(wav,generated.samples,generated.sample_rate);elapsed=time.monotonic()-started
            with wave.open(str(wav),'rb') as audio:
                samples=audio.getnframes();rate=audio.getframerate()
            record={'shot_num':number,'key':key,'text':text,'voice':'zh-CN-YunjianNeural','rate':'+10%',
                'edge_tts_version':'7.3.1','sha256':digest(wav.read_bytes()),'sample_rate':rate,'samples':samples,
                'seconds':samples/rate,'application_synthesis_requests':1,'paid_provider_calls':0,'elapsed_seconds':elapsed,
                'post_time_stretch':False,'word_alignment':'NOT_PERFORMED'}
            write_json(receipt,record)
        records.append(record)
        write_json(root/'takes.json',records)
        print(json.dumps({'stage':'chosen_voice','shot':number,'total':len(value['shots']),
                          'seconds':record['seconds'],'cache_key':key}),flush=True)
    if (root/'request-in-progress.json').exists():(root/'request-in-progress.json').unlink()
    return original,records


def rejected_input(root,original,records):
    """Keep unpadded raw takes and exercise the ORIGINAL independent gate."""
    value=json.loads(json.dumps(original['exec_pitch_input']))
    value['voice_mix']={'profile':'exec_pitch_p3','music':'original_ducked','input_audio':'dry_dialogue'}
    value['evidence_boundary']='来源为产品功能与情境演绎，不是客户真实事件或已测得的成效。用户已选择云健合成语速；配音为本轮新生成干声。画面仍为平台机制动画，不是客户产品截图，未获得内容人工验收。'
    owner=digest(b'sandbox-nick');assets=root/'candidate-assets';assets.mkdir(exist_ok=True)
    for shot,record in zip(value['shots'],records):
        raw=root/'takes'/f"{record['shot_num']:02}-{record['key']}.wav"
        resampled=assets/f"beat-{record['shot_num']:02}.wav"
        if not resampled.exists():
            subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(raw),'-ar','48000','-ac','1','-c:a','pcm_s16le',str(resampled)],check=True,capture_output=True)
        with wave.open(str(resampled),'rb') as audio:count=audio.getnframes()
        shot.update(audio_sha256=digest(resampled.read_bytes()),audio_samples=count,lead_frames=6,tail_frames=9)
    # Only the already allowed 6..12 frame handles absorb subsecond rounding.
    total=sum(math.ceil(s['audio_samples']/2000)+s['lead_frames']+s['tail_frames'] for s in value['shots'])
    adjustment=round(total/24)*24-total
    for shot in value['shots']:
        step=max(-3,min(3,adjustment));shot['tail_frames']+=step;adjustment-=step
    if adjustment:raise ValueError('Unable to close frame clock within allowed handles')
    seconds=sum(math.ceil(s['audio_samples']/2000)+s['lead_frames']+s['tail_frames'] for s in value['shots'])//24
    input_id=digest(canonical(value));registry=root/'rejected-registry';package=registry/owner/input_id
    (package/'assets').mkdir(parents=True,exist_ok=False)
    (package/'input.json').write_bytes(canonical(value))
    old_root=Path(original['_reference_registry'])/original['video_input_owner']/original['video_input_id']
    for shot in value['shots']:
        audio=assets/f"beat-{shot['shot_num']:02}.wav"
        shutil.copyfile(audio,package/'assets'/f"{shot['audio_sha256']}.wav")
        visual=package/'assets'/f"{shot['visual_sha256']}.mp4"
        if not visual.exists():shutil.copyfile(old_root/'assets'/visual.name,visual)
    spec={k:original[k] for k in ('generation_contract','planner_provider','video_preset','original_prompt_cn',
          'video_aspect_ratio','video_voice','video_narration','video_subtitles','video_visual_mode')}
    spec.update(video_duration_sec=seconds,video_input_id=input_id,video_input_owner=owner,video_render_engine='html_chromium')
    violations=[]
    for shot in value['shots']:
        budget=math.ceil(shot['audio_samples']/2000)/24*4
        if len(shot['narration'])>budget:
            violations.append({'shot_num':shot['shot_num'],'characters':len(shot['narration']),'budget':budget,
                               'measured_chars_per_second':len(shot['narration'])/(shot['audio_samples']/48000)})
    try:
        validate_input(value,spec)
    except ValueError as exc:
        facts={'admission':'BLOCKED','gate_error':str(exc),'violations':violations,'spec':spec,
               'input_id':input_id,'registry':str(registry),'source_sha256':value['source_sha256']}
        write_json(root/'admission.json',facts)
        return facts
    raise ValueError('Candidate unexpectedly passed; use the ordinary application path instead of a blocked preview')


async def verify_rejection(root,facts):
    """Actual HTTP admission and disposable wallet; no fake Worker completion."""
    import secrets,sqlite3
    import httpx
    from gateway.billing_tcc import BillingManager
    from gateway import main
    from gateway.mcp_server import PresentationJobs
    os.environ['NBPPT_EXEC_PITCH_ROOT']=facts['registry']
    manager=BillingManager(str(root/'rejection.db'),root/'rejection-jobs');await manager.initialize()
    token=secrets.token_urlsafe(40)
    with sqlite3.connect(manager.db_path) as db:
        db.execute("INSERT INTO users(id,phone_or_email,tier,credits_available,created_at) VALUES ('sandbox-nick','sandbox-nick','studio',2000,'sandbox')")
        db.execute("INSERT INTO mcp_api_keys(api_key,user_id,created_at,scope) VALUES (?,'sandbox-nick','sandbox','generate')",(token,))
    jobs=PresentationJobs(manager);main.billing=manager;main.mcp_jobs=jobs;main.JOBS_ROOT=manager.jobs_root
    payload={'source':facts['spec']['original_prompt_cn'],'task_type':'video','execution_mode':'auto',
             'request_id':'p3-b-raw-takes-rejected','video_preset':'exec_pitch','video_input_id':facts['input_id'],
             'video_duration_sec':facts['spec']['video_duration_sec'],'video_voice':'approved_local','video_visual_mode':'registered_local'}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://sandbox') as client:
            response=await client.post('/api/jobs',headers={'Authorization':'Bearer '+token},json=payload)
        with sqlite3.connect(manager.db_path) as db:
            balance=db.execute("SELECT credits_available FROM users WHERE id='sandbox-nick'").fetchone()[0]
            count=db.execute('SELECT count(*) FROM media_jobs').fetchone()[0]
            ledger=db.execute('SELECT count(*) FROM credit_ledger').fetchone()[0]
        if response.status_code!=422 or balance!=2000 or count or ledger:raise ValueError('Admission did not fail before reservation')
        write_json(root/'http-rejection.json',{'status':response.status_code,'detail':response.json(),
            'balance_after':balance,'jobs_created':count,'ledger_entries':ledger,'completed_settlement':False})
    finally:await jobs.close()


def review_clock(value):
    """A measured preview clock does not assert admission or word alignment."""
    shots=[];cursor=0
    for shot in value['shots']:
        frames=math.ceil(shot['audio_samples']/2000)+shot['lead_frames']+shot['tail_frames']
        if not 48<=frames<=480 or not 6<=shot['lead_frames']<=12 or not 6<=shot['tail_frames']<=12:
            raise ValueError('Preview cannot change shot bounds or permitted sound handles')
        shots.append({'shot_num':shot['shot_num'],'section_num':shot['section_num'],'start_frame':cursor,'end_frame':cursor+frames,
            'speech_start_sample':(cursor+shot['lead_frames'])*2000,'audio_samples':shot['audio_samples'],
            'audio_sha256':shot['audio_sha256'],'visual_sha256':shot['visual_sha256']})
        cursor+=frames
    if cursor%24:raise ValueError('Preview frame clock is not closed')
    return {'time_base':'1/24','fps':24,'sample_rate':48000,'total_frames':cursor,
            'alignment':'measured_narration_beats_not_words','shots':shots}


def render_review(root,reference,original,records,*,natural_clock=False):
    """A private, watermarked comparison cut; cannot be published by this tool."""
    import numpy as np
    from gateway.audio_contract import verify_loudness
    from worker.video_music import mix_original_bed
    from worker.video_subtitles import burn_subtitles,_find_ffmpeg
    from gateway.exec_pitch_voice import caption_vtt
    version='video_v6_review_only' if natural_clock else 'video_v5_review_only'
    out=root/version;out.mkdir(exist_ok=False)
    work=root/('natural-review-work' if natural_clock else 'review-work');work.mkdir(exist_ok=False)
    value=original['exec_pitch_input'];timeline=original['exec_pitch_timeline'];seconds=original['video_duration_sec']
    picture=reference/'html-render/picture.mp4';captions=reference/'output/subtitles.vtt'
    if natural_clock:
        facts=json.loads((root/'admission.json').read_text())
        registry=Path(facts['registry'])/facts['spec']['video_input_owner']/facts['input_id']
        value=json.loads((registry/'input.json').read_text());timeline=review_clock(value);seconds=timeline['total_frames']//24
        from gateway.motion_contract import validate_motion
        for shot in value['shots']:validate_motion(shot['motion'],original['original_prompt_cn'])
        from worker.html_motion_renderer import render_chunks
        job=work/'private-render';(job/'staging').mkdir(parents=True)
        plan={**original,'video_duration_sec':seconds}
        # Only trusted, already validated P1 templates/scene data are reused.
        # This low-level private render never emits an application completion.
        picture=render_chunks(job,plan,value,timeline,registry,str(_find_ffmpeg()))
        captions=work/'natural-subtitles.vtt';captions.write_text(caption_vtt(value,timeline))
        shutil.copyfile(job/'staging/render_chunks.json',out/'render_chunks.json')
    voice=np.zeros(seconds*48000,dtype=np.float32);placement=[]
    for shot,cut,record in zip(value['shots'],timeline['shots'],records):
        raw=root/'candidate-assets'/f"beat-{record['shot_num']:02}.wav"
        with wave.open(str(raw),'rb') as audio:samples=np.frombuffer(audio.readframes(audio.getnframes()),dtype='<i2').astype(np.float32)/32768
        start=cut['speech_start_sample'];end=start+len(samples)
        if end>(cut['end_frame']-6)*2000:raise ValueError('Chosen natural take does not fit unchanged reference cut')
        voice[start:end]=samples
        placement.append({'shot_num':shot['shot_num'],'speech_start_sample':start,'audio_samples':len(samples),
                          'reference_start_frame':cut['start_frame'],'reference_end_frame':cut['end_frame'],
                          'reference_music_only_tail_seconds':(cut['end_frame']*2000-end)/48000})
    _write_pcm_wav(work/'dialogue.wav',voice,48000)
    _write_pcm_wav(work/'mixed.wav',mix_original_bed(voice,48000),48000)
    _mux_audio(picture,work/'mixed.wav',work/'muxed.mp4',seconds,normalise=True,sample_rate=48000,audio_profile='exec_pitch_p3')
    burn_subtitles((work/'muxed.mp4').resolve(),captions.resolve(),(work/'subtitled.mp4').resolve())
    shutil.copyfile(Path(os.environ['NBPPT_HTML_FONT']),work/'caption.ttf')
    (work/'review-label.txt').write_text('仅本地审阅 · 长片入场未通过')
    video=out/'P3_B_Chinese_REVIEW_ONLY.mp4';encoder=str(_find_ffmpeg())
    subprocess.run([encoder,'-v','error','-nostdin','-threads','2','-filter_threads','2','-i','subtitled.mp4',
        '-vf','drawtext=fontfile=caption.ttf:textfile=review-label.txt:fontsize=20:fontcolor=white:box=1:boxcolor=black@0.65:x=w-tw-24:y=12',
        '-map','0:v:0','-map','0:a:0','-c:v','libx264','-preset','medium','-crf','18','-threads','2','-pix_fmt','yuv420p',
        '-c:a','copy','-map_metadata','-1','-movflags','+faststart',str(video.resolve())],cwd=work,check=True,capture_output=True,timeout=seconds*8)
    subprocess.run([encoder,'-v','error','-xerror','-nostdin','-threads','2','-i',str(video),'-f','null','-'],check=True,capture_output=True,timeout=seconds*2)
    levels=verify_loudness(video,profile='exec_pitch_p3',timeout_sec=seconds*2)
    shutil.copyfile(captions,out/'subtitles.vtt');shutil.copyfile(root/'manuscript.json',out/'manuscript.json')
    (out/'narration.txt').write_text('\n\n'.join(s['narration'] for s in original['exec_pitch_input']['sections']))
    write_json(out/'voice_selection.json',json.loads((root/'human-selection.json').read_text()))
    write_json(out/'audio_placement.json',placement)
    write_json(out/'timeline.json',timeline)
    write_json(out/'admission.json',json.loads((root/'admission.json').read_text()))
    facts={'purpose':'PRIVATE_COMPARISON_PREVIEW_NOT_APPLICATION_DELIVERY','file_decode':'PASSED',
        'delivery_status':'BLOCKED','admission':'FAILED_NARRATION_DENSITY','content_status':'NOT_REVIEWED',
        'duration_seconds':seconds,'shots':len(records),'voice':'zh-CN-YunjianNeural','rate':'+10%',
        'text_unchanged_from_P1':True,'reference_picture_sha256':digest(picture.read_bytes()),'video_sha256':digest(video.read_bytes()),
        'levels':levels,'application_synthesis_requests':sum(r['application_synthesis_requests'] for r in records),
        'paid_provider_calls':0,'korean_synthesis_requests':0,'korean_translation_approval':'MISSING',
        'post_time_stretch':False,'raw_takes_ever_padded_for_admission':False,
        'comparison_cut':('fresh_trusted_HTML_on_measured_raw_take_clock' if natural_clock else 'unchanged_P1_192s_visual_clock_with_explicit_music_only_intervals'),
        'completed_settlement':False,'published':False,'push':False,'deploy':False}
    write_json(out/'facts.json',facts)
    print(json.dumps(facts,ensure_ascii=False),flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--reference-job',required=True)
    parser.add_argument('--runtime',required=True)
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--synthesize',action='store_true');mode.add_argument('--render-only',action='store_true')
    parser.add_argument('--natural-clock',action='store_true')
    args=parser.parse_args();root=Path(args.root).resolve();reference=Path(args.reference_job).resolve()
    os.environ.update(json.loads(Path(args.runtime).read_text()))
    # Process-only opt-in; no global configuration or account settings change.
    if args.synthesize:os.environ['NBPPT_MICROSOFT_EDGE_ENABLED']='true'
    original,records=prepare(root,reference,synthesize=args.synthesize)
    original['_reference_registry']=str(reference.parents[1]/'registry')
    if args.render_only:
        facts=json.loads((root/'admission.json').read_text());http=json.loads((root/'http-rejection.json').read_text())
        package=Path(facts['registry'])/facts['spec']['video_input_owner']/facts['input_id']/'input.json'
        if facts['admission']!='BLOCKED' or http['status']!=422 or digest(package.read_bytes())!=facts['input_id']:
            raise ValueError('Missing unchanged refused-input evidence')
    else:
        facts=rejected_input(root,original,records)
        asyncio.run(verify_rejection(root,facts))
    render_review(root,reference,original,records,natural_clock=args.natural_clock)


if __name__=='__main__':main()
