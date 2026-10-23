const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const context={window:{}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/analytical.js'),'utf8'),context);
const analytical=context.window.ReportAnalytical;

class Node{
  constructor(tag){this.tagName=tag;this.children=[];this.attrs={};this.className='';this.textContent='';this.tabIndex=-1;}
  setAttribute(key,value){this.attrs[key]=String(value);}
  append(...nodes){this.children.push(...nodes);}
}
const el=(tag,cls,text)=>{const node=new Node(tag);node.className=cls||'';if(text!==undefined)node.textContent=text;return node;};
// Keep this signature strict: production renderers must always pass attrs.
const svgEl=(tag,attrs)=>{assert.ok(attrs&&typeof attrs==='object',`svgEl(${tag}) requires attrs`);const node=new Node(tag);Object.entries(attrs).forEach(([key,value])=>node.setAttribute(key,value));return node;};
const flatten=node=>[node,...node.children.flatMap(flatten)];
const classes=node=>node.className||node.attrs.class||'';
const shown=[];

const waterfall={kind:'waterfall',title:'利润变化桥',note:'',unit:'万元',basis:'同一审计口径',start:{label:'期初',value:100.25,quote:'期初证据',source_ids:['S1']},changes:[{label:'销量增长',value:25.125,quote:'增长证据',source_ids:['S2']},{label:'成本增加',value:-40.005,quote:'成本证据',source_ids:['S3']}],end:{label:'期末',value:85.37,quote:'期末证据',source_ids:['S4']}};
const geometry=analytical.waterfallGeometry(waterfall);
assert.equal(geometry.rows[1].from,100.25);assert.equal(geometry.rows[1].to,125.375);
assert.equal(geometry.rows[2].from,125.375);assert.equal(geometry.rows[2].to,85.37);
assert.ok(geometry.domain.low<=0&&geometry.domain.high>125.375,'waterfall scale must include zero and every cumulative endpoint');
const belowZero=analytical.waterfallGeometry({...waterfall,start:{...waterfall.start,value:10},changes:[{...waterfall.changes[1],value:-30}],end:{...waterfall.end,value:-20}});
assert.equal(belowZero.rows[1].from,10);assert.equal(belowZero.rows[1].to,-20);assert.ok(belowZero.domain.low<-20&&belowZero.domain.high>10,'negative cumulative geometry crosses the true zero axis');
const ticks=analytical.axisTicks(belowZero.domain);assert.ok(ticks.length>=3&&ticks.length<=7);assert.ok(ticks.includes(0));assert.ok(ticks.slice(2).every((tick,index)=>index===0||Math.abs((tick-ticks[index+1])-(ticks[1]-ticks[0]))<1e-6),'axis ticks are equally spaced');
const waterfallRoot=analytical.render(waterfall,{el,svgEl,show:(...args)=>shown.push(args)}),waterfallNodes=flatten(waterfallRoot);
const rows=waterfallNodes.filter(node=>String(classes(node)).includes('waterfall-row'));
assert.equal(rows.length,4);assert.deepEqual(rows.map(node=>node.attrs['data-item-index']),['0','1','2','3']);
assert.ok(waterfallNodes.some(node=>node.textContent==='+25.125 万元'),'positive raw precision is preserved');
assert.ok(waterfallNodes.some(node=>node.textContent==='-40.005 万元'),'negative raw precision is preserved');
assert.ok(waterfallNodes.some(node=>classes(node)==='observation-connector waterfall-connector'),'cumulative rows have visible hand-off connectors');
rows[2].onclick();assert.equal(shown[0][0],'成本增加');
let prevented=false;rows[3].onkeydown({key:' ',preventDefault:()=>{prevented=true;}});assert.equal(prevented,true);assert.equal(shown.length,2);

const mismatched=analytical.render({...waterfall,end:{...waterfall.end,value:90.123456789}},{el,svgEl,show:()=>{}}),mismatchNodes=flatten(mismatched);
assert.ok(mismatchNodes.some(node=>node.textContent.includes('90.123456789 万元')),'an unbalanced end value is shown literally');
assert.ok(mismatchNodes.some(node=>classes(node)==='analytical-warning'&&node.textContent.includes('输入未对齐')),'an imbalance cannot be hidden by the drawing');
const withinTolerance=analytical.render({...waterfall,end:{...waterfall.end,value:85.38}},{el,svgEl,show:()=>{}});
assert.ok(!flatten(withinTolerance).some(node=>classes(node)==='analytical-warning'),'float closure uses the upstream 0.01 tolerance');
const largeWaterfall={...waterfall,unit:'元',start:{...waterfall.start,value:1088983.34},changes:[{...waterfall.changes[0],value:10575613.03},{...waterfall.changes[1],value:0}],end:{...waterfall.end,value:11664596.37}};
const largeNodes=flatten(analytical.render(largeWaterfall,{el,svgEl,show:()=>{}})),largeValues=largeNodes.filter(node=>classes(node)==='waterfall-value'),largeBars=largeNodes.filter(node=>classes(node)==='waterfall-bar');
assert.ok(largeValues.every(node=>Number(node.attrs.x)<=940&&node.attrs['text-anchor']==='end'),'large raw values stay in the reserved value column inside the viewBox');
assert.ok(largeValues.some(node=>node.textContent==='+10,575,613.03 元'),'large values keep literal precision and units');
assert.equal(largeBars[2].attrs.width,'0','zero change has zero geometry rather than a fabricated minimum bar');
const largeTicks=largeNodes.filter(node=>classes(node)==='waterfall-axis-label');
assert.ok(largeTicks.length>=3&&largeTicks.length<=7,'the plot has readable equal-interval ticks');assert.ok(largeTicks.every(node=>!node.textContent.includes('.')),'large axes use nice integer tick steps');assert.ok(largeTicks.some(node=>node.textContent==='0'),'the equal-interval scale includes the true zero axis');

const mechanism={kind:'mechanism',title:'证据关系',note:'',lanes:['市场','组织'],nodes:[
  {label:'市场读数<script>',lane:0,stage:0,status:'observed',detail:'材料已披露',quote:'<b>原文而非 HTML</b>',source_ids:['S1']},
  {label:'改进动作',lane:1,stage:1,status:'proposal',detail:'建议动作',quote:'建议原文',source_ids:['S2']},
  {label:'业务结果',lane:0,stage:2,status:'unknown',detail:'结果尚未披露',quote:'未披露',source_ids:['S3']}
],links:[{from:0,to:1,label:'支持设计',quote:'关系证据',source_ids:['S1']},{origin:1,to:2,label:'结果尚待后续业务事实完整验证',quote:'待验',source_ids:['S3']}]};
const mechanismRoot=analytical.render(mechanism,{el,svgEl,show:(...args)=>shown.push(args)}),mechanismNodes=flatten(mechanismRoot);
const cards=mechanismNodes.filter(node=>String(classes(node)).includes('mechanism-node '));
assert.equal(cards.length,3);assert.equal(cards[2].attrs['data-item-index'],'2');
assert.ok(String(classes(cards[2])).includes('is-unknown'));assert.ok(!String(classes(cards[2])).includes('is-observed'),'unknown status must not render as observed');
const paths=mechanismNodes.filter(node=>classes(node)==='observation-connector mechanism-link-path');
const linkGroups=mechanismNodes.filter(node=>String(classes(node)).includes('mechanism-link '));
assert.equal(paths.length,2);assert.equal(linkGroups[1].attrs['data-from-index'],'1');assert.ok(String(classes(linkGroups[1])).includes('is-unknown'),'a link touching unknown evidence is not drawn as observed');
assert.ok(mechanismNodes.some(node=>node.textContent==='未披露'),'status is stated with words, not color alone');
assert.equal(mechanismNodes.filter(node=>classes(node)==='mechanism-stage').length,3,'only stages present in the data are rendered');
assert.ok(mechanismNodes.some(node=>node.tagName==='title'&&node.textContent==='结果尚待后续业务事实完整验证'),'a shortened relationship label keeps its complete SVG title');
assert.ok(mechanismNodes.some(node=>node.textContent.includes('<script>')),'hostile-looking labels remain literal SVG text');
assert.ok(mechanismNodes.some(node=>node.textContent==='<b>原文而非 HTML</b>')===false,'quotes are sent to the evidence viewer rather than injected into SVG');
cards[0].onclick();assert.equal(shown.at(-1)[0],'市场读数<script>');assert.equal(shown.at(-1)[2],'<b>原文而非 HTML</b>','evidence remains inert text passed to show');
assert.ok(mechanismNodes.every(node=>!('innerHTML' in node)),'SVG construction uses textContent and attributes only');
const parallel={...mechanism,lanes:['市场','组织','结果'],nodes:[...mechanism.nodes,{...mechanism.nodes[1],label:'并列控制',stage:1,lane:1},{...mechanism.nodes[2],label:'下泳道',lane:2}],links:[...mechanism.links,{from:0,to:3,label:'另一独立关系',quote:'证据'}]};
const parallelNodes=flatten(analytical.render(parallel,{el,svgEl,show:()=>{}})),parallelCards=parallelNodes.filter(node=>String(classes(node)).includes('mechanism-node '));
const rectangles=parallelCards.map(card=>card.children.find(child=>child.tagName==='rect'));
assert.equal(rectangles[1].attrs.x,rectangles[3].attrs.x,'parallel nodes keep their true stage');
assert.ok(Number(rectangles[3].attrs.y)>=Number(rectangles[1].attrs.y)+Number(rectangles[1].attrs.height),'parallel cards do not overlap');
assert.ok(Number(rectangles[4].attrs.y)>Number(rectangles[3].attrs.y)+Number(rectangles[3].attrs.height),'the next lane moves below the whole parallel stack');
assert.equal(parallelCards[3].attrs['data-item-index'],'3','stacking preserves evidence and reading-step identity');
assert.ok(parallelNodes.some(node=>node.attrs['data-to-index']==='3'),'the branch still targets the original parallel node');
console.log('Analytical waterfall and mechanism diagrams preserve geometry, disclosure status, literal values and evidence interactions');
