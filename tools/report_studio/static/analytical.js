/* Evidence-led waterfall and mechanism diagrams. Values and disclosure status stay literal. */
window.ReportAnalytical=(()=>{
  const NS='http://www.w3.org/2000/svg';
  let renderSerial=0;
  const statusText={observed:'已披露',proposal:'建议',unknown:'未披露'};
  const raw=value=>Number.isFinite(Number(value))?Number(value).toLocaleString('zh-CN',{maximumFractionDigits:15}):String(value);
  const finite=value=>Number.isFinite(Number(value));
  const signed=value=>Number(value)>0?'+'+raw(value):raw(value);
  const itemSources=(item,c)=>item.source_ids?.length?item.source_ids:c.source_ids||[];
  const activate=(node,open)=>{
    node.onclick=open;
    node.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();open();}};
  };
  const statusForLink=(from,to)=>from.status==='unknown'||to.status==='unknown'?'unknown':from.status==='proposal'||to.status==='proposal'?'proposal':'observed';

  function numericDomain(values){
    const valid=values.map(Number).filter(Number.isFinite);
    let low=Math.min(0,...valid),high=Math.max(0,...valid);
    if(low===high){const spread=Math.abs(low)||1;low-=spread*.25;high+=spread*.25;}
    const span=high-low;
    return {low:low<0?low-span*.07:0,high:high>0?high+span*.07:0};
  }

  function axisTicks(domain,count=5){
    const rough=(domain.high-domain.low)/Math.max(1,count-1),power=10**Math.floor(Math.log10(rough||1));
    const step=([1,2,2.5,5,10].find(value=>value>=rough/power)||10)*power;
    const first=Math.floor(domain.low/step),last=Math.ceil(domain.high/step);
    return Array.from({length:last-first+1},(_,index)=>Number(((index+first)*step).toPrecision(12)));
  }

  const tickText=value=>Number(value).toLocaleString('zh-CN',{maximumFractionDigits:6});

  function waterfallGeometry(c){
    const points=[c.start,...(c.changes||[]),c.end],rows=[];
    let running=Number(c.start.value);
    rows.push({index:0,item:c.start,type:'start',from:0,to:running,value:Number(c.start.value)});
    (c.changes||[]).forEach((item,changeIndex)=>{
      const from=running;running+=Number(item.value);
      rows.push({index:changeIndex+1,item,type:Number(item.value)<0?'negative':'positive',from,to:running,value:Number(item.value)});
    });
    rows.push({index:points.length-1,item:c.end,type:'end',from:0,to:Number(c.end.value),value:Number(c.end.value)});
    const domain=numericDomain(rows.flatMap(row=>[row.from,row.to]));
    return {points,rows,computed:running,difference:Number(c.end.value)-running,domain};
  }

  function fallbackSvg(tag,attrs){
    const node=document.createElementNS(NS,tag);
    Object.entries(attrs).forEach(([key,value])=>node.setAttribute(key,String(value)));
    return node;
  }

  function renderWaterfall(c,{el,svgEl,show}){
    const makeSvg=(tag,attrs)=>svgEl?svgEl(tag,attrs):fallbackSvg(tag,attrs);
    const layout=waterfallGeometry(c),root=el('div','report-analytical analytical-waterfall');
    const definition=el('p','analytical-reading',`读图：每一行从前一累计值接力；向右为增加，向左为减少。起点与终点均从零轴读取。单位：${c.unit}；口径：${c.basis}`);
    root.append(definition);
    if(layout.rows.some(row=>!finite(row.value))){root.append(el('p','analytical-empty','缺少可绘制的数值。'));return root;}
    if(Math.abs(layout.difference)>0.01){
      root.append(el('p','analytical-warning',`输入未对齐：起点加各项变化为 ${raw(layout.computed)} ${c.unit}，终点为 ${raw(c.end.value)} ${c.unit}，差额 ${signed(layout.difference)} ${c.unit}。图中保留原始终点。`));
    }
    const rowHeight=76,top=70,bottom=42,height=top+layout.rows.length*rowHeight+bottom,width=960,left=255,right=700,valueColumn=940,plotWidth=right-left,ticks=axisTicks(layout.domain),axisDomain={low:ticks[0],high:ticks.at(-1)};
    const x=value=>left+(Number(value)-axisDomain.low)/(axisDomain.high-axisDomain.low)*plotWidth;
    const svg=makeSvg('svg',{viewBox:`0 0 ${width} ${height}`,class:'analytical-waterfall-svg',role:'img','aria-label':`${c.title}。${definition.textContent}。每一项可点击或使用键盘查看证据。`});
    const title=makeSvg('title',{});title.textContent=c.title;svg.append(title);
    const zero=x(0);
    svg.append(makeSvg('line',{x1:zero,x2:zero,y1:top-26,y2:height-bottom+4,class:'waterfall-zero'}));
    ticks.forEach(tick=>{const tickX=x(tick);svg.append(makeSvg('line',{x1:tickX,x2:tickX,y1:top-20,y2:height-bottom+4,class:'waterfall-grid'}));const label=makeSvg('text',{x:tickX,y:top-34,'text-anchor':'middle',class:'waterfall-axis-label'});label.textContent=tickText(tick);svg.append(label);});
    const unitLabel=makeSvg('text',{x:right,y:top-52,'text-anchor':'end',class:'waterfall-axis-unit'});unitLabel.textContent=`横轴单位：${c.unit}`;svg.append(unitLabel);
    const columnLabel=makeSvg('text',{x:valueColumn,y:top-52,'text-anchor':'end',class:'waterfall-axis-unit'});columnLabel.textContent='原值';svg.append(columnLabel);
    layout.rows.forEach((row,rowIndex)=>{
      const y=top+rowIndex*rowHeight+rowHeight/2,barX=Math.min(x(row.from),x(row.to)),barWidth=Math.abs(x(row.to)-x(row.from));
      if(rowIndex<layout.rows.length-1){
        const nextY=y+rowHeight,connector=makeSvg('line',{x1:x(row.to),x2:x(row.to),y1:y+16,y2:nextY-16,class:'observation-connector waterfall-connector','data-item-index':rowIndex+1});
        svg.append(connector);
      }
      const group=makeSvg('g',{class:`observation-row waterfall-row is-${row.type}`,role:'button',tabindex:'0','data-item-index':row.index,'aria-label':`${row.item.label}：${raw(row.item.value)} ${c.unit}`});
      const hit=makeSvg('rect',{x:8,y:y-rowHeight/2+4,width:width-16,height:rowHeight-8,class:'waterfall-hit'});
      const label=makeSvg('text',{x:left-22,y:y-6,'text-anchor':'end',class:'waterfall-label'});label.textContent=row.item.label;
      const role=makeSvg('text',{x:left-22,y:y+14,'text-anchor':'end',class:'waterfall-role'});role.textContent=row.type==='start'?'起点':row.type==='end'?'终点':row.type==='negative'?'减少':'增加';
      const bar=makeSvg('rect',{x:barX,y:y-14,width:barWidth,height:28,rx:2,class:'waterfall-bar'});
      const cap=makeSvg('line',{x1:x(row.to),x2:x(row.to),y1:y-18,y2:y+18,class:'waterfall-cap'});
      const value=makeSvg('text',{x:valueColumn,y:y+5,'text-anchor':'end',class:'waterfall-value'});value.textContent=`${row.type==='positive'?signed(row.item.value):raw(row.item.value)} ${c.unit}`;
      const tip=makeSvg('title',{});tip.textContent=`${row.item.label}：${raw(row.item.value)} ${c.unit}`;
      group.append(tip,hit,label,role,bar,cap,value);
      activate(group,()=>show(row.item.label,`${raw(row.item.value)} ${c.unit} · ${c.basis}`,row.item.quote,itemSources(row.item,c)));
      svg.append(group);
    });
    const scroll=el('div','analytical-plot-scroll');scroll.tabIndex=0;scroll.setAttribute('aria-label','瀑布桥图，窄屏可横向滚动');scroll.append(svg);root.append(scroll);
    const details=el('div','analytical-evidence-list');details.setAttribute('aria-label','瀑布图完整数据与证据');
    layout.rows.forEach(row=>{const button=el('button',`analytical-evidence is-${row.type}`);button.setAttribute('data-item-index',String(row.index));button.append(el('strong','',row.item.label),el('span','',`${raw(row.item.value)} ${c.unit}`));button.onclick=()=>show(row.item.label,`${raw(row.item.value)} ${c.unit} · ${c.basis}`,row.item.quote,itemSources(row.item,c));details.append(button);});
    root.append(details);return root;
  }

  function wrapSvgText(makeSvg,text,x,y,width,lineHeight,className,maxLines=3){
    const value=String(text),limit=Math.max(4,Math.floor(width/14)),lines=[];
    for(let offset=0;offset<value.length;offset+=limit)lines.push(value.slice(offset,offset+limit));
    const label=makeSvg('text',{x,y,class:className});
    lines.slice(0,maxLines).forEach((line,index)=>{const span=makeSvg('tspan',{x,dy:index?lineHeight:0});span.textContent=line+(index===maxLines-1&&lines.length>maxLines?'…':'');label.append(span);});
    return label;
  }

  function renderMechanism(c,{el,svgEl,show}){
    const makeSvg=(tag,attrs)=>svgEl?svgEl(tag,attrs):fallbackSvg(tag,attrs),nodes=c.nodes||[],links=c.links||[];
    const root=el('div','report-analytical analytical-mechanism');
    const definition=el('p','analytical-reading','读图：从左向右阅读箭头关系；同列节点并行呈现，不表示先后。实线为已披露，虚线为建议，点线为未披露。线条不表达流量或概率。');root.append(definition);
    if(!nodes.length){root.append(el('p','analytical-empty','缺少可绘制的机制节点。'));return root;}
    const lanes=(c.lanes||[]).slice(0,3),stageCount=Math.min(4,Math.max(1,...nodes.map(node=>Number(node.stage)+1))),left=120,top=78,colWidth=220,nodeWidth=172,nodeHeight=86,stackGap=20,width=Math.max(520,left+stageCount*colWidth+40);
    const slots=new Map(),stackIndex=new Map();
    nodes.forEach(node=>{const key=`${node.lane}:${node.stage}`,index=slots.get(key)||0;stackIndex.set(node,index);slots.set(key,index+1);});
    const laneHeights=lanes.map((_,lane)=>Math.max(150,Math.max(1,...Array.from({length:stageCount},(_,stage)=>slots.get(`${lane}:${stage}`)||0))*(nodeHeight+stackGap)+44));
    const laneY=[];let nextY=top;laneHeights.forEach(height=>{laneY.push(nextY);nextY+=height;});const height=nextY+48;
    const position=node=>({x:left+node.stage*colWidth,y:laneY[node.lane]+stackIndex.get(node)*(nodeHeight+stackGap)});
    const markerId=`analytical-arrow-${renderSerial++}`;
    const svg=makeSvg('svg',{viewBox:`0 0 ${width} ${height}`,class:'analytical-mechanism-svg',role:'img','aria-label':`${c.title}。${definition.textContent}。节点和关系均可查看证据。`});
    const title=makeSvg('title',{});title.textContent=c.title;svg.append(title);
    const defs=makeSvg('defs',{}),marker=makeSvg('marker',{id:markerId,viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:7,markerHeight:7,orient:'auto-start-reverse'});marker.append(makeSvg('path',{d:'M 0 0 L 10 5 L 0 10 z',class:'mechanism-arrowhead'}));defs.append(marker);svg.append(defs);
    for(let stage=0;stage<stageCount;stage++){const x=left+stage*colWidth+nodeWidth/2,heading=makeSvg('text',{x,y:34,'text-anchor':'middle',class:'mechanism-stage'});heading.textContent=`阶段 ${stage+1}`;svg.append(heading,makeSvg('line',{x1:x,x2:x,y1:48,y2:height-25,class:'mechanism-stage-guide'}));}
    lanes.forEach((lane,index)=>{const y=laneY[index]+nodeHeight/2,label=makeSvg('text',{x:18,y:y+4,class:'mechanism-lane'});label.textContent=lane;svg.append(label);});
    links.forEach((link,linkIndex)=>{
      const source=link.from??link.origin,from=nodes[source],to=nodes[link.to];if(!from||!to)return;
      const a=position(from),b=position(to),x1=a.x+nodeWidth,y1=a.y+nodeHeight/2,x2=b.x,y2=b.y+nodeHeight/2,curve=Math.max(35,Math.abs(x2-x1)*.42),status=statusForLink(from,to);
      const group=makeSvg('g',{class:`mechanism-link is-${status}`,role:'button',tabindex:'0','data-item-index':link.to,'data-link-index':linkIndex,'data-from-index':source,'data-to-index':link.to,'aria-label':`${from.label} 到 ${to.label}：${link.label}，${statusText[status]}`});
      const path=`M ${x1} ${y1} C ${x1+curve} ${y1}, ${x2-curve} ${y2}, ${x2} ${y2}`;
      group.append(makeSvg('path',{d:path,class:'mechanism-link-hit'}),makeSvg('path',{d:path,class:'observation-connector mechanism-link-path','marker-end':`url(#${markerId})`}));
      const mx=(x1+x2)/2,my=(y1+y2)/2-8,label=wrapSvgText(makeSvg,link.label,mx,my,Math.max(y1!==y2?140:54,Math.abs(x2-x1)-12),13,'mechanism-link-label',2),fullLabel=makeSvg('title',{});fullLabel.textContent=link.label;label.setAttribute('text-anchor','middle');group.append(fullLabel,label);
      activate(group,()=>show(`${from.label} → ${to.label}`,`${link.label} · ${statusText[status]}`,link.quote,itemSources(link,c)));svg.append(group);
    });
    nodes.forEach((node,index)=>{
      const p=position(node),group=makeSvg('g',{class:`observation-row mechanism-node is-${node.status}`,role:'button',tabindex:'0','data-item-index':index,'aria-label':`${node.label}，${statusText[node.status]}`});
      group.append(makeSvg('rect',{x:p.x,y:p.y,width:nodeWidth,height:nodeHeight,rx:3,class:'mechanism-node-card'}));
      const state=makeSvg('text',{x:p.x+12,y:p.y+19,class:'mechanism-node-status'});state.textContent=statusText[node.status];group.append(state,wrapSvgText(makeSvg,node.label,p.x+12,p.y+43,nodeWidth-24,17,'mechanism-node-label'));
      activate(group,()=>show(node.label,`${statusText[node.status]} · ${node.detail}`,node.quote,itemSources(node,c)));svg.append(group);
    });
    const scroll=el('div','analytical-plot-scroll');scroll.tabIndex=0;scroll.setAttribute('aria-label','机制证据地图，窄屏可横向滚动');scroll.append(svg);root.append(scroll);
    const legend=el('div','mechanism-legend');['observed','proposal','unknown'].forEach(status=>{const item=el('span',`is-${status}`);item.append(el('i','',''),el('span','',statusText[status]));legend.append(item);});root.append(legend);
    const details=el('div','mechanism-evidence-list');details.setAttribute('aria-label','完整节点证据列表');
    nodes.forEach((node,index)=>{const button=el('button',`mechanism-evidence is-${node.status}`);button.setAttribute('data-item-index',String(index));button.append(el('span','mechanism-evidence-status',statusText[node.status]),el('strong','',node.label),el('span','',node.detail));button.onclick=()=>show(node.label,`${statusText[node.status]} · ${node.detail}`,node.quote,itemSources(node,c));details.append(button);});root.append(details);
    return root;
  }

  function render(c,env){
    if(c.kind==='waterfall')return renderWaterfall(c,env);
    if(c.kind==='mechanism')return renderMechanism(c,env);
    const root=env.el('div','report-analytical');root.append(env.el('p','analytical-empty','不支持的专业图形类型。'));return root;
  }
  return {render,waterfallGeometry,numericDomain,axisTicks,statusForLink};
})();
