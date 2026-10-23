/* Evidence-led analytical scatter plots. Geometry is deterministic and values stay literal. */
window.ReportScatter=(()=>{
  const NS='http://www.w3.org/2000/svg';
  const finite=value=>Number.isFinite(Number(value));
  const numeric=value=>Number(value);
  const median=values=>{const ordered=values.map(numeric).filter(Number.isFinite).sort((a,b)=>a-b);if(!ordered.length)return 0;const middle=Math.floor(ordered.length/2);return ordered.length%2?ordered[middle]:(ordered[middle-1]+ordered[middle])/2;};
  const tickText=value=>{const absolute=Math.abs(value);const digits=absolute>=100?0:absolute>=10?1:2;return Number(value.toFixed(digits)).toLocaleString('zh-CN',{maximumFractionDigits:digits});};
  const valueText=value=>numeric(value).toLocaleString('zh-CN',{maximumFractionDigits:6});
  const tickStep=span=>{if(!span)return 1;const raw=span/5,power=10**Math.floor(Math.log10(raw)),scaled=raw/power;return (scaled<=1?1:scaled<=2?2:scaled<=2.5?2.5:scaled<=5?5:10)*power;};
  function scaleDomain(values,reference='none'){
    const list=values.map(numeric).filter(Number.isFinite);let low=Math.min(...list),high=Math.max(...list);
    if(!list.length)return {low:0,high:1,ticks:[0,1]};
    if(reference==='zero'){low=Math.min(low,0);high=Math.max(high,0);}
    let span=high-low;if(!span){const spread=Math.abs(high)||1;low-=spread*.22;high+=spread*.22;span=high-low;}
    const padding=span*.1;low-=padding;high+=padding;
    if(reference==='zero'){low=Math.min(low,0);high=Math.max(high,0);}
    const step=tickStep(high-low),tickLow=Math.floor(low/step)*step,tickHigh=Math.ceil(high/step)*step,ticks=[];
    for(let value=tickLow,count=0;value<=tickHigh+step/100&&count<12;value+=step,count++)ticks.push(Number(value.toFixed(10)));
    return {low:tickLow,high:tickHigh,ticks};
  }
  const overlap=(a,b,pad=7)=>!(a.x+a.w+pad<=b.x||b.x+b.w+pad<=a.x||a.y+a.h+pad<=b.y||b.y+b.h+pad<=a.y);
  function layoutLabels(points,bounds){
    const placed=[];
    const ordered=[...points].sort((a,b)=>Number(Boolean(b.emphasis))-Number(Boolean(a.emphasis))||a.cy-b.cy);
    const directions=[
      [14,-50],[14,10],[-174,-50],[-174,10],[14,-20],[-174,-20],[-80,-62],[-80,20]
    ];
    for(const point of ordered){
      const width=Math.min(174,Math.max(112,point.label.length*8+22)),height=43;
      let best=null;
      directions.forEach(([dx,dy],rank)=>{
        const x=Math.max(bounds.left,Math.min(bounds.right-width,point.cx+dx));
        const y=Math.max(bounds.top,Math.min(bounds.bottom-height,point.cy+dy));
        const box={x,y,w:width,h:height};
        const collisions=placed.filter(other=>overlap(box,other)).length;
        const pointCover=points.filter(other=>other.cx>x-10&&other.cx<x+width+10&&other.cy>y-10&&other.cy<y+height+10).length;
        const score=collisions*1000+pointCover*240+rank*4+Math.abs((x+width/2)-point.cx)*.02;
        if(!best||score<best.score)best={...box,score};
      });
      placed.push({...best,point});
    }
    return placed;
  }
  const shortened=(text,max=16)=>text.length>max?text.slice(0,max-1)+'…':text;
  const ariaPoint=(c,p)=>`${p.label}：${c.x_label} ${p.x} ${c.x_unit||''}，${c.y_label} ${p.y} ${c.y_unit||''}`;
  function render(c,{el,svgEl,show}){
    const makeSvg=(tag,attrs={})=>{if(svgEl)return svgEl(tag,attrs);const node=document.createElementNS(NS,tag);Object.entries(attrs).forEach(([key,value])=>node.setAttribute(key,String(value)));return node;};
    const makeEl=el||((tag,cls,text)=>{const node=document.createElement(tag);if(cls)node.className=cls;if(text!==undefined)node.textContent=text;return node;});
    const analysis=c.analysis||{reference:'none'};
    const points=(c.points||[]).filter(point=>finite(point.x)&&finite(point.y));
    const root=makeEl('div','analytical-scatter');
    if(!points.length){root.append(makeEl('p','scatter-empty','缺少可绘制的数值。'));return root;}
    const xDomain=scaleDomain(points.map(p=>p.x),analysis.reference),yDomain=scaleDomain(points.map(p=>p.y),analysis.reference);
    const frame={left:92,right:826,top:58,bottom:440},width=frame.right-frame.left,height=frame.bottom-frame.top;
    const x=value=>frame.left+(numeric(value)-xDomain.low)/(xDomain.high-xDomain.low)*width;
    const y=value=>frame.bottom-(numeric(value)-yDomain.low)/(yDomain.high-yDomain.low)*height;
    const xReference=analysis.reference==='median'?median(points.map(p=>p.x)):analysis.reference==='zero'?0:null;
    const yReference=analysis.reference==='median'?median(points.map(p=>p.y)):analysis.reference==='zero'?0:null;
    const summary=makeEl('p','scatter-definition',`X = ${c.x_label}${c.x_unit?'（'+c.x_unit+'）':''} · Y = ${c.y_label}${c.y_unit?'（'+c.y_unit+'）':''}${analysis.reference==='median'?' · 虚线为样本中位数':analysis.reference==='zero'?' · 虚线为零轴':''}`);
    root.append(summary);
    const svg=makeSvg('svg',{viewBox:'0 0 880 510',class:'analytical-scatter-svg',role:'img','aria-label':`${c.title}。${summary.textContent}。各点可点击或使用键盘查看证据。`});
    const title=makeSvg('title');title.textContent=c.title;svg.append(title);
    const plot=makeSvg('rect',{x:frame.left,y:frame.top,width,height,class:'scatter-field'});svg.append(plot);
    if(xReference!==null&&yReference!==null){
      const px=x(xReference),py=y(yReference),zones=[
        {key:'II',x:frame.left,y:frame.top,w:px-frame.left,h:py-frame.top,cls:'zone-a'},
        {key:'I',x:px,y:frame.top,w:frame.right-px,h:py-frame.top,cls:'zone-b'},
        {key:'III',x:frame.left,y:py,w:px-frame.left,h:frame.bottom-py,cls:'zone-c'},
        {key:'IV',x:px,y:py,w:frame.right-px,h:frame.bottom-py,cls:'zone-d'}
      ];
      zones.forEach(zone=>{const rect=makeSvg('rect',{x:zone.x,y:zone.y,width:zone.w,height:zone.h,class:`scatter-zone ${zone.cls}`});svg.append(rect);if(zone.w>=45&&zone.h>=30){const label=makeSvg('text',{x:zone.x+10,y:zone.y+20,class:'scatter-region-label'});label.textContent=zone.key;svg.append(label);}});
    }
    xDomain.ticks.forEach(value=>{const px=x(value);svg.append(makeSvg('line',{x1:px,x2:px,y1:frame.top,y2:frame.bottom,class:'scatter-grid'}));const label=makeSvg('text',{x:px,y:frame.bottom+25,'text-anchor':'middle',class:'scatter-tick'});label.textContent=tickText(value);svg.append(label);});
    yDomain.ticks.forEach(value=>{const py=y(value);svg.append(makeSvg('line',{x1:frame.left,x2:frame.right,y1:py,y2:py,class:'scatter-grid'}));const label=makeSvg('text',{x:frame.left-14,y:py+4,'text-anchor':'end',class:'scatter-tick'});label.textContent=tickText(value);svg.append(label);});
    if(xReference!==null){const px=x(xReference);svg.append(makeSvg('line',{x1:px,x2:px,y1:frame.top,y2:frame.bottom,class:'scatter-reference'}));const label=makeSvg('text',{x:px+7,y:frame.top-12,class:'scatter-reference-label'});label.textContent=analysis.reference==='median'?`X 中位数 ${valueText(xReference)}`:'X = 0';svg.append(label);}
    if(yReference!==null){const py=y(yReference);svg.append(makeSvg('line',{x1:frame.left,x2:frame.right,y1:py,y2:py,class:'scatter-reference'}));const label=makeSvg('text',{x:frame.right-7,y:py-8,'text-anchor':'end',class:'scatter-reference-label'});label.textContent=analysis.reference==='median'?`Y 中位数 ${valueText(yReference)}`:'Y = 0';svg.append(label);}
    const xAxis=makeSvg('text',{x:(frame.left+frame.right)/2,y:498,'text-anchor':'middle',class:'scatter-axis-label'});xAxis.textContent=`${c.x_label}${c.x_unit?' →  '+c.x_unit:''}`;
    const yAxis=makeSvg('text',{x:22,y:(frame.top+frame.bottom)/2,'text-anchor':'middle',class:'scatter-axis-label',transform:`rotate(-90 22 ${(frame.top+frame.bottom)/2})`});yAxis.textContent=`${c.y_label}${c.y_unit?' →  '+c.y_unit:''}`;svg.append(xAxis,yAxis);
    const projected=points.map((point,index)=>({...point,index,cx:x(point.x),cy:y(point.y)}));
    const labels=layoutLabels(projected,{left:frame.left+5,right:frame.right-5,top:frame.top+35,bottom:frame.bottom-5});
    labels.forEach(box=>{
      const point=box.point,labelX=box.x,labelY=box.y,edgeX=point.cx<labelX?labelX:point.cx>labelX+box.w?labelX+box.w:point.cx,edgeY=point.cy<labelY?labelY:point.cy>labelY+box.h?labelY+box.h:point.cy;
      if(Math.hypot(edgeX-point.cx,edgeY-point.cy)>9)svg.append(makeSvg('line',{x1:point.cx,y1:point.cy,x2:edgeX,y2:edgeY,class:'scatter-leader'}));
    });
    projected.forEach(point=>{
      const activate=()=>show(point.label,`${c.x_label} ${point.x} ${c.x_unit||''} · ${c.y_label} ${point.y} ${c.y_unit||''}`,point.quote,point.source_ids||c.source_ids||[]);
      const group=makeSvg('g',{class:'scatter-point'+(point.emphasis?' is-emphasis':''),tabindex:'0',role:'button','aria-label':ariaPoint(c,point)});
      const accessible=makeSvg('title');accessible.textContent=ariaPoint(c,point);group.append(accessible,makeSvg('circle',{cx:point.cx,cy:point.cy,r:20,class:'scatter-hit'}),makeSvg('circle',{cx:point.cx,cy:point.cy,r:7,class:'scatter-mark'}));
      group.onclick=activate;group.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();activate();}};svg.append(group);
    });
    labels.forEach(box=>{const point=box.point,text=makeSvg('text',{x:box.x,y:box.y+15,'data-item-index':point.index,class:'scatter-direct-label'+(point.emphasis?' is-emphasis':'')});const name=makeSvg('tspan',{x:box.x,dy:0,class:'scatter-direct-name'});name.textContent=shortened(point.label);const value=makeSvg('tspan',{x:box.x,dy:18,class:'scatter-direct-value'});value.textContent=`${valueText(point.x)}${c.x_unit||''} · ${valueText(point.y)}${c.y_unit||''}`;const full=makeSvg('title');full.textContent=ariaPoint(c,point);text.append(full,name,value);svg.append(text);});
    const plotScroll=makeEl('div','scatter-plot-scroll');plotScroll.append(svg);root.append(plotScroll);
    if(xReference!==null&&yReference!==null){const key=makeEl('div','scatter-region-key');[
      ['II',analysis.x_low_label||'X 较低',analysis.y_high_label||'Y 较高'],['I',analysis.x_high_label||'X 较高',analysis.y_high_label||'Y 较高'],
      ['III',analysis.x_low_label||'X 较低',analysis.y_low_label||'Y 较低'],['IV',analysis.x_high_label||'X 较高',analysis.y_low_label||'Y 较低']
    ].forEach(([id,xLabel,yLabel])=>{const item=makeEl('span','scatter-region-key-item');item.append(makeEl('b','',id),makeEl('span','',`${xLabel} · ${yLabel}`));key.append(item);});root.append(key);}
    const details=makeEl('div','scatter-details');details.setAttribute('aria-label','散点数据明细');
    points.forEach(point=>{const button=makeEl('button','scatter-detail'+(point.emphasis?' is-emphasis':''));button.setAttribute('aria-label',ariaPoint(c,point));button.append(makeEl('strong','',point.label),makeEl('span','',`${c.x_label} ${point.x}${c.x_unit||''} · ${c.y_label} ${point.y}${c.y_unit||''}`));button.onclick=()=>show(point.label,`${c.x_label} ${point.x} ${c.x_unit||''} · ${c.y_label} ${point.y} ${c.y_unit||''}`,point.quote,point.source_ids||c.source_ids||[]);details.append(button);});
    root.append(details);return root;
  }
  return {render,median,scaleDomain,layoutLabels};
})();
