"""P4 registered acoustic character anchors, never proportional text timing.

The administrator registers local model output, not human content approval.
Point spans and overlapping predictions remain uncertain; no interpolation.
"""
import html
import json
import unicodedata

from gateway.exec_pitch_contract import digest, hash_id


def spoken(text):
    return ''.join(c for c in text if unicodedata.category(c)[0] in 'LN')


def validate_quality(value,spec):
    q=value.get('quality')
    if q is None:return
    if (not isinstance(q,dict) or set(q)!={'profile','alignment_sha256','client_rules_sha256'}
            or q['profile']!='exec_pitch_p4' or not hash_id(q['alignment_sha256'])
            or q['client_rules_sha256'] is not None and not hash_id(q['client_rules_sha256'])
            or value.get('bilingual') is not None or spec.get('video_subtitles') is not True
            or spec.get('video_render_engine','html_chromium')!='html_chromium'
            or value.get('voice_mix',{}).get('profile')!='exec_pitch_p3'):
        raise ValueError('P4须使用明确中文单语、P3混音、烧录字幕和登记逐字对齐；双语缺口不能替代')


def load_alignment(value,spec,timeline,root):
    if 'quality' not in value:return None
    from gateway.exec_pitch_inputs import safe_file
    key=value['quality']['alignment_sha256'];path=safe_file(root,f'evidence/{key}.json',2*1024*1024)
    if digest(path.read_bytes())!=key:raise ValueError('逐字对齐记录摘要改变')
    a=json.loads(path.read_text())
    if (not isinstance(a,dict) or set(a)-{'recheck'}!={'version','owner','source_sha256','engine','shots'}
            or type(a['version']) is not int or a['version'] not in (1,2)
            or (a['version']==2)!=('recheck' in a)
            or a['owner']!=spec['video_input_owner'] or a['source_sha256']!=value['source_sha256']):
        raise ValueError('逐字对齐记录与账户或原文不一致')
    engine=a['engine']
    if (not isinstance(engine,dict) or set(engine)!={'name','version','model_manifest_sha256','quantum_ms','timestamp_repair','record_type'}
            or engine['name']!='qwen3-forced-aligner-mlx' or engine['version']!='0.5.9'
            or not hash_id(engine['model_manifest_sha256']) or engine['quantum_ms']!=80
            or engine['timestamp_repair']!='disabled_no_interpolation'):
        raise ValueError('逐字对齐缺少固定模型、精度或禁止插值证据')
    if engine['record_type']!=('test_fixture' if value['media_kind']=='synthetic_fixture' else 'model_output'):
        raise ValueError('逐字合成测试记录不能作为真实模型输出')
    if not isinstance(a['shots'],list) or len(a['shots'])!=len(value['shots']):
        raise ValueError('逐字对齐未覆盖全部镜头')
    for s,r in zip(value['shots'],a['shots']):
        fields={'shot_num','audio_sha256','narration_sha256','units'}|({'inference_prefix_samples'} if a['version']==2 else set())
        if (not isinstance(r,dict) or set(r)!=fields
                or type(r['shot_num']) is not int or r['shot_num']!=s['shot_num'] or r['audio_sha256']!=s['audio_sha256']
                or r['narration_sha256']!=digest(s['narration'].encode())
                or not isinstance(r['units'],list) or not 1<=len(r['units'])<=80):
            raise ValueError('逐字对齐与登记录音或口播身份不一致')
        prefix=r.get('inference_prefix_samples',0)
        if type(prefix) is not int or prefix not in (0,1920):raise ValueError('对齐复核只能使用固定40毫秒分析偏移')
        previous_start=previous_end=0
        for u in r['units']:
            if (not isinstance(u,dict) or set(u)!={'text','start_sample','end_sample'}
                    or not isinstance(u['text'],str) or not 1<=len(u['text'])<=30 or spoken(u['text'])!=u['text']
                    or any(type(u[k]) is not int for k in ('start_sample','end_sample'))
                    or not previous_start<=u['start_sample']<=u['end_sample']<=s['audio_samples']
                    or u['end_sample']<previous_end or previous_end-u['start_sample']>3840
                    or any((u[k]+prefix)%3840 for k in ('start_sample','end_sample'))):
                raise ValueError('逐字时间无效、倒序、超出实测音频或非模型时钟')
            previous_start,previous_end=u['start_sample'],u['end_sample']
        if ''.join(u['text'] for u in r['units'])!=spoken(s['narration']):
            raise ValueError('逐字对齐文字缺失、替换或重复')
    if a['version']==2:
        verify_recheck(value,spec,timeline,root,a)
    return a


