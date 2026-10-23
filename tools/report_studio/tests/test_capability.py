import copy
import json
from argparse import Namespace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tools.report_studio.app import ROOT, app
from tools.report_studio.cli import run, write_artifacts
from tools.report_studio.generator import Refinement, apply_refinement
from tools.report_studio.models import ExportInput, Report
from tools.report_studio.quality import review_report


@pytest.fixture
def data():
    return ExportInput.model_validate_json((ROOT / 'sample.json').read_text())


def test_body_numbers_are_checked_separately(data):
    data.report.sections[0].paragraphs = ['材料未提供的999999.123%。']
    result = review_report(data.report, data.content)
    assert any(x['code'] == 'body_numbers' for x in result['findings'])


def test_short_material_is_not_forced_to_add_figures(data):
    result = review_report(data.report, data.content)
    assert not any(x['code'] in {'composition', 'thin_analysis'} for x in result['findings'])


def test_prose_decline_and_numeric_sign_are_equivalent(data):
    data.content += '\n内销同比-22.53%。'
    data.report.sections[0].paragraphs = ['内销下降22.53%。']
    assert not any(x['code'] == 'body_numbers' for x in review_report(data.report, data.content)['findings'])
    data.report.sections[0].paragraphs = ['内销增长22.53%。']
    assert any(x['code'] == 'body_numbers' for x in review_report(data.report, data.content)['findings'])


def test_loss_ratio_is_not_negated_as_profit():
    from tools.report_studio.evidence import narrative_number_tokens
    from decimal import Decimal
    assert narrative_number_tokens('亏损面55.7%，亏损8.6亿元。') == [Decimal('55.7'), Decimal('-8.6')]


def test_refinement_preserves_existing_report_units(data):
    before = copy.deepcopy(data.report.model_dump())
    path = '/sections/0/paragraphs/0'
    replacement = '这段为局部复审后的说明，仍需核实因果。'
    result = apply_refinement(data.report, Refinement(patches=[{'path': path, 'text': replacement}], additions=[], notes=[]), data.content)
    assert data.report.model_dump() == before
    assert result.sources == data.report.sources
    assert result.metrics == data.report.metrics
    assert result.sections[0].chart == data.report.sections[0].chart
    assert result.sections[1:] == data.report.sections[1:]


@pytest.mark.parametrize('path,text', [('/title', '改标题'), ('/sources/0/url', 'https://evil.example'),
                                      ('/sections/99/paragraphs/0', '越界'), ('/sections/0/paragraphs/0', '新增999999.123元')])
def test_refinement_rejects_scope_expansion(data, path, text):
    with pytest.raises(ValueError):
        apply_refinement(data.report, Refinement(patches=[{'path': path, 'text': text}], additions=[], notes=[]), data.content)


@pytest.mark.anyio
async def test_long_generation_uses_editorial_review(data, monkeypatch, business_question):
    import tools.report_studio.generator as module
    calls = []
    async def fake_invoke(prompt, model, timeout):
        from tools.report_studio.business_question import BusinessQuestion
        if model is BusinessQuestion: return business_question
        calls.append(model)
        return data.report if model is Report else Refinement(patches=[], additions=[], notes=['材料不足，不添加重复图。'])
    async def fake_design(report, content, deadline):
        calls.append('editorial')
        return report
    monkeypatch.setattr(module, 'invoke', fake_invoke)
    monkeypatch.setattr(module, 'design_editorial', fake_design)
    result = await module.ai_report(data.content * 50, '')
    assert result == data.report
    assert calls == [Report, Refinement, 'editorial']


def test_quality_api_is_readonly_and_validates_evidence(data):
    with TestClient(app) as client:
        assert client.post('/api/review', json=data.model_dump()).status_code == 200
        data.report.metrics[0].value = '999999.123'
        assert client.post('/api/review', json=data.model_dump()).status_code == 422


