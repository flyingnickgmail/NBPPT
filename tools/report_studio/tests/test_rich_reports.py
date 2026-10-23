import copy

import pytest
from fastapi.testclient import TestClient

from tools.report_studio.app import app, export_html
from tools.report_studio.evidence import validate_evidence
from tools.report_studio.models import ExportInput, Report


@pytest.fixture
def rich():
    source = {"id": "S01", "label": "试验材料", "url": "https://example.org/material", "date": "2026-10-01", "category": "测试", "version": "样本"}
    content = "2026-10-01 https://example.org/material\n甲营收120亿元、净利-3亿元；乙营收90亿元、净利0亿元。\n周转天数现状65天，建议50天。服务收入未单列，建议100亿元。\n建议2026-10开始采集；建议2026-12核对记录；建议2027-02验收。"
    base = {"title": "", "note": "样本不是实际业务数据", "source_ids": ["S01"], "width": "full"}
    visuals = [
        {**base, "kind": "matrix", "title": "同单位比较", "columns": [{"label": "营收", "unit": "亿元"}, {"label": "净利", "unit": "亿元"}], "rows": [
            {"label": "甲", "emphasis": True, "cells": [{"value": "120", "quote": "甲营收120亿元、净利-3亿元", "source_ids": ["S01"]}, {"value": "-3", "quote": "甲营收120亿元、净利-3亿元", "source_ids": ["S01"]}]},
            {"label": "乙", "emphasis": False, "cells": [{"value": "90", "quote": "乙营收90亿元、净利0亿元", "source_ids": ["S01"]}, {"value": "—", "quote": "", "source_ids": []}]}
        ]},
        {**base, "kind": "targets", "title": "现状与建议", "items": [
            {"label": "周转天数", "baseline": "65", "target": "50", "unit": "天", "direction": "down", "quote": "周转天数现状65天，建议50天。", "source_ids": ["S01"]},
            {"label": "服务收入", "baseline": "未单列", "target": "100", "unit": "亿元", "direction": "neutral", "quote": "服务收入未单列，建议100亿元。", "source_ids": ["S01"]}
        ]},
        {**base, "kind": "roadmap", "title": "建议路线", "periods": ["2026-10", "2026-12", "2027-02"], "milestones": [
            {"lane": "采集", "period": "2026-10", "end_period": "", "label": "开始采集", "status": "proposal", "quote": "建议2026-10开始采集", "source_ids": ["S01"]},
            {"lane": "验收", "period": "2027-02", "end_period": "", "label": "验收", "status": "proposal", "quote": "建议2027-02验收", "source_ids": ["S01"]}
        ]},
        {**base, "kind": "car", "title": "指标主题图", "metrics": [{"label": "样本营收", "value": "120亿元", "quote": "甲营收120亿元、净利-3亿元", "source_ids": ["S01"]}]}
    ]
    report = {"title": "汽车样本：报告检验", "title_lines": ["汽车样本", "报告检验"], "cover_style": "automotive", "subtitle": "只用于检验图形", "summary": "虚构测试材料，不代表真实企业。", "metrics": [], "sources": [source], "sections": [{"label": "多图", "title": "一个章节包含四种表达", "paragraphs": ["测试材料。"], "bullets": [], "chart": None, "visuals": visuals, "source_ids": ["S01"], "layout": "feature"}]}
    return {"report": report, "content": content, "theme": "paper", "mode": "import"}


def test_multiple_visuals_and_offline_render(rich):
    data = ExportInput.model_validate(rich)
    validate_evidence(data.report, data.content)
    html = export_html(data)
    assert 'ReportVisuals' in html
    assert 'vehicle-svg' in html
    assert '<script src=' not in html
    assert len(data.report.sections[0].visuals) == 4
    with TestClient(app) as client:
        response = client.post('/api/preview', json=rich)
        assert response.status_code == 200
        assert client.get(response.json()['url']).status_code == 200


