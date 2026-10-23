/* Render a constrained, material-designed vector scene. Model output is data only. */
window.ReportStory = (() => {
  const ns='http://www.w3.org/2000/svg';let serial=0;
  const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
  const svg=(tag,attrs)=>{const n=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));return n;};
  const positions=(scene,beat)=>Object.fromEntries(scene.objects.map(o=>{
    const selected=beat.focus.includes(o.id),spread=beat.composition==='unfold'?1.07:1;
    return [o.id,{x:500+(o.x-500)*spread,y:285+(o.y-285)*spread+(selected?(beat.composition==='balance'?-6:-14):4)}];
  }));
  const activeSection=(tops,anchor)=>{let index=0;tops.forEach((top,i)=>{if(top<=anchor)index=i;});return index;};
  const focusFrame=(coords,ids)=>{
    const points=ids.map(id=>coords[id]),xs=points.map(p=>p.x),ys=points.map(p=>p.y);
    const width=Math.max(500,Math.max(...xs)-Math.min(...xs)+280,(Math.max(...ys)-Math.min(...ys)+310)*1000/620),height=width*620/1000;
    return [(Math.min(...xs)+Math.max(...xs)-width)/2,(Math.min(...ys)+Math.max(...ys)-height)/2+15,width,height].join(' ');
  };
  const editorialPositions=(scene,beat,mode)=>{
    if(mode==='overview')return positions(scene,beat);
    return Object.fromEntries(scene.objects.map(o=>{const i=beat.focus.indexOf(o.id),count=beat.focus.length;
      return [o.id,i<0?{x:o.x,y:o.y}:{x:500+(i-(count-1)/2)*220,y:265}];}));
  };
  const assemblyState=(obj,assembly,beat,mode)=>{
    const action=(beat.actions||[]).find(a=>a.object_id===obj.id&&a.group===assembly.id);
    const reveal=mode==='structure'||(mode==='narrative'&&action?.effect==='reveal');
    return {transform:reveal?`translate(${assembly.dx}px,${assembly.dy}px) rotate(${assembly.angle}deg)`:'translate(0px,0px) rotate(0deg)',effect:mode==='narrative'&&action? action.effect:'none'};
  };
  function create(scene,env){
    const beats=[...scene.beats].sort((a,b)=>a.section_index-b.section_index),views=[];
    const semantic=scene.edition==='semantic';
    const media=matchMedia('(prefers-reduced-motion: reduce)');let current=0,reading=0,following=true,paused=media.matches,mode='narrative';
    const relationLabels={context:'相关背景',mechanism:'原文解释',uncertain:'条件 / 风险'};
    function choose(index){current=Math.max(0,Math.min(beats.length-1,index));following=false;paint();}
    function makeView(compact=false){
      const root=el('section','story-view'+(compact?' story-compact':'')+(semantic?' story-semantic':''));root.setAttribute('aria-label',compact?'随章节变化的阅读场景':'材料专属动态插画');
      const head=el('div','story-heading');head.append(el('span','story-kicker',compact?'随文场景':'材料专属构图'),el('strong','',scene.title));root.append(head);
      const stage=svg('svg',{viewBox:'0 0 1000 620',class:'story-stage',role:'group','aria-label':scene.concept});
      const defs=svg('defs',{}),uid='scene-'+(++serial),clip=svg('clipPath',{id:uid+'-clip'});clip.append(svg('rect',{x:-65,y:-65,width:290,height:290}));defs.append(clip);stage.append(defs);
      if(semantic)for(const color of ['paper','teal','clay','gold','ink','mist'])for(const material of ['metal','glass','paper']){
        const gradient=svg('linearGradient',{id:uid+'-'+color+'-'+material,x1:'0%',y1:'0%',x2:'100%',y2:'100%'});
        const base=`var(--scene-${color})`,stops=material==='metal'?[[0,`color-mix(in srgb,${base} 60%,white)`],[.38,base],[.54,`color-mix(in srgb,${base} 78%,white)`],[1,`color-mix(in srgb,${base} 72%,black)`]]:material==='glass'?[[0,`color-mix(in srgb,${base} 25%,transparent)`],[.5,`color-mix(in srgb,${base} 65%,transparent)`],[1,`color-mix(in srgb,${base} 35%,transparent)`]]:[[0,`color-mix(in srgb,${base} 70%,white)`],[1,base]];
        stops.forEach(([offset,color])=>{const stop=svg('stop',{offset});stop.style.stopColor=color;gradient.append(stop);});defs.append(gradient);
      }
      const backdrop=svg('g',{'aria-hidden':'true',class:'scene-ground'});
      backdrop.append(svg('ellipse',{cx:500,cy:345,rx:435,ry:240}));
      for(let i=0;i<5;i++)backdrop.append(svg('path',{d:`M${100+i*170} 90L${40+i*170} 550`,class:'scene-grid'}));stage.append(backdrop);
      const linkLayer=svg('g',{'aria-hidden':'true',class:'scene-links'}),objectLayer=svg('g',{});stage.append(linkLayer,objectLayer);
      const paths=new Map(),nodes=new Map(),assemblies=new Map();
      scene.links.forEach(link=>{const p=svg('path',{class:'scene-connection relation-'+link.relation,'data-link':link.id});paths.set(link.id,p);linkLayer.append(p);});
      scene.objects.forEach((obj,i)=>{
        const group=svg('g',{class:'scene-object',role:'button',tabindex:0,'aria-label':obj.label+'：'+obj.fact,'data-object':obj.id});
        group.append(svg('ellipse',{cx:80,cy:144,rx:77,ry:24,class:'scene-shadow'}),svg('ellipse',{cx:80,cy:148,rx:90,ry:32,class:'scene-aura'}));
        if(!semantic){const plate=svg('path',{d:'M0 137L78 111L160 137L82 164Z',class:'scene-plinth'});group.append(plate);}
        const drawing=svg('g',{'clip-path':`url(#${uid}-clip)`,class:'scene-drawing'});
        const groups=new Map();
        obj.parts.forEach(part=>{const attrs={class:'scene-part fill-'+part.fill+' stroke-'+part.stroke};
          if(part.kind==='rect')Object.assign(attrs,{x:part.x,y:part.y,width:part.width,height:part.height,rx:2});
          else if(part.kind==='ellipse')Object.assign(attrs,{cx:part.x+part.width/2,cy:part.y+part.height/2,rx:part.width/2,ry:part.height/2});
          else attrs.d=part.path;
          const shape=svg(part.kind,attrs);
          if(semantic){shape.style.strokeWidth=String(part.stroke_width??1);if(part.fill!=='none'&&part.surface&&part.surface!=='flat')shape.style.fill=`url(#${uid}-${part.fill}-${part.surface})`;
            const key=part.group||'body';if(!groups.has(key)){
              const a=(obj.assemblies||[]).find(a=>a.id===key),pose=svg('g',{class:'scene-assembly','data-group':key}),moving=svg('g',{class:'scene-motion'});
              const origin=`${a?.pivot_x??80}px ${a?.pivot_y??80}px`;pose.style.transformOrigin=origin;moving.style.transformOrigin=origin;pose.append(moving);drawing.append(pose);groups.set(key,{pose,moving,assembly:a});
            }groups.get(key).moving.append(shape);
          }else drawing.append(shape);
        });assemblies.set(obj.id,groups);group.append(drawing);
        const label=svg('text',{x:80,y:194,'text-anchor':'middle',class:'scene-node-label'});label.textContent=obj.label;group.append(label);
        const number=svg('text',{x:80,y:225,'text-anchor':'middle',class:'scene-node-number'});number.textContent=String(i+1).padStart(2,'0');group.append(number);
        const open=()=>env.evidence(obj.label,obj.fact,obj.quote,obj.source_ids);group.onclick=open;group.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open();}};
        nodes.set(obj.id,group);objectLayer.append(group);
      });root.append(stage);
      const modes=el('div','story-modes');
      if(semantic){modes.setAttribute('aria-label','插画表现方式');for(const [key,label] of [['narrative','随文'],['structure','结构展开'],['blueprint','精细线稿'],['overview','全景']]){const button=el('button','',label);button.dataset.mode=key;button.onclick=()=>{mode=key;paint();};modes.append(button);}root.append(modes);}
      const controls=el('div','story-controls'),previous=el('button','','‹'),select=el('select'),next=el('button','','›');
      previous.setAttribute('aria-label','预览上一章场景');next.setAttribute('aria-label','预览下一章场景');select.setAttribute('aria-label','选择章节场景');
      beats.forEach((beat,i)=>{const section=env.sections[beat.section_index],label=section.label&&!/^\d+$/.test(section.label)?section.label:section.title;const option=el('option','',String(i+1).padStart(2,'0')+' / '+label);option.value=String(i);select.append(option);});
      select.onchange=()=>choose(Number(select.value));previous.onclick=()=>choose(current-1);next.onclick=()=>choose(current+1);controls.append(previous,select,next);root.append(controls);
      const caption=el('div','story-caption'),title=el('h3'),copy=el('p'),focus=el('div','story-focus'),relations=el('div','story-relations');caption.append(title,copy,focus,relations);root.append(caption);
      const actions=el('div','story-actions'),follow=el('button'),motion=el('button'),source=el('button','','分镜依据 ↗'),jump=el('a','','阅读本章 ↓');
      follow.onclick=()=>{following=true;current=reading;paint();};motion.onclick=()=>{paused=!paused;paint();};source.onclick=()=>{const beat=beats[current];env.evidence(beat.title,beat.caption,beat.quote,beat.source_ids);};jump.onclick=()=>{following=true;};actions.append(follow,motion,source,jump);root.append(actions);
      const explanation=el('details','story-explanation'),explanationBody=el('div');explanation.append(el('summary','','图形与材料的关系'),explanationBody);if(semantic)root.append(explanation);
      root.append(el('p','story-boundary','概念构图 · 位置、大小与动效不表示数据变化'));
      const view={root,stage,compact,paths,nodes,assemblies,modes,select,previous,next,title,copy,focus,relations,follow,motion,jump,explanationBody};views.push(view);return root;
    }
    const hero=makeView(),dock=makeView(true),mobile=el('aside','story-mobile');mobile.setAttribute('aria-label','手机随文场景');mobile.hidden=true;
    const mobileBar=el('button','story-mobile-toggle'),mobileBody=el('div','story-mobile-body');mobileBody.hidden=true;mobileBody.append(makeView(true));mobileBar.setAttribute('aria-expanded','false');mobileBar.onclick=()=>{mobileBody.hidden=!mobileBody.hidden;mobileBar.setAttribute('aria-expanded',String(!mobileBody.hidden));paint();};mobile.append(mobileBar,mobileBody);
    function paint(){
      const beat=beats[current],coords=semantic?editorialPositions(scene,beat,mode):positions(scene,beat);
      for(const view of views){
        view.root.dataset.section=String(beat.section_index);view.root.dataset.motion=paused?'paused':'running';view.root.dataset.composition=beat.composition;view.root.dataset.view=mode;
        if(semantic){const width=beat.focus.length===1?260:beat.focus.length*220+40,frame=mode==='overview'?'0 0 1000 620':`${500-width/2} 120 ${width} 300`;view.stage.setAttribute('viewBox',frame);view.modes.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===mode)));}
        else if(view.compact)view.stage.setAttribute('viewBox',focusFrame(coords,beat.focus));
        view.nodes.forEach((node,id)=>{const p=coords[id],focused=beat.focus.includes(id),hidden=semantic?mode!=='overview'&&!focused:view.compact&&!focused;node.style.transform=`translate(${p.x-80}px,${p.y-80}px)`;node.classList.toggle('is-focus',focused);node.classList.toggle('is-hidden',hidden);node.setAttribute('tabindex',hidden?'-1':'0');node.setAttribute('aria-hidden',String(hidden));
          if(semantic){const obj=scene.objects.find(o=>o.id===id);view.assemblies.get(id).forEach(({pose,moving,assembly})=>{if(!assembly)return;const state=assemblyState(obj,assembly,beat,mode);pose.style.transform=state.transform;moving.dataset.effect=focused?state.effect:'none';});}
          else{const parts=node.querySelectorAll('.scene-part');parts.forEach((part,i)=>{const depth=beat.composition==='unfold'&&focused?i/Math.max(1,parts.length-1):0;part.style.transform=`translate(${depth*9}px,${-depth*26}px)`;});}});
        scene.links.forEach(link=>{const a=coords[link.origin],b=coords[link.destination],path=view.paths.get(link.id),bend=(a.x+b.x)/2;
          path.setAttribute('d',`M${a.x} ${a.y+25}C${bend} ${a.y-40} ${bend} ${b.y-40} ${b.x} ${b.y+25}`);path.classList.toggle('is-focus',beat.links.includes(link.id));});
        view.select.value=String(current);view.previous.disabled=current===0;view.next.disabled=current===beats.length-1;
        view.title.textContent=beat.title;view.copy.textContent=beat.caption;view.focus.replaceChildren();
        const focusIds=semantic&&mode==='overview'?scene.objects.map(o=>o.id):beat.focus;
        focusIds.forEach(id=>{const obj=scene.objects.find(o=>o.id===id),b=el('button','',obj.label+' ↗');b.onclick=()=>env.evidence(obj.label,obj.fact,obj.quote,obj.source_ids);view.focus.append(b);});
        if(semantic){view.explanationBody.replaceChildren();beat.focus.forEach(id=>{const obj=scene.objects.find(o=>o.id===id);view.explanationBody.append(el('p','',obj.label+'：'+obj.rationale));});}
        view.relations.replaceChildren();beat.links.forEach(id=>{const link=scene.links.find(l=>l.id===id),b=el('button','story-relation',relationLabels[link.relation]+' · '+link.label+' ↗');b.onclick=()=>env.evidence(link.label,relationLabels[link.relation],link.quote,link.source_ids);view.relations.append(b);});
        view.follow.textContent=following?'正在随文':'恢复随文';view.follow.disabled=following;view.motion.textContent=media.matches?'系统已减少动态':paused?'启用动效':'暂停动效';view.motion.disabled=media.matches;view.motion.setAttribute('aria-pressed',String(!paused));view.jump.href='#section-'+beat.section_index;
      }
      mobileBar.textContent=(mobileBody.hidden?'展开':'收起')+'随文场景 · '+String(beat.section_index+1).padStart(2,'0')+' '+beat.title;
    }
    media.addEventListener('change',event=>{paused=event.matches;paint();});
    const visibility=new IntersectionObserver(entries=>entries.forEach(entry=>{entry.target.dataset.visible=String(entry.isIntersecting);}));views.forEach(v=>visibility.observe(v.root));
    document.addEventListener('visibilitychange',()=>views.forEach(v=>{v.root.dataset.background=String(document.hidden);}));paint();
    return {hero,dock,mobile,resume(){following=true;current=reading;paint();},setReading(index,visible=true){reading=Math.max(0,Math.min(beats.length-1,index));mobile.hidden=!visible;if(following&&current!==reading){current=reading;paint();}}};
  }
  return {create,positions,activeSection,focusFrame,editorialPositions,assemblyState};
})();
