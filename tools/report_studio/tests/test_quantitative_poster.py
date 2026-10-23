from types import SimpleNamespace
import pytest
from tools.report_studio.quantitative_poster import geometry,select_chart,lines
from tools.report_studio.models import QualifiedPoint


def point(n,rel='exact'):
    return QualifiedPoint(label='测试',value=n,relation=rel,quote=str(n),qualifier_quote=str(n))


@pytest.mark.parametrize('values',[[75,120],[-20,30,90],[0,0],[.01,.1],[-5,-1]])
def test_scale_is_mathematically_uniform(values):
    g=geometry([point(v) for v in values])
    ticks=g['ticks'];d=ticks[1]['x']-ticks[0]['x']
    for a,b in zip(ticks,ticks[1:]):assert b['x']-a['x']==pytest.approx(d)
    for p in g['points']:
        assert p['x']==pytest.approx(g['left']+(p['value']-g['low'])/(g['high']-g['low'])*(g['right']-g['left']))


def test_bound_has_open_drawing_room_without_invented_measurement():
    g=geometry([point(75),point(120,'gt')])
    assert g['right']-g['points'][1]['x']>44
    assert g['points'][1]['value']==120 and g['points'][1]['relation']=='gt'


def test_unrelated_graphics_never_enter_numeric_renderer():
    plan=SimpleNamespace(reader_design=SimpleNamespace(visual_grammar='annotated_structure'),fact_refs=[],panels=[])
    assert select_chart(plan,None) is None
    plan.reader_design.visual_grammar='quantitative_comparison';plan.fact_refs=['metrics/0','metrics/1']
    assert select_chart(plan,None) is None


def test_editorial_columns_preserve_true_height_and_bound(tmp_path):
    import json
    from PIL import Image
    from tools.report_studio.quantitative_poster import render
    points=[point(120,'gt'),point(75)]
    for p in points:p.label='类别'
    visual=SimpleNamespace(kind='qualified_dot',basis='同一期间',unit='%',points=points)
    data=SimpleNamespace(report=SimpleNamespace(sections=[SimpleNamespace(visuals=[visual])],sources=[]))
    plan=SimpleNamespace(reader_design=SimpleNamespace(visual_grammar='quantitative_comparison',numeric_layout='paired_columns',chart_caption='同一期间 · 单位：%',implication_panel_index=0),fact_refs=['sections/0/visuals/0/points/0','sections/0/visuals/0/points/1'],panels=[SimpleNamespace(statement='核对真实记录，验证具体原因。')],title='规模差异，需要如何判断',thesis='这是有口径约束的比较。',boundary='各项指标具有独立分母，不代表同一批对象的转化率。',source_ids=[])
    out=render(plan,data,tmp_path)
    assert Image.open(out).size==(1600,2000)
    g=json.loads((tmp_path/'quantitative-geometry.json').read_text())
    vertical=g['vertical'];a,b=vertical['points']
    assert (vertical['bottom']-a['y'])/(vertical['bottom']-b['y'])==pytest.approx(120/75)
    assert a['relation']=='gt'
    points[0].value=-20
    with pytest.raises(ValueError,match='非负值'):render(plan,data,tmp_path)


def test_missing_visible_glyph_is_blocked_instead_of_silent_space():
    from tools.report_studio.quantitative_poster import ensure_glyphs,font
    from types import SimpleNamespace
    fake=SimpleNamespace(getmask=lambda c:SimpleNamespace(getbbox=lambda:None if c=='迟' else (0,0,1,1)))
    with pytest.raises(ValueError,match='迟'):ensure_glyphs('统计延迟',fake)
    ensure_glyphs('统计延迟',font(32))
