const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
function harness(fetch) {
  const nodes = new Map(), redirects = [];
  function element(tag = 'div') {
    return {tag,textContent:'',value:'',hidden:false,checked:false,disabled:false,children:[],open:false,
      classList:{toggle(){}},setAttribute(k,v){this[k]=v;},append(...values){this.children.push(...values);},replaceChildren(...values){this.children=values;},
      querySelectorAll(){return [];},showModal(){this.open=true;},close(){this.open=false;},reset(){},addEventListener(){},
      set innerHTML(value){throw new Error('Untrusted HTML insertion');}
    };
  }
  const get = id => { if (!nodes.has(id)) nodes.set(id,element()); return nodes.get(id); };
  const context = vm.createContext({document:{getElementById:get,createElement:element,querySelectorAll:()=>[]},fetch,crypto:webcrypto,
    location:{origin:'https://test',replace:path=>redirects.push(path)},window:{addEventListener(){}},confirm:()=>true,navigator:{},URL,Blob,setTimeout});
  const script=fs.readFileSync('gateway/static/admin.js','utf8');
  const source=script.slice(0,script.lastIndexOf('\ninitialize().catch('));
  vm.runInContext(source+`\nglobalThis.testApi={api,mutate,clearPrivate,renderKeys,openEditor,controls,refreshRecords,
    set(s){if(s.keys) keys=s.keys;if(s.selected) selected=s.selected;if(s.issued)issued=s.issued;userId=s.userId||'admin';},
    get(){return {keys,selected,issued,pending:pending.size,epoch};}};`,context);
  return {api:context.testApi,get,redirects};
}
const response=(body,status=200)=>({ok:status<400,status,json:async()=>body});
const key={key_id:'a'.repeat(64),name:'产品账户',user_id:'customer-0001',api_key:'***1234',scope:'generate',allow_claude:false,claude_eligible:false,
  daily_credit_limit:240,effective_daily_limit:240,daily_spent:60,credits_available:180,credits_frozen:60,is_active:1,account_key_count:1,is_current:false};

test('balance totals deduplicate accounts and names are inserted as text',()=>{
  const h=harness();h.get('status-filter').value='all';
  h.api.set({keys:[{...key,name:'<img src=x onerror=alert(1)>'},{...key,key_id:'b'.repeat(64)}]});h.api.renderKeys();
  assert.equal(h.get('balance-total').textContent,'180');assert.equal(h.get('frozen-total').textContent,'60');assert.equal(h.get('account-count').textContent,'1');
  assert.equal(h.get('key-rows').children[0].children[0].children[0].textContent,'<img src=x onerror=alert(1)>');
  h.get('search').value='not found';h.api.renderKeys();assert.equal(h.get('empty').hidden,false);
});

test('uncertain credit request reuses its id and blocks changing the amount until resolved',async()=>{
  const calls=[];let failed=false;
  const h=harness(async(path,options)=>{calls.push(JSON.parse(options.body));if(!failed){failed=true;throw new TypeError('network');}return response({credits_available:240});});
  await assert.rejects(h.api.mutate('credits','/credits','POST',{delta:60,note:'测试'}),/结果尚未确认/);
  await assert.rejects(h.api.mutate('credits','/credits','POST',{delta:600,note:'测试'}),/上一笔操作尚未确认/);
  await h.api.mutate('credits','/credits','POST',{delta:60,note:'测试'});
  assert.equal(calls.length,2);assert.equal(calls[0].request_id,calls[1].request_id);assert.equal(h.api.get().pending,0);
});

test('confirmed business denial releases the request id without logging out a valid admin',async()=>{
  const h=harness(async()=>response({detail:'当前密钥未获准使用 Claude'},403));
  await assert.rejects(h.api.mutate('settings','/key','PATCH',{allow_claude:true}),/未获准/);
  assert.equal(h.api.get().pending,0);assert.equal(h.redirects.length,0);
});

