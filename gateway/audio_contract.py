"""Measure the encoded audio, rather than trusting a normalization request."""
import json
import math
import re
import shutil
import subprocess


def measure_loudness(path):
    result=subprocess.run([shutil.which('ffmpeg') or 'ffmpeg','-v','info','-nostdin',
        '-i',str(path),'-af','loudnorm=I=-16:TP=-2.5:LRA=7:print_format=json',
        '-f','null','-'],capture_output=True,text=True,timeout=120,check=True)
    blocks=re.findall(r'\{\s*"input_i".*?\}',result.stderr,re.S)
    if not blocks:
        raise ValueError('配音缺少有效响度测量')
    value=json.loads(blocks[-1])
    if any(not math.isfinite(float(value[k])) for k in
           ['input_i','input_tp','input_lra','input_thresh','target_offset']):
        raise ValueError('配音响度无效或整轨静音')
    return value


def verify_loudness(path):
    levels=measure_loudness(path)
    loudness=float(levels['input_i']);peak=float(levels['input_tp'])
    if not -17<=loudness<=-15 or peak> -1.5:
        raise ValueError('最终成片配音未达到响度或真峰值标准')
    return {'integrated_lufs':loudness,'true_peak_dbfs':peak}
