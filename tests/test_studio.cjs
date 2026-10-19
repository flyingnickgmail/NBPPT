const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');

function harness(fetch, crypto = webcrypto) {
  const nodes = new Map(), storage = new Map(), timers = new Set();
  function element(tag = '') {
    return {
      tagName:String(tag).toUpperCase(), hidden:false, disabled:false, children:[], value:'', textContent:'', open:false,
      selectedOptions:[{text:'自动匹配'}], className:'',
      setAttribute(k,v){ this[k]=v; }, removeAttribute(k){ delete this[k]; }, replaceChildren(...x){ this.children=x; },
      append(...x){ this.children.push(...x); }, add(x){ this.children.push(x); }, showModal(){ this.open=true; }, close(){ this.open=false; },
      focus(){ this.focused=true; }, pause(){ this.paused=true; }, load(){ this.loads=(this.loads || 0)+1; }
    };
  }
  const get = id => {
    if (!nodes.has(id)) nodes.set(id, element());
    const node = nodes.get(id);
    if (id === 'style' && !node.value) { node.value='auto'; node.selectedOptions=[{text:'自动匹配'}]; }
    if (id === 'pages' && !node.value) { node.value='0'; node.selectedOptions=[{text:'自动页数'}]; }
    if (id === 'video-duration' && !node.value) { node.value='30'; node.selectedOptions=[{text:'30 秒'}]; }
    if (id === 'video-ratio' && !node.value) { node.value='16:9'; node.selectedOptions=[{text:'16:9 横屏'}]; }
    return node;
  };
  const ctx = vm.createContext({
    document:{getElementById:get, createElement:tag=>element(tag)},
    sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,String(v)),removeItem:k=>storage.delete(k)},
    fetch, URL, Option:class { constructor(text,value){ this.text=text; this.value=value; } }, crypto, TextEncoder, Uint8Array,
    location:{origin:'http://test'}, setTimeout:fn=>{timers.add(fn);return fn;}, clearTimeout:fn=>timers.delete(fn)
  });
  let source = fs.readFileSync('gateway/static/studio.js','utf8');
  source = source.slice(0, source.lastIndexOf("updateMode('ppt');"));
  vm.runInContext(source + `
    globalThis.testApi={
      api,controls,clearSession,initialize,activateTask,pollKind,submitKind,retryKind,updateMode,renderVideo,
      set(s={}){
        authenticated=s.auth ?? true; canGenerate=s.canGenerate ?? true; ready=s.ready ?? true; busy=s.busy ?? false;
        userId=s.userId ?? 'owner'; capabilities=s.capabilities ?? {delivery_modes:{ppt:{supported:true,freeze_credits:60},video:{supported:true,freeze_credits:80}}};
        if ('mode' in s) mode=s.mode; if ('activeTask' in s) activeTask=s.activeTask;
        if ('pptState' in s) states.ppt=s.pptState; if ('videoState' in s) states.video=s.videoState;
      },
      get(){return {activeTask,authenticated,ready,mode,states:{ppt:states.ppt,video:states.video},deliveries:{ppt:deliveries.ppt,video:deliveries.video}}}
    };`, ctx);
  return {api:ctx.testApi, get, timers, storage};
}

const response = (body,status=200) => ({ok:status<400,status,json:async()=>body});
const tick = () => new Promise(resolve=>setImmediate(resolve));
const sourceText = '完整测试内容，展示问题进展以及下周的责任分工和验收标准。';

