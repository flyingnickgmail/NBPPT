/* Model-authored narrative references; presentation only, source values never change. */
window.ReportReading=(()=>{
  const selectors={qualified_dot:'.qualified-row',bar:'.ranking-item',line:'.line-points button',comparison:'.observation-row',matrix:'tbody tr',scatter:'.scatter-point',targets:'.target-row',roadmap:'.milestone',car:'.car-metric',worldmap:'.map-point'};
  function bindItems(chart,visual){
    if(['waterfall','mechanism','contrast','membership','evidence_strip'].includes(visual.kind))return;
    if(visual.kind==='multiseries'){
      chart.querySelectorAll('[aria-label]').forEach(node=>{const text=node.getAttribute('aria-label')||'';const i=visual.series.findIndex(s=>text.startsWith(s.label+' · '));if(i>=0)node.dataset.itemIndex=String(i);});
      return;
    }
    const selector=selectors[visual.kind];if(!selector)return;
    chart.querySelectorAll(selector).forEach((node,i)=>{if(node.dataset.itemIndex===undefined)node.dataset.itemIndex=String(i);});
    if(visual.kind==='scatter')chart.querySelectorAll('.scatter-detail,.scatter-direct-label').forEach((node,i)=>{if(node.dataset.itemIndex===undefined)node.dataset.itemIndex=String(i);});
  }
  function attach(section,model,figures,prose){
    const guide=model.reading;if(!guide||!guide.steps.length)return;
    const charts=[...figures.children].filter(chart=>Number(chart.dataset.visualIndex)>=0),paragraphs=[...section.querySelectorAll('[data-paragraph-index]')].sort((a,b)=>Number(a.dataset.paragraphIndex)-Number(b.dataset.paragraphIndex));
    charts.forEach(chart=>bindItems(chart,model.visuals[Number(chart.dataset.visualIndex)]));
    const el=(tag,cls,text)=>{const n=document.createElement(tag);n.className=cls;if(text!==undefined)n.textContent=text;return n;};
    const root=el('div','reading-guide'),head=el('div','reading-guide-head'),title=el('h3','',guide.question),mode=el('button','reading-mode','展开全部图表');
    head.append(el('span','reading-eyebrow','跟着问题读图'),title,mode);root.append(head);
    const controls=el('div','reading-steps');controls.setAttribute('role','group');controls.setAttribute('aria-label',guide.question);
    const caption=el('p','reading-caption');caption.setAttribute('aria-live','polite');
    let active=0,all=false,manual=false;
    const apply=(index,fromUser=false)=>{
      active=index;if(fromUser){manual=true;resume.textContent='随正文聚焦';}const step=guide.steps[index];
      root.dataset.activeStep=String(index);root.dataset.activeVisual=String(step.visual_index);
      [...controls.children].forEach((b,i)=>b.setAttribute('aria-pressed',String(i===index)));
      caption.textContent=step.explanation;
      charts.forEach(chart=>{const vi=Number(chart.dataset.visualIndex);chart.hidden=!all&&vi!==step.visual_index;chart.classList.toggle('reading-active-chart',vi===step.visual_index);chart.querySelectorAll('[data-item-index]').forEach(node=>{const focused=vi===step.visual_index&&step.item_indices.includes(Number(node.dataset.itemIndex));node.classList.toggle('reading-focus',focused);node.classList.toggle('reading-muted',vi===step.visual_index&&!focused);});});
      paragraphs.forEach((p,i)=>p.classList.toggle('reading-paragraph',i===step.paragraph_index));
    };
    guide.steps.forEach((step,i)=>{const button=el('button','reading-step');button.type='button';button.append(el('span','reading-step-number',String(i+1).padStart(2,'0')),el('strong','',step.title));button.onclick=()=>apply(i,true);controls.append(button);});
    mode.onclick=()=>{all=!all;mode.textContent=all?'返回分步读图':'展开全部图表';apply(active,true);};
    const resume=el('button','reading-resume','随正文聚焦');resume.type='button';resume.onclick=()=>{manual=false;resume.textContent='正在跟随正文';};
    root.append(controls,caption,resume);figures.before(root);section.classList.add('has-reading-guide');
    if(typeof IntersectionObserver==='function'){
      const observer=new IntersectionObserver(entries=>{if(manual)return;const found=entries.filter(e=>e.isIntersecting).sort((a,b)=>a.boundingClientRect.top-b.boundingClientRect.top)[0];if(!found)return;const pi=paragraphs.indexOf(found.target),si=guide.steps.findIndex(s=>s.paragraph_index===pi);if(si>=0)apply(si);},{rootMargin:'-20% 0px -55% 0px',threshold:0});
      paragraphs.forEach(p=>observer.observe(p));
    }
    // Resize-driven chart redraws must keep the original semantic series binding.
    if(typeof MutationObserver==='function'){const observer=new MutationObserver(()=>{charts.forEach(chart=>bindItems(chart,model.visuals[Number(chart.dataset.visualIndex)]));apply(active);});charts.forEach(c=>observer.observe(c,{childList:true,subtree:true}));}
    apply(0);
  }
  return {attach,bindItems};
})();
