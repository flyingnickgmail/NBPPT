import pytest
from tools.report_studio.models import QualifiedDot, QualifiedPoint, ExportInput
from tools.report_studio.app import ROOT, export_html
from tools.report_studio.qualified import qualification
from tools.report_studio.evidence import validate_evidence, EvidenceIssues
from tools.report_studio.editorial import evidence_catalog


def point(value=120, relation='gt', phrase='more than 120%'):
    return QualifiedPoint(label='出口',value=value,relation=relation,qualifier_quote=phrase,quote=phrase,source_ids=[])


@pytest.mark.parametrize('value,relation,phrase',[(120,'gt','more than 120%'),(20,'approx','nearly 20%'),(-20,'approx','down nearly 20%'),(-20,'lt','下降超过20%'),(10,'gte','至少10'),(10,'lte','no more than 10'),(75,'exact','75%')])
def test_qualifier_semantics(value,relation,phrase):
    assert qualification(point(value,relation,phrase)) == relation


@pytest.fixture
def data():
    d=ExportInput.model_validate_json((ROOT/'sample.json').read_text())
    d.report.editorial=None
    d.content+='\nmore than 120%\n75%'
    d.report.sections[0].visuals=[QualifiedDot(kind='qualified_dot',title='增长不同步',unit='%',basis='同一期间的同比，各指标基期不同，不计算转化率。',points=[point(),point(75,'exact','75%').model_copy(update={'label':'海外销售'})])]
    return d


def test_end_to_end_provenance_and_export(data):
    validate_evidence(data.report,data.content)
    assert evidence_catalog(data.report)['sections/0/visuals/0/points/0']['value']=='>120%'
    html=export_html(data)
    assert 'window.ReportQualified' in html and '.qualified-row' in html


@pytest.mark.parametrize('mutation',['exact','inverse','unquoted','two_numbers','duplicate','invented'])
def test_reject_false_precision_and_false_bounds(data,mutation):
    v=data.report.sections[0].visuals[0];p=v.points[0]
    if mutation=='exact':p.relation='exact'
    elif mutation=='inverse':p.relation='lt'
    elif mutation=='unquoted':p.qualifier_quote='at least 120%'
    elif mutation=='two_numbers':p.quote=p.qualifier_quote='75% and more than 120%';data.content+='\n'+p.quote
    elif mutation=='duplicate':v.points[1].label=p.label
    elif mutation=='invented':p.value=130
    with pytest.raises(ValueError):validate_evidence(data.report,data.content)


def test_cannot_hide_qualifier_by_shortening_quote(data):
    p=data.report.sections[0].visuals[0].points[0]
    p.qualifier_quote='120%';p.relation='exact'
    with pytest.raises(ValueError,match='遗漏'):validate_evidence(data.report,data.content)


def test_decline_can_follow_short_qualifier_in_same_clause():
    p=point(-20,'approx','almost 20%')
    p.quote='the almost 20% drop in electric car sales in China'
    assert qualification(p)=='approx'
    p.quote='sales rose almost 20%; exports dropped'
    with pytest.raises(ValueError):qualification(p)
