from types import SimpleNamespace
import pytest
from tools.report_studio.reference_poster import ReferenceDesign,validate_design,geometry,select_and_render


def plan():
    return SimpleNamespace(fact_refs=[],visual_labels=['等待任务','处理能力匹配','超出处理能力','保持排班','评估调配'],reader_design=SimpleNamespace(visual_grammar='condition_contrast',chart_caption='分析情景，不代表实测数量。',visual_proof=[object()]))


def design():
    return ReferenceDesign(applicable=True,reason='原方案比较等待任务与适用处理能力的匹配关系。',object_label='等待任务',cases=[{'condition':'处理能力匹配','outcome':'保持排班','relation':'within'},{'condition':'超出处理能力','outcome':'评估调配','relation':'exceeds'}])


def test_within_and_overflow_are_geometrically_true():
    inside=geometry('within');outside=geometry('exceeds')
    assert inside['reference_left']<inside['object_left']<inside['object_right']<inside['reference_right']
    assert inside['overflow_left'] is None
    assert outside['object_left']==inside['object_left']
    assert outside['object_left']>outside['reference_left']
    assert outside['overflow_left']==outside['reference_right']<outside['object_right']
    assert not inside['quantitative'] and not outside['quantitative']
    with pytest.raises(ValueError):geometry('unknown')


def test_reference_renderer_rejects_invented_labels_or_measured_facts():
    p=plan();s=design();validate_design(s,p)
    s.cases[0].outcome='库存已经减少'
    with pytest.raises(ValueError,match='批准'):validate_design(s,p)
    p.fact_refs=['metrics/0']
    with pytest.raises(ValueError,match='定量事实'):validate_design(design(),p)


@pytest.mark.anyio
async def test_unsupported_grammar_never_calls_reference_model(tmp_path):
    p=plan();p.reader_design.visual_grammar='scope_map'
    async def invoke(*args):raise AssertionError('交集图不可硬套参照对照')
    assert await select_and_render(p,None,tmp_path,invoke) is None


@pytest.mark.anyio
async def test_editorial_choice_is_not_overridden_by_reference_geometry(tmp_path):
    p=plan();p.panels=[object(),object()]
    p.presentation=SimpleNamespace(rendering='editorial_illustration')
    async def invoke(*args):raise AssertionError('已选择编辑插画，不得退回两根横条')
    assert await select_and_render(p,None,tmp_path,invoke) is None
