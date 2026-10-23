import pytest
from pydantic import ValidationError
from tools.report_studio.models import ExportInput, Scatter, ScatterAnalysis
from tools.report_studio.app import ROOT, export_html
from tools.report_studio.evidence import validate_evidence, EvidenceIssues


def test_scatter_contract_and_provenance():
    data = ExportInput.model_validate_json((ROOT / 'sample.json').read_text())
    quote = '甲销量下降4.5%，出口增长65.8%；乙销量增长11.1%，出口增长127.9%。'
    data.content += '\n' + quote
    chart = Scatter(kind='scatter', title='同期间增长对照', x_label='销量同比',
                    y_label='出口同比', x_unit='%', y_unit='%',
                    analysis=ScatterAnalysis(reference='zero'),
                    points=[dict(label='甲', x=-4.5, y=65.8, quote=quote),
                            dict(label='乙', x=11.1, y=127.9, quote=quote)])
    data.report.sections[0].visuals = [chart]
    validate_evidence(data.report, data.content)
    html = export_html(data)
    assert 'window.ReportScatter=' in html
    assert 'window.ReportScatter.render(c,{el,svgEl,show})' in html
    assert 'scatter-plot-scroll' in html
    chart.points[1].y = 128
    with pytest.raises(EvidenceIssues):
        validate_evidence(data.report, data.content)


def test_reference_cannot_be_arbitrary_score():
    with pytest.raises(ValidationError):
        ScatterAnalysis(reference='priority', threshold=5)