test('Claude selection is advertised explicitly and stays on the PPT side of composite jobs', async () => {
  const requests=[];
  const h=harness(async(path,options={})=>{
    if(path==='/api/jobs') {
      const payload=JSON.parse(options.body);requests.push(payload);
      return response({job_id:payload.task_type==='ppt'?'ppt_0123456789':'video_abcdef0123'});
    }
    if(path==='/api/wallet') return response({user:{credits_available:1800}});
    return response({status:'RUNNING',stage:'queued'});
  });
  h.api.set({capabilities:{delivery_modes:{ppt:{supported:true,execution_modes:['codex_cli','claude_cli']},video:{supported:true}}}});
  h.api.updateMode('composite'); h.get('source').value=sourceText;h.get('ppt-engine').value='claude_cli';
  h.api.controls(); assert.equal(h.get('claude-engine-option').disabled,false);
  await h.get('brief').onsubmit({preventDefault(){}});await tick();
  assert.equal(requests.length,2);
  assert.equal(requests.find(x=>x.task_type==='ppt').execution_mode,'claude_cli');
  assert.equal(requests.find(x=>x.task_type==='video').execution_mode,'codex_cli');
  assert.equal(h.api.get().activeTask.input.execution_mode,'claude_cli');
  h.api.set();h.get('ppt-engine').value='claude_cli';h.api.controls();
  assert.equal(h.get('claude-engine-option').disabled,true);
  assert.equal(h.get('ppt-engine').value,'codex_cli');
});

test('changing mode while digest is pending cannot add an unrequested video job', async () => {
  let release;
  const gate = new Promise(resolve => {release=resolve;});
  const requests=[];
  const crypto={randomUUID:()=>webcrypto.randomUUID(),subtle:{digest:async(...args)=>{await gate;return webcrypto.subtle.digest(...args);}}};
  const h=harness(async(path,options={})=>{
    if(path==='/api/jobs'){requests.push(JSON.parse(options.body));return response({job_id:'ppt_0123456789'});}
    if(path==='/api/wallet') return response({user:{credits_available:1940}});
    return response({status:'RUNNING',stage:'queued'});
  },crypto);
  h.api.set();h.api.updateMode('ppt');h.get('source').value=sourceText;
  const submitted=h.get('brief').onsubmit({preventDefault(){}});
  h.get('mode-composite').onclick();
  assert.equal(h.get('mode-composite').disabled,true);
  release();await submitted;await tick();
  assert.equal(h.api.get().activeTask.mode,'ppt');
  assert.equal(requests.length,1);assert.equal(requests[0].task_type,'ppt');
});
async function signature(mode,input) {
  const bytes=await webcrypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify({mode,input})));
  return Array.from(new Uint8Array(bytes),b=>b.toString(16).padStart(2,'0')).join('');
}

test('video submission sends the declared video contract and does not invent progress', async () => {
  const requests=[];
  const h=harness(async(path,options={})=>{
    if(path==='/api/jobs'){ requests.push(JSON.parse(options.body)); return response({job_id:'video_abcdef0123'}); }
    if(path==='/api/jobs/video_abcdef0123') return response({status:'RUNNING',stage:'generating',message:'正在生成视频'});
    if(path==='/api/wallet') return response({user:{credits_available:920}});
    throw Error(`unexpected ${path}`);
  });
  h.api.set(); h.api.updateMode('video'); h.get('source').value=sourceText; h.get('video-duration').value='45'; h.get('video-ratio').value='9:16';
  await h.get('brief').onsubmit({preventDefault(){}}); await tick();
  assert.equal(requests[0].task_type,'video'); assert.equal(requests[0].video_duration_sec,45); assert.equal(requests[0].video_aspect_ratio,'9:16');
  assert.equal(requests[0].video_voice,'melo'); assert.equal(requests[0].video_narration,true); assert.equal(requests[0].video_subtitles,true);
  assert.match(requests[0].request_id,/^[0-9a-f-]{36}$/); assert.equal(h.get('video-progress').textContent,'正在生成视频');
  assert.equal(h.get('video-meter').value,undefined); assert.equal(h.get('video-meter').hidden,false);
});

