from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from tools.check_video_docs import capability_table, check_document, START, END
from tools.quality_gate import check_results


def test_capability_document_tracks_contracts_and_rejects_stale_claims():
    expected=capability_table()
    check_document(START+'\n'+expected+'\n'+END,expected)
    with pytest.raises(ValueError,match='不一致'):
        check_document(START+'\n'+expected.replace('6–600','6–60')+'\n'+END,expected)
    with pytest.raises(ValueError,match='唯一'):
        check_document(START+expected+END+START+END,expected)


def write_cases(path, cases):
    suite=ET.Element('testsuite')
    for module,name,reason in cases:
        case=ET.SubElement(suite,'testcase',classname=module,name=name)
        if reason:ET.SubElement(case,'skipped',message=reason)
    ET.ElementTree(suite).write(path)


def test_gate_only_allows_explicit_optional_skips(tmp_path):
    report=tmp_path/'results.xml'
    required=('test_video_integrated','test_real_media_failure_refund_retry_download_and_voice[False]',None)
    write_cases(report,[required,('test_video_speech','optional','trusted MeloTTS runtime not configured')])
    assert check_results(report)['passed']==1
    write_cases(report,[required,('test_security_delivery','auth','ffmpeg unavailable')])
    with pytest.raises(ValueError,match='Unexpected'):check_results(report)
    write_cases(report,[('test_video_integrated',required[1],'optional voice integration runtime required')])
    with pytest.raises(ValueError,match='must execute'):check_results(report)
    write_cases(report,[])
    with pytest.raises(ValueError,match='must execute'):check_results(report)
