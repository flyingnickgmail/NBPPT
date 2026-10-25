/** Real root-page acceptance. No mocked responses, DOM stand-ins or live models. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import readline from 'node:readline';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(path.join(root, 'tests/browser/package.json'));
const {chromium} = require('playwright');
const output = path.resolve(process.argv[2] || '');
assert(process.argv[2] && path.isAbsolute(process.argv[2]), 'Pass an absolute, fresh acceptance output directory');
await fs.mkdir(output, {recursive: true});
const server = spawn(process.env.NBPPT_TEST_PYTHON || 'python3',
  ['-B', path.join(root, 'tools/workbench_fixture.py'), '--output', output],
  {cwd: root, env: process.env, stdio: ['ignore', 'pipe', 'pipe']});
let logs = '', browser, context;
server.stderr.on('data', x => { logs = (logs+x).slice(-50000); });
const lines = readline.createInterface({input: server.stdout});
const errors = [], requests = [], submitted = [], progress = [];
const receipt = {kind:'real_workbench_offline_acceptance', planner:'fixed_test_data',
  renderer:'real_worker_ffmpeg', tree_sha256:process.env.NBPPT_ACCEPTANCE_TREE_SHA || null,
  assertions:[], production_access:false, model_calls:0};
const record = name => receipt.assertions.push(name);
async function waitForServer(origin) {
  for (let i=0;i<100;i++) {
    if (server.exitCode !== null) throw new Error('Fixture exited: '+logs.slice(-1500));
    try { if ((await fetch(origin+'/')).ok) return; } catch {}
    await new Promise(r=>setTimeout(r,100));
  }
  throw new Error('Fixture did not become ready');
}
try {
  const line = await Promise.race([once(lines,'line').then(([s])=>s),
    once(server,'exit').then(()=>{throw new Error('Fixture startup failed: '+logs.slice(-1500));}),
    new Promise((_,reject)=>{const timer=setTimeout(()=>reject(new Error('Fixture ready timeout')),30000);timer.unref();})]);
  const fixture = JSON.parse(line);
  await waitForServer(fixture.origin);
  receipt.origin = fixture.origin; receipt.page_path = '/';
  browser = await chromium.launch({headless:true,chromiumSandbox:true});
  context = await browser.newContext({viewport:{width:1280,height:900}, acceptDownloads:true});
  // All browser requests stay on this fixture, including media. Block external egress.
  await context.route('**/*', route => new URL(route.request().url()).origin === fixture.origin
    ? route.continue() : route.abort());
  const page = await context.newPage();
  page.on('pageerror', error=>errors.push(error.message));
  page.on('request', req=>{
    if (new URL(req.url()).pathname === '/api/jobs' && req.method()==='POST') requests.push(req.postDataJSON());
  });
  page.on('response', async res=>{
    const p=new URL(res.url()).pathname;
    if (res.request().method()==='GET' && /^\/api\/jobs\/video_[a-z0-9]+$/.test(p) && res.ok()) {
      const body=await res.json();
      if(body.status==='RUNNING')progress.push({percent:body.percent,stage:body.stage});
    }
    if (res.request().method()==='POST' && (p==='/api/jobs'||p.endsWith('/retry')) && res.ok()) {
      const body=await res.json(); if(body.job_id) submitted.push(body.job_id);
    }
  });
  await page.goto(fixture.origin+'/');
  assert.match(await page.title(), /内容创作工作台/);
  await page.locator('#key').fill(fixture.key_a);
  await page.locator('#login-form button[type=submit]').click();
  await page.locator('#mode-video:not([disabled])').waitFor();
  await page.locator('#mode-video').click();
  await page.locator('#video-audio-options').waitFor({state:'visible'});
  assert.equal(await page.locator('.creation-options').getAttribute('open'),null);
  await page.locator('#video-voice').selectOption('microsoft_xiaoxiao');
  await page.locator('#video-voice-audition').click();
  await page.waitForFunction(()=>{const a=document.querySelector('#video-voice-audio');return !a.paused&&a.currentTime>0&&a.duration>0;});
  record('real_root_login_and_voice_audition_without_opening_advanced');
  await page.locator('#video-narration').selectOption('off');
  assert(await page.locator('#video-voice').isDisabled());
  assert.equal(await page.locator('#video-voice').inputValue(),'microsoft_xiaoxiao');
  await page.locator('#source').fill(fixture.source);
  await page.locator('.creation-options summary').click();
  await page.locator('#video-duration').selectOption('6');
  await page.locator('#submit').click();
  await page.locator('#retry-video').waitFor({state:'visible',timeout:30000});
  assert.equal(submitted.length,1);
  receipt.failed_job_id=submitted[0];
  let state=await (await context.request.get(fixture.origin+'/_acceptance_state')).json();
  assert.deepEqual(state.wallets,[['a',2000,0],['b',2000,0]]);
  assert.equal(state.jobs[0][2],'FAILED');
  record('worker_failure_refunded_before_real_ui_retry');
  await page.locator('#retry-video').click();
  await page.locator('#video-download[href]').waitFor({state:'visible',timeout:90000});
  assert.equal(submitted.length,2); assert.notEqual(submitted[0],submitted[1]);
  receipt.job_id=submitted[1];
  assert.equal(requests[0].video_voice,'microsoft_xiaoxiao');
  assert.equal(requests[0].video_narration,false);
  assert.equal(requests[0].video_duration_sec,6);
  receipt.request={video_voice:requests[0].video_voice,video_narration:false,video_duration_sec:6};
  const status=await (await context.request.get(fixture.origin+'/api/jobs/'+receipt.job_id)).json();
  assert.equal(status.status,'COMPLETED');
  const artifacts=await (await context.request.get(fixture.origin+'/api/jobs/'+receipt.job_id+'/artifacts')).json();
  assert.equal(artifacts.video.audio,false);
  assert.equal(artifacts.content_status,'NOT_REVIEWED');
  record('selected_voice_and_silent_request_reached_real_job_and_retry');
  assert(progress.some(p=>p.percent>0&&p.percent<100),'Actual polling must expose intermediate server progress');
  receipt.progress=progress;
  record('intermediate_progress_came_from_real_job_polling');
  const player=page.locator('#video-player');
  await player.evaluate(v=>v.play());
  await page.waitForFunction(()=>{const v=document.querySelector('#video-player');return !v.paused&&v.currentTime>.1&&v.videoWidth===1280&&v.videoHeight===720;});
  record('actual_decoded_video_playback');
  const [download]=await Promise.all([page.waitForEvent('download'),page.locator('#video-download').click()]);
  const downloaded=path.join(output,'downloaded.mp4'); await download.saveAs(downloaded);
  const bytes=await fs.readFile(downloaded);
  receipt.download_sha256=createHash('sha256').update(bytes).digest('hex');
  const expected=artifacts.files.find(f=>f.path.endsWith('.mp4'));
  assert.equal(receipt.download_sha256,expected.sha256);
  const url=new URL(await page.locator('#video-download').getAttribute('href'),fixture.origin).href;
  const anonymous=await browser.newContext();
  assert.equal((await anonymous.request.get(url)).status(),401); await anonymous.close();
  const other=await browser.newContext();
  assert.equal((await other.request.get(url,{headers:{Authorization:'Bearer '+fixture.key_b}})).status(),404);
  assert.equal((await other.request.get(fixture.origin+'/api/jobs/'+receipt.job_id,{headers:{Authorization:'Bearer '+fixture.key_b}})).status(),404);
  await other.close();
  const range=await context.request.get(url,{headers:{Range:'bytes=0-1023'}});
  assert.equal(range.status(),206); assert.equal((await range.body()).length,1024);
  record('real_download_hash_range_and_cross_tenant_denial');
  state=await (await context.request.get(fixture.origin+'/_acceptance_state')).json();
  assert.equal(state.wallets.find(x=>x[0]==='a')[2],0);
  assert(state.wallets.find(x=>x[0]==='a')[1]<2000);
  assert.deepEqual(state.wallets.find(x=>x[0]==='b'),['b',2000,0]);
  record('settlement_only_changed_fixture_owner');
  await page.screenshot({path:path.join(output,'workbench.png'),fullPage:true});
  receipt.screenshot_sha256=createHash('sha256').update(await fs.readFile(path.join(output,'workbench.png'))).digest('hex');
  assert.equal(new URL(page.url()).pathname,'/');
  assert.deepEqual(errors,[]);
  receipt.result='PASSED';
  await fs.writeFile(path.join(output,'receipt.json'),JSON.stringify(receipt,null,2));
  console.log('Real workbench acceptance PASSED: '+path.join(output,'receipt.json'));
} catch(error) {
  receipt.result='FAILED'; receipt.error=String(error.message).slice(0,2000);
  await fs.writeFile(path.join(output,'receipt.json'),JSON.stringify(receipt,null,2));
  throw error;
} finally {
  if(context)await context.close(); if(browser)await browser.close();
  lines.close(); server.kill('SIGTERM');
  if(server.exitCode===null)await Promise.race([once(server,'exit'),new Promise(r=>{const t=setTimeout(()=>{server.kill('SIGKILL');r();},5000);t.unref();})]);
  await fs.writeFile(path.join(output,'fixture.log'),logs);
}