test('partial composite submission retries only the missing video with the same request id', async () => {
  const requests=[]; let videoAttempts=0;
  const h=harness(async(path,options={})=>{
    if(path==='/api/jobs'){
      const body=JSON.parse(options.body); requests.push(body);
      if(body.task_type==='ppt') return response({job_id:'ppt_0123456789'});
      if(++videoAttempts===1) throw Error('connection lost');
      return response({job_id:'video_abcdef0123'});
    }
    if(path.startsWith('/api/jobs/')) return response({status:'RUNNING',stage:'queued'});
    if(path==='/api/wallet') return response({user:{credits_available:800}});
    throw Error(`unexpected ${path}`);
  });
  h.api.set(); h.api.updateMode('composite'); h.get('source').value=sourceText;
  await h.get('brief').onsubmit({preventDefault(){}}); await tick();
  assert.equal(h.api.get().activeTask.jobs.ppt,'ppt_0123456789'); assert.equal(h.api.get().activeTask.jobs.video,undefined);
  assert.equal(h.get('task-state').textContent,'部分失败');
  await h.get('retry-video').onclick(); await tick();
  const ppt=requests.filter(x=>x.task_type==='ppt'), video=requests.filter(x=>x.task_type==='video');
  assert.equal(ppt.length,1); assert.equal(video.length,2); assert.equal(video[0].request_id,video[1].request_id);
  assert.equal(h.api.get().activeTask.jobs.video,'video_abcdef0123');
});

test('resubmitting the same partial composite retries the failed output without charging the completed PPT again', async () => {
  const calls=[];
  const h=harness(async(path,options={})=>{
    calls.push(path);
    if(path==='/api/jobs/video_abcdef0123/retry') return response({job_id:'video_1111111111'});
    if(path==='/api/jobs/ppt_0123456789') return response({status:'COMPLETED',stage:'ready',credits_charged:60});
    if(path==='/api/jobs/ppt_0123456789/artifacts') return response({slide_count:1,artifacts:{slide_preview_urls:['/artifacts/ppt_0123456789/slide.png'],pptx_url:'/artifacts/ppt_0123456789/deck.pptx',html_deck_url:'/artifacts/ppt_0123456789/deck.html'}});
    if(path==='/api/jobs/video_1111111111') return response({status:'RUNNING',stage:'queued'});
    if(path==='/api/wallet') return response({user:{credits_available:850}});
    throw Error(`unexpected ${path}`);
  });
  const input={source:sourceText,template_id:'auto',slide_count:0,video_duration_sec:30,video_aspect_ratio:'16:9'};
  h.api.set({activeTask:{mode:'composite',input,signature:await signature('composite',input),jobs:{ppt:'ppt_0123456789',video:'video_abcdef0123'},request_ids:{},submit_errors:{}},pptState:{status:'COMPLETED'},videoState:{status:'FAILED'}});
  h.api.updateMode('composite'); h.get('source').value=sourceText;
  await h.get('brief').onsubmit({preventDefault(){}}); await tick();
  assert.equal(calls.filter(path=>path==='/api/jobs').length,0); assert.equal(calls.filter(path=>path.endsWith('/retry')).length,1);
  assert.equal(h.api.get().activeTask.jobs.ppt,'ppt_0123456789'); assert.equal(h.api.get().activeTask.jobs.video,'video_1111111111');
});

test('one completed composite artifact remains available when the other job fails', async () => {
  const h=harness(async path=>{
    if(path==='/api/jobs/ppt_0123456789') return response({status:'COMPLETED',stage:'ready',credits_charged:60,slide_count:1});
    if(path==='/api/jobs/ppt_0123456789/artifacts') return response({slide_count:1,artifacts:{slide_preview_urls:['/artifacts/ppt_0123456789/slide.png'],pptx_url:'/artifacts/ppt_0123456789/deck.pptx',html_deck_url:'/artifacts/ppt_0123456789/deck.html'}});
    if(path==='/api/jobs/video_abcdef0123') return response({status:'FAILED',stage:'rendering',message:'视频编码失败'});
    if(path==='/api/wallet') return response({user:{credits_available:940}});
    throw Error(`unexpected ${path}`);
  });
  h.api.set(); h.api.activateTask({mode:'composite',jobs:{ppt:'ppt_0123456789',video:'video_abcdef0123'},request_ids:{},submit_errors:{},input:{source:sourceText}});
  await tick(); await tick();
  assert.equal(h.get('task-state').textContent,'部分完成'); assert.equal(h.get('ppt-panel').hidden,false);
  assert.equal(h.get('download').href,'/artifacts/ppt_0123456789/deck.pptx'); assert.equal(h.get('retry-video').hidden,false);
});

