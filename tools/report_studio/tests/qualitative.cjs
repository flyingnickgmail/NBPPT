const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const context={window:{}};vm.runInNewContext(fs.readFileSync(__dirname+'/../static/qualitative.js','utf8'),context);
class Node{
 constructor(tag,cls='',text=''){this.tagName=tag;this.className=cls;this.textContent=text;this.children=[];this.dataset={};this.attrs={};this.classList={add:c=>{this.className+=' '+c;}};}
 append(...nodes){this.children.push(...nodes);}setAttribute(k,v){this.attrs[k]=v;}
}
const el=(...args)=>new Node(...args),flatten=n=>[n,...n.children.flatMap(flatten)],seen=[];
const render=c=>flatten(context.window.ReportQualitative.render(c,{el,show:(...args)=>seen.push(args)}));
const quote='<script>原句仅是文本</script>';
const statement={label:'身份<script>',detail:'连续身份',nature:'recorded',quote,source_ids:['S1']};
const paired=render({kind:'contrast',left_label:'身份',right_label:'凭据',rows:[{label:'生命周期',left:statement,right:{...statement,label:'短期'}}]});
assert.equal(paired.filter(n=>n.className.includes('qual-statement')).length,2);
paired.find(n=>n.className.includes('qual-statement')).onclick();assert.equal(seen[0][2],quote);
assert.ok(paired.some(n=>n.textContent==='身份<script>'),'variable text remains inert');
const dots=render({kind:'membership',sets:['身份','授权','审计'],items:[{label:'任务凭据',detail:'有限范围',relations:[{set_index:1,relation:'included',quote,source_ids:['S1']}]}]}).filter(n=>n.className.includes('membership-cell'));
assert.equal(dots.length,3);assert.equal(dots[0].textContent,'·');assert.equal(dots[0].disabled,true);
assert.equal(dots[1].textContent,'●');dots[1].onclick();assert.equal(seen.at(-1)[0],'任务凭据 · 授权');
assert.ok(dots.every(n=>n.dataset.itemIndex==='0'),'narrative focus binds semantic item indices');
const strips=render({kind:'evidence_strip',items:[statement,{...statement,nature:'proposed'},{...statement,nature:'unresolved'}]});
assert.equal(strips.filter(n=>n.className.startsWith('evidence-column ')).length,3);
assert.equal(strips.filter(n=>n.className.includes('evidence-entry')).length,3);
console.log('Qualitative rendering: inert evidence, unknown membership and semantic focus passed');
