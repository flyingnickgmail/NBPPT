"""Deterministic numeric share artwork selected by a model-authored overview plan.

This creates a new image from structured evidence; it does not edit generated
artwork. Unsupported information grammars continue through image generation.
"""
import json
import math
import re
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from .qualified import SYMBOLS

PAPER, INK, COPPER, MUTED, RULE = '#F5F1E9', '#252824', '#B45F36', '#6C6861', '#D4CBBE'


def select_chart(plan, data):
    if not plan.reader_design or plan.reader_design.visual_grammar != 'quantitative_comparison' or len(plan.panels)>3:
        return None
    matches = [re.fullmatch(r'sections/(\d+)/visuals/(\d+)/points/(\d+)', ref) for ref in plan.fact_refs]
    if not 2 <= len(matches) <= 3 or any(m is None for m in matches):
        return None
    parents = {(int(m[1]), int(m[2])) for m in matches}
    if len(parents) != 1:
        return None
    si, vi = next(iter(parents))
    visual = data.report.sections[si].visuals[vi]
    if visual.kind != 'qualified_dot' or len(visual.basis)>150:
        return None
    selected = [visual.points[int(m[3])] for m in matches]
    if len(visual.unit)>12 or any(len(p.label)>18 for p in selected):
        return None
    return visual, selected


def geometry(points, left=132, right=1440):
    low, high = min(0, *(p.value for p in points)), max(0, *(p.value for p in points))
    raw = (high-low or 1)/5
    power = 10**math.floor(math.log10(raw))
    step = next(n for n in (1, 2, 2.5, 5, 10) if n >= raw/power)*power
    # Room beyond a bound is drawing space, never another measurement.
    low = math.floor(low/step)*step
    high = math.ceil(high/step)*step
    if high == low:
        high += step
    if any(p.relation in ('gt','gte') and high-p.value < (high-low)*.08 for p in points):
        high += step
    if any(p.relation in ('lt','lte') and p.value <= low for p in points):
        low -= step
    pos = lambda value: left+(value-low)/(high-low)*(right-left)
    ticks = [low+i*step for i in range(round((high-low)/step)+1)]
    return {'low':low,'high':high,'ticks':[{'value':v,'x':pos(v)} for v in ticks],
            'points':[{'value':p.value,'relation':p.relation,'x':pos(p.value)} for p in points],
            'zero':pos(0),'left':left,'right':right}


@lru_cache(maxsize=12)
def font(size, serif=False):
    # Some macOS PingFang asset collections expose blank CJK glyphs through
    # FreeType despite reporting a valid character advance (e.g. 迟).
    family = 'Songti SC' if serif else 'Noto Sans CJK SC:style=Regular'
    try:
        path = subprocess.check_output(['fc-match','-f','%{file}',family],text=True,timeout=5).strip()
    except (OSError, subprocess.SubprocessError):
        path = '/System/Library/Fonts/Supplemental/Songti.ttc' if serif else '/System/Library/Fonts/STHeiti Medium.ttc'
    if not Path(path).is_file():
        raise ValueError('精确图稿缺少中文字体，请配置中文字体后重试。')
    return ImageFont.truetype(path, size)


def lines(text, face, width):
    result, current = [], ''
    for char in text:
        if char == '\n' or (current and char not in '，。；：！？、,.!?;:' and face.getlength(current+char)>width):
            result.append(current);current=''
            if char=='\n':continue
        current+=char
    if current:result.append(current)
    return result


def ensure_glyphs(text, face):
    missing=[c for c in set(text) if not c.isspace() and face.getmask(c).getbbox() is None]
    if missing:
        raise ValueError('分享图字体缺少可见字形：'+''.join(sorted(missing))+'；请配置完整中文字体后重新生成。')


