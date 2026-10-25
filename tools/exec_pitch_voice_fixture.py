"""P3 synthetic-only bilingual/mix fixture; never writes human approvals."""
import json
import shutil
from datetime import datetime,timedelta,timezone
from pathlib import Path

from gateway.exec_pitch_contract import canonical,digest,validate_input
from tools.exec_pitch_fixture import build_fixture


def build_voice_fixture(registry,user_id,*,portrait=False,bilingual=True):
    source,old_id,value=build_fixture(registry,user_id,seconds=6)
    owner=digest(user_id.encode());old=Path(registry)/owner/old_id
    value['voice_mix']={'profile':'exec_pitch_p3','music':'original_ducked','input_audio':'dry_dialogue'}
    spec={'original_prompt_cn':source,'video_duration_sec':6,'video_aspect_ratio':'9:16' if portrait else '16:9',
          'video_subtitles':True,'video_input_owner':owner}
    # Motion labels must be source-grounded too.
    for shot in value['shots']:
        shot['motion']={'layout':'title','headline':shot['narration'],'labels':['原文','人工审核'],'focus':0}
    timeline=validate_input(value,spec)
    evidence=None
    if bilingual:
        now=datetime.now(timezone.utc)
        mapping={'enabled':True,'narration_language':'ko-KR','arrangement':'single_language_track',
                 'voice':'microsoft_injoon','rate':'+0%','record_type':'test_fixture',
                 'cues':[{'shot_num':s['shot_num'],'start_frame':c['start_frame'],'end_frame':c['end_frame'],
                          'zh':s['narration'],'ko':ko} for s,c,ko in zip(value['shots'],timeline['shots'],['원문 보존.','사람 검토 아님.'])]}
        record={'record_type':'test_fixture','reviewer':'SYNTHETIC_TEST_NOT_HUMAN_APPROVAL','owner':owner,
                'source_sha256':value['source_sha256'],'mapping_sha256':digest(canonical(mapping)),
                'audio_sha256':[s['audio_sha256'] for s in value['shots']],
                'scope':'translation_captions_and_single_language_audio',
                'approved_at':(now-timedelta(minutes=1)).isoformat(),'expires_at':(now+timedelta(days=1)).isoformat()}
        evidence=canonical(record);mapping['approval_sha256']=digest(evidence);value['bilingual']=mapping
        value['evidence_boundary']='合成测试运动图形与测试音调，不是韩语人声；中韩字幕为测试夹具，未获得人工译审或客户批准。'
    input_id=digest(canonical(value));root=Path(registry)/owner/input_id
    shutil.copytree(old,root);(root/'input.json').write_bytes(canonical(value))
    if evidence:
        (root/'evidence').mkdir();(root/'evidence'/f'{digest(evidence)}.json').write_bytes(evidence)
    return source,input_id,value