def verify_recheck(value,spec,timeline,root,a):
    """Validate actual prefixed-audio inference, preserving raw v1 evidence.

    Offset subtraction is a coordinate transform, never timestamp interpolation.
    40ms is fixed before selecting results; 80/120ms probes test stability.
    """
    import wave
    from gateway.exec_pitch_inputs import safe_file
    from copy import deepcopy
    meta=a['recheck']
    if not isinstance(meta,dict) or set(meta)!={'parent_alignment_sha256','evidence_sha256'} or not all(hash_id(k) for k in meta.values()):
        raise ValueError('复核缺少原始对齐与完整分析证据')
    parent_value=deepcopy(value);parent_value['quality']['alignment_sha256']=meta['parent_alignment_sha256']
    parent_path=safe_file(root,f"evidence/{meta['parent_alignment_sha256']}.json",2*1024*1024)
    if json.loads(parent_path.read_text()).get('version')!=1:raise ValueError('复核父记录只能是原始版本，禁止递归')
    parent=load_alignment(parent_value,spec,timeline,root)
    if parent['version']!=1 or parent['engine']!=a['engine']:raise ValueError('复核不能替换原模型或递归改写结果')
    path=safe_file(root,f"evidence/{meta['evidence_sha256']}.json",2*1024*1024)
    if digest(path.read_bytes())!=meta['evidence_sha256']:raise ValueError('复核记录摘要改变')
    evidence=json.loads(path.read_text())
    if (set(evidence)!={'status','original_alignment_sha256','trials'}
            or evidence['status']!='MACHINE_RECHECK_NOT_HUMAN_APPROVAL'
            or evidence['original_alignment_sha256']!=meta['parent_alignment_sha256']):
        raise ValueError('复核记录类型或父记录错误')
    changed={r['shot_num'] for r in a['shots'] if r['inference_prefix_samples']}
    trials=evidence['trials']
    if not isinstance(trials,list) or len(trials)!=len(changed)*3:raise ValueError('分析复核次数不完整')
    for s,old,new in zip(value['shots'],parent['shots'],a['shots']):
        if s['shot_num'] not in changed:
            if {k:v for k,v in new.items() if k!='inference_prefix_samples'}!=old:raise ValueError('未复核的时间被改变')
            continue
        rows=[t for t in trials if t['shot_num']==s['shot_num']]
        if [t['prefix_silence_samples'] for t in rows]!=[1920,3840,5760]:raise ValueError('分析偏移必须固定40/80/120毫秒')
        with wave.open(str(safe_file(root,f"assets/{s['audio_sha256']}.wav",2_000_000)),'rb') as w:
            pcm=w.readframes(w.getnframes())
        for t in rows:
            if (set(t)!={'shot_num','prefix_silence_samples','original_audio_sha256','probe_audio_sha256','units','timestamp_repair'}
                    or type(t['prefix_silence_samples']) is not int or t['original_audio_sha256']!=s['audio_sha256']
                    or t['timestamp_repair']!='disabled_no_interpolation' or not hash_id(t['probe_audio_sha256'])
                    or len(t['units'])!=len(old['units'])):raise ValueError('复核音频/模型记录非法')
            p=safe_file(root,f"evidence/{t['probe_audio_sha256']}.wav",2_100_000)
            if digest(p.read_bytes())!=t['probe_audio_sha256']:raise ValueError('分析音频摘要改变')
            with wave.open(str(p),'rb') as w:
                if (w.getparams()[:3]!=(1,2,48000) or w.readframes(w.getnframes())!=b'\0'*(t['prefix_silence_samples']*2)+pcm):
                    raise ValueError('分析输入必须是原声音加固定前缀静音，不能修改声音')
            for u,o in zip(t['units'],old['units']):
                if (set(u)!={'text','start_sample','end_sample'} or u['text']!=o['text']
                        or any(type(u[k]) is not int or (u[k]+t['prefix_silence_samples'])%3840 for k in ('start_sample','end_sample'))
                        or not 0<=u['start_sample']<=u['end_sample']<=s['audio_samples']):
                    raise ValueError('分析复核不是原稿的真实模型时钟')
        if new['units']!=rows[0]['units'] or any(u['start_sample']>=u['end_sample'] for u in new['units']):
            raise ValueError('固定40毫秒复核仍有未解决的时间区间')
        if any(x['end_sample']>y['start_sample'] for x,y in zip(new['units'],new['units'][1:])):
            raise ValueError('复核仍存在重叠')
        for i,o in enumerate(old['units']):
            for k in ('start_sample','end_sample'):
                times=[t['units'][i][k] for t in rows]
                if max(times)-min(times)>3840 or abs(new['units'][i][k]-o[k])>3840:
                    raise ValueError('复核边界不稳定，不能消除待审')


