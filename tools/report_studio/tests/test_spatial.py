import copy
import pytest
from tools.report_studio.models import ExportInput
from tools.report_studio.spatial_models import SpatialDesign, SpatialScene
from tools.report_studio.app import ROOT, export_html
from tools.report_studio.evidence import validate_evidence, EvidenceIssues

@pytest.fixture
def spatial_data():
    data=ExportInput.model_validate_json((ROOT/'sample.json').read_text())
    quote='材料显示设备需求扩大，融资条件仍然偏紧。'
    data.content += '\n'+quote
    data.report.spatial=SpatialScene(
        title='设备与融资',concept='以日常实物解释研究主题，不编码数值。',
        groups=[dict(id=g,label=g,rationale='设备和融资各自呈现。',explode=[0,0,1],fact='设备需求扩大',quote=quote,source_ids=[]) for g in ['device','credit']],
        parts=[dict(group=g,shape='box',center=[i,0,1],size=[1,1,.2],rotation=[0,0,0],profile=[],material='metal',tone='silver',detail='none') for g in ['device','credit'] for i in range(6)],
        beats=[dict(section_index=i,title='需求扩大',caption='设备需求扩大，融资条件仍然偏紧。',focus=['device'],quote=quote,source_ids=[]) for i in range(len(data.report.sections))])
    return data

@pytest.mark.parametrize('fault',['unknown_group','unknown_focus','missing_beat','duplicate_group','bad_profile','degenerate_profile','unknown_source','quote'])
def test_reject_geometry_and_evidence_faults(spatial_data,fault):
    s=spatial_data.report.spatial
    if fault=='unknown_group': s.parts[0].group='missing'
    if fault=='unknown_focus': s.beats[0].focus=['missing']
    if fault=='missing_beat': s.beats.pop()
    if fault=='duplicate_group': s.groups[1].id=s.groups[0].id
    if fault=='bad_profile': s.parts[0].shape='prism';s.parts[0].profile=[[0,0],[1,0],[1,1],[.5,.2],[0,1]]
    if fault=='degenerate_profile': s.parts[0].shape='prism';s.parts[0].profile=[[0,0],[1,0],[.5,0]]
    if fault=='unknown_source': s.beats[0].source_ids=['S999']
    if fault=='quote': s.beats[0].quote='材料没有这句话'
    with pytest.raises(ValueError): validate_evidence(spatial_data.report,spatial_data.content)

def test_export_embeds_spatial_engine_and_design_no_external_art(spatial_data):
    html=export_html(spatial_data)
    assert 'window.ReportSpace=' in html and 'window.ReportDesign=' in html
    assert 'window.ReportSpaceGPU=' in html and 'gl.enable(gl.DEPTH_TEST)' in html
    assert 'data:image/png' not in html
    assert '<script src=' not in html and '<link rel="stylesheet"' not in html
    assert '材料专属空间构图' in html

@pytest.mark.anyio
async def test_spatial_generation_preserves_body_and_repairs_facts_only(spatial_data,monkeypatch):
    from tools.report_studio import generator as module
    original=spatial_data.report.model_copy(deep=True);original.spatial=None
    before=copy.deepcopy(original.model_dump())
    bad=spatial_data.report.spatial.model_copy(deep=True);bad.beats[0].caption='增长9999%'
    from tools.report_studio.spatial_models import VisualSelection
    bad.selection=VisualSelection(question='需求与融资如何影响设备？',options=[dict(expression=e,concept='方案',relevance='材料关联',risk='不量化') for e in ['literal','relationship','editorial_metaphor']],selected=1,reason='关系清楚')
    bad.opening=[g.id for g in bad.groups]
    calls=[]
    async def invoke(prompt,model,timeout):
        calls.append(model)
        if model is SpatialDesign: return SpatialDesign(spatial=bad)
        return module.Corrections(patches=[dict(path='/spatial/beats/0/caption',text=spatial_data.report.spatial.beats[0].caption)])
    monkeypatch.setattr(module,'invoke',invoke)
    result=await module.design_spatial(original,spatial_data.content)
    assert calls==[SpatialDesign,module.Corrections]
    assert result.spatial.parts==bad.parts
    result.spatial=None
    assert result.model_dump()==before and original.model_dump()==before

@pytest.mark.parametrize('profile',[[[-1,-.2],[0,1],[1,.3]],[[-1,.4],[-1,.5],[1,.4]],[[-1,0],[0,0],[1,0]]])
def test_reject_invalid_lathe_profile(spatial_data,profile):
    part=spatial_data.report.spatial.parts[0]
    part.shape='lathe';part.profile=profile
    with pytest.raises(ValueError): validate_evidence(spatial_data.report,spatial_data.content)

def test_reject_opening_with_missing_or_duplicate_groups(spatial_data):
    spatial_data.report.spatial.opening=['device','device']
    with pytest.raises(ValueError): validate_evidence(spatial_data.report,spatial_data.content)

def test_accept_curved_profile_and_semantic_opening(spatial_data):
    part=spatial_data.report.spatial.parts[0]
    part.shape='lathe';part.profile=[[-1,.7],[-.8,1],[.8,1],[1,.7]]
    spatial_data.report.spatial.opening=['credit','device']
    validate_evidence(spatial_data.report,spatial_data.content)

@pytest.mark.parametrize('stations', [
    [[-1,.5,-.5,.5],[0,1,-.5,.8],[1,.5,-.5,.5]],
    [[-1,.4,-1,-.8],[0,.8,-.6,-.2],[1,.4,.3,.5]],
])
def test_accept_loft_shells(spatial_data, stations):
    part=spatial_data.report.spatial.parts[0]
    part.shape='loft';part.stations=stations
    validate_evidence(spatial_data.report,spatial_data.content)

@pytest.mark.parametrize('stations', [
    [[-1,.5,-.5,.5],[1,.5,-.5,.5]],
    [[-1,.5,-.5,.5],[0,0,-.5,.8],[1,.5,-.5,.5]],
    [[-1,.5,-.5,.5],[0,.5,.8,-.5],[1,.5,-.5,.5]],
    [[-1,.5,-.5,.5],[-1,.5,-.5,.8],[1,.5,-.5,.5]],
    [[-1,.5,-.5,.5],[0,.5,-.5],[1,.5,-.5,.5]],
])
def test_reject_degenerate_loft_shells(spatial_data, stations):
    part=spatial_data.report.spatial.parts[0]
    part.shape='loft';part.stations=stations
    with pytest.raises(ValueError): validate_evidence(spatial_data.report,spatial_data.content)

def test_reject_unused_stations(spatial_data):
    spatial_data.report.spatial.parts[0].stations=[[-1,.5,-.5,.5],[0,1,-.5,.8],[1,.5,-.5,.5]]
    with pytest.raises(ValueError): validate_evidence(spatial_data.report,spatial_data.content)
