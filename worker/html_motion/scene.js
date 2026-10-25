/* Host-owned motion templates. No HTML, paths, expressions or Lottie JSON from clients. */
'use strict';
const NS='http://www.w3.org/2000/svg', stage=document.querySelector('svg');
const ink='#142D33', paper='#F1EBDD', orange='#DC7247', teal='#3F8B80', mute='#8C9D98';
let objects=[], current, duration=1, portrait=false, brand='', signals=[], approved=false, logo=false;
const ease=x=>1-Math.pow(1-Math.max(0,Math.min(1,x)),3);
function node(tag,attrs={},text,parent=stage){const el=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))el.setAttribute(k,String(v));if(text!==undefined)el.textContent=text;parent.append(el);return el;}
function text(x,y,value,size=24,color=paper,parent=stage){return node('text',{x,y,fill:color,'font-size':size,'font-family':'MotionCJK, sans-serif','font-weight':500},value,parent);}
function wrappedText(x,y,value,capacity,size,color=paper){for(let i=0;i<value.length;i+=capacity)text(x,y+Math.floor(i/capacity)*size*1.35,value.slice(i,i+capacity),size,color);}
function line(x1,y1,x2,y2,color=mute,width=2,parent=stage){return node('line',{x1,y1,x2,y2,stroke:color,'stroke-width':width},undefined,parent);}
function box(x,y,w,h,label,color=paper){const size=Math.min(28,Math.floor((w-44)/Math.max(1,label.length)));if(size<18)throw Error('Label exceeds visual capacity');const g=node('g');node('rect',{x,y,width:w,height:h,rx:12,fill:ink,stroke:color,'stroke-width':2},undefined,g);text(x+22,y+h*.57,label,size,color,g);return g;}
function signal(x1,y1,x2,y2,begin,end){const e=node('circle',{cx:0,cy:0,r:7,fill:orange,stroke:paper,'stroke-width':1});signals.push({e,x1,y1,x2,y2,begin,end});return e;}
function parcel(x,y,scale=1){const g=node('g',{transform:`translate(${x},${y}) scale(${scale})`});node('path',{d:'M0 20 L46 0 L92 20 L92 77 L46 99 L0 77 Z',fill:orange,stroke:paper,'stroke-width':2},undefined,g);node('path',{d:'M0 20 L46 42 L92 20 M46 42 L46 99 M23 10 L69 30 L69 55',fill:'none',stroke:ink,'stroke-width':3},undefined,g);return g;}
function setupLottie(){
  const shape={ty:'el',p:{a:0,k:[0,0]},s:{a:0,k:[28,28]},nm:'evidence pulse'};
  const layer={ddd:0,ind:1,ty:4,nm:'evidence moving along a verified route',sr:1,ks:{o:{a:0,k:100},r:{a:0,k:0},p:{a:1,k:[{t:0,s:[20,24,0],e:[1160,24,0],o:{x:.33,y:0},i:{x:.67,y:1}},{t:240,s:[1160,24,0]}]},a:{a:0,k:[0,0,0]},s:{a:0,k:[100,100,100]}},shapes:[shape,{ty:'fl',c:{a:0,k:[.86,.45,.28,1]},o:{a:0,k:100},r:1}],ip:0,op:241,st:0,bm:0};
  return lottie.loadAnimation({container:document.querySelector('#beat'),renderer:'svg',loop:false,autoplay:false,animationData:{v:'5.13.0',fr:24,ip:0,op:241,w:1200,h:48,nm:'host evidence route',ddd:0,assets:[],layers:[layer]}});
}
const beat=setupLottie();beat.setSubframe(false);lottie.freeze();
window.motionReady=beat.isLoaded;beat.addEventListener('DOMLoaded',()=>{window.motionReady=true;});
function portraitScene(p,labels){
  stage.setAttribute('viewBox','0 0 720 1280');node('rect',{width:720,height:1280,fill:ink});
  wrappedText(48,56,brand,40,15,mute);wrappedText(48,130,current.headline,20,28);
  if(p==='architecture')labels.forEach((v,i)=>{const y=700-i*170,g=node('g');node('path',{d:`M80 ${y} l280 -95 l280 95 l-280 110 Z`,fill:i%2?teal:'#24454B',stroke:paper,'stroke-width':2},undefined,g);text(230,y+14,v,26,paper,g);objects.push(g);});
  else if(p==='timeline'){
    line(165,285,165,900,teal,4);labels.forEach((v,i)=>{const y=300+i*580/(labels.length-1);node('circle',{cx:165,cy:y,r:11,fill:orange});objects.push(box(220,y-35,390,80,v));});objects.push(parcel(72,250,.65));
  }else if(p==='task_hub'){
    node('circle',{cx:360,cy:570,r:90,fill:teal});text(300,580,'责任人',30);labels.forEach((v,i)=>{const y=270+i*185;line(360,570,i%2?540:180,y,orange,3);objects.push(box(i%2?435:60,y-36,220,72,v));});
  }else if(p==='comparison'){
    objects.push(box(70,260,580,240,labels[0],orange));objects.push(box(70,610,580,240,labels[1],teal));parcel(445,360,.85);line(355,520,355,585,orange,4);
  }else if(p==='crm_frame'){
    node('rect',{x:60,y:260,width:600,height:650,rx:16,fill:'#213E43',stroke:paper,'stroke-width':2});
    if(approved)node('image',{id:'footage',x:68,y:268,width:584,height:634,preserveAspectRatio:'xMidYMid meet'});
    else{text(180,580,'已审产品画面待提供',28);objects.push(line(90,830,630,830,orange,4));}
  }else if(p==='broll_plate'){
    node('image',{id:'footage',x:40,y:220,width:640,height:740,preserveAspectRatio:'xMidYMid meet'});if(!approved)objects.push(box(140,860,440,80,labels[current.focus],orange));
  }else if(p==='closing'){
    if(logo)node('image',{id:'footage',x:210,y:250,width:300,height:220,preserveAspectRatio:'xMidYMid meet'});else parcel(285,260,1.5);
    wrappedText(70,535,current.headline||brand,18,30);text(150,650,labels[0],28,orange);text(150,715,labels[1],25);objects.push(line(90,800,630,800,teal,4));
  }else if(p==='title'){
    for(let i=0;i<2;i++){line(70+i*310,310,70+i*310,820,teal,5);line(70+i*310,500,340+i*310,500,teal,5);line(70+i*310,800,340+i*310,800,teal,5);}
    objects.push(parcel(95,660,.9));node('rect',{x:415,y:580,width:185,height:195,fill:'none',stroke:orange,'stroke-width':3,'stroke-dasharray':'8 9'});text(415,860,labels[0],24,orange);
  }else{labels.forEach((v,i)=>{objects.push(box(170,250+i*190,410,105,v,i===current.focus?orange:paper));});objects.push(parcel(60,265,.65));}
}
window.configure=(input)=>{
  current=input.motion;duration=input.frames/24;portrait=Boolean(input.portrait);brand=input.brand;objects=[];signals=[];stage.replaceChildren();
  approved=Boolean(input.approved_asset);logo=approved&&input.product_kind==='brand_logo';
  const p=current.layout, labels=current.labels;
  if(portrait){portraitScene(p,labels);window.renderFrame(0);return;}
  stage.setAttribute('viewBox','0 0 1280 720');
  node('rect',{width:1280,height:720,fill:ink});
  // A restrained scene space, with a work surface and architectural depth.
  for(let i=0;i<10;i++)line(30+i*140,105,30+i*140,625,'#203B40',1);
  line(64,634,1216,634,'#42534E',1);
  if(current.headline)text(64,88,current.headline,42);
  text(64,125,brand,14,mute);
  if(p==='architecture'){
    labels.forEach((label,i)=>{const y=450-i*105;const g=node('g');node('path',{d:`M340 ${y} l330 -95 l290 95 l-330 100 Z`,fill:i%2?teal:'#24454B',stroke:paper,'stroke-width':2},undefined,g);text(465,y+7,label,26,paper,g);objects.push(g);});
    parcel(960,365,.8);line(935,430,830,410,orange,4);
    labels.forEach((_,i)=>signal(935,430,650,450-i*105,.18+i*.18,.38+i*.18));
  }else if(p==='task_hub'){
    node('circle',{cx:640,cy:365,r:95,fill:'#23484B',stroke:orange,'stroke-width':3});text(581,373,'责任人',30);
    labels.forEach((label,i)=>{const a=i*Math.PI*2/labels.length-Math.PI/2,x=640+365*Math.cos(a),y=365+175*Math.sin(a);line(640,365,x,y,teal,3);objects.push(box(x-98,y-32,196,64,label,i===current.focus?orange:paper));});
    objects.push(parcel(595,470,.65));
    signal(280,525,640,365,.1,.5);signal(640,365,1005,365,.55,.85);
  }else if(p==='timeline'){
    line(145,405,1135,405,mute,3);
    labels.forEach((label,i)=>{const x=160+i*960/(labels.length-1);node('circle',{cx:x,cy:405,r:10,fill:orange});text(x-30,466,label,24);objects.push(box(x-70,252,170,80,label,teal));});
    objects.push(parcel(125,500,.55));
    labels.forEach((_,i)=>signal(160+i*960/(labels.length-1),405,160+i*960/(labels.length-1),285,.12+i*.22,.3+i*.22));
  }else if(p==='comparison'){
    const a=box(105,230,455,315,labels[0],orange),b=box(720,230,455,315,labels[1],teal);objects.push(a,b);
    line(600,380,680,380,orange,4);node('path',{d:'M665 365 l16 15 l-16 15',fill:'none',stroke:orange,'stroke-width':4});
    node('rect',{x:285,y:355,width:105,height:110,fill:'none',stroke:orange,'stroke-dasharray':'7 7','stroke-width':2});
    text(310,430,'？',42,orange);node('circle',{cx:940,cy:418,r:55,fill:'none',stroke:teal,'stroke-width':5});
    signal(230,480,430,480,.08,.8);signal(850,480,1050,480,.2,.9);
  }else if(p==='crm_frame'){
    node('rect',{x:170,y:185,width:940,height:390,rx:16,fill:'#213E43',stroke:paper,'stroke-width':2});
    line(170,225,1110,225,mute,1);text(210,214,'产品画面',16,mute);
    if(approved)node('image',{id:'footage',x:180,y:235,width:920,height:330,preserveAspectRatio:'xMidYMid meet'});
    else{text(420,380,'已审产品画面待提供',32);text(468,425,'保留真实产品证据',21,mute);objects.push(node('rect',{x:183,y:238,width:914,height:325,fill:'none',stroke:orange,'stroke-width':2}));}
  }else if(p==='broll_plate'){
    node('rect',{x:56,y:162,width:1168,height:440,rx:12,fill:'#213E43'});
    node('image',{id:'footage',x:56,y:162,width:1168,height:440,preserveAspectRatio:'xMidYMid meet'});
    if(!approved)objects.push(box(825,492,350,72,labels[current.focus],orange));
  }else if(p==='closing'){
    if(logo)node('image',{id:'footage',x:180,y:235,width:280,height:250,preserveAspectRatio:'xMidYMid meet'});else parcel(235,260,1.5);
    text(510,330,current.headline||brand,Math.min(45,Math.floor(700/Math.max(1,current.headline.length))));text(514,390,labels[0],30,orange);text(514,442,labels[1],24,mute);
    objects.push(node('path',{d:'M510 482 L1120 482',stroke:teal,'stroke-width':5}));
  }else if(p==='title'){
    // Opening is an incident at the shelf, not a slogan/title card.
    for(let i=0;i<3;i++){line(220+i*330,200,220+i*330,540,teal,5);line(220+i*330,330,505+i*330,330,teal,5);line(220+i*330,515,505+i*330,515,teal,5);}
    const ghost=parcel(625,400,.8);ghost.dataset.ghost='true';objects.push(ghost);node('rect',{x:570,y:367,width:210,height:140,fill:'none',stroke:orange,'stroke-width':3,'stroke-dasharray':'8 9'});
    node('rect',{x:280,y:375,width:100,height:130,rx:5,fill:paper});for(let n=0;n<4;n++)line(294,397+n*24,367,397+n*24,teal,3);
    text(570,570,labels[0],26,orange);text(250,262,labels[1],24,mute);
  }else{
    labels.forEach((label,i)=>{const x=115+i*1050/labels.length;objects.push(box(x,290,220,100,label,i===current.focus?orange:paper));if(i<labels.length-1)line(x+224,340,x+300,340,teal,3);});
    objects.push(parcel(125,460,.65));
  }
  window.renderFrame(0);
};
window.renderFrame=async(frame,image)=>{
  const t=frame/24, progress=t/duration,p=current.layout;
  objects.forEach((o,i)=>{let x=0,y=0,opacity=1;
    if(p==='architecture'){y=28*(1-ease((t-i*.35)/.9));opacity=ease((t-i*.35)/.65);}
    else if(p==='process'&&i===objects.length-1){if(portrait)y=550*ease(progress);else x=Math.max(0,Math.min(800,(t-.4)*130));}
    else if(p==='title'){if(o.dataset.ghost)opacity=.75*(1-ease(t/1.6));else y=-5*Math.sin(t*2);}
    else if(p==='timeline'&&i===objects.length-1){if(portrait)y=580*ease(progress);else x=900*ease(progress);}
    else if(p==='task_hub'){y=8*Math.sin(t*1.4+i);opacity=Math.min(1,.2+ease((t-i*.18)/.7));}
    else if(p==='closing'){o.setAttribute('stroke-dasharray','610');o.setAttribute('stroke-dashoffset',String(610*(1-ease(t/1.5))));}
    else {y=18*(1-ease((t-i*.2)/.8));}
    const original=o.dataset.original??o.getAttribute('transform')??'';o.dataset.original=original;
    o.setAttribute('transform',`translate(${x},${y}) ${original}`);o.setAttribute('opacity',String(opacity));
  });
  signals.forEach(({e,x1,y1,x2,y2,begin,end})=>{const q=ease((progress-begin)/(end-begin));e.setAttribute('cx',String(x1+(x2-x1)*q));e.setAttribute('cy',String(y1+(y2-y1)*q));e.setAttribute('opacity',progress>=begin&&progress<=end?'1':'0');});
  const media=document.querySelector('#footage');if(media&&image){const bitmap=new Image();bitmap.src=image;await bitmap.decode();media.setAttribute('href',image);}
  beat.goToAndStop(Math.min(240,progress*240),true);lottie.freeze();
  document.querySelector('#route').style.width=`${Math.max(0,Math.min(1,progress))*100}%`;
  return {frame,progress};
};
