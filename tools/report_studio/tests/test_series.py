import pytest

from tools.report_studio.app import ROOT, export_html
from tools.report_studio.evidence import EvidenceIssues, validate_evidence
from tools.report_studio.illustrations import illustration_asset
from tools.report_studio.models import ExportInput, MultiSeries


@pytest.fixture
def data():
    data = ExportInput.model_validate_json((ROOT / 'sample.json').read_text())
    data.content += '\n2024甲为2，2025甲为3；2024乙为4，2025乙未提供。'
    point = lambda label, value, quote: dict(label=label, value=value, quote=quote, source_ids=[])
    chart = MultiSeries(kind='multiseries', title='双序列', display='grouped_bar', unit='%',
                        categories=['2024', '2025'], basis='同一统计定义、同一年度的观察值', observation='observed', series=[
        dict(label='甲', definition='甲定义', points=[point('2024', 2, '2024甲为2'), point('2025', 3, '2025甲为3')]),
        dict(label='乙', definition='乙定义', points=[point('2024', 4, '2024乙为4'), None])])
    data.report.sections[0].visuals = [chart]
    return data


def test_null_stays_missing_and_quotes_checked_per_point(data):
    validate_evidence(data.report, data.content)
    assert data.report.sections[0].visuals[0].series[1].points[1] is None
    data.report.sections[0].visuals[0].series[0].points[1].value = 9
    with pytest.raises(EvidenceIssues) as exc:
        validate_evidence(data.report, data.content)
    assert exc.value.issues[0]['path'].endswith('/series/0/points/1')


@pytest.mark.parametrize('mutation', ['length', 'label', 'duplicate', 'line_two', 'empty'])
def test_reject_ambiguous_alignment(data, mutation):
    v = data.report.sections[0].visuals[0]
    if mutation == 'length':
        v.series[0].points.pop()
    elif mutation == 'label':
        v.series[0].points[0].label = '2023'
    elif mutation == 'duplicate':
        v.categories[1] = v.categories[0]
    elif mutation == 'empty':
        v.series[0].points = [None, None]
    else:
        v.display = 'line'
    with pytest.raises(ValueError):
        validate_evidence(data.report, data.content)


def test_offline_export_embeds_only_selected_art_and_legacy_is_unchanged(data):
    no_art = export_html(data)
    assert 'window.ReportIllustration=null;' in no_art
    assert 'window.ReportSeries' in no_art
    data.report.illustration = 'economy'
    html = export_html(data)
    assert html.count('data:image/png;base64,') == 1
    assert 'https://images' not in html
    assert illustration_asset('../../secrets') is None
    assert illustration_asset('technology')['alt'] != illustration_asset('ecology')['alt']
    raw = data.model_dump()
    raw['report'].pop('illustration')
    assert ExportInput.model_validate(raw).report.illustration == 'none'


def test_line_accepts_real_ordered_dates_but_rejects_mixed_periods(data):
    v = data.report.sections[0].visuals[0]
    v.display = 'line'
    v.categories = ['2023', '2024', '2025']
    for s in v.series:
        quote = s.points[0].quote.replace('2024', '2023')
        data.content += '\n' + quote
        s.points.insert(0, s.points[0].model_copy(update={'label': '2023', 'quote': quote}))
    validate_evidence(data.report, data.content)
    v.categories = ['2023', '2025', '2024']
    with pytest.raises(ValueError, match='升序真实年月'):
        validate_evidence(data.report, data.content)
    v.categories = ['2023', '2024年平均', '2025峰值']
    with pytest.raises(ValueError, match='升序真实年月'):
        validate_evidence(data.report, data.content)
