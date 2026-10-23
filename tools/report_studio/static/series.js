/* Shared multi-series presentation. No interpolation, stacking or secondary axes. */
window.ReportSeries = (() => {
  const palette=window.ReportBrand?.chartColors||['#A34F2D','#242522','#7B756C','#C98261','#A99E90'];
  const marks=['●','◆','■','▲','✚'];
  const segments=(points,layout)=>layout.segments.flatMap(indices=>{
    const result=[];let current=[];
    for(const i of indices){if(points[i]!==null)current.push(i);else if(current.length){result.push(current);current=[];}}
    if(current.length)result.push(current);return result;
  });
  const domain=c=>{
    const values=c.series.flatMap(s=>s.points.filter(p=>p!==null).map(p=>p.value));
    const low=Math.min(0,...values),high=Math.max(0,...values),magnitude=Math.max(-low,high);
    if(!magnitude)return [0,1];
    const raw=magnitude*1.04/5,power=10**Math.floor(Math.log10(raw));
    const step=[1,2,2.5,5,10].find(n=>n>=raw/power)*power;
    return [Number((Math.floor(low*1.04/step)*step).toPrecision(12)),Number((Math.ceil(high*1.04/step)*step).toPrecision(12))];
  };
  const tick=value=>Number(value.toPrecision(6)).toString();
  const displayValue=(value,unit='',signed=false)=>{
    const exact=String(value);
    return signed&&unit==='%'&&value>0?'+'+exact:exact;
  };
  const scaleTicks=(low,high)=>{
    const values=[low];
    if(low<0&&high>0)values.push(0);
    if(high!==low)values.push(high);
    return values.map(value=>({value,position:(value-low)/(high-low)*100}));
  };
  // Separate direct readouts without moving the actual observations.
  const labelPositions=(values,min=32,max=290,gap=18)=>{
    const ordered=values.map((y,index)=>({y,index})).sort((a,b)=>a.y-b.y);
    ordered.forEach((p,i)=>{p.placed=Math.max(min,p.y,i?ordered[i-1].placed+gap:min);});
    for(let i=ordered.length-1;i>=0;i--)ordered[i].placed=Math.min(ordered[i].placed,i===ordered.length-1?max:ordered[i+1].placed-gap);
    const result=[];ordered.forEach(p=>{result[p.index]=p.placed;});return result;
  };
  function render(c,env){
    const {el,svgEl,show}=env,root=el('div','multi-series');
    const [low,high]=domain(c),position=v=>(v-low)/(high-low)*100;
    const kind={observed:'统计观测',survey:'调查读数',forecast:'预测值',target:'目标值'}[c.observation];
    root.append(el('p','series-basis',kind+' · '+c.unit+' / '+c.basis));
    const legend=el('div','series-legend');legend.setAttribute('aria-label','选择显示的数据序列');
    const selected=new Set(c.series.map((_,i)=>i)),buttons=[];
    c.series.forEach((s,i)=>{const b=el('button','series-key');b.style.setProperty('--series-color',c._recipe==='paired_period_columns'?'var(--ink)':palette[i]);b.title=s.definition;const swatch=el('span','series-swatch');swatch.setAttribute('aria-hidden','true');b.append(swatch,el('span','',s.label));b.onclick=()=>{if(selected.has(i)){if(selected.size===1)return;selected.delete(i);}else selected.add(i);draw();};buttons.push(b);legend.append(b);});root.append(legend);
    const plot=el('div','series-plot');root.append(plot);
    const tableDetails=el('details','series-data'),table=el('table','chart-table');
    tableDetails.append(el('summary','','查看全部数据与原文'));
    const caption=el('caption','','单位：'+c.unit+'；— 表示材料未给出，不等于0。'),head=el('thead'),hr=el('tr');hr.append(el('th','','时期 / 分类'));
    c.series.forEach(s=>hr.append(el('th','',s.label)));head.append(hr);const body=el('tbody');
    c.categories.forEach((label,j)=>{const tr=el('tr');tr.append(el('th','',label));c.series.forEach(s=>{const td=el('td'),p=s.points[j];if(p){const b=el('button','series-data-value',String(p.value));b.onclick=()=>show(s.label+' · '+p.label,p.value+' '+c.unit,p.quote,p.source_ids);td.append(b);}else td.textContent='—';tr.append(td);});body.append(tr);});table.append(caption,head,body);const tableScroll=el('div','series-table-scroll');tableScroll.tabIndex=0;tableScroll.append(table);tableDetails.append(tableScroll);root.append(tableDetails);
    const definitions=el('div','series-definitions');c.series.forEach((s,i)=>definitions.append(el('p','',marks[i]+' '+s.label+'：'+s.definition)));tableDetails.append(definitions);
    function draw(){
      buttons.forEach((b,i)=>{b.setAttribute('aria-pressed',String(selected.has(i)));b.disabled=selected.has(i)&&selected.size===1;});plot.replaceChildren();
      if(window.ReportRecipes&&['paired_period_columns','small_multiples_trend','grouped_category_columns'].includes(c._recipe)){
        plot.append(ReportRecipes.seriesPlot(c,{el,svgEl,show,selected,palette,marks,domain:[low,high],segments}));
      }else if(c.display==='grouped_bar'){
        const groups=el('div','series-groups');
        c.categories.forEach((label,j)=>{const group=el('div','series-group');group.append(el('h4','',label));
          c.series.forEach((s,i)=>{if(!selected.has(i))return;const p=s.points[j],row=el('div','series-bar-row');row.style.setProperty('--series-color',palette[i]);if(p)row.classList.add(p.value<0?'is-negative':'is-positive');
            const heading=el('div','series-bar-label'),metric=el('span','series-metric');const swatch=el('i','series-swatch');swatch.setAttribute('aria-hidden','true');metric.append(swatch,el('span','',s.label));heading.append(metric);const value=el(p?'button':'span','series-value',p?displayValue(p.value,c.unit,low<0):'—');if(p){value.setAttribute('aria-label',s.label+' · '+label+'：'+p.value+' '+c.unit);value.onclick=()=>show(s.label+' · '+label,p.value+' '+c.unit,p.quote,p.source_ids);}heading.append(value);row.append(heading);
            const track=el('div','series-track');track.append(el('span','series-zero'));track.firstChild.style.left=position(0)+'%';
            if(p){const fill=el('span','series-fill');fill.style.left=Math.min(position(0),position(p.value))+'%';fill.style.width=Math.abs(position(p.value)-position(0))+'%';track.append(fill);}else track.append(el('span','series-missing','材料未提供'));
            row.append(track);group.append(row);
          });const scale=el('div','series-scale');scale.setAttribute('aria-label','统一尺度 '+low+' 至 '+high+' '+c.unit);scaleTicks(low,high).forEach(item=>{const tickLabel=el('span','series-scale-tick',String(item.value));tickLabel.style.left=item.position+'%';scale.append(tickLabel);});group.append(scale,el('p','series-scale-caption','统一尺度 · '+c.unit));groups.append(group);
        });plot.append(groups);
      }else{
        const layout=window.ReportVisuals.lineLayout(c.categories.map(label=>({label}))),x=i=>64+layout.positions[i]*600,y=v=>300-(v-low)/(high-low)*250;
        const scroll=el('div','series-line-scroll');scroll.tabIndex=0;scroll.setAttribute('aria-label','多序列时间图，窄屏可横向滚动');
        const svg=svgEl('svg',{viewBox:'0 0 720 360',class:'series-line',role:'img','aria-label':c.title+'；缺期与缺测处断线，完整数值和引文见数据表'});
        for(let j=0;j<=5;j++){const value=low+(high-low)*j/5;svg.append(svgEl('line',{x1:64,x2:664,y1:y(value),y2:y(value),class:'series-grid'+(value===0?' zero-baseline':'')}));const label=svgEl('text',{x:52,y:y(value)+5,'text-anchor':'end',class:'series-svg-text series-tick'});label.textContent=tick(value);svg.append(label);}
        c.categories.forEach((label,i)=>{if(i!==0&&i!==c.categories.length-1&&i%Math.ceil(c.categories.length/6)!==0)return;const tick=svgEl('text',{x:x(i),y:332,'text-anchor':'middle',class:'series-svg-text'});tick.textContent=label;svg.append(tick);});
        const endpoints={start:[],end:[]};
        c.series.forEach((s,i)=>{if(!selected.has(i))return;for(const part of segments(s.points,layout)){if(part.length>1)svg.append(svgEl('polyline',{points:part.map(j=>x(j)+','+y(s.points[j].value)).join(' '),fill:'none',stroke:palette[i],'stroke-width':3,'stroke-dasharray':['forecast','target'].includes(c.observation)?'5 3':['none','8 4','2 5','10 3 2 3','5 3'][i],class:'series-path'}));}
          s.points.forEach((p,j)=>{if(!p)return;const g=svgEl('g',{role:'button',tabindex:0,'aria-label':s.label+' · '+p.label+'：'+p.value+' '+c.unit,class:'series-point'});g.append(svgEl('circle',{cx:x(j),cy:y(p.value),r:14,fill:'transparent'}));const mark=svgEl('text',{x:x(j),y:y(p.value)+5,'text-anchor':'middle',fill:palette[i],'font-size':18});mark.textContent=marks[i];g.append(mark);const open=()=>show(s.label+' · '+p.label,p.value+' '+c.unit,p.quote,p.source_ids);g.onclick=open;g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open();}};svg.append(g);});
          const present=s.points.map((p,j)=>p?j:-1).filter(j=>j>=0);for(const [edge,j] of [['start',present[0]],['end',present.at(-1)]]){if(j===undefined||j<0||(edge==='end'&&j===present[0]))continue;endpoints[edge].push({x:x(j),y:y(s.points[j].value),value:s.points[j].value,color:palette[i]});}
        });
        for(const [edge,items] of Object.entries(endpoints)){const ys=labelPositions(items.map(p=>p.y-10));items.forEach((p,i)=>{const lx=p.x+(edge==='start'?12:-12);if(Math.abs(ys[i]-(p.y-10))>3)svg.append(svgEl('line',{x1:p.x,y1:p.y,x2:lx,y2:ys[i]-4,stroke:p.color,'stroke-width':.7,class:'series-label-leader'}));const label=svgEl('text',{x:lx,y:ys[i],'text-anchor':edge==='start'?'start':'end',fill:p.color,class:'series-endpoint '+edge});label.textContent=String(p.value);svg.append(label);});}
        scroll.append(svg);plot.append(scroll,el('p','series-line-note','缺期、缺测处断线；连接线只连接已提供的相邻时点。'));
      }
    }
    draw();return root;
  }
  return {render,segments,domain,tick,displayValue,scaleTicks,labelPositions};
})();
