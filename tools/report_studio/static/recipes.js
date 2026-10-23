/* Pure presentation changes, selected from declared data shape. Original facts stay intact. */
window.ReportRecipes=(()=>{
  const adapt=(c,decision)=>{
    if(!decision)return c;const out={...c,_recipe:decision.recipe};
    if(c.kind==='line'&&decision.recipe!=='single_series_trend')out.kind='bar';
    if(c.kind==='multiseries')out.display=['multi_series_trend','small_multiples_trend'].includes(decision.recipe)?'line':'grouped_bar';
    return out;
  };
  const categoryGeometry=(value,low,high,top=34,plotHeight=266)=>{const y=number=>top+(high-number)/(high-low)*plotHeight,zero=y(0),point=y(value);return {y:Math.min(zero,point),height:Math.abs(point-zero),origin:value<0?'top':'bottom',zero,point};};
  const categoryTicks=(low,high,target=5)=>{const span=high-low;if(!(span>0))return [low];const raw=span/target,power=10**Math.floor(Math.log10(raw)),fraction=raw/power,step=([1,2,2.5,5,10].find(value=>value>=fraction)||10)*power,start=Math.ceil((low-1e-10)/step)*step,values=[];for(let value=start;value<=high+step*1e-9;value+=step)values.push(Number(value.toPrecision(12)));return values;};
  const categoryViewportWidth=(count,mobile=false)=>count<=3?(mobile?460:680):Math.max(680,count*150);
  function categoryColumns(c,env){
    const {el,svgEl,show,selected,palette,domain:[low,high]}=env,chosen=[...selected];
    const compact=c.categories.length<=3,root=el('div','recipe-category'),scroll=el('div','recipe-category-scroll'+(compact?' is-compact':''));
    scroll.tabIndex=0;scroll.setAttribute('aria-label',c.title+'；所有类别和序列使用同一纵轴，窄屏可横向滚动');
    const height=340,left=64,right=24,top=28,bottom=58,plotHeight=height-top-bottom;
    const svg=svgEl('svg',{role:'group','aria-label':c.title+'；共享零轴分组柱图，点击数值查看原文',class:'recipe-chart category-chart'+(compact?' is-compact':'')});
    let renderedWidth=0;
    const draw=width=>{if(width===renderedWidth)return;renderedWidth=width;svg.setAttribute('viewBox',`0 0 ${width} ${height}`);svg.replaceChildren();
      const y=value=>top+(high-value)/(high-low)*plotHeight,x=index=>left+(index+.5)*(width-left-right)/c.categories.length;
      const text=(parent,xp,yp,value,cls='recipe-axis',anchor='start')=>{const node=svgEl('text',{x:xp,y:yp,class:cls,'text-anchor':anchor});node.textContent=value;parent.append(node);return node;};
      const ticks=categoryTicks(low,high);ticks.forEach(value=>{svg.append(svgEl('line',{x1:left,x2:width-right,y1:y(value),y2:y(value),class:'recipe-grid'+(value===0?' zero-baseline':'')}));text(svg,left-10,y(value)+4,ReportSeries.tick(value),'recipe-axis','end');});
      if(low<0&&high>0&&!ticks.includes(0)){svg.append(svgEl('line',{x1:left,x2:width-right,y1:y(0),y2:y(0),class:'recipe-zero'}));text(svg,left-10,y(0)+4,'0','recipe-axis zero-label','end');}
      const groupWidth=Math.min(92,(width-left-right)/Math.max(1,c.categories.length)*.62),gap=chosen.length>2?4:7,columnWidth=Math.max(12,Math.min(34,(groupWidth-gap*(chosen.length-1))/Math.max(1,chosen.length)));
      c.categories.forEach((label,j)=>{const center=x(j),total=columnWidth*chosen.length+gap*Math.max(0,chosen.length-1),start=center-total/2;text(svg,center,height-22,label,'recipe-category-label','middle');
        chosen.forEach((seriesIndex,slot)=>{const series=c.series[seriesIndex],point=series.points[j];if(!point)return;const cx=start+slot*(columnWidth+gap),geometry=categoryGeometry(point.value,low,high,top,plotHeight),valueY=geometry.point;
          const group=svgEl('g',{role:'button',tabindex:0,'aria-label':series.label+' · '+label+'：'+point.value+' '+c.unit,class:'recipe-hit category-hit'}),projected=['forecast','target'].includes(c.observation);
          group.append(svgEl('rect',{x:cx,y:geometry.y,width:columnWidth,height:geometry.height,rx:1.5,fill:projected?'var(--surface)':palette[seriesIndex],stroke:projected?palette[seriesIndex]:'none','stroke-width':projected?1.6:0,'stroke-dasharray':projected?'5 3':'none',class:'recipe-column category-column'+(point.value<0?' is-negative':' is-positive')+(projected?' is-projected':''),'data-motion-origin':geometry.origin}));
          text(group,cx+columnWidth/2,point.value>=0?valueY-10:valueY+18,ReportSeries.displayValue(point.value,c.unit,low<0),'recipe-value category-value','middle');
          const open=()=>show(series.label+' · '+label,point.value+' '+c.unit,point.quote,point.source_ids);group.onclick=open;group.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();open();}};svg.append(group);
        });
      });
    };
    const responsiveDraw=()=>{const measured=scroll.clientWidth||scroll.getBoundingClientRect?.().width||0,mobile=measured?measured<=600:typeof matchMedia==='function'&&matchMedia('(max-width:600px)').matches;draw(categoryViewportWidth(c.categories.length,mobile));};
    responsiveDraw();
    scroll.append(svg);root.append(scroll,el('p','recipe-reading','共享零轴与统一纵轴 · 柱高只表示材料中的原始数值；负值向零轴下方展开。'));
    if(typeof ResizeObserver==='function')new ResizeObserver(responsiveDraw).observe(scroll);
    return root;
  }
  function seriesPlot(c,env){
    if(c._recipe==='grouped_category_columns')return categoryColumns(c,env);
    const {el,svgEl,show,selected,palette,marks,domain:[low,high],segments}=env;
    const root=el('div','recipe-panels'),paired=c._recipe==='paired_period_columns';root.dataset.recipe=c._recipe;
    const text=(parent,x,y,value,cls='recipe-axis',anchor='start')=>{const t=svgEl('text',{x,y,class:cls,'text-anchor':anchor});t.textContent=value;parent.append(t);return t;};
    c.series.forEach((s,i)=>{if(!selected.has(i))return;const panel=el('section','recipe-panel');panel.append(el('h4','',marks[i]+' '+s.label));
      const svg=svgEl('svg',{viewBox:'0 0 300 300',role:'group','aria-label':s.label+'；统一尺度，点击数值查看原文',class:'recipe-chart'}),y=v=>235-(v-low)/(high-low)*180;
      for(const value of categoryTicks(low,high)){svg.append(svgEl('line',{x1:46,x2:285,y1:y(value),y2:y(value),class:'recipe-grid'+(value===0?' zero-baseline':'')}));text(svg,37,y(value)+4,ReportSeries.tick(value),'recipe-axis','end');}
      const open=(point,index)=>()=>show(s.label+' · '+c.categories[index],point.value+' '+c.unit,point.quote,point.source_ids);
      if(paired){
        svg.append(svgEl('line',{x1:46,x2:285,y1:y(0),y2:y(0),class:'recipe-zero'}));
        s.points.forEach((p,j)=>{const x=90+j*128;text(svg,x,269,c.categories[j],'recipe-period','middle');if(!p){text(svg,x,210,'未提供','recipe-axis','middle');return;}
          const g=svgEl('g',{role:'button',tabindex:0,'aria-label':s.label+' · '+c.categories[j]+'：'+p.value+' '+c.unit,class:'recipe-hit'});
          g.append(svgEl('rect',{x:x-23,y:Math.min(y(0),y(p.value)),width:46,height:Math.abs(y(p.value)-y(0)),fill:j===0||['forecast','target'].includes(c.observation)?'var(--surface)':palette[0],stroke:j===0?'var(--muted)':palette[0],'stroke-width':1.6,'stroke-dasharray':['forecast','target'].includes(c.observation)?'5 3':'none',class:'recipe-column '+(j===0?'is-first':'is-later'),'data-motion-origin':p.value<0?'top':'bottom'}));
          text(g,x,p.value>=0?y(p.value)-12:y(p.value)+23,String(p.value),'recipe-value','middle');g.onclick=open(p,j);g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open(p,j)();}};svg.append(g);
        });
      }else{
        const layout=window.ReportVisuals.lineLayout(c.categories.map(label=>({label}))),x=j=>48+layout.positions[j]*228;
        for(const seg of segments(s.points,layout))if(seg.length>1)svg.append(svgEl('polyline',{points:seg.map(j=>[x(j),y(s.points[j].value)].join(',')).join(' '),fill:'none',stroke:palette[i],'stroke-width':2.2,'stroke-dasharray':['forecast','target'].includes(c.observation)?'5 3':'none',class:'recipe-line'}));
        s.points.forEach((p,j)=>{if(!p)return;const g=svgEl('g',{tabindex:0,role:'button','aria-label':s.label+' · '+c.categories[j]+'：'+p.value+' '+c.unit,class:'recipe-hit'});g.append(svgEl('circle',{cx:x(j),cy:y(p.value),r:12,fill:'transparent'}),svgEl('circle',{cx:x(j),cy:y(p.value),r:3,fill:['forecast','target'].includes(c.observation)?'var(--surface)':palette[i],stroke:palette[i],'stroke-width':1.2}));g.onclick=open(p,j);g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open(p,j)();}};svg.append(g);});
        const present=s.points.map((p,j)=>p?j:-1).filter(j=>j>=0);for(const [edge,j] of [['start',present[0]],['end',present.at(-1)]]){if(j===undefined||j<0||(edge==='end'&&j===present[0]))continue;text(svg,x(j)+(edge==='start'?7:-7),y(s.points[j].value)-9,String(s.points[j].value),'recipe-endpoint '+edge,edge==='start'?'start':'end');}
        text(svg,48,269,c.categories[0],'recipe-period');text(svg,276,269,c.categories.at(-1),'recipe-period','end');
      }
      panel.append(svg);root.append(panel);
    });
    root.append(el('p','recipe-reading',paired?(['forecast','target'].includes(c.observation)?'虚线空心为预测或目标；各面板使用同一尺度，不表示已经发生。':'空心：前期 · 实心：后期。各面板使用同一尺度；两次观测不表示中间路径。'):'各面板使用同一纵轴与时间轴。缺期、缺测断线，保留真实路径。'));
    return root;
  }
  return {adapt,seriesPlot,categoryColumns,categoryGeometry,categoryTicks,categoryViewportWidth};
})();
