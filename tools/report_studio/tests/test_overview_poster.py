from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from tools.report_studio.app import ROOT
from tools.report_studio.models import ExportInput
from tools.report_studio.overview_poster import PosterProduction, validate_production, render_poster, font_path, orthogonal_route


def example():
    data=ExportInput.model_validate_json((ROOT/'sample.json').read_text())
    quote='获准任务经策略检查后执行；撤销应阻断执行入口，下游权限应包含在上游范围内，证据关联策略决定。'
    data.report.sections[0].paragraphs.append(quote)
    node=lambda id,label,kind,col,row,parent=None:dict(id=id,label=label,kind=kind,column=col,row=row,parent_id=parent,section_index=0,support_quote=quote)
    edge=lambda id,origin,to,kind,target=None:dict(id=id,origin=origin,to=to,kind=kind,target_edge=target,section_index=0,support_quote=quote)
    production=PosterProduction(mode='diagram',reason='材料中的范围包含和阻断关系需要精确绘制，不能依赖像素模型猜测箭头。',nodes=[
        node('task','获准任务','entity',0,0),node('policy','策略检查','policy',1,0),node('run','执行','entity',2,0),
        node('stop','撤销','stop',2,1),node('parent','上游范围','scope',0,1),node('child','下游范围','entity',0,1,'parent'),node('audit','责任证据','evidence',1,1)],
        edges=[edge('request1','task','policy','request'),edge('request2','policy','run','request'),edge('stop1','stop','run','block','request2'),edge('record','audit','policy','association')],
        note='建议机制；箭头表示请求，细线表示关联，终止线表示阻断；范围不表示数量。')
    return data,production


def test_scope_and_block_geometry_preserve_relation_meaning(tmp_path):
    if not font_path():pytest.skip('主机没有可用的中文字库')
    data,production=example();validate_production(production,data)
    panel=SimpleNamespace(heading='研究判断',statement='先验证权限与执行记录能否一致。',status='inference')
    plan=SimpleNamespace(title='可信执行：范围与入口',subtitle='从获准任务到可检查执行',period='输入材料所列期间',thesis='关系需要由结构明确表达。',panels=[panel,panel],boundary='本图为建议机制，不表示已经部署。')
    output=tmp_path/'poster.png'
    geometry=render_poster(plan,production,{'facts':[],'sources':[]},output)
    parent,child=geometry['boxes']['parent'],geometry['boxes']['child']
    assert parent[0]<child[0]<child[2]<parent[2]
    assert parent[1]<child[1]<child[3]<parent[3]
    block=geometry['block_endpoints']['stop1'];point=block['point'];a,b=block['segment']
    assert block['target_edge']=='request2'
    assert min(a[0],b[0])<=point[0]<=max(a[0],b[0]) and min(a[1],b[1])<=point[1]<=max(a[1],b[1])
    assert Image.open(output).size==(geometry['width'],geometry['height'])
    assert min(geometry['node_font_sizes'].values()) >= 44
    assert geometry['publication_standard'] == 'legacy-structure-1.0'


def test_wrong_entry_containment_cycle_and_unsupported_quote_are_rejected():
    data,production=example()
    production.edges[2].target_edge='request1'
    with pytest.raises(ValueError,match='实际请求入口'):validate_production(production,data)
    data,production=example();production.nodes[4].parent_id='child'
    with pytest.raises(ValueError,match='父范围'):validate_production(production,data)
    data,production=example();production.edges[0].support_quote='这是不存在于原材料中的依据。'
    with pytest.raises(ValueError,match='逐字证据'):validate_production(production,data)


def test_association_routes_around_an_unrelated_node():
    boxes={'origin':(0,0,100,100),'unrelated':(200,0,300,100),'target':(400,0,500,100)}
    nodes={id:SimpleNamespace(kind='entity',parent_id=None) for id in boxes}
    path=orthogonal_route(boxes,nodes,'origin','target')
    assert path[0] in [(0,50),(100,50),(50,0),(50,100)]
    assert path[-1] in [(400,50),(500,50),(450,0),(450,100)]
    for a,b in zip(path,path[1:]):
        if a[1]==b[1]:assert not(0<a[1]<100 and max(min(a[0],b[0]),200)<min(max(a[0],b[0]),300))
        else:assert not(200<a[0]<300 and max(min(a[1],b[1]),0)<min(max(a[1],b[1]),100))