for (const failure of ['truncated','server-error']) test(`${failure} response preserves the same credit adjustment id`,async()=>{
  const calls=[];let first=true;
  const h=harness(async(path,options)=>{
    calls.push(JSON.parse(options.body));
    if(first){first=false;return failure==='truncated'?{ok:true,status:200,json:async()=>{throw new SyntaxError('incomplete');}}:response({detail:'server failed'},502);}
    return response({credits_available:240});
  });
  await assert.rejects(h.api.mutate('credits','/credits','POST',{delta:60,note:'测试'}),/结果尚未确认/);
  await h.api.mutate('credits','/credits','POST',{delta:60,note:'测试'});
  assert.equal(calls[0].request_id,calls[1].request_id);assert.equal(h.api.get().pending,0);
});

test('expired authorization clears private lists, issued key, pending operations and dialogs',async()=>{
  const h=harness(async()=>response({detail:'Session expired'},401));h.api.set({keys:[key],issued:{api_key:'test-only-secret'}});h.get('new-secret').value='test-only-secret';
  await assert.rejects(h.api.mutate('credits','/credits','POST',{delta:60,note:'测试'}));
  assert.equal(h.api.get().keys.length,0);assert.equal(h.api.get().issued,null);assert.equal(h.get('new-secret').value,'');assert.equal(h.api.get().pending,0);
  assert.equal(h.get('admin-content').hidden,true);assert.deepEqual(h.redirects,['/?next=admin']);
});

test('late create response after logout cannot restore a secret key',async()=>{
  let release;const wait=new Promise(resolve=>{release=resolve;});const h=harness(async()=>{await wait;return response({new_key:{api_key:'test-only-secret'}});});
  const request=h.api.mutate('create','/api/admin/keys','POST',{name:'test'});h.api.clearPrivate();release();
  await assert.rejects(request,/会话已切换/);assert.equal(h.api.get().issued,null);assert.equal(h.get('new-secret').value,'');
});

test('current admin is protected and Claude switch is independent of runtime owner identity',()=>{
  const h=harness();h.api.set({keys:[{...key,is_current:true,scope:'admin'}]});h.api.openEditor(key.key_id);
  assert.equal(h.get('edit-scope').disabled,true);assert.equal(h.get('revoke').disabled,true);assert.equal(h.get('edit-claude').disabled,false);
  assert.match(h.get('claude-detail').textContent,/按密钥独立授权/);
});

test('successful create retains its secret when subsequent list refresh fails',async()=>{
  let creates=0;const h=harness(async(path)=>{
    if(path==='/api/admin/keys'){creates++;if(creates===1)return response({new_key:{api_key:'test-only-secret',user_id:'new-user',credits_available:0,daily_credit_limit:240}});}
    throw new TypeError('refresh failed');
  });
  h.get('create-name').value='new account';h.get('create-credits').value='0';h.get('create-limit').value='240';h.get('create-scope').value='generate';
  await h.get('create-form').onsubmit({preventDefault(){}});
  assert.equal(h.get('new-secret').value,'test-only-secret');assert.equal(h.get('secret-dialog').open,true);
  assert.equal(h.get('create-dialog').open,false);assert.match(h.get('notice').textContent,/操作已成功/);
});

test('new independent key can be created with Claude enabled without sharing its account',async()=>{
  let request;
  const h=harness(async(path,options)=>{
    if(options?.method==='POST'){request=JSON.parse(options.body);return response({new_key:{api_key:'test-secret',user_id:'independent-new',credits_available:0,daily_credit_limit:240,allow_claude:true}});}
    return response(path.endsWith('/actions')?{actions:[]}:{keys:[]});
  });
  h.get('create-name').value='独立 Claude';h.get('create-credits').value='0';h.get('create-limit').value='240';h.get('create-scope').value='generate';h.get('create-claude').checked=true;
  await h.get('create-form').onsubmit({preventDefault(){}});
  assert.equal(request.allow_claude,true);assert.equal(request.initial_credits,0);assert.match(h.get('new-account-meta').textContent,/Claude 允许/);
});
