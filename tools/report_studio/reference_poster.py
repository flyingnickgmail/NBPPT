"""Original concept artwork from typed reference relationships, never edited pixels.

Model chooses applicability and grounded labels. Geometry is schematic, not a
measurement, and cannot carry values, dates, thresholds or sampled entities.
"""
import json
import re
from pathlib import Path
from typing import Literal
from pydantic import Field
from PIL import Image, ImageDraw
from .models import StrictModel
from .quantitative_poster import PAPER,INK,COPPER,MUTED,RULE,font,lines,ensure_glyphs


class ReferenceCase(StrictModel):
    condition: str
    outcome: str
    relation: Literal['within', 'exceeds']


class ReferenceDesign(StrictModel):
    applicable: bool
    reason: str = Field(min_length=10,max_length=350)
    object_label: str
    cases: list[ReferenceCase] = Field(max_length=2)


def validate_design(design, plan):
    if not design.applicable:
        return
    if plan.fact_refs or not plan.reader_design or plan.reader_design.visual_grammar!='condition_contrast':
        raise ValueError('参照情景图不接收定量事实或其他关系语法')
    if len(design.cases)!=2 or {c.relation for c in design.cases}!={'within','exceeds'}:
        raise ValueError('参照对照必须包含范围内与超出范围两种有据情景')
    allowed=set(plan.visual_labels)
    labels=[design.object_label,*[v for c in design.cases for v in (c.condition,c.outcome)]]
    if any(label not in allowed for label in labels):
        raise ValueError('参照情景只能使用批准且有证据的标签')
    if not plan.reader_design.chart_caption or not plan.reader_design.visual_proof:
        raise ValueError('参照情景缺少图示性质或可核验关系说明')


def geometry(relation):
    """All coordinates are illustrative layout coordinates, never business units."""
    if relation not in {'within','exceeds'}:
        raise ValueError('未知参照关系')
    return {'reference_left':180,'reference_right':1040,
            'object_left':220,'object_right':980 if relation=='within' else 1340,
            'overflow_left':1040 if relation=='exceeds' else None,
            'quantitative':False}


async def select_and_render(plan,data,folder,invoke):
    presentation = getattr(plan, 'presentation', None)
    if presentation and presentation.rendering != 'exact_reference':
        return None
    if not plan.reader_design or plan.reader_design.visual_grammar!='condition_contrast' or plan.fact_refs or len(plan.panels)>3:
        return None
    folder=Path(folder)
    prompt=('判断批准方案是否适用于精确参照对照。只返回结构，不调用工具。'
            '只支持同一对象相对适用参照范围的两个分析情景：within范围内与exceeds超出右界。'
            '若方案是两种独立条件的交集、数量比较、流程、时间线或不能用同一参照表达，则applicable=false且cases=[]，不能硬套。'
            '不是选行业模板，不新增阈值、实测对象、统计值或因果条件。'
            '适用时所有标签必须逐字从visual_labels选择：object_label对象，'
            '两项cases各有condition条件（须直接命名对应的业务参照）、outcome相邻行动标签、relation。'
            '按原方案保留分析建议与未知，禁止将超出条件扩大为任何不匹配。'
            '\n批准方案：'+plan.model_dump_json())
    design=await invoke(prompt,ReferenceDesign,180)
    (folder/'reference-design.json').write_text(design.model_dump_json(indent=2))
    validate_design(design,plan)
    if not design.applicable:return None
    return render(plan,data,design,folder)


