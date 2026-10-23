import pytest

from tools.report_studio.app import ROOT, export_html
from tools.report_studio.evidence import validate_evidence, EvidenceIssues
from tools.report_studio.models import ExportInput, NarrativeScene, StoryDesign, Source, SceneAssembly, SceneAction


@pytest.fixture
def data():
    data = ExportInput.model_validate_json((ROOT / 'sample.json').read_text())
    quote = '阅读使用扩大，保存条件仍需改善。'
    data.content += '\n' + quote
    data.report.sources = [Source(id='S01', label='输入材料', url='')]
    refs = ['S01']
    part = dict(kind='path', x=0, y=0, width=0, height=0, path='M20 20 L120 20 L80 120 Z', fill='teal', stroke='ink')
    data.report.story = NarrativeScene(title='档案与阅读', concept='以书本、书架与阅读桌表达材料中的保存与利用关系。',
        objects=[dict(id=key, label=label, description='概念书架', x=x, y=140,
                      parts=[part.copy() for _ in range(3)], fact='保存条件仍需改善。', quote=quote, source_ids=refs)
                 for key, label, x in [('books', '档案', 200), ('shelves', '书架', 500), ('reading', '阅览', 800)]],
        links=[dict(id='access', origin='books', destination='reading', label='阅读使用扩大', relation='context', quote=quote, source_ids=refs)],
        beats=[dict(section_index=i, title='保存与使用', caption='阅读使用扩大，保存条件仍需改善。', focus=['books', 'reading'],
                    links=['access'], composition='unfold', quote=quote, source_ids=refs) for i in range(len(data.report.sections))])
    return data


def test_offline_scene_is_data_and_preserves_legacy(data):
    validate_evidence(data.report, data.content)
    data.report.illustration = 'economy'
    html = export_html(data)
    assert 'window.ReportStory' in html
    assert 'data:image/png;base64,' not in html
    raw = data.model_dump()
    raw['report'].pop('story')
    assert ExportInput.model_validate(raw).report.story is None


def test_unlinked_material_keeps_exact_quotes_without_fabricated_sources(data):
    data.report.sources = []
    for item in [*data.report.story.objects, *data.report.story.links, *data.report.story.beats]:
        item.source_ids = []
    data = ExportInput.model_validate(data.model_dump())
    validate_evidence(data.report, data.content)
    data.report.story.objects[0].quote = '虚构原句'
    with pytest.raises(EvidenceIssues):
        validate_evidence(data.report, data.content)


@pytest.mark.parametrize('fault', ['duplicate', 'missing_chapter', 'missing_object', 'inactive_endpoint', 'overlap', 'script', 'outside', 'unknown_source'])
def test_scene_rejects_structural_and_rendering_failures(data, fault):
    scene = data.report.story
    if fault == 'duplicate': scene.objects[1].id = scene.objects[0].id
    elif fault == 'missing_chapter': scene.beats.pop()
    elif fault == 'missing_object': scene.links[0].destination = 'missing'
    elif fault == 'inactive_endpoint': scene.beats[0].focus = ['books']
    elif fault == 'overlap': scene.objects[1].x = scene.objects[0].x
    elif fault == 'script': scene.objects[0].parts[0].path = '<script>alert(1)</script>'
    elif fault == 'outside': scene.objects[0].parts[0].path = 'M900 0 L1 2 Z'
    elif fault == 'unknown_source': scene.objects[0].source_ids = ['S999']
    with pytest.raises(ValueError): validate_evidence(data.report, data.content)


@pytest.mark.parametrize('fault', ['quote', 'number', 'headline'])
def test_scene_observations_are_grounded(data, fault):
    scene = data.report.story
    if fault == 'quote': scene.objects[0].quote = '不是材料中的引句'
    elif fault == 'number': scene.objects[0].fact = '阅读增加9999%'
    else: scene.beats[0].title = '阅读增加9999%'
    with pytest.raises(EvidenceIssues): validate_evidence(data.report, data.content)


@pytest.mark.anyio
async def test_scene_generation_repairs_once_and_keeps_body(semantic, monkeypatch):
    import tools.report_studio.generator as module
    data = semantic
    source = data.report.model_copy(deep=True)
    source.story = None
    before = source.model_dump()
    bad = data.report.story.model_copy(deep=True)
    bad.beats[0].caption = '错误9999%'
    calls = []
    async def invoke(prompt, model, timeout):
        calls.append(prompt)
        if model is StoryDesign:
            return StoryDesign(story=bad)
        assert model is module.Corrections
        return module.Corrections(patches=[dict(path='/story/beats/0/caption', text=data.report.story.beats[0].caption)])
    monkeypatch.setattr(module, 'invoke', invoke)
    result = await module.design_story(source, data.content)
    assert len(calls) == 2 and '只能改错误对象' in calls[1]
    assert source.model_dump() == before
    assert result.story.objects == data.report.story.objects
    result.story = None
    assert result.model_dump() == before


@pytest.fixture
def semantic(data):
    data = data.model_copy(deep=True)
    scene = data.report.story
    scene.edition = 'semantic'
    for obj in scene.objects:
        obj.rationale = '以书页与保护夹层区分可读性和保存条件，不表示档案数量。'
        obj.parts = [obj.parts[0].model_copy(update={'group': 'pages' if i < 4 else 'cover'}) for i in range(8)]
        obj.assemblies = [SceneAssembly(id=g, label=g, dx=12, dy=-8, angle=4) for g in ['pages', 'cover']]
    for beat in scene.beats:
        beat.actions = [SceneAction(object_id='books', group='cover', effect='reveal', reason='揭开保护层查看内部结构。')]
    return ExportInput.model_validate(data.model_dump())


def test_semantic_design_and_legacy_can_both_export(semantic, data):
    validate_evidence(semantic.report, semantic.content)
    assert '精细线稿' in export_html(semantic)
    validate_evidence(data.report, data.content)


@pytest.mark.parametrize('fault', ['empty_actions', 'outside_focus', 'unknown_group', 'duplicate_action', 'empty_rationale', 'interleaved_groups', 'unknown_assembly', 'motionless_reveal'])
def test_semantic_motion_rejects_undefined_or_misleading_structure(semantic, fault):
    scene = semantic.report.story
    if fault == 'empty_actions': scene.beats[0].actions = []
    elif fault == 'outside_focus': scene.beats[0].actions[0].object_id = 'shelves'
    elif fault == 'unknown_group': scene.beats[0].actions[0].group = 'pointer'
    elif fault == 'duplicate_action': scene.beats[0].actions *= 2
    elif fault == 'empty_rationale': scene.objects[0].rationale = ''
    elif fault == 'interleaved_groups': scene.objects[0].parts[2].group = 'cover'
    elif fault == 'unknown_assembly': scene.objects[0].assemblies[0].id = 'missing'
    elif fault == 'motionless_reveal':
        group = scene.objects[0].assemblies[1]
        group.dx = group.dy = group.angle = 0
    with pytest.raises(ValueError): validate_evidence(semantic.report, semantic.content)


def test_motion_ranges_are_bounded(semantic):
    raw = semantic.model_dump()
    raw['report']['story']['objects'][0]['assemblies'][0]['angle'] = 180
    with pytest.raises(ValueError): ExportInput.model_validate(raw)
