/* Progressive chart motion. The DOM is readable before, without and after animation. */
window.ReportChartMotion=(()=>{
  const selectors=[
    '.bar-fill','.series-fill','.recipe-column',
    '.line-plot polyline','.series-path','.recipe-line',
    '.line-plot circle','.series-point','.recipe-hit circle','.scatter-point','.rank-dot',
    '.observation-connector','.target-connector','.rank-stem','.observation-dot','.target-dot',
    '.qualified-stem','.qualified-mark','.qualified-value','.qualified-axis',
    '.peer-matrix tbody tr','.observation-row','.target-row','.qual-row','.evidence-entry'
  ].join(',');
  const has=(node,name)=>Boolean(node?.classList?.contains(name));
  function specFor(node,index=0){
    const delay=Math.min(index*42,360),common={duration:680,delay,easing:'cubic-bezier(.22,.7,.16,1)',fill:'both'};
    const rowDelay=Math.min(Number(node?.dataset?.motionOrder||0)*120,480);
    if(has(node,'qualified-axis'))return {kind:'scale',keyframes:[{opacity:.25},{opacity:1}],options:{...common,delay:0,duration:240}};
    if(has(node,'qualified-stem'))return {kind:'magnitude',keyframes:[{transform:'scaleX(0)',opacity:.2},{transform:'scaleX(1)',opacity:1}],options:{...common,delay:200+rowDelay,duration:720},origin:(node?.dataset?.motionOrigin||'left')+' center'};
    if(has(node,'qualified-mark'))return {kind:'bound',keyframes:[{opacity:0},{opacity:1}],options:{...common,delay:700+rowDelay,duration:240}};
    if(has(node,'qualified-value'))return {kind:'readout',keyframes:[{opacity:0,transform:'translateY(5px)'},{opacity:1,transform:'translateY(0)'}],options:{...common,delay:860+rowDelay,duration:280}};
    if(has(node,'mechanism-link-path'))return {kind:'relationship',keyframes:[{clipPath:'inset(0 100% 0 0)',opacity:.2},{clipPath:'inset(0 0 0 0)',opacity:1}],options:{...common,duration:760}};
    if(has(node,'waterfall-connector'))return {kind:'handoff',keyframes:[{clipPath:'inset(0 0 100% 0)',opacity:.2},{clipPath:'inset(0 0 0 0)',opacity:1}],options:{...common,duration:520}};
    if(has(node,'bar-fill')||has(node,'series-fill'))return {kind:'bar',keyframes:[{transform:'scaleX(0)',opacity:.35},{transform:'scaleX(1)',opacity:1}],options:common,origin:has(node,'negative')||node?.closest?.('.is-negative')?'right center':'left center'};
    if(has(node,'recipe-column'))return {kind:'column',keyframes:[{transform:'scaleY(0)',opacity:.3},{transform:'scaleY(1)',opacity:1}],options:common,origin:'center '+(node?.dataset?.motionOrigin||node?.getAttribute?.('data-motion-origin')||'bottom')};
    if(node?.tagName?.toLowerCase()==='polyline'||has(node,'series-path')||has(node,'recipe-line'))return {kind:'line',keyframes:[{clipPath:'inset(0 100% 0 0)',opacity:.28},{clipPath:'inset(0 0 0 0)',opacity:1}],options:{...common,duration:820}};
    if(has(node,'observation-connector')||has(node,'target-connector')||has(node,'rank-stem'))return {kind:'connector',keyframes:[{transform:'scaleX(0)',opacity:.25},{transform:'scaleX(1)',opacity:1}],options:{...common,duration:560},origin:(node?.dataset?.motionOrigin||node?.getAttribute?.('data-motion-origin')||'left')+' center'};
    if(has(node,'series-point')||has(node,'scatter-point')||has(node,'rank-dot')||has(node,'observation-dot')||has(node,'target-dot')||node?.tagName?.toLowerCase()==='circle')return {kind:'point',keyframes:[{transform:'scale(.55)',opacity:0},{transform:'scale(1)',opacity:1}],options:{...common,duration:430,delay:delay+180},origin:'center'};
    return {kind:'row',keyframes:[{transform:'translateY(8px)',opacity:0},{transform:'translateY(0)',opacity:1}],options:{...common,duration:480}};
  }
  function mount(root=document){
    const charts=root?.matches?.('.chart')?[root]:[...(root?.querySelectorAll?.('.chart')||[])],active=new Set(),media=typeof matchMedia==='function'?matchMedia('(prefers-reduced-motion: reduce)'):null;let observer=null,mutations=null,printing=false,reduced=Boolean(media?.matches);
    const suppressed=()=>printing||reduced;
    const finish=()=>{for(const animation of active){try{animation.finish();animation.cancel();}catch(_){}}active.clear();};
    const animateNode=(node,index)=>{if(suppressed()||node.dataset?.chartMotionPlayed==='true'||typeof node.animate!=='function')return;if(node.dataset)node.dataset.chartMotionPlayed='true';const spec=specFor(node,index);if(spec.origin){node.style.transformBox='fill-box';node.style.transformOrigin=spec.origin;}const animation=node.animate(spec.keyframes,spec.options);active.add(animation);Promise.resolve(animation.finished).catch(()=>{}).then(()=>{active.delete(animation);try{animation.cancel();}catch(_){}});};
    const reveal=chart=>{chart.dataset.chartMotionVisible='true';if(!suppressed())[...chart.querySelectorAll(selectors)].forEach(animateNode);};
    const replay=chart=>{if(suppressed())return;const targets=chart?[chart]:charts;targets.forEach(item=>{item.querySelectorAll(selectors).forEach(node=>{if(node.dataset)delete node.dataset.chartMotionPlayed;});reveal(item);});};
    const onMedia=event=>{reduced=Boolean(event.matches);if(reduced)finish();};
    const beforePrint=()=>{printing=true;finish();},afterPrint=()=>{printing=false;};
    if(media?.addEventListener)media.addEventListener('change',onMedia);else media?.addListener?.(onMedia);
    if(typeof addEventListener==='function'){addEventListener('beforeprint',beforePrint);addEventListener('afterprint',afterPrint);}
    if(typeof IntersectionObserver==='function'){observer=new IntersectionObserver(entries=>entries.forEach(entry=>{if(!entry.isIntersecting)return;reveal(entry.target);observer.unobserve(entry.target);}),{threshold:.22,rootMargin:'0px 0px -8% 0px'});charts.forEach(chart=>observer.observe(chart));}
    if(typeof MutationObserver==='function'){mutations=new MutationObserver(records=>{const changed=new Set();for(const record of records){const chart=record.target?.closest?.('.chart');if(chart?.dataset?.chartMotionVisible==='true')changed.add(chart);}changed.forEach(reveal);});charts.forEach(chart=>mutations.observe(chart,{childList:true,subtree:true}));}
    return {finish,replay,disconnect(){observer?.disconnect();mutations?.disconnect();finish();if(media?.removeEventListener)media.removeEventListener('change',onMedia);else media?.removeListener?.(onMedia);if(typeof removeEventListener==='function'){removeEventListener('beforeprint',beforePrint);removeEventListener('afterprint',afterPrint);}}};
  }
  return {mount,specFor};
})();
