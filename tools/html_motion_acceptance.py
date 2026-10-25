"""P1 real-content rehearsal using existing narration, never a new provider call."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import wave

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gateway.exec_pitch_contract import canonical,digest

SCENES=[
 ('title','原库位上，没有包裹',['预期库位','现场记录']),
 ('comparison','空货位，不能直接下结论',['现场没看到','仍待查证']),
 ('task_hub','把猜测变成可核对的事实',['仓管员','出库人员','负责人']),
 ('architecture','把分散的记录放在一起',['扫码记录','库位变更','交接备注']),
 ('timeline','每条线索，都保留来源',['时间','操作者','原始记录']),
 ('comparison','查证路线，不是找回的证据',['记录线索','现场结果']),
 ('process','先查交接，再去现场',['最近交接','现场核对','确认实物']),
 ('process','确认同一个包裹',['扫描标签','核对包裹','确认库位']),
 ('task_hub','未确认的部分，一并交接',['已核对','仍不清楚','负责人']),
 ('comparison','不能把猜测写成事实',['猜测','已确认事实']),
 ('architecture','线索可见，责任不转移',['线索','核查','判断']),
 ('process','现场确认后，再更正库位',['现场确认','更正库位','通知出库']),
 ('timeline','更正保留依据',['旧记录','更正依据','后续交接']),
 ('process','通知之后，还要核对',['接收通知','核对信息','完成后续']),
 ('task_hub','让处理记录用于复盘',['有效线索','交接缺口','规则调整']),
 ('comparison','一次演示，不证明效率提升',['演示过程','实测结果']),
 ('comparison','没有实测，就不承诺收益',['能力说明','收益依据']),
 ('process','先做小范围试点',['谁核对','谁确认','谁接收通知']),
 ('timeline','根据处理记录决定是否扩大',['处理记录','复盘','试点决定']),
 ('closing','让一次判断，留下依据',['仓库协作助手','先做小范围试点']),
]


def build_content(registry,user,cached):
    source=(cached/'planner/source.md').read_text();manuscript=json.loads((cached/'output/manuscript.json').read_text())
    work=registry/'build';work.mkdir(parents=True,exist_ok=False)
    # A legacy visual hash stays in the compatibility data contract. The HTML
    # scenes below do not display this file, or pretend it is client footage.
    placeholder=next(iter(sorted((cached/'film-render').glob('shot-*.mp4'))))
    vh=digest(placeholder.read_bytes());assets={vh+'.mp4':placeholder};shots=[];sections=[];provenance=[]
    original=cached/'output'/f'{cached.name}_video.mp4';cursor=0
    for i,(section,scene) in enumerate(zip(manuscript['sections'],SCENES),1):
        audio=work/f'beat-{i:02}.wav'
        # Reuse complete, already-timed takes from the existing final soundtrack,
        # including its pauses/music. Never pad, accelerate or stretch a raw VO
        # cache to get around the admitted pacing limit.
        subprocess.run(['ffmpeg','-v','error','-nostdin','-ss',str(cursor),'-i',str(original),'-t',str(section['duration_sec']),
                       '-vn','-ac','1','-ar','48000','-c:a','pcm_s16le',str(audio)],
                       check=True,timeout=30)
        with wave.open(str(audio),'rb') as wav:samples=wav.getnframes()
        ah=digest(audio.read_bytes());assets[ah+'.wav']=audio
        shots.append({'shot_num':i,'section_num':i,'narration':section['narration'],'source_quotes':section['source_quotes'],
            'reason':section['argument'],'audio_sha256':ah,'visual_sha256':vh,'audio_samples':samples,'lead_frames':6,'tail_frames':9,
            'motion':{'layout':scene[0],'headline':scene[1],'labels':scene[2],'focus':0}})
        sections.append({'section_num':i,'argument':section['argument'],'narration':section['narration'],'source_quotes':section['source_quotes']})
        provenance.append({'shot_num':i,'cached_relative':f'output/{cached.name}_video.mp4',
                           'cached_sha256':digest(original.read_bytes()),'start_sec':cursor,'duration_sec':section['duration_sec'],
                           'resampled_sha256':ah,'new_provider_calls':0})
        cursor+=section['duration_sec']
    total=sum((s['audio_samples']+1999)//2000+s['lead_frames']+s['tail_frames'] for s in shots)
    adjustment=round(total/24)*24-total
    for shot in shots:
        step=max(-3,min(3,adjustment));shot['tail_frames']+=step;adjustment-=step
    assert adjustment==0
    value={k:manuscript[k] for k in ('title','audience','purpose','thesis','causal_chain')}
    value.update(evidence_boundary='产品功能与情境演绎设定来自原文，不是客户真实事件或已测得的业务成效。声音复用既有成片完整段落音轨，保留原停顿及配乐，不加速、拉伸或新增留白，未重新调用提供方；画面为平台自绘机制动画，不是客户产品截图。未做内容人工验收。',
                 source_sha256=digest(source.encode()),media_kind='approved_local',sections=sections,shots=shots)
    input_id=digest(canonical(value));destination=registry/digest(user.encode())/input_id
    (destination/'assets').mkdir(parents=True,exist_ok=False);(destination/'input.json').write_bytes(canonical(value))
    for name,path in assets.items():shutil.copyfile(path,destination/'assets'/name)
    (registry.parent/'cached-audio-provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2))
    shutil.rmtree(work);return source,input_id,value


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--runtime',required=True)
    parser.add_argument('--cached-job',required=True);args=parser.parse_args()
    root=Path(args.root).resolve();root.mkdir(parents=True,exist_ok=False)
    environment=json.loads(Path(args.runtime).read_text());os.environ.update(environment)
    os.environ.update(NBPPT_REQUIRE_ISOLATION='true',DATABASE_PATH=str(root/'sandbox.db'),
                      NBPPT_EXEC_PITCH_ROOT=str(root/'registry'),NBPPT_JOBS_ROOT=str(root/'jobs'))
    from tools.exec_pitch_acceptance import acceptance
    cached=Path(args.cached_job).resolve()
    asyncio.run(acceptance(root,builder=lambda registry,user:build_content(registry,user,cached),milestone='P1',version='video_v2'))


if __name__=='__main__':main()
