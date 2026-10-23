/* Evidence is supplied by the resolver, never synthesized or rescaled by the renderer. */
window.ReportEditorialCover=(()=>{
  const el=(tag,cls,text)=>{const n=document.createElement(tag);n.className=cls;if(text!==undefined)n.textContent=text;return n;};
  function valueParts(value){
    if(/\d\s*(?:to|至|—|–|~|～|\/)\s*\d|\d\s*-\s*\d/i.test(value))return {prefix:'',number:value,suffix:''};
    const m=value.match(/^([^\d+−-]*)([+−-]?\d[\d,.]*)(.*)$/);
    return m?{prefix:m[1],number:m[2],suffix:m[3]}:{prefix:'',number:value,suffix:''};
  }
  function create(cover,facts,{evidence}){
    const root=el('figure','evidence-cover evidence-'+cover.layout);root.setAttribute('aria-label',cover.question);
    const heading=el('div','evidence-cover-head');heading.append(el('span','','主题观察'),el('span','','材料 → 判断'));
    const question=el('h2','evidence-question',cover.question),grid=el('div','evidence-plates');
    const first=facts[cover.items[0].ref],second=facts[cover.items[1].ref];
    const basis=el('p','evidence-period',first?.basis&&first.basis===second?.basis?first.basis.split(/[；;]/)[0]:'不同观察口径 · 详见各项原文');
    const animateNodes=[];
    cover.items.forEach((item,i)=>{
      const fact=facts[item.ref];if(!fact)return;
      const b=el('button','evidence-plate'+(i>1?' evidence-support':''));b.type='button';
      const meta=el('span','evidence-meta');meta.append(el('span','',String(i+1).padStart(2,'0')),el('span','',fact.source_ids.join(' / ')+' ↗'));
      const value=el('span','evidence-number'),parts=valueParts(fact.value);
      if(parts.number.length>7)value.classList.add('is-complex');
      value.append(el('small','',parts.prefix),el('strong','',parts.number),el('small','',parts.suffix));
      b.append(meta,el('span','evidence-label',fact.label.replace(/ · (材料读数|数值)$/,'')),value,el('span','evidence-caption',item.caption));
      b.setAttribute('aria-label',`${fact.label} ${fact.value}，查看证据`);
      b.onclick=()=>evidence(fact.label,fact.value+' · '+fact.context,fact.quote,fact.source_ids);
      grid.append(b);animateNodes.push(b);
    });
    const takeaway=el('p','evidence-takeaway',cover.takeaway),boundary=el('p','evidence-boundary',cover.boundary);
    const controls=el('div','evidence-cover-controls'),replay=el('button','','重播展开');replay.type='button';
    controls.append(el('span','','点击读数，查看原文'),replay);
    root.append(heading,question,basis,grid,takeaway,boundary,controls);
    let animations=[];
    const finish=()=>{animations.forEach(a=>a.cancel());animations=[];root.dataset.motion='complete';};
    const media=window.matchMedia?.('(prefers-reduced-motion: reduce)');
    function play(){
      finish();if(media?.matches||!root.animate)return;
      root.dataset.motion='playing';
      [question,...animateNodes,takeaway].forEach((node,i)=>{
        animations.push(node.animate([{opacity:.15,transform:'translateY(18px)',clipPath:'inset(0 0 30% 0)'},{opacity:1,transform:'translateY(0)',clipPath:'inset(0 0 0 0)'}],{duration:800,delay:i*190,easing:'cubic-bezier(.22,1,.36,1)',fill:'backwards'}));
      });
      Promise.all(animations.map(a=>a.finished.catch(()=>{}))).then(()=>{root.dataset.motion='complete';});
    }
    replay.onclick=play;media?.addEventListener?.('change',finish);window.addEventListener('beforeprint',finish);
    requestAnimationFrame(play);return root;
  }
  return {create,valueParts};
})();
