"""Measure the encoded audio, rather than trusting a normalization request."""
import json
import math
import re
import shutil
import subprocess


def profile_targets(profile='legacy'):
    if profile not in ('legacy','exec_pitch_p3'):
        raise ValueError('未知的音频响度配置')
    # Extra AAC headroom is intentional; acceptance measures encoded samples.
    return {'integrated':-16,'normalization_peak':-4.8 if profile=='exec_pitch_p3' else -2.5,
            'maximum_peak':-3.8 if profile=='exec_pitch_p3' else -1.5}


def measure_loudness(path, *, timeout_sec=120, profile='legacy', pre_filter=None):
    target=profile_targets(profile)
    result=subprocess.run([shutil.which('ffmpeg') or 'ffmpeg','-v','info','-nostdin',
        '-i',str(path),'-af',(pre_filter+',' if pre_filter else '')+f"loudnorm=I=-16:TP={target['normalization_peak']}:LRA=7:print_format=json",
        '-f','null','-'],capture_output=True,text=True,timeout=timeout_sec,check=True)
    blocks=re.findall(r'\{\s*"input_i".*?\}',result.stderr,re.S)
    if not blocks:
        raise ValueError('配音缺少有效响度测量')
    value=json.loads(blocks[-1])
    if any(not math.isfinite(float(value[k])) for k in
           ['input_i','input_tp','input_lra','input_thresh','target_offset']):
        raise ValueError('配音响度无效或整轨静音')
    return value


def verify_loudness(path, *, timeout_sec=120, profile='legacy'):
    target=profile_targets(profile)
    options={} if timeout_sec==120 else {'timeout_sec':timeout_sec}
    if profile!='legacy':options['profile']=profile
    levels=measure_loudness(path,**options)
    loudness=float(levels['input_i']);peak=float(levels['input_tp'])
    if not -17<=loudness<=-15 or peak>target['maximum_peak']:
        raise ValueError('最终成片配音未达到响度或真峰值标准')
    return {'integrated_lufs':loudness,'true_peak_dbfs':peak}
