const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
function harness(fetch) {
 const nodes = new Map(), storage = new Map(), timers = new Set();
 function element() { return {hidden:false,children:[],value:'',textContent:'',open:false,selectedOptions:[{text:'auto'}],setAttribute(k,v){this[k]=v},removeAttribute(k){delete this[k]},replaceChildren(...x){this.children=x},append(x){this.children.push(x)},add(x){this.children.push(x)},showModal(){this.open=true},close(){this.open=false},focus(){}}; }
 const get=id=>{if(!nodes.has(id)) nodes.set(id,element());return nodes.get(id)};
 const ctx=vm.createContext({document:{getElementById:get,createElement:element},sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},fetch,URL,Option:class{},crypto:webcrypto,TextEncoder,Uint8Array,location:{origin:'http://test'},setTimeout:fn=>{timers.add(fn);return fn},clearTimeout:fn=>timers.delete(fn)});
 let source=fs.readFileSync('gateway/static/studio.js','utf8'); source=source.slice(0,source.lastIndexOf('initialize().catch'));
 vm.runInContext(source+';globalThis.testApi={poll,api,controls,clearSession,initialize,set(s){authenticated=s.auth??true;canGenerate=s.canGenerate??true;ready=true;active=s.active??"ppt_0123456789";userId="a";artifacts=s.artifacts??null},get(){return {active,authenticated,ready}}};',ctx);
 return {api:ctx.testApi,get,timers,storage};
}
const response=(body,status=200)=>({ok:status<400,status,json:async()=>body});
const tick=()=>new Promise(r=>setImmediate(r));
test('late RUNNING response cannot overwrite a newer completion',async()=>{
 const pending=[]; const h=harness(path=>path==='/api/wallet'?Promise.resolve(response({user:{credits_available:1940}})):new Promise(resolve=>pending.push(resolve)));
 h.api.set({artifacts:{}}); const old=h.api.poll(), recent=h.api.poll();
 pending[1](response({status:'COMPLETED',percent:100,credits_charged:60})); await recent;
 pending[0](response({status:'RUNNING',percent:25})); await old;
 assert.equal(h.get('task-state').textContent,'待审阅'); assert.equal(h.timers.size,0);
});
test('401 clears private preview, draft, links and active timers',async()=>{
 const h=harness(async()=>response({detail:'expired'},401)); h.api.set({});
 h.get('slide').src='/private.png';h.get('download').href='/private.pptx';h.get('source').value='private source';
 await assert.rejects(h.api.api('/api/session'));
 assert.equal(h.api.get().authenticated,false);assert.equal(h.api.get().active,null);
 assert.equal(h.get('slide').src,undefined);assert.equal(h.get('download').href,undefined);assert.equal(h.get('source').value,'');
 assert.equal(h.get('submit').disabled,true); assert.equal(h.get('task-view').hidden,true);assert.equal(h.get('login').open,true);
});
test('read-only credentials cannot submit or retry in UI',async()=>{
 let calls=0;const h=harness(async()=>{calls++;return response({})});h.api.set({canGenerate:false});h.api.controls();
 assert.equal(h.get('submit').disabled,true);assert.equal(h.get('retry-ppt').disabled,true);
 await h.get('brief').onsubmit({preventDefault(){}});await h.get('retry-ppt').onclick();assert.equal(calls,0);
});
test('failed submission reuses request id and successful response opens its task',async()=>{
 const ids=[];const h=harness(async(path,options)=>{
 if(path==='/api/jobs'){ids.push(JSON.parse(options.body).request_id);if(ids.length===1)throw Error('network');return response({job_id:'ppt_0123456789'});}
 return response({status:'RUNNING',percent:10});});h.api.set({});h.get('source').value='完整测试内容，展示问题进展以及下周的责任分工和验收标准。';h.get('style').value='auto';h.get('pages').value='2';
 await h.get('brief').onsubmit({preventDefault(){}});await h.get('brief').onsubmit({preventDefault(){}});await tick();
 assert.equal(ids.length,2);assert.equal(ids[0],ids[1]);assert.equal(h.get('task-view').hidden,false);
});
test('initialization failure stays recoverable and cannot submit',async()=>{
 const h=harness(async path=>{if(path==='/api/session')return response({user_id:'a',can_generate:true});throw Error('templates unavailable')});
 await assert.rejects(h.api.initialize()); h.api.controls();assert.equal(h.api.get().ready,false);assert.equal(h.get('submit').disabled,true);
});
test('late initialization cannot restore an explicitly logged-out session',async()=>{
 let release;const h=harness(()=>new Promise(resolve=>release=resolve));const pending=h.api.initialize();h.api.clearSession();release(response({user_id:'a',can_generate:true}));await pending;
 assert.equal(h.api.get().authenticated,false);assert.equal(h.get('submit').disabled,true);
});
test('retry transport failure preserves idempotency key',async()=>{
 const ids=[];const h=harness(async(path,options)=>{ids.push(JSON.parse(options.body).request_id);throw Error('lost response')});h.api.set({});
 await h.get('retry-ppt').onclick();await h.get('retry-ppt').onclick();assert.equal(ids.length,2);assert.equal(ids[0],ids[1]);assert.equal(h.get('retry-ppt').disabled,false);
});