@pytest.mark.anyio
async def test_cli_render_and_strict_check_preserve_input(data, tmp_path):
    original = tmp_path / 'input.json'
    original.write_text(data.model_dump_json())
    destination = tmp_path / 'output'
    assert await run(Namespace(command='render', input=original, output=destination)) == 0
    assert (destination / 'report.html').exists()
    assert json.loads((destination / 'quality.json').read_text())['version'] == 'report-quality.v1'
    assert ExportInput.model_validate_json((destination / 'report.json').read_text()) == data
    with pytest.raises(FileExistsError):
        write_artifacts(data, destination)
    data.report.sections[0].paragraphs = ['新增999999.123元。']
    original.write_text(data.model_dump_json())
    assert await run(Namespace(command='check', input=original, strict=True)) == 3


def test_english_decline_matches_chinese_without_negating_levels():
    from tools.report_studio.evidence import narrative_number_tokens
    from decimal import Decimal
    assert narrative_number_tokens('GDP edged down at an annual rate of 0.2 percent.') == [Decimal('-.2')]
    assert narrative_number_tokens('a 0.5 percent decline recorded a year ago') == [Decimal('-.5')]
    assert narrative_number_tokens('Inflation declined to 2.1 percent, down from 2.6.') == [Decimal('2.1'), Decimal('2.6')]
    assert narrative_number_tokens('increased 0.2 percent') == [Decimal('.2')]


def test_summary_numbers_and_single_value_charts_are_flagged(data):
    data.report.summary = '未经提供的99999.123美元。'
    from tools.report_studio.models import Chart, Point
    data.report.sections[0].chart = Chart(kind='bar',title='单值',unit='%',steps=[],points=[Point(label='读数',value=1,quote='读数1')])
    data.content += '\n读数1'
    codes = {f['code'] for f in review_report(data.report,data.content)['findings']}
    assert {'headline_numbers','single_point_chart'} <= codes


def test_comparison_checks_each_endpoint_and_source(data):
    from tools.report_studio.models import Comparison
    from tools.report_studio.evidence import validate_evidence, EvidenceIssues
    data.content += '\n甲旧值2，新值3；乙旧值4，新值5。'
    point = lambda v,q: {'label':'时期','value':v,'quote':q,'source_ids':[]}
    visual = Comparison(kind='comparison',title='同一时期前后观察',unit='%',before_label='之前',after_label='之后',rows=[
        {'label':'甲','before':point(2,'甲旧值2'),'after':point(3,'新值3')},
        {'label':'乙','before':point(4,'乙旧值4'),'after':point(5,'新值5')}])
    data.report.sections[0].visuals=[visual]
    validate_evidence(data.report,data.content)
    visual.rows[1].after.value=999
    with pytest.raises(EvidenceIssues) as exc:
        validate_evidence(data.report,data.content)
    assert exc.value.issues[0]['path'].endswith('/rows/1/after')


def test_review_replaces_only_selected_figure(data):
    from tools.report_studio.models import Chart
    original=Chart(kind='flow',title='旧结构',unit='',steps=['原关系'],points=[])
    data.report.sections[0].visuals=[original]
    revision=Refinement(patches=[],additions=[],notes=[],replacements=[{'section_index':0,'visual_index':0,
        'visual':{'kind':'flow','title':'改正结构','unit':'','steps':['并行关系'],'points':[]}}])
    result=apply_refinement(data.report,revision,data.content)
    assert result.sections[0].visuals[0].title=='改正结构'
    assert data.report.sections[0].visuals[0].title=='旧结构'
    assert result.sections[0].paragraphs==data.report.sections[0].paragraphs
    revision.replacements[0].visual_index=5
    with pytest.raises(ValueError):
        apply_refinement(data.report,revision,data.content)


def test_english_currency_decline_is_a_magnitude_not_a_level():
    from tools.report_studio.evidence import narrative_number_tokens
    from decimal import Decimal
    assert narrative_number_tokens('holdings have declined $176 billion to $6.7 trillion.') == [Decimal('-176'),Decimal('6.7')]
    assert narrative_number_tokens('holdings declined to $176 billion.') == [Decimal('176')]


def test_chart_counts_do_not_force_composition_findings(data):
    result=review_report(data.report,data.content*50)
    assert not any(f['code']=='composition' for f in result['findings'])
