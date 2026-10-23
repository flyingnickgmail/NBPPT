"""Typed relationship posters: model chooses the structure; pixels preserve it."""
import math
import os
import heapq
import re
from pathlib import Path
from typing import Annotated, Literal

from PIL import Image, ImageDraw, ImageFont
from pydantic import Field

from .evidence import number_tokens
from .models import StrictModel
from .overview_style import WIDTH, MARGIN, MIN_NODE_SIZE, TITLE_SIZE, BODY_SIZE, FOOTER_SIZE, VERSION


class PosterNode(StrictModel):
    id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,24}$')
    label: str = Field(min_length=1, max_length=14)
    kind: Literal['entity', 'policy', 'scope', 'stop', 'evidence', 'boundary']
    column: int = Field(ge=0, le=2)
    row: int = Field(ge=0, le=3)
    parent_id: str | None
    section_index: int = Field(ge=0, le=23)
    support_quote: str = Field(min_length=10, max_length=1000)


class PosterEdge(StrictModel):
    id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,24}$')
    origin: str
    to: str
    kind: Literal['request', 'association', 'block']
    target_edge: str | None
    section_index: int = Field(ge=0, le=23)
    support_quote: str = Field(min_length=10, max_length=1000)


class PosterProduction(StrictModel):
    mode: Literal['diagram', 'illustration']
    reason: str = Field(min_length=20, max_length=500)
    nodes: list[PosterNode] = Field(max_length=12)
    edges: list[PosterEdge] = Field(max_length=16)
    note: str = Field(max_length=80)
    callouts: list[Annotated[str, Field(min_length=1, max_length=32)]] = Field(default_factory=list, max_length=4)


def validate_production(design, data):
    if design.mode == 'illustration':
        if design.nodes or design.edges or design.callouts:
            raise ValueError('插画方式不应携带未绘制的关系结构')
        return
    if len(design.nodes) < 2:
        raise ValueError('结构图需要至少两个有依据的节点')
    ids = {node.id: node for node in design.nodes}
    edges = {edge.id: edge for edge in design.edges}
    if len(ids) != len(design.nodes) or len(edges) != len(design.edges):
        raise ValueError('关系图节点或连线标识重复')
    slots = set()
    children = {}
    for item in [*design.nodes, *design.edges]:
        if item.section_index >= len(data.report.sections):
            raise ValueError('结构图引用的章节不存在')
        section = data.report.sections[item.section_index]
        if item.support_quote not in '\n'.join([*section.paragraphs, *section.bullets]):
            raise ValueError(f'结构图节点或关系 {item.id} 缺少第{item.section_index+1}节的逐字证据，请检查章节索引和引文')
    available = set(number_tokens(data.report.model_dump_json()))
    if set(number_tokens(' '.join([design.note, *design.callouts, *[n.label for n in design.nodes]]))) - available:
        raise ValueError('结构图新增了报告外的数值')
    if design.note and not design.note.endswith(('。', '.', '！', '!', '？', '?')):
        raise ValueError('图例须是给读者的完整短句，不能截断或印入制作指令')
    if sum(node.kind == 'boundary' for node in design.nodes) > 1:
        raise ValueError('整体状态边界最多一项')
    for node in design.nodes:
        if node.kind == 'boundary':
            if node.parent_id:raise ValueError('整体状态边界不能成为子节点')
            continue
        if node.parent_id:
            parent = ids.get(node.parent_id)
            if not parent or parent.kind != 'scope' or parent.parent_id or parent.id == node.id:
                raise ValueError('范围包含只允许一个有效父范围，不支持循环或多级嵌套')
            if (node.column, node.row) != (parent.column, parent.row):
                raise ValueError('包含节点必须继承父范围的位置')
            if node.parent_id in children:
                raise ValueError('每个范围最多一个嵌套范围，以保证手机可读性')
            children[node.parent_id] = node
        elif (node.column, node.row) in slots:
            raise ValueError('结构图的独立节点位置重叠')
        else:
            slots.add((node.column, node.row))
    for edge in design.edges:
        if edge.origin not in ids or edge.to not in ids or edge.origin == edge.to:
            raise ValueError('结构图连线必须引用两个已有节点')
        if ids[edge.origin].kind == 'boundary' or ids[edge.to].kind == 'boundary':
            raise ValueError('整体状态边界不参与请求或关联流程')
        if edge.kind == 'block':
            target = edges.get(edge.target_edge)
            if not target or target.kind != 'request' or target.to != edge.to:
                raise ValueError('阻断线必须终止于实际请求入口，而非执行区外围')
        elif edge.target_edge is not None:
            raise ValueError('只有阻断线可以引用请求入口')