@pytest.mark.parametrize('change,message', [
    ('row_length', '单元格'), ('fabricated', '数字'), ('sign', '数字'),
    ('unknown_source', '来源编号'), ('direction', '方向'), ('outside_time', '时间列'),
    ('reversed_time', '早于'), ('duplicate_id', '重复'), ('fake_date', '日期'), ('title_loss', '标题'),
])
def test_rich_rejects_invalid_data(rich, change, message):
    report = rich['report']; visuals = report['sections'][0]['visuals']
    if change == 'row_length': visuals[0]['rows'][0]['cells'].pop()
    elif change == 'fabricated': visuals[0]['rows'][0]['cells'][0]['value'] = '999'
    elif change == 'sign': visuals[0]['rows'][0]['cells'][1]['value'] = '3'
    elif change == 'unknown_source': visuals[0]['source_ids'] = ['S404']
    elif change == 'direction': visuals[1]['items'][0]['direction'] = 'up'
    elif change == 'outside_time': visuals[2]['milestones'][0]['period'] = '2028-12'
    elif change == 'reversed_time': visuals[2]['milestones'][1]['end_period'] = '2026-10'
    elif change == 'duplicate_id': report['sources'].append(copy.deepcopy(report['sources'][0]))
    elif change == 'fake_date': report['sources'][0]['date'] = '1900-01-01'
    elif change == 'title_loss': report['title_lines'] = ['删除了原标题']
    with pytest.raises(ValueError, match=message):
        validate_evidence(Report.model_validate(report), rich['content'])


def test_missing_is_not_zero(rich):
    data = ExportInput.model_validate(rich)
    assert data.report.sections[0].visuals[1].items[1].baseline == '未单列'
    assert data.report.sections[0].visuals[0].rows[1].cells[1].value == '—'
    validate_evidence(data.report, data.content)


def test_roadmap_rejects_fabricated_event_number(rich):
    rich['report']['sections'][0]['visuals'][2]['milestones'][0]['label'] = '采集999家店'
    with pytest.raises(ValueError, match='数字'):
        validate_evidence(Report.model_validate(rich['report']), rich['content'])


def test_repairs_only_reported_fields(rich):
    from tools.report_studio.evidence import EvidenceIssues
    from tools.report_studio.generator import Corrections, apply_corrections
    rich['report']['sections'][0]['visuals'][0]['rows'][0]['cells'][1]['value'] = '3'
    report = Report.model_validate(rich['report'])
    with pytest.raises(EvidenceIssues) as caught:
        validate_evidence(report, rich['content'])
    issues = caught.value.issues
    path = issues[0]['path'] + '/value'
    repaired = apply_corrections(report, issues, Corrections(patches=[{'path': path, 'text': '-3'}]))
    validate_evidence(repaired, rich['content'])
    assert repaired.sections[0].paragraphs == report.sections[0].paragraphs
    assert repaired.sections[0].visuals[1:] == report.sections[0].visuals[1:]
    assert report.sections[0].visuals[0].rows[0].cells[1].value == '3'
    with pytest.raises(ValueError, match='超出'):
        apply_corrections(report, issues, Corrections(patches=[{'path': '/title', 'text': '越权改写'}]))
    with pytest.raises(ValueError, match='超出'):
        apply_corrections(report, issues, Corrections(patches=[{'path': path, 'text': '-3'}, {'path': path, 'text': '-3'}]))


@pytest.mark.anyio
async def test_generator_repairs_then_revalidates(rich, monkeypatch, business_question):
    import tools.report_studio.generator as module
    rich['report']['sections'][0]['visuals'][0]['rows'][0]['cells'][1]['value'] = '3'
    report = Report.model_validate(rich['report'])
    calls = []
    async def fake_invoke(prompt, model, timeout):
        from tools.report_studio.business_question import BusinessQuestion
        if model is BusinessQuestion: return business_question
        calls.append(model)
        if model is Report:
            return report
        return module.Corrections(patches=[{'path': '/sections/0/visuals/0/rows/0/cells/1/value', 'text': '-3'}])
    monkeypatch.setattr(module, 'invoke', fake_invoke)
    result = await module.ai_report(rich['content'], '汽车样本：报告检验')
    validate_evidence(result, rich['content'])
    assert calls == [Report, module.Corrections]


@pytest.mark.anyio
async def test_generator_does_not_accept_bad_repair(rich, monkeypatch, business_question):
    import tools.report_studio.generator as module
    from fastapi import HTTPException
    rich['report']['sections'][0]['visuals'][0]['rows'][0]['cells'][1]['value'] = '3'
    report = Report.model_validate(rich['report'])
    async def fake_invoke(prompt, model, timeout):
        from tools.report_studio.business_question import BusinessQuestion
        if model is BusinessQuestion: return business_question
        return report if model is Report else module.Corrections(patches=[])
    monkeypatch.setattr(module, 'invoke', fake_invoke)
    with pytest.raises(HTTPException) as error:
        await module.ai_report(rich['content'], '')
    assert error.value.status_code == 422