test('a late video poll cannot overwrite a newer terminal state', async () => {
  const pending=[];
  const h=harness(path=>path==='/api/wallet' ? Promise.resolve(response({user:{credits_available:900}})) : new Promise(resolve=>pending.push(resolve)));
  h.api.set({activeTask:{mode:'video',jobs:{video:'video_abcdef0123'},request_ids:{},submit_errors:{},input:{}}});
  const old=h.api.pollKind('video'), recent=h.api.pollKind('video');
  pending[1](response({status:'FAILED',stage:'rendering',message:'失败'})); await recent;
  pending[0](response({status:'RUNNING',stage:'generating'})); await old;
  assert.equal(h.api.get().states.video.status,'FAILED'); assert.equal(h.timers.size,0);
});

test('failed video retry reuses its idempotency key after a lost response', async () => {
  const ids=[];
  const h=harness(async(path,options)=>{ ids.push(JSON.parse(options.body).request_id); throw Error('lost response'); });
  h.api.set({activeTask:{mode:'video',jobs:{video:'video_abcdef0123'},request_ids:{},submit_errors:{},input:{}},videoState:{status:'FAILED'}});
  await h.get('retry-video').onclick(); await h.get('retry-video').onclick();
  assert.equal(ids.length,2); assert.equal(ids[0],ids[1]); assert.equal(h.get('retry-video').disabled,false);
});

test('video preview uses same-origin validated mp4, poster and subtitles', () => {
  const h=harness(async()=>response({}));
  h.api.set({activeTask:{mode:'video',jobs:{video:'video_abcdef0123'},request_ids:{},submit_errors:{},input:{}}});
  h.api.renderVideo({artifacts:{mp4_url:'/artifacts/video_abcdef0123/result.mp4',video_poster_url:'/artifacts/video_abcdef0123/poster.jpg',subtitles_url:'/artifacts/video_abcdef0123/subtitles.vtt'}},'video_abcdef0123');
  assert.equal(h.get('video-player').src,'/artifacts/video_abcdef0123/result.mp4'); assert.equal(h.get('video-player').poster,'/artifacts/video_abcdef0123/poster.jpg');
  assert.equal(h.get('video-subtitles').src,'/artifacts/video_abcdef0123/subtitles.vtt'); assert.equal(h.get('video-download').href,'/artifacts/video_abcdef0123/result.mp4');
  assert.equal(h.get('video-panel').hidden,false);
  h.api.renderVideo({video:{subtitles_burned:true},artifacts:{mp4_url:'/artifacts/video_abcdef0123/result.mp4',subtitles_url:'/artifacts/video_abcdef0123/subtitles.vtt'}},'video_abcdef0123');
  assert.equal(h.get('video-subtitles').default,false);
});

test('studio markup has unique control ids', () => {
  const ids = [...fs.readFileSync('gateway/static/index.html','utf8').matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);
  assert.equal(ids.length, new Set(ids).size);
});

test('chosen voice and explicit silent captions options are submitted', async () => {
  const requests=[];
  const h=harness(async(path,options={})=>{
    if(path==='/api/jobs'){requests.push(JSON.parse(options.body));return response({job_id:'video_abcdef0123'});}
    if(path==='/api/wallet')return response({user:{credits_available:920}});
    return response({status:'RUNNING'});
  });
  h.api.set();h.api.updateMode('video');h.get('source').value=sourceText;
  h.get('video-voice').value='kokoro_male';h.get('video-narration').value='off';h.get('video-captions').value='off';
  await h.get('brief').onsubmit({preventDefault(){}});await tick();
  assert.equal(requests[0].video_voice,'kokoro_male');
  assert.equal(requests[0].video_narration,false);assert.equal(requests[0].video_subtitles,false);
});

