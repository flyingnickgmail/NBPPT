const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const ctx={window:{}};for(const name of ['brand','space_gpu','space','recipes'])vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/'+name+'.js'),'utf8'),ctx);
const {mesh,project,rotate}=ctx.window.ReportSpace;
const part={shape:'box',center:[2,3,4],size:[2,4,6],rotation:[0,0,0],profile:[]};
const faces=mesh(part);assert.equal(faces.length,6);
const vertices=faces.flat();for(let i=0;i<3;i++){assert.equal(Math.min(...vertices.map(p=>p[i])),part.center[i]-part.size[i]/2);assert.equal(Math.max(...vertices.map(p=>p[i])),part.center[i]+part.size[i]/2);}
assert.ok(Math.abs(rotate([1,0,0],[0,0,90])[1]-1)<1e-8);
assert.ok(project([0,0,4],.6).y<project([0,0,0],.6).y);
assert.ok(project([0,0,4],.6).depth<project([0,0,0],.6).depth);
for(const shape of ['ring','cylinder','ellipsoid','prism']){
 const m=mesh({...part,shape,profile:[[-1,-1],[1,-1],[1,1],[-1,1]]});assert.ok(m.length>0);assert.ok(m.flat(2).every(Number.isFinite));
}
const original={kind:'line',points:[{value:2},{value:3}]};
const adapted=ctx.window.ReportRecipes.adapt(original,{recipe:'paired_period_columns'});assert.equal(adapted.kind,'bar');assert.equal(original.kind,'line');assert.equal(adapted.points,original.points);
assert.equal(ctx.window.ReportRecipes.adapt({kind:'multiseries',display:'line'},{recipe:'grouped_category_columns'}).display,'grouped_bar');
console.log('Spatial geometry, camera depth, primitive bounds and non-mutating recipe checks passed');
assert.ok(project([0,2,0],0).y<project([0,-2,0],0).y,'farther ground points must appear higher, not in front of tall objects');
for(const shape of ['rounded_box','lathe']){
 const originalPart={...part,shape,profile:shape==='lathe'?[[-1,.7],[-.8,1],[.8,1],[1,.7]]:[]};
 const before=JSON.stringify(originalPart),m=mesh(originalPart);
 assert.ok(m.length>8&&m.flat(2).every(Number.isFinite));assert.equal(JSON.stringify(originalPart),before);
 for(let i=0;i<3;i++){assert.ok(m.flat().every(p=>Math.abs(p[i]-part.center[i])<=part.size[i]/2+1e-8));}
}
const openingState=ctx.window.ReportSpace.openingState,order=['policy','inflation','jobs'];
const start=openingState(order,0),middle=openingState(order,1.4),end=openingState(order,20);
assert.equal(start.groups.jobs.opacity,0);assert.ok(middle.groups.policy.opacity>middle.groups.jobs.opacity);
assert.equal(end.done,true);assert.equal(end.groups.jobs.opacity,1);assert.equal(end.groups.jobs.offset,0);assert.equal(end.groups.policy.lift,0);
assert.deepEqual(JSON.parse(JSON.stringify(openingState(order,1.4))),JSON.parse(JSON.stringify(middle)),'paused time produces exactly the same pose');
console.log('Curved geometry and finite semantic opening checks passed');
const arc=mesh({...part,center:[0,0,0],size:[2,2,2],shape:'arc',sweep:180});
assert.ok(arc.flat(2).every(Number.isFinite));
assert.ok(ctx.window.ReportSpace.normal(arc.at(-2))[1]<-.99,'start cap must face out of the open arc');
assert.ok(arc.flat().every(p=>p[1]>=-1e-8),'half arc must not silently become a complete ring');
console.log('Open curved arc and outward caps checked');

assert.ok(ctx.window.ReportSpace.shade('ink',1,true)[0]>ctx.window.ReportSpace.shade('ink',1)[0], 'night lighting must preserve dark-object visibility');
assert.deepEqual(ctx.window.ReportSpace.shade('blue',1),ctx.window.ReportSpace.shade('accent',1),'legacy blue maps to current brand');
console.log('Brand tone compatibility and night illumination checked');

const shell={...part,center:[0,0,0],size:[2,2,2],shape:'loft',stations:[[-1,.4,-.6,.1],[0,1,-.8,1],[1,.65,-.5,.2]]};
const shellBefore=JSON.stringify(shell),shellMesh=mesh(shell),shellPoints=shellMesh.flat();
assert.equal(JSON.stringify(shell),shellBefore);
assert.ok(shellPoints.flat().every(Number.isFinite));
assert.ok(shellPoints.every(p=>p.every(v=>v>=-1-1e-8&&v<=1+1e-8)),'loft interpolation must not overshoot normalized bounds');
assert.ok(ctx.window.ReportSpace.normal(shellMesh[0])[0]<-.99);
assert.ok(ctx.window.ReportSpace.normal(shellMesh[1])[0]>.99);
assert.ok(shellMesh.slice(2).some(f=>ctx.window.ReportSpace.normal(f)[1]>.9),'side faces point outwards');
assert.ok(Math.max(...shellPoints.filter(p=>p[0]===-1).map(p=>Math.abs(p[1])))<Math.max(...shellPoints.filter(p=>p[0]===0).map(p=>Math.abs(p[1]))),'tapered silhouette follows cross sections');
const surfaceColor=ctx.window.ReportSpace.surfaceColor;
assert.ok(surfaceColor('ink','glass',1.2)[0]>surfaceColor('ink','rubber',1.2)[0],'glass and rubber must have distinct reflectance');
for(const material of ['metal','glass','paper','fiber','ceramic','rubber'])for(const light of [.4,1,1.35])assert.ok(surfaceColor('chalk',material,light).every(v=>Number.isInteger(v)&&v>=0&&v<=255));
assert.equal(start.zoom,.97);assert.equal(end.zoom,1);
assert.ok(openingState(order,.3).groups.policy.opacity>openingState(order,.3).groups.policy.label,'labels follow the object reveal');
assert.equal(end.groups.jobs.label,1);
console.log('Continuous shells, material reflectance and staged label reveal checked');
const shellFaces=shellMesh.map((points,index)=>({points,part:shell,partIndex:0,normal:ctx.window.ReportSpace.normal(points)}));
const normals=ctx.window.ReportSpaceGPU.smoothNormals(shellFaces);
assert.equal(normals.length,shellFaces.length);
assert.ok(normals.flat(2).every(Number.isFinite));
assert.ok(normals.flat().every(n=>Math.abs(Math.hypot(...n)-1)<1e-8));
assert.ok(normals[0].every(n=>n[0]<-.99),'smoothing preserves sharp shell end caps');
const cubeFaces=faces.map(points=>({points,part,partIndex:1,normal:ctx.window.ReportSpace.normal(points)}));
const cubeNormals=ctx.window.ReportSpaceGPU.smoothNormals(cubeFaces);
cubeNormals.forEach((normals,i)=>normals.forEach(n=>assert.deepEqual(n,cubeFaces[i].normal)));
assert.equal(ctx.window.ReportSpaceGPU.create({getContext:()=>null},()=>{}),null,'unavailable GPU must select vector fallback');
console.log('Smooth surface normals, hard edges and unavailable GPU fallback checked');
