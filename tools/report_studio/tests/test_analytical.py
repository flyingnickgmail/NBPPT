import pytest
from decimal import Decimal
from tools.report_studio.app import ROOT, export_html
from tools.report_studio.models import ExportInput, Waterfall, Mechanism, MechanismLink, ReadingGuide
from tools.report_studio.evidence import validate_evidence
from tools.report_studio.analytical import validate_reading


def test_adjacent_negative_accounting_amounts_preserve_signs():
    from tools.report_studio.evidence import number_tokens, narrative_number_tokens
    text='经营现金流 -16,950,019.26-41,282,675.39 不适用'
    assert number_tokens(text)==[Decimal('-16950019.26'),Decimal('-41282675.39')]
    assert narrative_number_tokens(text)==number_tokens(text)
    assert number_tokens('10-20；1,000.00-2,000.00')==[Decimal('10'),Decimal('20'),Decimal('1000'),Decimal('2000')]


def test_translated_date_months_do_not_authorize_new_chart_measurements():
    from tools.report_studio.evidence import number_tokens, narrative_number_tokens
    assert Decimal(10) in narrative_number_tokens('October 28th at 1:00 P.M.')
    assert Decimal(6) in narrative_number_tokens('Jun. 2026')
    assert Decimal(5) not in narrative_number_tokens('May increase by 10 percent')
    assert Decimal(10) not in number_tokens('October 28th at 1:00 P.M.')


@pytest.fixture
def data():
    d=ExportInput.model_validate_json((ROOT/'sample.json').read_text())
    d.content+='\n初值10，贡献-3，终值7。研发完成后交付，交付上线后提供运维。'
    p=lambda label,value:dict(label=label,value=value,quote='初值10，贡献-3，终值7。')
    d.report.sections[0].visuals=[Waterfall(kind='waterfall',title='结果构成',unit='元',basis='同一期间同一统计口径',start=p('初值',10),changes=[p('贡献',-3)],end=p('终值',7))]
    return d


def test_signed_bridge_closes_without_residual(data):
    validate_evidence(data.report,data.content)
    html=export_html(data)
    assert 'window.ReportAnalytical=' in html and 'window.ReportReading=' in html
    data.report.sections[0].visuals[0].changes[0].value=3
    with pytest.raises(ValueError,match='不闭合'):
        validate_evidence(data.report,data.content)


def test_mechanism_rejects_fake_or_backward_links(data):
    node=lambda label,stage:dict(label=label,stage=stage,lane=0,status='observed',detail=label,quote='研发完成后交付，交付上线后提供运维。')
    graph=Mechanism(kind='mechanism',title='交付关系',lanes=['服务'],nodes=[node('研发',0),node('交付',1)],links=[dict(origin=0,to=1,label='完成后交付',quote='研发完成后交付，交付上线后提供运维。')])
    data.report.sections[0].visuals=[graph]
    validate_evidence(data.report,data.content)
    graph.links[0].origin=1;graph.links[0].to=0
    with pytest.raises(ValueError,match='更后的阶段'):
        validate_evidence(data.report,data.content)


def guide():
    return ReadingGuide(question='结果由何构成？',rationale='以桥图解释已有构成',steps=[dict(title='读起点',explanation='初值与终值保留各自依据。',visual_index=0,item_indices=[0],paragraph_index=0),dict(title='读贡献',explanation='贡献改变累计值。',visual_index=0,item_indices=[1],paragraph_index=0)])


def test_parallel_nodes_share_a_stage_without_becoming_a_sequence(data):
    node=lambda label,stage:dict(label=label,stage=stage,lane=0,status='proposal',detail=label,quote='研发完成后交付，交付上线后提供运维。')
    graph=Mechanism(kind='mechanism',title='并列能力',lanes=['服务'],nodes=[node('研发',0),node('交付',1),node('运维',1)],links=[MechanismLink(origin=0,to=1,label='支持交付',quote='研发完成后交付，交付上线后提供运维。')])
    data.report.sections[0].visuals=[graph]
    validate_evidence(data.report,data.content)
    graph.links.append(MechanismLink(origin=1,to=2,label='并列项不能连成先后',quote='研发完成后交付，交付上线后提供运维。'))
    with pytest.raises(ValueError,match='更后的阶段'):validate_evidence(data.report,data.content)


def test_reading_references_cannot_invent_data(data):
    data.report.sections[0].reading=guide()
    validate_reading(data.report,data.content)
    data.report.sections[0].reading.steps[0].item_indices=[99]
    with pytest.raises(ValueError,match='已有数据项'):
        validate_reading(data.report,data.content)


@pytest.mark.anyio
async def test_model_reading_preserves_final_facts(data,monkeypatch):
    import tools.report_studio.generator as g
    original=data.report.model_dump()
    async def invoke(prompt,model,timeout):
        assert model is g.ReadingPlan and 'item_counts' in prompt
        return g.ReadingPlan(sections=[dict(section_index=0,reading=guide())])
    monkeypatch.setattr(g,'invoke',invoke)
    result=await g.design_reading(data.report,data.content)
    assert result.sections[0].reading
    after=result.model_dump()
    for section in after['sections']: section['reading']=None
    assert after==original
