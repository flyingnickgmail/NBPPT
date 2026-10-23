const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const context={window:{}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/scatter.js'),'utf8'),context);
const scatter=context.window.ReportScatter;

assert.equal(scatter.median([11.1,-4.5]),3.3);
const zero=scatter.scaleDomain([-4.5,11.1],'zero');
assert.ok(zero.low<0&&zero.high>11.1);
assert.ok(zero.ticks.includes(0),'zero reference must be represented exactly');
const positive=scatter.scaleDomain([65.8,127.9],'none');
assert.ok(positive.low>0,'a positive-only series must not create a large empty zero range');

const projected=[{label:'汽车总体',cx:190,cy:320,emphasis:false},{label:'新能源汽车',cx:610,cy:110,emphasis:true}];
const labels=scatter.layoutLabels(projected,{left:90,right:826,top:60,bottom:440});
assert.equal(labels.length,2);
for(const box of labels){assert.ok(box.x>=90&&box.y>=60&&box.x+box.w<=826&&box.y+box.h<=440,'labels stay inside the plot');}

class Node{
  constructor(tag){this.tagName=tag;this.children=[];this.attrs={};this.className='';this.textContent='';}
  setAttribute(key,value){this.attrs[key]=String(value);}
  append(...nodes){this.children.push(...nodes);}
}
const el=(tag,cls,text)=>{const node=new Node(tag);node.className=cls||'';if(text!==undefined)node.textContent=text;return node;};
const svgEl=(tag,attrs)=>{const node=new Node(tag);Object.entries(attrs).forEach(([key,value])=>node.setAttribute(key,value));return node;};
const shown=[];
const chart={kind:'scatter',title:'销量与出口增长并不同步',x_label:'销量同比',x_unit:'%',y_label:'出口同比',y_unit:'%',source_ids:['S01'],analysis:{reference:'zero',x_low_label:'销量同比下降',x_high_label:'销量同比增长',y_low_label:'出口同比下降',y_high_label:'出口同比增长',emphasis_label:'重点观察'},points:[
  {label:'汽车总体',x:-4.5,y:65.8,quote:'总体证据',source_ids:['S01'],emphasis:false},
  {label:'新能源汽车',x:11.1,y:127.9,quote:'新能源证据',source_ids:['S01'],emphasis:true}
]};
const root=scatter.render(chart,{el,svgEl,show:(...args)=>shown.push(args)});
const flatten=node=>[node,...node.children.flatMap(flatten)];
const classes=node=>node.className||node.attrs.class||'';
const nodes=flatten(root),marks=nodes.filter(node=>classes(node)==='scatter-mark'),points=nodes.filter(node=>String(classes(node)).includes('scatter-point'));
assert.equal(marks.length,2);assert.deepEqual(marks.map(node=>node.attrs.r),['7','7'],'equal dots must not imply a fake magnitude');
assert.equal(points.length,2);assert.equal(points[0].attrs.tabindex,'0');assert.equal(points[0].attrs.role,'button');
assert.ok(nodes.some(node=>node.textContent==='X = 0'));assert.ok(nodes.some(node=>node.textContent==='Y = 0'));
assert.ok(nodes.some(node=>node.textContent==='销量同比下降 · 出口同比增长'),'region semantics are stated below the plot without a priority score');
assert.ok(nodes.some(node=>node.textContent.includes('127.9%')),'direct values must preserve source precision');
assert.ok(nodes.some(node=>classes(node)==='scatter-zone zone-a'),'regions have neutral, reference-aligned backgrounds');
assert.ok(nodes.some(node=>classes(node)==='scatter-plot-scroll'),'the plot has a mobile overflow safety wrapper');
points[0].onclick();assert.equal(shown.length,1);assert.equal(shown[0][0],'汽车总体');
let prevented=false;points[1].onkeydown({key:'Enter',preventDefault:()=>{prevented=true;}});assert.equal(prevented,true);assert.equal(shown.length,2);
assert.ok(nodes.some(node=>classes(node)==='scatter-hit'&&node.attrs.r==='20'),'true hit area is larger than the mark');
const medianRoot=scatter.render({...chart,analysis:{...chart.analysis,reference:'median'}},{el,svgEl,show:()=>{}}),medianNodes=flatten(medianRoot);
assert.ok(medianNodes.some(node=>node.textContent==='X 中位数 3.3'));
assert.ok(medianNodes.some(node=>node.textContent==='Y 中位数 96.85'),'derived median labels preserve real precision');
console.log('Analytical scatter preserves values, references, readable labels and evidence interactions');
