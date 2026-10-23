import copy
import json

import pytest
from fastapi.testclient import TestClient

from tools.report_studio.app import (
    ExportInput, Report, app, export_html, local_report, validate_evidence,
)


@pytest.fixture
def sample():
    from tools.report_studio.app import ROOT
    return json.loads((ROOT / "sample.json").read_text())


def test_sample_evidence_and_offline_export(sample):
    report = Report.model_validate(sample["report"])
    validate_evidence(report, sample["content"])
    html = export_html(ExportInput.model_validate(sample))
    assert '<script src=' not in html
    assert '<link rel="stylesheet"' not in html
    assert 'ReportView.mount' in html
    assert sample['report']['title'] in html


def test_import_cannot_escape_script(sample):
    attack = '</script><img src=x onerror="alert(1)">'
    sample['report']['title'] = attack
    sample['content'] += attack
    html = export_html(ExportInput.model_validate(sample))
    assert attack not in html
    assert '\\u003c/script>' in html
    assert '.textContent=text' in html


def test_rejects_fabricated_number(sample):
    sample['report']['sections'][0]['chart']['points'][0]['value'] = 999
    with pytest.raises(ValueError, match='数字'):
        validate_evidence(Report.model_validate(sample['report']), sample['content'])


def test_rejects_substring_number(sample):
    sample['report']['sections'][0]['chart']['points'][0].update(value=2, quote='第一季度交付12万辆')
    with pytest.raises(ValueError, match='数字'):
        validate_evidence(Report.model_validate(sample['report']), sample['content'])


def test_rejects_invented_quote(sample):
    sample['report']['metrics'][0]['quote'] = '前三季度交付45万辆已独立核验。'
    with pytest.raises(ValueError, match='引文'):
        validate_evidence(Report.model_validate(sample['report']), sample['content'])


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'https://invented.example/report'])
def test_rejects_invented_or_executable_sources(sample, url):
    sample['report']['sources'] = [{'label': '伪来源', 'url': url}]
    with pytest.raises(ValueError, match='链接'):
        validate_evidence(Report.model_validate(sample['report']), sample['content'])


def test_negative_and_zero_data_valid(sample):
    sample['content'] += '\n示例变化：东区-3辆，南区0辆。'
    sample['report']['sections'][0]['chart'].update(kind='bar', unit='辆', points=[
        {'label': '东区', 'value': -3, 'quote': '东区-3辆'},
        {'label': '南区', 'value': 0, 'quote': '南区0辆'}])
    validate_evidence(Report.model_validate(sample['report']), sample['content'])


def test_local_preserves_content_and_makes_no_metrics():
    content = '# 标题\n\n## 分析\n第一段。\n- 行动一\n- 行动二\n<script>alert(1)</script>'
    report = local_report(content)
    assert report.title == '标题'
    assert not report.metrics
    assert report.sections[0].bullets == ['行动一', '行动二']
    assert '<script>alert(1)</script>' in report.sections[0].paragraphs
    assert all(s.chart.kind == 'none' for s in report.sections)


def test_no_silent_truncation():
    content = '\n'.join(f'第{i}条材料' for i in range(65))
    report = local_report(content)
    actual = [p for s in report.sections for p in s.paragraphs]
    assert actual == content.splitlines()
    with pytest.raises(ValueError, match='章节超过'):
        local_report('\n'.join(f'## 第{i}节\n材料' for i in range(25)))


def test_bad_or_missing_chart_data(sample):
    for changed in ({'points': []}, {'unit': ''}, {'points': sample['report']['sections'][0]['chart']['points'][:1]}):
        data = copy.deepcopy(sample)
        data['report']['sections'][0]['chart'].update(changed)
        with pytest.raises(ValueError):
            validate_evidence(Report.model_validate(data['report']), data['content'])


def test_generation_and_preview_roundtrip(sample):
    with TestClient(app) as client:
        result = client.post('/api/generate', json={'content': '# 测试\n## 章节\n保留这段材料', 'mode': 'local'})
        assert result.status_code == 200
        assert result.json()['content'].endswith('保留这段材料')
        exported = client.post('/api/export', json=result.json())
        assert exported.status_code == 200
        preview = client.post('/api/preview', json=sample)
        assert preview.status_code == 200
        assert client.get(preview.json()['url']).text == export_html(ExportInput.model_validate(sample))
        assert client.get('/preview/missing').status_code == 404
        assert client.post('/api/generate', json={'content': '   '}).status_code == 422
        assert client.post('/api/generate', json={'content': 'x' * 60001}).status_code == 422


def test_cross_origin_and_foreign_host_denied():
    with TestClient(app) as client:
        assert client.get('/', headers={'host': 'evil.example'}).status_code == 403
        assert client.post('/api/generate', headers={'origin': 'https://evil.example'}, json={'content': 'text'}).status_code == 403


@pytest.mark.anyio
async def test_ai_failure_is_not_demo(monkeypatch):
    import tools.report_studio.app as module
    async def failure(*args):
        from fastapi import HTTPException
        raise HTTPException(502, '模型生成失败')
    monkeypatch.setattr(module, 'ai_report', failure)
    with TestClient(app) as client:
        res = client.post('/api/generate', json={'content': '材料', 'mode': 'ai'})
        assert res.status_code == 502
        assert 'report' not in res.json()

@pytest.mark.parametrize('quote,value,valid', [
    ('Sales were down by around 5% y-o-y.', -5, True),
    ('Sales were around 1% lower compared to the same period.', -1, True),
    ('销量同比下降4.5%。', -4.5, True),
    ('Sales increased by around 5%.', -5, False),
    ('The rate fell to 5%.', -5, False),
    ('A 5% lower limit applies.', -5, False),
    ('Sales were down by around 5%.', -5.1, False),
])
def test_chart_explicit_decline_keeps_magnitude(sample, quote, value, valid):
    sample['content'] += '\n' + quote
    sample['report']['sections'][0]['chart'].update(kind='bar', unit='%', points=[
        {'label': '观察', 'value': value, 'quote': quote}])
    report = Report.model_validate(sample['report'])
    if valid:
        validate_evidence(report, sample['content'])
    else:
        with pytest.raises(ValueError, match='数字'):
            validate_evidence(report, sample['content'])


def test_international_thousands_grouping_is_not_unit_conversion(sample):
    from tools.report_studio.evidence import number_tokens
    assert number_tokens('140 000; +100\u202f000; 95\u00a0000') == [140000, 100000, 95000]
    assert number_tokens('2026 9 1 2') == [2026, 9, 1, 2]
    quote = 'Germany sold 140 000 more cars.'
    sample['content'] += '\n' + quote
    point = {'label': '德国', 'value': 140000, 'quote': quote}
    sample['report']['sections'][0]['chart'].update(kind='bar', unit='辆', points=[point])
    validate_evidence(Report.model_validate(sample['report']), sample['content'])
    point['value'] = 140
    with pytest.raises(ValueError, match='数字'):
        validate_evidence(Report.model_validate(sample['report']), sample['content'])