test('401 clears PPT and video private previews, draft and active task', async () => {
  const h=harness(async()=>response({detail:'expired'},401)); h.api.set({activeTask:{mode:'composite',jobs:{ppt:'ppt_0123456789',video:'video_abcdef0123'},request_ids:{},submit_errors:{},input:{}}});
  h.get('slide').src='/private.png'; h.get('download').href='/private.pptx'; h.get('video-player').src='/private.mp4'; h.get('video-player').poster='/private.jpg'; h.get('video-subtitles').src='/private.vtt'; h.get('source').value='private source';
  await assert.rejects(h.api.api('/api/session'));
  assert.equal(h.api.get().authenticated,false); assert.equal(h.api.get().activeTask,null); assert.equal(h.get('source').value,'');
  for(const [id,attr] of [['slide','src'],['download','href'],['video-player','src'],['video-player','poster'],['video-subtitles','src']]) assert.equal(h.get(id)[attr],undefined);
  assert.equal(h.get('video-player').paused,true); assert.equal(h.get('submit').disabled,true); assert.equal(h.get('login').open,true);
});

test('read-only credentials cannot submit or retry either output', async () => {
  let calls=0; const h=harness(async()=>{calls++;return response({});}); h.api.set({canGenerate:false}); h.api.controls();
  assert.equal(h.get('submit').disabled,true); assert.equal(h.get('retry-ppt').disabled,true); assert.equal(h.get('retry-video').disabled,true);
  await h.get('brief').onsubmit({preventDefault(){}}); await h.get('retry-ppt').onclick(); await h.get('retry-video').onclick(); assert.equal(calls,0);
});

test('switching users clears the previous users draft and both private previews', async () => {
  const h=harness(async path=>{
    if(path==='/api/session') return response({user_id:'new-owner',can_generate:true,admin:false});
    if(path==='/api/templates') return response({templates:[{id:'auto',name:'自动匹配'}]});
    if(path==='/api/capabilities') return response({delivery_modes:{ppt:{supported:true,freeze_credits:60},video:{supported:true,freeze_credits:80}}});
    if(path==='/api/wallet') return response({user:{credits_available:1000}});
    throw Error(`unexpected ${path}`);
  });
  h.api.set({userId:'old-owner',activeTask:{mode:'video',jobs:{video:'video_abcdef0123'},request_ids:{},submit_errors:{},input:{}}});
  h.get('source').value='old private draft'; h.get('slide').src='/old.png'; h.get('video-player').src='/old.mp4';
  await h.api.initialize();
  assert.equal(h.get('source').value,''); assert.equal(h.get('slide').src,undefined); assert.equal(h.get('video-player').src,undefined); assert.equal(h.api.get().activeTask,null);
});

test('legacy single-job session value is restored after initialization', async () => {
  const h=harness(async path=>{
    if(path==='/api/session') return response({user_id:'owner',can_generate:true,admin:false});
    if(path==='/api/templates') return response({templates:[{id:'auto',name:'自动匹配'}]});
    if(path==='/api/capabilities') return response({delivery_modes:{ppt:{supported:true,freeze_credits:60},video:{supported:true,freeze_credits:80}}});
    if(path==='/api/wallet') return response({user:{credits_available:1000}});
    if(path==='/api/jobs/ppt_0123456789') return response({status:'RUNNING',stage:'planning'});
    throw Error(`unexpected ${path}`);
  });
  h.storage.set('nbppt-active-owner','ppt_0123456789'); await h.api.initialize(); await tick();
  assert.equal(h.api.get().activeTask.jobs.ppt,'ppt_0123456789'); assert.equal(h.get('task-view').hidden,false);
});

test('Claude cooldown blocks only Claude PPT and keeps the selected provider for manual recovery', async () => {
  const h=harness(async()=>response({}));
  const caps={delivery_modes:{ppt:{supported:true,execution_modes:['codex_cli','claude_cli']},video:{supported:true}},providers:{claude_cli:{state:'cooldown',retry_after_seconds:60,message:'冷却中'}}};
  h.api.set({capabilities:caps});h.get('ppt-engine').value='claude_cli';h.api.updateMode('ppt');
  assert.equal(h.get('submit').disabled,true);
  assert.equal(h.get('ppt-engine').value,'claude_cli');
  assert.match(h.get('claude-status').textContent,/60/);
  h.api.updateMode('video');assert.equal(h.get('submit').disabled,false);
  caps.providers.claude_cli={state:'ready',message:'可以生成'};h.api.updateMode('ppt');assert.equal(h.get('submit').disabled,false);
});

