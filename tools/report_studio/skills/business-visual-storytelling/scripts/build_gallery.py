"""Build original, explicitly synthetic chart specimens; no external assets."""
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT/'references/catalog.json').read_text())['recipes']
INK, ACCENT, MUTED, GRID = '#252824','#B45F36','#77766f','#dcd6ca'

def text(x,y,s,size=12,color=INK,anchor='start'):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" text-anchor="{anchor}">{html.escape(str(s))}</text>'
def line(x1,y1,x2,y2,color=GRID,width=1,dash=''):
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}" stroke-dasharray="{dash}"/>'
def circle(x,y,r=5,color=ACCENT):
    return f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}"/>'
def rect(x,y,w,h,color):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{color}"/>'
def svg(body,label):
    return f'<div class="plot" tabindex="0" aria-label="图形，窄屏可横向滚动"><svg viewBox="0 0 520 285" role="img" aria-label="{html.escape(label)}"><title>{html.escape(label)}</title>{body}</svg></div>'

def dumbbell():
    s=text(24,25,'交付等待 / 天',12,MUTED)+text(495,25,'○ 6月   ● 9月',12,MUTED,'end')
    for v in [0,5,10,15]:
        x=95+v*23;s+=line(x,45,x,233)+text(x,258,v,11,MUTED,'middle')
    for i,(a,b) in enumerate([(12,9),(8,8),(10,13)]):
        y=80+i*64;s+=text(24,y+4,['甲店','乙店','丙店'][i])+line(95+a*23,y,95+b*23,y,ACCENT,3)
        s+=f'<circle cx="{95+a*23}" cy="{y}" r="6" fill="#fbf9f4" stroke="{INK}" stroke-width="1.5"/>'+circle(95+b*23,y,6)
        s+=text(95+a*23,y-14,a,12,INK,'middle')+text(95+b*23,y+25,b,12,ACCENT,'middle')
    return s

def bridge():
    vals=[60,25,-10,-5,70];labels=['起点','量增','费用','其他','终点'];s=text(24,25,'贡献分解 / 示例单位',12,MUTED);zero=225;scale=2
    for v in [0,20,40,60,80]:s+=line(45,zero-v*scale,493,zero-v*scale)+text(32,zero-v*scale+4,v,10,MUTED,'end')
    running=60
    for i,(v,label) in enumerate(zip(vals,labels)):
        x=70+i*87
        if i in (0,4):low,high=0,v
        else:low,high=sorted([running,running+v]);running+=v
        s+=rect(x,zero-high*scale,44,(high-low)*scale,INK if i in (0,4) else ACCENT if v>0 else '#95958b')
        s+=text(x+22,zero-high*scale-9,str(v) if i in (0,4) else f'{v:+}',12,INK,'middle')+text(x+22,252,label,12,INK,'middle')
        if i<4:s+=line(x+44,zero-running*scale,x+87,zero-running*scale,MUTED,1,'3 3')
    return s

def intervals():
    s=text(24,25,'时长差 / 天 · 示例上下界，非置信区间',12,MUTED)
    for v in [-4,-2,0,2,4]:
        x=285+v*35;s+=line(x,50,x,230,INK if v==0 else GRID,1,'4 4' if v==0 else '')+text(x,258,v,11,MUTED,'middle')
    for i,(lo,mid,hi) in enumerate([(-3.5,-2,-.5),(-1,.5,2),(1,2.5,4)]):
        y=85+i*61;s+=text(24,y+4,['方案甲','方案乙','方案丙'][i])+line(285+lo*35,y,285+hi*35,y,ACCENT,3)+circle(285+mid*35,y,6)
        for e in [lo,hi]:s+=line(285+e*35,y-6,285+e*35,y+6,ACCENT,1.5)
    return s

