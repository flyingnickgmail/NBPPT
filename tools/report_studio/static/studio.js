const $=id=>document.getElementById(id);let current=null,html='',previewUrl='';
const reportConfig=window.ReportStudioConfig||{},reportAPI=reportConfig.apiBase||'/api';
const reportRoute=path=>reportAPI+path.slice('/api'.length);
let reportStage='',reportCanGenerate=true;
// Reproducible viewport review without changing the browser's own window.
const reviewWidth=Number(new URLSearchParams(location.search).get('previewWidth'));
if([375,768,1024,1440].includes(reviewWidth)){Object.assign($('preview').style,{width:reviewWidth+'px',maxWidth:'none',flexShrink:'0',transition:'none'});$('preview').parentElement.style.justifyContent='flex-start';}
async function api(path,body){const res=await fetch(reportRoute(path),body?{method:'POST',headers:await ReportOverviewGenerate.headersFor(reportRoute(path),body),body:JSON.stringify(body)}:{});if(res.status===401&&reportConfig.platform){location.assign('/?next=reports');throw Error('登录已过期，请重新登录。');}if(!res.ok){ReportOverviewGenerate.acknowledged(reportRoute(path),res);let msg='请求失败';try{const data=await res.json();msg=typeof data.detail==='string'?data.detail:'输入格式不符合要求，请检查材料长度和结构。';}catch{}throw Error(msg);}if(path==='/api/export')return res.text();const data=await res.json();ReportOverviewGenerate.acknowledged(reportRoute(path),res);if(res.status===202&&data.status_url&&path!=='/api/overview'){loadReportHistory();refreshReportWallet();for(;;){await new Promise(resolve=>setTimeout(resolve,1800));const job=await ReportOverviewGenerate.request(data.status_url);reportStage=job.message;$('status').textContent=job.message;if(job.state==='failed'){refreshReportWallet();throw Error(job.message);}if(job.state==='completed')return ReportOverviewGenerate.request(data.status_url+'/result');}}return data;}
async function loadReportHistory(){
  const box=$('report-history');if(!box)return;
  try{
    const data=await api('/api/jobs');box.replaceChildren();
    for(const item of data.items){
      const row=document.createElement('div'),button=document.createElement('button');button.type='button';
      button.textContent=item.title+' · '+(item.state==='completed'?'已保存':item.state==='failed'?'载入并重试':item.state==='draft'?'草稿 · 继续填写':'查看进度');
      button.onclick=async()=>{
        try{
          const state=await api('/api/jobs/'+item.id);
          if(state.state==='completed'){
            const saved=await api('/api/jobs/'+item.id+'/result');await show({...saved,mode:'import'},state.preview_url);
            $('content').value=saved.content;$('title').value=saved.report.title;
            $('status').textContent='已载入保存的报告；可继续复审或生成分享图。';
          }else if(['failed','draft'].includes(state.state)){
            const input=await api('/api/jobs/'+item.id+'/input');
            if(input.report)await show({...input,mode:'import'});
            $('content').value=input.content;$('title').value=input.report?.title||input.title||'';
            if(input.mode==='local'||input.mode==='ai')$('mode').value=input.mode;
            $('status').textContent='原始输入已恢复。'+state.message;
          }else{$('status').textContent=state.message;}
          count();loadReportHistory();
        }catch(e){$('status').textContent=e.message;}
      };
      row.append(button);
      if(item.preview_url){const link=document.createElement('a');link.href=item.preview_url;link.target='_blank';link.rel='noopener';link.textContent='打开 ↗';row.append(link);}
      box.append(row);
    }
    if(!data.items.length)box.textContent='生成或导入后，报告会保存在这里。';
  }catch(e){box.textContent=e.message;}
}
function save(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function show(data,savedUrl=''){
  const next=await api('/api/export',data),preview=savedUrl?{url:savedUrl}:reportCanGenerate?await api('/api/preview',data):{url:''},review=await api('/api/review',data);
  $('review').hidden=false;$('review-summary').textContent=review.findings.length?`本次质量检查 · ${review.findings.length} 项待核对`:'基础检查通过 · 内容仍需审核';
  $('review-items').replaceChildren();for(const item of review.findings){const li=document.createElement('li');li.textContent=item.detail;$('review-items').append(li);}
  current=data;html=next;previewUrl=preview.url;if(previewUrl){$('preview').removeAttribute('srcdoc');$('preview').src=previewUrl;}else{$('preview').srcdoc=next;}
  $('preview-label').textContent=data.mode==='ai'?'智能编排 · 内容待审核':data.mode==='local'?'原文排版':data.mode==='import'?'导入报告 · 内容待审核':'演示材料 · 虚构数据';
  $('resume-report').hidden=data.mode!=='import';
  loadReportHistory();refreshReportWallet();
}
async function refreshReportWallet(){if(!reportConfig.platform)return;try{const h=await api('/api/health');const w=$('report-wallet');if(w)w.textContent='可用 '+h.credits_available+' 积分';}catch{}}
function count(){$('count').textContent=$('content').value.length.toLocaleString()+' / 60,000 字';}$('content').oninput=count;
$('mode').onchange=()=>{$('mode-note').textContent=$('mode').value==='ai'?(reportConfig.platform?'报告60积分，继续复审60积分，分享图40积分；受理冻结，成功结算，失败退回。':'模型整理章节、观点和可比数据。材料会发往 Codex 配置的模型服务，使用现有账户额度。'):'按原文标题和列表排版，不生成分析观点，也不自动提取数字图表。';};
$('form').onsubmit=async e=>{e.preventDefault();$('generate').disabled=true;reportStage='';const started=Date.now();$('status').textContent=$('mode').value==='ai'?'正在编排内容、核对材料并设计场景…':'正在排版原文…';const timer=setInterval(()=>{$('status').textContent=reportConfig.platform?`${reportStage||'正在组织材料'} · 已等待 ${Math.floor((Date.now()-started)/1000)} 秒。任务在后台继续，可稍后从“我的报告”查看。`:`正在生成 · 已等待 ${Math.floor((Date.now()-started)/1000)} 秒。包含材料检查、内容复审与视觉设计；长材料可能需要数分钟，请保持页面打开。`;},1000);try{await show(await api('/api/generate',{content:$('content').value,title:$('title').value,mode:$('mode').value,theme:$('theme').value}));$('status').textContent='报告已生成。请核对正文与数据，再下载使用。';}catch(err){$('status').textContent=err.message;}finally{clearInterval(timer);$('generate').disabled=false;}};
$('sample').onclick=async()=>{try{const sample=await api('/api/sample');$('content').value=sample.content;$('title').value=sample.report.title;count();await show({...sample,theme:$('theme').value});$('status').textContent='已载入演示材料。数据为虚构，可修改后重新生成。';}catch(err){$('status').textContent=err.message;}};
$('theme').onchange=async()=>{if(current)try{await show({...current,theme:$('theme').value});}catch(err){$('status').textContent=err.message;}};
$('file').onchange=async e=>{const f=e.target.files[0];if(!f)return;try{const jsonFile=f.name.endsWith('.json');if(f.size>(jsonFile?10000000:500000))throw Error(jsonFile?'结构化报告超过 10 MB，请缩小概览图片后导入。':'文件过大，请使用不超过 60,000 字的文本。');const text=await f.text();if(f.name.endsWith('.json')){const parsed=JSON.parse(text);await show({...parsed,mode:'import'});$('content').value=parsed.content;$('title').value=parsed.report.title;}else{if(text.length>60000)throw Error('材料超过 60,000 字，请精简后导入。');$('content').value=text;}count();$('status').textContent='已导入材料。';}catch(err){$('status').textContent=err.message;}};
$('mobile').onclick=()=>{$('preview').classList.add('mobile');$('mobile').classList.add('selected');$('desktop').classList.remove('selected');};$('desktop').onclick=()=>{$('preview').classList.remove('mobile');$('desktop').classList.add('selected');$('mobile').classList.remove('selected');};
$('download').onclick=()=>{if(current)save(new Blob([html],{type:'text/html'}),'交互报告.html');};$('json').onclick=()=>{if(current)save(new Blob([JSON.stringify(current,null,2)],{type:'application/json'}),'报告内容.json');};$('full').onclick=()=>{if(current)window.open(previewUrl,'_blank','noopener');};
(async()=>{
  try{
    const health=await api('/api/health');reportCanGenerate=health.can_generate!==false;refreshReportWallet();
    let initial=null,savedUrl='',draftId=reportConfig.platform?new URLSearchParams(location.search).get('draft'):null;
    if(draftId&&/^[a-f0-9]{32}$/.test(draftId)){
      const draft=await api('/api/jobs/'+draftId+'/input');
      $('content').value=draft.content;$('title').value=draft.title||'';count();
      $('preview-label').textContent='主页材料已带入 · 待生成';
      $('status').textContent='原文已从 NB PPT 主页带入，点击生成交互报告。';
      loadReportHistory();
    }else{
      if(reportConfig.platform){
        const history=await api('/api/jobs'),last=history.items.find(item=>item.state==='completed');
        if(last){initial=await api('/api/jobs/'+last.id+'/result');initial.mode='import';savedUrl=last.preview_url;$('content').value=initial.content;$('title').value=initial.report.title;count();}
      }
      await show(initial||await api('/api/sample'),savedUrl);
    }
    if(!health.codex_installed){$('mode').value='local';$('mode').onchange();$('status').textContent=health.ai_unavailable_reason||'未安装 Codex，可使用本地排版或导入报告。';}
    if(!reportCanGenerate){for(const id of ['generate','overview-generate','resume-report'])$(id).disabled=true;$('status').textContent='当前为只读权限，可查看和下载已有报告。';}
  }catch(err){$('status').textContent=err.message;}
})();

$('overview-generate').onclick=async()=>{if(!current)return;const snapshot=current;const b=$('overview-generate');b.disabled=true;try{await ReportOverviewGenerate.run(snapshot,{key:'overview-studio-job',status:t=>{$('status').textContent=t;},complete:async job=>{const result=await api('/api/overview/'+job.id+'/result');if(current!==snapshot){$('status').textContent='全景图已完成，当前材料已改变，请从任务结果查看。';const a=document.createElement('a');a.href=job.preview_url;a.target='_blank';a.textContent='查看完成的全景图报告';$('status').append(a);return;}await show(result);$('status').textContent=job.message;}});}catch(e){$('status').textContent=e.message+'；原报告保留。';}finally{b.disabled=false;}};

$('resume-report').onclick=async()=>{
  if(!current)return;const snapshot=current,b=$('resume-report');b.disabled=true;$('generate').disabled=true;
  $('status').textContent='正在从已保存报告继续复审与读图编排；不会重新生成初稿…';
  try{
    const result=await api('/api/continue',snapshot);
    if(current!==snapshot){const preview=await api('/api/preview',result),a=document.createElement('a');a.href=preview.url;a.target='_blank';a.textContent='查看完成的报告';$('status').textContent='复审已完成，当前材料已改变。';$('status').append(a);return;}
    await show(result);$('status').textContent='报告已继续完成；可以核阅或生成全景图。';
  }catch(e){$('status').textContent=e.message+'；导入的报告保留。';}
  finally{b.disabled=false;$('generate').disabled=false;}
};
