/* All variable text is assigned through textContent. SVG geometry is local artwork. */
window.ReportVisuals = (() => {
  const ns = 'http://www.w3.org/2000/svg';
  const number=value=>Number(value).toLocaleString('zh-CN',{maximumFractionDigits:15});
  const el = (tag, cls, text) => {const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
  const svgEl = (tag, attrs) => {const n=document.createElementNS(ns,tag);for(const [key,value] of Object.entries(attrs))n.setAttribute(key,String(value));return n;};
  const scalar = (text,unit='') => {let value=text.trim();if(unit&&value.endsWith(unit))value=value.slice(0,-unit.length).trim();return /^[<>≤≥≈约]?\s*[+-]?\d[\d,]*(?:\.\d+)?$/.test(value)?Number(value.replace(/[<>≤≥≈约,\s]/g,'')):null;};
  const columnTitle = (column,rows,index) => column.label==='材料原句'&&rows.some(r=>r.cells[index].quote&&!r.cells[index].quote.includes(r.cells[index].value))?'材料要点':column.label;
  const withUnit = (value,unit) => {const text=String(value).trim();return unit&&unit!=='各格注明'&&!text.endsWith(unit)?text+' '+unit:text;};
  const splitRoadmap = c => {const coarse=c.periods.filter(p=>/^\d{4}$/.test(p)&&c.periods.some(other=>other!==p&&other.startsWith(p)));return {periods:c.periods.filter(p=>!coarse.includes(p)),dated:c.milestones.filter(m=>!coarse.includes(m.period)),undated:c.milestones.filter(m=>coarse.includes(m.period))};};
  const lineLayout = points => {const monthly=points.every(p=>/^\d{4}-(0[1-9]|1[0-2])$/.test(p.label)),yearly=points.every(p=>/^\d{4}$/.test(p.label));let times=points.map((p,i)=>monthly?Number(p.label.slice(0,4))*12+Number(p.label.slice(5)):yearly?Number(p.label):i);const temporal=(monthly||yearly)&&times.every((t,i)=>!i||t>times[i-1]);if(!temporal)times=points.map((_,i)=>i);const span=times.at(-1)-times[0]||1,positions=times.map(t=>(t-times[0])/span),segments=[];for(let i=0;i<times.length;i++){if(!i||(temporal&&times[i]-times[i-1]>1))segments.push([]);segments.at(-1).push(i);}return {positions,segments,temporal};};
  const compareCell = (cell,baseline,column) => {if(!column.direction||column.direction==='none'||cell.comparable===false||baseline?.comparable===false||!baseline||/[<>≤≥≈约]/.test(cell.value+baseline.value))return '';const a=scalar(cell.value,column.unit),b=scalar(baseline.value,column.unit);if(a===null||b===null)return '';if(a===b)return 'equal';return (column.direction==='higher'?a>b:a<b)?'better':'worse';};
  const displayPeriod = text => {const months=['January','February','March','April','May','June','July','August','September','October','November','December'];const match=/^([A-Za-z]+) (\d{4})$/.exec(text);return match&&months.includes(match[1])?match[2]+'年'+(months.indexOf(match[1])+1)+'月':text;};
  const sparseRoadmap = milestones => {const lanes=new Set(milestones.map(m=>m.lane)).size;return lanes>=5&&milestones.length/lanes<1.7;};
  const plotBounds = values => {const nice=v=>{if(!v)return 1;const power=10**Math.floor(Math.log10(v)),fraction=v/power;return [1,2,2.5,5,10].find(x=>x>=fraction)*power;};const low=Math.min(0,...values),high=Math.max(0,...values);return [low<0?-nice(-low*1.04):0,high>0?nice(high*1.04):low<0?0:1];};
  const contextFacts = section => {const visuals=[...(section.visuals||[]),...(section.chart&&section.chart.kind!=='none'?[section.chart]:[])];for(const v of visuals){const fact=(label,value,p)=>({label,value,quote:p.quote,source_ids:p.source_ids?.length?p.source_ids:v.source_ids||[]});let facts=[];
    if(v.kind==='car')facts=v.metrics;
    else if(v.kind==='scatter'){const p=v.points.find(x=>x.emphasis);if(p)facts=[fact(p.label+' · '+v.y_label,p.y+' '+v.y_unit,p),fact(p.label+' · '+v.x_label,p.x+' '+v.x_unit,p)];}
    else if(v.kind==='qualified_dot')facts=v.points.map(p=>fact(p.label,ReportQualified.label(p,v.unit),p));
    else if(v.kind==='worldmap')facts=v.places.map(p=>fact(p.label,p.value,p));
    else if(v.kind==='matrix'){const row=v.rows.find(r=>r.emphasis);if(row)facts=v.columns.flatMap((col,i)=>col.direction&&col.direction!=='none'&&row.cells[i].quote?[fact(row.label+' · '+col.label,withUnit(row.cells[i].value,col.unit),row.cells[i])]:[]);}
    else if(v.kind==='multiseries')facts=v.series.flatMap(s=>{const p=s.points.filter(Boolean).at(-1);return p?[fact(s.label+' · '+p.label,number(p.value)+' '+v.unit,p)]:[];});
    else if(v.kind==='comparison')facts=v.rows.map(row=>fact(row.label+' · '+v.after_label,number(row.after.value)+' '+v.unit,row.after));
    else if(v.kind==='waterfall')facts=[fact(v.start.label,number(v.start.value)+' '+v.unit,v.start),fact(v.end.label,number(v.end.value)+' '+v.unit,v.end)];
    else if(v.kind==='targets')facts=v.items.slice(0,3).map(p=>fact('建议 · '+p.label,p.baseline+' → '+p.target+' '+p.unit,p));
    else if(v.kind==='bar'||v.kind==='line')facts=(v.kind==='line'?v.points.slice(-2):v.points).map(p=>fact(p.label,number(p.value)+' '+v.unit,p));
    if(facts.length)return facts.slice(0,3);}return [];};
  function carSvg() {
    const svg=svgEl('svg',{viewBox:'0 0 1000 450',class:'vehicle-svg','aria-hidden':'true'});
    const ground=svgEl('path',{d:'M65 365H940',class:'vehicle-ground'});svg.append(ground);
    const wheels=svgEl('g',{class:'vehicle-wheels'});
    for(const x of [285,755]){wheels.append(svgEl('circle',{cx:x,cy:338,r:69,class:'vehicle-tire'}),svgEl('circle',{cx:x,cy:338,r:39,class:'vehicle-rim'}));
      for(let i=0;i<5;i++){const a=i*Math.PI*2/5;wheels.append(svgEl('path',{d:`M${x} 338L${x+31*Math.cos(a)} ${338+31*Math.sin(a)}`,class:'vehicle-spoke'}));}}
    const chassis=svgEl('g',{class:'vehicle-chassis'});chassis.append(svgEl('path',{d:'M156 307H838L824 347H170Z',class:'vehicle-underbody'}));
    const body=svgEl('g',{class:'vehicle-body'});body.append(svgEl('path',{d:'M132 289L155 224L254 205L340 111Q348 98 372 98H669Q688 98 699 116L763 204L853 225L884 273V326H831Q823 258 755 258Q687 258 678 326H362Q353 258 285 258Q216 258 207 326H130Z',class:'vehicle-shell'}));
    body.append(svgEl('path',{d:'M284 201L354 122H463V201ZM486 122H650Q665 122 675 139L719 201H486Z',class:'vehicle-window'}));
    body.append(svgEl('path',{d:'M474 109V305M736 214V299M370 216V304M385 226H412M630 226H657M142 277H192M830 250H870',class:'vehicle-detail'}));
    body.append(svgEl('rect',{x:150,y:237,width:27,height:26,rx:6,class:'vehicle-light'}),svgEl('rect',{x:849,y:237,width:17,height:26,rx:4,class:'vehicle-tail'}));
    const roof=svgEl('g',{class:'vehicle-roof'});roof.append(svgEl('path',{d:'M364 87H657M417 77H610',class:'vehicle-detail'}),svgEl('rect',{x:446,y:65,width:130,height:13,rx:4,class:'vehicle-roof-bar'}));
    const battery=svgEl('g',{class:'vehicle-battery'});battery.append(svgEl('rect',{x:390,y:312,width:245,height:29,rx:3,class:'vehicle-pack'}));
    for(let i=0;i<9;i++)battery.append(svgEl('path',{d:`M${405+i*25} 318V335`,class:'vehicle-pack-line'}));
    svg.append(chassis,battery,body,wheels,roof);return svg;
  }
  function render(c,env){
    const frame=el('figure','chart visual-'+c.kind);frame.dataset.kind=c.kind;
    const head=el('div','chart-head');head.append(el('h3','',c.title));frame.append(head);
    const note=c.note?el('p','visual-note',c.note):null;
    const content=el('div','visual-content');frame.append(content);
    const show=(label,value,quote,ids=[])=>env.evidence(label,value,quote,ids.length?ids:(c.source_ids||[]));
    if(['contrast','membership','evidence_strip'].includes(c.kind)){
      content.append(ReportQualitative.render(c,{el,svgEl,show}));
    }else if(c.kind==='qualified_dot'){
      content.append(ReportQualified.render(c,{el,show}));
    }else if(c.kind==='multiseries'){
      content.append(ReportSeries.render(c,{el,svgEl,show}));
    }else if(c.kind==='matrix'){
      const wrap=el('div','matrix-scroll');wrap.tabIndex=0;wrap.setAttribute('aria-label',c.title+'；可横向滚动');
      const table=el('table','peer-matrix');const caption=el('caption','','浅色为重点行；点击单元格查引文，点击列标题排序。');table.append(caption);
      const header=el('thead'),tr=el('tr');tr.append(el('th','','主体'));const body=el('tbody');
      const subjects=c.rows.filter(r=>r.emphasis),subject=subjects.length===1?subjects[0]:null;
      const draw=rows=>{body.replaceChildren();for(const row of rows){const line=el('tr',row.emphasis?'subject-row':'');line.dataset.itemIndex=String(c.rows.indexOf(row));const name=el('th','',row.label);name.scope='row';line.append(name);row.cells.forEach((cell,i)=>{const comparison=!row.emphasis&&subject?compareCell(cell,subject.cells[i],c.columns[i]):'';const td=el('td',comparison?'comparison-'+comparison:'');if(cell.quote){const b=el('button','matrix-cell',cell.value);if(comparison)b.append(el('small','comparison-label',comparison==='better'?'▲ 较优':comparison==='worse'?'▼ 较弱':'＝ 相同'));else if(cell.comparable===false&&['higher','lower'].includes(c.columns[i].direction)&&c.columns[i].unit&&/\d/.test(cell.value))b.append(el('small','comparison-label','不参与比较'));b.onclick=()=>show(row.label+' · '+c.columns[i].label,withUnit(cell.value,c.columns[i].unit),cell.quote,cell.source_ids);td.append(b);}else td.append(el('span','missing-value',cell.value));line.append(td);});body.append(line);}};
      c.columns.forEach((col,i)=>{const th=el('th');th.scope='col';const b=el('button','column-sort');b.append(el('span','',columnTitle(col,c.rows,i)),el('small','',col.unit));let descending=true;b.onclick=()=>{header.querySelectorAll('[aria-sort]').forEach(n=>n.removeAttribute('aria-sort'));th.setAttribute('aria-sort',descending?'descending':'ascending');const ordered=[...c.rows].sort((a,z)=>{const av=scalar(a.cells[i].value,col.unit),zv=scalar(z.cells[i].value,col.unit);if(av===null&&zv===null)return a.cells[i].value.localeCompare(z.cells[i].value,'zh');if(av===null)return 1;if(zv===null)return -1;return descending?zv-av:av-zv;});draw(ordered);descending=!descending;};th.append(b);tr.append(th);});header.append(tr);table.append(header,body);draw(c.rows);wrap.append(table);content.append(wrap);
      if(subject&&c.columns.some(col=>col.direction&&col.direction!=='none')){const legend=el('div','comparison-legend');legend.append(el('span','better-key','▲ 较优'),el('span','worse-key','▼ 较弱'),el('span','','相对'+subject.label+'，仅比较方向明确且口径相同的指标；不代表综合排名。'));for(const col of c.columns.filter(x=>x.direction&&x.direction!=='none'))legend.append(el('small','',col.label+'：'+col.comparison_note));content.append(legend);}
    }else if(c.kind==='comparison'){
      const domain=plotBounds(c.rows.flatMap(r=>[r.before.value,r.after.value]));
      if(c.rows.some(r=>[r.before.value,r.after.value].some(v=>number(v).length>9)))frame.classList.add('long-values');
      const position=value=>8+(value-domain[0])/(domain[1]-domain[0])*84;
      const legend=el('div','comparison-periods');legend.append(el('span','before-key','○ '+c.before_label),el('span','after-key','● '+c.after_label),el('span','','单位：'+c.unit));if(domain[0]<0&&domain[1]>0)legend.append(el('span','','竖虚线：零轴'));content.append(legend);
      for(const row of c.rows){const line=el('div','observation-row'+(row.before.value===row.after.value?' same-values':''));line.append(el('strong','observation-label',row.label));const track=el('div','observation-track');track.setAttribute('aria-label',row.label+'，同一数值尺度');if(domain[0]<0&&domain[1]>0){const zero=el('span','observation-zero');zero.style.left=position(0)+'%';zero.title='零轴';track.append(zero);}const a=position(row.before.value),b=position(row.after.value),connector=el('span','observation-connector');connector.style.left=Math.min(a,b)+'%';connector.style.width=Math.abs(a-b)+'%';track.append(connector);
        for(const key of ['before','after']){const point=row[key],dot=el('button','observation-dot '+key);dot.style.left=position(point.value)+'%';dot.setAttribute('aria-label',row.label+' · '+point.label+'：'+point.value+' '+c.unit);dot.onclick=()=>show(row.label+' · '+point.label,point.value+' '+c.unit,point.quote,point.source_ids);track.append(dot);}
        const values=el('div','observation-values');for(const key of ['before','after']){const point=row[key],button=el('button',key,number(point.value));button.setAttribute('aria-label',row.label+' · '+point.label+'：'+point.value+' '+c.unit);button.onclick=()=>show(row.label+' · '+point.label,point.value+' '+c.unit,point.quote,point.source_ids);values.append(button);if(key==='before')values.append(el('span','','→'));}line.append(track,values);content.append(line);}
      const axis=el('div','observation-axis'),scale=el('div','observation-scale');scale.append(el('span','',number(domain[0])),el('span','','全图统一尺度'),el('span','',number(domain[1])));axis.append(scale);content.append(axis);
    }else if(c.kind==='targets'){
      content.append(el('div','target-legend','○ 现状　● 原报告建议目标 · 每行独立尺度，目标不代表已完成'));
      for(const item of c.items){const row=el('button','target-row');row.setAttribute('aria-label',`${item.label}：现状${item.baseline}，建议目标${item.target}${item.unit}`);const label=el('span','target-name',item.label);label.append(el('small','',item.unit));
        const track=el('span','target-track'),a=scalar(item.baseline,item.unit),b=scalar(item.target,item.unit);
        if(a!==null&&b!==null){const min=Math.min(0,a,b),max=Math.max(0,a,b),range=max-min||1,ax=8+(a-min)/range*84,bx=8+(b-min)/range*84;const line=el('span','target-connector');line.style.left=Math.min(ax,bx)+'%';line.style.width=Math.abs(ax-bx)+'%';const from=el('span','target-dot baseline'),to=el('span','target-dot planned');from.style.left=ax+'%';to.style.left=bx+'%';track.append(line,from,to);}else track.append(el('span','target-unknown',/未|未知|待|—/.test(item.baseline)?'现状缺失 · 保留空缺':'保留原文口径 · 见右侧数值'));
        const values=el('span','target-values');values.append(el('span','baseline-value',item.baseline),el('span','target-arrow',item.direction==='down'?'↘':item.direction==='up'?'↗':'→'),el('strong','',item.target));row.append(label,track,values);row.onclick=()=>show(item.label,`现状 ${item.baseline} → 建议目标 ${item.target} ${item.unit}`,item.quote,item.source_ids);content.append(row);
      }
    }else if(c.kind==='roadmap'){
      content.append(el('p','roadmap-legend','虚线 = 建议规划　实线 = 材料已记载发生；未给出时长的事件只画里程碑'));
      const {periods,dated,undated}=splitRoadmap(c);
      const eventButton=item=>{const button=el('button','milestone '+item.status);button.append(el('span','milestone-status',item.status==='proposal'?'建议规划':'材料记录'),el('span','',item.label));if(item.end_period)button.append(el('small','',item.period+' → '+item.end_period));button.onclick=()=>show(item.lane+' · '+item.period,item.label+' · '+(item.status==='proposal'?'建议规划，未视为实施结果':'材料记载，仍待核验'),item.quote,item.source_ids);return button;};
      if(dated.length){const wrap=el('div','roadmap-scroll');wrap.tabIndex=0;wrap.setAttribute('aria-label',c.title+'；时间路线可横向滚动');const grid=el('div','roadmap-grid');grid.style.setProperty('--periods',periods.length);
        grid.append(el('div','roadmap-corner','事项 / 时间'));for(const p of periods)grid.append(el('div','period-label',displayPeriod(p)));
        const lanes=[...new Set(dated.map(x=>x.lane))];lanes.forEach((lane,li)=>{const name=el('div','lane-label',lane);name.style.gridRow=li+2;name.style.gridColumn=1;grid.append(name);
          periods.forEach((p,i)=>{const cell=el('div','roadmap-cell');cell.style.gridRow=li+2;cell.style.gridColumn=i+2;for(const item of dated.filter(x=>x.lane===lane&&x.period===p))cell.append(eventButton(item));grid.append(cell);});});wrap.append(grid);
        const compact=el('div','roadmap-compact');for(const p of periods){const events=dated.filter(m=>m.period===p);if(!events.length)continue;const group=el('div','roadmap-phase');group.append(el('strong','phase-date',displayPeriod(p)));for(const item of events){const card=el('div','phase-event');card.append(el('span','phase-lane',item.lane),eventButton(item));group.append(card);}compact.append(group);}
        let useCompact=sparseRoadmap(dated)||periods.length>6;const toggle=el('button','roadmap-toggle');const update=()=>{compact.hidden=!useCompact;wrap.hidden=useCompact;toggle.textContent=useCompact?'切换为分类泳道':'切换为紧凑时间线';toggle.setAttribute('aria-label',toggle.textContent);};toggle.onclick=()=>{useCompact=!useCompact;update();};update();content.append(toggle,compact,wrap);}
      if(undated.length){const window=el('div','roadmap-undated');window.append(el('p','roadmap-legend','年内窗口 · 月份未定，不参与半年或月份的先后排序'));for(const item of undated){const card=el('div','undated-card');card.append(el('strong','',item.period+' · '+item.lane),eventButton(item));window.append(card);}content.append(window);}
    }else if(c.kind==='waterfall'||c.kind==='mechanism'){
      content.append(window.ReportAnalytical.render(c,{el,svgEl,show}));
    }else if(c.kind==='scatter'){
      content.append(window.ReportScatter.render(c,{el,svgEl,show}));
    }else if(c.kind==='worldmap'){
      const geography=window.ReportGeography;if(!geography){content.append(el('p','','地图底图不可用，保留市场证据列表。'));}
      const list=el('div','market-list');list.style.setProperty('--market-cols',c.places.length===4?2:Math.min(3,c.places.length));let svg;if(geography){svg=svgEl('svg',{viewBox:'0 0 720 300',class:'world-map',role:'img','aria-label':c.title+'；等大节点代表国家概览位置，详细材料见下方列表'});for(const d of geography.land)svg.append(svgEl('path',{d,class:'world-land'}));}
      c.places.forEach((p,i)=>{const click=()=>show(p.label,p.value,p.quote,p.source_ids);if(svg&&geography.locations[p.country]){const [x,y]=geography.locations[p.country],g=svgEl('g',{class:'market-node',tabindex:0,role:'button','aria-label':p.label+'：'+p.value});g.append(svgEl('circle',{cx:x,cy:y,r:13,class:'market-halo'}),svgEl('circle',{cx:x,cy:y,r:6,class:'market-dot'}));const n=svgEl('text',{x:x+18,y:y+4,class:'market-number'});n.textContent=i+1;g.append(n);g.onclick=click;g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();click();}};svg.append(g);}const button=el('button','market-card');button.append(el('strong','',`${i+1} · ${p.label}`),el('span','',p.value),el('small','','查看市场原文 ↗'));button.onclick=click;list.append(button);});if(svg)content.append(svg);content.append(el('p','map-caption','国家位置仅用于市场概览，等大节点不表示销量或风险大小；不是工厂坐标。底图：Natural Earth(自然地理底图)，不描绘行政边界。'),list);
    }else if(c.kind==='car'){
      const stage=el('div','car-data-stage');stage.append(carSvg());const positions=[[10,9],[40,1],[70,9],[6,71],[40,73],[73,71]];
      c.metrics.forEach((m,i)=>{const b=el('button','car-callout');b.style.left=positions[i][0]+'%';b.style.top=positions[i][1]+'%';b.append(el('strong','',m.value),el('span','',m.label),el('small','','查看原文 ↗'));b.onclick=()=>show(m.label,m.value,m.quote,m.source_ids);stage.append(b);});content.append(stage,el('p','car-caption','车身为原创示意图，指标位置用于组织阅读，不表示机械部件与经营指标存在因果关系。'));
    }
    if(note)frame.append(note);frame.append(env.sourceLine(c.source_ids||[]));return frame;
  }
  return {render,carSvg,scalar,splitRoadmap,lineLayout,compareCell,sparseRoadmap,plotBounds,contextFacts,displayPeriod,withUnit,columnTitle};
})();
