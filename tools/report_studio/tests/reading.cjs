const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
class Node {
  constructor(){this.children=[];this.dataset={};this.attrs={};this.hidden=false;this.classes=new Set();this.classList={add:x=>this.classes.add(x),toggle:(x,on)=>on?this.classes.add(x):this.classes.delete(x)};}
  append(...nodes){this.children.push(...nodes);}
  setAttribute(k,v){this.attrs[k]=v;}
  querySelectorAll(selector){return this.items||[];}
}
let intersection,mutation;
const context={window:{},document:{createElement:()=>new Node()},IntersectionObserver:class{constructor(cb){intersection=cb;}observe(){}},MutationObserver:class{constructor(cb){mutation=cb;}observe(){}}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/reading.js'),'utf8'),context);
const paragraphs=[new Node(),new Node()];paragraphs.forEach((p,i)=>p.dataset.paragraphIndex=String(i));
const section=new Node();section.items=paragraphs;
const charts=[new Node(),new Node(),new Node()];charts.forEach((c,i)=>{c.dataset.visualIndex=String(i-1);c.items=[new Node(),new Node()];c.items.forEach((n,j)=>n.dataset.itemIndex=String(j));});
let guide;const figures=new Node();figures.children=charts;figures.before=node=>guide=node;
const model={visuals:[{kind:'comparison'},{kind:'matrix'}],reading:{question:'变化与构成如何关联？',steps:[{title:'观察变化',explanation:'先读前后差异。',visual_index:0,item_indices:[1],paragraph_index:0},{title:'核对证据',explanation:'再读证据边界。',visual_index:1,item_indices:[0],paragraph_index:1}]}};
context.window.ReportReading.attach(section,model,figures,{});
const controls=guide.children[1],caption=guide.children[2],resume=guide.children[3],mode=guide.children[0].children[2];
assert.equal(charts[0].hidden,false,'legacy chart remains independent of modern visual indices');
assert.equal(charts[1].hidden,false);assert.equal(charts[2].hidden,true);
assert.ok(charts[1].items[1].classes.has('reading-focus'));assert.ok(charts[1].items[0].classes.has('reading-muted'));
controls.children[1].onclick();assert.equal(charts[1].hidden,true);assert.equal(charts[2].hidden,false);assert.equal(caption.textContent,'再读证据边界。');
intersection([{isIntersecting:true,boundingClientRect:{top:0},target:paragraphs[0]}]);assert.equal(guide.dataset.activeStep,'1','manual choice cannot be overwritten by scrolling');
resume.onclick();intersection([{isIntersecting:true,boundingClientRect:{top:0},target:paragraphs[0]}]);assert.equal(guide.dataset.activeStep,'0');
mode.onclick();assert.ok(charts.every(c=>!c.hidden),'all-chart mode exposes every chart');
charts[2].items.reverse();mutation();controls.children[1].onclick();assert.ok(charts[2].items[1].classes.has('reading-focus'),'matrix sorting retains semantic identity, not row position');
assert.equal(resume.textContent,'随正文聚焦');
console.log('Narrative steps bind to stable evidence, preserve manual focus, expose all charts, and survive sorting');
