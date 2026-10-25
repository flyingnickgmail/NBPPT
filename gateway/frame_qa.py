"""P4 final encoded frame evidence and conservative client-rule verdicts.

Mechanical frame checks do not certify branding, OCR or semantic correctness.
"""
import json
from pathlib import Path
import subprocess
import shutil
import tempfile

import numpy as np
from PIL import Image,ImageDraw

from gateway.exec_pitch_contract import digest
from gateway.motion_delivery import selection_expression,verify_motion_chunks


def client_rules(value,spec,registry,video=None,frames=None):
    if 'governance' in value:
        from gateway.exec_pitch_review import verdict
        return verdict(value,spec,video,frames)
    key=value['quality']['client_rules_sha256']
    if key is None:
        return {'status':'UNAVAILABLE','reason':'缺少已批准客户规则、品牌/产品素材及最终画面审核；不以机制示意或OCR猜测替代',
                'brand':'UNAVAILABLE','watermark':'NEEDS_REVIEW','forbidden_terms':'UNAVAILABLE'}
    from gateway.exec_pitch_inputs import safe_file
    from gateway.video_contract import _plain_text
    from datetime import datetime,timezone
    path=safe_file(registry,f'evidence/{key}.json',65536)
    if digest(path.read_bytes())!=key:raise ValueError('客户规则摘要改变')
    rule=json.loads(path.read_text())
    fields={'record_type','owner','source_sha256','reviewer','approved_at','expires_at','brand','forbidden_terms','required_terms'}
    if (not isinstance(rule,dict) or set(rule)!=fields or rule['owner']!=spec['video_input_owner']
            or rule['source_sha256']!=value['source_sha256']
            or rule['record_type']!=('test_fixture' if value['media_kind']=='synthetic_fixture' else 'human_record')):
        raise ValueError('客户规则未绑定真实人工记录、原文及账户')
    for k in ('reviewer','brand'):_plain_text(rule[k],k,80)
    dates=[datetime.fromisoformat(rule[k]) for k in ('approved_at','expires_at')]
    if any(d.tzinfo is None for d in dates) or not dates[0]<=datetime.now(timezone.utc)<dates[1]:
        raise ValueError('客户规则批准时间无效或过期')
    for k in ('forbidden_terms','required_terms'):
        if not isinstance(rule[k],list) or len(rule[k])>40:raise ValueError('客户用语规则超限')
        for term in rule[k]:_plain_text(term,k,80)
    text=json.dumps(value,ensure_ascii=False)
    violations=[t for t in rule['forbidden_terms'] if t in text]
    missing=[t for t in rule['required_terms'] if t not in text]
    # This scans declared Chinese text only. Final visual/OCR/brand evidence is
    # still missing, so clean strings must NEVER produce CLIENT_RULES_PASSED.
    return {'status':'FAILED' if violations or missing else 'NEEDS_REVIEW','forbidden_found':violations,
            'required_missing':missing,'text_scope':'registered_declared_text_only',
            'brand':'NEEDS_REVIEW','watermark':'NEEDS_REVIEW','final_visual_ocr':'UNAVAILABLE',
            'reason':'规则仅完成文字扫描，缺少绑定最终MP4的客户画面审批；不能推断品牌正确'}


