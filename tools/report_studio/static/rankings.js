/* Shared linear scale for categorical observations. No sorting or data rewriting. */
window.ReportRankings=(()=>{
  function geometry(points){
    const [low,high]=ReportSeries.domain({series:[{points}]});
    const raw=(high-low)/4,power=10**Math.floor(Math.log10(raw));
    const step=[1,2,2.5,5,10].find(x=>x>=raw/power)*power;
    const ticks=[];for(let v=Math.ceil(low/step)*step;v<=high+step/100;v+=step)ticks.push(Number(v.toPrecision(12)));
    return {low,high,ticks,position:value=>(value-low)/(high-low)};
  }
  function render(c,show){
    const ns='http://www.w3.org/2000/svg',node=(tag,attrs={},text)=>{const n=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n;};
    const compact=window.matchMedia?.('(max-width:600px)').matches;
    const scale=geometry(c.points),width=compact?480:660,row=57,top=30,height=top+c.points.length*row+36,left=130,right=width-92,x=value=>left+scale.position(value)*(right-left);
    const svg=node('svg',{viewBox:`0 0 ${width} ${height}`,class:'ranking-chart',role:'group','aria-label':c.title+'；统一横轴，点击端点查看原文'});
    const baseline=top+c.points.length*row-12;
    scale.ticks.forEach(value=>{svg.append(node('line',{x1:x(value),x2:x(value),y1:10,y2:baseline,class:value===0?'ranking-zero':'ranking-grid'}),node('text',{x:x(value),y:baseline+25,'text-anchor':'middle',class:'ranking-tick'},new Intl.NumberFormat('zh-CN').format(value)));});
    c.points.forEach((p,i)=>{const y=top+i*row+12,px=x(p.value),g=node('g',{class:'ranking-item',tabindex:0,role:'button','aria-label':p.label+' '+p.value+c.unit});
      const label=node('text',{x:0,y:y+4,class:'ranking-label'});const chunks=/^[\x20-\x7E]{1,14}$/.test(p.label)?[p.label]:p.label.match(/.{1,6}/gu)||[''];chunks.slice(0,2).forEach((s,j)=>label.append(node('tspan',{x:0,dy:j?'1.3em':chunks.length>1?'-.45em':0},s+(j===1&&chunks.length>2?'…':''))));g.append(label);
      g.append(node('line',{x1:x(0),x2:px,y1:y,y2:y,class:'rank-stem','data-motion-origin':p.value<0?'right':'left'}),node('circle',{cx:px,cy:y,r:4,class:'rank-dot'}));
      g.append(node('text',{x:px+11,y:y+5,class:'ranking-value'},new Intl.NumberFormat('zh-CN',{maximumFractionDigits:15}).format(p.value)));
      // A generous transparent hit area preserves small-value and zero-value access.
      g.append(node('rect',{x:0,y:y-20,width,height:42,fill:'transparent'}));
      g.onclick=()=>show(p);g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();show(p);}};svg.append(g);
    });
    return svg;
  }
  return {render,geometry};
})();