def font_path():
    paths = [os.getenv('REPORT_CJK_FONT', ''), '/System/Library/Fonts/STHeiti Medium.ttc',
             '/System/Library/Fonts/Supplemental/Songti.ttc',
             '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
    return next((Path(path) for path in paths if path and Path(path).is_file()), None)


def orthogonal_route(boxes, nodes, origin, target=None, point=None, reserved=(), arrival_direction=None, avoid_crossings=False, bounds=None):
    """Route through whitespace, so a line never appears to connect an unrelated card."""
    source=boxes[origin]
    destination=boxes[target] if target else None
    center=lambda box:((box[0]+box[2])/2,(box[1]+box[3])/2)
    goal=center(destination) if destination else point
    def ports(box, other):
        x,y=center(box);dx,dy=other[0]-x,other[1]-y
        choices=[((box[2],y),(box[2]+12,y)),((box[0],y),(box[0]-12,y)),((x,box[3]),(x,box[3]+12)),((x,box[1]),(x,box[1]-12))]
        preferred=(0 if dx>=0 else 1) if abs(dx)>abs(dy) else (2 if dy>=0 else 3)
        return [choices[preferred],*[p for i,p in enumerate(choices) if i!=preferred]]
    ignored={nodes[id].parent_id for id in [origin,target] if id and nodes[id].parent_id}
    obstacles=[(box[0]-7,box[1]-7,box[2]+7,box[3]+7) for id,box in boxes.items() if id not in ignored and nodes[id].kind!='boundary']
    segments=[(a,b) for path in reserved for a,b in zip(path,path[1:])]
    def separate(a,b):
        for c,d in segments:
            if a[0]==b[0] and c[0]==d[0] and abs(a[0]-c[0])<12 and max(min(a[1],b[1]),min(c[1],d[1]))<min(max(a[1],b[1]),max(c[1],d[1])):return False
            if a[1]==b[1] and c[1]==d[1] and abs(a[1]-c[1])<12 and max(min(a[0],b[0]),min(c[0],d[0]))<min(max(a[0],b[0]),max(c[0],d[0])):return False
            if avoid_crossings:
                if a[0]==b[0] and c[1]==d[1] and min(c[0],d[0])<a[0]<max(c[0],d[0]) and min(a[1],b[1])<=c[1]<=max(a[1],b[1]):return False
                if a[1]==b[1] and c[0]==d[0] and min(a[0],b[0])<=c[0]<=max(a[0],b[0]) and min(c[1],d[1])<a[1]<max(c[1],d[1]):return False
        return True
    def clear(a,b):
        if bounds and any(not(bounds[0]<=p[0]<=bounds[2] and bounds[1]<=p[1]<=bounds[3]) for p in [a,b]):return False
        if not separate(a,b):return False
        for x1,y1,x2,y2 in obstacles:
            if a[0]==b[0] and x1<a[0]<x2 and max(min(a[1],b[1]),y1)<min(max(a[1],b[1]),y2):return False
            if a[1]==b[1] and y1<a[1]<y2 and max(min(a[0],b[0]),x1)<min(max(a[0],b[0]),x2):return False
        return True
    routes=[]
    for start_inside,start in ports(source,goal):
        for end_inside,end in (ports(destination,center(source)) if destination else [(point,point)]):
            if not separate(start_inside,start) or not separate(end,end_inside):continue
            xs=sorted({start[0],end[0],*[x for b in boxes.values() for x in [b[0]-12,(b[0]+b[2])/2,b[2]+12]],*[x+offset for segment in segments for p in segment for x in [p[0]] for offset in [-20,20]]})
            ys=sorted({start[1],end[1],*[y for b in boxes.values() for y in [b[1]-12,(b[1]+b[3])/2,b[3]+12]],*[y+offset for segment in segments for p in segment for y in [p[1]] for offset in [-20,20]]})
            begin=(xs.index(start[0]),ys.index(start[1]),2);end_index=(xs.index(end[0]),ys.index(end[1]))
            queue=[(0,0,begin)];costs={begin:0};parents={}
            finish=None
            while queue:
                _,cost,state=heapq.heappop(queue)
                if cost!=costs[state]:continue
                ix,iy,direction=state
                if (ix,iy)==end_index and (arrival_direction is None or direction==arrival_direction):finish=state;break
                for nx,ny,nd in [(ix-1,iy,0),(ix+1,iy,0),(ix,iy-1,1),(ix,iy+1,1)]:
                    if not(0<=nx<len(xs) and 0<=ny<len(ys)):continue
                    a,b=(xs[ix],ys[iy]),(xs[nx],ys[ny])
                    if not clear(a,b):continue
                    next_state=(nx,ny,nd);next_cost=cost+math.dist(a,b)+(24 if direction!=2 and direction!=nd else 0)
                    if next_cost>=costs.get(next_state,float('inf')):continue
                    costs[next_state]=next_cost;parents[next_state]=state
                    heapq.heappush(queue,(next_cost+abs(b[0]-end[0])+abs(b[1]-end[1]),next_cost,next_state))
            if finish is not None:
                result=[];state=finish
                while True:
                    result.append((xs[state[0]],ys[state[1]]))
                    if state==begin:break
                    state=parents[state]
                result=[start_inside,*reversed(result),end_inside]
                compact=[]
                for p in result:
                    if compact and p==compact[-1]:continue
                    while len(compact)>1 and ((compact[-2][0]==compact[-1][0]==p[0]) or (compact[-2][1]==compact[-1][1]==p[1])):compact.pop()
                    compact.append(p)
                score=sum(math.dist(a,b) for a,b in zip(compact,compact[1:]))+24*max(0,len(compact)-2)
                routes.append((score,compact))
    if routes:
        return min(routes,key=lambda item:item[0])[1]
    raise ValueError('关系通道过于拥挤，请减少关联或调整节点位置')


def callout_copy(copy, panel):
    """A status badge owns status; strip only a matching redundant prefix."""
    aliases={'observed':{'披露','已观察','事实'},'proposal':{'反馈主张','来源建议','机构建议','原文建议'},
             'inference':{'编辑建议','分析建议','本图建议'},'unknown':{'待验证','结果尚缺','未知','未披露'}}
    parts=re.split(r'[｜|：:]',copy,maxsplit=1)
    return parts[1].strip() if len(parts)==2 and parts[0].strip() in aliases[panel.status] else copy


def render_poster(plan, production, resolved, output):
    """Create a new PNG from typed data, without editing a generated picture."""
    font = font_path()
    if not font:
        raise ValueError('未找到中文字库，可设置 REPORT_CJK_FONT；不输出缺字图片')
    paper, ink, accent, soft, muted = '#F5F1E9', '#252824', '#B45F36', '#EAE2D5', '#6A6D66'
    white, line_color = '#FFFCF7', '#D7D0C4'
    width, margin = WIDTH, MARGIN
    title_copy = plan.title
    subtitle_copy = '' if ''.join(c for c in plan.subtitle if c.isalnum()) == '友车科技研究图解' else plan.subtitle
    scratch = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    fonts = {size: ImageFont.truetype(str(font), size=size) for size in [28, 32, 36, 40, 44, 48, 52, 60, 72, 84, 88]}

    def wrap(text, size, max_width):
        lines, line = [], ''
        tokens=re.findall(r'\d{4}-\d{2}-\d{2}|[+−-]?\d[\d,.]*(?:%)?|[A-Za-z][A-Za-z0-9_/-]*|\n|.',text)
        for token in tokens:
            if token == '\n' or (line and scratch.textlength(line + token, font=fonts[size]) > max_width):
                lines.append(line); line = ''
            if token == '\n':continue
            if scratch.textlength(token,font=fonts[size])>max_width:
                for char in token:
                    if line and scratch.textlength(line+char,font=fonts[size])>max_width:lines.append(line);line=''
                    line+=char
            else:line+=token if line else token.lstrip()
        if line: lines.append(line)
        closing='，。；：！？、）》】”’％%'
        for i in range(1,len(lines)):
            if lines[i] and lines[i][0] in closing and len(lines[i-1])>1:
                lines[i]=lines[i-1][-1]+lines[i];lines[i-1]=lines[i-1][:-1]
        # Balance a lone CJK tail without splitting a date or an English token.
        if len(lines)>1 and len(lines[-1])==1 and re.fullmatch(r'[\u4e00-\u9fff]',lines[-1]) and re.search(r'[\u4e00-\u9fff]{2}$',lines[-2]):
            lines[-1]=lines[-2][-2:]+lines[-1];lines[-2]=lines[-2][:-2]
        return lines

    def text_height(text, size, max_width):
        return len(wrap(text, size, max_width)) * int(size * 1.38)

    y = 144 + text_height(title_copy, TITLE_SIZE, width - 2 * margin)
    if subtitle_copy:y += text_height(subtitle_copy, 36, width - 2 * margin) + 18
    y += text_height(plan.thesis, 44, width - 2 * margin - 44) + 56
    facts = resolved['facts']
    fact_w = (width-2*margin)//max(1,len(facts))
    if facts: y += max(text_height(f['label'],32,fact_w-20)+text_height(f['value'],72,fact_w-20) for f in facts)+28
    graph_top = y + 88
    roots = [n for n in production.nodes if not n.parent_id and n.kind != 'boundary']
    row_count = max(n.row for n in roots) + 1
    pitch, card_w, card_h = 196, 400, 140
    graph_bottom = graph_top + (row_count-1)*pitch + 184 + 24
    panel_w = (width - 2 * margin - 48) // 2
    row_heights = []
    headings=[]
    for panel in plan.panels:
        heading=re.split(r'[｜|]',panel.heading,maxsplit=1)[0]
        headings.append(heading)
    callouts=[]
    for panel,copy in zip(plan.panels,production.callouts or [p.statement for p in plan.panels]):
        callouts.append(callout_copy(copy,panel))
    for i in range(0, len(plan.panels), 2):
        row_heights.append(max(88 + text_height(callouts[i+j],BODY_SIZE,panel_w) for j,p in enumerate(plan.panels[i:i+2])))
    panels_top = graph_bottom + 130
    footer_top = panels_top + sum(row_heights) + 18*len(row_heights) + 24
    source_lines=[]
    for source in resolved['sources']:
        label=source['label'].split('：')[-1]
        if len(label)>24:label=label[:23]+'…'
        source_lines.append(' · '.join(x for x in [source.get('id',''),label,source['date']] if x))
    sources='\n'.join(dict.fromkeys(source_lines))
    boundary_copy=plan.boundary.replace('AI辅助图解。','').replace('AI辅助图解','').strip()
    footer_h = text_height(boundary_copy,FOOTER_SIZE,width-2*margin)+text_height(plan.period,FOOTER_SIZE,width-2*margin)+text_height(sources,FOOTER_SIZE,width-2*margin)+120
    height = max(2000,footer_top+footer_h+24)
    footer_top = height-footer_h-24
    image = Image.new('RGB', (width, height), paper)
    draw = ImageDraw.Draw(image)

    def text(text, x, y, size, max_width, fill=ink):
        for line in wrap(text, size, max_width):
            draw.text((x, y), line, font=fonts[size], fill=fill, stroke_width=0)
            y += int(size * 1.38)
        return y

    draw.rectangle((0,0,16,height),fill=accent)
    draw.line((margin, 112, width-margin, 112), fill=line_color, width=2)
    text('友车科技  /  研究图解', margin, 52, 32, width-2*margin, accent)
    y = text(title_copy, margin, 144, TITLE_SIZE, width-2*margin)
    if subtitle_copy:y = text(subtitle_copy, margin, y+12, 36, width-2*margin, muted)
    draw.line((margin, y+20, margin, y+20+text_height(plan.thesis,44,width-2*margin-44)), fill=accent, width=6)
    y = text(plan.thesis, margin+28, y+20, 44, width-2*margin-44)+35
    if facts:
        for i,fact in enumerate(facts):
            next_y=text(fact['label'], margin+i*fact_w, y, 32, fact_w-20, muted)
            text(fact['value'], margin+i*fact_w, next_y+12, 72, fact_w-20, accent)
    draw.rounded_rectangle((margin-24,graph_top-88,width-margin+24,graph_bottom+106),radius=20,fill=white)
    text('关系图解', margin, graph_top-76, 32, 300, muted)
    boxes, positions = {}, {}
    col_pitch = (width-2*margin-card_w)//2
    for node in roots:
        x = margin + node.column*col_pitch
        top = graph_top + node.row*pitch
        node_h = 184 if node.kind == 'scope' else card_h
        boxes[node.id] = (x, top, x+card_w, top+node_h)
    for node in production.nodes:
        if node.parent_id:
            x1,y1,x2,y2 = boxes[node.parent_id]
            boxes[node.id] = (x1+28,y1+76,x2-28,y2-18)
    for node_id,box in boxes.items():
        x1,y1,x2,y2=box;positions[node_id]=((x1+x2)/2,(y1+y2)/2)

    main_ids={id for edge in production.edges if edge.kind=='request' for id in [edge.origin,edge.to]}
    node_sizes={}

    def draw_node(node):
        box=boxes[node.id];x1,y1,x2,y2=box
        primary=node.id in main_ids and not node.parent_id and node.kind!='scope'
        fill=(accent if node.kind=='policy' else ink) if primary else soft if node.kind=='scope' else white
        color=paper if primary else accent if node.kind in {'policy','stop'} else ink
        outline=accent if node.kind in {'policy','stop'} else line_color
        draw.rounded_rectangle(box,radius=12,fill=fill,outline=outline,width=3 if node.kind in {'policy','stop'} else 2)
        if node.kind=='stop':draw.line((x1+20,y1+24,x1+20,y2-24),fill=accent,width=5)
        size=44 if node.parent_id or node.kind=='scope' else 52
        lines=wrap(node.label,size,x2-x1-48)
        allowed_height=64 if node.kind=='scope' and not node.parent_id else y2-y1-24
        while len(lines)*int(size*1.28)>allowed_height and size>MIN_NODE_SIZE:
            size=max(s for s in fonts if MIN_NODE_SIZE<=s<size);lines=wrap(node.label,size,x2-x1-48)
        if len(lines)*int(size*1.28)>allowed_height:
            raise ValueError('主图标签无法按最小44像素排印，请缩短标签或减少嵌套内容')
        node_sizes[node.id]=size
        label_h=len(lines)*int(size*1.28)
        top=y1+8 if node.kind=='scope' else (y1+y2-label_h)/2
        for line in lines:
            line_w=draw.textlength(line,font=fonts[size]);draw.text(((x1+x2-line_w)/2,top),line,font=fonts[size],fill=color);top+=int(size*1.28)
    for node in production.nodes:
        if node.kind=='scope' and not node.parent_id:draw_node(node)
        if node.kind=='boundary':
            outer=(margin-24,graph_top-24,width-margin+24,graph_bottom-6)
            boxes[node.id]=outer
            for start,end in [((outer[0],outer[1]),(outer[2],outer[1])),((outer[2],outer[1]),(outer[2],outer[3])),((outer[2],outer[3]),(outer[0],outer[3])),((outer[0],outer[3]),(outer[0],outer[1]))]:
                length=math.dist(start,end)
                for offset in range(0,int(length),28):
                    a=offset/length;b=min(offset+16,length)/length
                    draw.line((start[0]+(end[0]-start[0])*a,start[1]+(end[1]-start[1])*a,start[0]+(end[0]-start[0])*b,start[1]+(end[1]-start[1])*b),fill=line_color,width=2)
            label_w=draw.textlength(node.label,font=fonts[32]);x=width-margin-label_w
            draw.rounded_rectangle((x-14,graph_top-77,x+label_w+14,graph_top-31),radius=8,fill=soft)
            text(node.label,x,graph_top-75,32,label_w+2,accent)

    node_map={node.id:node for node in production.nodes}
    paths = {edge.id:orthogonal_route(boxes,node_map,edge.origin,edge.to) for edge in production.edges if edge.kind=='request'}
    block_paths={}
    block_endpoints = {}
    for edge in production.edges:
        if edge.kind=='block':
            route=paths[edge.target_edge]
            segments=[(math.dist(a,b),a,b) for a,b in zip(route,route[1:])]
            _,a,b=max(segments,key=lambda s:s[0]);end=((a[0]+b[0])/2,(a[1]+b[1])/2)
            block_endpoints[edge.id]={'target_edge':edge.target_edge,'point':list(end),'segment':[list(a),list(b)]}
            points=orthogonal_route(boxes,node_map,edge.origin,point=end,reserved=[*paths.values(),*block_paths.values()],arrival_direction=0 if a[0]==b[0] else 1)
            block_paths[edge.id]=points
    for edge in production.edges:
        if edge.kind=='association':paths[edge.id]=orthogonal_route(boxes,node_map,edge.origin,edge.to,
            reserved=[*block_paths.values(),*paths.values()],avoid_crossings=True,
            bounds=(margin-12,graph_top-12,width-margin+12,graph_bottom-18))
    for edge in sorted(production.edges,key=lambda e:e.kind!='association'):
        color = muted if edge.kind=='association' else accent if edge.kind=='block' else ink
        if edge.kind=='block':
            draw.line(block_paths[edge.id],fill=color,width=5)
            end=block_endpoints[edge.id]['point'];a,b=block_endpoints[edge.id]['segment']
            if a[0]==b[0]:draw.line((end[0]-18,end[1],end[0]+18,end[1]),fill=accent,width=8)
            else:draw.line((end[0],end[1]-18,end[0],end[1]+18),fill=accent,width=8)
            continue
        points=paths[edge.id]
        if edge.kind=='association':
            for a,b in zip(points,points[1:]):
                length=math.dist(a,b)
                for offset in range(0,int(length),20):
                    start=offset/length;end=min(offset+10,length)/length
                    draw.line((a[0]+(b[0]-a[0])*start,a[1]+(b[1]-a[1])*start,a[0]+(b[0]-a[0])*end,a[1]+(b[1]-a[1])*end),fill=color,width=3)
        else:draw.line(points,fill=color,width=5)
        if edge.kind=='request':
            a,b=next((a,b) for a,b in reversed(list(zip(points,points[1:]))) if a!=b)
            angle=math.atan2(b[1]-a[1],b[0]-a[0]);size=16
            draw.polygon([b,(b[0]-size*math.cos(angle-.45),b[1]-size*math.sin(angle-.45)),(b[0]-size*math.cos(angle+.45),b[1]-size*math.sin(angle+.45))],fill=ink)
    for node in production.nodes:
        if node.kind!='boundary' and (node.kind!='scope' or node.parent_id):draw_node(node)
    # Only explain line types actually present. The note and full qualifications
    # remain in the evidence-bound design and image alt; the footer owns limits.
    legend_x=margin;legend_y=graph_bottom+35
    for kind,label in [('request','操作方向'),('association','关联支持'),('block','阻断入口')]:
        if not any(e.kind==kind for e in production.edges):continue
        color=accent if kind=='block' else ink if kind=='request' else muted
        if kind=='association':
            for dx in [0,20,40]:draw.line((legend_x+dx,legend_y+18,legend_x+dx+10,legend_y+18),fill=color,width=3)
        else:
            draw.line((legend_x,legend_y+18,legend_x+54,legend_y+18),fill=color,width=4)
            if kind=='block':draw.line((legend_x+54,legend_y+7,legend_x+54,legend_y+29),fill=color,width=5)
            else:draw.polygon([(legend_x+54,legend_y+18),(legend_x+40,legend_y+10),(legend_x+40,legend_y+26)],fill=color)
        text(label,legend_x+72,legend_y,32,220,muted);legend_x+=340
    statuses={'observed':'披露','proposal':'来源建议','inference':'分析建议','unknown':'待验证'}
    y=panels_top
    for i in range(0,len(plan.panels),2):
        for j,panel in enumerate(plan.panels[i:i+2]):
            x=margin+j*(panel_w+48)
            draw.line((x,y,x+panel_w,y),fill=line_color,width=2)
            heading_end=text(headings[i+j],x,y+18,36,panel_w-190)
            status=statuses[panel.status];status_w=draw.textlength(status,font=fonts[28])
            draw.rounded_rectangle((x+panel_w-status_w-24,y+16,x+panel_w,y+60),radius=6,fill=soft)
            text(status,x+panel_w-status_w-12,y+17,28,status_w+2,accent)
            text(callouts[i+j],x,max(y+78,heading_end+12),BODY_SIZE,panel_w)
        y+=row_heights[i//2]+18
    draw.line((margin,footer_top,width-margin,footer_top),fill=line_color,width=2)
    y=text(boundary_copy,margin,footer_top+12,32,width-2*margin,muted)
    y=text(plan.period,margin,y+12,32,width-2*margin,muted)
    y=text(sources,margin,y+12,32,width-2*margin,muted)
    text('AI辅助图解 · 依据输入报告整理',margin,y+12,32,width-2*margin,accent)
    image.save(output,format='PNG',optimize=True)
    return {'width':width,'height':height,'publication_standard':'legacy-structure-1.0','node_font_sizes':node_sizes,
            'typography':{'title':TITLE_SIZE,'body':BODY_SIZE,'footer':FOOTER_SIZE},'boxes':{key:list(value) for key,value in boxes.items()},
            'edge_paths':{key:[list(p) for p in value] for key,value in paths.items()},'block_endpoints':block_endpoints,
            'block_paths':{key:[list(p) for p in value] for key,value in block_paths.items()}}
