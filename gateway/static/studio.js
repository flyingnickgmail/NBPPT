const $ = id => document.getElementById(id);
let authenticated = false, busy = false, active = null, timer, epoch = 0, artifacts = null;
let userId = '', canGenerate = false, ready = false, pollSequence = 0;
const sample = '为项目负责人制作客户问题协同试点汇报。以下是合成测试数据：本周收集12个问题，已解决7个，5个待处理。说明当前进展、销售与产品团队如何分工，以及下周逐项确认责任人与验收标准的计划。不要编造收益或客户案例。';
function notice(message = '') { $('notice').textContent = message; $('notice').hidden = !message; }
function clearSession() {
  epoch++; pollSequence++; clearTimeout(timer); authenticated = false; ready = false; canGenerate = false;
  active = null; artifacts = null;
  $('slide').removeAttribute('src'); $('download').removeAttribute('href'); $('html-deck').removeAttribute('href');
  $('source').value = ''; $('count').textContent = '0 字';
  $('thumbnails').replaceChildren(); $('history-list').replaceChildren(); $('history').close();
  $('ppt-panel').hidden = true; $('task-summary').textContent = ''; $('request-source').textContent = ''; $('request-config').textContent = ''; $('ppt-progress').textContent = '';
  $('account').textContent = '登录'; $('wallet').textContent = ''; $('admin').hidden = true;
  showComposer(); controls();
}
function login() { if (!$('login').open) $('login').showModal(); }
async function api(path, options = {}) {
  const requestEpoch = epoch;
  const response = await fetch(path, {credentials:'same-origin', ...options, headers:{'Content-Type':'application/json', ...options.headers}});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && requestEpoch === epoch) { clearSession(); login(); }
    throw new Error(typeof body.detail === 'string' ? body.detail : `请求失败（${response.status}），请稍后重试。`);
  }
  return body;
}
function showTask() {
  for (const id of ['composer','welcome','compose-intro']) $(id).hidden = true;
  $('task-view').hidden = false; $('back-edit').hidden = false; $('resume-task').hidden = true;
}
function showComposer() {
  for (const id of ['composer','welcome','compose-intro']) $(id).hidden = false;
  $('task-view').hidden = true; $('back-edit').hidden = true; $('resume-task').hidden = !active;
}
function controls() {
  $('submit').disabled = !authenticated || !ready || !canGenerate || busy;
  $('account').disabled = busy;
  $('submit').textContent = busy ? '正在提交…' : authenticated ? (!canGenerate ? '当前凭据仅可查看任务' : '开始生成 →') : '登录后开始生成 →';
  $('retry-ppt').disabled = busy || !canGenerate;
}
function safeArtifact(path) {
  if (typeof path !== 'string' || !path.startsWith(`/artifacts/${active}/`) || path.includes('..') || path.includes('\\')) throw new Error('产物地址校验失败');
  const url = new URL(path, location.origin);
  if (url.origin !== location.origin || !url.pathname.startsWith(`/artifacts/${active}/`) || url.search || url.hash) throw new Error('产物地址校验失败');
  return path;
}
function showSlide(index) {
  const pages = artifacts.artifacts.slide_preview_urls;
  $('slide').src = safeArtifact(pages[index]); $('slide').alt = `生成结果第 ${index + 1} 页`;
  $('slide-title').textContent = `第 ${index + 1} 页`; $('position').textContent = `${index + 1} / ${pages.length}`;
  [...$('thumbnails').children].forEach((button,i) => button.setAttribute('aria-pressed', String(i === index)));
}
function renderArtifacts(result) {
  const links = result.artifacts;
  [...links.slide_preview_urls, links.pptx_url, links.html_deck_url].forEach(safeArtifact);
  artifacts = result; $('thumbnails').replaceChildren();
  links.slide_preview_urls.forEach((path,i) => {
    const button = document.createElement('button'); button.type = 'button'; button.setAttribute('aria-label', `查看第 ${i+1} 页`);
    const img = document.createElement('img'); img.src = safeArtifact(path); img.alt = ''; button.append(img);
    button.onclick = () => showSlide(i); $('thumbnails').append(button);
  });
  $('download').href = safeArtifact(links.pptx_url); $('html-deck').href = safeArtifact(links.html_deck_url);
  $('preview-empty').hidden = true; $('ppt-panel').hidden = false;
  $('preview-context').textContent = `${result.slide_count} 页 · 文件验收通过 · 内容待人工审阅`;
  showSlide(0);
}
async function poll() {
  clearTimeout(timer); const id = active, ticket = epoch, sequence = ++pollSequence;
  if (!id || !authenticated) return;
  try {
    const status = await api(`/api/jobs/${id}`);
    if (ticket !== epoch || sequence !== pollSequence) return;
    if (status.request) { $('request-source').textContent = status.request.source; $('request-config').textContent = `${status.request.template_id} · ${status.request.slide_count || '自动'} 页`; }
    $('task-state').textContent = ({RUNNING:'生成中',FAILED:'生成失败',COMPLETED:'待审阅'})[status.status] || status.status;
    $('ppt-progress').textContent = status.status === 'COMPLETED' ? '文件检查通过，可以预览和下载。内容仍需人工复核。' : (status.message || '任务执行中，等待服务器更新');
    const step = {queued:-1,planning:0,generating:1,checking:2,ready:3}[status.stage] ?? -1;
    [...$('phase-steps').children].forEach((node,i) => { node.className = i < step ? 'done' : i === step ? 'active' : ''; node.setAttribute('aria-current', i === step ? 'step' : 'false'); });
    $('updated').textContent = `最近同步：${new Date().toLocaleTimeString('zh-CN')}`;
    if (Number.isFinite(status.percent)) $('ppt-meter').value = status.percent;
    else $('ppt-meter').removeAttribute('value');
    $('ppt-meter').hidden = status.status === 'FAILED';
    $('retry-ppt').hidden = status.status !== 'FAILED' || !canGenerate;
    $('billing').textContent = status.status === 'FAILED' ? '本次失败，冻结算力已退回。重试会创建新任务并重新冻结算力。' : status.status === 'COMPLETED' ? `本次结算 ${status.credits_charged} 点算力。` : '任务执行中，完成验收后结算；失败退回冻结算力。';
    if (status.status === 'COMPLETED' && !artifacts) {
      const result = await api(`/api/jobs/${id}/artifacts`);
      if (ticket !== epoch || sequence !== pollSequence) return;
      renderArtifacts(result);
    }
    if (status.status === 'RUNNING') timer = setTimeout(poll, 5000);
    else refreshWallet().catch(() => {});
  } catch (error) {
    if (ticket !== epoch || sequence !== pollSequence) return;
    notice(`状态同步中断：${error.message} 已保留任务，请刷新状态；不会再次扣费或重复提交。`);
    if (authenticated) timer = setTimeout(poll, 10000);
  }
}
function openJob(id) {
  if (!/^[a-z]+_[a-f0-9]{10}$/.test(id)) throw new Error('无效的任务编号');
  epoch++; clearTimeout(timer); active = id; artifacts = null;
  sessionStorage.setItem(`nbppt-active-${userId}`, id);
  $('ppt-panel').hidden = true; $('preview-empty').hidden = false; $('preview-context').textContent = '';
  $('task-summary').textContent = id; $('request-source').textContent = ''; $('request-config').textContent = ''; $('retry-ppt').hidden = true; $('ppt-progress').textContent = '正在获取真实状态…';
  $('task-state').textContent = '同步中'; $('ppt-meter').hidden = false; $('ppt-meter').removeAttribute('value'); $('billing').textContent = '';
  showTask(); $('task-title').focus(); poll();
}
async function refreshWallet() { const authEpoch = epoch; const data = await api('/api/wallet'); if (authEpoch !== epoch || !authenticated) return; $('wallet').textContent = `可用 ${data.user.credits_available} 点`; }
async function initialize() {
  const initEpoch = epoch;
  const session = await api('/api/session');
  if (initEpoch !== epoch) return;
  if (userId && userId !== session.user_id) { active = null; artifacts = null; clearTimeout(timer); showComposer(); }
  userId = session.user_id; authenticated = true; canGenerate = session.can_generate === true; ready = false; $('account').textContent = '退出'; $('admin').hidden = !session.admin;
  const data = await api('/api/templates'); if (initEpoch !== epoch) return; $('style').replaceChildren(new Option('自动匹配','auto'));
  data.templates.forEach(t => { if(t.id !== 'auto') $('style').add(new Option(t.name, t.id)); });
  const caps = await api('/api/capabilities');
  if (initEpoch !== epoch) return;
  $('cost').textContent = `提交时冻结 ${caps.delivery_modes.ppt.freeze_credits} 点算力，按实际结算；失败自动退回。`;
  await refreshWallet(); if (initEpoch !== epoch) return; ready = true; controls();
  const saved = sessionStorage.getItem(`nbppt-active-${userId}`); if (saved) openJob(saved);
}
$('login-form').onsubmit = async event => {
  event.preventDefault(); $('login-error').textContent = '';
  try { await api('/api/session',{method:'POST',body:JSON.stringify({api_key:$('key').value})}); $('key').value = ''; $('login').close(); await initialize(); }
  catch(error) { if ($('login').open) $('login-error').textContent = error.message; else { notice(`初始化失败：${error.message} 点击重新连接再试。`); $('account').textContent = '重新连接'; } controls(); }
};
$('login-close').onclick = () => $('login').close();
$('account').onclick = async () => {
  if (!authenticated) return login();
  if (!ready) { try { await initialize(); notice(); } catch(error) { notice(error.message); } return; }
  try { await api('/api/session',{method:'DELETE'}); clearSession(); }
  catch(error) { notice(error.message); }
};
$('brief').onsubmit = async event => {
  event.preventDefault(); if (busy || !authenticated || !ready || !canGenerate) return;
  const args = {source:$('source').value.trim(), template_id:$('style').value, slide_count:Number($('pages').value)};
  if (args.source.length < 20) return notice('请至少输入20个字的原文与要求。');
  busy = true; controls(); notice();
  try {
    const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(args))))).map(b=>b.toString(16).padStart(2,'0')).join('');
    const storageKey = `nbppt-pending-${userId}`;
    let pending = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
    if (!pending || pending.hash !== hash) { pending = {hash,request_id:crypto.randomUUID()}; sessionStorage.setItem(storageKey, JSON.stringify(pending)); }
    const result = await api('/api/jobs',{method:'POST',body:JSON.stringify({...args, request_id:pending.request_id})});
    if (!authenticated) return;
    openJob(result.job_id); sessionStorage.removeItem(storageKey);
  } catch(error) { notice(`提交未确认：${error.message} 再次点击会复用本次编号，避免重复创建。`); }
  finally { busy = false; controls(); }
};
$('retry-ppt').onclick = async () => {
  if (busy || !canGenerate) return; busy = true; controls(); notice(); const id = active;
  try {
    const key = `nbppt-retry-${userId}-${id}`; let request_id = sessionStorage.getItem(key);
    if (!request_id) { request_id = crypto.randomUUID(); sessionStorage.setItem(key, request_id); }
    const result = await api(`/api/jobs/${id}/retry`,{method:'POST',body:JSON.stringify({request_id})});
    if (!authenticated) return;
    openJob(result.job_id);
  } catch(error) { notice(`重试未确认：${error.message} 可再次点击，仍复用同一编号。`); }
  finally { busy=false; controls(); }
};
$('history-open').onclick = async () => {
  if (!authenticated) return login(); const ticket = epoch; $('history').showModal(); $('history-list').textContent = '正在读取…';
  try {
    const data = await api('/api/jobs'); if (ticket !== epoch || !authenticated) return; $('history-list').replaceChildren();
    data.jobs.forEach(job => { const b = document.createElement('button'); b.textContent = `${job.job_id} · ${({RUNNING:'生成中',FAILED:'失败',COMPLETED:'待审阅'})[job.status] || job.status} · ${job.created_at || ''}`; b.onclick = () => { $('history').close(); openJob(job.job_id); }; $('history-list').append(b); });
    if (!data.jobs.length) $('history-list').textContent = '还没有任务。';
  } catch(error) { $('history-list').textContent = error.message; }
};
$('history-close').onclick = () => $('history').close(); $('back-edit').onclick = showComposer; $('resume-task').onclick = showTask; $('refresh').onclick = () => { notice(); poll(); };
$('source').oninput = () => { $('count').textContent = `${$('source').value.length} 字`; };
$('example').onclick = () => { $('source').value = sample; $('source').oninput(); $('source').focus(); };
for (const id of ['style','pages']) $(id).onchange = () => { $('config-summary').textContent = `${$('style').selectedOptions[0].text} · ${$('pages').selectedOptions[0].text}`; };
for (let i=1;i<=5;i++) { const b = document.createElement('button'); b.type='button'; b.setAttribute('aria-label',`查看样例第${i}页`); b.setAttribute('aria-pressed',String(i===3)); const img=document.createElement('img'); img.src=`/static/samples/slide_preview_${i}.png`; img.alt=''; b.append(img); b.onclick=()=> { $('gallery-main').src=img.src; $('gallery-main').alt=`已有样例第${i}页`; $('gallery-count').textContent=`${i} / 5`; [...$('gallery-picks').children].forEach(c=>c.setAttribute('aria-pressed',String(c===b))); }; $('gallery-picks').append(b); }
$('slide').onerror = () => notice('预览图片加载失败，请刷新状态或重新登录。');
initialize().catch(error => { controls(); if(authenticated) { notice(`初始化失败：${error.message} 点击重新连接再试。`); $('account').textContent = '重新连接'; } });
