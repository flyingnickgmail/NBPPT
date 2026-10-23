/* Shared by the studio and standalone localhost preview. Offline export stays read-only. */
window.ReportOverviewGenerate = (() => {
  const pending=new Map();
  const config=window.ReportStudioConfig||{},apiBase=config.apiBase||'/api';
  async function headersFor(url,body){
    const headers={'Content-Type':'application/json'};
    if(!config.platform||!/(?:generate|continue|overview)$/.test(url))return headers;
    const digest=await binding({report:body}),key='report-write:'+url;
    let saved;try{saved=JSON.parse(storage.get(key));}catch{}
    if(saved?.digest!==digest)saved={digest,id:crypto.randomUUID()};
    storage.set(key,JSON.stringify(saved));headers['X-Request-ID']=saved.id;return headers;
  }
  function acknowledged(url,response){if(config.platform&&(response.ok||response.status>=400&&response.status<500))storage.set('report-write:'+url,null);}
  async function request(url,body){
    if(url.startsWith('/api/')&&!url.startsWith(apiBase+'/'))url=apiBase+url.slice(4);
    const response=await fetch(url,body?{method:'POST',headers:await headersFor(url,body),body:JSON.stringify(body)}:{});
    const data=await response.json();
    acknowledged(url,response);
    if(!response.ok){const error=Error(typeof data.detail==='string'?data.detail:'全景图生成请求失败');error.status=response.status;throw error;}
    return data;
  }
  const storage={get:key=>{try{return sessionStorage.getItem(key);}catch{return null;}},set:(key,value)=>{try{value?sessionStorage.setItem(key,value):sessionStorage.removeItem(key);}catch{}}};
  const binding=async data=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(data.report))))).map(x=>x.toString(16).padStart(2,'0')).join('');
  const savedJob=async(key,data)=>{try{const saved=JSON.parse(storage.get(key));return saved?.digest===await binding(data)?saved.id:null;}catch{return null;}};
  async function run(data,{status,complete,key='overview-job'}){
    if(pending.has(key))return pending.get(key);
    const task=(async()=>{
      let id=await savedJob(key,data);
      try{
        if(!id){const created=await request('/api/overview',{...data,overview:null});id=created.id;storage.set(key,JSON.stringify({id,digest:await binding(data)}));}
        status('正在连接全景图任务…');
        for(;;){
          const job=await request('/api/overview/'+id);status(job.message);
          if(job.state==='completed'){await complete(job);storage.set(key,null);return;}
          if(job.state==='failed'){storage.set(key,null);throw Error(job.message);}
          await new Promise(resolve=>setTimeout(resolve,1800));
        }
      }catch(error){
        // Keep the job ID on network failure so a retry resumes instead of charging twice.
        if(!id||error.status===404)storage.set(key,null);
        throw error;
      }finally{pending.delete(key);}
    })();pending.set(key,task);return task;
  }
  function mount(data,actions,target){
    const local=['127.0.0.1','localhost','[::1]'].includes(location.hostname)&&/^\/preview\/[a-f0-9]+$/.test(location.pathname);
    const integrated=config.platform&&/^\/api\/reports\/preview\/[a-f0-9]+$/.test(location.pathname);
    if(!local&&!integrated)return;
    // The studio owns its current data and export buttons; use its toolbar there.
    if(window.self!==window.top)return;
    const button=document.createElement('button');button.type='button';button.textContent=data.overview?'重新生成全景图':'一键生成全景图';
    button.title=config.platform?'远程生成分享图40积分；失败退回，原报告保留':'根据全文自动设计、生成并核对；使用本机已登录模型，结果保存在本机';
    const note=document.createElement('p');note.className='overview-generation-status';note.hidden=true;note.setAttribute('role','status');note.setAttribute('aria-live','polite');
    const key='overview-job:'+location.pathname;
    async function start(){button.disabled=true;note.hidden=false;note.textContent=config.platform?'分享图40积分，正在提交；失败积分退回，原报告保留。':'准备生成；使用本机已登录模型，设计与结果保存在本机。';
      try{await run(data,{key,status:t=>{note.textContent=t;},complete:job=>{location.href=job.preview_url;}});}
      catch(e){note.textContent=e.message+'；原报告保留。';button.disabled=false;button.textContent='重试 / 继续全景图';}}
    button.onclick=start;actions.prepend(button);target.append(note);
    savedJob(key,data).then(id=>{if(id)start();});
  }
  return {run,mount,request,headersFor,acknowledged};
})();
