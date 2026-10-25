/* P6 trusted parcel story. Source-bound plain data; no invented product UI. */
;(()=>{
 'use strict';
 const legacyConfigure=window.configure,legacyRender=window.renderFrame;
 let input=null;
 const phases=['问题','查证机制','证据边界','试点收束'],ids=['problem','mechanism','proof','close'];
 const curve=(p,a=0,b=1)=>ease((p-a)/(b-a));
 const label=(x,y,s,size=22,color=paper,parent=stage)=>text(x,y,s,size,color,parent);
 function rect(x,y,w,h,color='#24454B',stroke='#425B5D',parent=stage){return node('rect',{x,y,width:w,height:h,rx:12,fill:color,stroke,'stroke-width':2},undefined,parent);}
 function arrow(x1,y1,x2,y2,color=teal){line(x1,y1,x2,y2,color,3);const a=Math.atan2(y2-y1,x2-x1),r=10;node('path',{d:`M${x2-r*Math.cos(a-.55)} ${y2-r*Math.sin(a-.55)} L${x2} ${y2} L${x2-r*Math.cos(a+.55)} ${y2-r*Math.sin(a+.55)}`,fill:'none',stroke:color,'stroke-width':3});}
 function chip(x,y,s,color=teal,w=168){rect(x,y,w,48,ink,color);label(x+16,y+31,s,20,color);}
 function card(x,y,title,sub,color=teal,w=244){rect(x,y,w,112,ink,color);label(x+20,y+38,title,24,color);if(sub)label(x+20,y+78,sub,18,mute);}
 function packet(x,y,s,color=paper){rect(x,y,142,54,'#213E43',color);label(x+15,y+34,s,20,color);}
 function check(x,y,p,color=teal){node('circle',{cx:x,cy:y,r:22,fill:ink,stroke:color,'stroke-width':2});if(p>0)node('path',{d:`M${x-11} ${y} l8 9 l17 -20`,fill:'none',stroke:color,'stroke-width':3,'stroke-dasharray':38,'stroke-dashoffset':38*(1-p)});}
 function parcelAt(x,y,opacity=1){const g=parcel(x,y,.9);g.setAttribute('opacity',String(opacity));for(let i=0;i<6;i++)line(18+i*7,48,18+i*7,66,ink,i%2?2:3,g);return g;}
 function shelf(x,y,title,found=false,p=1){
  label(x,y-22,title,22,mute);for(let i=0;i<3;i++)line(x+i*108,y,x+i*108,y+205,teal,4);
  line(x,y+100,x+216,y+100,teal,4);line(x,y+204,x+216,y+204,teal,4);
  node('rect',{x:x+116,y:y+113,width:87,height:78,rx:4,fill:'none',stroke:orange,'stroke-width':2,'stroke-dasharray':'6 7'});
  if(found)parcelAt(x+117,y+107,p);
 }
 function person(x,y,title,color=paper){node('circle',{cx:x,cy:y,r:21,fill:ink,stroke:color,'stroke-width':2});node('path',{d:`M${x-35} ${y+66} v-9 q0 -35 35 -35 q35 0 35 35 v9`,fill:'none',stroke:color,'stroke-width':2});label(x-title.length*10,y+99,title,20,color);}
 function scan(x,y,w,p){const py=y+70*p;line(x,py,x+w,py,orange,3);node('rect',{x,y:py-12,width:w,height:24,fill:orange,opacity:.08});}
 function note(lines,color=teal){
  rect(958,182,264,366,'#19363D','#3F5B5E');label(980,220,'判断依据',18,mute);line(980,238,1200,238,'#3F5B5E',1);
  lines.forEach((s,i)=>label(980,278+i*56,s,i===0?23:19,i===0?color:paper));
 }
 function header(){
  node('rect',{width:1280,height:720,fill:ink});
  label(64,40,input.story.question,20,mute);label(64,92,input.motion.headline,34);
  label(995,42,'机制示意',18,orange);label(995,72,'非客户实录',16,mute);
  const active=ids.indexOf(input.story.act);
  phases.forEach((s,i)=>{label(64+i*286,140,s,19,i===active?paper:mute);line(64+i*286,154,314+i*286,154,i===active?orange:'#2A484D',i===active?3:1);});
  label(64,558,input.story.entity+' · 机制示意',17,mute);
  if(input.story.act==='proof')label(380,558,'来源：本次产品功能与情境演绎设定',16,mute);
 }
 function draw(p){
  const a=input.story.action,q=curve(p,.08,.88);stage.replaceChildren();header();
  if(['locate_gap','withhold_judgment','form_question'].includes(a)){
   shelf(110,220,'记录中的原库位');person(520,310,'出库人员');
   scan(225,330,94,q);
   if(a==='locate_gap'){
    const ghost=parcelAt(227,327,1-curve(p,0,.35));ghost.setAttribute('opacity',String(1-curve(p,0,.35)));
    packet(630-90*q,241,'库位记录');arrow(570,275,342,365,orange);note(['原库位没有看到','先保留疑问','查证尚未完成'],orange);
   }else if(a==='withhold_judgment'){
    card(645,285,'空货位','不足以判定丢失',orange,240);note(['现场发现','不是丢失结论','继续查记录'],orange);
   }else{
    arrow(350,360,475,360,orange);card(630,270,'下一步查什么','记录与现场互证',teal,255);note(['同一个包裹','查记录','到现场核对']);
   }
  }else if(['join_records','trace_origin','route_not_proof'].includes(a)){
   const names=['扫码记录','库位变更','交接备注'];line(160,400,840,400,teal,3);
   names.forEach((s,i)=>{const x=146+i*265;packet(x,220+105*curve(p,i*.12,.7+i*.1),s);node('circle',{cx:x+70,cy:400,r:8,fill:orange});});
   if(a==='join_records'){arrow(475,443,475,495);label(354,528,'同一包裹的查证路线',25);note(['线索汇到一起','每条记录有来源','不替人猜位置']);}
   else if(a==='trace_origin'){
    ['时间','操作者','原始记录'].forEach((s,i)=>chip(152+i*262,455,s,i===Math.min(2,Math.floor(p*3))?orange:teal,168));
    note(['从哪条记录来','何时留下','由谁记录']);
   }else{
    node('path',{d:'M180 450 Q430 540 770 470',fill:'none',stroke:orange,'stroke-width':3,'stroke-dasharray':'8 9'});
    label(282,535,'路线还要到现场验证',26,orange);note(['记录可能滞后','时间线不是找回证据','保留未确认部分'],orange);
   }
  }else if(['visit_handover','scan_identity'].includes(a)){
   shelf(100,230,'原库位');shelf(640,230,'现场核对',a==='scan_identity',curve(p,.15,.55));
   if(a==='visit_handover'){
    packet(365,215,'最近交接');arrow(436,289,720,320);person(390+175*q,350,'仓管员');note(['先查最近交接','记录提示方向','实物反验记录']);
   }else{
    chip(390,250,'扫描标签',orange,172);scan(755,336,100,q);arrow(560,286,748,360,orange);
    chip(355,446,'同一个包裹',teal,245);note(['核对同一标签','货位相近不等于相同','仍需确认库位']);
   }
  }else if(['escalate_unknown','block_guess','human_decision'].includes(a)){
   packet(108,229,'已核对',teal);packet(108,330,'仍不清楚',orange);
   const x=260+190*q;arrow(284,260,576,300,teal);arrow(284,361,576,340,orange);
   if(a!=='block_guess'){rect(x,425,100,42,ink,orange);label(x+12,453,'交接依据',17,orange);}person(668,270,'负责人',paper);
   if(a==='escalate_unknown'){label(108,190,'记录与现场仍对不上',24,orange);note(['判断转折','已知与未知一起交接','由负责人继续核查'],orange);}
   else if(a==='block_guess'){
    card(108,416,'猜测','不能写成已确认',orange,240);line(350,468,482,468,orange,3);line(450,450,480,486,orange,3);line(480,450,450,486,orange,3);
    note(['不能自动判定丢失','不清楚仍是不清楚','确认需要核查'],orange);
   }else{chip(567,449,'核查与判断',teal,240);note(['系统汇集线索','责任人核查','责任不转给系统']);}
  }else if(a==='confirm_location'){
   shelf(92,223,'原库位');shelf(640,223,'另一个货位',true,curve(p,.08,.36));
   chip(355,195,'如果现场确认',orange,242);check(834,218,curve(p,.28,.5));
   packet(160+570*q,432,'库位记录',q>.85?teal:orange);label(354,520,'更正的是记录，实物仍在现场',23);
   note(['条件分支','先确认同一包裹','再更正库位并通知']);
  }else if(a==='append_basis'){
   line(142,385,846,385,teal,3);card(106,240,'原库位记录','保留',mute);arrow(370,300,475,300);
   const g=node('g',{opacity:curve(p,.1,.55)});rect(504,240,306,112,ink,teal,g);label(526,280,'追加更正依据',26,teal,g);label(526,323,'回到同一包裹记录',20,paper,g);
   parcelAt(112,421);packet(250+400*q,438,'处理依据');note(['旧记录不删除','留下本次处理依据','下一位能接着核对']);
  }else if(a==='notify_then_verify'){
   person(150,262,'仓管员');person(750,262,'出库人员');arrow(255,300,641,300);
   packet(270+330*q,247,'更正通知');check(748,429,0,orange);label(615,487,'仍待后续核对',24,orange);
   note(['收到通知','不等于事情完成','按更正信息再核对'],orange);
  }else if(a==='review_trace'){
   const names=['有效线索','交接缺口','调整规则'];names.forEach((s,i)=>{card(102+i*270,226,s,['哪条起作用','哪里未留记录','下一步查什么'][i],i===1?orange:teal,242);});
   line(153,422,825,422,teal,3);packet(150+520*q,448,'处理记录');note(['建议验证的证据','记录处理依据','复盘交接环节']);
  }else if(['separate_proof','withhold_roi'].includes(a)){
   card(108,228,'本片说明','查证与交接的机制',teal,322);card(548,228,'尚无实测','效率与收益结论',orange,322);
   parcelAt(136+218*q,404);line(455,258,455,472,orange,3);label(548,448,a==='separate_proof'?'单次演示不证明效率':'不填没有依据的数字',24,orange);
   label(111,516,'保留流程依据，再讨论后续验证',24);note(['来源支持的机制','尚无观察成效','不承诺固定收益'],orange);
  }else if(a==='pilot_roles'){
   ['谁核对','谁确认','谁接收通知'].forEach((s,i)=>{person(206+i*280,270,s,i===Math.min(2,Math.floor(p*3))?orange:paper);check(206+i*280,445,0,teal);});
   label(233,523,'先选一段真实交接流程',26);note(['试点建议','事先明确责任人','不扩大成已完成部署']);
  }else if(a==='decide_scale'){
   ['小范围试点','异常处理记录','是否扩大'].forEach((s,i)=>{card(105+i*270,251,s,'',i===2?orange:teal,240);if(i<2)arrow(352+i*270,304,366+i*270,304);});
   packet(148+540*q,418,'复盘依据');label(111,521,'建议尚未实施，结论来自后续真实记录',23,mute);note(['用记录作决定','不预设试点成功','不是已部署成果'],orange);
  }else if(a==='return_question'){
   parcelAt(140,300);line(302,352,464,352,teal,3);card(490,266,'把判断依据留下','让下一位能继续核对',teal,362);
   label(110,482,'先做小范围试点，再决定是否扩大',27);line(110,513,110+730*q,513,orange,4);
   note(['回到开场的问题','核对同一个包裹','保留可追溯的依据']);
  }else throw Error('Unsupported trusted story action');
  line(64,574,1216,574,'#2B4C51',1);line(64,574,64+1152*p,574,orange,3);
 }
 window.configure=(value)=>{
  if(!value.story){input=null;document.querySelector('#beat').style.display='';return legacyConfigure(value);}
  if(value.portrait||value.motion.layout!=='parcel_story')throw Error('P6 schematic requires the explicit landscape story profile');
  input=value;stage.setAttribute('viewBox','0 0 1280 720');document.querySelector('#beat').style.display='none';draw(0);
 };
 window.renderFrame=async(frame,image)=>{
  if(!input)return legacyRender(frame,image);
  const p=Math.max(0,Math.min(1,frame/input.frames));draw(p);
  document.querySelector('#route').style.width=`${p*100}%`;
  return {frame,progress:p,action:input.story.action,evidence_kind:input.story.evidence_kind};
 };
})();
