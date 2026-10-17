const $ = id => document.getElementById(id);
const sample = '为项目负责人制作客户问题协同试点汇报。以下是合成测试数据：本周收集12个问题，已解决7个，5个待处理。说明当前进展、销售与产品团队如何分工，以及下周逐项确认责任人与验收标准的计划。不要编造收益或客户案例。';
const kindsFor = mode => mode === 'composite' ? ['ppt', 'video'] : [mode];
const labels = {ppt:'PPT', video:'视频'};
let authenticated = false, busy = false, userId = '', canGenerate = false, ready = false;
let mode = 'ppt', capabilities = null, activeTask = null, epoch = 0;
const timers = {ppt:null, video:null}, sequences = {ppt:0, video:0};
const states = {ppt:null, video:null}, deliveries = {ppt:null, video:null};

function notice(message = '') { $('notice').textContent = message; $('notice').hidden = !message; }
function login() { if (!$('login').open) $('login').showModal(); }
function clearTimers() { for (const kind of ['ppt','video']) { clearTimeout(timers[kind]); timers[kind] = null; sequences[kind]++; } }
function clearDelivery(kind) {
  deliveries[kind] = null;
  if (kind === 'ppt') {
    $('slide').removeAttribute('src'); $('download').removeAttribute('href'); $('html-deck').removeAttribute('href');
    $('thumbnails').replaceChildren(); $('ppt-panel').hidden = true;
  } else {
    $('video-player').pause(); $('video-player').removeAttribute('src'); $('video-player').removeAttribute('poster');
    $('video-subtitles').removeAttribute('src'); $('video-player').load(); $('video-download').removeAttribute('href'); $('video-panel').hidden = true;
  }
}
function clearSession() {
  epoch++; clearTimers(); authenticated = false; ready = false; canGenerate = false; activeTask = null;
  states.ppt = states.video = null; clearDelivery('ppt'); clearDelivery('video');
  $('source').value = ''; $('count').textContent = '0 字'; $('history-list').replaceChildren(); $('history').close();
  $('task-summary').textContent = ''; $('request-source').textContent = ''; $('request-config').textContent = '';
  for (const kind of ['ppt','video']) { $(`${kind}-progress`).textContent = ''; $(`${kind}-billing`).textContent = ''; $(`retry-${kind}`).hidden = true; }
  $('account').textContent = '登录'; $('wallet').textContent = ''; $('admin').hidden = true; $('preview-empty').hidden = false;
  showComposer(); controls();
}
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
  $('task-view').hidden = true; $('back-edit').hidden = true; $('resume-task').hidden = !activeTask;
}
function controls() {
  const allowed = authenticated && ready && canGenerate && !busy;
  for (const name of ['ppt','video','composite']) $(`mode-${name}`).disabled = busy || (name !== 'ppt' && capabilities?.delivery_modes.video.supported !== true);
  $('submit').disabled = !allowed; $('account').disabled = busy;
  $('submit').textContent = busy ? '正在提交…' : authenticated ? (!canGenerate ? '当前凭据仅可查看任务' : mode === 'composite' ? '开始生成 PPT＋视频 →' : `开始生成${labels[mode]} →`) : '登录后开始生成 →';
  for (const kind of ['ppt','video']) $(`retry-${kind}`).disabled = !allowed;
}
function updateMode(next) {
  if (busy) return;
  if (!['ppt','video','composite'].includes(next)) return;
  if (next !== 'ppt' && capabilities && !capabilities.delivery_modes.video.supported) next = 'ppt';
  mode = next;
  for (const name of ['ppt','video','composite']) $(`mode-${name}`).setAttribute('aria-pressed', String(name === mode));
  $('ppt-options').hidden = mode === 'video'; $('video-options').hidden = mode === 'ppt'; updateSummary(); updateCost(); controls();
}
function updateSummary() {
  const parts = [$('style').selectedOptions[0].text];
  if (mode !== 'video') parts.push($('pages').selectedOptions[0].text);
  if (mode !== 'ppt') parts.push(`${$('video-duration').value} 秒`, $('video-ratio').value);
  $('config-summary').textContent = parts.join(' · ');
}
function updateCost() {
  if (!capabilities) return;
  const costs = kindsFor(mode).map(kind => capabilities.delivery_modes[kind].freeze_credits);
  $('cost').textContent = `提交时分别冻结 ${costs.join('＋')} 点算力，按各自产物结算；失败项自动退回。`;
}
function safeArtifact(path, jobId) {
  if (typeof path !== 'string' || typeof jobId !== 'string' || !path.startsWith(`/artifacts/${jobId}/`) || path.includes('..') || path.includes('\\')) throw new Error('产物地址校验失败');
  const url = new URL(path, location.origin);
  if (url.origin !== location.origin || !url.pathname.startsWith(`/artifacts/${jobId}/`) || url.search || url.hash) throw new Error('产物地址校验失败');
  return path;
}
function showSlide(index) {
  const result = deliveries.ppt, jobId = activeTask.jobs.ppt, pages = result.artifacts.slide_preview_urls;
  $('slide').src = safeArtifact(pages[index], jobId); $('slide').alt = `生成结果第 ${index + 1} 页`;
  $('slide-title').textContent = `第 ${index + 1} 页`; $('position').textContent = `${index + 1} / ${pages.length}`;
  [...$('thumbnails').children].forEach((button,i) => button.setAttribute('aria-pressed', String(i === index)));
}
function renderPpt(result, jobId) {
  const links = result.artifacts, pages = links.slide_preview_urls;
  if (!Array.isArray(pages) || !pages.length) throw new Error('PPT预览文件缺失');
  [...pages, links.pptx_url, links.html_deck_url].forEach(path => safeArtifact(path, jobId));
  deliveries.ppt = result; $('thumbnails').replaceChildren();
  pages.forEach((path,i) => {
    const button = document.createElement('button'); button.type = 'button'; button.setAttribute('aria-label', `查看第 ${i+1} 页`);
    const img = document.createElement('img'); img.src = safeArtifact(path, jobId); img.alt = ''; button.append(img);
    button.onclick = () => showSlide(i); $('thumbnails').append(button);
  });
  $('download').href = safeArtifact(links.pptx_url, jobId); $('html-deck').href = safeArtifact(links.html_deck_url, jobId);
  $('ppt-panel').hidden = false; showSlide(0); updatePreview();
}
function renderVideo(result, jobId) {
  const links = result.artifacts;
  $('video-player').src = safeArtifact(links.mp4_url, jobId);
  if (links.video_poster_url) $('video-player').poster = safeArtifact(links.video_poster_url, jobId); else $('video-player').removeAttribute('poster');
  if (links.subtitles_url) $('video-subtitles').src = safeArtifact(links.subtitles_url, jobId); else $('video-subtitles').removeAttribute('src');
  $('video-download').href = safeArtifact(links.mp4_url, jobId); $('video-player').load(); deliveries.video = result;
  $('video-panel').hidden = false; updatePreview();
}
function updatePreview() {
  const parts = [];
  if (deliveries.ppt) parts.push(`${deliveries.ppt.slide_count} 页 PPT 已通过文件验收`);
  if (deliveries.video) parts.push('视频已通过文件验收');
  $('preview-empty').hidden = parts.length > 0; $('preview-context').textContent = parts.length ? `${parts.join('；')}。内容仍需人工审阅。` : '';
}
function stageStep(stage) { return ({queued:-1,planning:0,generating:1,rendering:1,checking:2,ready:3})[stage] ?? -1; }
function renderTrack(kind) {
  const state = states[kind], retry = $(`retry-${kind}`), meter = $(`${kind}-meter`), steps = $(`${kind}-phase-steps`);
  if (!activeTask.jobs[kind]) {
    const error = activeTask.submit_errors[kind]; $(`${kind}-progress`).textContent = error ? `提交未确认：${error}` : '正在提交任务…';
    $(`${kind}-billing`).textContent = error ? '尚未确认冻结；再次提交会复用同一编号，不会创建重复任务。' : '等待服务器确认任务。';
    retry.textContent = `重新提交${labels[kind]}`; retry.hidden = !error || !canGenerate; meter.hidden = true;
    [...steps.children].forEach(node => { node.className = error ? 'error' : ''; node.setAttribute('aria-current','false'); }); return;
  }
  if (!state) { $(`${kind}-progress`).textContent = '正在获取真实状态…'; retry.hidden = true; meter.hidden = false; meter.removeAttribute('value'); return; }
  const step = stageStep(state.stage);
  [...steps.children].forEach((node,i) => { node.className = state.status === 'FAILED' && i === Math.max(step,0) ? 'error' : i < step ? 'done' : i === step ? 'active' : ''; node.setAttribute('aria-current', i === step ? 'step' : 'false'); });
  $(`${kind}-progress`).textContent = state.status === 'COMPLETED' ? '文件检查通过，可以预览和下载。内容仍需人工复核。' : (state.message || '任务执行中，等待服务器更新');
  if (Number.isFinite(state.percent)) { meter.hidden = false; meter.value = state.percent; } else { meter.hidden = state.status !== 'RUNNING'; meter.removeAttribute('value'); }
  retry.textContent = `重试${labels[kind]}`; retry.hidden = state.status !== 'FAILED' || !canGenerate;
  $(`${kind}-billing`).textContent = state.status === 'FAILED' ? '本项失败，冻结算力已退回；重试会创建新任务并重新冻结。' : state.status === 'COMPLETED' ? `本项结算 ${state.credits_charged} 点算力。` : '完成验收后结算；失败自动退回本项冻结算力。';
}
function updateAggregate() {
  if (!activeTask) return;
  const kinds = kindsFor(activeTask.mode), current = kinds.map(kind => activeTask.jobs[kind] ? states[kind]?.status : (activeTask.submit_errors[kind] ? 'SUBMIT_FAILED' : 'SUBMITTING'));
  const complete = current.filter(x => x === 'COMPLETED').length, failed = current.filter(x => x === 'FAILED' || x === 'SUBMIT_FAILED').length;
  $('task-state').textContent = complete === kinds.length ? '待审阅' : complete && failed ? '部分完成' : failed === kinds.length ? '生成失败' : failed ? '部分失败' : '生成中';
  $('updated').textContent = `最近同步：${new Date().toLocaleTimeString('zh-CN')}`;
}
function persistActive() { if (activeTask && userId) sessionStorage.setItem(`nbppt-active-${userId}`, JSON.stringify(activeTask)); }
function validJobId(id) { return typeof id === 'string' && /^[a-z]+_[a-f0-9]{10}$/.test(id); }
function normalizeTask(value) {
  if (typeof value === 'string' && validJobId(value)) { const kind = value.startsWith('video_') ? 'video' : 'ppt'; return {mode:kind,jobs:{[kind]:value},request_ids:{},submit_errors:{},input:{}}; }
  if (!value || !['ppt','video','composite'].includes(value.mode)) return null;
  value.jobs ||= {}; value.request_ids ||= {}; value.submit_errors ||= {}; value.input ||= {}; return value;
}
function resetTaskView() {
  states.ppt = states.video = null; clearDelivery('ppt'); clearDelivery('video'); $('preview-empty').hidden = false; $('preview-context').textContent = '';
  for (const kind of ['ppt','video']) { const shown = activeTask && kindsFor(activeTask.mode).includes(kind); $(`${kind}-track`).hidden = !shown; if (shown) renderTrack(kind); }
}
function activateTask(task) {
  const normalized = normalizeTask(task); if (!normalized) throw new Error('无效的任务记录');
  epoch++; clearTimers(); activeTask = normalized; persistActive(); resetTaskView();
  const ids = kindsFor(activeTask.mode).map(kind => activeTask.jobs[kind]).filter(Boolean);
  $('task-summary').textContent = ids.length ? ids.join(' · ') : '任务提交状态待确认'; $('request-source').textContent = activeTask.input.source || '';
  $('request-config').textContent = activeTask.mode === 'ppt' ? `${activeTask.input.template_id || 'auto'} · ${activeTask.input.slide_count || '自动'} 页` : activeTask.mode === 'video' ? `${activeTask.input.video_duration_sec || 30} 秒 · ${activeTask.input.video_aspect_ratio || '16:9'}` : `PPT ${activeTask.input.slide_count || '自动'} 页 · 视频 ${activeTask.input.video_duration_sec || 30} 秒 · ${activeTask.input.video_aspect_ratio || '16:9'}`;
  showTask(); $('task-title').focus(); updateAggregate(); refreshWallet().catch(() => {});
  for (const kind of kindsFor(activeTask.mode)) if (activeTask.jobs[kind]) pollKind(kind);
}
async function pollKind(kind) {
  clearTimeout(timers[kind]); const taskEpoch = epoch, jobId = activeTask?.jobs[kind], sequence = ++sequences[kind];
  if (!jobId || !authenticated) return;
  try {
    const status = await api(`/api/jobs/${jobId}`);
    if (taskEpoch !== epoch || sequence !== sequences[kind] || activeTask?.jobs[kind] !== jobId) return;
    states[kind] = status; renderTrack(kind); updateAggregate();
    if (status.status === 'COMPLETED' && !deliveries[kind]) {
      const result = await api(`/api/jobs/${jobId}/artifacts`);
      if (taskEpoch !== epoch || sequence !== sequences[kind] || activeTask?.jobs[kind] !== jobId) return;
      if (kind === 'ppt') renderPpt(result, jobId); else renderVideo(result, jobId);
    }
    if (status.status === 'RUNNING') timers[kind] = setTimeout(() => pollKind(kind), 5000); else refreshWallet().catch(() => {});
  } catch (error) {
    if (taskEpoch !== epoch || sequence !== sequences[kind] || activeTask?.jobs[kind] !== jobId) return;
    notice(`${labels[kind]}状态同步中断：${error.message} 已保留任务，不会重复扣费。`);
    if (authenticated) timers[kind] = setTimeout(() => pollKind(kind), 10000);
  }
}
async function refreshWallet() { const authEpoch = epoch; const data = await api('/api/wallet'); if (authEpoch !== epoch || !authenticated) return; $('wallet').textContent = `可用 ${data.user.credits_available} 点`; }
function payloadFor(kind, task = activeTask) {
  const input = task.input;
  return {source:input.source, template_id:input.template_id || 'auto', slide_count:Number(input.slide_count || 0), task_type:kind, video_duration_sec:Number(input.video_duration_sec || 30), video_aspect_ratio:input.video_aspect_ratio || '16:9', request_id:task.request_ids[kind]};
}
async function submitKind(kind) {
  const task = activeTask;
  if (!task || task.jobs[kind]) return task?.jobs[kind];
  task.submit_errors[kind] = null; persistActive(); renderTrack(kind); updateAggregate();
  try {
    const result = await api('/api/jobs', {method:'POST', body:JSON.stringify(payloadFor(kind, task))});
    if (!authenticated || activeTask !== task) return;
    if (!validJobId(result.job_id)) throw new Error('服务器返回了无效任务编号');
    task.jobs[kind] = result.job_id; task.submit_errors[kind] = null; persistActive();
    $('task-summary').textContent = kindsFor(task.mode).map(name => task.jobs[name]).filter(Boolean).join(' · ');
    renderTrack(kind); pollKind(kind); refreshWallet().catch(() => {}); return result.job_id;
  } catch (error) {
    if (authenticated && activeTask === task) { task.submit_errors[kind] = error.message; persistActive(); renderTrack(kind); updateAggregate(); }
    throw error;
  }
}
async function retryFailedJob(kind) {
    const task = activeTask, oldId = task.jobs[kind], key = `nbppt-retry-${userId}-${oldId}`;
    let requestId = sessionStorage.getItem(key); if (!requestId) { requestId = crypto.randomUUID(); sessionStorage.setItem(key, requestId); }
    const result = await api(`/api/jobs/${oldId}/retry`, {method:'POST', body:JSON.stringify({request_id:requestId})});
    if (!authenticated || activeTask !== task) return;
    if (!validJobId(result.job_id)) throw new Error('服务器返回了无效任务编号');
    task.jobs[kind] = result.job_id; states[kind] = null; clearDelivery(kind); persistActive(); renderTrack(kind); updateAggregate();
    $('task-summary').textContent = kindsFor(task.mode).map(name => task.jobs[name]).filter(Boolean).join(' · ');
    pollKind(kind); refreshWallet().catch(() => {});
}
async function retryKind(kind) {
  if (busy || !canGenerate || !activeTask || !kindsFor(activeTask.mode).includes(kind)) return;
  busy = true; controls(); notice();
  try {
    if (!activeTask.jobs[kind]) { await submitKind(kind); return; }
    if (states[kind]?.status !== 'FAILED') return;
    await retryFailedJob(kind);
  } catch (error) { notice(`${labels[kind]}重试未确认：${error.message} 再次点击会复用同一编号。`); }
  finally { busy = false; controls(); }
}
async function initialize() {
  const initEpoch = epoch, session = await api('/api/session'); if (initEpoch !== epoch) return;
  if (userId && userId !== session.user_id) {
    activeTask = null; clearTimers(); states.ppt = states.video = null; clearDelivery('ppt'); clearDelivery('video');
    $('source').value = ''; $('count').textContent = '0 字'; $('history-list').replaceChildren();
    $('task-summary').textContent = ''; $('request-source').textContent = ''; $('request-config').textContent = ''; showComposer();
  }
  userId = session.user_id; authenticated = true; canGenerate = session.can_generate === true; ready = false; $('account').textContent = '退出'; $('admin').hidden = !session.admin;
  const templates = await api('/api/templates'); if (initEpoch !== epoch) return; $('style').replaceChildren(new Option('自动匹配','auto'));
  templates.templates.forEach(t => { if (t.id !== 'auto') $('style').add(new Option(t.name, t.id)); });
  capabilities = await api('/api/capabilities'); if (initEpoch !== epoch) return;
  const videoSupported = capabilities.delivery_modes.video.supported === true; $('mode-video').disabled = !videoSupported; $('mode-composite').disabled = !videoSupported;
  if (!videoSupported && mode !== 'ppt') updateMode('ppt'); else updateMode(mode);
  await refreshWallet(); if (initEpoch !== epoch) return; ready = true; controls();
  const raw = sessionStorage.getItem(`nbppt-active-${userId}`);
  if (raw) {
    let saved = null;
    try { saved = normalizeTask(JSON.parse(raw)); } catch { saved = normalizeTask(raw); }
    if (saved) activateTask(saved); else sessionStorage.removeItem(`nbppt-active-${userId}`);
  }
}