def render(plan, data, folder):
    chosen=select_chart(plan,data)
    if not chosen:return None
    visual,points=chosen
    if getattr(plan.reader_design, 'numeric_layout', 'horizontal_scale') == 'paired_columns':
        if any(p.value < 0 for p in points):
            raise ValueError('并置立柱仅适合非负值，请模型选择水平标尺。')
        return render_columns(plan, data, folder, visual, points)
    image=Image.new('RGB',(1600,2000),PAPER);draw=ImageDraw.Draw(image)
    def text(value,x,y,size=40,color=INK,width=1380,serif=False,leading=1.4):
        face=font(size,serif);ensure_glyphs(value,face);wrapped=lines(value,face,width)
        for i,line in enumerate(wrapped):draw.text((x,y+i*size*leading),line,font=face,fill=color)
        return y+len(wrapped)*size*leading
    def rule(y,color=RULE):draw.line((110,y,1490,y),fill=color,width=2)
    text('友车科技  /  研究图解',110,62,27,COPPER)
    text('AI辅助图解 · 依据输入报告整理',975,65,24,MUTED,width=515)
    rule(120,COPPER)
    headline=plan.title
    clauses=re.split('[，：]',headline,maxsplit=1)
    if len(clauses)==2 and all(4<=len(c)<=17 for c in clauses):headline=clauses[0]+'，\n'+clauses[1]
    end=text(headline,110,160,82,width=1380,serif=True,leading=1.25)
    if end>380:raise ValueError('分享图标题超出两行安全区，请缩短标题。')
    text(plan.subtitle,110,405,36,MUTED)
    end=text(plan.thesis,110,485,39,width=1370,leading=1.45)
    if end>605:raise ValueError('分享图核心判断超出安全区，请压缩文案。')
    g=geometry(points,left=500,right=1460)
    top,bottom=740,1090
    text('同比比较' if '同比' in visual.basis else '同尺度比较',110,615,25,COPPER)
    text('单位：'+visual.unit,1260,615,25,MUTED,width=230)
    basis_end=text(visual.basis,110,655,23,MUTED,width=1380,leading=1.3)
    if basis_end>730:raise ValueError('统计口径过长，无法在数字图稿中完整排下。')
    ys=[top+75+i*(bottom-top-120)/max(1,len(points)-1) for i in range(len(points))]
    for tick in g['ticks']:
        x=tick['x'];draw.line((x,top,x,bottom+15),fill=RULE,width=2)
        face=font(27);value=f"{tick['value']:g}";draw.text((x-face.getlength(value)/2,bottom+34),value,font=face,fill=MUTED)
    draw.line((g['zero'],top,g['zero'],bottom+15),fill=MUTED,width=2)
    for p,pt,y in zip(points,g['points'],ys):
        x=pt['x'];color=COPPER if p.emphasis or p.relation!='exact' else INK
        # Labels above each row leave a full-width exact linear scale.
        text(p.label,110,y-30,40,INK,width=380)
        draw.line((g['zero'],y,x,y),fill=color,width=5)
        value=f'{SYMBOLS[p.relation]}{p.value:.15g}{visual.unit}'
        face=font(48,True);tx=max(500,min(x-face.getlength(value)/2,1490-face.getlength(value)))
        draw.text((tx,y-70),value,font=face,fill=color)
        if p.relation=='approx':
            draw.ellipse((x-15,y-15,x+15,y+15),outline=color,width=4)
            draw.text((x-10,y-20),'≈',font=font(29),fill=color)
        elif p.relation in ('gt','gte','lt','lte'):
            sign=1 if p.relation in ('gt','gte') else -1
            draw.ellipse((x-13,y-13,x+13,y+13),fill=PAPER,outline=color,width=4)
            if p.relation in ('gte','lte'):draw.ellipse((x-5,y-5,x+5,y+5),fill=color)
            tip=x+sign*44;draw.line((x+sign*15,y,tip,y),fill=color,width=4)
            draw.line((tip-sign*12,y-9,tip,y),fill=color,width=4);draw.line((tip-sign*12,y+9,tip,y),fill=color,width=4)
        else:draw.ellipse((x-13,y-13,x+13,y+13),fill=color)
    text('● 报告值   ≈ 近似值   空心点与短箭头表示界限，箭头长度不表示数量',110,1165,23,MUTED)
    rule(1215)
    statuses={'observed':'披露','proposal':'来源建议','inference':'分析建议','unknown':'待验证'}
    y=1240
    for panel in plan.panels:
        if y>1635:raise ValueError('分享图支撑文案过多，无法保持可读字号。')
        color=COPPER if panel.status=='inference' else INK
        text(panel.heading,110,y,36,color,serif=True,width=280)
        text(statuses[panel.status],110,y+55,23,MUTED,width=270)
        end=text(panel.statement,430,y,44,color,width=1040,leading=1.25)
        if end>y+125:raise ValueError('分享图单条文案超出两行，请压缩文案。')
        y+=max(125,end-y+28)
    rule(y)
    end=text(plan.boundary,110,y+25,26,MUTED,width=1380,leading=1.5)
    if end>1850:raise ValueError('分享图边界文案过长，来源安全区不足。')
    sources={s.id:s for s in data.report.sources}
    source_lines=[f'{sources[i].label} · {sources[i].date}' for i in plan.source_ids if i in sources]
    source='来源：'+'；'.join(source_lines)
    end=text(source,110,1880,23,MUTED,width=1380,leading=1.4)
    if end>1980:raise ValueError('来源过多，无法在分享图完整保留；应收缩主图范围。')
    folder=Path(folder);out=folder/'quantitative.png';image.save(out,optimize=True)
    (folder/'quantitative-geometry.json').write_text(json.dumps(g,ensure_ascii=False,indent=2))
    (folder/'render-engine.json').write_text(json.dumps({'engine':'qualified-numeric.v1','dimensions':[1600,2000],
        'selection':'model-authored quantitative_comparison, facts from one qualified_dot','geometry':'exact linear scale; no generated pixels used'},ensure_ascii=False,indent=2))
    return out