test('a 429 admission response exposes the circuit and does not fall back to Codex', async () => {
  const h=harness(async()=>response({detail:{provider_state:'cooldown',retry_after_seconds:120,message:'已限流'}},429));
  h.api.set({capabilities:{delivery_modes:{ppt:{supported:true,execution_modes:['codex_cli','claude_cli']},video:{supported:true}}}});
  h.get('ppt-engine').value='claude_cli';h.api.updateMode('ppt');
  await assert.rejects(()=>h.api.api('/api/jobs'),/已限流/);
  assert.equal(h.get('submit').disabled,true);assert.equal(h.get('ppt-engine').value,'claude_cli');
});

test('a late cooldown response cannot disable a newly signed-in users provider', async () => {
  let release;const gate=new Promise(r=>release=r);
  const h=harness(async()=>{await gate;return response({detail:{provider_state:'blocked',message:'暂停'}},503);});
  const caps={delivery_modes:{ppt:{supported:true,execution_modes:['codex_cli','claude_cli']},video:{supported:true}},providers:{claude_cli:{state:'ready',message:'ready'}}};
  h.api.set({capabilities:caps});const pending=h.api.api('/api/jobs').catch(()=>{});
  h.api.clearSession();h.api.set({userId:'new-user',capabilities:caps});h.get('ppt-engine').value='claude_cli';
  release();await pending;h.api.controls();assert.equal(h.get('submit').disabled,false);
});

test('a provider failure in a polled task disables Claude retry without hiding the failure refund', async () => {
  const h=harness(async(path)=>path==='/api/providers/claude/status'?response({state:'blocked',message:'已暂停'}):response({job_id:'ppt_0123456789',status:'FAILED',message:'冻结算力已退回',provider:{state:'blocked',retry_after_seconds:0}}));
  const task={mode:'ppt',jobs:{ppt:'ppt_0123456789'},input:{source:sourceText,execution_mode:'claude_cli'},request_ids:{ppt:'req'},submit_errors:{}};
  h.api.set({activeTask:task,capabilities:{delivery_modes:{ppt:{supported:true,execution_modes:['codex_cli','claude_cli']},video:{supported:true}}}});
  await h.api.pollKind('ppt');assert.equal(h.get('retry-ppt').disabled,true);
  assert.equal(h.api.get().states.ppt.status,'FAILED');
});

test('an old failed jobs cooldown cannot disable retry after the live circuit recovers', async () => {
  const h=harness(async(path)=>path==='/api/providers/claude/status'?response({state:'ready',message:'可以生成'}):response({status:'FAILED',provider:{state:'cooldown',retry_after_seconds:60}}));
  const task={mode:'ppt',jobs:{ppt:'ppt_0123456789'},input:{source:sourceText,execution_mode:'claude_cli'},request_ids:{ppt:'req'},submit_errors:{}};
  h.api.set({activeTask:task,capabilities:{delivery_modes:{ppt:{supported:true,execution_modes:['codex_cli','claude_cli']},video:{supported:true}}}});
  await h.api.pollKind('ppt');assert.equal(h.get('retry-ppt').disabled,false);
});