for (const name of ['ppt','video','composite']) $(`mode-${name}`).onclick = () => updateMode(name);
$('login-form').onsubmit = async event => {
  event.preventDefault(); $('login-error').textContent = '';
  try { await api('/api/session',{method:'POST',body:JSON.stringify({api_key:$('key').value})}); $('key').value = ''; $('login').close(); await initialize(); }
  catch(error) { if ($('login').open) $('login-error').textContent = error.message; else { notice(`初始化失败：${error.message} 点击重新连接再试。`); $('account').textContent = '重新连接'; } controls(); }
};
$('login-close').onclick = () => $('login').close();
$('account').onclick = async () => {
  if (!authenticated) return login(); if (!ready) { try { await initialize(); notice(); } catch(error) { notice(error.message); } return; }
  try { await api('/api/session',{method:'DELETE'}); clearSession(); } catch(error) { notice(error.message); }
};
$('brief').onsubmit = async event => {
  event.preventDefault(); if (busy || !authenticated || !ready || !canGenerate) return;
  const requestedMode = mode;
  const input = {source:$('source').value.trim(), template_id:$('style').value, slide_count:Number($('pages').value), video_duration_sec:Number($('video-duration').value), video_aspect_ratio:$('video-ratio').value};
  if (input.source.length < 20) return notice('请至少输入20个字的原文与要求。');
  if (mode !== 'ppt' && (!Number.isInteger(input.video_duration_sec) || input.video_duration_sec < 6 || input.video_duration_sec > 60)) return notice('视频时长须为 6–60 秒整数。');
  busy = true; controls(); notice();
  try {
    const signature = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify({mode:requestedMode,input}))))).map(b=>b.toString(16).padStart(2,'0')).join('');
    const requestedKinds = kindsFor(requestedMode), sameUnfinished = activeTask?.signature === signature && requestedKinds.some(kind => !activeTask.jobs[kind] || states[kind]?.status !== 'COMPLETED');
    const failedKinds = sameUnfinished ? requestedKinds.filter(kind => activeTask.jobs[kind] && states[kind]?.status === 'FAILED') : [];
    if (!sameUnfinished) { const requestIds = {}; requestedKinds.forEach(kind => requestIds[kind] = crypto.randomUUID()); activeTask = {mode:requestedMode, input, signature, jobs:{}, request_ids:requestIds, submit_errors:{}}; }
    activateTask(activeTask);
    await Promise.allSettled([
      ...kindsFor(activeTask.mode).filter(kind => !activeTask.jobs[kind]).map(submitKind),
      ...failedKinds.map(retryFailedJob)
    ]);
  } finally { busy = false; controls(); }
};
$('retry-ppt').onclick = () => retryKind('ppt'); $('retry-video').onclick = () => retryKind('video');
$('history-open').onclick = async () => {
  if (!authenticated) return login(); if (busy) return notice('任务正在提交，请等待服务器确认后再打开历史记录。'); const ticket = epoch; $('history').showModal(); $('history-list').textContent = '正在读取…';
  try {
    const data = await api('/api/jobs'); if (ticket !== epoch || !authenticated) return; $('history-list').replaceChildren();
    data.jobs.forEach(job => { const kind = job.task_type === 'video' || String(job.job_id).startsWith('video_') ? 'video' : 'ppt'; const b = document.createElement('button'); b.textContent = `${labels[kind]} · ${job.job_id} · ${({RUNNING:'生成中',FAILED:'失败',COMPLETED:'待审阅'})[job.status] || job.status} · ${job.created_at || ''}`; b.onclick = () => { $('history').close(); activateTask({mode:kind,jobs:{[kind]:job.job_id},request_ids:{},submit_errors:{},input:{source:job.cn_user_prompt || ''}}); }; $('history-list').append(b); });
    if (!data.jobs.length) $('history-list').textContent = '还没有任务。';
  } catch(error) { $('history-list').textContent = error.message; }
};
$('history-close').onclick = () => $('history').close(); $('back-edit').onclick = showComposer; $('resume-task').onclick = showTask;
$('refresh').onclick = () => { notice(); if (activeTask) kindsFor(activeTask.mode).forEach(kind => activeTask.jobs[kind] && pollKind(kind)); };
$('source').oninput = () => { $('count').textContent = `${$('source').value.length} 字`; }; $('example').onclick = () => { $('source').value = sample; $('source').oninput(); $('source').focus(); };
for (const id of ['style','pages','video-duration','video-ratio']) $(id).onchange = updateSummary;
for (let i=1;i<=5;i++) { const b = document.createElement('button'); b.type='button'; b.setAttribute('aria-label',`查看样例第${i}页`); b.setAttribute('aria-pressed',String(i===3)); const img=document.createElement('img'); img.src=`/static/samples/slide_preview_${i}.png`; img.alt=''; b.append(img); b.onclick=()=> { $('gallery-main').src=img.src; $('gallery-main').alt=`已有样例第${i}页`; $('gallery-count').textContent=`${i} / 5`; [...$('gallery-picks').children].forEach(c=>c.setAttribute('aria-pressed',String(c===b))); }; $('gallery-picks').append(b); }
$('slide').onerror = () => notice('PPT预览图片加载失败，请刷新状态或重新登录。'); $('video-player').onerror = () => notice('视频预览加载失败，请刷新状态或下载文件检查。');
updateMode('ppt');
initialize().catch(error => { controls(); if (authenticated) { notice(`初始化失败：${error.message} 点击重新连接再试。`); $('account').textContent = '重新连接'; } });