def scatter():
    s=text(24,25,'毛利率 / %',12,MUTED)+rect(70,50,385,160,'#eee8dc')
    for v in [5,10,15,20]:
        y=230-v*8;s+=line(70,y,455,y)+text(57,y+4,v,11,MUTED,'end')
    for x,y,name,hi in [(20,8,'甲店',False),(35,15,'乙店',True),(60,12,'丙店',False),(80,20,'丁店',False)]:
        px=70+x*4;py=230-y*8;s+=circle(px,py,7,ACCENT if hi else INK)+text(px+12,py+4,name,12,ACCENT if hi else INK)
    s+=line(70,230,455,230,INK)+text(455,272,'业务量 / 示例百单',12,MUTED,'end')
    for v in [0,20,40,60,80]:s+=text(70+v*4,250,v,11,MUTED,'middle')
    return s

def cohort():
    s=text(24,25,'同批次留存 / %',12,MUTED);values=[[100,70,50,40],[100,80,60,None],[100,85,None,None],[100,None,None,None]]
    for j in range(4):s+=text(164+j*83,53,f'M{j}',12,MUTED,'middle')
    for i,row in enumerate(values):
        s+=text(30,87+i*44,f'{i+1}月批次',12)
        for j,v in enumerate(row):
            x=125+j*83;y=67+i*44
            if v is None:s+=rect(x,y,78,38,'#eae7df')+text(x+39,y+25,'—',13,MUTED,'middle')
            else:
                t=v/100;rgb=tuple(round(a+(b-a)*t) for a,b in zip((246,239,227),(180,95,54)))
                s+=rect(x,y,78,38,'rgb'+str(rgb))+text(x+39,y+25,str(v),13,'white' if v>=70 else INK,'middle')
    return s+text(125,265,'— 尚未到观察期；未填作零',12,MUTED)

def mix():
    s=text(24,25,'市场总量 × 内部结构',12,MUTED);x=55;totals=[50,30,20];shares=[.7,.4,.6]
    for i,(total,share) in enumerate(zip(totals,shares)):
        w=total*4;y=60;s+=rect(x,y,w,160*share,ACCENT)+rect(x,y+160*share,w,160*(1-share),'#a2a297')
        s+=text(x+w/2,50,f'{total}单位',12,MUTED,'middle')+text(x+w/2,90,f'{int(share*100)}%',14,'white','middle')+text(x+w/2,245,['市场甲','市场乙','市场丙'][i],12,INK,'middle');x+=w+3
    return s+text(55,273,'列宽＝规模；铜橙高度＝同一类别份额',12,MUTED)

