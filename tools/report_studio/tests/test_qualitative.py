import pytest
from pydantic import ValidationError
from tools.report_studio.app import ROOT, export_html
from tools.report_studio.models import ExportInput, Contrast, Membership, EvidenceStrip
from tools.report_studio.evidence import validate_evidence
from tools.report_studio.chart_design import recommend_design
from tools.report_studio.generator import Refinement, apply_refinement


@pytest.fixture
def data():
    data = ExportInput.model_validate_json((ROOT / 'sample.json').read_text())
    data.content += '\n身份持续存在，任务凭据短期有效。标准组合尚待验证。'
    data.report.editorial = None
    return data


def statement(label, nature='recorded'):
    return dict(label=label, detail=label, nature=nature,
                quote='身份持续存在，任务凭据短期有效。')


def contrast():
    return Contrast(kind='contrast', title='身份与任务凭据', left_label='身份', right_label='任务凭据',
                    rows=[dict(label=label, left=statement('持续存在'), right=statement('短期有效'))
                          for label in ['有效范围', '生命周期']])


def test_qualitative_requires_evidence_and_has_no_fake_score_axis(data):
    visual = contrast()
    data.report.sections[0].visuals = [visual]
    validate_evidence(data.report, data.content)
    assert recommend_design(data.report)[0]['recipe'] == 'qualitative_pair'
    assert 'window.ReportQualitative=' in export_html(data)
    with pytest.raises(ValidationError):
        Contrast.model_validate({**visual.model_dump(), 'score': 9})
    visual.rows[0].right.quote = '编造引文'
    with pytest.raises(ValueError):
        validate_evidence(data.report, data.content)


def test_membership_rejects_duplicate_and_out_of_range_sets(data):
    visual = Membership(kind='membership',title='职责归属',sets=['身份','任务'],items=[
        dict(label=label,detail=label,relations=[dict(set_index=0,relation='included',quote='身份持续存在，任务凭据短期有效。')])
        for label in ['身份锚','凭据']])
    data.report.sections[0].visuals=[visual]
    validate_evidence(data.report,data.content)
    visual.items[0].relations.append(visual.items[0].relations[0].model_copy())
    with pytest.raises(ValueError,match='重复'):validate_evidence(data.report,data.content)
    visual.items[0].relations.pop();visual.items[0].relations[0].set_index=5
    with pytest.raises(ValueError,match='不存在'):validate_evidence(data.report,data.content)


def test_evidence_facets_need_actual_different_natures(data):
    visual=EvidenceStrip(kind='evidence_strip',title='证据边界',items=[statement('持续存在') for _ in range(3)])
    data.report.sections[0].visuals=[visual]
    with pytest.raises(ValueError,match='两种'):validate_evidence(data.report,data.content)
    visual.items[2]=visual.items[2].model_copy(update=dict(label='标准组合',detail='尚待验证',nature='unresolved',quote='标准组合尚待验证。'))
    validate_evidence(data.report,data.content)


def test_replacing_figure_clears_obsolete_cover_and_reading(data):
    revision=Refinement(patches=[], additions=[], replacements=[dict(section_index=0,visual_index=0,visual=contrast())], notes=[])
    data.report.sections[0].visuals=[contrast()]
    result=apply_refinement(data.report,revision,data.content)
    assert result.editorial is None and result.sections[0].reading is None
    assert result.sources == data.report.sources and result.metrics == data.report.metrics