def test_different_relation_types_do_not_share_a_corridor():
    boxes={'origin':(0,0,100,100),'target':(400,0,500,100)}
    nodes={id:SimpleNamespace(kind='entity',parent_id=None) for id in boxes}
    request=orthogonal_route(boxes,nodes,'origin','target')
    association=orthogonal_route(boxes,nodes,'origin','target',reserved=[request])
    for a,b in zip(association,association[1:]):
        assert not(a[1]==b[1]==50 and max(min(a[0],b[0]),100)<min(max(a[0],b[0]),400))


def test_auxiliary_line_avoids_crossing_existing_relationship():
    boxes={'origin':(150,0,250,100),'target':(150,300,250,400)}
    nodes={id:SimpleNamespace(kind='entity',parent_id=None) for id in boxes}
    path=orthogonal_route(boxes,nodes,'origin','target',reserved=[[(100,200),(300,200)]],avoid_crossings=True)
    for a,b in zip(path,path[1:]):
        assert not(a[0]==b[0] and 100<a[0]<300 and min(a[1],b[1])<=200<=max(a[1],b[1]))


def test_publication_dates_stay_whole_when_sources_wrap(tmp_path,monkeypatch):
    if not font_path():pytest.skip('主机没有可用的中文字库')
    from PIL import ImageDraw
    data,production=example();drawn=[];original=ImageDraw.ImageDraw.text
    def capture(self,position,value,*args,**kwargs):
        drawn.append(value);return original(self,position,value,*args,**kwargs)
    monkeypatch.setattr(ImageDraw.ImageDraw,'text',capture)
    panel=SimpleNamespace(heading='研究判断',statement='保留原文边界。',status='inference')
    plan=SimpleNamespace(title='日期完整排印',subtitle='',period='来源所列期间',thesis='来源日期不拆开。',panels=[panel,panel],boundary='依据输入材料。')
    sources=[{'label':'较长的官方反馈材料标题'*5,'date':'2026-09-29'},{'label':'另一份官方项目发布说明'*5,'date':'2026-09-29'}]
    render_poster(plan,production,{'facts':[],'sources':sources},tmp_path/'dates.png')
    assert sum('2026-09-29' in line for line in drawn)==2
    assert all('2026-09-29' in line for line in drawn if '2026' in line or '026-09' in line)


def test_publication_budget_rejects_density_instead_of_shrinking():
    from tools.report_studio.overview_style import validate_publication_copy, validate_publication_structure
    plan=SimpleNamespace(title='标题',thesis='判断',boundary='边界',panels=[])
    validate_publication_copy(plan)
    plan.thesis='长'*43
    with pytest.raises(ValueError,match='不能缩小字体'):validate_publication_copy(plan)
    _,production=example();production.callouts=['说明'*14]
    with pytest.raises(ValueError,match='用户不接受流程图'):validate_publication_structure(production)


def test_content_share_budget_preserves_four_points_without_duplicate_signature():
    from tools.report_studio.overview_style import validate_publication_copy
    panel=SimpleNamespace(heading='执行边界',statement='具体操作、允许条件与验证限制应在图片里直接说明。')
    plan=SimpleNamespace(title='权限由谁决定',thesis='任务与权限应分别设计。',boundary='仅据输入材料，建议仍需验证。',panels=[panel]*4)
    validate_publication_copy(plan)
    plan.boundary+='AI辅助图解'
    with pytest.raises(ValueError,match='固定署名'):validate_publication_copy(plan)


def test_general_reader_graphic_rejects_code_but_keeps_explained_acronyms():
    from tools.report_studio.overview_style import validate_publication_copy
    panel=SimpleNamespace(heading='执行权限',statement='人工智能(AI)可提出操作，实际执行仍需授权。')
    plan=SimpleNamespace(title='权限边界',thesis='能力与许可应分别设计。',boundary='建议尚需验证。',panels=[panel],visual_labels=[])
    validate_publication_copy(plan)
    for code in ['publish_to_production()', 'notify(user)', 'def run(task):', '```python']:
        plan.visual_labels=[code]
        with pytest.raises(ValueError,match='代码'):validate_publication_copy(plan)


def test_status_is_displayed_once_and_cannot_be_silently_reclassified():
    from tools.report_studio.overview_poster import callout_copy
    panel=SimpleNamespace(status='proposal')
    assert callout_copy('来源建议：稳定身份配合短期凭据。',panel)=='稳定身份配合短期凭据。'
    assert callout_copy('来源建议｜稳定身份配合短期凭据。',panel)=='稳定身份配合短期凭据。'
    assert callout_copy('披露：已经部署。',panel)=='披露：已经部署。'
