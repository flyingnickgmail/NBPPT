/* Same-scale reported values, approximation and one-sided bounds. */
window.ReportQualified=(()=>{
  const symbols={exact:'',approx:'≈',gt:'>',lt:'<',gte:'≥',lte:'≤'};
  const names={exact:'原文报告值',approx:'近似值',gt:'超过此值',lt:'低于此值',gte:'至少此值',lte:'至多此值'};
  const number=n=>Number(n).toLocaleString('zh-CN',{maximumFractionDigits:12});
  const label=(p,unit)=>symbols[p.relation]+number(p.value)+unit;
  function layout(points){
    const values=points.map(p=>p.value),min=Math.min(0,...values),max=Math.max(0,...values),span=max-min||1;
    const raw=span/4,power=10**Math.floor(Math.log10(raw)),step=([1,2,2.5,5,10].find(n=>n>=raw/power)||10)*power;
    const low=Math.floor(min/step)*step,high=Math.ceil(max/step)*step||step;
    const ticks=[];for(let v=low;v<=high+step*.001;v+=step)ticks.push(Math.abs(v)<step*.001?0:Number(v.toPrecision(12)));
    return {low,high,ticks,position:value=>7+(value-low)/(high-low)*86};
  }
  function render(c,{el,show}){
    const root=el('div','qualified-chart'+(c.points.length===2?' qualified-pair':'')),domain=layout(c.points);
    root.append(el('p','qualified-basis',c.basis));
    const scroll=el('div','qualified-scroll');scroll.tabIndex=0;scroll.setAttribute('aria-label',c.title+'；共同数轴，窄屏可横向滚动');
    const plot=el('div','qualified-plot');
    const guides=()=>{const track=el('span','qualified-track');for(const value of domain.ticks){const tick=el('span','qualified-guide'+(value===0?' zero':''));tick.style.left=domain.position(value)+'%';track.append(tick);}return track;};
    c.points.forEach((p,i)=>{
      const row=el('button','qualified-row'+(p.emphasis?' emphasis':''));row.type='button';row.dataset.itemIndex=String(i);row.setAttribute('aria-label',p.label+'：'+label(p,c.unit)+'，'+names[p.relation]+'；查看来源');
      const track=guides(),dot=el('span','qualified-mark '+p.relation);dot.style.left=domain.position(p.value)+'%';dot.setAttribute('aria-hidden','true');
      if(p.relation==='approx')dot.textContent='≈';else if(['gt','gte','lt','lte'].includes(p.relation))dot.textContent=['gt','gte'].includes(p.relation)?'›':'‹';
      const stem=el('span','qualified-stem');const zero=domain.position(0),end=domain.position(p.value);
      stem.style.left=Math.min(zero,end)+'%';stem.style.width=Math.abs(end-zero)+'%';stem.dataset.motionOrigin=p.value<0?'right':'left';
      for(const node of [stem,dot])node.dataset.motionOrder=String(i);
      track.append(stem,dot);const value=el('span','qualified-value',label(p,c.unit));value.dataset.motionOrder=String(i);value.append(el('small','',names[p.relation]));
      row.append(el('span','qualified-label',p.label),track,value);row.onclick=()=>show(p.label,label(p,c.unit)+' · '+names[p.relation],p.quote,p.source_ids);plot.append(row);
    });
    const axis=el('div','qualified-axis'),scale=el('span','qualified-track');for(const value of domain.ticks){const text=el('span','qualified-tick',number(value));text.style.left=domain.position(value)+'%';scale.append(text);}axis.append(el('span','','单位 '+c.unit),scale,el('span','','点击标记查证'));plot.append(axis);scroll.append(plot);root.append(scroll);
    root.append(el('p','qualified-legend','● 报告值　≈ 近似位置　‹ / › 上下界；尖括号只表示方向，不表示区间长度。'));
    return root;
  }
  return {render,layout,label};
})();
