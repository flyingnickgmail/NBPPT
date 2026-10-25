"""Explicit synthetic media for exercising the real pipeline without providers."""
import math
from pathlib import Path
import shutil
import subprocess
import wave

import numpy as np

from gateway.exec_pitch_contract import canonical, digest, SAMPLE_RATE

SENTENCES = [
    '制作视频先保留完整原文，再明确受众要解决的具体问题。',
    '创作者需要说明目的，让后续段落围绕同一个论点展开。',
    '因果链把问题与机制连起来，也记录哪些结果仍然未知。',
    '原文引用为每个镜头保留依据，引用存在仍需核对语义。',
    '内容稿先写论证，口播再用简短连贯的句子表达。',
    '口播保留来源中的限制，不能用承诺代替待验证的结果。',
    '数字检查逐项对照来源，来源没有的数字不能擅自加入。',
    '用户确认文字后才提交生成，转写本身不创建视频任务。',
    '演示画面需要说明用途，测试图形不能作为真实客户证据。',
    '已登记内容包绑定当前账户，其他账户无法借用其编号。',
    '内容包摘要固定原稿，改动文字就会产生不同的输入身份。',
    '客户端只提交内容包编号，不能指定服务器上的任意文件。',
    '服务器检查音频摘要，再读取实际采样率与样本数量。',
    '镜头对应一段完整口播节拍，段落可以包含多个镜头。',
    '段落负责组织论证，镜头负责展现这一段中的具体动作。',
    '镜头数量与段落容量分别受限，增加镜头不会放宽正文限制。',
    '切点根据实测音频向后推进，每个节拍留出明确的呼吸空间。',
    '编码时钟与镜头时间轴一致，字幕时间由同一组切点转换。',
    '音频装不下就明确失败，不通过加速掩盖时间不足。',
    '画面短于口播时拒绝剪辑，不循环素材填满剩余时长。',
    '原始音频保留在登记包中，最终合成不重新请求配音。',
    '画面与音频摘要分别记录，便于复核每个镜头使用的输入。',
    '素材说明需要保留审批范围，文件可读并不等于允许商用。',
    '合成测试素材只验证工程机制，声音不用于评价配音自然度。',
    '渲染通过共享资源闸门串行执行，等待时持续报告实际阶段。',
    '取消任务时结束所属进程，释放资源后才报告最终状态。',
    '文件先写入暂存目录，通过校验后才发布为任务输出。',
    '视频的编码与画幅需要检查，只有文件头有效还不足以交付。',
    '完整解码逐帧读取成片，检查编码损坏与时长是否闭合。',
    '字幕文字逐镜对照口播，不能静默丢掉中间的一段。',
    '最终音轨重新测量响度，滤镜参数不能代替实际测量。',
    '分镜总览用于人工查看，每个镜头的代表帧保留在输出中。',
    '文件摘要记录发布时的内容，下载前再次复核这些摘要。',
    '任务与下载沿用账户鉴权，其他用户不能读取这份输出。',
    '重复提交同一个请求编号时返回原任务，避免重复冻结。',
    '请求编号对应的参数改变时拒绝提交，要求明确的新编号。',
    '失败任务退回冻结点数，重试创建新任务并保留原输入。',
    '短片继续使用原有入口，长片需要显式选择自己的预设。',
    '本地测试与部署分别报告，草稿完成不能证明线上已经可用。',
    '文件通过校验不代表内容已经人工审核，最后仍需人工判断。',
]


def build_fixture(registry, user_id, seconds=480):
    if seconds not in (6,480): raise ValueError('Only bounded test fixtures are provided')
    sentences=SENTENCES if seconds==480 else ['先保留原文。','不代表人工审核。']
    source='\n'.join(sentences)
    work=Path(registry)/'fixture-build';work.mkdir(parents=True,exist_ok=False)
    visual=work/'moving-test-pattern.mp4'
    subprocess.run(['ffmpeg','-v','error','-nostdin','-f','lavfi','-i',
        'testsrc2=size=1280x720:rate=24:duration=16','-an','-c:v','libx264','-preset','ultrafast',
        '-crf','32','-threads','2','-pix_fmt','yuv420p',str(visual)],check=True,timeout=120)
    visual_hash=digest(visual.read_bytes());assets={visual_hash+'.mp4':visual}
    durations=([8,11,13,16]*10) if seconds==480 else [3,3]
    shots=[];sections=[]
    for i,(sentence,duration) in enumerate(zip(sentences,durations),1):
        samples=round((duration-.75)*SAMPLE_RATE)
        t=np.arange(samples)/SAMPLE_RATE
        signal=.1*np.sin(2*math.pi*(220+i*7)*t)
        # A regular amplitude envelope gives a measurable non-silent test track.
        signal*=.65+.35*np.sin(2*math.pi*2*t)**2
        audio=work/f'beat-{i:03}.wav'
        with wave.open(str(audio),'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(SAMPLE_RATE)
            wav.writeframes((signal*32767).astype('<i2').tobytes())
        ah=digest(audio.read_bytes());assets[ah+'.wav']=audio
        section=(i+1)//2 if seconds==480 else i
        quote=sentence
        shots.append({'shot_num':i,'section_num':section,'narration':sentence,'source_quotes':[],
            'reason':'以明确标注的合成运动测试画面检验本段口播节拍，不作为真实客户素材。',
            'audio_sha256':ah,'visual_sha256':visual_hash,'audio_samples':samples,'lead_frames':6,'tail_frames':12})
    for i in range(1,max(s['section_num'] for s in shots)+1):
        group=[s for s in shots if s['section_num']==i];quotes=[s['narration'] for s in group]
        for shot in group: shot['source_quotes']=quotes
        sections.append({'section_num':i,'argument':'由已实现的视频制作流程说明输入、控制条件与可验证结果。',
                         'narration':''.join(s['narration'] for s in group),'source_quotes':quotes})
    value={'title':'视频制作链路工程排练','audience':'视频制作与验收人员','purpose':'验证有界长片与音频节拍时间轴',
        'thesis':'逐步把来源、口播、镜头、文件校验与账户交付连接起来。',
        'causal_chain':['先固定来源和因果论证，再保留逐段口播与证据。','实测音频决定镜头节拍，可信程序剪辑并复核交付。',
                        '文件验收后保留人工审阅状态，失败则退款并保留重试输入。'],
        'evidence_boundary':'本片使用合成运动测试画面和合成测试音调；字幕是排练稿，音调不是人声。只验证工程机制，未做内容、音质或客户质量验收。',
        'source_sha256':digest(source.encode()),'media_kind':'synthetic_fixture','sections':sections,'shots':shots}
    input_id=digest(canonical(value));owner=digest(user_id.encode());destination=Path(registry)/owner/input_id
    (destination/'assets').mkdir(parents=True,exist_ok=False)
    (destination/'input.json').write_bytes(canonical(value))
    for name,path in assets.items(): shutil.copyfile(path,destination/'assets'/name)
    shutil.rmtree(work)
    return source,input_id,value
