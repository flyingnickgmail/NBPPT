const $ = id => document.getElementById(id);
const number = value => Number(value || 0).toLocaleString('zh-CN');
let keys = [], selected = null, issued = null, userId = '', epoch = 0, busy = false;
const pending = new Map();
function message(text = '', error = false) { $('notice').textContent = text; $('notice').hidden = !text; $('notice').classList.toggle('error', error); }
function formError(id, text = '') { $(id).textContent = text; $(id).hidden = !text; }
function clearIssued() { issued = null; $('new-secret').value = ''; $('new-account-meta').textContent = ''; $('secret-notice').textContent = ''; }
function clearPrivate() {
  epoch++; keys = []; selected = null; userId = ''; pending.clear(); clearIssued();
  $('key-rows').replaceChildren(); $('audit-list').replaceChildren(); $('admin-content').hidden = true;
  for (const name of ['create','settings','credits']) $(name+'-form').reset();
  $('selected-meta').textContent = ''; $('manage-heading').textContent = '管理密钥';
  $('selected-balance').textContent = $('selected-frozen').textContent = '—';
  for (const id of ['account-count','active-count','balance-total','frozen-total','shared-note','daily-detail','claude-detail','result-count']) $(id).textContent = '';
  for (const id of ['create-error','credits-error','settings-error']) formError(id);
  message();
  for (const dialog of document.querySelectorAll('dialog')) dialog.close();
}
async function api(path, options = {}) {
  const start = epoch;
  const response = await fetch(path, {credentials:'same-origin', ...options, headers:{'Content-Type':'application/json', ...options.headers}});
  let body;
  try { body = await response.json(); }
  catch { if (response.ok) throw new Error('未收到完整的操作结果'); body = {}; }
  if (start !== epoch) { const error = new Error('会话已切换，已丢弃旧请求结果'); error.stale = true; throw error; }
  if (!response.ok) {
    const text = typeof body.detail === 'string' ? body.detail : `参数或请求无效（${response.status}）`;
    if (response.status === 401 || (response.status === 403 && text === 'Administrator required')) {
      clearPrivate(); location.replace('/?next=admin');
    }
    const error = new Error(text); error.confirmed = response.status < 500 && response.status !== 408; throw error;
  }
  return body;
}
async function mutate(slot, path, method, values) {
  const fingerprint = JSON.stringify([path, method, values]);
  let operation = pending.get(slot);
  if (operation && operation.fingerprint !== fingerprint) throw new Error('上一笔操作尚未确认。请保持原参数再次提交核对结果，或刷新数据后核查操作记录。');
  if (!operation) { operation = {fingerprint, id:crypto.randomUUID()}; pending.set(slot, operation); }
  try {
    const result = await api(path, {method, body:JSON.stringify({...values, request_id:operation.id})});
    pending.delete(slot); return result;
  } catch (error) {
    if (error.confirmed) pending.delete(slot);
    if (!error.confirmed && !error.stale) error.message += '；结果尚未确认，保持参数再次提交会核对同一笔操作，不会重复记账。';
    throw error;
  }
}
function controls() {
  for (const button of document.querySelectorAll('[data-write]')) button.disabled = busy;
  $('refresh').disabled = busy;
  for (const form of document.querySelectorAll('form')) for (const field of form.querySelectorAll('input,select,textarea')) field.disabled = busy;
  if (selected) {
    const inactive = !selected.is_active;
    for (const field of $('settings-form').querySelectorAll('input,select,textarea,button')) field.disabled = busy || inactive;
    $('edit-scope').disabled = busy || inactive || selected.scope === 'admin';
    $('edit-claude').disabled = busy || inactive;
    $('revoke').disabled = busy || inactive || selected.is_current;
  }
}
function cell(tag, text, className = '') { const node = document.createElement(tag); node.textContent = text; if (className) node.className = className; return node; }
function renderKeys() {
  const query = $('search').value.trim().toLowerCase(), status = $('status-filter').value;
  const visible = keys.filter(key => (status === 'all' || Boolean(key.is_active) === (status === 'active')) &&
    `${key.name} ${key.user_id} ${key.api_key}`.toLowerCase().includes(query));
  const rows = visible.map(key => {
    const row = document.createElement('tr'), identity = document.createElement('td');
    const name = cell('strong', key.name || '未命名密钥');
    name.append(cell('span', key.is_active ? (key.is_current ? '当前登录' : '有效') : '已停用', key.is_active ? 'badge' : 'badge revoked'));
    identity.append(name, cell('small', `${key.api_key} · ${key.user_id.slice(0,8)}`, 'mono'));
    const balance = document.createElement('td'); balance.append(cell('strong', number(key.credits_available)), cell('small', `冻结 ${number(key.credits_frozen)} 点`));
    const daily = document.createElement('td'); daily.append(cell('strong', `${number(key.daily_spent)} / ${number(key.effective_daily_limit)} 点`), cell('small', `设置上限 ${number(key.daily_credit_limit)} 点`));
    const permission = document.createElement('td');
    permission.append(cell('strong', key.scope === 'admin' ? '管理员' : key.scope === 'read' ? '只读成果' : '允许生成'),
      cell('small', key.allow_claude ? (key.claude_configured ? 'Claude 已允许' : 'Claude 已允许 · 服务未启用') : 'Claude 已关闭'));
    const actions = document.createElement('td'), button = cell('button', key.is_active ? '管理' : '查看'); button.type = 'button';
    button.setAttribute('aria-label', `管理 ${key.name}`); button.onclick = () => { if (!busy) openEditor(key.key_id); }; actions.append(button);
    row.append(identity,balance,daily,permission,actions); return row;
  });
  $('key-rows').replaceChildren(...rows); $('empty').hidden = visible.length > 0; $('result-count').textContent = `${visible.length} 把密钥`;
  const accounts = [...new Map(keys.map(key => [key.user_id,key])).values()];
  $('account-count').textContent = number(accounts.length); $('active-count').textContent = number(keys.filter(key => key.is_active).length);
  $('balance-total').textContent = number(accounts.reduce((sum,key) => sum + key.credits_available,0));
  $('frozen-total').textContent = number(accounts.reduce((sum,key) => sum + key.credits_frozen,0));
}
function renderAudit(actions) {
  const labels = {CREATE_KEY:'创建独立账户与密钥', UPDATE_KEY:'修改密钥权限与上限', ADJUST_CREDITS:'调整账户算力点', REVOKE_KEY:'停用访问密钥', CREATE_ADMIN_LOGIN:'创建管理员登录密钥'};
  const rows = actions.map(action => {
    const row = document.createElement('li'), text = document.createElement('div'), result = action.result || {};
    let description = labels[action.action] || '管理操作';
    if (action.action === 'ADJUST_CREDITS') description += ` · ${result.delta > 0 ? '+' : ''}${number(result.delta)} 点${result.note ? ' · '+result.note : ''}`;
    if (action.action === 'CREATE_KEY') description += ` · ${result.name || ''} · 初始 ${number(result.credits_available)} 点`;
    if (action.action === 'UPDATE_KEY') {
      const changes = [];
      if ('name' in result) changes.push('名称：'+result.name);
      if ('scope' in result) changes.push(result.scope === 'read' ? '只读权限' : '允许生成');
      if ('daily_credit_limit' in result) changes.push('日上限 '+number(result.daily_credit_limit)+' 点');
      if ('allow_claude' in result) changes.push(result.allow_claude ? '允许 Claude' : '关闭 Claude');
      description += ' · '+changes.join('，');
    }
    text.append(cell('span', description), cell('small', `账户 ${result.user_id || action.target_id} · 操作人 ${action.actor_user_id}`, 'mono'));
    const time = cell('time', action.created_at); row.append(text,time); return row;
  });
  $('audit-list').replaceChildren(...rows); $('audit-empty').hidden = rows.length > 0;
}
async function refreshRecords(resetEditor = false) {
  const start = epoch;
  const [registry, audit] = await Promise.all([api('/api/admin/keys'), api('/api/admin/actions')]);
  if (start !== epoch) return;
  keys = registry.keys; renderKeys(); renderAudit(audit.actions);
  if (selected) { selected = keys.find(key => key.key_id === selected.key_id) || null; if (selected) renderSelected(resetEditor); }
  controls();
}
async function initialize() {
  const session = await api('/api/session');
  if (!session.admin) { clearPrivate(); location.replace('/'); return; }
  if (userId && userId !== session.user_id) clearPrivate();
  userId = session.user_id;
  await refreshRecords(); $('loading').hidden = true; $('admin-content').hidden = false;
}
function renderSelected(reset) {
  const key = selected;
  $('manage-heading').textContent = key.name || '管理密钥';
  $('selected-meta').textContent = `账户 ${key.user_id} · 密钥 ${key.api_key}`;
  $('shared-note').textContent = key.account_key_count > 1 ? `此账户有 ${key.account_key_count} 把密钥，共享历史、余额和每日累计尝试点数。余额调整将作用于整个账户。` : '此密钥归属独立账户，历史与余额不会与其他账户共享。';
  $('selected-balance').textContent = number(key.credits_available); $('selected-frozen').textContent = number(key.credits_frozen);
  $('daily-detail').textContent = `今日已尝试 ${number(key.daily_spent)} 点；当前实际日上限 ${number(key.effective_daily_limit)} 点。修改上限不会重置今日用量。`;
  $('claude-detail').textContent = '按密钥独立授权，历史与额度仍属于当前账户。只读权限不能生成；Claude 的供应商用量与冷却由服务器统一管理。' + (key.claude_configured ? '' : ' 当前服务器尚未启用 Claude，可先设置权限。');
  $('revoke-note').textContent = key.is_current ? '当前管理员登录密钥受保护，不能在此停用。' : key.is_active ? '停用不可恢复，网页会话同时失效；已受理的任务继续完成，账户账目保留。' : '这把密钥已停用；账目保留，可继续核查或调整账户可用点数。';
  if (reset) { $('edit-name').value = key.name; $('edit-limit').value = key.daily_credit_limit; $('edit-scope').value = key.scope; $('edit-claude').checked = key.allow_claude; }
}
function openEditor(keyId) {
  selected = keys.find(key => key.key_id === keyId); if (!selected) return;
  for (const id of ['settings-error','credits-error']) formError(id);
  $('credits-form').reset(); renderSelected(true); controls(); $('manage-dialog').showModal();
}
async function runForm(errorId, action) {
  if (busy) return;
  formError(errorId); busy = true; controls();
  try { await action(); } catch (error) { if (!error.stale) formError(errorId,error.message); }
  finally { busy = false; controls(); }
}
async function afterWrite(reset = false) {
  try { await refreshRecords(reset); }
  catch (error) { if (!error.stale) message('操作已成功，但列表刷新失败。请刷新数据核查，勿重复创建或调整。'+error.message,true); }
}
$('create-open').onclick = () => { if (busy) return; if (!pending.has('create')) $('create-form').reset(); formError('create-error'); $('create-dialog').showModal(); };
$('create-form').onsubmit = event => {
  event.preventDefault();
  return runForm('create-error',async () => {
    const values = {name:$('create-name').value.trim(), initial_credits:Number($('create-credits').value), daily_credit_limit:Number($('create-limit').value), scope:$('create-scope').value, allow_claude:$('create-claude').checked};
    const result = await mutate('create','/api/admin/keys','POST',values);
    issued = result.new_key; $('new-secret').value = issued.api_key;
    $('new-account-meta').textContent = `账户 ${issued.user_id} · 初始点数 ${number(issued.credits_available)} · 日上限 ${number(issued.daily_credit_limit)} 点 · Claude ${issued.allow_claude ? '允许' : '关闭'}`;
    $('create-dialog').close(); $('secret-dialog').showModal(); await afterWrite();
  });
};
$('settings-form').onsubmit = event => {
  event.preventDefault();
  return runForm('settings-error',async () => {
    const values = {}, draft = {name:$('edit-name').value.trim(), daily_credit_limit:Number($('edit-limit').value), allow_claude:$('edit-claude').checked};
    if (selected.scope !== 'admin') draft.scope = $('edit-scope').value;
    for (const [key,value] of Object.entries(draft)) if (value !== selected[key]) values[key] = value;
    if (!Object.keys(values).length) { message('设置没有变化，无需保存。'); return; }
    await mutate('settings-'+selected.key_id,'/api/admin/keys/'+selected.key_id,'PATCH',values);
    message('密钥设置已保存。后续提交与重试将使用新权限。'); await afterWrite(true);
  });
};
$('credits-form').onsubmit = event => {
  event.preventDefault();
  return runForm('credits-error',async () => {
    const delta = Number($('credit-amount').value) * ($('credit-direction').value === 'subtract' ? -1 : 1);
    const result = await mutate('credits-'+selected.key_id,'/api/admin/keys/'+selected.key_id+'/credits','POST',{delta,note:$('credit-note').value.trim()});
    message(`已${result.delta > 0 ? '增加' : '减少'} ${number(Math.abs(result.delta))} 点，此笔调整后余额 ${number(result.credits_available)} 点，最新余额见账户面板。`);
    $('credits-form').reset(); await afterWrite();
  });
};
$('revoke').onclick = () => runForm('settings-error',async () => {
  if (!selected || selected.is_current || !selected.is_active) return;
  if (!confirm(`确认停用“${selected.name}”吗？密钥和网页会话将失效，不可恢复；账户账目保留。`)) return;
  await mutate('revoke-'+selected.key_id,'/api/admin/keys/'+selected.key_id+'/revoke','POST',{});
  message('密钥已停用，相关网页会话已失效。'); await afterWrite(); controls();
});
for (const button of document.querySelectorAll('[data-close]')) button.onclick = () => { if (!busy) { if (button.dataset.close === 'secret-dialog') clearIssued(); $(button.dataset.close).close(); } };
for (const dialog of document.querySelectorAll('dialog')) dialog.addEventListener('cancel',event => { if (busy) event.preventDefault(); else if (dialog.id === 'secret-dialog') clearIssued(); });
$('secret-dialog').addEventListener('close',clearIssued);
$('copy-secret').onclick = async () => { try { if (issued) { await navigator.clipboard.writeText(issued.api_key); $('secret-notice').textContent = '密钥已复制。'; } } catch { $('secret-notice').textContent = '浏览器未允许复制，请在上方手动选择密钥。'; } };
$('download-config').onclick = () => {
  if (!issued) return;
  const config = {url:location.origin+'/mcp', api_key:issued.api_key, download_dir:'~/Downloads/NBPPT/'+issued.user_id};
  const url = URL.createObjectURL(new Blob([JSON.stringify(config,null,2)],{type:'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = 'nbppt-'+issued.user_id.slice(0,8)+'.json'; document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url),1000); $('secret-notice').textContent = '连接配置已下载，其中含密钥，请私下保存。';
};
$('search').oninput = renderKeys; $('status-filter').onchange = renderKeys;
$('refresh').onclick = async () => { if (busy) return; busy = true; controls(); try { await initialize(); message(pending.size ? '数据已刷新。尚未确认的操作可保持原参数再次提交核对，不会重复记账。' : '数据已刷新。'); } catch (error) { if (!error.stale) message(error.message,true); } finally { busy = false; controls(); } };
$('logout').onclick = async () => { clearPrivate(); try { await api('/api/session',{method:'DELETE'}); } catch {} location.replace('/'); };
window.addEventListener('pagehide',clearPrivate);
window.addEventListener('pageshow',event => { if (event.persisted) initialize().catch(error => { if (!error.stale) message(error.message,true); }); });
initialize().catch(error => { if (!error.stale) { $('loading').textContent = '暂时无法载入管理页面，请刷新重试。'; message(error.message,true); } });