def test_missing_direct_source_url_is_not_fabricated(rich):
    rich['report']['sources'][0]['url'] = ''
    validate_evidence(Report.model_validate(rich['report']), rich['content'])
    html = export_html(ExportInput.model_validate(rich))
    assert '原材料未附直链' in html


def test_date_spelling_equivalence_and_precision():
    from tools.report_studio.evidence import period_in_quote
    assert period_in_quote('2026H2', '建议2026 下半年开始')
    assert period_in_quote('2027-02', '计划2027年2月试点')
    assert period_in_quote('2027Q4', '2027年第四季度验收')
    assert not period_in_quote('2027H1', '2027 年上线系统')
    assert not period_in_quote('2027-02', '2027年上线系统')


def test_year_cannot_be_invented_as_half_year(rich):
    rich['content'] += '\n建议2027年验收。'
    chart = rich['report']['sections'][0]['visuals'][2]
    chart['periods'] = ['2026-10', '2027H1', '2027H2']
    chart['milestones'][1].update(period='2027H1', end_period='2027H2', quote='建议2027年验收。')
    from tools.report_studio.evidence import EvidenceIssues
    with pytest.raises(EvidenceIssues, match='时间精度'):
        validate_evidence(Report.model_validate(rich['report']), rich['content'])


@pytest.fixture
def spatial(rich):
    rich['content'] += '\n甲接管2.77次，评分7.57分；乙接管5.86次，评分4.79分。\n俄罗斯海外占比32%，巴西工厂年产能5万辆。'
    base = {'title': '独立测试样本', 'source_ids': ['S01'], 'note': '非业务数据', 'width': 'full'}
    rich['report']['sections'][0]['visuals'] = [
        {**base, 'kind': 'scatter', 'x_label': '接管', 'x_unit': '次', 'y_label': '评分', 'y_unit': '分', 'points': [
            {'label': '甲', 'x': 2.77, 'y': 7.57, 'quote': '甲接管2.77次，评分7.57分', 'source_ids': ['S01'], 'emphasis': False},
            {'label': '乙', 'x': 5.86, 'y': 4.79, 'quote': '乙接管5.86次，评分4.79分', 'source_ids': ['S01'], 'emphasis': True}]},
        {**base, 'kind': 'worldmap', 'places': [
            {'country': 'RUS', 'label': '俄罗斯', 'value': '海外占比32%', 'quote': '俄罗斯海外占比32%', 'source_ids': ['S01']},
            {'country': 'BRA', 'label': '巴西', 'value': '工厂年产能5万辆', 'quote': '巴西工厂年产能5万辆', 'source_ids': ['S01']}]}]
    return rich


def test_spatial_visuals_export_offline(spatial):
    html = export_html(ExportInput.model_validate(spatial))
    assert 'window.ReportGeography=' in html
    assert '<script src=' not in html
    assert 'market-node' in html


@pytest.mark.parametrize('change,message', [('x', '数字'), ('y', '数字'), ('map_value', '数字'), ('wrong_country', '国家'), ('repeat_country', '一次'), ('source', '来源编号')])
def test_spatial_visuals_reject_wrong_data(spatial, change, message):
    scatter, worldmap = spatial['report']['sections'][0]['visuals']
    if change in {'x', 'y'}: scatter['points'][0][change] = 999
    elif change == 'map_value': worldmap['places'][0]['value'] = '海外占比999%'
    elif change == 'wrong_country': worldmap['places'][0]['country'] = 'THA'
    elif change == 'repeat_country': worldmap['places'][1]['country'] = 'RUS'
    elif change == 'source': scatter['points'][0]['source_ids'] = ['S404']
    with pytest.raises(ValueError, match=message):
        validate_evidence(Report.model_validate(spatial['report']), spatial['content'])


def test_matrix_direction_requires_explanation(rich):
    rich['report']['sections'][0]['visuals'][0]['columns'][1]['direction'] = 'higher'
    with pytest.raises(ValueError, match='可比口径'):
        validate_evidence(Report.model_validate(rich['report']), rich['content'])
