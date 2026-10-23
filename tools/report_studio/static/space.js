/* Spatial scene engine: bounded data → mesh → camera → material → narrative.
   Model output cannot introduce scripts, assets, textures or arbitrary markup. */
window.ReportSpace=(()=>{
  const TAU=Math.PI*2,rad=a=>a*Math.PI/180,clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
  const add=(a,b)=>a.map((n,i)=>n+b[i]);
  const rotate=(p,r)=>{let [x,y,z]=p;const [a,b,c]=r.map(rad);[y,z]=[y*Math.cos(a)-z*Math.sin(a),y*Math.sin(a)+z*Math.cos(a)];[x,z]=[x*Math.cos(b)+z*Math.sin(b),-x*Math.sin(b)+z*Math.cos(b)];return [x*Math.cos(c)-y*Math.sin(c),x*Math.sin(c)+y*Math.cos(c),z];};
  const normal=points=>{const a=points[1].map((x,i)=>x-points[0][i]),b=points[2].map((x,i)=>x-points[0][i]);const n=[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]],len=Math.hypot(...n)||1;return n.map(x=>x/len);};
  const project=(p,yaw)=>{const x=p[0]*Math.cos(yaw)-p[1]*Math.sin(yaw),y=p[0]*Math.sin(yaw)+p[1]*Math.cos(yaw);return {x,y:-y*.46-p[2]*.88,depth:y*.88-p[2]*.46};};
  function mesh(part){
    const faces=[],ring=(z,r=1,n=20)=>Array.from({length:n},(_,i)=>[Math.cos(i/n*TAU)*r,Math.sin(i/n*TAU)*r,z]);
    const extrude=outline=>{const lo=outline.map(([x,y])=>[x,y,-1]),hi=outline.map(([x,y])=>[x,y,1]);faces.push([...lo].reverse(),hi);lo.forEach((p,i)=>{const j=(i+1)%lo.length;faces.push([p,lo[j],hi[j],hi[i]]);});};
    if(part.shape==='rounded_box'){
      const outline=[];for(let corner=0;corner<4;corner++){const a=corner*Math.PI/2;for(let j=0;j<=4;j++){const theta=a+j*Math.PI/8;outline.push([Math.cos(a+Math.PI/4)>0?.78:-.78,Math.sin(a+Math.PI/4)>0?.78:-.78].map((v,k)=>v+.22*(k?Math.sin(theta):Math.cos(theta))));}}
      const levels=[[-1,.92],[-.88,1],[.88,1],[1,.92]],rings=levels.map(([z,r])=>outline.map(([x,y])=>[x*r,y*r,z]));
      faces.push([...rings[0]].reverse(),rings.at(-1));for(let k=0;k<rings.length-1;k++)rings[k].forEach((p,i)=>{const j=(i+1)%outline.length;faces.push([p,rings[k][j],rings[k+1][j],rings[k+1][i]]);});
    }
    if(part.shape==='lathe'){
      const profile=part.profile,n=32,rings=profile.map(([z,r])=>ring(z,r,n));
      if(profile[0][1]>0)faces.push([...rings[0]].reverse());if(profile.at(-1)[1]>0)faces.push(rings.at(-1));
      for(let k=0;k<rings.length-1;k++)for(let i=0;i<n;i++){const j=(i+1)%n;const face=profile[k][1]===0?[rings[k][i],rings[k+1][j],rings[k+1][i]]:profile[k+1][1]===0?[rings[k][i],rings[k][j],rings[k+1][i]]:[rings[k][i],rings[k][j],rings[k+1][j],rings[k+1][i]];faces.push(face);}
    }
    if(part.shape==='box')extrude([[-1,-1],[1,-1],[1,1],[-1,1]]);
    if(part.shape==='loft'){
      // Bounded cross-section interpolation preserves the supplied silhouette;
      // no spline overshoot, hidden asset or topic-specific model is involved.
      const stations=part.stations,n=24,rings=[];
      const contour=s=>Array.from({length:n},(_,i)=>{const a=i/n*TAU,c=Math.cos(a),v=Math.sin(a);return [s[0],s[1]*Math.sign(c)*Math.abs(c)**.48,(s[2]+s[3])/2+(s[3]-s[2])/2*Math.sign(v)*Math.abs(v)**.48];});
      stations.forEach((s,k)=>{if(k){const p=stations[k-1];rings.push(contour(s.map((v,j)=>(v+p[j])/2)));}rings.push(contour(s));});
      faces.push([...rings[0]].reverse(),rings.at(-1));
      for(let k=0;k<rings.length-1;k++)for(let i=0;i<n;i++){const j=(i+1)%n;faces.push([rings[k][i],rings[k][j],rings[k+1][j],rings[k+1][i]]);}
    }
    if(part.shape==='prism'){let profile=part.profile;const area=profile.reduce((s,p,i)=>s+p[0]*profile[(i+1)%profile.length][1]-profile[(i+1)%profile.length][0]*p[1],0);if(area<0)profile=[...profile].reverse();extrude(profile);}
    if(part.shape==='cylinder')extrude(ring(0).map(p=>p.slice(0,2)));
    if(part.shape==='arc'){
      const n=Math.ceil((part.sweep||270)/7.5),m=10,point=(i,j)=>{const a=i/n*rad(part.sweep||270),b=j/m*TAU;return [(.83+.17*Math.cos(b))*Math.cos(a),(.83+.17*Math.cos(b))*Math.sin(a),Math.sin(b)];};
      for(let i=0;i<n;i++)for(let j=0;j<m;j++)faces.push([point(i,j),point(i+1,j),point(i+1,j+1),point(i,j+1)]);
      faces.push(Array.from({length:m},(_,j)=>point(0,j)),Array.from({length:m},(_,j)=>point(n,m-j)));
    }
    if(part.shape==='ring'){
      const lo=ring(-1),hi=ring(1),li=ring(-1,.72),ha=ring(1,.72);
      lo.forEach((p,i)=>{const j=(i+1)%lo.length;faces.push([p,lo[j],hi[j],hi[i]],[li[j],li[i],ha[i],ha[j]],[hi[i],hi[j],ha[j],ha[i]],[lo[j],lo[i],li[i],li[j]]);});
    }
    if(part.shape==='ellipsoid'){
      const major=Math.max(...part.size)>1.5,rows=major?8:5,n=major?20:12,point=(j,i)=>{const lat=-Math.PI/2+j/rows*Math.PI,lon=i/n*TAU;return [Math.cos(lat)*Math.cos(lon),Math.cos(lat)*Math.sin(lon),Math.sin(lat)];};
      for(let j=0;j<rows;j++)for(let i=0;i<n;i++){const a=point(j,i),b=point(j,i+1),c=point(j+1,i+1),d=point(j+1,i);faces.push(j===0?[a,c,d]:j===rows-1?[a,b,c]:[a,b,c,d]);}
    }
    return faces.map(points=>points.map(p=>add(rotate(p.map((v,i)=>v*part.size[i]/2),part.rotation),part.center)));
  }
  const tones=window.ReportBrand?.tones||{ink:[36,37,34],accent:[163,79,45],silver:[148,143,134],chalk:[246,245,241],copper:[163,79,45]};
  const palette={...tones,blue:tones.accent};
  const shade=(tone,light,night=false)=>(night?(window.ReportBrand?.nightTones?.[tone==='blue'?'accent':tone]||palette[tone]):palette[tone]).map(n=>Math.round(clamp(n*light,0,255)));
  const color=(a,alpha=1)=>`rgba(${a.join(',')},${alpha})`;
  function surfaceColor(tone,material,light,night=false){
    const base=shade(tone,1,night),profiles={metal:[.72,.35,.16],glass:[.58,.24,.24],ceramic:[.77,.29,.045],paper:[.84,.18,.015],fiber:[.7,.25,.015],rubber:[.65,.23,.01]};
    const [ambient,diffuse,reflection]=profiles[material]||profiles.paper;
    const illumination=ambient+diffuse*clamp(light,0,1.4),reflect=reflection*clamp((light-.65)/.7,0,1);
    const studio=night?205:248;
    return base.map(v=>Math.round(clamp(v*illumination*(1-reflect)+studio*reflect,0,255)));
  }
  const svg=(tag,attrs={})=>{const e=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,String(v)));return e;};
  const el=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;};
  const ease=x=>{const k=clamp(x,0,1);return k*k*(3-2*k);};
  function openingState(order,seconds){
    const duration=order.length*.95+1.7,done=seconds>=duration,settle=ease((seconds-(duration-1.1))/1.1);
    const index=Math.min(order.length-1,Math.max(0,Math.floor(seconds/.95))),progress=clamp(seconds/duration,0,1);
    return {duration,done,index,progress,yaw:.59+.06*ease(progress),zoom:.97+.03*ease(progress),groups:Object.fromEntries(order.map((id,i)=>{const reveal=ease((seconds-i*.95)/.85),label=ease((seconds-i*.95-.5)/.55);return [id,{opacity:reveal,label,offset:(1-settle)*(1-reveal)*.22,lift:(1-reveal)*.18}];}))};
  }
  let serial=0;
  function create(scene,env){
    const shadeFor=(tone,light)=>shade(tone,light,document.body.classList.contains('night'));
    const media=matchMedia('(prefers-reduced-motion: reduce)'),beats=[...scene.beats].sort((a,b)=>a.section_index-b.section_index),views=[];
    const groups=new Map(scene.groups.map(g=>[g.id,g]));
    const faces=scene.parts.flatMap((part,partIndex)=>mesh(part).map((points,index)=>({points,part,partIndex,key:partIndex+'-'+index,normal:normal(points)})));
    const smoothNormals=window.ReportSpaceGPU?.smoothNormals(faces);
    let current=0,reading=0,following=true,paused=media.matches,mode=scene.opening?.length?'intro':'assembled',t=0,last=0,opening=0,pointer=0,dirty=true,raf=0;
    const order=scene.opening?.length?scene.opening:scene.groups.map(g=>g.id),duration=openingState(order,0).duration;
    // A single fixed camera scale is fitted to both assembled and exploded states.
    const all=faces.flatMap(f=>[0,1].flatMap(k=>f.points.map(p=>add(p,groups.get(f.part.group).explode.map(n=>n*k)))));
    const bounds=[.45,.65,.85].flatMap(yaw=>all.map(p=>project(p,yaw))),xs=bounds.map(p=>p.x),ys=bounds.map(p=>p.y);
    const cx=(Math.min(...xs)+Math.max(...xs))/2,cy=(Math.min(...ys)+Math.max(...ys))/2;
    const scale=Math.min(560/(Math.max(...xs)-Math.min(...xs)||1),440/(Math.max(...ys)-Math.min(...ys)||1));
    function choose(n){current=clamp(n,0,beats.length-1);following=false;update();}
    const evidence=id=>{const g=groups.get(id);env.evidence(g.label,g.fact,g.quote,g.source_ids);};
    function makeView(compact=false){
      const root=el('section','space-view'+(compact?' space-compact':''));root.setAttribute('aria-label',compact?'随文空间场景':'材料专属空间构图');
      const head=el('div','space-heading');head.append(el('span','space-kicker',compact?'本章解读':'主题解读 / 概念示意'),el('strong','',scene.title));root.append(head);
      const stage=svg('svg',{viewBox:'0 0 680 610',class:'space-stage',role:'img','aria-label':scene.concept});
      const id='space-'+(++serial),defs=svg('defs');stage.append(defs);
      const shadow=svg('radialGradient',{id:id+'-shadow'});shadow.append(svg('stop',{offset:0,'stop-color':'#393026','stop-opacity':'.18'}),svg('stop',{offset:1,'stop-color':'#393026','stop-opacity':0}));defs.append(shadow);
      const floor=svg('g',{class:'space-floor','aria-hidden':true});
      const shadows=scene.groups.map(g=>{const node=svg('ellipse',{fill:`url(#${id}-shadow)`});floor.append(node);return {group:g.id,node};});
      for(let i=0;i<11;i++){floor.append(svg('line',{x1:50+i*48,y1:455,x2:100+i*48,y2:565}),svg('line',{x1:50,y1:455+i*11,x2:630,y2:455+i*11}));}stage.append(floor);
      const grain=svg('pattern',{id:id+'-grain',width:7,height:7,patternUnits:'userSpaceOnUse'});grain.append(svg('path',{d:'M0 1H7 M0 5H7',stroke:'#fff','stroke-opacity':.28,'stroke-width':.5}));defs.append(grain);
      const grid=svg('pattern',{id:id+'-grid',width:9,height:9,patternUnits:'userSpaceOnUse'});grid.append(svg('path',{d:'M0 0H9V9',fill:'none',stroke:'#393026','stroke-opacity':.22,'stroke-width':.6}));defs.append(grid);
      const faceLayer=svg('g',{'aria-hidden':true}),labelLayer=svg('g',{class:'space-labels','aria-hidden':true});
      const gpuLayer=svg('foreignObject',{x:0,y:0,width:680,height:610,'aria-hidden':true,'pointer-events':'none'}),canvas=document.createElement('canvas');
      canvas.width=1360;canvas.height=1220;canvas.style.cssText='display:block;width:680px;height:610px';gpuLayer.append(canvas);
      const gpu=window.ReportSpaceGPU?.create(canvas,()=>{dirty=true;requestFrame();});stage.append(faceLayer,gpuLayer,labelLayer);
      const nodes=faces.map(f=>{const g=svg('g',{'data-group':f.part.group}),polygon=svg('polygon'),texture=f.part.detail!=='none'?svg('polygon'):null;g.append(polygon);if(texture)g.append(texture);faceLayer.append(g);return {g,polygon,texture};});
      const labels=scene.groups.map((g,i)=>{const path=svg('path',{fill:'none'}),dot=svg('circle',{r:3}),label=svg('text',{x:655,y:150+i*78});label.textContent=g.label;const sub=svg('text',{x:655,y:171+i*78,class:'space-label-note'});sub.textContent=String(i+1).padStart(2,'0')+' / 原文观察';labelLayer.append(path,dot,label,sub);return {path,dot,label,sub};});
      stage.addEventListener('pointermove',e=>{const rect=stage.getBoundingClientRect();if(!paused){pointer=((e.clientX-rect.left)/rect.width-.5)*.18;dirty=true;requestFrame();}});stage.addEventListener('pointerleave',()=>{if(!paused){pointer=0;dirty=true;requestFrame();}});
      root.append(stage);
      const openingCopy=el('div','space-opening');openingCopy.setAttribute('aria-live','off');root.append(openingCopy);
      const modes=el('div','space-modes');modes.setAttribute('aria-label','空间表现方式');for(const [key,label] of [['assembled','整体'],['exploded','分层展开'],['blueprint','工程线稿'],['intro','重播开场']]){const b=el('button','',label);b.dataset.mode=key;b.onclick=()=>{mode=key;opening=media.matches?duration:0;if(key==='intro'&&!media.matches)paused=false;update();};modes.append(b);}root.append(modes);
      const controls=el('div','space-controls'),prev=el('button','','‹'),select=el('select'),next=el('button','','›');prev.setAttribute('aria-label','上一章空间场景');next.setAttribute('aria-label','下一章空间场景');select.setAttribute('aria-label','选择空间场景章节');beats.forEach((b,i)=>{const o=el('option','',String(i+1).padStart(2,'0')+' / '+env.sections[b.section_index].title);o.value=String(i);select.append(o);});prev.onclick=()=>choose(current-1);next.onclick=()=>choose(current+1);select.onchange=()=>choose(Number(select.value));controls.append(prev,select,next);root.append(controls);
      const caption=el('div','space-caption'),title=el('h3'),copy=el('p'),focus=el('div','space-focus');caption.append(title,copy,focus);root.append(caption);
      const actions=el('div','space-actions'),motion=el('button'),follow=el('button'),source=el('button','','查看本章依据 ↗');motion.onclick=()=>{if(mode==='intro'&&opening>=duration){opening=0;paused=false;}else paused=!paused;update();};follow.onclick=()=>{following=true;current=reading;update();};source.onclick=()=>{const b=beats[current];env.evidence(b.title,b.caption,b.quote,b.source_ids);};actions.append(motion,follow,source);root.append(actions);
      const details=el('details','space-explanation');details.append(el('summary','','构图含义与表达边界'),el('p','',scene.concept));scene.groups.forEach(g=>details.append(el('p','',g.label+'：'+g.rationale)));root.append(details,el('p','space-boundary','概念插画 · 形状、位置与动态不表示统计数值'));
      const view={root,stage,openingCopy,faceLayer,gpuLayer,gpu,nodes,labels,shadows,defs,id,compact,modes,select,prev,next,title,copy,focus,motion,follow,visible:!compact,cache:new Map(),smooth:new Map()};views.push(view);new ResizeObserver(()=>{stage.setAttribute('viewBox','0 0 680 610');dirty=true;requestFrame();}).observe(root);return root;
    }
    const hero=makeView(),dock=makeView(true),mobile=el('aside','story-mobile space-mobile');mobile.hidden=true;const bar=el('button','story-mobile-toggle'),body=el('div','story-mobile-body');body.hidden=true;body.append(makeView(true));bar.setAttribute('aria-expanded','false');bar.onclick=()=>{body.hidden=!body.hidden;bar.setAttribute('aria-expanded',String(!body.hidden));update();};mobile.append(bar,body);
    function material(view,part,light){
      const bucket=Math.round(light*12),night=document.body.classList.contains('night'),key=part.tone+'-'+part.material+'-'+bucket+'-'+Number(night);if(view.cache.has(key))return view.cache.get(key);
      const id=view.id+'-'+key,g=svg('linearGradient',{id,x1:'0%',y1:'0%',x2:'65%',y2:'100%'});
      const metal=part.material==='metal',glass=part.material==='glass';
      const stops=metal?[[0,1.12],[.38,1.04],[.7,.98],[1,.88]]:glass?[[0,1.24],[.42,.98],[1,.82]]:[[0,1.035],[1,.96]];
      stops.forEach(([offset,k])=>g.append(svg('stop',{offset,'stop-color':color(surfaceColor(part.tone,part.material,bucket/12*k,night))})));view.defs.append(g);const result=`url(#${id})`;view.cache.set(key,result);return result;
    }
    function draw(view){
      const night=document.body.classList.contains('night');if(view.night!==night){view.smooth.forEach(g=>g.remove());view.smooth.clear();view.night=night;}
      const intro=openingState(order,media.matches?duration:opening),playing=mode==='intro'&&!intro.done;
      const yaw=(playing?intro.yaw:.65)+pointer,beat=beats[current],blue=mode==='blueprint';
      const progress=mode==='intro'?intro.progress:mode==='assembled'?0:1;
      const openingGroup=groups.get(order[intro.index]);
      view.openingCopy.hidden=mode!=='intro';
      const line=playing?String(intro.index+1).padStart(2,'0')+' / '+openingGroup.label+' · '+openingGroup.fact:groups.get(order[0]).fact;
      if(view.openingCopy.textContent!==line)view.openingCopy.textContent=line;
      view.root.dataset.opening=playing?'playing':'complete';
      const projected=faces.map((f,index)=>{
        const state=intro.groups[f.part.group],k=mode==='intro'?state.offset:progress,off=groups.get(f.part.group).explode.map((n,i)=>n*k+(mode==='intro'&&i===2?state.lift:0)),points=f.points.map(p=>project(add(p,off),yaw));
        const zoom=mode==='intro'?intro.zoom:1,screen=points.map(p=>[320+(p.x-cx)*scale*zoom,305+(p.y-cy)*scale*zoom]);
        const n=rotate(f.normal,[0,0,yaw*180/Math.PI]);
        return {f,index,screen,depths:points.map(p=>p.depth),front:n[1]*-.88+n[2]*.46>0,depth:points.reduce((s,p)=>s+p.depth,0)/points.length,light:clamp(.8+n[0]*-.18+n[1]*-.22+n[2]*.32,.4,1.35)};
      }).sort((a,b)=>b.depth-a.depth);
      const gpuActive=!blue&&view.gpu?.draw(projected,smoothNormals,rotate,yaw,night?(window.ReportBrand?.nightTones||palette):palette,id=>(mode==='intro'?intro.groups[id].opacity:1)*(view.compact&&!beat.focus.includes(id)?.38:1),night);
      view.faceLayer.style.display=gpuActive?'none':'';view.gpuLayer.style.display=gpuActive?'':'none';view.root.dataset.renderer=gpuActive?'depth-tested':'vector';
      // Shadows follow each semantic object's footprint, not a fixed floating oval.
      view.shadows.forEach(({group,node})=>{const points=projected.filter(p=>p.f.part.group===group).flatMap(p=>p.screen),xs=points.map(p=>p[0]),ys=points.map(p=>p[1]),x0=Math.min(...xs),x1=Math.max(...xs),y1=Math.max(...ys);
        node.setAttribute('cx',(x0+x1)/2);node.setAttribute('cy',y1+9);node.setAttribute('rx',Math.max(12,(x1-x0)*.53));node.setAttribute('ry',Math.max(6,(x1-x0)*.075));node.setAttribute('opacity',blue?0:(mode==='intro'?intro.groups[group].opacity:1)*.65);
      });
      // One continuous light field per curved solid avoids a highlight on every mesh tile.
      const solids=new Map();projected.forEach(item=>{if(item.f.part.shape!=='ellipsoid')return;const key=item.f.partIndex;if(!solids.has(key))solids.set(key,[]);solids.get(key).push(...item.screen);});
      if(!gpuActive)solids.forEach((points,key)=>{const part=scene.parts[key],xs=points.map(p=>p[0]),ys=points.map(p=>p[1]),x0=Math.min(...xs),x1=Math.max(...xs),y0=Math.min(...ys),y1=Math.max(...ys);let gradient=view.smooth.get(key);
        if(!gradient){gradient=svg('radialGradient',{id:view.id+'-solid-'+key,gradientUnits:'userSpaceOnUse',cx:0,cy:0,r:1,fx:-.4,fy:-.55});[[0,1.42],[.3,1.18],[.7,.94],[1,.64]].forEach(([offset,k])=>gradient.append(svg('stop',{offset,'stop-color':color(shadeFor(part.tone,k)),'stop-opacity':part.material==='glass'?.75:1})));view.defs.append(gradient);view.smooth.set(key,gradient);}
        gradient.setAttribute('gradientTransform',`translate(${(x0+x1)/2} ${(y0+y1)/2}) scale(${Math.max(1,(x1-x0)/2)} ${Math.max(1,(y1-y0)/2)})`);
      });
      const anchors=new Map();let cursor=view.faceLayer.firstChild;
      // Retain existing DOM order whenever possible; move only faces whose depth order changed.
      if(!gpuActive)projected.forEach(item=>{const node=view.nodes[item.index].g;if(node===cursor)cursor=cursor.nextSibling;else view.faceLayer.insertBefore(node,cursor);});
      projected.forEach(item=>{
        const {f,index,screen}=item,node=view.nodes[index],points=screen.map(p=>p.map(n=>n.toFixed(2)).join(',')).join(' '),active=playing?f.part.group===order[intro.index]:beat.focus.includes(f.part.group);
        if(gpuActive){for(const point of screen){const old=anchors.get(f.part.group);if(!old||point[1]>old[1])anchors.set(f.part.group,point);}return;}
        node.g.style.display=blue||item.front?'':'none';
        for(const point of screen){const old=anchors.get(f.part.group);if(!old||point[1]>old[1])anchors.set(f.part.group,point);}
        if(!blue&&!item.front)return;
        node.polygon.setAttribute('points',points);if(node.texture)node.texture.setAttribute('points',points);
        const curved=['loft','ellipsoid','cylinder','ring','lathe','arc'].includes(f.part.shape)&&Math.abs(f.normal[2])<.99;
        const fill=blue?'var(--surface)':f.part.shape==='ellipsoid'?`url(#${view.id}-solid-${f.partIndex})`:curved?color(surfaceColor(f.part.tone,f.part.material,item.light,night)):material(view,f.part,item.light);
        node.polygon.setAttribute('fill',fill);node.polygon.setAttribute('fill-opacity',blue?.12:1);
        node.polygon.setAttribute('stroke',blue?(active?'var(--accent)':'var(--muted)'):fill);
        node.polygon.setAttribute('stroke-width',blue?.65:.38);node.polygon.setAttribute('stroke-linejoin','round');
        if(node.texture)node.texture.setAttribute('fill',!blue&&f.part.detail!=='none'?`url(#${view.id}-${f.part.detail==='grid'?'grid':'grain'})`:'none');
        node.g.setAttribute('opacity',(mode==='intro'?intro.groups[f.part.group].opacity:1)*(view.compact&&!active?.38:1));
        for(const point of screen){const old=anchors.get(f.part.group);if(!old||point[1]>old[1])anchors.set(f.part.group,point);}
      });
      const labelOrder=[...scene.groups].sort((a,b)=>anchors.get(a.id)[0]-anchors.get(b.id)[0]).map(g=>g.id);
      scene.groups.forEach((g,i)=>{
        const a=anchors.get(g.id),l=view.labels[i],rank=labelOrder.indexOf(g.id),x=scene.groups.length===1?320:80+rank*480/(scene.groups.length-1),y=558;
        const active=playing?g.id===order[intro.index]:beat.focus.includes(g.id),opacity=mode==='intro'?intro.groups[g.id].label:1;
        [l.label,l.sub].forEach(n=>{n.setAttribute('x',x);n.setAttribute('text-anchor','middle');});l.label.setAttribute('y',y);l.sub.setAttribute('y',y+22);l.label.style.fontSize=scene.groups.length>3?'15px':view.root.clientWidth<420?'24px':'19px';
        [l.path,l.dot,l.label,l.sub].forEach(n=>n.setAttribute('opacity',opacity));
        l.path.setAttribute('d',`M${a[0]} ${a[1]}L${x} ${y-28}V${y-18}`);l.dot.setAttribute('cx',a[0]);l.dot.setAttribute('cy',a[1]);l.path.setAttribute('stroke',active?'var(--accent)':'var(--line)');l.dot.setAttribute('fill',active?'var(--accent)':'var(--muted)');l.label.setAttribute('fill',active?'var(--accent)':'var(--ink)');
      });
      view.root.dataset.mode=mode;view.stage.dataset.yaw=yaw.toFixed(5);view.stage.dataset.progress=progress.toFixed(4);
    }
    function update(){
      const b=beats[current];views.forEach(v=>{v.root.dataset.section=String(b.section_index);v.title.textContent=b.title;v.copy.textContent=b.caption;v.focus.replaceChildren();for(const id of (v.compact?b.focus:scene.groups.map(g=>g.id))){const g=groups.get(id),button=el('button',b.focus.includes(id)?'is-active':'',g.label+' ↗');button.onclick=()=>evidence(id);v.focus.append(button);}v.select.value=String(current);v.prev.disabled=current===0;v.next.disabled=current===beats.length-1;v.modes.querySelectorAll('button').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.mode===mode)));v.motion.textContent=media.matches?'已减少动态':mode!=='intro'?'静态检视':opening>=duration?'重播动态':paused?'播放动态':'暂停动态';v.motion.disabled=media.matches||mode!=='intro';v.motion.setAttribute('aria-pressed',String(!paused&&mode==='intro'&&opening<duration));v.follow.textContent=following?'正在随文':'恢复随文';v.follow.disabled=following;});
      bar.textContent=(body.hidden?'展开':'收起')+'随文构图 · '+b.title;dirty=true;requestFrame();
    }
    function tick(now){
      raf=0;if(last&&now-last<55){raf=requestAnimationFrame(tick);return;}const dt=last?Math.min((now-last)/1000,.06):0;last=now;const running=!paused&&!media.matches&&!document.hidden&&mode==='intro'&&opening<duration,visible=views.some(v=>v.visible);
      if(running&&visible){t+=dt;opening+=dt;if(opening>=duration)views.forEach(v=>{v.motion.textContent='重播动态';v.motion.setAttribute('aria-pressed','false');});}
      if(dirty||running)views.forEach(v=>{if(v.visible)draw(v);});dirty=false;
      if(running&&visible)raf=requestAnimationFrame(tick);else last=0;
    }
    function requestFrame(){if(!raf)raf=requestAnimationFrame(tick);}
    const io=new IntersectionObserver(entries=>{entries.forEach(entry=>{const v=views.find(v=>v.root===entry.target);v.visible=entry.isIntersecting;});dirty=true;requestFrame();});views.forEach(v=>io.observe(v.root));
    document.addEventListener('report-theme-change',()=>{dirty=true;requestFrame();});
    media.addEventListener('change',e=>{paused=e.matches;update();});document.addEventListener('visibilitychange',()=>{last=0;dirty=true;requestFrame();});update();
    return {hero,dock,mobile,resume(){following=true;current=reading;update();},setReading(index,visible=true){reading=clamp(index,0,beats.length-1);mobile.hidden=!visible;if(following&&current!==reading){current=reading;update();}}};
  }
  return {mesh,rotate,normal,project,shade,surfaceColor,openingState,create};
})();