def sample_frames(timeline):
    frames={0,timeline['total_frames']-1}
    for s in timeline['shots']:
        a,b=s['start_frame'],s['end_frame']
        frames.update((a,b-1,(a+b)//2,a+(b-a)//4,a+3*(b-a)//4))
    return sorted(frames)


def inspect_frames(video,spec,root):
    """Full-film black/freeze scan + real cut/intra-shot PNGs, bounded work."""
    timeline=spec['exec_pitch_timeline'];seconds=spec['video_duration_sec']
    work=root.parent/'frame-qa'
    if work.is_symlink() or work.exists() and not work.is_dir():raise ValueError('帧质检工作目录不安全')
    work.mkdir(exist_ok=True)
    if (work/'contact-sheet.png').is_symlink():raise ValueError('帧质检联系表路径不安全')
    # All frames, not just headers or selected representatives.
    raw=subprocess.run(['ffmpeg','-v','error','-nostdin','-threads','2','-i',str(video),'-an','-vf',
        'scale=96:54,format=gray','-f','rawvideo','-'],check=True,capture_output=True,timeout=max(120,seconds*2)).stdout
    if len(raw)!=timeline['total_frames']*96*54:raise ValueError('最终逐帧解码数量与时钟不一致')
    frames=np.frombuffer(raw,dtype=np.uint8).reshape((-1,54*96))
    # Captions/review labels must not disguise a black main picture.
    main_picture=frames.reshape((-1,54,96))[:,:43,:]
    black=np.flatnonzero(main_picture.mean(axis=(1,2))<2).tolist()
    same=np.all(frames[1:]==frames[:-1],axis=1);longest=run=1
    for matched in same:
        run=run+1 if matched else 1;longest=max(run,longest)
    if black:raise ValueError('最终编码包含黑帧：'+str(black[:8]))
    if longest>=48:raise ValueError('最终编码连续两秒完全冻结，须复核而非自动通过')
    # Existing independent browser/chunk comparison is retained unchanged.
    _,boundary=verify_motion_chunks(spec,root)
    wanted=sample_frames(timeline);evidence=[];tiles=[]
    with tempfile.TemporaryDirectory(prefix='scan-',dir=work) as temp:
        temp=Path(temp)
        for batch_index,offset in enumerate(range(0,len(wanted),500)):
            batch=wanted[offset:offset+500];folder=temp/str(batch_index);folder.mkdir()
            subprocess.run(['ffmpeg','-v','error','-nostdin','-threads','2','-i',str(video),'-vf',
                'select='+selection_expression(batch),'-fps_mode','vfr','-threads','2',str(folder/'%06d.png')],
                check=True,capture_output=True,timeout=max(120,seconds*2))
            files=sorted(folder.glob('*.png'))
            if len(files)!=len(batch):raise ValueError('最终帧抽样不完整')
            for n,file in zip(batch,files):
                target=work/f'frame-{n:06}.png'
                if target.is_symlink():raise ValueError('帧快照不能使用符号链接')
                target.write_bytes(file.read_bytes())
                evidence.append({'frame':n,'path':f'assets/qa_frames/frame-{n:06}.png','sha256':digest(file.read_bytes())})
                with Image.open(file) as im:
                    im.load()
                    tile=Image.new('RGB',(320,205),'#102D35');im.thumbnail((320,180));tile.paste(im,(0,0))
                    ImageDraw.Draw(tile).text((8,184),f'frame {n} | {n/24:.3f}s',fill='white');tiles.append(tile)
    sheet=Image.new('RGB',(1280,205*((len(tiles)+3)//4)),'#102D35')
    for i,t in enumerate(tiles):sheet.paste(t,((i%4)*320,(i//4)*205))
    sheet.save(work/'contact-sheet.png')
    saved=root/'assets/qa_frames'
    if any(p.is_symlink() for p in (root,root/'assets',saved)):raise ValueError('P4快照输出目录不安全')
    saved.mkdir(exist_ok=True)
    if any((saved/f'frame-{n:06}.png').is_symlink() for n in wanted) or (root/'assets/p4_contact.png').is_symlink():
        raise ValueError('P4快照输出不能覆盖符号链接')
    for n in wanted:shutil.copyfile(work/f'frame-{n:06}.png',saved/f'frame-{n:06}.png')
    shutil.copyfile(work/'contact-sheet.png',root/'assets/p4_contact.png')
    return {'status':'PASSED','scope':'full_decode_black_freeze_and_sampled_geometry_not_semantics',
            'decoded_frames':len(frames),'black_frames':black,'maximum_identical_frames':longest,
            'boundary':boundary,'samples':evidence,'sheet_sha256':digest((work/'contact-sheet.png').read_bytes()),
            'visual_semantics':'NEEDS_REVIEW','brand_ocr':'UNAVAILABLE'}


def run_p4(job_id,spec,root):
    from gateway.exec_pitch_inputs import load_input
    from gateway.word_alignment import load_alignment,verify_words,aligned_cues
    value,timeline,registry=load_input(spec['video_input_owner'],spec['video_input_id'],spec)
    alignment=load_alignment(value,spec,timeline,registry)
    video=root/f'{job_id}_video.mp4'
    def checked(action):
        try:return action()
        except ValueError as exc:return {'status':'FAILED','reason':str(exc)}
    words=checked(lambda:verify_words(video,value,timeline,alignment,registry))
    frames=checked(lambda:inspect_frames(video,spec,root))
    rules=checked(lambda:client_rules(value,spec,registry,video,frames if frames['status']=='PASSED' else None))
    report={'version':1,'profile':'exec_pitch_p4','video_sha256':digest(video.read_bytes()),
            'input_id':spec['video_input_id'],'alignment_sha256':value['quality']['alignment_sha256'],
            'FILE_OK':{'status':'PASSED','evidence':'independent_existing_decode_audio_duration_peak_manuscript_gate'},
            'WORD_SYNC':words,'FRAME_QA_PASSED':frames,'CLIENT_RULES_PASSED':rules,
            'content_status':'NOT_REVIEWED','korean_approval':'UNAVAILABLE',
            'caption_cues':aligned_cues(value,timeline,alignment),
            'delivery_status':'PASSED' if all(r['status']=='PASSED' for r in (words,frames,rules)) else 'BLOCKED'}
    if 'story' in value:
        from gateway.exec_pitch_contract import canonical
        report['STORY_INTEGRITY']={'status':'PASSED','brief_sha256':digest(canonical(value['story'])),
                                  'scope':'source_voice_and_evidence_contract_not_story_quality',
                                  'human_story_review':'NOT_REVIEWED','observed_outcomes':[]}
    (root/'p4_qa.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    if 'governance' in value:
        from gateway.exec_pitch_contract import canonical
        request={'record_type':'REVIEW_REQUEST_NOT_APPROVAL','owner':spec['video_input_owner'],
                 'input_id':spec['video_input_id'],'source_sha256':value['source_sha256'],
                 'profile_sha256':value['governance']['profile_sha256'],'video_sha256':report['video_sha256'],
                 'samples_sha256':digest(canonical(frames.get('samples',[]))),
                 'required_scopes':['brand','watermark','forbidden_terms','disclosure','redaction'],
                 'current_gates':{k:report[k]['status'] for k in ('FILE_OK','WORD_SYNC','FRAME_QA_PASSED','CLIENT_RULES_PASSED')},
                 'content_status':'NOT_REVIEWED','korean_approval':'UNAVAILABLE'}
        (root/'final_review_request.json').write_text(json.dumps(request,ensure_ascii=False,indent=2))
    if 'revision' in value:
        from gateway.exec_pitch_revision import verify_revision
        def revision_check():
            verify_revision(value,spec,root)
            return {'status':'PASSED','qa_reused':False}
        report['REVISION_INTEGRITY']=checked(revision_check)
        if report['REVISION_INTEGRITY']['status']!='PASSED':report['delivery_status']='BLOCKED'
        (root/'p4_qa.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report


def verify_p4_report(job_id,spec,root):
    from gateway.delivery import contained_file
    from gateway.exec_pitch_inputs import load_input
    from gateway.word_alignment import load_alignment,verify_words
    report_path=contained_file(root,'p4_qa.json')
    if report_path.stat().st_size>8*1024*1024:raise ValueError('P4报告超限')
    report=json.loads(report_path.read_text());video=contained_file(root,f'{job_id}_video.mp4')
    if (report.get('video_sha256')!=digest(video.read_bytes()) or report.get('input_id')!=spec['video_input_id']
            or report.get('delivery_status')!='PASSED'
            or any(report.get(k,{}).get('status')!='PASSED' for k in ('FILE_OK','WORD_SYNC','FRAME_QA_PASSED','CLIENT_RULES_PASSED'))
            or report.get('content_status')!='NOT_REVIEWED'):
        raise ValueError('P4必要门槛缺失或待审；不能交付、下载为合格输出或完成结算')
    value,timeline,registry=load_input(spec['video_input_owner'],spec['video_input_id'],spec)
    alignment=load_alignment(value,spec,timeline,registry)
    saved=contained_file(root,'word_alignment.json')
    if json.loads(saved.read_text())!=alignment:raise ValueError('交付逐字记录改变')
    if verify_words(video,value,timeline,alignment,registry)['status']!='PASSED':raise ValueError('P4逐字状态复检不通过')
    # Recompute the client verdict; a forged green JSON cannot clear missing
    # client approvals or uncertain visual evidence.
    if client_rules(value,spec,registry,video,report['FRAME_QA_PASSED'])['status']!='PASSED':raise ValueError('客户规则缺口不能伪造成通过')
    files=[report_path,saved,contained_file(root,'assets/p4_contact.png')]
    expected=sample_frames(timeline);samples=report['FRAME_QA_PASSED'].get('samples',[])
    if [s.get('frame') for s in samples]!=expected:raise ValueError('P4帧扫描覆盖不足')
    for s in samples:
        if s.get('path')!=f"assets/qa_frames/frame-{s['frame']:06}.png":raise ValueError('P4帧路径非法')
        path=contained_file(root,s['path'])
        if digest(path.read_bytes())!=s.get('sha256'):raise ValueError('P4帧快照改变')
        files.append(path)
    return files
