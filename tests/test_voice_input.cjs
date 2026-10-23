const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
function harness(fetch){
 const nodes=new Map();const get=id=>{if(!nodes.has(id))nodes.set(id,{value:'',files:[],disabled:false,textContent:'',dispatchEvent(){},focus(){}});return nodes.get(id);};
 const ctx=vm.createContext({document:{getElementById:get},fetch,navigator:{},Event:class{},setTimeout,clearTimeout});
 ctx.window=ctx;ctx.addEventListener=()=>{};vm.runInContext(fs.readFileSync('gateway/static/voice-input.js','utf8'),ctx);
 return {ctx,get};
}
test('dictation fills editable text and never submits a generation job',async()=>{
 const calls=[];const h=harness(async(path,options)=>{calls.push(path);return {ok:true,json:async()=>({text:'核对后的原文'})};});
 h.ctx.configureVoiceInput({available:true},true);h.get('voice-file').files=[{size:10}];
 h.get('voice-file').onchange();await new Promise(r=>setImmediate(r));
 assert.equal(h.get('source').value,'核对后的原文');assert.deepEqual(calls,['/api/voice/transcribe']);
 assert.match(h.get('voice-input-status').textContent,/核对/);
});
test('a late transcription cannot populate another accounts draft',async()=>{
 let resolve;const pending=new Promise(r=>resolve=r);const h=harness(()=>pending);
 h.ctx.configureVoiceInput({available:true},true);h.get('voice-file').files=[{size:10}];h.get('voice-file').onchange();
 h.ctx.configureVoiceInput(null,false);h.ctx.configureVoiceInput({available:true},true);
 resolve({ok:true,json:async()=>({text:'旧账户的录音'})});await new Promise(r=>setImmediate(r));
 assert.equal(h.get('source').value,'');
});
test('unsupported or read-only accounts cannot upload dictation',()=>{
 const h=harness(()=>{throw Error('must not fetch');});h.ctx.configureVoiceInput({available:true},false);
 assert.equal(h.get('record-voice').disabled,true);assert.equal(h.get('voice-file').disabled,true);
});
test('the voice controller is loaded before the studio module',()=>{
 const html=fs.readFileSync('gateway/static/index.html','utf8');
 const voice=html.indexOf('<script src="/static/voice-input.js');const studio=html.indexOf('<script type="module" src="/static/studio.js');
 assert.ok(voice>0&&voice<studio);
});
