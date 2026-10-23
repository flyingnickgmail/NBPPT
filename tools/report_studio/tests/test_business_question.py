import pytest
from pathlib import Path
from tools.report_studio.business_question import narrative_fields, reframe_report, frame_question, BusinessQuestion
from tools.report_studio.models import ExportInput
from tools.report_studio import generator as g
from tools.report_studio import overview_generation as overview


def sample():
    return ExportInput.model_validate_json((Path(g.ROOT)/'sample.json').read_text())


def test_prose_scope_does_not_unlock_factual_data():
    fields=narrative_fields(sample().report)
    assert '/title' in fields and '/sections/0/paragraphs/0' in fields
    assert not any('/metrics/' in p or '/sources/' in p or p.endswith('/quote') or p.endswith('/value') for p in fields)


@pytest.mark.anyio
async def test_reframing_rejects_fact_mutation(monkeypatch,business_question):
    data=sample(); original=data.model_dump_json()
    async def invoke(prompt,model,timeout):
        if model is BusinessQuestion:return business_question
        return g.Corrections(patches=[{'path':'/metrics/0/value','text':'999'}])
    monkeypatch.setattr(g,'invoke',invoke)
    with pytest.raises(ValueError,match='超出叙事字段'):
        await reframe_report(data.report,data.content,'纠正不成立的结论')
    assert data.model_dump_json()==original


@pytest.mark.anyio
async def test_old_design_cannot_skip_question_gate(tmp_path):
    data=sample()
    # A legacy design still parses, but resume may not bypass the new gate.
    from tools.report_studio.tests.test_overview_generation import plan_for
    plan=plan_for(data);plan.question_review=None
    (tmp_path/'resume-plan.json').write_text(plan.model_dump_json())
    async def progress(*args):pass
    with pytest.raises(ValueError,match='旧设计缺少业务审题'):
        await overview.create_overview(data,tmp_path,progress)


@pytest.mark.anyio
async def test_frame_receives_normal_baseline_and_alternatives(business_question):
    async def invoke(prompt,model,timeout):
        assert '正常业务基线' in prompt and '替代解释' in prompt
        assert '签约与收入' in prompt and '不能预设恶化' in prompt
        assert model is BusinessQuestion
        return business_question
    result=await frame_question('材料没有提供实际库存和库龄。','出口快于销售所以库存恶化',invoke)
    assert result.evidence_status=='open_question'

@pytest.mark.anyio
async def test_reframing_updates_root_and_nested_prose_preserving_facts(monkeypatch,business_question,tmp_path):
    data=sample(); original=data.report.model_dump()
    async def invoke(prompt,model,timeout):
        if model is BusinessQuestion:return business_question
        return g.Corrections(patches=[{'path':'/title','text':'经营表现：先核对基线，再判断异常'}, {'path':'/sections/0/paragraphs/0','text':'现有材料不足以确认经营异常，需要进一步核对可比基线。'}])
    monkeypatch.setattr(g,'invoke',invoke)
    result=await reframe_report(data.report,data.content,'审题',tmp_path)
    assert result.title=='经营表现：先核对基线，再判断异常'
    assert result.metrics==data.report.metrics and result.sources==data.report.sources
    assert result.sections[0].visuals==data.report.sections[0].visuals
    assert data.report.model_dump()==original
    assert (tmp_path/'narrative-patches.json').exists()

@pytest.mark.anyio
async def test_invalid_framing_stops_before_report_generation(monkeypatch):
    from fastapi import HTTPException
    calls=[]
    async def invoke(prompt,model,timeout):
        calls.append(model)
        raise ValueError('invalid framing')
    monkeypatch.setattr(g,'invoke',invoke)
    with pytest.raises(HTTPException) as error:
        await g.ai_report('材料只有不同交易环节的数值。','经营问题')
    assert error.value.status_code==422
    assert calls==[BusinessQuestion]