test('hybrid engine persists through composite submission and shares Claude cooldown', async () => {
  const calls=[];
  const h=harness(async(path,options={})=>{
    if(path==='/api/jobs'){const x=JSON.parse(options.body);calls.push(x);return response({job_id:x.task_type==='ppt'?'ppt_0123456789':'video_abcdef0123'});}
    if(path==='/api/wallet')return response({user:{credits_available:1800}});
    return response({status:'RUNNING',stage:'outlining',message:'Claude 正在推演论证'});
  });
  const cap={delivery_modes:{ppt:{supported:true,execution_modes:['codex_cli','claude_cli','claude_codex']},video:{supported:true}},providers:{claude_cli:{state:'ready',message:'ready'}}};
  h.api.set({capabilities:cap});h.api.updateMode('composite');h.get('ppt-engine').value='claude_codex';h.get('source').value=sourceText;
  h.api.controls();assert.equal(h.get('hybrid-engine-option').disabled,false);
  await h.get('brief').onsubmit({preventDefault(){}});await tick();
  assert.equal(calls.find(x=>x.task_type==='ppt').execution_mode,'claude_codex');
  assert.equal(calls.find(x=>x.task_type==='video').execution_mode,'codex_cli');
  assert.equal(h.api.get().activeTask.input.execution_mode,'claude_codex');
  cap.providers.claude_cli.state='cooldown';h.api.controls();
  assert.equal(h.get('retry-ppt').disabled,true);assert.equal(h.get('ppt-engine').value,'claude_codex');
});

test('validated hybrid outline is downloadable and cleared on logout', async () => {
  const job='ppt_0123456789',base=`/artifacts/${job}/`;
  const h=harness(async(path)=>{
    if(path==='/api/wallet')return response({user:{credits_available:1940}});
    if(path.endsWith('/artifacts'))return response({artifacts:{slide_preview_urls:[base+'assets/slide_preview_1.png'],pptx_url:base+'deck.pptx',html_deck_url:base+'deck.html',content_outline_url:base+'content_outline.md'}});
    return response({status:'COMPLETED',percent:100});
  });
  h.api.set();h.api.activateTask({mode:'ppt',input:{source:sourceText,execution_mode:'claude_codex'},jobs:{ppt:job},request_ids:{ppt:'hybrid-outline-test'},submit_errors:{}});await tick();await tick();
  assert.equal(h.get('outline-download').hidden,false);assert.equal(h.get('outline-download').href,base+'content_outline.md');
  h.api.clearSession();assert.equal(h.get('outline-download').hidden,true);assert.equal(h.get('outline-download').href,undefined);
});

test('hybrid outline and image stages highlight their actual progress steps', async () => {
  let stage='outlining';
  const h=harness(async path=>path==='/api/wallet'?response({user:{credits_available:940}}):response({status:'RUNNING',stage,percent:stage==='outlining'?32:46,message:stage}));
  const steps=[h.get('outline-step'),h.get('image-step'),h.get('check-step'),h.get('ready-step')];
  h.get('ppt-phase-steps').children=steps;
  h.api.set();h.api.activateTask({mode:'ppt',input:{source:sourceText,execution_mode:'claude_codex'},jobs:{ppt:'ppt_0123456789'},request_ids:{ppt:'hybrid-stage-test'},submit_errors:{}});await tick();
  assert.equal(steps[0].textContent,'Claude 内容策划');assert.equal(steps[0].className,'active');
  assert.equal(steps[1].textContent,'Codex 图片制作');
  stage='illustrating';await h.api.pollKind('ppt');
  assert.equal(steps[0].className,'done');assert.equal(steps[1].className,'active');
  assert.equal(h.get('ppt-meter').value,46);
});

test('MCP-created history tasks restore the engine and full request before rendering progress', async () => {
  const h=harness(async path=>path==='/api/wallet'?response({user:{credits_available:940}}):response({status:'RUNNING',stage:'outlining',percent:32,request:{source:sourceText,template_id:'auto',slide_count:6,execution_mode:'claude_codex'}}));
  const steps=[h.get('outline-step'),h.get('image-step')];h.get('ppt-phase-steps').children=steps;
  h.api.set({capabilities:{delivery_modes:{ppt:{execution_modes:['codex_cli','claude_cli','claude_codex']},video:{supported:true}}}});
  h.api.activateTask({mode:'ppt',input:{},jobs:{ppt:'ppt_0123456789'},request_ids:{},submit_errors:{}});await tick();
  assert.equal(h.api.get().activeTask.input.execution_mode,'claude_codex');assert.equal(steps[0].textContent,'Claude 内容策划');
  assert.match(h.get('request-config').textContent,/6 页.*Claude 策划 → Codex 绘图/);assert.equal(h.get('request-source').textContent,sourceText);
});