def render_columns(plan, data, folder, visual, points):
    """Editorial comparison: exact heights, open bounds, one business takeaway.

    All visible prose comes from the validated model plan or source fields.
    No report/industry-specific geometry or copy is embedded here.
    """
    image=Image.new('RGB',(1600,2000),PAPER);draw=ImageDraw.Draw(image)
    def block(value,x,y,size,width,color=INK,serif=False,leading=1.3,max_lines=None):
        face=font(size,serif);ensure_glyphs(value,face);wrapped=lines(value,face,width)
        if max_lines is not None and len(wrapped)>max_lines:
            raise ValueError('分享图文字超出层级安全区，应缩短文案而不是缩字。')
        for i,line in enumerate(wrapped):draw.text((x,y+i*size*leading),line,font=face,fill=color)
        return y+len(wrapped)*size*leading
    block('友车科技  /  研究图解',100,58,28,1000,COPPER)
    block('AI辅助图解 · 依据输入报告整理',1000,62,24,500,MUTED)
    draw.rectangle((100,122,210,130),fill=COPPER)
    headline=plan.title
    clauses=re.split('[，：]',headline,maxsplit=1)
    if len(clauses)==2:headline=clauses[0]+'，\n'+clauses[1]
    block(headline,100,165,90,1400,serif=True,max_lines=2)
    block(plan.thesis,100,425,42,1400,max_lines=2)
    # Same vertical coordinate system. No perspective or decorative height.
    g=geometry(points,left=0,right=1)
    top,bottom=800,1290
    value_y=lambda v:bottom-(v-g['low'])/(g['high']-g['low'])*(bottom-top)
    caption=plan.reader_design.chart_caption
    if not caption:raise ValueError('并置立柱缺少模型撰写的统计期与单位说明。')
    block(caption,100,575,32,1400,MUTED,max_lines=2)
    for tick in g['ticks']:
        y=value_y(tick['value'])
        draw.line((220,y,1460,y),fill=RULE,width=2)
        block(f"{tick['value']:g}",100,y-18,30,110,MUTED)
    draw.line((220,bottom,1460,bottom),fill=INK,width=3)
    xs=[480+i*690/max(1,len(points)-1) for i in range(len(points))]
    width=200 if len(points)==2 else 150
    for p,x in zip(points,xs):
        y=value_y(p.value);color=COPPER if p.emphasis or p.relation!='exact' else INK
        # Exact/approximate heights and threshold positions are distinct.
        draw.rectangle((x-width/2,y,x+width/2,bottom),fill=color)
        if p.relation in ('gt','gte','lt','lte'):
            draw.rectangle((x-width/2,y,x+width/2,y+25),fill=PAPER)
            for offset in range(0,width,20):
                draw.line((x-width/2+offset,y+25,x-width/2+offset+12,y),fill=color,width=3)
        label=f'{SYMBOLS[p.relation]}{p.value:.15g}{visual.unit}'
        face=font(110 if len(points)==2 else 82,True)
        text_width=face.getlength(label)
        draw.rectangle((x-text_width/2-12,y-135,x+text_width/2+12,y-12),fill=PAPER)
        draw.text((x-face.getlength(label)/2,y-135),label,font=face,fill=color)
        ensure_glyphs(p.label,font(40))
        label_lines=lines(p.label,font(40),420 if len(points)==2 else 320)
        for i,line in enumerate(label_lines):
            draw.text((x-font(40).getlength(line)/2,1325+i*51),line,font=font(40),fill=INK)
        if len(label_lines)>2:raise ValueError('类别名称超出分享图两行范围。')
    block('界限符号保留原文口径，开放柱顶不表示已知终值',100,1450,28,1400,MUTED)
    # One distinct takeaway, not a repeated table of every approved panel.
    implication=plan.panels[plan.reader_design.implication_panel_index]
    draw.rectangle((0,1500,1600,1740),fill=INK)
    block('对友车科技的启发 · 分析建议',100,1535,28,1400,'#DFA480')
    block(implication.statement,100,1590,46,1400,PAPER,max_lines=2)
    block(plan.boundary,100,1770,32,1400,MUTED,max_lines=3)
    sources={s.id:s for s in data.report.sources}
    source='来源：'+'；'.join(f'{sources[i].label} · {sources[i].date}' for i in plan.source_ids if i in sources)
    block(source,100,1910,32,1400,MUTED,max_lines=2)
    # Every non-implication statement must be represented by the thesis or facts;
    # the approved overview audit checks this semantic compression as well.
    folder=Path(folder);out=folder/'quantitative.png';image.save(out,optimize=True)
    g['vertical']={'top':top,'bottom':bottom,'points':[{'value':p.value,'relation':p.relation,'y':value_y(p.value)} for p in points]}
    (folder/'quantitative-geometry.json').write_text(json.dumps(g,ensure_ascii=False,indent=2))
    (folder/'render-engine.json').write_text(json.dumps({'engine':'qualified-numeric.v2','layout':'paired_columns','dimensions':[1600,2000],'geometry':'exact zero-based vertical scale; open bounds; no generated pixels'},ensure_ascii=False,indent=2))
    return out
