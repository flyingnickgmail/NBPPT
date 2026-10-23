import copy
import pytest
from tools.report_studio.app import ROOT, export_html
from tools.report_studio.models import ExportInput
from tools.report_studio.editorial_models import EditorialCover
from tools.report_studio.editorial import evidence_catalog, validate_editorial


@pytest.fixture
def data():
    return ExportInput.model_validate_json((ROOT/'sample.json').read_text())


def cover_for(report):
    keys=list(evidence_catalog(report))
    return EditorialCover(layout='contrast', question='规模与效率是否同步？',
        selection_reason='采用两个来源观察的并列对照，不表示因果关系，也不绘制额外变化。',
        items=[{'ref':k,'caption':'原始观察'} for k in keys[:2]],
        takeaway='需要结合期间和定义阅读。', boundary='不同指标不相减，不推导转化率。')


def test_cover_references_preserve_fact_and_quote(data):
    data.report.editorial=cover_for(data.report)
    before=copy.deepcopy(data.report.model_dump())
    validate_editorial(data.report)
    html=export_html(data)
    assert 'ReportCoverFacts=' in html
    assert 'ReportChartMotion' in html
    assert data.report.model_dump()==before
    for item in data.report.editorial.items:
        assert evidence_catalog(data.report)[item.ref]['quote'] in data.content


def test_cover_rejects_missing_and_duplicate_references(data):
    data.report.editorial=cover_for(data.report)
    data.report.editorial.items[1].ref=data.report.editorial.items[0].ref
    with pytest.raises(ValueError): validate_editorial(data.report)
    data.report.editorial.items[1].ref='missing'
    with pytest.raises(ValueError): export_html(data)


def test_cover_has_no_executable_geometry_or_values(data):
    cover=cover_for(data.report).model_dump()
    cover['items'][0]['value']='999999'
    with pytest.raises(ValueError): EditorialCover.model_validate(cover)


def test_cover_text_cannot_add_new_numbers(data):
    data.report.editorial=cover_for(data.report)
    data.report.editorial.takeaway='收益增加9999999.987%。'
    with pytest.raises(ValueError): validate_editorial(data.report)


@pytest.mark.anyio
async def test_model_design_preserves_body_sources_and_numbers(data,monkeypatch):
    import tools.report_studio.generator as module
    before=data.report.model_dump()
    async def fake_invoke(prompt,model,timeout):
        assert 'facts' in prompt
        return cover_for(data.report)
    monkeypatch.setattr(module,'invoke',fake_invoke)
    designed=await module.design_editorial(data.report,data.content)
    assert designed.editorial
    assert designed.spatial is None and designed.story is None
    for key in ('metrics','sections','sources','title','summary'):
        assert designed.model_dump()[key]==before[key]
