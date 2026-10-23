const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const c={window:{}};vm.runInNewContext(fs.readFileSync(__dirname+'/../static/qualified.js','utf8'),c);
const q=c.window.ReportQualified;
const p=[{value:-20,relation:'approx'},{value:30,relation:'exact'},{value:90,relation:'gt'}];
const l=q.layout(p);assert.ok(l.position(-20)<l.position(0));assert.ok(l.position(0)<l.position(90));assert.ok(l.position(-20)>=7&&l.position(90)<=93);assert.ok(l.ticks.includes(0));
assert.equal(q.label(p[0],'%'),'≈-20%');assert.equal(q.label(p[2],'%'),'>90%');
for(const values of [[0,0],[-2,-2],[1,1],[1e-6,3e-6],[-1e12,1e12]]){const d=q.layout(values.map(value=>({value})));assert.ok(d.high>d.low);for(const value of values)assert.ok(Number.isFinite(d.position(value)));}
class Node{constructor(tag,cls,text){this.tag=tag;this.className=cls;this.textContent=text;this.children=[];this.style={};this.dataset={};this.attrs={};}append(...n){this.children.push(...n);}setAttribute(k,v){this.attrs[k]=v;}}
let shown;const root=q.render({title:'限制',basis:'同一单位',unit:'%',points:[{...p[0],label:'A',quote:'a',source_ids:['S1']},{...p[2],label:'B',quote:'b',source_ids:['S2']}]},{el:(...a)=>new Node(...a),show:(...a)=>shown=a});
const rows=root.children[1].children[0].children;rows[1].onclick();assert.equal(shown[1],'>90% · 超过此值');assert.equal(shown[2],'b');assert.equal(rows[1].dataset.itemIndex,'1');assert.equal(rows[1].children[1].children.at(-1).textContent,'›');
console.log('Qualified values preserve bounds, signed geometry, evidence and stable narrative identity');