def render(plan,data,design,folder):
    validate_design(design,plan)
    image=Image.new('RGB',(1600,2000),PAPER);d=ImageDraw.Draw(image)
    def text(value,x,y,size=40,width=1400,color=INK,serif=False,max_lines=None):
        face=font(size,serif);ensure_glyphs(value,face);wrapped=[];current=""
        for token in re.findall(r"[A-Za-z]+|[0-9]+(?:[-./][0-9]+)*|[^\n]|\n",value):
            if token=="\n" or (current and face.getlength(current+token)>width and token not in "，。；：！？、,.!?;:"):
                wrapped.append(current);current=""
                if token=="\n":continue
            current+=token
        if current:wrapped.append(current)
        if max_lines and len(wrapped)>max_lines:
            raise ValueError('参照图文字超出安全区，应精简设计文案')
        for i,line in enumerate(wrapped):d.text((x,y+i*size*1.36),line,font=face,fill=color)
        return y+len(wrapped)*size*1.36
    def rule(y):d.line((100,y,1500,y),fill=RULE,width=2)
    text('友车科技  /  研究图解',100,55,28,color=COPPER)
    d.rectangle((100,111,220,119),fill=COPPER)
    end=text(plan.title,100,150,78,serif=True,max_lines=2)
    y=max(320,end+25)
    y=text(plan.subtitle,100,y,34,color=MUTED,max_lines=2)+22
    # Source observations at the top, implication at the end; every approved
    # panel remains visible and keeps its epistemic label.
    statuses={'observed':'披露','proposal':'来源建议','inference':'分析建议','unknown':'待验证'}
    implication=plan.reader_design.implication_panel_index
    for i,p in enumerate(plan.panels):
        if i==implication:continue
        if y>660:raise ValueError('参照图前置信息过多，无法保持主图空间')
        text(p.heading+' · '+statuses[p.status],100,y,26,color=COPPER)
        y=text(p.statement,100,y+42,36,max_lines=2)+26
    rule(y)
    top=y+30
    text(plan.reader_design.chart_caption,100,top,29,color=MUTED,max_lines=2)
    top+=92
    cases=sorted(design.cases,key=lambda c:c.relation!='within')
    geometry_record=[]
    for i,c in enumerate(cases):
        row=top+i*330;g=geometry(c.relation);geometry_record.append({**g,'condition':c.condition,'outcome':c.outcome})
        # Explicit illustrative reference window, no numeric axis or actual
        # inventory points. End caps encompass the top object in full.
        color=INK if c.relation=='within' else COPPER
        text(c.condition,100,row,39,color=color,serif=True,max_lines=1)
        left,right=g['reference_left'],g['reference_right'];by=row+107
        d.line((left,by-15,right,by-15),fill=MUTED,width=2)
        for x in [left,right]:
            d.line((x,by-25,x,by+125),fill=MUTED,width=2)
        d.rounded_rectangle((g['object_left'],by,g['object_right'],by+95),radius=5,fill='#E3DBCE',outline=INK,width=2)
        if g['overflow_left'] is not None:
            a,b=g['overflow_left'],g['object_right']
            d.rectangle((a,by,b,by+95),fill='#EAD0BD')
            # Clipped diagonal marks exist only to the right of the reference.
            for offset in range(-95,b-a+1,16):
                x1=max(a,a+offset);y1=by+95-max(0,-offset)
                x2=min(b,a+offset+95);y2=by+max(0,a+offset+95-b)
                if x1<x2:d.line((x1,y1,x2,y2),fill=COPPER,width=2)
        text(design.object_label,g['object_left']+22,by+10,34,width=680,max_lines=1)
        text(c.outcome,100,by+145,39,color=color,max_lines=1)
    bottom=top+660
    rule(bottom)
    p=plan.panels[implication]
    text(p.heading+' · '+statuses[p.status],100,bottom+30,28,color=COPPER)
    bottom=text(p.statement,100,bottom+80,42,max_lines=2)+36
    bottom=text(plan.thesis,100,bottom,31,color=MUTED,max_lines=2)+24
    rule(bottom)
    bottom=text(plan.boundary,100,bottom+23,27,color=MUTED,max_lines=3)+16
    source={s.id:s for s in data.report.sources}
    source_text='来源：'+'；'.join(source[i].label+' · '+source[i].date for i in plan.source_ids)
    bottom=text(source_text,100,bottom,27,color=MUTED,max_lines=3)
    if bottom>1905:raise ValueError('参照图正文超出来源安全区，请缩短设计')
    text('友车科技 · 研究图解',100,1940,29)
    text('AI辅助图解 · 依据输入报告整理',930,1944,23,width=570,color=MUTED)
    out=Path(folder)/'reference-contrast.png';image.save(out,optimize=True)
    (Path(folder)/'reference-geometry.json').write_text(json.dumps(geometry_record,ensure_ascii=False,indent=2))
    (Path(folder)/'render-engine.json').write_text(json.dumps({'engine':'reference-contrast.v1','dimensions':[1600,2000],'quantitative':False,'selection':'model-authored labels and relations; schematic reference geometry'},ensure_ascii=False,indent=2))
    return out