def multiples():
    s=text(24,25,'共同尺度 / 示例销量 0—20',12,MUTED)
    series=[[4,8,7,12,14,17],[12,10,8,9,8,6],[3,5,None,7,11,10],[7,8,8,9,10,12]]
    for n,values in enumerate(series):
        x=40+(n%2)*253;y=60+(n//2)*110;s+=text(x,y-8,['市场甲','市场乙','市场丙','市场丁'][n],12)
        for v in [0,10,20]:s+=line(x,y+70-v*3,x+190,y+70-v*3)+text(x-8,y+74-v*3,v,9,MUTED,'end')
        prev=None
        for i,v in enumerate(values):
            if v is None:prev=None;continue
            px=x+i*38;py=y+70-v*3
            if prev:s+=line(*prev,px,py,ACCENT,2)
            s+=circle(px,py,2.5);prev=(px,py)
        s+=text(x,y+87,'4月',10,MUTED)+text(x+190,y+87,'9月',10,MUTED,'end')
    return s

def distribution():
    s=text(24,25,'每个点＝一条样本 / 等待天数',12,MUTED)
    vals=[[2,3,4,4,5,5,5,6,6,7,8,9,18],[3,4,4,5,5,6,6,7,7,8,9,11,12]]
    for v in [0,5,10,15,20]:s+=line(90+v*18,50,90+v*18,230)+text(90+v*18,256,v,11,MUTED,'middle')
    for i,row in enumerate(vals):
        y=90+i*90;seen={};s+=text(24,y+4,['甲店','乙店'][i])
        from statistics import quantiles,median
        q1,_,q3=quantiles(row,n=4,method='inclusive'); med=median(row);iqr=q3-q1
        inside=[v for v in row if q1-1.5*iqr<=v<=q3+1.5*iqr]
        s+=line(90+min(inside)*18,y+33,90+max(inside)*18,y+33,MUTED,1)
        s+=f'<rect x="{90+q1*18}" y="{y+27}" width="{(q3-q1)*18}" height="12" fill="#F5F1E9" stroke="{MUTED}"/>'
        s+=line(90+med*18,y+26,90+med*18,y+40,INK,2)
        for v in row:
            k=seen.get(v,0);seen[v]=k+1;offset=[0,-14,14,-28,28][k]
            s+=circle(90+v*18,y+offset,5.2,ACCENT if v>=15 else '#77796e')
    return s+text(420,70,'长尾',12,ACCENT)+text(90,280,'每组13条；须端取箱体外1.5倍箱长内的极值',10,MUTED)

samples=[('paired_change','谁改善了，谁变慢了？',dumbbell),('result_bridge','把结果拆成可核对的贡献',bridge),('relationship','规模与收益，放到同一张图看',scatter),('shared_trends','四个市场，一把共同的尺',multiples),('interval_dot','差异之外，还要看不确定性',intervals),('distribution','均值之外，长尾在哪里？',distribution),('cohort','同龄比较，才看得清留存',cohort),('size_mix','同时看规模与市场结构',mix)]
css='''*{box-sizing:border-box}body{margin:0;background:#F5F1E9;color:#252824;font-family:system-ui,-apple-system,"PingFang SC",sans-serif}main{max-width:1260px;margin:auto;padding:44px 42px 80px}.eyebrow{font-size:12px;letter-spacing:.16em;color:#77766f}header{padding:20px 0 28px;border-bottom:1px solid #cfc7b9}h1{font:500 clamp(30px,4vw,53px)/1.3 "Songti SC",serif;margin:22px 0}h1 em{font-style:normal;color:#B45F36}header p{max-width:850px;line-height:1.9;color:#66675f}nav{display:flex;gap:12px;flex-wrap:wrap;margin:26px 0}button{font:inherit;font-size:13px;background:transparent;border:1px solid #cfc7b9;padding:10px 16px;cursor:pointer;color:inherit}button[aria-pressed=true]{background:#252824;color:#fff}button:focus-visible,a:focus-visible{outline:2px solid #B45F36;outline-offset:4px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:30px}.specimen{background:#fbf9f4;padding:25px;border-top:2px solid #252824;min-width:0}.meta{display:flex;justify-content:space-between;gap:12px;color:#77766f;font-size:11px}.status{color:#B45F36}h2{font:500 25px/1.5 "Songti SC",serif;margin:14px 0 6px}.question{font-size:13px;color:#77766f;line-height:1.65;margin:0 0 14px}.plot{overflow-x:auto;max-width:100%;scrollbar-width:thin}svg{width:100%;height:auto;display:block;font-family:system-ui,sans-serif;font-variant-numeric:tabular-nums;border-top:1px solid #e6dfd3;border-bottom:1px solid #e6dfd3;padding-top:8px}.note{font-size:12px;line-height:1.8;color:#66675f}.note strong{font-weight:600;color:#252824}details{font-size:12px;line-height:1.85}summary{cursor:pointer;color:#B45F36;min-height:36px;padding:8px 0}details p{margin:8px 0}.source{font-size:10px;color:#77766f;margin-top:14px}.principles{margin-top:42px;padding-top:24px;border-top:1px solid #cfc7b9}.principles p{max-width:930px;line-height:1.9;font-size:14px}.principles a{color:#B45F36}svg.reveal{animation:appear .7s ease both}@keyframes appear{from{opacity:.2;clip-path:inset(0 100% 0 0)}to{opacity:1;clip-path:inset(0)}}[hidden]{display:none!important}@media(max-width:700px){main{padding:24px 18px}.grid{grid-template-columns:1fr;gap:22px}.specimen{padding:18px}h2{font-size:23px}svg{min-width:460px}}@media(prefers-reduced-motion:reduce){svg.reveal{animation:none}}@media print{nav{display:none}.grid{display:block}.specimen{break-inside:avoid;margin-bottom:24px}}'''
parts=[]
for id,title,fn in samples:
    r=next(r for r in CATALOG if r['id']==id);available=r['engine']['kind'] is not None
    fields=''.join(f'<p><strong>{label}</strong> {html.escape(r[key])}</p>' for label,key in [('需要的数据','requires'),('怎样读图','encoding'),('何时不适合','avoid'),('数据不足时','fallback')])
    parts.append(f'''<article class="specimen" data-status="{'ready' if available else 'reserve'}"><div class="meta"><span>{html.escape(r['name'])}</span><span class="status">{'网页已有对应图种' if available else '配方储备 · 未接入报告引擎'}</span></div><h2>{title}</h2><p class="question">{html.escape(r['question'])}</p>{svg(fn(),title+'。合成示例，不是经营数据。')}<p class="note"><strong>表达重点</strong> {html.escape(r['encoding'])}</p><details><summary>适用条件与误用边界</summary>{fields}</details><p class="source">数据：合成教学示例 · 非友车科技经营结果 · 图形原创绘制</p></article>''')
page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>友车科技 · 商业研究图形词典</title><style>'''+css+'''</style><main><header><div class="eyebrow">友车科技 / 图形表达研究 · 2026.10</div><h1>先想清楚问题，<br><em>再让图形给出解释。</em></h1><p>沿用暖纸、石墨与铜橙的研究风格。这里展示 8 种表达样张，完整技能包含 18 项问题配方。每种图形都有数据门槛；新颖服务于理解，不替代证据。</p><p><strong>本页所有数值均为合成示例。</strong>“配方储备”表示样式已可预览，报告引擎尚未支持自动生成该图种。</p></header><nav aria-label="筛选图形"><button data-filter="all" aria-pressed="true">全部样张</button><button data-filter="ready" aria-pressed="false">网页已有图种</button><button data-filter="reserve" aria-pressed="false">专业扩展配方</button><button id="replay">重播阅读动效</button></nav><section class="grid">'''+''.join(parts)+'''</section><section class="principles"><div class="eyebrow">右上角内容图 / 同一风格，按材料选表达</div><h2>固定阅读标准，开放视觉构图。</h2><p>结构和功能用注释剖面；条件改变用同位对照；数量差距用有尺度的数据图；范围约束用命名边界。主视觉负责解释一个核心问题，旁注保留证据，对友车科技的启发单独标明分析建议。保留精细线描与层次，不固定汽车、港口或集合圆。</p><p>原始参考：<a href="https://github.com/Financial-Times/chart-doctor/blob/main/visual-vocabulary/README.md">金融时报选图方法</a> · <a href="https://ig.ft.com/ai-data-centres/">金融时报结构解释案例</a> · <a href="https://github.com/TheEconomist/graphic-detail-data/tree/master/data/2019-03-23_happiness-economics">经济学人二维关系案例</a> · <a href="https://reuters-graphics.github.io/newsroom-datawrapper-guide/getting-started/making-your-first-chart/">路透出版规范</a></p><p>这些是表达方法参考；图形、教学示例与铜橙样式由本项目独立制作。历史媒体案例不作为当前经营事实。</p></section></main><script>const buttons=[...document.querySelectorAll('[data-filter]')];buttons.forEach(b=>b.onclick=()=>{buttons.forEach(x=>x.setAttribute('aria-pressed',String(x===b)));document.querySelectorAll('.specimen').forEach(x=>x.hidden=b.dataset.filter!=='all'&&x.dataset.status!==b.dataset.filter)});document.getElementById('replay').onclick=()=>document.querySelectorAll('.specimen:not([hidden]) svg').forEach(x=>{x.classList.remove('reveal');void x.getBoundingClientRect();x.classList.add('reveal')});</script></html>'''
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(page)
    print(a.output)