def aligned_cues(value,timeline,alignment):
    """Clause captions use observed anchors, quantized outward onto 24Hz.

    Punctuation is retained on its clause; no timestamps are invented for it.
    """
    cues=[]
    for shot,cut,record in zip(value['shots'],timeline['shots'],alignment['shots']):
        units=record['units'];slots=[];position=0
        for u in units:
            start=shot['narration'].find(u['text'],position)
            if start<0:raise ValueError('逐字文本不能映射回原稿')
            slots.append(start);position=start+len(u['text'])
        groups=[];begin=0
        for i in range(len(units)):
            stop=slots[i+1] if i+1<len(units) else len(shot['narration'])
            text=shot['narration'][slots[begin]:stop]
            span=units[i]['end_sample']-units[begin]['start_sample']
            if i==len(units)-1 or span>=48000 and (text[-1] in '，。；！？' or len(text)>=16):
                groups.append((begin,i,text));begin=i+1
        # A trailing fragment stays with its preceding clause; retain measured
        # endpoints rather than manufacturing dwell time for one final glyph.
        if len(groups)>1:
            first,last,text=groups[-1]
            if units[last]['end_sample']-units[first]['start_sample']<38400:
                a,b,previous=groups[-2];groups[-2:]=[(a,last,previous+text)]
        for j,(first,last,text) in enumerate(groups):
            start=(cut['speech_start_sample']+units[first]['start_sample'])//2000
            end=((cut['speech_start_sample']+units[groups[j+1][0]]['start_sample'])//2000
                 if j+1<len(groups) else (cut['speech_start_sample']+units[last]['end_sample']+1999)//2000)
            if not cut['start_frame']<=start<end<=cut['end_frame']:
                raise ValueError('逐字字幕超出实际镜头或倒序')
            cues.append({'shot_num':shot['shot_num'],'start_frame':start,'end_frame':end,'text':text})
    return cues


def aligned_vtt(value,timeline,alignment):
    from worker.video_speech import _stamp
    lines=['WEBVTT','']
    for c in aligned_cues(value,timeline,alignment):
        lines.extend([f"{_stamp(c['start_frame']/24)} --> {_stamp(c['end_frame']/24)}",html.escape(c['text']),''])
    return '\n'.join(lines)


def verify_words(video,value,timeline,alignment,root):
    """Measure each acoustic anchor's local delay in the FINAL decoded AAC.

    ±250ms search, 0.25ms resolution, 2-frame (83.34ms) rejection tolerance.
    Original beat correlation remains an independent gate.
    """
    import subprocess,wave
    import numpy as np
    result=subprocess.run(['ffmpeg','-v','error','-nostdin','-threads','2','-i',str(video),'-vn','-ac','1','-ar','48000','-f','s16le','-'],check=True,capture_output=True,timeout=max(120,timeline['total_frames']//12))
    decoded=np.frombuffer(result.stdout,dtype='<i2').astype(np.float64)
    checks=[];uncertain=[]
    for shot,cut,record in zip(value['shots'],timeline['shots'],alignment['shots']):
        with wave.open(str(root/'assets'/f"{shot['audio_sha256']}.wav"),'rb') as wav:
            source=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').astype(np.float64)
        for index,u in enumerate(record['units']):
            # A fixed acoustic context around the actual model onset; no text
            # lengths are used. Downsample only this delay comparison to 4kHz.
            start=max(0,min(len(source)-14400,u['start_sample']-4800))
            expected=source[start:start+14400:12].copy();expected-=expected.mean()
            offset=cut['speech_start_sample']+start;radius=12000
            left=offset-radius;right=offset+14400+radius
            actual=np.pad(decoded[max(0,left):min(len(decoded),right)],(max(0,-left),max(0,right-len(decoded))))[::12]
            energy=np.dot(expected,expected)
            dots=np.correlate(actual,expected,'valid')
            sums=np.convolve(actual,np.ones(len(expected)),'valid')
            square=np.convolve(actual*actual,np.ones(len(expected)),'valid')-sums*sums/len(expected)
            correlation=dots/np.sqrt(np.maximum(square*energy,1))
            at=int(np.argmax(correlation));delay=(at*12-radius)/48000
            score=float(correlation[at])
            if abs(delay)>2/24 or score<.80:
                raise ValueError(f"第{shot['shot_num']}镜第{index+1}字音轨错位或波形不符：{delay:.4f}秒/{score:.3f}")
            checks.append({'shot_num':shot['shot_num'],'unit':index+1,'text':u['text'],
                           'delay_samples':at*12-radius,'correlation':round(score,6)})
            if u['start_sample']==u['end_sample']:
                uncertain.append({'shot_num':shot['shot_num'],'unit':index+1,'text':u['text'],'reason':'zero_span_at_model_80ms_quantum'})
            if index and record['units'][index-1]['end_sample']>u['start_sample']:
                uncertain.append({'shot_num':shot['shot_num'],'unit':index+1,'text':u['text'],
                                  'reason':'overlap_at_model_80ms_quantum',
                                  'overlap_samples':record['units'][index-1]['end_sample']-u['start_sample']})
    return {'status':'NEEDS_REVIEW' if uncertain else 'PASSED','method':'acoustic_character_anchor_delay',
            'model_quantum_ms':80,'delay_tolerance_samples':4000,'search_radius_samples':12000,
            'max_abs_delay_samples':max(abs(c['delay_samples']) for c in checks),
            'minimum_correlation':min(c['correlation'] for c in checks),'checks':checks,'uncertain_units':uncertain,
            'note':'Model estimates are not phonetic truth or human approval; zero spans are not expanded.'}
